//! The integration run: synthetic memory hogs on the real box.
//!
//! These tests use the CPU only (no CUDA) and take the box's own stopgap
//! lock (`~/lm-wt/heavy.lock`) while they run, so they cannot collide with
//! another seat's heavy work. Every hog is capped, and the total memory in
//! use stays under 60 GiB.
//!
//! The box state is measured, not assumed: the tests read `/proc/meminfo`
//! and `/proc/vmstat` while they run, and the numbers they assert on are
//! the numbers the kernel reported.

use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;

const BIN: &str = env!("CARGO_BIN_EXE_thor-admit");
const HOG: &str = env!("CARGO_BIN_EXE_thor-admit-hog");

/// A GiB.
const GIB: u64 = 1024 * 1024 * 1024;

/// The box's stopgap lock: the one every seat takes for heavy work today.
fn heavy_lock_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join("lm-wt/heavy.lock")
}

/// The box's stopgap lock, and what a heavy test may do about it.
enum Gate {
    /// Skip the test: another seat is working and the wait was not allowed.
    Skip,
    /// Run the test. The file is the lock, when it could be taken.
    Run(Option<std::fs::File>),
}

impl Gate {
    /// Take the box's stopgap lock, so the test does not collide with a seat.
    ///
    /// The heavy tests wait for it: the box's queue of seats is exactly the
    /// contention this daemon is meant to replace.
    /// `THOR_ADMIT_HEAVY_WAIT_SECS` says how long to wait (zero skips the
    /// test); `THOR_ADMIT_SKIP_HEAVY_LOCK=1` runs the test without it, which
    /// is only for a small, bounded demonstration.
    fn take() -> Gate {
        use std::os::unix::io::AsRawFd;
        if std::env::var("THOR_ADMIT_SKIP_HEAVY_LOCK").as_deref() == Ok("1") {
            eprintln!(
                "WARNING: running without the box's heavy lock — only for a small, \
                 bounded demonstration"
            );
            return Gate::Run(None);
        }
        let path = heavy_lock_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let file = match std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
        {
            Ok(file) => file,
            Err(_) => return Gate::Skip,
        };
        let fd = file.as_raw_fd();
        let wait: u64 = std::env::var("THOR_ADMIT_HEAVY_WAIT_SECS")
            .ok()
            .and_then(|text| text.parse().ok())
            .unwrap_or(0);
        let deadline = Instant::now() + Duration::from_secs(wait);
        loop {
            // Non-blocking first: if another seat is working, this test
            // steps aside rather than fighting for the box.
            let rc = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
            if rc == 0 {
                return Gate::Run(Some(file));
            }
            if Instant::now() >= deadline {
                return Gate::Skip;
            }
            eprintln!("waiting for the box's heavy lock...");
            std::thread::sleep(Duration::from_secs(5));
        }
    }
}

/// A daemon under test.
struct DaemonUnderTest {
    child: Child,
    socket: PathBuf,
    state_dir: PathBuf,
}

impl DaemonUnderTest {
    fn start(extra: &[&str]) -> DaemonUnderTest {
        let mut state_dir = std::env::temp_dir();
        state_dir.push(format!(
            "thor-admit-it-{}-{}",
            std::process::id(),
            extra.join("_").replace(['/', ' '], "-")
        ));
        let _ = std::fs::remove_dir_all(&state_dir);
        std::fs::create_dir_all(&state_dir).unwrap();
        let socket = state_dir.join("sock");
        let mut command = Command::new(BIN);
        command
            .arg("daemon")
            .arg("--socket")
            .arg(&socket)
            .arg("--state-dir")
            .arg(&state_dir)
            .arg("--idle-exit")
            .arg("600")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for argument in extra {
            command.arg(argument);
        }
        let child = command.spawn().expect("the daemon starts");
        let daemon = DaemonUnderTest {
            child,
            socket,
            state_dir,
        };
        daemon.wait_for_socket();
        daemon
    }

