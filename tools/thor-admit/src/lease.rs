//! The lease lock: a file lock the **client** holds.
//!
//! The daemon cannot be the one that holds the lock, or a client that dies
//! would leak its lease forever — the daemon would still think it is running.
//! So the client takes an exclusive `flock(2)` on a per-lease file and keeps
//! the descriptor open for as long as the lease lasts. The kernel drops the
//! lock when the descriptor closes, whatever killed the client.
//!
//! The daemon watches the lease by *trying* to take the same lock: if it gets
//! it, nobody is holding it and the client is gone.

use std::fs::{File, OpenOptions};
use std::io;
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

/// A held lease lock.
#[derive(Debug)]
pub struct LeaseLock {
    /// The descriptor is the whole point: as long as it is open, the kernel
    /// keeps the lock. Nothing reads it.
    #[allow(dead_code)]
    file: File,
    path: PathBuf,
}

impl LeaseLock {
    /// Take the lock, creating the file if it is not there.
    pub fn acquire(path: &Path) -> io::Result<LeaseLock> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        // The lock is ours until the descriptor closes. CLOEXEC matters:
        // the command we run must not inherit it, or the lease would outlive
        // the client. Rust opens every file with O_CLOEXEC already.
        let fd = file.as_raw_fd();
        let rc = unsafe { libc::flock(fd, libc::LOCK_EX) };
        if rc != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(LeaseLock {
            file,
            path: path.to_path_buf(),
        })
    }

    /// The file the lock is on.
    pub fn path(&self) -> &Path {
        &self.path
    }
}

/// Is somebody else holding this lock?
///
/// `Ok(true)` means the lock is held (the client is alive). `Ok(false)` means
/// it is free (the client is gone). The probe uses its own descriptor, so it
/// never disturbs the holder's lock.
pub fn is_held(path: &Path) -> io::Result<bool> {
    let file = match OpenOptions::new().read(true).write(true).open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    let fd = file.as_raw_fd();
    let rc = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
    if rc == 0 {
        // It was free. Put it back the way we found it.
        unsafe { libc::flock(fd, libc::LOCK_UN) };
        return Ok(false);
    }
    let error = io::Error::last_os_error();
    match error.raw_os_error() {
        Some(code) if code == libc::EWOULDBLOCK => Ok(true),
        _ => Err(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_path(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("thor-admit-lock-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_file(&path);
        path
    }

    #[test]
    fn a_lock_we_hold_reads_as_held() {
        let path = temp_path("held");
        let _lock = LeaseLock::acquire(&path).unwrap();
        assert!(is_held(&path).unwrap(), "the lock is held");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_lock_nobody_holds_reads_as_free() {
        let path = temp_path("free");
        assert!(!is_held(&path).unwrap(), "nothing holds it");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn dropping_the_lock_frees_it() {
        let path = temp_path("dropped");
        {
            let _lock = LeaseLock::acquire(&path).unwrap();
            assert!(is_held(&path).unwrap());
        }
        assert!(
            freed_within(&path, std::time::Duration::from_secs(2)),
            "the kernel dropped it"
        );
        let _ = std::fs::remove_file(&path);
    }

    /// Wait for the lock to be free.
    ///
    /// Closing the holder's descriptor releases the flock — unless another
    /// process inherited the descriptor and has not reached its `exec` yet
    /// (a fork that is still starting up holds the open file description
    /// alive, and `O_CLOEXEC` only closes it at the `exec`). That window is
    /// about a millisecond; the daemon polls every 250 ms, so it never
    /// notices. A test that probes once can lose the race, so it waits.
    fn freed_within(path: &Path, within: std::time::Duration) -> bool {
        let deadline = std::time::Instant::now() + within;
        loop {
            if !is_held(path).unwrap_or(false) {
                return true;
            }
            if std::time::Instant::now() >= deadline {
                return false;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }

    #[test]
    fn a_lock_held_by_a_dead_process_is_free() {
        // This is the whole point: a client that dies must not leak a lease.
        let path = temp_path("dead");
        let mut child = std::process::Command::new("sh")
            .arg("-c")
            .arg(format!(
                "exec python3 -c \"import fcntl,time; f=open('{}','w'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); time.sleep(30)\"",
                path.display()
            ))
            .stdout(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        // Wait for the child to say it has the lock.
        use std::io::BufRead;
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        stdout.read_line(&mut line).unwrap();
        assert!(line.contains("locked"), "the child took the lock: {line:?}");
        assert!(is_held(&path).unwrap());

        // Kill it: the kernel must release the lock.
        let _ = child.kill();
        let _ = child.wait();
        let mut released = false;
        for _ in 0..50 {
            if !is_held(&path).unwrap() {
                released = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        assert!(released, "a dead client cannot leak a lease");
        let _ = std::fs::remove_file(&path);
    }
}
