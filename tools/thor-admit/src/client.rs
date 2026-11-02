//! The CLI's side of the protocol.
//!
//! The `run` command is the interesting one: it takes a lease, runs a
//! command under it, and gives the lease back — including when the command
//! is killed, when the client is interrupted, or when the client itself
//! crashes (the kernel drops the lock, and the daemon gives the memory
//! back).

use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::json;

use crate::boxlock::{self, BoxLock};
use crate::lease::LeaseLock;
use crate::ledger::Bucket;
use crate::protocol::{PeakArg, PresenceReport, Request, Response, TargetSpec};
use crate::tier::Tier;

/// Is this error the daemon's connection going away, as opposed to an
/// answer the daemon gave?
///
/// A refusal arrives *as data*: `Rejected` becomes a `PermissionDenied`
/// error carrying the daemon's own reason, so it is deliberately not in
/// this set. What is in it is the connection-level truth of a daemon that
/// died or was restarted mid-request — the closed connection (EOF), the
/// reset, the refused, the broken pipe.
pub fn is_connection_gone(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        std::io::ErrorKind::UnexpectedEof
            | std::io::ErrorKind::ConnectionReset
            | std::io::ErrorKind::ConnectionAborted
            | std::io::ErrorKind::ConnectionRefused
            | std::io::ErrorKind::BrokenPipe
            | std::io::ErrorKind::NotConnected
    )
}

/// Does a daemon answer on this socket — not just accept the connection?
///
/// A bound socket takes connections into its backlog even when nobody ever
/// `accept`s them, so "connect succeeded" is not "a daemon is there": a
/// daemon wedged between its bind and its acceptor owns a socket that
/// connects fine and answers nothing (round 10, item b). The probe asks it
/// something and gives it two seconds to answer.
pub fn daemon_answers(path: &Path) -> bool {
    let Ok(mut client) = Client::connect(path) else {
        return false;
    };
    let _ = client.writer.set_read_timeout(Some(Duration::from_secs(2)));
    client.ping().unwrap_or(false)
}

/// A connection to the daemon.
pub struct Client {
    writer: UnixStream,
    reader: BufReader<UnixStream>,
}

impl Client {
    /// Connect to the daemon's socket.
    pub fn connect(path: &Path) -> std::io::Result<Client> {
        let stream = UnixStream::connect(path)?;
        let reader = BufReader::new(stream.try_clone()?);
        Ok(Client {
            writer: stream,
            reader,
        })
    }

    /// Send one request and read one answer.
    pub fn request(&mut self, request: &Request) -> std::io::Result<Response> {
        self.send(request)?;
        self.read_response()
    }

    fn send(&mut self, request: &Request) -> std::io::Result<()> {
        let mut text = serde_json::to_string(request).map_err(std::io::Error::other)?;
        text.push('\n');
        self.writer.write_all(text.as_bytes())?;
        self.writer.flush()
    }