    fn wait_for_socket(&self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline {
            if self.socket.exists() && std::os::unix::net::UnixStream::connect(&self.socket).is_ok() {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        panic!("the daemon did not come up on {}", self.socket.display());
    }

    fn status(&self) -> Value {
        let output = Command::new(BIN)
            .arg("status")
            .arg("--socket")
            .arg(&self.socket)
            .arg("--json")
            .output()
            .expect("the status runs");
        serde_json::from_slice(&output.stdout).expect("the status is JSON")
    }

    fn log(&self) -> String {
        std::fs::read_to_string(self.state_dir.join("daemon.log")).unwrap_or_default()
    }

    fn history(&self) -> Vec<Value> {
        let text =
            std::fs::read_to_string(self.state_dir.join("peaks.jsonl")).unwrap_or_default();
        text.lines()
            .filter(|line| !line.trim().is_empty())
            .filter_map(|line| serde_json::from_str(line).ok())
            .collect()
    }
}

impl Drop for DaemonUnderTest {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_dir_all(&self.state_dir);
    }
}

/// `MemAvailable`, in bytes, as the kernel sees it right now.
fn mem_available() -> u64 {
    let text = std::fs::read_to_string("/proc/meminfo").unwrap();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("MemAvailable:") {
            let kb: u64 = rest.split_whitespace().next().unwrap().parse().unwrap();
            return kb * 1024;
        }
    }
    0
}

/// The number of times the kernel's OOM killer has fired.
fn oom_kills() -> u64 {
    let text = std::fs::read_to_string("/proc/vmstat").unwrap_or_default();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("oom_kill ") {
            return rest.trim().parse().unwrap_or(0);
        }
    }
    0
}

/// The resident set of a process, in bytes.
fn rss_of(pid: u32) -> u64 {
    let text = std::fs::read_to_string(format!("/proc/{pid}/status")).unwrap_or_default();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("VmRSS:") {
            let kb: u64 = rest.split_whitespace().next().unwrap_or("0").parse().unwrap_or(0);
            return kb * 1024;
        }
    }
    0
}

/// The CPU time a process has used, in seconds.
fn cpu_seconds(pid: u32) -> f64 {
    let text = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap_or_default();
    let close = text.rfind(')').unwrap_or(0);
    let fields: Vec<&str> = text[close + 1..].split_whitespace().collect();
    let utime: f64 = fields.get(11).and_then(|v| v.parse().ok()).unwrap_or(0.0);
    let stime: f64 = fields.get(12).and_then(|v| v.parse().ok()).unwrap_or(0.0);
    // The kernel counts in clock ticks; the Thor runs at 100 Hz.
    (utime + stime) / 100.0
}

/// Run a command under a lease and wait for it.
fn leased(daemon: &DaemonUnderTest, label: &str, peak: &str, command: &[&str]) -> Child {
    leased_with_priority(daemon, label, peak, 0, command)
}

/// Run a command under a lease with a priority.
fn leased_with_priority(
    daemon: &DaemonUnderTest,
    label: &str,
    peak: &str,
    priority: i32,
    command: &[&str],
) -> Child {
    Command::new(BIN)
        .arg("run")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--peak")
        .arg(peak)
        .arg("--label")
        .arg(label)
        .arg("--priority")
        .arg(priority.to_string())
        .arg("--")
        .args(command)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the lease starts")
}

/// Read a child's output after it finishes.
fn output_of(child: &mut Child) -> String {
    let mut text = String::new();
    if let Some(mut stdout) = child.stdout.take() {
        let _ = stdout.read_to_string(&mut text);
    }
    let mut errors = String::new();
    if let Some(mut stderr) = child.stderr.take() {
        let _ = stderr.read_to_string(&mut errors);
    }
    text.push_str(&errors);
    text
}

/// How big a hog the heavy tests use. The brief's scale is 30 GiB; a
/// smaller one is for a box that is already busy.
fn hog_gb() -> u64 {
    std::env::var("THOR_ADMIT_HOG_GB")
        .ok()
        .and_then(|text| text.parse().ok())
        .unwrap_or(30)
}

/// The floor that lets exactly one hog run at a time.
///
/// The box has `available` free; a hog of `hog` GiB must fit while a second
/// one must not. The floor is set from the box's own headroom with a
/// margin, so the test does not depend on the exact number of gigabytes
/// free at that moment.
fn floor_for_one_hog(hog_bytes: u64) -> u64 {
    let available = mem_available();
    let margin = 8 * GIB;
    available
        .saturating_sub(hog_bytes)
        .saturating_sub(margin)
        .max(GIB)
}

