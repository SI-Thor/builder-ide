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
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
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
        // The wait is a budget for the whole run, not for each heavy test:
        // two tests that each wait 40 minutes are an hour of waiting.
        let deadline = heavy_deadline(wait);
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

/// When this test binary started, so the heavy tests' wait is one budget.
fn heavy_deadline(wait: u64) -> Instant {
    static START: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();
    let start = *START.get_or_init(Instant::now);
    start + Duration::from_secs(wait)
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

/// The brief's cap: a test must never take more than this much of the box.
/// The box has 122 GiB and no swap, and the OOM this crate exists to
/// prevent is one careless test away.
const TEST_MEMORY_CAP_GIB: u64 = 60;

/// How big a hog the heavy tests use. The brief's scale is 30 GiB; a
/// smaller one is for a box that is already busy.
fn hog_gb() -> u64 {
    let gigabytes = std::env::var("THOR_ADMIT_HOG_GB")
        .ok()
        .and_then(|text| text.parse().ok())
        .unwrap_or(30);
    assert!(
        gigabytes <= TEST_MEMORY_CAP_GIB,
        "the brief caps a test's memory at {TEST_MEMORY_CAP_GIB} GiB, and {gigabytes} GiB \
         was asked for"
    );
    gigabytes
}

/// A scripted `/proc/meminfo`.
///
/// The daemon reads the kernel's own file in production. A test points it
/// at a file the test writes, so a memory **curve** can be driven without
/// taking the real box down to nothing — see
/// `the_watchdog_stops_a_runaway_before_the_memory_runs_out`.
fn write_meminfo(path: &Path, total_bytes: u64, available_bytes: u64) {
    let kb = |bytes: u64| bytes / 1024;
    let text = format!(
        "MemTotal:       {total:>12} kB\n\
         MemFree:        {free:>12} kB\n\
         MemAvailable:   {available:>12} kB\n\
         Buffers:              0 kB\n\
         Cached:         {cached:>12} kB\n\
         SwapTotal:             0 kB\n\
         SwapFree:              0 kB\n",
        total = kb(total_bytes),
        free = kb(available_bytes),
        available = kb(available_bytes),
        cached = kb(total_bytes.saturating_sub(available_bytes)),
    );
    // Sideways, so the daemon never reads half a file.
    let temporary = path.with_extension("tmp");
    std::fs::write(&temporary, text).unwrap();
    std::fs::rename(&temporary, path).unwrap();
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
    // The brief's memory cap is checked first, so an over-large hog is
    // refused even when the test is about to skip.
    let hog_gb = hog_gb();
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
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
    // The brief's memory cap is checked first, so an over-large hog is
    // refused even when the test is about to skip.
    let hog_gb = hog_gb();
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

/// The brief's line: the watchdog must stop the runaway hog while the box
/// still has more than 2 GiB free — long before the kernel's OOM killer is
/// anywhere near.
///
/// Driving the **real** box to 2 GiB free would take about 100 GiB of
/// allocation. The brief caps a test's memory at 60 GiB, and the box is
/// also running a seat's work, so the memory **curve** is scripted here:
/// the daemon, the hog, the SIGSTOP, the SIGTERM and the timing are all
/// real; only the number the daemon reads is written by the test.
#[test]
fn the_watchdog_stops_a_runaway_before_the_memory_runs_out() {
    let total = 122 * GIB;
    // The daemon's own default emergency floor: the brief's 8 GiB.
    let floor = 8 * GIB;
    let scratch =
        std::env::temp_dir().join(format!("thor-admit-lowwater-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let meminfo = scratch.join("meminfo");
    write_meminfo(&meminfo, total, 100 * GIB);

    let daemon = DaemonUnderTest::start(&["--meminfo", meminfo.to_str().unwrap()]);
    let oom_before = oom_kills();

    // A hog big enough to be a valid victim (the watchdog will not touch a
    // lease under 2 GiB) and no bigger than it needs to be.
    let mut hog = leased(&daemon, "runaway", "4G", &[HOG, "--bytes", "4G", "--hold", "120"]);

    // Wait until the hog is really using memory, so the watchdog has
    // something to find.
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut hog_rss = 0u64;
    while Instant::now() < deadline {
        let status = daemon.status();
        if let Some(lease) = status["leases"].as_array().and_then(|leases| leases.first()) {
            hog_rss = lease["current_rss_bytes"].as_u64().unwrap_or(0);
            if hog_rss >= 2 * GIB {
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        hog_rss >= 2 * GIB,
        "the hog never grew to be a victim ({hog_rss} bytes); the status was {}",
        daemon.status()
    );

    // The curve. First the box loses a lot of memory at once — the shape of
    // the 13:22 OOM — and then it keeps sliding down, a quarter of a
    // gibibyte a step, through the emergency floor and on past the 2 GiB
    // line the brief names.
    let steps = Arc::new(Mutex::new(Vec::<(u64, Instant)>::new()));
    let writer = {
        let meminfo = meminfo.clone();
        let steps = Arc::clone(&steps);
        std::thread::spawn(move || {
            write_meminfo(&meminfo, total, 12 * GIB);
            steps.lock().unwrap().push((12 * GIB, Instant::now()));
            let mut available = 12 * GIB;
            while available > 0 {
                std::thread::sleep(Duration::from_millis(50));
                available = available.saturating_sub(256 * 1024 * 1024);
                write_meminfo(&meminfo, total, available);
                steps.lock().unwrap().push((available, Instant::now()));
            }
        })
    };

    // Wait for the watchdog to act.
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut stopped_at = None;
    let mut observed_at = None;
    while Instant::now() < deadline {
        for line in daemon.log().lines() {
            if !line.contains("\"watchdog.stopped\"") {
                continue;
            }
            if let Ok(event) = serde_json::from_str::<Value>(line) {
                stopped_at = event["mem_available_bytes"].as_u64();
            }
            break;
        }
        if stopped_at.is_some() {
            observed_at = Some(Instant::now());
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let Some(available_at_stop) = stopped_at else {
        let _ = hog.kill();
        let _ = hog.wait();
        panic!("the watchdog did not stop the hog; the log was:\n{}", daemon.log());
    };

    // Let the curve finish: it has to reach the danger zone *after* the
    // stop, or the test would only prove that the line was never crossed.
    let _ = writer.join();
    let curve = steps.lock().unwrap().clone();
    let lowest = curve.last().map(|(available, _)| *available).unwrap_or(0);

    // The brief's line: the hog was stopped while there was still more than
    // 2 GiB free.
    assert!(
        available_at_stop > 2 * GIB,
        "the hog was stopped with only {} MiB free, which is inside the OOM zone",
        available_at_stop / (1024 * 1024)
    );
    // It acted because the box was short, and it acted at once: the daemon
    // samples every 250 ms and the curve moves 256 MiB every 50 ms, so the
    // number it reads can be up to 1.25 GiB below the floor. It must not be
    // far below that, or the daemon would be acting late.
    assert!(
        available_at_stop <= floor && floor - available_at_stop <= 2 * GIB,
        "the watchdog acted at {} MiB free, which is not the {} MiB floor",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024)
    );
    // The curve really did go past the 2 GiB line, and it did so after the
    // stop: the daemon acted before the box was in trouble.
    assert!(
        lowest <= 2 * GIB,
        "the curve only reached {} MiB free, so the danger zone was never reached",
        lowest / (1024 * 1024)
    );

    // The hog must actually be stopped, not merely signalled.
    let deadline = Instant::now() + Duration::from_secs(10);
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

    // And then it dies.
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
    assert_eq!(
        oom_kills(),
        oom_before,
        "the kernel's OOM killer fired; the watchdog was too late"
    );

    // And nothing is left behind. A hog that was stopped and never killed
    // would sit on the box holding its memory with nobody watching it.
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline && hog_pid > 0 && Path::new(&format!("/proc/{hog_pid}")).exists() {
        std::thread::sleep(Duration::from_millis(50));
    }
    if hog_pid > 0 && Path::new(&format!("/proc/{hog_pid}")).exists() {
        // Clean up before failing: the box must not keep a frozen hog.
        unsafe {
            libc::kill(-(hog_pid as i32), libc::SIGCONT);
            libc::kill(-(hog_pid as i32), libc::SIGTERM);
        }
        panic!("the hog {hog_pid} was still there after the watchdog killed it");
    }

    // How fast: the curve crossed the floor, and the daemon acted after it.
    // The number is an upper bound — the log is polled every 20 ms.
    let crossed = curve
        .iter()
        .find(|(available, _)| *available < floor)
        .map(|(_, at)| *at);
    let latency = match (crossed, observed_at) {
        (Some(crossed), Some(observed)) => observed.saturating_duration_since(crossed),
        _ => Duration::ZERO,
    };
    eprintln!(
        "low water: the hog was stopped with {} MiB free (the floor was {} MiB) and the \
         curve went on down to {} MiB; the daemon acted within {} ms of the floor being \
         crossed, and the kernel's OOM killer fired {} times",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024),
        lowest / (1024 * 1024),
        latency.as_millis(),
        oom_kills() - oom_before,
    );

    let _ = hog.kill();
    let _ = hog.wait();
    let _ = std::fs::remove_dir_all(&scratch);
}

#[test]
fn a_dead_client_cannot_leak_a_lease() {
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);

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
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);
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
        "daemon overhead (idle): {} MiB resident, {cpu_percent:.2}% of one core over {:.0}s",
        rss_after / (1024 * 1024),
        elapsed
    );
    let _ = rss_before;

    // And with a lease running: the daemon walks /proc every sample to find
    // the lease's resident set, and asks nvidia-smi what the GPU is doing.
    let mut busy = leased(&daemon, "busy", "1G", &["sleep", "30"]);
    std::thread::sleep(Duration::from_secs(2));
    let cpu_before = cpu_seconds(pid);
    let wall = Instant::now();
    std::thread::sleep(Duration::from_secs(10));
    let cpu_after = cpu_seconds(pid);
    let elapsed = wall.elapsed().as_secs_f64();
    let cpu_percent = (cpu_after - cpu_before) / elapsed * 100.0;
    assert!(
        cpu_percent < 5.0,
        "the daemon used {cpu_percent:.2}% of a core while watching a lease"
    );
    eprintln!(
        "daemon overhead (one lease running): {cpu_percent:.2}% of one core over {:.0}s",
        elapsed
    );
    let _ = busy.kill();
    let _ = busy.wait();
}

#[test]
fn a_learned_peak_is_used_by_the_next_run() {
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);

    // One run with an explicit peak teaches the daemon what the label costs.
    let mut first = leased(&daemon, "auto-label", "2G", &[HOG, "--bytes", "2G", "--hold", "1"]);
    let _ = first.wait();
    let _ = output_of(&mut first);

    let history = daemon.history();
    assert_eq!(history.len(), 1, "the run was recorded");
    assert_eq!(history[0]["label"], "auto-label");
    let measured = history[0]["peak_rss_bytes"].as_u64().unwrap();
    assert!(
        measured > GIB,
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
    let mut daemon = DaemonUnderTest::start(&["--floor", "1G"]);

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
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);
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
    // The floor and the reservation are derived from the box's free memory
    // at this moment, so the test says what it means whatever else is
    // running. The floor is placed half way between "the first lease fits"
    // and "no lease fits", so all three requests wait and the queue is
    // tested on its own — and the box's memory can move by twenty-odd
    // gibibytes while the test runs without changing the answer.
    let available = mem_available();
    let reservation = ((available / 2) / GIB) * GIB;
    let floor = available - reservation / 2;
    let daemon = DaemonUnderTest::start(&[
        "--floor",
        &floor.to_string(),
        "--emergency-floor",
        "1G",
    ]);
    let peak = format!("{}G", reservation / GIB);

    let low = leased_with_priority(&daemon, "low", &peak, 0, &["sleep", "6"]);
    std::thread::sleep(Duration::from_millis(800));

    let normal = leased_with_priority(&daemon, "normal", &peak, 0, &["sleep", "6"]);
    std::thread::sleep(Duration::from_millis(400));

    // A high-priority request must overtake the one that arrived first.
    let high = leased_with_priority(&daemon, "high", &peak, 5, &["sleep", "2"]);
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
    // Two requests of the same priority keep the order they arrived in:
    // "low" asked first, so it is in front of "normal".
    assert_eq!(
        queue.get(1).map(String::as_str),
        Some("low"),
        "the queue is {queue:?}; the earlier request should be in front of the later one"
    );
    assert_eq!(
        queue.get(2).map(String::as_str),
        Some("normal"),
        "the queue is {queue:?}"
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
    let daemon = DaemonUnderTest::start(&[
        "--floor",
        "1G",
        "--emergency-floor",
        "200G",
        "--min-victim-rss",
        "2G",
    ]);

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

// ---------------------------------------------------------------------------
// The presence queue: the work the box does when it has room.
// ---------------------------------------------------------------------------

/// Register a job in the presence queue and return its id.
fn presence_add(daemon: &DaemonUnderTest, tier: &str, peak: &str, label: &str, command: &[&str]) -> u64 {
    let output = Command::new(BIN)
        .arg("presence")
        .arg("add")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--tier")
        .arg(tier)
        .arg("--peak")
        .arg(peak)
        .arg("--label")
        .arg(label)
        .arg("--")
        .args(command)
        .output()
        .expect("the presence add runs");
    let text = String::from_utf8_lossy(&output.stdout);
    // "thor-admit: registered #1 \"label\" as study"
    let id = text
        .split('#')
        .nth(1)
        .and_then(|rest| rest.split_whitespace().next())
        .and_then(|text| text.parse::<u64>().ok())
        .unwrap_or_else(|| panic!("cannot read the job id out of {text:?}"));
    id
}

/// The presence queue, as the status shows it.
fn presence_jobs(daemon: &DaemonUnderTest) -> Vec<Value> {
    daemon.status()["presence"]
        .as_array()
        .cloned()
        .unwrap_or_default()
}

/// The ledger, as the CLI shows it.
fn ledger(daemon: &DaemonUnderTest) -> Vec<Value> {
    let output = Command::new(BIN)
        .arg("ledger")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--json")
        .output()
        .expect("the ledger runs");
    let value: Value = serde_json::from_slice(&output.stdout).expect("the ledger is JSON");
    value["ledger"].as_array().cloned().unwrap_or_default()
}

/// Wait until the predicate holds, or give up.
fn wait_until(seconds: u64, mut predicate: impl FnMut() -> bool) -> bool {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        if predicate() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    predicate()
}

/// The registered work runs when the box has room for it.
#[test]
fn a_presence_job_runs_when_the_box_has_room() {
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);
    let marker = daemon.state_dir.join("ran");
    let _ = std::fs::remove_file(&marker);

    let id = presence_add(
        &daemon,
        "study",
        "1G",
        "presence.test",
        &["sh", "-c", &format!("sleep 1; touch {}", marker.display())],
    );

    let ran = wait_until(20, || marker.exists());
    assert!(ran, "the presence job did not run: {}", daemon.log());

    let jobs = presence_jobs(&daemon);
    let job = jobs.iter().find(|job| job["id"].as_u64() == Some(id));
    assert!(job.is_some(), "the job is still registered");
    let state = job.unwrap()["state"].as_str().unwrap_or("");
    assert!(
        state == "done" || state == "running",
        "the job's state is {state:?}: {}",
        daemon.log()
    );
}

/// Live work takes the memory back from the presence queue.
#[test]
fn a_live_lease_preempts_a_presence_job() {
    // The floor is set so that the presence job's reservation is exactly
    // what stands between the live lease and the box's room: the presence
    // job promised 4 GiB it has not used, and the live lease needs 2 GiB.
    let available = mem_available();
    let presence_peak = 4 * GIB;
    let live_peak = 2 * GIB;
    let floor = available
        .saturating_sub(presence_peak)
        .saturating_sub(live_peak)
        .saturating_add(GIB);
    let daemon = DaemonUnderTest::start(&[
        "--floor",
        &floor.to_string(),
        "--emergency-floor",
        &available.saturating_sub(GIB).to_string(),
    ]);

    // A presence job that reserves memory it does not use yet.
    let id = presence_add(
        &daemon,
        "study",
        "4G",
        "presence.test",
        &["sleep", "120"],
    );
    let running = wait_until(20, || {
        presence_jobs(&daemon)
            .iter()
            .any(|job| job["id"].as_u64() == Some(id) && job["state"] == "running")
    });
    assert!(running, "the presence job never started: {}", daemon.log());

    // A live lease arrives. It does not fit while the presence job holds
    // its reservation, so the daemon must take the memory back.
    let mut live = leased(&daemon, "live.test", "2G", &["sleep", "20"]);
    let granted = wait_until(20, || {
        daemon
            .log()
            .contains("\"label\":\"live.test\"")
            && daemon.log().contains("lease.granted")
    });
    assert!(granted, "the live lease was never granted: {}", daemon.log());

    let log = daemon.log();
    let preempted = log.find("presence.preempted").unwrap_or_else(|| {
        panic!("the presence job was not pre-empted: {log}");
    });
    let granted_at = log.find("lease.granted").unwrap_or_else(|| {
        panic!("the live lease was never granted: {log}");
    });
    assert!(
        preempted < granted_at,
        "the pre-emption came after the grant: {log}"
    );

    // The pre-empted job is stopped, and it is resumable, so it goes back
    // in the queue rather than being lost.
    let jobs = presence_jobs(&daemon);
    let job = jobs.iter().find(|job| job["id"].as_u64() == Some(id)).unwrap();
    assert!(
        job["preemptions"].as_u64().unwrap_or(0) >= 1,
        "the job was not counted as pre-empted: {job}"
    );

    let _ = live.kill();
    let _ = live.wait();
}

/// The ledger books the box's time to the tiers, and explains its idleness.
#[test]
fn the_ledger_books_the_time_by_tier() {
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);

    // A live lease, and a presence job, running together.
    let mut live = leased(&daemon, "live.test", "1G", &["sleep", "4"]);
    let id = presence_add(
        &daemon,
        "study",
        "1G",
        "presence.test",
        &["sleep", "4"],
    );
    assert!(
        wait_until(20, || {
            presence_jobs(&daemon)
                .iter()
                .any(|job| job["id"].as_u64() == Some(id) && job["state"] == "running")
        }),
        "the presence job never started: {}",
        daemon.log()
    );
    std::thread::sleep(Duration::from_secs(5));

    let buckets = ledger(&daemon);
    let bucket = buckets.last().expect("there is an hour");
    let live_s = bucket["tiers"]["live"]["running_s"].as_f64().unwrap_or(0.0);
    let study_s = bucket["tiers"]["study"]["running_s"].as_f64().unwrap_or(0.0);
    assert!(live_s > 0.0, "the live tier was not booked: {bucket}");
    assert!(study_s > 0.0, "the study tier was not booked: {bucket}");

    // The idle time has a cause: nothing was registered at the start, and
    // the ledger says so rather than leaving it unexplained.
    let unattributed = bucket["idle"]["unattributed_s"].as_f64().unwrap_or(-1.0);
    assert_eq!(
        unattributed, 0.0,
        "some idle time had no cause the ledger could name: {bucket}\nthe daemon's log:\n{}",
        daemon.log()
    );

    let _ = live.kill();
    let _ = live.wait();
}

/// With nothing registered, the box's idleness is named.
#[test]
fn the_ledger_names_the_idleness() {
    let daemon = DaemonUnderTest::start(&["--floor", "1G"]);
    std::thread::sleep(Duration::from_secs(3));

    let buckets = ledger(&daemon);
    let bucket = buckets.last().expect("there is an hour");
    let reasons = bucket["idle"]["by_reason"].as_object().cloned().unwrap_or_default();
    assert!(
        reasons.contains_key("no_work_registered"),
        "the ledger did not say why the box was idle: {bucket}"
    );
    assert_eq!(
        bucket["idle"]["unattributed_s"].as_f64().unwrap_or(-1.0),
        0.0,
        "some idle time had no cause the ledger could name: {bucket}"
    );
}

/// The daemon's log is chained, and a post-mortem's after-the-fact "fix" of
/// a line is named by its seq. The floor is what this box can clear, not
/// what the Thor can: the test is about the log's chain, not the admission
/// arithmetic, and it must run the same on a 3 GiB CI box and on the box
/// itself.
#[test]
fn the_daemons_log_is_chained_and_an_edit_is_named() {
    let mut daemon = DaemonUnderTest::start(&["--floor", "64M", "--emergency-floor", "512M"]);

    // One lease through its whole life, so the log has decisions in it.
    let mut client = leased(&daemon, "chain-test", "64M", &["/bin/true"]);
    let _ = output_of(&mut client);
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if daemon.log().contains("lease.released") {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    // Stop the daemon cleanly, the way an operator would, so the log is
    // flushed and final.
    let _ = Command::new(BIN)
        .arg("stop")
        .arg("--socket")
        .arg(&daemon.socket)
        .output();
    let _ = daemon.child.wait();

    // The log every line carries its number and the chain.
    let log = daemon.log();
    assert!(log.contains("\"seq\":"), "the log is not chained:\n{log}");
    assert!(log.contains("\"chain\":"), "the log is not chained:\n{log}");

    // The CLI verifies what the daemon wrote.
    let verify = |log_text: &str| -> (bool, String) {
        let path = daemon.state_dir.join("daemon.log");
        std::fs::write(&path, log_text).unwrap();
        let output = Command::new(BIN)
            .arg("verify")
            .arg("--log")
            .arg(&path)
            .output()
            .expect("the verify runs");
        let text = format!(
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        (output.status.success(), text)
    };
    let (held, text) = verify(&log);
    assert!(held, "verify rejected the daemon's own log:\n{text}");
    assert!(text.contains("chain intact"), "verify said:\n{text}");

    // An after-the-fact edit — a post-mortem that "fixes" a number —
    // breaks the chain at the line it touched, by its seq.
    let edited = log.lines().map(|line| {
        let value: Value = serde_json::from_str(line).unwrap_or(Value::Null);
        if value["event"] == "lease.granted" {
            let mut changed = value.clone();
            changed["peak_bytes"] = serde_json::json!(1);
            serde_json::to_string(&changed).unwrap()
        } else {
            line.to_string()
        }
    });
    let tampered: Vec<String> = edited.collect();
    let (held, text) = verify(&tampered.join("\n"));
    assert!(!held, "verify passed an edited log:\n{text}");
    assert!(text.contains("broke at seq"), "verify said:\n{text}");
}
