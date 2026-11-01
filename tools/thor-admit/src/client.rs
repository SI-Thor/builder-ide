//! The CLI's side of the protocol.
//!
//! The `run` command is the interesting one: it takes a lease, runs a
//! command under it, and gives the lease back — including when the command
//! is killed, when the client is interrupted, or when the client itself
//! crashes (the kernel drops the lock, and the daemon gives the memory
//! back).

use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;

use serde_json::json;

use crate::lease::LeaseLock;
use crate::ledger::Bucket;
use crate::protocol::{PeakArg, PresenceReport, Request, Response, TargetSpec};
use crate::tier::Tier;

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
    pub fn acquire(
        &mut self,
        label: &str,
        peak: PeakArg,
        priority: i32,
        tier: Tier,
        target: TargetSpec,
        on_queued: &mut dyn FnMut(usize, usize),
    ) -> std::io::Result<Grant> {
        let request = Request::Acquire {
            label: label.to_string(),
            peak,
            priority,
            tier,
            target,
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
                    return Ok(Grant {
                        lease,
                        label,
                        peak_bytes,
                        lock_path: std::path::PathBuf::from(lock_path),
                        floor_bytes,
                        available_bytes,
                    });
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

    /// Say the lock is held, so the daemon treats the lease as real.
    pub fn held(&mut self, lease: u64) -> std::io::Result<()> {
        self.request(&Request::Held { lease })?;
        Ok(())
    }

    /// Give the lease back.
    pub fn release(&mut self, lease: u64, peak_rss_bytes: Option<u64>) -> std::io::Result<()> {
        self.request(&Request::Release {
            lease,
            peak_rss_bytes,
        })?;
        Ok(())
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
        command: Vec<String>,
    ) -> std::io::Result<(u64, String, Tier)> {
        let request = Request::PresenceAdd {
            label: label.to_string(),
            tier,
            peak,
            resumable,
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

/// Run a command under a lease.
///
/// The command is started **after** the lease is granted, so nothing runs
/// before the box has room for it. The child gets its own process group,
/// which is what the watchdog stops if the box runs short.
pub fn run_under_lease(
    client: &mut Client,
    label: &str,
    peak: PeakArg,
    priority: i32,
    tier: Tier,
    command: &[String],
) -> std::io::Result<Outcome> {
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
        // The child: its own process group, then wait for the go-ahead.
        // The go-ahead is one byte: "g" means run. End of file (the parent
        // died, or the lease was refused) means **do not run**: nothing may
        // start without a lease.
        unsafe {
            libc::setpgid(0, 0);
            libc::close(write_fd);
            let mut byte = [0u8; 1];
            let read = libc::read(read_fd, byte.as_mut_ptr() as *mut libc::c_void, 1);
            libc::close(read_fd);
            if read == 1 && byte[0] == b'g' {
                exec_command(command);
            }
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
    let grant = match client.acquire(
        label,
        peak,
        priority,
        tier,
        TargetSpec::Group { pgid },
        &mut |position, waiting| {
            queued_at = Some((position, waiting));
        },
    ) {
        Ok(grant) => grant,
        Err(error) => {
            // No lease, so no run: closing the pipe is the refusal, and the
            // child exits without exec'ing anything.
            unsafe { libc::close(write_fd) };
            let mut status = 0;
            unsafe { libc::waitpid(pid, &mut status, 0) };
            return Err(error);
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

    // Now the command may run.
    unsafe {
        libc::write(write_fd, b"g".as_ptr() as *const libc::c_void, 1);
        libc::close(write_fd);
    }

    let outcome = wait_for(pid)?;
    let _ = client.release(grant.lease, Some(outcome.peak_rss_bytes));
    Ok(outcome)
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