#[test]
fn three_thirty_gigabyte_hogs_are_serialised() {
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
    let hog_gb = hog_gb();
    let hog_bytes = hog_gb * GIB;
    // A floor of (available - hog - 8 GiB) means one hog fits and a second
    // one does not: the daemon charges the running hog's reservation, so
    // the second hog is refused while the first is still growing.
    let floor = floor_for_one_hog(hog_bytes);
    let daemon = DaemonUnderTest::start(&[
        "--floor",
        &format!("{}", floor),
    ]);

    let mut hogs = Vec::new();
    for index in 0..3 {
        hogs.push(leased(
            &daemon,
            &format!("hog{index}"),
            &format!("{hog_gb}G"),
            &[HOG, "--bytes", &format!("{hog_gb}G"), "--hold", "4"],
        ));
    }

    // Watch the box while they run.
    let mut max_active = 0usize;
    let mut min_available = u64::MAX;
    let deadline = Instant::now() + Duration::from_secs(60);
    while Instant::now() < deadline {
        let status = daemon.status();
        let active = status["leases"].as_array().map(|a| a.len()).unwrap_or(0);
        max_active = max_active.max(active);
        min_available = min_available.min(mem_available());
        let mut running = 0;
        for child in hogs.iter_mut() {
            if child.try_wait().ok().flatten().is_none() {
                running += 1;
            }
        }
        if running == 0 && active == 0 {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    let mut finished = Vec::new();
    for mut hog in hogs {
        let _ = hog.wait();
        finished.push(output_of(&mut hog));
    }

    assert_eq!(
        max_active, 1,
        "only one {hog_gb} GiB hog may run at a time; the log was:\n{}",
        daemon.log()
    );
    // One hog at a time: the box never came near empty. (The floor is
    // charged against the *reservations*, so the second hog is refused
    // long before the memory is actually gone.)
    assert!(
        min_available > 30 * GIB,
        "the box fell to {} MiB free",
        min_available / (1024 * 1024)
    );
    for text in &finished {
        assert!(
            text.contains("hog: done"),
            "a hog did not finish:\n{text}"
        );
    }
    eprintln!(
        "serialisation: {hog_gb} GiB hogs, floor {}, at most {max_active} at a time, \
         the box never fell below {} MiB free",
        floor,
        min_available / (1024 * 1024)
    );
    for line in daemon.log().lines() {
        if line.contains("\"lease.granted\"") || line.contains("\"lease.released\"") {
            eprintln!("  {line}");
        }
    }
}

#[test]
fn the_watchdog_stops_a_runaway_before_the_kernel_oom_does() {
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
    // The emergency floor is scaled down: the real one is 8 GiB, and driving
    // the box to 8 GiB free would need 110 GiB of allocation, which is not
    // safe on a box that is also running a seat's work. The floor here is
    // (available - 8 GiB), so the same rule fires after the runaway has
    // taken 8 GiB — and it fires with the whole box still free.
    let hog_gb = hog_gb();
    let emergency = mem_available().saturating_sub(8 * GIB).max(GIB);
    let daemon = DaemonUnderTest::start(&[
        "--emergency-floor",
        &format!("{emergency}"),
        "--min-victim-rss",
        "2G",
    ]);

    let oom_before = oom_kills();
    let mut hog = leased(
        &daemon,
        "runaway",
        &format!("{hog_gb}G"),
        &[HOG, "--bytes", &format!("{hog_gb}G"), "--hold", "60"],
    );

    // Wait for the watchdog to act.
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut stopped_at_available = None;
    let mut min_available = u64::MAX;
    while Instant::now() < deadline {
        let available = mem_available();
        min_available = min_available.min(available);
        // The event carries the free memory at the moment of the stop.
        for line in daemon.log().lines() {
            if !line.contains("\"watchdog.stopped\"") {
                continue;
            }
            if let Ok(event) = serde_json::from_str::<Value>(line) {
                stopped_at_available = event["mem_available_bytes"].as_u64();
            }
            break;
        }
        if stopped_at_available.is_some() {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    let Some(available_at_stop) = stopped_at_available else {
        let _ = hog.kill();
        let _ = hog.wait();
        panic!("the watchdog did not stop the hog; the log was:\n{}", daemon.log());
    };

    // The whole point: the box was stopped while there was still a lot of
    // memory free — long before the kernel's OOM killer would have run.
    assert!(
        available_at_stop > 2 * GIB,
        "the hog was stopped with only {} MiB free, which is inside the OOM zone",
        available_at_stop / (1024 * 1024)
    );
    assert_eq!(
        oom_kills(),
        oom_before,
        "the kernel's OOM killer fired; the watchdog was too late"
    );

    // The hog must actually be stopped, not merely signalled. The hog is
    // the command the client spawned, in its own process group: the group's
    // leader *is* the hog, and that is the pid the watchdog signalled.
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut hog_pid = 0i64;
    let mut saw_stopped = false;
    while Instant::now() < deadline {
        let status = daemon.status();
        if let Some(lease) = status["leases"].as_array().and_then(|leases| leases.first()) {
            hog_pid = lease["pgid"].as_i64().unwrap_or(0);
            let state = std::fs::read_to_string(format!("/proc/{hog_pid}/stat")).unwrap_or_default();
            let code = state
                .rfind(')')
                .map(|close| {
                    state[close + 1..]
                        .split_whitespace()
                        .next()
                        .unwrap_or("")
                        .to_string()
                })
                .unwrap_or_default();
            if code == "T" || code == "t" {
                saw_stopped = true;
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        saw_stopped,
        "the runaway was never stopped (pid {hog_pid}); the log was:\n{}",
        daemon.log()
    );

    // And then it dies: the watchdog kills it once the grace period is out.
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut died = false;
    while Instant::now() < deadline {
        if hog.try_wait().ok().flatten().is_some() {
            died = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(died, "the runaway was stopped but never killed");
    assert!(
        daemon.log().contains("watchdog.killed"),
        "the daemon did not log the kill; the log was:\n{}",
        daemon.log()
    );
    eprintln!(
        "watchdog: the runaway was stopped with {} MiB free (the emergency floor was \
         {} MiB) and killed {} ms later; the kernel's OOM killer fired {} times",
        available_at_stop / (1024 * 1024),
        emergency / (1024 * 1024),
        daemon
            .log()
            .lines()
            .find(|line| line.contains("\"watchdog.killed\""))
            .and_then(|line| serde_json::from_str::<Value>(line).ok())
            .and_then(|event| event["waited_ms"].as_u64())
            .unwrap_or(0),
        oom_kills() - oom_before
    );

    let _ = hog.kill();
    let _ = hog.wait();
}

#[test]
fn a_dead_client_cannot_leak_a_lease() {
    let daemon = DaemonUnderTest::start(&[]);

    let mut client = leased(&daemon, "ghost", "1G", &["sleep", "120"]);

    // Wait for the lease to be real.
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let status = daemon.status();
        if status["leases"].as_array().map(|a| a.len()).unwrap_or(0) == 1 {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(
        daemon.status()["leases"].as_array().unwrap().len(),
        1,
        "the lease never started"
    );

    // Kill the client outright: no release message, no goodbye.
    let _ = client.kill();
    let _ = client.wait();

    // The kernel drops the client's lock, so the daemon must give the
    // memory back without being told.
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let status = daemon.status();
        if status["leases"].as_array().map(|a| a.len()).unwrap_or(0) == 0 {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert_eq!(
        daemon.status()["leases"].as_array().unwrap().len(),
        0,
        "the lease leaked after the client died"
    );
    assert!(
        daemon.log().contains("lease.client_gone"),
        "the daemon did not notice the client was gone"
    );
}

#[test]
fn the_daemon_costs_almost_nothing() {
    let daemon = DaemonUnderTest::start(&[]);
    let pid = daemon.child.id();

    // Warm up, then measure over ten seconds of doing nothing.
    std::thread::sleep(Duration::from_secs(2));
    let rss_before = rss_of(pid);
    let cpu_before = cpu_seconds(pid);
    let wall = Instant::now();
    std::thread::sleep(Duration::from_secs(10));
    let rss_after = rss_of(pid);
    let cpu_after = cpu_seconds(pid);
    let elapsed = wall.elapsed().as_secs_f64();
    let cpu_percent = (cpu_after - cpu_before) / elapsed * 100.0;

    assert!(
        rss_after < 64 * 1024 * 1024,
        "the daemon holds {} MiB of resident memory, which is more than a few MB",
        rss_after / (1024 * 1024)
    );
    assert!(
        cpu_percent < 5.0,
        "the daemon used {cpu_percent:.2}% of a core while doing nothing"
    );
    eprintln!(
        "daemon overhead: {} MiB resident, {cpu_percent:.2}% of one core over {:.0}s",
        rss_after / (1024 * 1024),
        elapsed
    );
    let _ = rss_before;
}

#[test]
fn a_learned_peak_is_used_by_the_next_run() {
    let daemon = DaemonUnderTest::start(&[]);

    // One run with an explicit peak teaches the daemon what the label costs.
    let mut first = leased(&daemon, "auto-label", "2G", &[HOG, "--bytes", "2G", "--hold", "1"]);
    let _ = first.wait();
    let _ = output_of(&mut first);

    let history = daemon.history();
    assert_eq!(history.len(), 1, "the run was recorded");
    assert_eq!(history[0]["label"], "auto-label");
    let measured = history[0]["peak_rss_bytes"].as_u64().unwrap();
    assert!(
        measured > 1 * GIB,
        "the peak was {measured} bytes, which is not the 2 GiB the hog took"
    );

    // The next run with --peak auto must use what was learned.
    let mut second = leased(&daemon, "auto-label", "auto", &[HOG, "--bytes", "2G", "--hold", "1"]);
    let output = {
        let _ = second.wait();
        output_of(&mut second)
    };
    assert!(
        output.contains("admitted after"),
        "the automatic peak was not used:\n{output}"
    );
    assert!(
        !output.contains("no history for the label"),
        "the automatic peak found no history:\n{output}"
    );
}

#[test]
fn the_stop_command_stops_the_daemon() {
    let mut daemon = DaemonUnderTest::start(&[]);

    // The daemon is answering.
    assert!(
        daemon.status()["leases"].is_array(),
        "the daemon did not answer the status request"
    );

    let output = Command::new(BIN)
        .arg("stop")
        .arg("--socket")
        .arg(&daemon.socket)
        .output()
        .expect("the stop command runs");
    assert!(
        output.status.success(),
        "the stop command failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // And then it is not.
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut gone = false;
    while Instant::now() < deadline {
        if daemon.child.try_wait().ok().flatten().is_some() {
            gone = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(gone, "the daemon was still running after it was told to stop");
}

#[test]
fn a_refused_lease_does_not_run_the_command() {
    let daemon = DaemonUnderTest::start(&[]);
    let marker = daemon.state_dir.join("ran.txt");

    // "--peak auto" for a label with no history is refused.
    let mut child = leased(
        &daemon,
        "never-seen-before",
        "auto",
        &["touch", marker.to_str().unwrap_or_default()],
    );
    let status = child.wait().expect("the client finishes");
    assert!(!status.success(), "the client should have failed");
    let output = output_of(&mut child);
    assert!(
        output.contains("no history for the label"),
        "the refusal was not explained:\n{output}"
    );
    assert!(
        !marker.exists(),
        "the command ran without a lease — that is the whole point of the admission"
    );
}

#[test]
fn the_queue_is_ordered_by_priority() {
    // The default floor (25 GiB) and a 50 GiB reservation: the first lease
    // fits (118 - 50 = 68 free, above the floor) and the second does not
    // (68 - 50 = 18, below it). The reservation is what blocks the queue —
    // the commands themselves use nothing.
    let daemon = DaemonUnderTest::start(&[]);

    let low = leased_with_priority(&daemon, "low", "50G", 0, &["sleep", "6"]);
    std::thread::sleep(Duration::from_millis(800));

    let normal = leased_with_priority(&daemon, "normal", "50G", 0, &["sleep", "6"]);
    std::thread::sleep(Duration::from_millis(400));

    // A high-priority request must overtake the one that arrived first.
    let high = leased_with_priority(&daemon, "high", "50G", 5, &["sleep", "2"]);
    std::thread::sleep(Duration::from_millis(800));

    let status = daemon.status();
    let queue: Vec<String> = status["queue"]
        .as_array()
        .map(|items| {
            items
                .iter()
                .map(|item| item["label"].as_str().unwrap_or("?").to_string())
                .collect()
        })
        .unwrap_or_default();
    assert!(
        !queue.is_empty(),
        "nothing was queued; the status was {status}"
    );
    assert_eq!(
        queue.first().map(String::as_str),
        Some("high"),
        "the queue is {queue:?}, and the high-priority request is not first"
    );
    assert_eq!(
        queue.get(1).map(String::as_str),
        Some("normal"),
        "the queue is {queue:?}; the earlier request should be behind the later one"
    );

    for mut child in [low, normal, high] {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// The daemon must never signal the box's own services.
#[test]
fn the_watchdog_leaves_small_leases_alone() {
    // The emergency floor is above the box's free memory, so the watchdog is
    // armed from the first sample.
    let daemon = DaemonUnderTest::start(&["--emergency-floor", "200G", "--min-victim-rss", "2G"]);

    let mut small = leased(&daemon, "small", "1G", &["sleep", "8"]);
    std::thread::sleep(Duration::from_secs(3));

    let status = daemon.status();
    let leases = status["leases"].as_array().cloned().unwrap_or_default();
    assert_eq!(leases.len(), 1, "the small lease is still running");
    let small_pid = leases[0]["pid"].as_i64().unwrap_or(0) as i32;
    let state = std::fs::read_to_string(format!("/proc/{small_pid}/stat")).unwrap_or_default();
    let close = state.rfind(')').unwrap_or(0);
    let code = state[close + 1..].split_whitespace().next().unwrap_or("");
    assert_ne!(
        code, "T",
        "the watchdog stopped a lease that was too small to be the cause"
    );
    assert!(
        !daemon.log().contains("watchdog.stopped"),
        "the watchdog acted on a small lease"
    );

    let _ = small.kill();
    let _ = small.wait();
}