    fn read_response(&mut self) -> std::io::Result<Response> {
        let mut line = String::new();
        let read = self.reader.read_line(&mut line)?;
        if read == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "the daemon closed the connection",
            ));
        }
        serde_json::from_str(line.trim()).map_err(std::io::Error::other)
    }

    /// Take a lease. The daemon answers "queued" first (if the box is
    /// busy) and "granted" when the lease is real.
    ///
    /// `coalesce` is the serve registry's key, and only `serve` passes
    /// one: an identical ask already waiting is joined rather than
    /// duplicated, and the answer for a joined asker is
    /// [`Response::Coalesced`] — somebody else's lease is starting the
    /// server, and this client's command must not run.
    pub fn acquire(
        &mut self,
        label: &str,
        peak: PeakArg,
        priority: i32,
        tier: Tier,
        target: TargetSpec,
        coalesce: Option<&str>,
        on_queued: &mut dyn FnMut(usize, usize),
    ) -> std::io::Result<Acquire> {
        let request = Request::Acquire {
            label: label.to_string(),
            peak,
            priority,
            tier,
            target,
            coalesce: coalesce.map(str::to_string),
        };
        self.send(&request)?;
        loop {
            let response = self.read_response()?;
            match response {
                Response::Queued { position, waiting, .. } => {
                    on_queued(position, waiting);
                }
                Response::Granted {
                    lease,
                    label,
                    peak_bytes,
                    lock_path,
                    floor_bytes,
                    available_bytes,
                } => {
                    return Ok(Acquire::Granted(Grant {
                        lease,
                        label,
                        peak_bytes,
                        lock_path: std::path::PathBuf::from(lock_path),
                        floor_bytes,
                        available_bytes,
                    }));
                }
                Response::Coalesced { lease, label } => {
                    return Ok(Acquire::Coalesced { lease, label });
                }
                Response::Rejected { reason } => {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::PermissionDenied,
                        reason,
                    ));
                }
                Response::Error { message } => {
                    return Err(std::io::Error::other(message));
                }
                other => {
                    return Err(std::io::Error::other(format!(
                        "unexpected answer from the daemon: {other:?}"
                    )));
                }
            }
        }
    }

    /// Change a running lease's reservation (`thor-admit phase`): the work
    /// changed phase, and the lease may shrink what it owes — or grow it,
    /// when the box has the room.
    pub fn phase(&mut self, lease: u64, peak: PeakArg) -> std::io::Result<()> {
        match self.request(&Request::Phase { lease, peak })? {
            Response::Ok => Ok(()),
            Response::Rejected { reason } => Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                reason,
            )),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// Say the lock is held, so the daemon treats the lease as real.
    pub fn held(&mut self, lease: u64) -> std::io::Result<()> {
        self.request(&Request::Held { lease })?;
        Ok(())
    }

    /// Say this lease's client is still alive and still working.
    ///
    /// The lock says the client is not *dead*; it cannot say the client is
    /// not *stuck* — a hung client's lock never drops, and its reservation
    /// would be charged forever. The heartbeat is the other half of the
    /// truth, and the daemon gives a silent client a grace period before it
    /// acts (see `--heartbeat-grace-secs`).
    pub fn heartbeat(&mut self, lease: u64) -> std::io::Result<()> {
        self.request(&Request::Heartbeat { lease })?;
        Ok(())
    }

    /// Give the lease back, saying how the run finished. A clean exit
    /// (`Some(0)`) is what lets the daemon learn the run's peak; anything
    /// else — a failure, a kill, or `None`, a client that cannot say —
    /// teaches the history nothing.
    pub fn release(
        &mut self,
        lease: u64,
        peak_rss_bytes: Option<u64>,
        exit_code: Option<i32>,
    ) -> std::io::Result<()> {
        self.request(&Request::Release {
            lease,
            peak_rss_bytes,
            exit_code,
        })?;
        Ok(())
    }

    /// Ask the daemon to re-read its history and its presence queue.
    pub fn reload(&mut self) -> std::io::Result<(usize, usize)> {
        match self.request(&Request::Reload)? {
            Response::Reloaded { peaks, presence } => Ok((peaks, presence)),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// Ask what is going on.
    pub fn status(&mut self) -> std::io::Result<crate::protocol::StatusReport> {
        match self.request(&Request::Status)? {
            Response::Status(report) => Ok(*report),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// Is the daemon alive?
    pub fn ping(&mut self) -> std::io::Result<bool> {
        Ok(matches!(self.request(&Request::Ping)?, Response::Ok))
    }

    /// Register a job in the presence queue.
    pub fn presence_add(
        &mut self,
        label: &str,
        tier: Tier,
        peak: PeakArg,
        resumable: bool,
        enabled: bool,
        command: Vec<String>,
    ) -> std::io::Result<(u64, String, Tier)> {
        let request = Request::PresenceAdd {
            label: label.to_string(),
            tier,
            peak,
            resumable,
            enabled,
            command,
        };
        match self.request(&request)? {
            Response::PresenceAdded { id, label, tier } => Ok((id, label, tier)),
            Response::Rejected { reason } => Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                reason,
            )),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// Take a job out of the presence queue.
    pub fn presence_remove(&mut self, id: u64) -> std::io::Result<bool> {
        match self.request(&Request::PresenceRemove { id })? {
            Response::Ok => Ok(true),
            Response::Rejected { reason } => Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                reason,
            )),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// What is in the presence queue?
    pub fn presence_list(&mut self) -> std::io::Result<Vec<PresenceReport>> {
        match self.request(&Request::PresenceList)? {
            Response::Presence { jobs } => Ok(jobs),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }

    /// The time ledger: the closed hours and the hour being kept now.
    pub fn ledger(&mut self) -> std::io::Result<(Vec<Bucket>, Bucket)> {
        match self.request(&Request::Ledger)? {
            Response::Ledger { buckets, current } => Ok((buckets, *current)),
            other => Err(std::io::Error::other(format!(
                "unexpected answer from the daemon: {other:?}"
            ))),
        }
    }
}

/// A lease that has been granted.
#[derive(Clone, Debug)]
pub struct Grant {
    pub lease: u64,
    pub label: String,
    pub peak_bytes: u64,
    pub lock_path: std::path::PathBuf,
    pub floor_bytes: u64,
    pub available_bytes: u64,
}

/// What an acquire came back with: a lease to run under, or the word that
/// an identical ask is already being served by another client's lease.
#[derive(Clone, Debug)]
pub enum Acquire {
    Granted(Grant),
    /// The ask was coalesced into `lease`: the same server, starting under
    /// somebody else's lease. Nothing should run for this ask.
    Coalesced { lease: u64, label: String },
}

/// What `run_under_lease` leaves behind: the command ran to its end, or an
/// identical serve ask was folded into another client's lease and the
/// command never started.
#[derive(Clone, Copy, Debug)]
pub enum UnderLease {
    Ran(Outcome),
    /// The ask joined a coalescing waiter and the grant went to its leader;
    /// the caller waits for the server by its port instead.
    Coalesced { lease: u64 },
}

/// What a command left behind: its exit code and the peak it reached.
#[derive(Clone, Copy, Debug)]
pub struct Outcome {
    /// The exit code, or 128 + the signal if it was killed.
    pub code: i32,
    /// The signal that killed it, if any.
    pub signal: Option<i32>,
    /// The kernel's own peak RSS for the command, in bytes.
    pub peak_rss_bytes: u64,
}

/// How often a client says it is alive.
pub const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(5);

/// Run a command under a lease.
///
/// The command is started **after** the lease is granted, so nothing runs
/// before the box has room for it. The child gets its own process group,
/// which is what the watchdog stops if the box runs short.
///
/// While the command runs, a heartbeat thread says the client is alive on
/// its own connection, once every [`HEARTBEAT_INTERVAL`]: the lock on the
/// lease file says this client is not dead, and only the heartbeat says it
/// is not *stuck*.
///
/// `revive` is called when the daemon cannot be reached at all — the
/// client's own auto-start (the same one that brought the daemon up before
/// the lease was asked for) brings a new one up. A daemon that goes away
/// while this client is queued or asking does not end the wait: the client
/// reconnects and asks again (round 10, item c), the way the heartbeat
/// already reconnects its own connection.
///
/// `coalesce` is the serve registry's key, and only `serve` passes one: an
/// identical ask already waiting is joined, and when the leader's lease is
/// granted this client's command does not run — the answer is
/// [`UnderLease::Coalesced`], and the server it asked for is starting under
/// the leader's lease.
///
/// When the command does run, it finds `THOR_ADMIT_LEASE` in its
/// environment holding its lease id: a workload that knows its own phases
/// can give memory back mid-run (`thor-admit phase $THOR_ADMIT_LEASE
/// --peak 4G`, round 11) without any outside help.
///
/// `lock` is the box's **legacy** lock (`~/lm-wt/heavy.lock`), and it is
/// taken **after** the lease is granted, never before (round 13). The order
/// is the whole point: a client that waits in the admission queue must hold
/// nothing, or it blocks every other seat that takes the lock while it is
/// not working yet. The lock is taken before the command starts, so the
/// command never runs without it, and it is released when the command ends.
pub fn run_under_lease(
    client: &mut Client,
    socket: &Path,
    label: &str,
    peak: PeakArg,
    priority: i32,
    tier: Tier,
    coalesce: Option<&str>,
    command: &[String],
    lock: Option<&Path>,
    revive: &mut dyn FnMut(),
) -> std::io::Result<UnderLease> {
    // The box's legacy lock, and the order it must be taken in (round 13).
    //
    // A seat that wrote `flock heavy.lock thor-admit run ...` holds the box's
    // lock from the moment it starts — and it holds it for the whole of its
    // wait in the queue. The client repairs that in place: the lock is given
    // back before the lease is asked for, and taken again the moment the
    // lease is granted. The command runs with the lock held; the queue runs
    // without it.
    //
    // Every lock this process inherited is found, not only the box's
    // well-known one: the client cannot know which file the seat meant, and
    // the order is wrong for all of them.
    //
    // This happens before the fork, so the command does not inherit the
    // descriptor: the client is what holds the lock, and the lock ends when
    // the client ends.
    let explicit_lock: Option<PathBuf> = lock.map(Path::to_path_buf);
    let mut inherited: Vec<(std::fs::File, PathBuf)> = Vec::new();
    for (file, path) in boxlock::inherited_locks() {
        eprintln!("thor-admit: {}", boxlock::inherited_lock_advice(&path));
        // Give the lock back now: the queue must not run behind a seat that
        // is waiting for room.
        boxlock::unlock(&file)?;
        inherited.push((file, path));
    }

    // A pipe the child waits on: the command starts when the lease is real.
    let mut fds = [0 as libc::c_int; 2];
    if unsafe { libc::pipe(fds.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let (read_fd, write_fd) = (fds[0], fds[1]);

    let pid = unsafe { libc::fork() };
    if pid < 0 {
        unsafe { libc::close(read_fd) };
        unsafe { libc::close(write_fd) };
        return Err(std::io::Error::last_os_error());
    }
    if pid == 0 {
        // The child: its own process group, then wait for the go-ahead. The
        // go-ahead is the lease id (decimal text) followed by "g"; the id is
        // put into the environment as THOR_ADMIT_LEASE before the exec, so
        // a phasing workload can name its own lease. End of file (the
        // parent died, the lease was refused, or the ask was coalesced)
        // means **do not run**: nothing may start without a lease.
        unsafe {
            libc::setpgid(0, 0);
            libc::close(write_fd);
            let mut seen = [0u8; 32];
            let mut length = 0usize;
            loop {
                let mut byte = [0u8; 1];
                let read = libc::read(read_fd, byte.as_mut_ptr() as *mut libc::c_void, 1);
                if read != 1 {
                    break;
                }
                if byte[0] == b'g' {
                    libc::close(read_fd);
                    if length > 0 {
                        let name = b"THOR_ADMIT_LEASE\0";
                        let value: Vec<u8> = seen[..length]
                            .iter()
                            .copied()
                            .chain(std::iter::once(0))
                            .collect();
                        libc::setenv(
                            name.as_ptr() as *const libc::c_char,
                            value.as_ptr() as *const libc::c_char,
                            1,
                        );
                    }
                    exec_command(command);
                }
                if length < seen.len() {
                    seen[length] = byte[0];
                    length += 1;
                }
            }
            libc::close(read_fd);
            libc::_exit(126);
        }
    }

    // The parent: make sure the process group is set before the daemon
    // reads it (both sides may set it; whoever wins, it is the same).
    unsafe { libc::setpgid(pid, pid) };
    unsafe { libc::close(read_fd) };

    let pgid = pid as i32;
    let asked_at = std::time::Instant::now();
    let mut queued_at: Option<(usize, usize)> = None;
    let acquire = loop {
        match client.acquire(
            label,
            peak,
            priority,
            tier,
            TargetSpec::Group { pgid },
            coalesce,
            &mut |position, waiting| {
                queued_at = Some((position, waiting));
            },
        ) {
            Ok(acquire) => break acquire,
            Err(error) if is_connection_gone(&error) => {
                // The daemon went away while this client was asking or
                // waiting for room — a restart, a crash, an idle exit. The
                // queue it knew went with it, and the wait continues on the
                // next daemon's queue: reconnect, and ask again from the
                // start. A refusal is data, not a disconnection, and it is
                // not retried.
                eprintln!(
                    "thor-admit: the daemon went away while {label:?} was waiting for \
                     room; asking again"
                );
                loop {
                    if let Ok(connection) = Client::connect(socket) {
                        *client = connection;
                        break;
                    }
                    revive();
                    std::thread::sleep(Duration::from_millis(500));
                }
                continue;
            }
            Err(error) => {
                // No lease, so no run: closing the pipe is the refusal, and
                // the child exits without exec'ing anything.
                unsafe { libc::close(write_fd) };
                let mut status = 0;
                unsafe { libc::waitpid(pid, &mut status, 0) };
                return Err(error);
            }
        }
    };

    let grant = match acquire {
        Acquire::Granted(grant) => grant,
        Acquire::Coalesced { lease, label } => {
            // An identical serve ask is already being started under `lease`.
            // This client's command must not run: the pipe closes without a
            // go-ahead and the child exits without exec'ing anything.
            eprintln!(
                "thor-admit: {label:?} was coalesced into lease {lease} — the same server \
                 is starting under another seat's lease; nothing to load here"
            );
            unsafe { libc::close(write_fd) };
            let mut status = 0;
            unsafe { libc::waitpid(pid, &mut status, 0) };
            return Ok(UnderLease::Coalesced { lease });
        }
    };

    let waited = asked_at.elapsed().as_secs_f64();
    // The queue is only worth mentioning when the wait was long enough for
    // the operator to wonder what was going on.
    if waited > 0.5 {
        if let Some((position, waiting)) = queued_at {
            eprintln!(
                "thor-admit: {label:?} waited {waited:.1}s for room (it was {position} of {waiting} in the queue)"
            );
        }
    }
    eprintln!(
        "thor-admit: {label:?} admitted after {waited:.3}s (peak {}, floor {})",
        crate::sizes::human(grant.peak_bytes),
        crate::sizes::human(grant.floor_bytes)
    );

    // The lock is what makes the lease real: the kernel drops it when this
    // process dies, whatever killed it.
    let _lock = LeaseLock::acquire(&grant.lock_path)?;
    client.held(grant.lease)?;

    // The box's legacy lock, taken **now** and not before the lease was
    // granted. A client that took it earlier — `flock heavy.lock thor-admit
    // run ...` — held it for the whole of its wait in the queue, which is
    // the flaw this order fixes. The lease is real now, so the lock can be
    // taken now, and the command starts only once the lock is held.
    let mut box_locks: Vec<BoxLock> = Vec::new();
    if let Some(path) = &explicit_lock {
        // A lock the operator asked for by name. If it was inherited from the
        // shell, it is taken back on the descriptor that already has it;
        // otherwise it is opened and waited for.
        match inherited
            .iter()
            .position(|(_, held)| boxlock::same_file(held, path))
        {
            Some(index) => {
                let (file, _) = inherited.remove(index);
                box_locks.push(BoxLock::adopt(file, path)?);
            }
            None => {
                eprintln!(
                    "thor-admit: {label:?} is admitted; taking the box's lock {}",
                    path.display()
                );
                box_locks.push(BoxLock::acquire(path)?);
            }
        }
    }
    // Any lock that was inherited and given back is taken again now, so the
    // command runs with the lock held, as the seat that wrote the old line
    // expected.
    for (file, path) in inherited.drain(..) {
        eprintln!(
            "thor-admit: {label:?} is admitted; taking the box's lock {} back",
            path.display()
        );
        box_locks.push(BoxLock::adopt(file, &path)?);
    }
    let _box_locks = box_locks;

    // The heartbeat, on its own connection: the main flow below waits on
    // the command and would not notice being asked whether it is alive.
    // The thread is a daemon in the informal sense — it stops of its own
    // accord once the lease is over, and the process's exit takes it with
    // it — and a beat that lands just after the release is answered with a
    // shrug (there is no such lease) and costs nothing.
    let _heartbeat = spawn_heartbeat(socket, grant.lease);

    // Now the command may run, with its lease id in front of the go-ahead.
    {
        let go = format!("{}g", grant.lease);
        unsafe {
            libc::write(
                write_fd,
                go.as_ptr() as *const libc::c_void,
                go.len(),
            );
            libc::close(write_fd);
        }
    }

    let outcome = wait_for(pid)?;
    let _ = client.release(grant.lease, Some(outcome.peak_rss_bytes), Some(outcome.code));
    Ok(UnderLease::Ran(outcome))
}

/// The thread that says this lease's client is alive, every five seconds,
/// until the process ends.
fn spawn_heartbeat(socket: &Path, lease: u64) -> std::thread::JoinHandle<()> {
    let socket = socket.to_path_buf();
    std::thread::Builder::new()
        .name("thor-admit-heartbeat".to_string())
        .spawn(move || {
            let mut connection: Option<Client> = None;
            loop {
                std::thread::sleep(HEARTBEAT_INTERVAL);
                // The lease may already be over; a beat for a released
                // lease is answered and ignored, and the thread ends with
                // the process. A new connection each time it breaks: the
                // daemon may have been restarted.
                if connection.is_none() {
                    connection = Client::connect(&socket).ok();
                }
                let Some(alive) = connection.as_mut() else {
                    continue;
                };
                if alive.heartbeat(lease).is_err() {
                    connection = None;
                }
            }
        })
        .expect("the heartbeat thread starts")
}

/// Wait for the command, and read the kernel's own peak for it.
fn wait_for(pid: libc::pid_t) -> std::io::Result<Outcome> {
    let mut status: libc::c_int = 0;
    let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
    let waited = unsafe { libc::wait4(pid, &mut status, 0, &mut usage) };
    if waited < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let peak_rss_bytes = (usage.ru_maxrss as u64).saturating_mul(1024);
    if libc::WIFEXITED(status) {
        let code = libc::WEXITSTATUS(status);
        Ok(Outcome {
            code,
            signal: None,
            peak_rss_bytes,
        })
    } else if libc::WIFSIGNALED(status) {
        let signal = libc::WTERMSIG(status);
        Ok(Outcome {
            code: 128 + signal,
            signal: Some(signal),
            peak_rss_bytes,
        })
    } else {
        Ok(Outcome {
            code: 128,
            signal: None,
            peak_rss_bytes,
        })
    }
}

/// Run a command **in place of this process**, and never come back.
///
/// `thor-admit exec` uses it: the command takes the terminal's process, its
/// signals and its exit code, so a program that reads the keyboard or traps
/// `SIGINT` behaves exactly as it would without the wrapper. It never
/// returns — the only way out is the command's own exit.
pub fn exec_now(command: &[String]) -> ! {
    if command.is_empty() {
        eprintln!("thor-admit: exec needs a command");
        unsafe { libc::_exit(2) };
    }
    exec_command(command)
}

/// `execvp` the command. Only called in the forked child; it never returns.
fn exec_command(command: &[String]) -> ! {
    let program = std::ffi::CString::new(command[0].clone()).unwrap_or_default();
    let argv: Vec<std::ffi::CString> = command
        .iter()
        .map(|part| std::ffi::CString::new(part.clone()).unwrap_or_default())
        .collect();
    let mut pointers: Vec<*const libc::c_char> = argv.iter().map(|part| part.as_ptr()).collect();
    pointers.push(std::ptr::null());
    unsafe { libc::execvp(program.as_ptr(), pointers.as_ptr()) };
    // Only reached when the command cannot be run.
    let message = format!(
        "thor-admit: cannot run {}: {}\n",
        command.first().map(String::as_str).unwrap_or(""),
        std::io::Error::last_os_error()
    );
    unsafe {
        libc::write(2, message.as_ptr() as *const libc::c_void, message.len());
        libc::_exit(127);
    }
}

/// Ask the daemon to stop.
pub fn stop_daemon(path: &Path) -> std::io::Result<()> {
    let mut client = Client::connect(path)?;
    client.ping()?;
    // The daemon stops on SIGTERM; the CLI cannot send one across a socket,
    // so the daemon is asked through its own pid file.
    let pid_file = path.with_extension("pid");
    let pid: i32 = std::fs::read_to_string(&pid_file)
        .ok()
        .and_then(|text| text.trim().parse().ok())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("no pid file at {}", pid_file.display()),
            )
        })?;
    let signalled = unsafe { libc::kill(pid, libc::SIGTERM) == 0 };
    if !signalled {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

/// A small JSON helper for the CLI's output.
pub fn json_line(value: &serde_json::Value) -> String {
    serde_json::to_string(value).unwrap_or_default()
}

/// Read a whole stream (used by the tests and by `status --raw`).
pub fn read_all(mut stream: impl Read) -> std::io::Result<String> {
    let mut text = String::new();
    stream.read_to_string(&mut text)?;
    Ok(text)
}

/// The JSON the CLI prints when it cannot reach the daemon.
pub fn unreachable_json(path: &Path, error: &std::io::Error) -> serde_json::Value {
    json!({"error": error.to_string(), "socket": path.display().to_string()})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_daemons_death_is_a_connection_gone() {
        // What a client actually sees when the daemon dies mid-request: the
        // closed connection, or the reset; and what it sees asking a socket
        // nobody is bound to: refused.
        assert!(is_connection_gone(&std::io::Error::new(
            std::io::ErrorKind::UnexpectedEof,
            "the daemon closed the connection"
        )));
        assert!(is_connection_gone(&std::io::Error::from(
            std::io::ErrorKind::ConnectionReset
        )));
        assert!(is_connection_gone(&std::io::Error::from(
            std::io::ErrorKind::ConnectionRefused
        )));
        assert!(is_connection_gone(&std::io::Error::from(
            std::io::ErrorKind::BrokenPipe
        )));
    }

    #[test]
    fn the_daemons_answer_is_not_a_connection_gone() {
        // A refusal is data — the daemon's own reason — so it must not be
        // retried as though the daemon had died.
        assert!(!is_connection_gone(&std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "no history for the label"
        )));
        assert!(!is_connection_gone(&std::io::Error::other(
            "unexpected answer from the daemon"
        )));
    }
}
