//! The box's **legacy lock**: `~/lm-wt/heavy.lock`.
//!
//! ## What the lock is, and what it was for
//!
//! Before the daemon existed, every seat that ran heavy work took the same
//! file lock, so two seats could not run heavy work at once. The lock is the
//! box's oldest mutual-exclusion device and it is still in use: seats that
//! have not migrated to leases still take it, and the crate's own integration
//! tests take it so a test cannot collide with a seat.
//!
//! ## The flaw it has, and why the order matters
//!
//! The lock was taken **around** the whole command, and the daemon's lease is
//! taken **inside** it:
//!
//! ```text
//! flock ~/lm-wt/heavy.lock thor-admit run --peak 8G --label build -- nvcc ...
//! \_____ the lock ____/ \______________ the lease ______________/
//! ```
//!
//! So a seat that waits in the admission queue holds the box's lock for the
//! whole wait. That is the wrong order for two reasons, and both of them
//! were seen on this box on 2026-11-01:
//!
//! 1. **The wait can be long.** The queue is FIFO with priorities, and a
//!    request that does not fit waits for the ones ahead of it. A seat that
//!    waited 3 003 s for an 8 GiB lease on a box with 77 GiB free was
//!    holding the box's lock for all of it.
//! 2. **A queued seat blocks the box, not just the other seats.** The lock is
//!    the only thing a seat that has *not* migrated to leases knows about, so
//!    it is what keeps the box's own work from starting. A seat that is
//!    waiting for memory must not be holding the thing that says "the box is
//!    busy".
//!
//! The rule this module exists to make possible: **the lease comes first, and
//! the lock only once the lease is granted.** The lease is the daemon's
//! promise about memory; the lock is the old mutual exclusion between seats.
//! Taking them in that order means a queued seat holds nothing, and a running
//! seat holds both.
//!
//! ## How a lock is recognised
//!
//! The kernel knows who holds a `flock(2)`, and it writes it down:
//! `/proc/locks` lists every lock on the box with the pid that took it and
//! the device and inode of the file. But the pid is **not** the way to find
//! the lock this process inherited: `flock(1)` **forks** — the parent takes
//! the lock and the child runs the command — so the kernel's record names
//! the parent, which is not this process.
//!
//! So the test is on the descriptor:
//!
//! 1. the file is flock-locked on the box (`/proc/locks` names it), and
//! 2. this process can take the lock on its own descriptor **without
//!    waiting** — which is true only when the lock is held by *this* open
//!    file description. `flock(2)` on a description that already holds the
//!    lock is a no-op; a lock held by a *different* description blocks even
//!    in the same process.
//!
//! The descriptor is inherited, so it is the same open file description the
//! parent took the lock on: releasing it releases the parent's lock too, and
//! taking it again restores the exclusion the seat asked for.

use std::fs::{File, OpenOptions};
use std::io;
use std::os::unix::io::{AsRawFd, FromRawFd, RawFd};
use std::path::{Path, PathBuf};

/// The box's legacy lock: `~/lm-wt/heavy.lock`.
///
/// This is the path every seat used before the daemon, and the one the
/// director's briefs point at. It is the *fallback* now: the daemon is what
/// orders the box, and the lock only matters to a seat that has not migrated.
pub fn default_lock_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join("lm-wt/heavy.lock")
}

/// A held box lock.
///
/// The descriptor is the whole point: the kernel drops the lock when it
/// closes, whatever killed the holder. Nothing has to be cleaned up by hand.
#[derive(Debug)]
pub struct BoxLock {
    #[allow(dead_code)]
    file: File,
    path: PathBuf,
}

impl BoxLock {
    /// Take the lock, creating the file if it is not there.
    ///
    /// This blocks until the lock is free. The caller must take it **after**
    /// the lease is granted — see the module's own note on the order.
    pub fn acquire(path: &Path) -> io::Result<BoxLock> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        // CLOEXEC: the command must not inherit the descriptor, or the lock
        // would outlive the client that took it. Rust opens every file with
        // O_CLOEXEC already.
        let fd = file.as_raw_fd();
        let rc = unsafe { libc::flock(fd, libc::LOCK_EX) };
        if rc != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(BoxLock {
            file,
            path: path.to_path_buf(),
        })
    }

    /// Take the lock on a descriptor this process already has open.
    ///
    /// This is the repair path: the descriptor came from the shell that
    /// started this client (`flock heavy.lock thor-admit run ...`), so the
    /// lock was taken **before** the lease. The client releases it while it
    /// waits for room and takes it back here, once the lease is granted.
    pub fn adopt(file: File, path: &Path) -> io::Result<BoxLock> {
        let fd = file.as_raw_fd();
        let rc = unsafe { libc::flock(fd, libc::LOCK_EX) };
        if rc != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(BoxLock {
            file,
            path: path.to_path_buf(),
        })
    }

    /// Give the lock back without closing the descriptor.
    ///
    /// The lock is a property of the open file description, so `LOCK_UN`
    /// frees it for every process that shares the descriptor — which is
    /// what "release it while the lease waits" means.
    pub fn release(&self) -> io::Result<()> {
        let rc = unsafe { libc::flock(self.file.as_raw_fd(), libc::LOCK_UN) };
        if rc != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    /// Let the command that replaces this process inherit the lock.
    ///
    /// `thor-admit exec` runs the command **in place of** the client: the
    /// command takes the process, its signals and its exit code. The
    /// descriptor Rust opens carries `O_CLOEXEC`, so the lock would be
    /// dropped by the `exec` and the command would run *without* it. This
    /// clears the flag, so the command holds the lock for as long as it
    /// runs — which is what `exec --lock` means.
    pub fn clear_close_on_exec(&self) -> io::Result<()> {
        let fd = self.file.as_raw_fd();
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags < 0 {
            return Err(io::Error::last_os_error());
        }
        // Every descriptor Rust opens carries FD_CLOEXEC, which the kernel
        // turns into a close at the next exec. Unset it so the lock survives
        // into the command.
        if unsafe { libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    /// The file the lock is on.
    pub fn path(&self) -> &Path {
        &self.path
    }
}

/// Who holds the box's lock, according to the kernel.
///
/// `Ok(Some(pid))` — the pid that took the lock. `Ok(None)` — the lock is
/// free, or the file is not there. `Err` — `/proc/locks` could not be read,
/// which is a real error and not an answer of "free": a caller that treats
/// an unreadable `/proc/locks` as "nobody holds it" would take a lock that
/// somebody holds.
pub fn holder(path: &Path) -> io::Result<Option<i32>> {
    let metadata = match std::fs::metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    use std::os::unix::fs::MetadataExt;
    let device = metadata.dev();
    let inode = metadata.ino();
    let wanted = format!(
        "{:02x}:{:02x}:{}",
        libc::major(device),
        libc::minor(device),
        inode
    );
    let locks = match std::fs::read_to_string("/proc/locks") {
        Ok(text) => text,
        Err(error) => return Err(error),
    };
    for line in locks.lines() {
        let fields: Vec<&str> = line.split_whitespace().collect();
        // "1: FLOCK ADVISORY WRITE 1234 00:1a:1234567 0 EOF"
        if fields.len() < 6 {
            continue;
        }
        if fields[1] != "FLOCK" {
            // A POSIX lock is a different mechanism; the box's lock is a
            // flock, and only a flock is answered by flock(2).
            continue;
        }
        if fields[5] != wanted {
            continue;
        }
        if let Ok(pid) = fields[4].parse::<i32>() {
            return Ok(Some(pid));
        }
    }
    Ok(None)
}

/// Is the lock held by this process?
///
/// This is the "the seat inherited the lock" test for the common case where
/// the lock was taken by this process itself.
pub fn held_by_us(path: &Path, pid: i32) -> bool {
    matches!(holder(path), Ok(Some(holder)) if holder == pid)
}

/// The command line of a process, as the kernel has it.
///
/// Used to say *who* holds the lock in one line of `status`: the pid alone
/// does not say whether the holder is a seat that has migrated to leases or
/// one that has not.
pub fn command_line(pid: i32) -> Option<String> {
    let raw = std::fs::read(format!("/proc/{pid}/cmdline")).ok()?;
    let text = String::from_utf8_lossy(&raw)
        .replace('\0', " ")
        .trim()
        .to_string();
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

/// Give the lock back on a descriptor, without closing it.
///
/// The lock is a property of the open file description, so `LOCK_UN` frees it
/// for every process that shares the descriptor — which is what "release it
/// while the lease waits" means.
pub fn unlock(file: &File) -> io::Result<()> {
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_UN) };
    if rc != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

/// **Every** lock this process inherited through its exec.
///
/// A client is a fresh process: it was exec'd, and whatever `flock(2)` locks
/// it holds were taken by the shell that started it. Those are exactly the
/// locks that must not be held while the client waits for room, and the
/// client cannot know which file the seat meant — so it finds them all.
///
/// **The limit of this:** a lock taken by a process that did not pass the
/// descriptor down cannot be found, because this process has no descriptor
/// for it.
pub fn inherited_locks() -> Vec<(File, PathBuf)> {
    let locked = flocked_files();
    if locked.is_empty() {
        return Vec::new();
    }
    let mut found: Vec<(File, PathBuf)> = Vec::new();
    let entries = match std::fs::read_dir("/proc/self/fd") {
        Ok(entries) => entries,
        Err(_) => return found,
    };
    for entry in entries.flatten() {
        let Some(name) = entry.file_name().to_str().map(str::to_string) else {
            continue;
        };
        let Ok(number) = name.parse::<RawFd>() else {
            continue;
        };
        let mut stat: libc::stat = unsafe { std::mem::zeroed() };
        let rc = unsafe { libc::fstat(number, &mut stat) };
        if rc != 0 {
            continue;
        }
        if !locked.contains(&(stat.st_dev, stat.st_ino)) {
            continue;
        }
        // The file is locked. Is it locked by *this* description? Taking it
        // without waiting succeeds only then.
        let rc = unsafe { libc::flock(number, libc::LOCK_EX | libc::LOCK_NB) };
        if rc != 0 {
            // Somebody else's description holds it: leave it alone.
            continue;
        }
        let path = std::fs::read_link(format!("/proc/self/fd/{number}"))
            .unwrap_or_else(|_| PathBuf::from("<unknown>"));
        // The descriptor is **copied**, not adopted: the descriptor belongs
        // to whoever opened it (the shell's `flock(1)`, or this process
        // itself), and taking ownership of it would close a file that
        // something else still owns. A copy shares the open file
        // description, so the lock is the same lock.
        let Some(file) = duplicate(number) else {
            continue;
        };
        // The command must not inherit the lock: the client is what holds
        // it, and the lock must end when the client ends.
        set_close_on_exec(number);
        found.push((file, path));
    }
    found
}

/// A copy of a descriptor, sharing its open file description.
///
/// `dup(2)`: the copy is a new descriptor onto the *same* open file
/// description, so a `flock(2)` on it is the same lock — and closing it does
/// not close the original.
fn duplicate(number: RawFd) -> Option<File> {
    let copy = unsafe { libc::dup(number) };
    if copy < 0 {
        return None;
    }
    Some(unsafe { File::from_raw_fd(copy) })
}

/// Mark a descriptor so that it does not survive an `exec`.
fn set_close_on_exec(number: RawFd) {
    let flags = unsafe { libc::fcntl(number, libc::F_GETFD) };
    if flags >= 0 {
        unsafe { libc::fcntl(number, libc::F_SETFD, flags | libc::FD_CLOEXEC) };
    }
}

/// Every file on the box that is flock-locked, by device and inode.
fn flocked_files() -> Vec<(u64, u64)> {
    let mut locked: Vec<(u64, u64)> = Vec::new();
    let Ok(text) = std::fs::read_to_string("/proc/locks") else {
        return locked;
    };
    for line in text.lines() {
        let fields: Vec<&str> = line.split_whitespace().collect();
        // "1: FLOCK ADVISORY WRITE 1234 00:1a:1234567 0 EOF"
        if fields.len() < 6 || fields[1] != "FLOCK" {
            continue;
        }
        if let Some((device, inode)) = parse_device_inode(fields[5]) {
            locked.push((device, inode));
        }
    }
    locked
}

/// The descriptor this process holds a flock on, for one named file.
///
/// The same test as [`inherited_locks`], for one path: the file is
/// flock-locked, and this process can take it on its own descriptor without
/// waiting.
pub fn inherited_lock(path: &Path) -> Option<(File, PathBuf)> {
    use std::os::unix::fs::MetadataExt;
    let metadata = std::fs::metadata(path).ok()?;
    let wanted = (metadata.dev(), metadata.ino());
    if !flocked_files().contains(&wanted) {
        return None;
    }
    let entries = std::fs::read_dir("/proc/self/fd").ok()?;
    for entry in entries.flatten() {
        let Some(name) = entry.file_name().to_str().map(str::to_string) else {
            continue;
        };
        let Ok(number) = name.parse::<RawFd>() else {
            continue;
        };
        let mut stat: libc::stat = unsafe { std::mem::zeroed() };
        let rc = unsafe { libc::fstat(number, &mut stat) };
        if rc != 0 {
            continue;
        }
        if (stat.st_dev, stat.st_ino) != wanted {
            continue;
        }
        let rc = unsafe { libc::flock(number, libc::LOCK_EX | libc::LOCK_NB) };
        if rc != 0 {
            return None;
        }
        let file = duplicate(number)?;
        set_close_on_exec(number);
        return Some((file, path.to_path_buf()));
    }
    None
}

/// Are these two paths the same file?
///
/// Compared by device and inode, not by name: the kernel's record of a lock
/// gives the inode, and a seat may name the same file in a different way
/// (relative, or through a symlink).
pub fn same_file(left: &Path, right: &Path) -> bool {
    use std::os::unix::fs::MetadataExt;
    let (Ok(a), Ok(b)) = (std::fs::metadata(left), std::fs::metadata(right)) else {
        return false;
    };
    a.dev() == b.dev() && a.ino() == b.ino()
}

/// The device and inode in a `/proc/locks` file field: `00:1a:1234567`.
fn parse_device_inode(field: &str) -> Option<(u64, u64)> {
    let mut parts = field.split(':');
    let major = u64::from_str_radix(parts.next()?, 16).ok()?;
    let minor = u64::from_str_radix(parts.next()?, 16).ok()?;
    let inode = parts.next()?.parse::<u64>().ok()?;
    // The kernel prints the device as major:minor; the device number the
    // stat gives is that pair packed back together.
    let device = libc::makedev(major as libc::c_uint, minor as libc::c_uint) as u64;
    Some((device, inode))
}

/// The advice the client gives when it finds the lock held before the lease.
///
/// The words matter here: a seat that wrote `flock ... thor-admit run ...`
/// from an older brief is not doing anything wrong on purpose — the rule it
/// followed was the rule at the time. So the message says what the client is
/// doing about it (the lock is given back now and taken again when the lease
/// is granted), what it costs, and gives the line that needs no repair.
pub fn inherited_lock_advice(path: &Path) -> String {
    let path = path.display();
    format!(
        "this process already holds {path} — the box's lock was taken before the lease.\n\
         what that costs: a lease that is still waiting for room holds the lock the whole \
         time it waits, so every seat that uses the lock waits behind a seat that is not \
         working yet.\n\
         what this client does about it: the lock is given back now, and taken again the \
         moment the lease is granted, so the command runs with the lock held and the queue \
         runs without it.\n\
         to make it permanent, write it the other way round — the lease first, the lock \
         only once the lease is granted:\n\
         \x20   thor-admit run --lock {path} --peak <size> --label <name> -- <command>"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_path(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("thor-admit-boxlock-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_file(&path);
        path
    }

    #[test]
    fn a_free_lock_has_no_holder() {
        let path = temp_path("free");
        assert_eq!(holder(&path).unwrap(), None, "nothing holds it");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_lock_we_hold_names_us_as_the_holder() {
        let path = temp_path("ours");
        let _lock = BoxLock::acquire(&path).unwrap();
        assert_eq!(
            holder(&path).unwrap(),
            Some(std::process::id() as i32),
            "the kernel's record names the pid that took the lock"
        );
        assert!(
            held_by_us(&path, std::process::id() as i32),
            "and that pid is us"
        );
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_lock_another_process_holds_names_that_process() {
        let path = temp_path("theirs");
        let mut child = std::process::Command::new("sh")
            .arg("-c")
            .arg(format!(
                "exec python3 -c \"import fcntl,time; f=open('{}','w'); fcntl.flock(f,fcntl.LOCK_EX); \
                 print('locked',flush=True); time.sleep(30)\"",
                path.display()
            ))
            .stdout(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        use std::io::BufRead;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        stdout.read_line(&mut line).unwrap();
        assert!(line.contains("locked"), "the child took the lock: {line:?}");

        assert_eq!(
            holder(&path).unwrap(),
            Some(child.id() as i32),
            "the holder is the child, not us"
        );
        assert!(
            !held_by_us(&path, std::process::id() as i32),
            "and it is not us"
        );

        let _ = child.kill();
        let _ = child.wait();
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn dropping_the_lock_frees_it() {
        let path = temp_path("dropped");
        {
            let _lock = BoxLock::acquire(&path).unwrap();
            assert!(held_by_us(&path, std::process::id() as i32));
        }
        assert_eq!(holder(&path).unwrap(), None, "the kernel dropped it");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_lock_this_process_holds_is_found_as_inherited() {
        // The client's own view of a lock it holds: the file is flock-locked
        // and this process can take it on its own descriptor without
        // waiting.
        let path = temp_path("inherited");
        let _lock = BoxLock::acquire(&path).unwrap();
        let found = inherited_lock(&path);
        assert!(found.is_some(), "the lock this process holds is not found");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_lock_another_process_holds_is_not_ours() {
        let path = temp_path("not-ours");
        let mut child = std::process::Command::new("sh")
            .arg("-c")
            .arg(format!(
                "exec python3 -c \"import fcntl,time; f=open('{}','w'); fcntl.flock(f,fcntl.LOCK_EX); \
                 print('locked',flush=True); time.sleep(30)\"",
                path.display()
            ))
            .stdout(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        use std::io::BufRead;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        stdout.read_line(&mut line).unwrap();
        assert!(line.contains("locked"), "the child took the lock: {line:?}");

        assert!(
            inherited_lock(&path).is_none(),
            "a lock another process holds is not this process's"
        );

        let _ = child.kill();
        let _ = child.wait();
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn the_advice_names_the_lock_and_the_order() {
        let path = Path::new("/home/someone/lm-wt/heavy.lock");
        let advice = inherited_lock_advice(path);
        assert!(advice.contains("--lock"), "it gives the line to write: {advice}");
        assert!(
            advice.contains("was taken before the lease"),
            "it names the order: {advice}"
        );
        assert!(
            advice.contains("taken again the moment the lease is granted"),
            "it says what the client does about it: {advice}"
        );
    }
}
