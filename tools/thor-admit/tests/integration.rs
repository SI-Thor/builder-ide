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

/// The counter that keeps every daemon under test on its own path.
///
/// The state directory used to be named after the process id and the daemon's
/// arguments alone. The tests run in parallel, so every test that started a
/// daemon with `--floor 1G` landed on the same socket, the same lease locks,
/// the same history file and the same ledger. The counter makes each daemon's
/// directory its own; the name makes it readable when a test leaves one
/// behind.
static DAEMON_SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Turn a test's name into something a path can hold.
fn slug(name: &str) -> String {
    name.chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

/// A daemon's path, reserved before the daemon starts.
///
/// The daemon reads a `/proc/meminfo` the test may write, so the test has to
/// know where the daemon's state will live before the daemon is started.
struct Reserved {
    state_dir: PathBuf,
    extra: Vec<String>,
}

impl DaemonUnderTest {
    /// Reserve a path for a daemon, with the arguments it will be started
    /// with.
    ///
    /// The directory is made here, not when the daemon starts, because the
    /// test may have to write a file the daemon reads — its `/proc/meminfo`
    /// — before the daemon is running.
    fn reserve(name: &str, extra: &[&str]) -> Reserved {
        let serial = DAEMON_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let mut state_dir = std::env::temp_dir();
        state_dir.push(format!(
            "thor-admit-it-{}-{serial}-{}",
            std::process::id(),
            slug(name)
        ));
        let _ = std::fs::remove_dir_all(&state_dir);
        std::fs::create_dir_all(&state_dir).unwrap();
        Reserved {
            state_dir,
            extra: extra.iter().map(|argument| argument.to_string()).collect(),
        }
    }

    /// Start a daemon on the path that was reserved for it.
    ///
    /// The daemon is started with the GPU's view **off**: these tests are
    /// CPU-only, and with the GPU's view on, the daemon would run the real
    /// `nvidia-smi`/`tegrastats` children and put other seats' CUDA work
    /// into its status. Since round 10 a CPU-only lease (no GPU history)
    /// skips the pool rule anyway, so the tests' admission decisions no
    /// longer depend on the box's real pool; a test that *is* about the
    /// pool passes its own `--gpu-probe` and its own scripted `tegrastats`,
    /// which overrides this default.
    fn start(reserved: Reserved) -> DaemonUnderTest {
        let state_dir = reserved.state_dir;
        std::fs::create_dir_all(&state_dir).unwrap();
        let socket = state_dir.join("sock");
        let mut command = Command::new(BIN);
        command
            .arg("daemon")
            .arg("--socket")
            .arg(&socket)
            .arg("--state-dir")
            .arg(&state_dir)
            .arg("--gpu-probe")
            .arg("off")
            .arg("--idle-exit")
            .arg("600")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        for argument in &reserved.extra {
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

    /// Start a daemon with a name of its own.
    fn start_named(name: &str, extra: &[&str]) -> DaemonUnderTest {
        DaemonUnderTest::start(DaemonUnderTest::reserve(name, extra))
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

/// The one-at-a-time gate every test takes unless it is told not to.
///
/// The director's note (2026-10-31): 7 of 14 tests failed when the suite
/// ran in parallel at load ~38, and all 14 passed serially. Every daemon now
/// has a socket and a state directory of its own, so the tests no longer
/// fight over the daemon's state — but they still share the box, and a box
/// at load 38 delays a client's connect, a daemon's first sample and a
/// hog's growth by seconds at a time, which the fixed waits in a test read
/// as a failure. So the suite is serial by default, which is also the fair
/// way to treat a box other seats are using. `THOR_ADMIT_PARALLEL_TESTS=1`
/// opens the gate for a deliberate parallel run — the isolation is real and
/// is tested on its own, and a parallel run under load is how that gets
/// re-checked.
fn serial_gate() -> Option<std::sync::MutexGuard<'static, ()>> {
    static SERIAL: std::sync::Mutex<()> = std::sync::Mutex::new(());
    if std::env::var("THOR_ADMIT_PARALLEL_TESTS").as_deref() == Ok("1") {
        return None;
    }
    Some(SERIAL.lock().unwrap_or_else(|poisoned| poisoned.into_inner()))
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

/// How much of the box a test hog may leave to everything else.
///
/// The box is not the test's: other seats' work runs on it, and a hog that
/// took what the box had left would push the *kernel's* OOM killer into the
/// picture, which is the thing this daemon exists to prevent.
const HOG_MARGIN_GIB: u64 = 16;

/// How big a hog the heavy tests use.
///
/// The brief's scale is 30 GiB. A smaller one is for a box that is already
/// busy: the hog is the smaller of the brief's scale and the box's real
/// headroom less the margin, so the test never takes memory the box cannot
/// spare. `THOR_ADMIT_HOG_GB` overrides it for a deliberate run.
fn hog_gb() -> u64 {
    let available = mem_available();
    let headroom = available.saturating_sub(HOG_MARGIN_GIB * GIB) / GIB;
    let brief = 30;
    let chosen = match std::env::var("THOR_ADMIT_HOG_GB")
        .ok()
        .and_then(|text| text.parse::<u64>().ok())
    {
        Some(gigabytes) => gigabytes,
        None => headroom.min(brief),
    };
    assert!(
        chosen <= TEST_MEMORY_CAP_GIB,
        "the brief caps a test's memory at {TEST_MEMORY_CAP_GIB} GiB, and {chosen} GiB \
         was asked for"
    );
    chosen
}

/// The box's own total memory, in bytes.
fn mem_total() -> u64 {
    let text = std::fs::read_to_string("/proc/meminfo").unwrap();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("MemTotal:") {
            let kb: u64 = rest.split_whitespace().next().unwrap().parse().unwrap();
            return kb * 1024;
        }
    }
    0
}

/// A daemon whose view of the box's memory the test holds still.
///
/// The daemon reads the kernel's own file in production, so its view of the
/// box moves with everything else that is running. That is right in
/// production and wrong in a test: the answer the test is checking must not
/// change because another seat's work started or finished. So the daemon is
/// pointed at a file the test writes, and the number in it is the box's real
/// free memory at the moment the test froze it.
fn frozen_memory_daemon(
    name: &str,
    extra: &[&str],
    total_bytes: u64,
    available_bytes: u64,
) -> DaemonUnderTest {
    let mut reserved = DaemonUnderTest::reserve(name, extra);
    let meminfo = reserved.state_dir.join("meminfo");
    write_meminfo(&meminfo, total_bytes, available_bytes);
    reserved.extra.push("--meminfo".to_string());
    reserved.extra.push(meminfo.display().to_string());
    DaemonUnderTest::start(reserved)
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
/// The box has `available` free and a hog takes `hog`. One hog must fit and
/// two must not, which puts the floor in a window:
///
/// ```text
/// available - 2*hog  <  floor  <=  available - hog
/// ```
///
/// The floor is set half way up that window. Half way is not a detail: the
/// daemon charges a running lease the memory it has *promised* but not yet
/// taken, and a hog that is halfway through faulting its pages in is owed
/// the whole reservation. The two ends of the window are therefore the two
/// moments the answer could change, and half way is as far from both as the
/// window allows.
fn floor_for_one_hog(available: u64, hog_bytes: u64) -> u64 {
    let upper = available.saturating_sub(hog_bytes);
    let lower = available.saturating_sub(2 * hog_bytes);
    lower + (upper - lower) / 2
}

/// Two daemons in the same test binary must never share a socket path or a
/// state directory.
///
/// The tests run in parallel, and the state directory used to be named after
/// the process id and the daemon's arguments alone — so every test that
/// started a daemon with `--floor 1G` landed on the *same* socket, the same
/// lease locks, the same history file and the same ledger. One test's daemon
/// answered another's status request, and one test's `Drop` deleted the
/// directory another test was still using.
#[test]
fn two_daemons_never_share_a_socket_or_a_state_directory() {
    let _serial = serial_gate();
    let first = DaemonUnderTest::start_named("isolation", &["--floor", "1G"]);
    let second = DaemonUnderTest::start_named("isolation", &["--floor", "1G"]);

    assert_ne!(
        first.socket, second.socket,
        "the two daemons were given the same socket path"
    );
    assert_ne!(
        first.state_dir, second.state_dir,
        "the two daemons were given the same state directory"
    );

    // And both of them answer, for themselves.
    assert!(
        first.status()["leases"].is_array(),
        "the first daemon does not answer"
    );
    assert!(
        second.status()["leases"].is_array(),
        "the second daemon does not answer"
    );
}

/// A daemon started for a socket of its own must keep its state beside that
/// socket.
///
/// The CLI starts a daemon when it cannot reach one. It used to start it
/// with the socket and nothing else, so the daemon fell back to the
/// *default* state directory — the box's real one — and wrote its history,
/// its ledger and its log there. A test's daemon was therefore writing into
/// the box's own record, and a test's `busy` lease ended up in the learned
/// peaks that the cost model reads.
#[test]
fn a_daemon_started_for_a_socket_keeps_its_state_beside_the_socket() {
    let _serial = serial_gate();
    let dir = std::env::temp_dir().join(format!(
        "thor-admit-statedir-{}-{}",
        std::process::id(),
        DAEMON_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let socket = dir.join("sock");
    // The default state directory, moved out of the way so the test can see
    // whether the daemon falls back to it.
    let state_home = dir.join("xdg");

    // The client cannot reach a daemon, so it starts one. The command runs
    // for six seconds: a run teaches the history only if it lasted, so a
    // `true` would prove nothing about where the history lands.
    let output = Command::new(BIN)
        .env("XDG_STATE_HOME", &state_home)
        .arg("run")
        .arg("--socket")
        .arg(&socket)
        .arg("--peak")
        .arg("1G")
        .arg("--label")
        .arg("state.dir.probe")
        .arg("--")
        .arg("sleep")
        .arg("6")
        .output()
        .expect("the client runs");
    assert!(
        output.status.success(),
        "the lease failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // The daemon the client started kept its state beside its socket: the
    // lease's peak is written there when the lease ends.
    let history = dir.join("peaks.jsonl");
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline && !history.exists() {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(
        history.exists(),
        "the daemon did not keep its history beside its socket; the directory holds {:?}",
        std::fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect::<Vec<_>>()
    );

    // And it did not touch the default state directory.
    assert!(
        !state_home.join("thor-admit").exists(),
        "the daemon wrote into the default state directory"
    );

    // Stop the daemon the client started, and take the directory away.
    let _ = Command::new(BIN)
        .arg("stop")
        .arg("--socket")
        .arg(&socket)
        .output();
    let _ = std::fs::remove_dir_all(&dir);
}

/// A second daemon must not take a socket that is already spoken for.
///
/// The daemon's front door is its socket, and two daemons on one socket
/// would be two admission controllers with two views of the box — exactly
/// the thing this crate exists to prevent. The daemon therefore holds an
/// exclusive lock on the socket's lock file for as long as it runs, and a
/// second daemon refuses to start while that lock is held, whether or not
/// the socket still answers.
#[test]
fn a_second_daemon_does_not_take_a_socket_that_is_already_spoken_for() {
    let _serial = serial_gate();
    let dir = std::env::temp_dir().join(format!(
        "thor-admit-lock-{}-{}",
        std::process::id(),
        DAEMON_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let socket = dir.join("sock");

    // Take the lock the way a live daemon would. The socket itself is left
    // with nobody listening: this is what a daemon whose acceptor has died
    // leaves behind, and the second daemon must not take it over.
    use std::os::unix::io::AsRawFd;
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(dir.join("sock.lock"))
        .unwrap();
    let held = unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    assert_eq!(held, 0, "the test could not take the lock");

    let mut output = Command::new(BIN)
        .arg("daemon")
        .arg("--socket")
        .arg(&socket)
        .arg("--state-dir")
        .arg(&dir)
        .stderr(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("the daemon starts");
    // The daemon must *stop*. A daemon that takes the socket and keeps
    // running would never end this wait, so the wait has its own deadline
    // and the child is killed if it overruns.
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut finished = None;
    loop {
        match output.try_wait() {
            Ok(Some(status)) => {
                finished = Some(status);
                break;
            }
            Ok(None) => {}
            Err(_) => break,
        }
        if Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let Some(status) = finished else {
        let _ = output.kill();
        let _ = output.wait();
        panic!("the second daemon took a socket that was already spoken for, and did not stop");
    };
    let mut errors = String::new();
    if let Some(mut stderr) = output.stderr.take() {
        use std::io::Read;
        let _ = stderr.read_to_string(&mut errors);
    }
    assert!(
        !status.success(),
        "the second daemon started on a socket that was already spoken for"
    );
    assert!(
        errors.contains("already running") || errors.contains("lock"),
        "the refusal was not explained: {errors}"
    );

    let _ = std::fs::remove_dir_all(&dir);
}

/// A stale socket — one whose daemon is gone — must not keep the box from
/// starting a daemon.
#[test]
fn a_stale_socket_does_not_keep_a_daemon_from_starting() {
    let _serial = serial_gate();
    let dir = std::env::temp_dir().join(format!(
        "thor-admit-stale-{}-{}",
        std::process::id(),
        DAEMON_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let socket = dir.join("sock");
    // A socket with nobody listening: bind it, then let the listener go.
    {
        let listener = std::os::unix::net::UnixListener::bind(&socket).unwrap();
        drop(listener);
    }
    assert!(socket.exists(), "the stale socket is there");

    let daemon = DaemonUnderTest::start_named("stale-socket", &[]);
    assert!(
        daemon.status()["leases"].is_array(),
        "the daemon did not come up over the stale socket"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

/// The 04:15 daemon of 2026-11-01, reproduced (round 10, item b).
///
/// The director stopped the old daemon; a client auto-started a new one;
/// it hung on the way up — wedged in `futex_wait_queue` — **holding the
/// socket's lock and never having bound the socket**, beside the stale
/// socket file the old daemon had left. Every later client got "connection
/// refused", and every later daemon was refused with "another thor-admit
/// daemon is already running", until a human killed the wedged process.
///
/// The fix is the order: construct, bind, *then* take the lifetime lock. A
/// daemon that hangs on the way up now holds nothing — no lock to refuse
/// the next daemon with, no bound socket to answer nobody — so the next
/// daemon takes the socket and serves, and the hung one refuses itself
/// when it wakes. The hang is injected through
/// `THOR_ADMIT_TEST_CONSTRUCTION_HANG_MS`, a test seam that sleeps before
/// anything is held or bound.
#[test]
fn a_daemon_that_hangs_on_the_way_up_does_not_wedge_the_socket() {
    let _serial = serial_gate();
    let reserved = DaemonUnderTest::reserve("wedged-start", &["--floor", "1G"]);
    let socket = reserved.state_dir.join("sock");
    // What the box looked like at 04:15: the old daemon gone, its socket
    // file stale, nobody holding the lock.
    {
        let listener = std::os::unix::net::UnixListener::bind(&socket).unwrap();
        drop(listener);
    }

    // The wedged daemon: hung before it constructs, binds or locks.
    let mut wedged = Command::new(BIN)
        .arg("daemon")
        .arg("--socket")
        .arg(&socket)
        .arg("--state-dir")
        .arg(&reserved.state_dir)
        .arg("--gpu-probe")
        .arg("off")
        .env("THOR_ADMIT_TEST_CONSTRUCTION_HANG_MS", "8000")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the wedged daemon starts");
    // It is mid-hang now: the seam sleeps at the very top of the daemon's
    // construction, and two seconds is a wide margin over a process start.
    std::thread::sleep(Duration::from_secs(2));

    // The next daemon takes the socket the wedged one never held, and
    // serves leases as though nothing had happened.
    let daemon = DaemonUnderTest::start(reserved);
    let mut run = leased(&daemon, "after.the.wedge", "1G", &["true"]);
    let status = run.wait().expect("the client finishes");
    let output = output_of(&mut run);
    assert!(
        status.success() && output.contains("admitted after"),
        "a lease did not run on the recovered daemon:\n{output}"
    );

    // The wedged daemon wakes, finds the socket taken, and refuses itself.
    let woken = wait_child_with_deadline(&mut wedged, 20);
    let mut woken_errors = String::new();
    if let Some(mut stderr) = wedged.stderr.take() {
        use std::io::Read;
        let _ = stderr.read_to_string(&mut woken_errors);
    }
    match woken {
        Some(status) => {
            assert!(
                !status.success(),
                "the wedged daemon started anyway, beside the recovered one"
            );
            assert!(
                woken_errors.contains("already running"),
                "the wedged daemon's refusal was not explained:\n{woken_errors}"
            );
        }
        None => {
            let _ = wedged.kill();
            let _ = wedged.wait();
            panic!("the wedged daemon never woke to refuse itself");
        }
    }

    // And the recovered daemon is still the one answering.
    assert!(
        daemon.status()["leases"].is_array(),
        "the recovered daemon stopped answering"
    );
}

/// A daemon that never serves stops itself (round 10, item b's other half).
///
/// The bind now comes before the lock, so a daemon wedging on the way up
/// holds nothing — but a daemon can still wedge *after* the bind, owning a
/// socket that answers nobody. The startup deadline turns that into a
/// bounded window: a daemon that has not begun serving within
/// `--startup-timeout-secs` says why and exits, the kernel drops whatever
/// it holds, and the next client's auto-start takes the socket back.
#[test]
fn a_daemon_that_never_serves_stops_itself() {
    let _serial = serial_gate();
    let dir = std::env::temp_dir().join(format!(
        "thor-admit-startup-{}-{}",
        std::process::id(),
        DAEMON_SERIAL.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut daemon = Command::new(BIN)
        .arg("daemon")
        .arg("--socket")
        .arg(dir.join("sock"))
        .arg("--state-dir")
        .arg(&dir)
        .arg("--gpu-probe")
        .arg("off")
        .arg("--startup-timeout-secs")
        .arg("2")
        .env("THOR_ADMIT_TEST_CONSTRUCTION_HANG_MS", "12000")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the daemon starts");

    // The hang (12 s) outlasts the deadline (2 s): the daemon must stop
    // itself, not sit on the box.
    let stopped = wait_child_with_deadline(&mut daemon, 10);
    let mut errors = String::new();
    if let Some(mut stderr) = daemon.stderr.take() {
        use std::io::Read;
        let _ = stderr.read_to_string(&mut errors);
    }
    match stopped {
        Some(status) => {
            assert!(
                !status.success(),
                "the daemon that never served exited as a success"
            );
            assert!(
                errors.contains("did not begin serving"),
                "the startup timeout did not explain itself:\n{errors}"
            );
        }
        None => {
            let _ = daemon.kill();
            let _ = daemon.wait();
            panic!("the daemon sat past its startup deadline without stopping");
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn three_thirty_gigabyte_hogs_are_serialised() {
    let _serial = serial_gate();
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
    // The test needs a window wide enough to be a real test: the floor sits
    // half way between "one hog fits" and "two do not", so the window is
    // half the hog. Below eight gibibytes the window is too narrow to say
    // anything, and the box is too busy for the brief's scale anyway.
    if hog_gb < 8 {
        eprintln!(
            "skipping: the box has only {} MiB free, so a {hog_gb} GiB hog would leave a \
             window too narrow to test; the box is busy",
            mem_available() / (1024 * 1024)
        );
        return;
    }
    // The box's own state, measured now, so the numbers in the failure
    // message say what the box was doing.
    let available_at_start = mem_available();
    // A floor half way up the window lets one hog run and refuses the
    // second: the daemon charges the running hog's reservation, so the
    // second hog is refused while the first is still growing. The box is
    // shared, though, and a co-tenant that frees memory mid-test raises
    // MemAvailable the same as a release would: on 2026-11-01 an eleven
    // GiB co-tenant drop admitted the second hog *lawfully* (the rule held
    // at the grant — projected cleared peak + floor — and the box stayed
    // above the allowed line below), and the strict "one at a time" claim
    // broke. The +10 GiB margin keeps the claim honest while a co-tenant
    // drops up to twenty-five GiB; the daemon's own guarantee is the
    // allowed line, checked separately.
    //
    // The predecessor's own exit is a bigger drop than that margin
    // covers: a hog that ends frees thirty GiB of pages about a second
    // before the daemon processes its release, so the second hog can be
    // granted while the first lease is still listed. That is legal (the
    // pages came back; the floor held) and it is why the lease *list* is
    // not asserted below — the grant is.
    let floor = floor_for_one_hog(available_at_start, hog_bytes) + 10 * GIB;
    let daemon = DaemonUnderTest::start_named("three-thirty-gib-hogs", &[
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

    // The claim, checked where the daemon makes it: every lease it granted
    // had room for its promise above the floor. This is "the box never held
    // two hogs at once", measured on the daemon's own numbers.
    //
    // The lease *list* is not the claim. A hog that exits frees its pages
    // before the client sends its release, about a second later, so
    // MemAvailable rises by the hog's full size while the lease is still
    // listed; the next hog is then granted, lawfully, because the freed
    // memory is honestly available. On 2026-11-01 a *co-tenant* drop of
    // eleven GiB did the same thing, and on this box the test's own
    // predecessor did it with thirty GiB — more than the +10 GiB margin
    // was sized for. The daemon's guarantee is the allowed line below, and
    // the grant check here; the lease count is reported, not asserted.
    for line in daemon.log().lines() {
        if !line.contains("\"lease.granted\"") {
            continue;
        }
        let event: Value = serde_json::from_str(line).expect("a log line that is not json");
        let available = event["mem_available_bytes"]
            .as_u64()
            .expect("a grant without the memory it saw");
        let peak = event["peak_bytes"]
            .as_u64()
            .expect("a grant without the promise it made");
        assert!(
            available.saturating_sub(peak) >= floor,
            "the daemon granted a lease that did not clear its floor: {} MiB free, a \
             {hog_gb} GiB promise, a floor of {} MiB; the log was:\n{}",
            available / (1024 * 1024),
            floor / (1024 * 1024),
            daemon.log()
        );
    }
    // One hog at a time: the box never came near empty. The measure is
    // relative — the box's own free memory at the start of the test — so
    // the answer does not depend on how busy the box was when the test ran.
    // A hog of its own size may be taken; the margin is everything else
    // that was running.
    let allowed = available_at_start
        .saturating_sub(hog_bytes)
        .saturating_sub(4 * GIB);
    assert!(
        min_available >= allowed,
        "the box fell to {} MiB free, which is below the {} MiB it was allowed to fall to \
         (it started at {} MiB free with a {hog_gb} GiB hog)",
        min_available / (1024 * 1024),
        allowed / (1024 * 1024),
        available_at_start / (1024 * 1024),
    );
    for text in &finished {
        assert!(
            text.contains("hog: done"),
            "a hog did not finish:\n{text}"
        );
    }
    eprintln!(
        "serialisation: {hog_gb} GiB hogs, floor {}, the lease list showed {max_active} at \
         once, the box went from {} MiB free to {} MiB free",
        floor,
        available_at_start / (1024 * 1024),
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
    let _serial = serial_gate();
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
    // The emergency floor is placed relative to the hog, not at a fixed
    // number of gibibytes. The real floor is 8 GiB, and driving the box to
    // 8 GiB free would need a hundred gibibytes of allocation, which is not
    // safe on a box that is also running a seat's work. The floor here is
    // (available - hog + 2 GiB), so the same rule fires once the runaway
    // has taken all but two gibibytes of its memory — and it fires with the
    // whole box still free, because the hog was sized to leave a margin.
    //
    // The two gibibytes of slack matter twice over: the box's other work may
    // free memory while the hog is growing (which would move the crossing
    // point), and the daemon reads the hog's resident set only once a
    // second, so the watchdog has to find it already large.
    let hog_bytes = hog_gb * GIB;
    let available_at_start = mem_available();
    let emergency = available_at_start
        .saturating_sub(hog_bytes)
        .saturating_add(2 * GIB)
        .max(GIB);
    let daemon = DaemonUnderTest::start_named("watchdog-on-the-real-box", &[
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
    let mut terminated_at_available = None;
    let mut min_available = u64::MAX;
    while Instant::now() < deadline {
        let available = mem_available();
        min_available = min_available.min(available);
        // The event carries the free memory at the moment of the termination.
        for line in daemon.log().lines() {
            if !line.contains("\"watchdog.terminated\"") {
                continue;
            }
            if let Ok(event) = serde_json::from_str::<Value>(line) {
                terminated_at_available = event["mem_available_bytes"].as_u64();
            }
            break;
        }
        if terminated_at_available.is_some() {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }

    let Some(available_at_stop) = terminated_at_available else {
        let _ = hog.kill();
        let _ = hog.wait();
        panic!("the watchdog did not terminate the hog; the log was:\n{}", daemon.log());
    };

    // The whole point: the box was acted on while there was still a lot of
    // memory free — long before the kernel's OOM killer would have run.
    assert!(
        available_at_stop > 2 * GIB,
        "the hog was terminated with only {} MiB free, which is inside the OOM zone",
        available_at_stop / (1024 * 1024)
    );
    assert_eq!(
        oom_kills(),
        oom_before,
        "the kernel's OOM killer fired; the watchdog was too late"
    );

    // The hog must actually die: the watchdog terminated it (SIGTERM, not a
    // stop — a stopped process keeps its memory, which on this box buys
    // nothing), so the client reaps it, releases the lease and exits.
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut died = false;
    while Instant::now() < deadline {
        if hog.try_wait().ok().flatten().is_some() {
            died = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        died,
        "the runaway was terminated but never died; the log was:\n{}",
        daemon.log()
    );
    // And the memory it held is booked back: the lease is released only
    // after the client reaped the process, so the daemon's picture and the
    // kernel's agree again.
    assert!(
        wait_until(20, || daemon.status()["leases"]
            .as_array()
            .map(|leases| leases.is_empty())
            .unwrap_or(false)),
        "the terminated lease was not released; the log was:\n{}",
        daemon.log()
    );
    eprintln!(
        "watchdog: the runaway was terminated with {} MiB free (the emergency floor was \
         {} MiB) and died, with the kernel's OOM killer firing {} times; the box's \
         lowest reading was {} MiB",
        available_at_stop / (1024 * 1024),
        emergency / (1024 * 1024),
        oom_kills() - oom_before,
        min_available / (1024 * 1024),
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
/// the daemon, the hog, the SIGTERM and the timing are all real; only the
/// number the daemon reads is written by the test.
///
/// The watchdog terminates (never stops: the box has no swap, so a stopped
/// process keeps its memory and the emergency gets worse while it waits).
#[test]
fn the_watchdog_stops_a_runaway_before_the_memory_runs_out() {
    let _serial = serial_gate();
    let total = 122 * GIB;
    // The daemon's own default emergency floor: the brief's 8 GiB.
    let floor = 8 * GIB;
    let scratch =
        std::env::temp_dir().join(format!("thor-admit-lowwater-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let meminfo = scratch.join("meminfo");
    write_meminfo(&meminfo, total, 100 * GIB);

    let daemon = DaemonUnderTest::start_named("watchdog-on-a-scripted-curve", &["--meminfo", meminfo.to_str().unwrap()]);
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
            if !line.contains("\"watchdog.terminated\"") {
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
        panic!("the watchdog did not terminate the hog; the log was:\n{}", daemon.log());
    };

    // Let the curve finish: it has to reach the danger zone *after* the
    // stop, or the test would only prove that the line was never crossed.
    let _ = writer.join();
    let curve = steps.lock().unwrap().clone();
    let lowest = curve.last().map(|(available, _)| *available).unwrap_or(0);

    // The brief's line: the hog was terminated while there was still more
    // than 2 GiB free.
    assert!(
        available_at_stop > 2 * GIB,
        "the hog was terminated with only {} MiB free, which is inside the OOM zone",
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
    // termination: the daemon acted before the box was in trouble.
    assert!(
        lowest <= 2 * GIB,
        "the curve only reached {} MiB free, so the danger zone was never reached",
        lowest / (1024 * 1024)
    );

    // The hog must actually die: a termination is not a stop. The client
    // reaps the SIGTERM'd process, releases the lease and exits.
    let mut hog_pid = 0i64;
    {
        let status = daemon.status();
        if let Some(lease) = status["leases"].as_array().and_then(|leases| leases.first()) {
            hog_pid = lease["pgid"].as_i64().unwrap_or(0);
        }
    }
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut died = false;
    while Instant::now() < deadline {
        if hog.try_wait().ok().flatten().is_some() {
            died = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        died,
        "the runaway was terminated but never died; the log was:\n{}",
        daemon.log()
    );
    assert_eq!(
        oom_kills(),
        oom_before,
        "the kernel's OOM killer fired; the watchdog was too late"
    );

    // And nothing is left behind. A hog that was terminated and never died
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
        panic!("the hog {hog_pid} was still there after the watchdog terminated it");
    }
    // And the daemon let go of the reservation only after the process was
    // reaped: the memory is back when the process is, not before.
    assert!(
        wait_until(20, || daemon.status()["leases"]
            .as_array()
            .map(|leases| leases.is_empty())
            .unwrap_or(false)),
        "the terminated lease was never released; the log was:\n{}",
        daemon.log()
    );

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
        "low water: the hog was terminated with {} MiB free (the floor was {} MiB) and the \
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
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("dead-client", &["--floor", "1G"]);

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

/// The lease-holder helper: a client whose silence is up to the test.
fn lease_holder(mode: &str, daemon: &DaemonUnderTest, label: &str, seconds: f64) -> Child {
    Command::new("python3")
        .arg(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/lease_holder.py"))
        .arg(mode)
        .arg(&daemon.socket)
        .arg(label)
        .arg(seconds.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the lease holder starts")
}

/// A client that holds its lease and never says another word is stuck, and
/// a stuck client's lock never drops: the reservation would be charged
/// forever. The heartbeat is the other half of the truth — the lock says
/// the client is not dead, the heartbeat says it is not stuck — and the
/// daemon gives a silent client a grace period before it acts (Hy4's
/// fourth failure mode).
#[test]
fn a_silent_client_loses_its_lease() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("silent-client", &[
        "--floor",
        "1G",
        "--heartbeat-grace-secs",
        "2",
    ]);

    let mut holder = lease_holder("silent", &daemon, "stuck.holder", 60.0);
    let held = wait_until(15, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(held, "the holder never took the lease: {}", daemon.log());

    // It is silent for far longer than the grace period.
    let gone = wait_until(20, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| leases.is_empty())
            .unwrap_or(false)
    });
    assert!(
        gone,
        "the silent client kept its lease; the log was:\n{}",
        daemon.log()
    );
    assert!(
        daemon.log().contains("lease.stale_client"),
        "the daemon never named the silence: {}",
        daemon.log()
    );
    // And the stuck client itself was asked to leave: its exit drops the
    // lock, which is what actually released the lease.
    assert!(
        daemon.log().contains("lease.stale_client_signalled"),
        "the stuck client was never signalled: {}",
        daemon.log()
    );
    let _ = holder.kill();
    let _ = holder.wait();
}

/// A lock can outlive its client: the file descriptor is inherited by a
/// child, the client exits, and the lock is held with nobody left to
/// release it. The daemon must not charge that reservation forever — and it
/// tells this case from a stuck client by the client's own pid, which the
/// socket's credentials put beyond argument.
#[test]
fn an_orphaned_lock_cannot_hold_a_reservation_forever() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("orphaned-lock", &[
        "--floor",
        "1G",
        "--heartbeat-grace-secs",
        "2",
    ]);

    let mut holder = lease_holder("orphan", &daemon, "orphan.holder", 60.0);
    let held = wait_until(15, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(held, "the holder never took the lease: {}", daemon.log());
    // The holder has already exited; only the inherited descriptor remains.
    let _ = holder.wait();

    let gone = wait_until(20, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| leases.is_empty())
            .unwrap_or(false)
    });
    assert!(
        gone,
        "an orphaned lock kept its reservation; the log was:\n{}",
        daemon.log()
    );
    assert!(
        daemon.log().contains("lease.force_released"),
        "the daemon never took the orphaned lease back: {}",
        daemon.log()
    );
}

/// A client that heartbeats keeps its lease, however long it holds it.
#[test]
fn a_heartbeating_client_keeps_its_lease() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("heartbeat-client", &[
        "--floor",
        "1G",
        "--heartbeat-grace-secs",
        "2",
    ]);

    // Ten seconds of holding with heartbeats every half-second: five times
    // the grace period, which a silent client does not survive.
    let mut holder = lease_holder("heartbeat", &daemon, "healthy.holder", 10.0);
    let held = wait_until(15, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(held, "the holder never took the lease: {}", daemon.log());

    std::thread::sleep(Duration::from_secs(8));
    let status = daemon.status();
    assert_eq!(
        status["leases"].as_array().map(|l| l.len()).unwrap_or(0),
        1,
        "the heartbeating client lost its lease; the log was:\n{}",
        daemon.log()
    );
    assert!(
        !daemon.log().contains("lease.stale_client"),
        "the daemon called a heartbeating client silent: {}",
        daemon.log()
    );

    let _ = holder.kill();
    let _ = holder.wait();
}

/// A model is loaded once per box, not once per seat (round 8, item 3: the
/// 22:09 incident had two d1-2B llama-servers running because two seats
/// each started one). The second seat that asks gets the first's port and
/// runs nothing; when the first goes away, the server goes with it and the
/// next ask starts a fresh one.
#[test]
fn a_model_is_loaded_once_per_box() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("serve-once", &["--floor", "1G"]);
    // A port nobody is using.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);

    let serve_args: Vec<String> = vec![
        "serve".to_string(),
        "test-model".to_string(),
        "--socket".to_string(),
        daemon.socket.display().to_string(),
        "--port".to_string(),
        port.to_string(),
        "--peak".to_string(),
        "1G".to_string(),
        "--".to_string(),
        "python3".to_string(),
        "-m".to_string(),
        "http.server".to_string(),
        port.to_string(),
    ];

    // The first seat starts the "model server" and stays in front of it.
    // The port answering is not enough to proceed on — the registry entry
    // is what the second seat reads, and the serve watching the port writes
    // that a moment after it first answers — so this waits for both.
    let registered = || {
        thor_admit::serve::port_answers(port)
            && std::fs::read_to_string(daemon.state_dir.join("servers.json"))
                .map(|text| text.contains("\"model\":\"test-model\""))
                .unwrap_or(false)
    };
    let mut first = Command::new(BIN)
        .args(&serve_args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the first serve starts");
    let came_up = wait_until(20, registered);
    assert!(
        came_up,
        "the model server never answered or was never registered; the log was:\n{}",
        daemon.log()
    );

    // The second seat asks for the same model: it gets the port, exits
    // clean, and starts nothing of its own.
    let second = Command::new(BIN)
        .args(&serve_args)
        .output()
        .expect("the second serve runs");
    assert!(
        second.status.success(),
        "the second serve failed: {}",
        String::from_utf8_lossy(&second.stderr)
    );
    let answered = String::from_utf8_lossy(&second.stdout);
    assert!(
        answered.contains("is served on port"),
        "the second serve did not return the port: {answered}"
    );
    // One model, one entry, one server.
    let registry = std::fs::read_to_string(daemon.state_dir.join("servers.json"))
        .unwrap_or_default();
    let entries = registry
        .lines()
        .filter(|line| line.contains("\"model\":\"test-model\""))
        .count();
    assert_eq!(entries, 1, "the registry has {entries} entries:\n{registry}");

    // The first seat goes away: its server goes with it (the lease cleans
    // up after the client), the port stops answering, and the next ask
    // starts a fresh one.
    let _ = first.kill();
    let _ = first.wait();
    let went_away = wait_until(15, || !thor_admit::serve::port_answers(port));
    assert!(
        went_away,
        "the server outlived the seat that started it; the log was:\n{}",
        daemon.log()
    );

    let mut third = Command::new(BIN)
        .args(&serve_args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the third serve starts");
    let back = wait_until(20, || thor_admit::serve::port_answers(port));
    assert!(back, "a fresh server was never started: {}", daemon.log());

    // Kill the seat and wait for its server to go with it. Killing the
    // client alone is not enough as a cleanup: the daemon reaps the orphan
    // on its next tick, and a test that tears its daemon down in the same
    // instant leaves the server running on the box — every run of this
    // test used to leak one idle `http.server` that way (37 were found
    // running on 2026-11-01).
    let _ = third.kill();
    let _ = third.wait();
    let gone = wait_until(15, || !thor_admit::serve::port_answers(port));
    assert!(gone, "the server outlived the test: {}", daemon.log());
}

/// The 01:19 incident (round 9, item e): three d1-2B servers ran at once as
/// `d1-2B`, `d1-2B-baseline` and `d1-2B-batch`, because the registry deduped
/// by the name a seat typed. The registry is keyed on the model file
/// (path + hash) and the command's other flags: the same model file with
/// the same flags is one server under any name, and only flags that really
/// differ ask for their own.
#[test]
fn the_same_model_under_two_names_is_loaded_once() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("serve-by-model-file", &["--floor", "1G"]);
    // A stand-in model file: the registry hashes its contents, so the key
    // is the file's, not the seat's word.
    let model = daemon.state_dir.join("d1-2B.gguf");
    std::fs::write(&model, b"the weights, as far as a test needs them").unwrap();
    // A stand-in server that answers the port and stays up, with the model
    // file named the way the real servers name it (`-m PATH`). The shell
    // script ignores its extra arguments, so the `-m` pair is exactly what
    // the key reads and nothing else happens with it.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let serve = |model_name: &str, port: u16, extra: &[&str]| -> Vec<String> {
        let mut args = vec![
            "serve".to_string(),
            model_name.to_string(),
            "--socket".to_string(),
            daemon.socket.display().to_string(),
            "--port".to_string(),
            port.to_string(),
            "--peak".to_string(),
            "1G".to_string(),
            "--".to_string(),
            "sh".to_string(),
            "-c".to_string(),
            format!("exec python3 -m http.server {port} --bind 127.0.0.1"),
            "serve".to_string(),
            "-m".to_string(),
            model.display().to_string(),
        ];
        args.extend(extra.iter().map(|token| token.to_string()));
        args
    };

    // The first seat starts the server under the plain name.
    let mut first = Command::new(BIN)
        .args(serve("d1-2B", port, &[]))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the first serve starts");
    let came_up = wait_until(20, || {
        thor_admit::serve::port_answers(port)
            && std::fs::read_to_string(daemon.state_dir.join("servers.json"))
                .map(|text| text.contains("\"model\":\"d1-2B\""))
                .unwrap_or(false)
    });
    assert!(came_up, "the server never answered; the log:\n{}", daemon.log());

    // The second seat asks under another name — `d1-2B-baseline` — with the
    // same model file and the same flags. It gets the first's port and runs
    // nothing: one model, one server, whatever the seats call it.
    let second = Command::new(BIN)
        .args(serve("d1-2B-baseline", port, &[]))
        .output()
        .expect("the second serve runs");
    let answered = String::from_utf8_lossy(&second.stdout);
    assert!(
        answered.contains("is served on port"),
        "the renamed ask did not get the port: {answered}"
    );
    let registry = std::fs::read_to_string(daemon.state_dir.join("servers.json")).unwrap();
    let entries = registry
        .lines()
        .filter(|line| line.contains("\"port\""))
        .count();
    assert_eq!(entries, 1, "the registry has {entries} entries:\n{registry}");

    // The third seat really does differ — a batch flag the first server was
    // not started with — so it is its own variant and its own server, and
    // it says which one it is rather than silently sharing the wrong one.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let other_port = listener.local_addr().unwrap().port();
    drop(listener);
    let mut third = Command::new(BIN)
        .args(serve("d1-2B-batch", other_port, &["--parallel", "4"]))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the third serve starts");
    let variant_came_up = wait_until(20, || {
        thor_admit::serve::port_answers(other_port)
            && std::fs::read_to_string(daemon.state_dir.join("servers.json"))
                .map(|text| text.matches("\"port\"").count() >= 2)
                .unwrap_or(false)
    });
    assert!(
        variant_came_up,
        "a variant with different flags did not start its own server; the log:\n{}",
        daemon.log()
    );

    // Kill the seats and wait for both servers to go with them: killing
    // the client alone leaves the orphan to the daemon's next tick, and a
    // test tearing its daemon down in the same instant leaks the server.
    let _ = first.kill();
    let _ = first.wait();
    let _ = third.kill();
    let _ = third.wait();
    let gone = wait_until(15, || {
        !thor_admit::serve::port_answers(port) && !thor_admit::serve::port_answers(other_port)
    });
    assert!(gone, "a server outlived the test; the log:\n{}", daemon.log());
}

/// The ledger names each player, not only the tier it played in, and keeps
/// the flow signal a publisher writes — recorded, never computed, and never
/// acted on.
#[test]
fn the_ledger_names_each_label_and_keeps_the_published_flow() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("ledger-by-label", &["--floor", "1G"]);

    // A publisher speaks: the reflex-shaped writer the design says will
    // publish confidence and rate of change to flow.json.
    std::fs::write(
        daemon.state_dir.join("flow.json"),
        r#"{"confidence": 0.91, "rate_of_change": 0.01}"#,
    )
    .unwrap();

    // A labelled lease runs for a few seconds.
    let mut run = leased(&daemon, "d1-critic", "1G", &["sleep", "3"]);
    let _ = run.wait();
    let _ = output_of(&mut run);

    let output = Command::new(BIN)
        .arg("ledger")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--json")
        .output()
        .expect("the ledger runs");
    let value: Value = serde_json::from_slice(&output.stdout).expect("the ledger is JSON");
    let hours = value["ledger"].as_array().expect("the hours are a list");
    let bucket = hours.last().expect("the hour being kept is there");
    let critic = bucket["by_label"]["d1-critic"]
        .as_object()
        .expect("the label is booked");
    let running_s = critic["running_s"].as_f64().unwrap_or(0.0);
    assert!(
        running_s >= 2.0,
        "the critic's label ran for {running_s}s in the ledger: {bucket}"
    );
    let flow = bucket["flow"].as_object().expect("the flow hour is there");
    assert!(
        flow["samples"].as_u64().unwrap_or(0) > 0,
        "the published flow signal was not recorded: {flow:?}"
    );
    assert_eq!(flow["sign"].as_str(), Some("steady"));
}

#[test]
fn the_daemon_costs_almost_nothing() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("daemon-overhead", &["--floor", "1G"]);
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
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("learned-peak", &["--floor", "1G"]);

    // `--peak auto` refuses to guess until the label has three runs, so the
    // teaching is three runs with an explicit peak. Every teaching run also
    // has to outlast the five-second line: a run that finishes in no time
    // did no work, and its peak teaches nothing.
    let mut refused = leased(&daemon, "auto-label", "auto", &["true"]);
    let status = refused.wait().expect("the client finishes");
    let output = output_of(&mut refused);
    assert!(!status.success(), "the client should have been refused");
    assert!(
        output.contains("no history for the label"),
        "the refusal was not explained:\n{output}"
    );

    // With one or two runs the daemon still refuses — a p95 of so few runs
    // under-reserves a shifted workload — and says so differently.
    let mut under_taught = leased(&daemon, "auto-label", "2G", &[HOG, "--bytes", "2G", "--hold", "6"]);
    let _ = under_taught.wait();
    let _ = output_of(&mut under_taught);
    let mut still_refused = leased(&daemon, "auto-label", "auto", &["true"]);
    let _ = still_refused.wait();
    let output = output_of(&mut still_refused);
    assert!(
        output.contains("needs 3") && output.contains("run(s) for the label"),
        "the too-few-runs refusal was not explained:\n{output}"
    );

    for _ in 0..2 {
        let mut run = leased(&daemon, "auto-label", "2G", &[HOG, "--bytes", "2G", "--hold", "6"]);
        let _ = run.wait();
        let _ = output_of(&mut run);
    }

    let history = daemon.history();
    assert_eq!(history.len(), 3, "the runs were recorded");
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

/// The auto peak reserves the larger of the p95 and the last run: a label
/// whose last run was far heavier than its history must not be reserved at
/// the p95 of the quiet runs (Hy4's second failure mode).
#[test]
fn an_auto_peak_reserves_the_last_run_when_it_outran_the_p95() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("auto-takes-the-last", &["--floor", "1G"]);

    // Three quiet runs, then one heavy one. The p95 of [2, 2, 2, 6] GiB is
    // about 5.4 GiB; the last run took a measured ~6 GiB. The runs outlast
    // the five-second line so they are allowed to teach.
    for gigabytes in [2u64, 2, 2, 6] {
        let mut run = leased(
            &daemon,
            "shifting-label",
            "6G",
            &[HOG, "--bytes", &format!("{gigabytes}G"), "--hold", "6"],
        );
        let _ = run.wait();
        let _ = output_of(&mut run);
    }

    let mut last = daemon.history();
    let last_measured = last
        .pop()
        .and_then(|record| record["peak_rss_bytes"].as_u64())
        .expect("the heavy run was recorded");
    assert!(last_measured > 5 * GIB, "the heavy run took {last_measured}");

    // The next auto run is reserved at no less than the last run's peak.
    let mut next = leased(&daemon, "shifting-label", "auto", &[HOG, "--bytes", "2G", "--hold", "1"]);
    let output = {
        let _ = next.wait();
        output_of(&mut next)
    };
    assert!(output.contains("admitted after"), "auto was refused:\n{output}");
    let granted = daemon
        .log()
        .lines()
        .filter(|line| line.contains("\"lease.granted\"") && line.contains("shifting-label"))
        .last()
        .and_then(|line| serde_json::from_str::<Value>(line).ok())
        .and_then(|event| event["peak_bytes"].as_u64())
        .expect("the auto run was granted");
    assert!(
        granted >= last_measured,
        "the auto run was reserved {granted} bytes, below the last run's \
         {last_measured} bytes — the p95 alone under-reserved it"
    );
}

/// The 2026-11-01 incident (round 9, item c): a lease's reserve showed as
/// **3.6M** for an Infinigen coarse stage, because the history held 25
/// no-op records — every one of them under 30 ms and under 4 MB — and the
/// daemon trusted them. Two halves must now hold:
///
/// * records like that cannot teach, however many of them there are, and a
///   live no-op run (a wrapper invoked with nothing to do, exit 0 in
///   milliseconds) writes nothing to the history — the log says why;
/// * after the operator edits the file by hand, `thor-admit reload` makes
///   the running daemon see the edit, without a restart.
#[test]
fn a_no_op_run_cannot_teach_the_reserve() {
    let _serial = serial_gate();
    // The history is seeded before the daemon starts, with the exact shape
    // of the 25 records the director removed at 00:50: `infinigen.*.coarse`,
    // ~3.8 MB, under 30 ms, no exit status.
    let reserved = DaemonUnderTest::reserve("no-op-cannot-teach", &["--floor", "1G"]);
    let label = "infinigen.mountain.coarse";
    let mut bogus = String::new();
    for biome in 0..25 {
        let record = serde_json::json!({
            "at": format!("2026-11-01T08:47:{:02}Z", biome),
            "kind": label, "label": label, "host": "thor",
            "peak_rss_bytes": 3_801_088_u64,
            "peak_gpu_bytes": null, "gpu_visible": true,
            "duration_s": 0.027, "mem_total_bytes": 131_856_928_768_u64,
            "floor_bytes": 26_843_545_600_u64,
            "basis": "measured", "source": "thor-admit",
            "peak_source": "rusage",
        });
        bogus.push_str(&record.to_string());
        bogus.push('\n');
    }
    std::fs::write(reserved.state_dir.join("peaks.jsonl"), bogus).unwrap();
    let daemon = DaemonUnderTest::start(reserved);

    // 3.6 MB worth of no-ops in the file, and `--peak auto` still refuses:
    // the label has no runs that may teach.
    let mut refused = leased(&daemon, label, "auto", &["true"]);
    let _ = refused.wait();
    let output = output_of(&mut refused);
    assert!(
        output.contains("no history for the label"),
        "25 no-op records taught a reserve:\n{output}"
    );

    // A live no-op run — exit 0, gone in milliseconds — does not land in
    // the history, and the log names the reason.
    let mut noop = leased(&daemon, label, "1G", &["true"]);
    let _ = noop.wait();
    let _ = output_of(&mut noop);
    let mut failed = leased(&daemon, label, "1G", &["sh", "-c", "exit 3"]);
    let _ = failed.wait();
    let _ = output_of(&mut failed);
    let log = daemon.log();
    assert!(
        log.lines().any(|line| line.contains("\"history.not_learned\"")
            && line.contains("under the")),
        "the short no-op was not named in the log:\n{log}"
    );
    assert!(
        log.lines().any(|line| line.contains("\"history.not_learned\"")
            && line.contains("exit 3")),
        "the failed run was not named in the log:\n{log}"
    );
    assert_eq!(
        daemon.history().len(),
        25,
        "the live no-op runs appended nothing; the file holds only the \
         seeded records: {:?}",
        daemon.history().len()
    );

    // The operator teaches the label by hand — three real records, clean
    // exits, real durations — and the running daemon sees them after a
    // reload. No restart, no lease interrupted.
    let mut taught = String::new();
    for peak in [2, 2, 2] {
        let record = serde_json::json!({
            "at": "2026-11-01T09:00:00Z",
            "kind": label, "label": label, "host": "thor",
            "peak_rss_bytes": peak * GIB,
            "peak_gpu_bytes": null, "gpu_visible": true,
            "duration_s": 52.9, "mem_total_bytes": 131_856_928_768_u64,
            "floor_bytes": 26_843_545_600_u64,
            "basis": "measured", "source": "thor-admit",
            "peak_source": "rusage", "exit_code": 0,
        });
        taught.push_str(&record.to_string());
        taught.push('\n');
    }
    std::fs::write(daemon.state_dir.join("peaks.jsonl"), taught).unwrap();
    let reloaded = Command::new(BIN)
        .arg("reload")
        .arg("--socket")
        .arg(&daemon.socket)
        .output()
        .expect("the reload runs");
    assert!(
        String::from_utf8_lossy(&reloaded.stdout).contains("3 peak records"),
        "the reload did not report the new history: {}",
        String::from_utf8_lossy(&reloaded.stdout)
    );

    let mut auto = leased(&daemon, label, "auto", &[HOG, "--bytes", "1G", "--hold", "1"]);
    let output = {
        let _ = auto.wait();
        output_of(&mut auto)
    };
    assert!(
        output.contains("admitted after"),
        "the hand-taught history was not used after the reload:\n{output}"
    );
    let granted = daemon
        .log()
        .lines()
        .filter(|line| line.contains("\"lease.granted\"") && line.contains(label))
        .last()
        .and_then(|line| serde_json::from_str::<Value>(line).ok())
        .and_then(|event| event["peak_bytes"].as_u64())
        .expect("the auto run was granted");
    assert!(
        granted >= 2 * GIB,
        "the auto run was reserved {granted} bytes, below what the hand-taught \
         history says the label costs"
    );
}

/// SIGHUP reloads too, and what the reload drops stays dropped: a daemon
/// that has already learned a label keeps its reserve when no-op records
/// are added to the file behind its back — the director's 00:50 cleanup,
/// made a fact of the daemon's memory rather than a wish about the file.
#[test]
fn a_sighup_reload_drops_what_the_operator_removed() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("sighup-reload", &["--floor", "1G"]);
    let label = "infinigen.forest.render";

    // Taught the honest way: three real runs.
    for _ in 0..3 {
        let mut run = leased(&daemon, label, "2G", &[HOG, "--bytes", "2G", "--hold", "6"]);
        let _ = run.wait();
        let _ = output_of(&mut run);
    }
    let mut auto = leased(&daemon, label, "auto", &[HOG, "--bytes", "1G", "--hold", "1"]);
    let output = {
        let _ = auto.wait();
        output_of(&mut auto)
    };
    assert!(output.contains("admitted after"), "auto was refused:\n{output}");

    // No-op records appear in the file — the shape the wrapper wrote before
    // the fix — and SIGHUP makes the daemon re-read the file. The reserve
    // does not move: the no-ops are not runs.
    let noop = serde_json::json!({
        "at": "2026-11-01T10:00:00Z",
        "kind": label, "label": label, "host": "thor",
        "peak_rss_bytes": 3_670_000_u64,
        "peak_gpu_bytes": null, "gpu_visible": true,
        "duration_s": 0.4, "mem_total_bytes": 131_856_928_768_u64,
        "floor_bytes": 26_843_545_600_u64,
        "basis": "measured", "source": "thor-admit",
        "peak_source": "rusage", "exit_code": 0,
    });
    let history_path = daemon.state_dir.join("peaks.jsonl");
    let mut text = std::fs::read_to_string(&history_path).unwrap();
    text.push_str(&noop.to_string());
    text.push('\n');
    std::fs::write(&history_path, text).unwrap();

    let signalled = unsafe { libc::kill(daemon.child.id() as i32, libc::SIGHUP) == 0 };
    assert!(signalled, "the SIGHUP was not sent");
    let reloaded = wait_until(10, || daemon.log().contains("\"daemon.reloaded\""));
    assert!(reloaded, "the SIGHUP did not reload the daemon:\n{}", daemon.log());

    let mut again = leased(&daemon, label, "auto", &[HOG, "--bytes", "1G", "--hold", "1"]);
    let output = {
        let _ = again.wait();
        output_of(&mut again)
    };
    assert!(output.contains("admitted after"), "auto was refused:\n{output}");
    let granted = daemon
        .log()
        .lines()
        .filter(|line| line.contains("\"lease.granted\"") && line.contains(label))
        .last()
        .and_then(|line| serde_json::from_str::<Value>(line).ok())
        .and_then(|event| event["peak_bytes"].as_u64())
        .expect("the auto run was granted");
    assert!(
        granted >= 2 * GIB,
        "a no-op record lowered the reserve to {granted} bytes after the reload"
    );
}

/// A lease that outruns its reservation is logged, and its measured peak is
/// written to the history while the lease is still running — not only when
/// it ends.
#[test]
fn an_overrunning_lease_is_logged_and_written_at_once() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("overrun", &["--floor", "1G"]);

    // Reserved 1 GiB; takes 3 GiB.
    let mut hog = leased(&daemon, "under.reserved", "1G", &[HOG, "--bytes", "3G", "--hold", "8"]);

    let saw_event = wait_until(20, || {
        daemon
            .log()
            .lines()
            .any(|line| line.contains("\"lease.underreserved\""))
    });
    assert!(
        saw_event,
        "the over-run was not logged; the log was:\n{}",
        daemon.log()
    );
    // The interim record is in the history while the lease still holds.
    let interim = wait_until(10, || {
        daemon
            .history()
            .iter()
            .any(|record| record["peak_source"] == "overrun")
    });
    assert!(
        interim,
        "the over-running peak was not written while the lease ran; the history was {:?}",
        daemon.history()
    );

    let _ = hog.wait();
    let _ = output_of(&mut hog);

    // And the final record is there too, with the client's own measurement.
    let history = daemon.history();
    assert!(
        history
            .iter()
            .any(|record| record["peak_source"] == "rusage"),
        "the finished lease's peak was not recorded: {history:?}"
    );
}

#[test]
fn the_stop_command_stops_the_daemon() {
    let _serial = serial_gate();
    let mut daemon = DaemonUnderTest::start_named("stop-command", &["--floor", "1G"]);

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
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("refused-lease", &["--floor", "1G"]);
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
    let _serial = serial_gate();
    // The floor and the reservation are derived from a **held-still** view
    // of the box, so the test says what it means whatever else is running.
    // The box's free memory moves by twenty-odd gibibytes while a sweep
    // renders, and the queue's order must not depend on that. The frozen
    // view is a busy box: a hundred gibibytes free of a hundred and
    // twenty-two.
    let total = mem_total();
    let available = 100 * GIB;
    let reservation = 40 * GIB;
    // The floor is placed so that a lease of `reservation` does not fit:
    // 100 - 40 = 60 GiB is left, and the floor is 80 GiB.
    let floor = available - reservation / 2;
    let daemon = frozen_memory_daemon(
        "queue-by-priority",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
        total,
        available,
    );
    let peak = format!("{}G", reservation / GIB);

    // The arrivals are waited for, not slept past: a box under load delays
    // a client's connect by more than any fixed sleep, and the FIFO half of
    // the assertion only means something if "low" really arrived first.
    let queued_labels = |daemon: &DaemonUnderTest| -> Vec<String> {
        daemon.status()["queue"]
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .map(|item| item["label"].as_str().unwrap_or("?").to_string())
                    .collect()
            })
            .unwrap_or_default()
    };
    let low = leased_with_priority(&daemon, "low", &peak, 0, &["sleep", "6"]);
    assert!(
        wait_until(20, || queued_labels(&daemon).contains(&"low".to_string())),
        "\"low\" never reached the queue; the status was {}",
        daemon.status()
    );

    let normal = leased_with_priority(&daemon, "normal", &peak, 0, &["sleep", "6"]);
    assert!(
        wait_until(20, || {
            let labels = queued_labels(&daemon);
            labels.contains(&"normal".to_string())
                && labels.iter().position(|l| l == "low")
                    < labels.iter().position(|l| l == "normal")
        }),
        "\"normal\" never queued behind \"low\"; the status was {}",
        daemon.status()
    );

    // A high-priority request must overtake the ones that arrived first.
    let high = leased_with_priority(&daemon, "high", &peak, 5, &["sleep", "2"]);
    assert!(
        wait_until(20, || queued_labels(&daemon).len() == 3),
        "the three requests were never all waiting; the status was {}",
        daemon.status()
    );

    let queue = queued_labels(&daemon);
    assert!(
        !queue.is_empty(),
        "nothing was queued; the status was {}",
        daemon.status()
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

/// The GPU's own allocation pool is a second budget, beside MemAvailable.
///
/// `MemAvailable` is the kernel's estimate of reclaimable memory, and it
/// cannot say how full or how fragmented the *non-reclaimable* pool is —
/// `cudaMalloc` blocks and pinned host memory stay put. `tegrastats`' `lfb`
/// (the free blocks of the allocation pool) can. When the pool is thin a
/// lease **that has held device memory before** waits even though
/// MemAvailable is generous: that is Hy4's third failure mode, a workload
/// OOM-ing on `cudaMalloc` while the daemon said there was room.
///
/// The GPU promise is learned, not asked for, so the label arrives with a
/// history that says it holds 2 GiB of device memory (a teaching record:
/// exit 0, over five seconds). A label with no GPU history would skip the
/// pool rule entirely — that is the other half of round 10, item a, and it
/// has its own test below.
///
/// The pool here is driven by a fake `tegrastats` (the
/// `--tegrastats-command` seam, like `--meminfo`), so the test allocates
/// nothing and touches no GPU.
#[test]
fn a_lease_waits_when_the_gpus_own_pool_is_thin() {
    let _serial = serial_gate();
    let reserved = DaemonUnderTest::reserve("gpu-pool", &[]);
    let state_dir = reserved.state_dir.clone();
    // The history that makes this label the GPU's business: one teaching
    // run that held 2 GiB of device memory.
    std::fs::write(
        state_dir.join("peaks.jsonl"),
        concat!(
            r#"{"at":"2026-11-01T04:00:00Z","kind":"gpu.thirsty","label":"gpu.thirsty","#,
            r#""host":"thor","peak_rss_bytes":2147483648,"peak_gpu_bytes":2147483648,"#,
            r#""gpu_visible":true,"duration_s":6.0,"mem_total_bytes":131856928768,"#,
            r#""floor_bytes":1073741824,"basis":"measured","source":"thor-admit","#,
            r#""peak_source":"sample","exit_code":0}"#,
            "\n",
        ),
    )
    .unwrap();
    // The pool the fake reports: the number of 4 MiB blocks free.
    let pool = state_dir.join("lfb");
    std::fs::write(&pool, "2\n").unwrap(); // 8 MiB free of the allocation pool
    let script = state_dir.join("fake-tegrastats.sh");
    std::fs::write(
        &script,
        format!(
            "#!/bin/sh\nwhile :; do\n  n=$(cat {})\n  printf '10-31-2026 23:00:00 RAM \
             40000/125749MB (lfb %sx4MB) VDD_GPU 3000mW/3000mW/3000mW\\n' \"$n\"\n  \
             sleep 1\ndone\n",
            pool.display()
        ),
    )
    .unwrap();
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755));
    let mut extra = vec![
        "--floor".to_string(),
        "1G".to_string(),
        "--gpu-probe".to_string(),
        "tegrastats".to_string(),
        "--gpu-floor".to_string(),
        "1G".to_string(),
        "--tegrastats-command".to_string(),
        script.display().to_string(),
    ];
    extra.extend(reserved.extra.clone());
    let daemon = DaemonUnderTest::start(Reserved {
        state_dir,
        extra,
    });

    // The daemon must *see* the thin pool before the lease asks: the fake
    // tegrastats is a child that takes a moment to print its first line,
    // and a grant that lands before the first sample would be ruled on by
    // the memory rule alone — the very thing this test is not about.
    let pool_seen = wait_until(15, || {
        daemon.status()["gpu_largest_free_block_bytes"].as_u64() == Some(8 * 1024 * 1024)
    });
    assert!(
        pool_seen,
        "the daemon never saw the scripted pool; the status was {}",
        daemon.status()
    );

    // MemAvailable is the box's real, generous number; the pool is 8 MiB.
    // The lease fits the memory rule and still waits.
    let mut waiter = leased(&daemon, "gpu.thirsty", "1G", &["sleep", "60"]);
    let held = wait_until(15, || {
        daemon.log().contains("lease.waiting_for_gpu_memory")
    });
    assert!(
        held,
        "the daemon did not say the lease was waiting for the GPU's pool; \
         the log was:\n{}",
        daemon.log()
    );
    // And it was the label's own 2 GiB device-memory promise that the thin
    // pool could not fit — the rule rides on the learned promise.
    let waiting_line = daemon
        .log()
        .lines()
        .find(|line| line.contains("lease.waiting_for_gpu_memory"))
        .and_then(|line| serde_json::from_str::<Value>(line).ok())
        .expect("the waiting line is JSON");
    assert_eq!(
        waiting_line["label_gpu_peak_bytes"].as_u64(),
        Some(2 * GIB),
        "the waiter's GPU promise was not the learned 2 GiB: {waiting_line}"
    );
    assert_eq!(
        daemon.status()["queue"]
            .as_array()
            .map(|queue| queue.len())
            .unwrap_or(0),
        1,
        "the lease should be waiting, not running; the status was {}",
        daemon.status()
    );

    // The pool recovers (whatever held it let go): the lease is admitted.
    std::fs::write(&pool, "1024\n").unwrap(); // 4 GiB free
    let admitted = wait_until(20, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(
        admitted,
        "the lease was not admitted once the pool recovered; the log was:\n{}",
        daemon.log()
    );
    // And the status shows the pool beside the memory, which is where the
    // rule's numbers live.
    let status = daemon.status();
    assert_eq!(
        status["gpu_largest_free_block_bytes"].as_u64(),
        Some(1024 * 4 * 1024 * 1024),
        "the status does not show the pool it is ruling on: {status}"
    );

    let _ = waiter.kill();
    let _ = waiter.wait();
}

/// A lease that promises no device memory is not held by the GPU's pool
/// (round 10, item a).
///
/// Measured on this box overnight (2026-11-01, the director's watch): the
/// 2 GiB `--gpu-floor` held **21 requests for over an hour** while ~100 GiB
/// was `MemAvailable` — because `tegrastats`' `lfb` is a contiguous-block
/// figure, a fragmentation signal of the allocation pool, not the GPU's
/// headroom; on unified memory the GPU's real budget is `MemAvailable`,
/// which the memory rule already governs. So the pool rule now applies
/// only to a lease whose label has held device memory before, and the
/// default floor is 0. This test is the other half of the one above: the
/// same thin pool, the same 1 GiB floor — a fresh, CPU-only label walks
/// through.
#[test]
fn a_cpu_only_lease_is_not_held_by_the_gpus_pool() {
    let _serial = serial_gate();
    let reserved = DaemonUnderTest::reserve("cpu-vs-pool", &[]);
    let state_dir = reserved.state_dir.clone();
    let pool = state_dir.join("lfb");
    std::fs::write(&pool, "2\n").unwrap(); // 8 MiB free of the allocation pool
    let script = state_dir.join("fake-tegrastats.sh");
    std::fs::write(
        &script,
        format!(
            "#!/bin/sh\nwhile :; do\n  n=$(cat {})\n  printf '10-31-2026 23:00:00 RAM \
             40000/125749MB (lfb %sx4MB) VDD_GPU 3000mW/3000mW/3000mW\\n' \"$n\"\n  \
             sleep 1\ndone\n",
            pool.display()
        ),
    )
    .unwrap();
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755));
    let mut extra = vec![
        "--floor".to_string(),
        "1G".to_string(),
        "--gpu-probe".to_string(),
        "tegrastats".to_string(),
        "--gpu-floor".to_string(),
        "1G".to_string(),
        "--tegrastats-command".to_string(),
        script.display().to_string(),
    ];
    extra.extend(reserved.extra.clone());
    let daemon = DaemonUnderTest::start(Reserved {
        state_dir,
        extra,
    });

    // The daemon must *see* the thin pool before the lease asks, or the
    // grant would be ruled by the memory rule alone — this test is about
    // the pool being visible and declined to hold a CPU-only lease.
    let pool_seen = wait_until(15, || {
        daemon.status()["gpu_largest_free_block_bytes"].as_u64() == Some(8 * 1024 * 1024)
    });
    assert!(
        pool_seen,
        "the daemon never saw the scripted pool; the status was {}",
        daemon.status()
    );

    // A label with no GPU history promises no device memory: the pool is
    // not its budget, and it does not wait for it.
    let mut waiter = leased(&daemon, "cpu.only", "1G", &["sleep", "60"]);
    let admitted = wait_until(15, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(
        admitted,
        "the CPU-only lease waited for the GPU's pool; the log was:\n{}",
        daemon.log()
    );
    assert!(
        !daemon
            .log()
            .lines()
            .any(|line| line.contains("lease.waiting_for_gpu_memory") && line.contains("cpu.only")),
        "the daemon said the CPU-only lease was waiting for the GPU's pool"
    );

    let _ = waiter.kill();
    let _ = waiter.wait();
}

/// A client queued when the daemon dies keeps waiting (round 10, item c).
///
/// A daemon restart empties its queue and drops its leases — the queue is
/// memory, and the daemon that held it is gone. The client's wait used to
/// end with it: the connection closed and the client exited with an error,
/// so a restart (the director stops and starts the daemon by hand during
/// the night) took every queued seat's request with it. The client now
/// reconnects and asks again — the same reconnection the heartbeat already
/// does — and if nothing answers, its own auto-start brings a daemon up.
#[test]
fn a_queued_client_rides_out_a_daemon_restart() {
    let _serial = serial_gate();
    // A daemon whose view of the box the test holds at 20 GiB available
    // against the default 25 GiB floor: nothing is admitted, and the
    // client queues.
    let mut daemon = frozen_memory_daemon("restart-ride", &[], 120 * GIB, 20 * GIB);
    let mut client = leased(&daemon, "restart.ride", "1G", &["true"]);
    let queued = wait_until(15, || {
        daemon.status()["queue"]
            .as_array()
            .map(|queue| !queue.is_empty())
            .unwrap_or(false)
    });
    assert!(
        queued,
        "the client never queued; the status was {}",
        daemon.status()
    );

    // The daemon dies the hard way — SIGKILL, no clean shutdown, a stale
    // socket file left behind — and the client must ride it out: notice,
    // reconnect, ask again, and run once the revived daemon (which reads
    // the box's real memory) admits it.
    let _ = daemon.child.kill();
    let _ = daemon.child.wait();
    let finished = wait_child_with_deadline(&mut client, 60);
    let output = output_of(&mut client);
    match finished {
        Some(status) => {
            assert!(
                status.success(),
                "the queued client did not survive the daemon restart:\n{output}"
            );
            assert!(
                output.contains("asking again"),
                "the client never said it was asking again:\n{output}"
            );
            assert!(
                output.contains("admitted after"),
                "the client never got its lease on the revived daemon:\n{output}"
            );
        }
        None => {
            let _ = client.kill();
            let _ = client.wait();
            stop_the_daemon_left_on(&daemon.socket, &daemon.state_dir);
            panic!(
                "the client is still waiting after the restart; the box's real MemAvailable \
                 is {} MiB, so the revived daemon's default 25 GiB floor may be holding it",
                mem_available() / (1024 * 1024)
            );
        }
    }

    // The revived daemon is not this test's child; stop it through its own
    // pid file so the suite leaves nothing running on the box.
    stop_the_daemon_left_on(&daemon.socket, &daemon.state_dir);
    let gone = wait_until(10, || !daemon.socket.exists());
    assert!(
        gone,
        "the revived daemon did not stop; the suite would leak it on the box"
    );
}

/// Stop a daemon this test did not start: ask it through `thor-admit stop`,
/// and if that does not take, read its pid file and kill it.
///
/// The auto-started daemons (a client's `ensure_daemon`) are children of
/// the client, and the client may already be gone; they are reaped by
/// init, so `kill -9` leaves no zombie. A SIGKILLed daemon cannot clean up
/// its socket file, so the last resort removes it by hand.
fn stop_the_daemon_left_on(socket: &Path, state_dir: &Path) {
    let _ = Command::new(BIN)
        .arg("stop")
        .arg("--socket")
        .arg(socket)
        .output();
    if wait_until(10, || !socket.exists()) {
        return;
    }
    let pid_file = socket.with_extension("pid");
    if let Ok(text) = std::fs::read_to_string(&pid_file) {
        if let Ok(pid) = text.trim().parse::<i32>() {
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        }
    }
    let _ = std::fs::remove_file(socket);
    let _ = std::fs::remove_file(state_dir.join("sock.lock"));
}

/// The daemon must never signal the box's own services.
#[test]
fn the_watchdog_leaves_small_leases_alone() {
    let _serial = serial_gate();
    // The emergency floor is above the box's free memory, so the watchdog is
    // armed from the first sample.
    let daemon = DaemonUnderTest::start_named("watchdog-small-leases", &[
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
    assert_eq!(
        code, "S",
        "the small lease's process is {code:?} rather than peacefully sleeping"
    );
    assert!(
        !daemon.log().contains("watchdog.terminated"),
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

/// Wait for a child to finish, with a deadline.
///
/// A test must fail, not hang, when the thing it waits on never happens —
/// a wedged daemon, a client that never comes back. `None` means the
/// deadline passed with the child still running; the caller decides what
/// that means, and kills what it started.
fn wait_child_with_deadline(
    child: &mut Child,
    seconds: u64,
) -> Option<std::process::ExitStatus> {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    loop {
        if let Ok(Some(status)) = child.try_wait() {
            return Some(status);
        }
        if Instant::now() >= deadline {
            return None;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

/// The registered work runs when the box has room for it.
#[test]
fn a_presence_job_runs_when_the_box_has_room() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("presence-runs", &["--floor", "1G"]);
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
    let _serial = serial_gate();
    // The floor is set so that the presence job's reservation is exactly
    // what stands between the live lease and the box's room: the presence
    // job promised 4 GiB it has not used, and the live lease needs 2 GiB.
    //
    // The view of the box is held still, so the arithmetic is the same
    // whatever the box is doing while the test runs.
    let total = mem_total();
    let available = 100 * GIB;
    let presence_peak = 4 * GIB;
    let live_peak = 2 * GIB;
    let floor = available
        .saturating_sub(presence_peak)
        .saturating_sub(live_peak)
        .saturating_add(GIB);
    let daemon = frozen_memory_daemon(
        "presence-preempted",
        &[
            "--floor",
            &floor.to_string(),
            "--emergency-floor",
            &available.saturating_sub(GIB).to_string(),
        ],
        total,
        available,
    );

    // A presence job that reserves memory it does not use yet.
    let id = presence_add(
        &daemon,
        "study",
        "4G",
        "presence.test",
        &["sleep", "120"],
    );
    let running = wait_until(30, || {
        presence_jobs(&daemon)
            .iter()
            .any(|job| job["id"].as_u64() == Some(id) && job["state"] == "running")
    });
    assert!(running, "the presence job never started: {}", daemon.log());

    // A live lease arrives. It does not fit while the presence job holds
    // its reservation, so the daemon must take the memory back.
    let mut live = leased(&daemon, "live.test", "2G", &["sleep", "20"]);
    let granted = wait_until(30, || {
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

/// A granted lease that is never held never ran anything, and the ledger
/// must not invent work for it: the tier's running time stays at zero, and
/// the window is booked to its own attributed cause instead (Hy4's fifth
/// failure mode — the ledger showed live.running_s > 0 for a lease whose
/// command never started).
#[test]
fn a_granted_lease_that_never_runs_is_not_booked_as_running() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("granted-not-run", &[
        "--floor",
        "1G",
        "--grant-grace-secs",
        "3",
    ]);

    let mut holder = lease_holder("abandon", &daemon, "phantom.live", 60.0);
    let granted = wait_until(15, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| !leases.is_empty())
            .unwrap_or(false)
    });
    assert!(granted, "the holder never got its grant: {}", daemon.log());

    // The grant's grace runs out and the daemon takes the lease back.
    let gone = wait_until(20, || {
        daemon.status()["leases"]
            .as_array()
            .map(|leases| leases.is_empty())
            .unwrap_or(false)
    });
    assert!(
        gone,
        "the unclaimed grant was never taken back: {}",
        daemon.log()
    );
    assert!(
        daemon.log().contains("lease.granted_not_run"),
        "the daemon never named the phantom lease: {}",
        daemon.log()
    );

    // And the ledger tells the truth about the window: nothing ran, and the
    // idleness has the cause the grant explains.
    let buckets = ledger(&daemon);
    let bucket = buckets.last().expect("there is an hour");
    let live_running = bucket["tiers"]["live"]["running_s"].as_f64().unwrap_or(0.0);
    assert_eq!(
        live_running, 0.0,
        "the ledger booked running time for a lease that never ran: {bucket}"
    );
    let reasons = bucket["idle"]["by_reason"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    assert!(
        reasons.contains_key("granted_not_run"),
        "the grant's window has no cause of its own: {bucket}"
    );
    assert_eq!(
        bucket["idle"]["unattributed_s"].as_f64().unwrap_or(-1.0),
        0.0,
        "an explained window was booked as unattributed: {bucket}"
    );

    let _ = holder.kill();
    let _ = holder.wait();
}

/// The ledger books the box's time to the tiers, and explains its idleness.
#[test]
fn the_ledger_books_the_time_by_tier() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("ledger-by-tier", &["--floor", "1G"]);

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
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("ledger-idleness", &["--floor", "1G"]);
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

// ---------------------------------------------------------------------------
// Round 11: backfill, serve coalescing, the phase op
// ---------------------------------------------------------------------------

/// One teaching history record for a label, written into a daemon's state
/// directory before the daemon starts, so the label arrives with a past —
/// a peak it reached and how long it ran, which is what `--peak auto` and
/// the backfill rule's duration estimate are made of.
fn teach_history(state_dir: &Path, label: &str, peak_bytes: u64, duration_s: f64) {
    let record = serde_json::json!({
        "at": "2026-11-01T00:00:00Z",
        "kind": label,
        "label": label,
        "host": "test",
        "peak_rss_bytes": peak_bytes,
        "peak_gpu_bytes": Value::Null,
        "gpu_visible": false,
        "duration_s": duration_s,
        "mem_total_bytes": 0,
        "floor_bytes": 0,
        "basis": "measured",
        "source": "thor-admit",
        "peak_source": "rusage",
        "exit_code": 0,
    });
    let path = state_dir.join("peaks.jsonl");
    let mut text = std::fs::read_to_string(&path).unwrap_or_default();
    text.push_str(&record.to_string());
    text.push('\n');
    std::fs::write(&path, text).unwrap();
}

/// A frozen-memory daemon whose small label already has a history: the
/// shape every round-11 backfill test starts from.
fn backfill_daemon(name: &str, extra: &[&str], available: u64) -> DaemonUnderTest {
    let mut reserved = DaemonUnderTest::reserve(name, extra);
    write_meminfo(&reserved.state_dir.join("meminfo"), mem_total(), available);
    // One clean run of 60 s: the label can promise when it will end, which
    // is the condition a candidate must meet before it may pass the head.
    teach_history(&reserved.state_dir, "small.hist", 4 * GIB, 60.0);
    reserved.extra.push("--meminfo".to_string());
    reserved
        .extra
        .push(reserved.state_dir.join("meminfo").display().to_string());
    DaemonUnderTest::start(reserved)
}

/// The 2026-11-01 queue at test scale: a 58 GiB head that cannot fit while
/// 35 GiB stands above the floor, and a small request behind it that fits
/// the hole. Before round 11 the small request waited two hours; now it
/// passes, because nothing is running to give the head a start it could be
/// delayed out of, and the candidate has a duration estimate of its own.
#[test]
fn a_small_request_backfills_past_a_blocked_head() {
    let _serial = serial_gate();
    let available = 80 * GIB;
    let floor = 25 * GIB;
    let daemon = backfill_daemon(
        "backfill-small",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
        available,
    );
    let peak = format!("{}G", 60);

    // The head arrives first and cannot fit: 80 − 60 = 20, under the 25 floor.
    let mut head = leased(&daemon, "big.head", &peak, &["sleep", "30"]);
    assert!(
        wait_until(20, || daemon.status()["queue"]
            .as_array()
            .map_or(false, |items| !items.is_empty())),
        "the head never reached the queue; the status was {}",
        daemon.status()
    );

    // The small request fits the hole (80 − 4 = 76, above the floor) and
    // its label can say when it will be done — so it passes the head.
    let mut small = leased(&daemon, "small.hist", "4G", &["sleep", "30"]);
    let passed = wait_until(20, || {
        daemon
            .status()["leases"]
            .as_array()
            .map_or(false, |leases| {
                leases
                    .iter()
                    .any(|lease| lease["label"] == "small.hist")
            })
    });
    assert!(
        passed,
        "the small request was never backfilled past the head; the status was {}\nthe log:\n{}",
        daemon.status(),
        daemon.log()
    );
    let status = daemon.status();
    let queue = status["queue"].as_array().cloned().unwrap_or_default();
    assert_eq!(
        queue.first().and_then(|waiter| waiter["label"].as_str()),
        Some("big.head"),
        "the head should still be waiting: {queue:?}"
    );
    assert!(
        daemon.log().contains("\"event\":\"lease.backfilled\""),
        "the backfill was not logged; the log:\n{}",
        daemon.log()
    );

    let _ = head.kill();
    let _ = head.wait();
    let _ = small.kill();
    let _ = small.wait();
}

/// The bound: once the head has waited it, nothing more passes — whatever
/// room appears next is the head's, and the delay a wrong estimate can add
/// is bounded by what was already admitted inside the window.
#[test]
fn the_heads_wait_bound_closes_the_backfill_window() {
    let _serial = serial_gate();
    let available = 80 * GIB;
    let floor = 25 * GIB;
    let daemon = backfill_daemon(
        "backfill-bound",
        &[
            "--floor",
            &floor.to_string(),
            "--emergency-floor",
            "1G",
            "--backfill-max-head-wait",
            "3",
        ],
        available,
    );

    // The head arrives and cannot fit; three seconds later the bound has
    // the queue to itself.
    let mut head = leased(&daemon, "big.head", "60G", &["sleep", "30"]);
    assert!(
        wait_until(20, || daemon.status()["queue"]
            .as_array()
            .map_or(false, |items| !items.is_empty())),
        "the head never reached the queue; the status was {}",
        daemon.status()
    );
    assert!(
        wait_until(15, || daemon.log().contains("\"event\":\"lease.backfill_bounded\"")),
        "the bound was never named in the log; the log:\n{}",
        daemon.log()
    );

    // The same small request that backfills without the bound (the test
    // above) now stays behind the head: the window is closed.
    let mut small = leased(&daemon, "small.hist", "4G", &["sleep", "30"]);
    std::thread::sleep(Duration::from_secs(8));
    let status = daemon.status();
    let queue = status["queue"].as_array().cloned().unwrap_or_default();
    assert_eq!(
        queue.len(),
        2,
        "both requests should still be waiting: {queue:?}; the log:\n{}",
        daemon.log()
    );
    assert_eq!(
        queue.first().and_then(|waiter| waiter["label"].as_str()),
        Some("big.head"),
        "the head is not in front: {queue:?}"
    );

    let _ = head.kill();
    let _ = head.wait();
    let _ = small.kill();
    let _ = small.wait();
}

/// A stand-in model server that takes its port the way the real servers do
/// (`--port N`), so two asks with different assigned ports are the same
/// key: the port is the instance's assigned fact, not a part of what is
/// being served (§12.1 of the design record).
fn stand_in_server(state_dir: &Path) -> PathBuf {
    let path = state_dir.join("server.py");
    std::fs::write(
        &path,
        "import argparse\n\
         from http.server import BaseHTTPRequestHandler, HTTPServer\n\
         parser = argparse.ArgumentParser()\n\
         parser.add_argument('--port', type=int)\n\
         parser.add_argument('--model')\n\
         args = parser.parse_args()\n\
         HTTPServer(('127.0.0.1', args.port), BaseHTTPRequestHandler).serve_forever()\n",
    )
    .unwrap();
    path
}

/// Two seats ask for the same model within minutes (the 15:23 and 15:27
/// `serve.glide` asks of 2026-11-01) while the box has no room for it. The
/// asks become **one waiter**: no second 58 GiB promise, and when the room
/// appears the leader's lease starts one server — the follower is told
/// which lease holds it, runs nothing, and reports the leader's port.
#[test]
fn two_identical_serve_asks_waiting_side_by_side_become_one_waiter() {
    let _serial = serial_gate();
    let available = 60 * GIB;
    let floor = 25 * GIB;
    let reserved = DaemonUnderTest::reserve(
        "serve-coalesce",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
    );
    let meminfo = reserved.state_dir.join("meminfo");
    write_meminfo(&meminfo, mem_total(), available);
    let model = reserved.state_dir.join("glide.gguf");
    std::fs::write(&model, b"the weights, as far as a test needs them").unwrap();
    let server = stand_in_server(&reserved.state_dir);
    let mut reserved = reserved;
    reserved.extra.push("--meminfo".to_string());
    reserved.extra.push(meminfo.display().to_string());
    let daemon = DaemonUnderTest::start(reserved);

    let free_port = || {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        port
    };
    let port_one = free_port();
    let port_two = free_port();
    let ask = |model_name: &str, port: u16| -> Vec<String> {
        vec![
            "serve".to_string(),
            model_name.to_string(),
            "--socket".to_string(),
            daemon.socket.display().to_string(),
            "--port".to_string(),
            port.to_string(),
            "--peak".to_string(),
            "58G".to_string(),
            "--".to_string(),
            "python3".to_string(),
            server.display().to_string(),
            "--port".to_string(),
            port.to_string(),
            "--model".to_string(),
            model.display().to_string(),
        ]
    };

    // The first seat asks; 60 − 58 is under the floor, so its ask waits.
    let mut first = Command::new(BIN)
        .args(ask("glide", port_one))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the first serve ask starts");
    assert!(
        wait_until(20, || daemon.status()["queue"]
            .as_array()
            .map_or(false, |items| items.len() == 1)),
        "the first ask never waited; the status was {}",
        daemon.status()
    );

    // The second seat asks under another name and another assigned port:
    // the same model file, the same flags — the same ask. One waiter.
    let second = Command::new(BIN)
        .args(ask("glide-baseline", port_two))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the second serve ask starts");
    let coalesced = wait_until(20, || {
        daemon.status()["queue"]
            .as_array()
            .and_then(|items| items.first())
            .and_then(|waiter| waiter["coalesced"].as_u64())
            .map_or(false, |coalesced| coalesced == 1)
    });
    assert!(
        coalesced,
        "the second ask never joined the first; the status was {}\nthe log:\n{}",
        daemon.status(),
        daemon.log()
    );
    let status = daemon.status();
    assert_eq!(
        status["queue"].as_array().map(Vec::len),
        Some(1),
        "two identical asks made two waiters: {}",
        status
    );
    assert!(
        daemon.log().contains("\"event\":\"lease.coalesced\""),
        "the coalescing was not logged; the log:\n{}",
        daemon.log()
    );

    // The room appears. The leader's lease is granted, one server starts,
    // and the follower — told which lease holds it — reports the leader's
    // port and runs nothing of its own.
    write_meminfo(&meminfo, mem_total(), 110 * GIB);
    let registered = || {
        thor_admit::serve::port_answers(port_one)
            && std::fs::read_to_string(daemon.state_dir.join("servers.json"))
                .map(|text| text.contains("\"model\":\"glide\""))
                .unwrap_or(false)
    };
    assert!(
        wait_until(25, registered),
        "the coalesced server never answered its port; the log:\n{}",
        daemon.log()
    );
    let (second_tx, second_rx) = std::sync::mpsc::channel();
    let mut second_for_output = second;
    std::thread::spawn(move || {
        let _ = second_tx.send(output_of(&mut second_for_output));
    });
    let answered =
        second_rx.recv_timeout(Duration::from_secs(30)).unwrap_or_default();
    assert!(
        answered.contains(&format!("is served on port {port_one}")),
        "the follower did not report the leader's port: {answered}"
    );
    assert!(
        !thor_admit::serve::port_answers(port_two),
        "the follower started a server of its own on {port_two}"
    );

    // Clean up like the other serve tests: kill the leader and wait for
    // its server to go with it, or the test leaks it on the box. (The
    // follower has already exited on its own — it reported the leader's
    // port and ran nothing.)
    let _ = first.kill();
    let _ = first.wait();
    let gone = wait_until(15, || !thor_admit::serve::port_answers(port_one));
    assert!(gone, "the server outlived the test; the log:\n{}", daemon.log());
}

/// The phase op: a lease that reserved far above its use gives the
/// difference back while it runs, and the queue behind it drains with the
/// freed bytes — the `night-v3.heavy` shape of 2026-11-01, answered.
#[test]
fn a_phase_shrink_frees_the_room_the_queue_is_waiting_for() {
    let _serial = serial_gate();
    let available = 80 * GIB;
    let floor = 25 * GIB;
    let reserved = DaemonUnderTest::reserve(
        "phase-shrink",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
    );
    let meminfo = reserved.state_dir.join("meminfo");
    write_meminfo(&meminfo, mem_total(), available);
    // The heavy label has a past: its runs peak at 4 GiB, which is what a
    // phase shrink should settle at.
    teach_history(&reserved.state_dir, "heavy.hist", 4 * GIB, 300.0);
    let mut reserved = reserved;
    reserved.extra.push("--meminfo".to_string());
    reserved.extra.push(meminfo.display().to_string());
    let daemon = DaemonUnderTest::start(reserved);

    // The heavy lease is granted (80 − 40 = 40, above the floor) and its
    // label's learned p95 is what a phase op should settle at.
    let mut heavy = leased(&daemon, "heavy.hist", "40G", &["sleep", "60"]);
    assert!(
        wait_until(20, || daemon.status()["leases"]
            .as_array()
            .map_or(false, |leases| leases
                .iter()
                .any(|lease| lease["label"] == "heavy.hist"))),
        "the heavy lease was never granted; the status was {}",
        daemon.status()
    );

    // A 30 GiB request behind it cannot fit while the 40 GiB promise is
    // charged: 80 − 40 = 40, under 30 + 25.
    let mut waiter = leased(&daemon, "waiter", "30G", &["sleep", "30"]);
    assert!(
        wait_until(20, || daemon.status()["queue"]
            .as_array()
            .map_or(false, |items| !items.is_empty())),
        "the waiter never reached the queue; the status was {}",
        daemon.status()
    );

    // The work changed phase: the lease shrinks by name, the freed bytes
    // are charged back at once, and the waiter fits (80 − 4 = 76 ≥ 55).
    let phased = Command::new(BIN)
        .arg("phase")
        .arg("heavy.hist")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--peak")
        .arg("4G")
        .output()
        .expect("the phase command runs");
    assert!(
        phased.status.success(),
        "the phase command failed: {}",
        String::from_utf8_lossy(&phased.stderr)
    );
    let granted = wait_until(20, || {
        daemon
            .status()["leases"]
            .as_array()
            .map_or(false, |leases| leases
                .iter()
                .any(|lease| lease["label"] == "waiter"))
    });
    assert!(
        granted,
        "the waiter was never granted after the shrink; the status was {}\nthe log:\n{}",
        daemon.status(),
        daemon.log()
    );
    let log = daemon.log();
    assert!(
        log.contains("\"event\":\"lease.phase\"") && log.contains("\"direction\":\"shrink\""),
        "the shrink was not logged; the log:\n{}",
        log
    );

    let _ = heavy.kill();
    let _ = heavy.wait();
    let _ = waiter.kill();
    let _ = waiter.wait();
}

/// The over-reservation cue reaches the holder: a lease holding far more
/// than it uses is named in the status, with the peak it would fit in, so
/// the holder can answer with `thor-admit phase` without reading the log.
#[test]
fn a_lease_that_holds_far_more_than_it_uses_is_named_in_the_status() {
    let _serial = serial_gate();
    let available = 80 * GIB;
    let floor = 25 * GIB;
    let reserved = DaemonUnderTest::reserve(
        "over-reserved",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
    );
    let meminfo = reserved.state_dir.join("meminfo");
    write_meminfo(&meminfo, mem_total(), available);
    // The label's history says the work peaks at 4 GiB, so a 40 GiB promise
    // is ten times what the work needs.
    teach_history(&reserved.state_dir, "heavy.hist", 4 * GIB, 300.0);
    let mut reserved = reserved;
    reserved.extra.push("--meminfo".to_string());
    reserved.extra.push(meminfo.display().to_string());
    let daemon = DaemonUnderTest::start(reserved);

    let mut heavy = leased(&daemon, "heavy.hist", "40G", &["sleep", "60"]);
    assert!(
        wait_until(20, || daemon.status()["leases"]
            .as_array()
            .map_or(false, |leases| leases
                .iter()
                .any(|lease| lease["label"] == "heavy.hist"))),
        "the lease was never granted; the status was {}",
        daemon.status()
    );

    // The daemon names it: the status says the lease is over-reserved and
    // what it would fit in (the larger of the learned p95 and the measured
    // peak — here the 4 GiB the label's runs peak at).
    let named = wait_until(20, || {
        daemon.status()["leases"]
            .as_array()
            .map_or(false, |leases| leases
                .iter()
                .any(|lease| lease["label"] == "heavy.hist" && lease["over_reserved"] == true))
    });
    let status = daemon.status();
    assert!(
        named,
        "the over-reserved lease was never named in the status; the status was {status}\n\
         the log:\n{}",
        daemon.log()
    );
    let suggested = status["leases"]
        .as_array()
        .and_then(|leases| {
            leases
                .iter()
                .find(|lease| lease["label"] == "heavy.hist")
                .and_then(|lease| lease["suggested_peak_bytes"].as_u64())
        })
        .unwrap_or(0);
    assert_eq!(
        suggested, 4 * GIB,
        "the suggested peak was not the label's learned peak; the status was {status}"
    );

    let _ = heavy.kill();
    let _ = heavy.wait();
}

/// A grow that the box has no room for is refused with the numbers, and
/// the lease keeps the reservation it has.
#[test]
fn a_phase_grow_that_does_not_fit_is_refused() {
    let _serial = serial_gate();
    let available = 80 * GIB;
    let floor = 25 * GIB;
    let reserved = DaemonUnderTest::reserve(
        "phase-grow",
        &["--floor", &floor.to_string(), "--emergency-floor", "1G"],
    );
    let meminfo = reserved.state_dir.join("meminfo");
    write_meminfo(&meminfo, mem_total(), available);
    let mut reserved = reserved;
    reserved.extra.push("--meminfo".to_string());
    reserved.extra.push(meminfo.display().to_string());
    let daemon = DaemonUnderTest::start(reserved);

    // 40 GiB is granted; a second 40 GiB would put the box under the floor
    // (80 − 40 − 40 = 0), so the running lease may not grow that far.
    let mut heavy = leased(&daemon, "grower", "40G", &["sleep", "60"]);
    assert!(
        wait_until(20, || daemon.status()["leases"]
            .as_array()
            .map_or(false, |leases| leases
                .iter()
                .any(|lease| lease["label"] == "grower"))),
        "the lease was never granted; the status was {}",
        daemon.status()
    );
    let refused = Command::new(BIN)
        .arg("phase")
        .arg("grower")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--peak")
        .arg("80G")
        .output()
        .expect("the phase command runs");
    assert!(
        !refused.status.success(),
        "a grow the box has no room for was accepted"
    );
    let message = String::from_utf8_lossy(&refused.stderr);
    assert!(
        message.contains("room to grow"),
        "the refusal did not say why: {message}"
    );
    let status = daemon.status();
    let peak = status["leases"]
        .as_array()
        .and_then(|leases| leases.first())
        .and_then(|lease| lease["peak_bytes"].as_u64())
        .unwrap_or(0);
    assert_eq!(peak, 40 * GIB, "the reservation changed despite the refusal");

    let _ = heavy.kill();
    let _ = heavy.wait();
}

/// `run` leaves the lease id in the command's environment, so a workload
/// that knows its own phases can give memory back mid-run without any
/// outside help.
#[test]
fn run_leaves_the_lease_id_in_the_command_environment() {
    let _serial = serial_gate();
    let daemon = DaemonUnderTest::start_named("lease-env", &["--floor", "1G"]);
    let output = Command::new(BIN)
        .arg("run")
        .arg("--socket")
        .arg(&daemon.socket)
        .arg("--peak")
        .arg("100M")
        .arg("--label")
        .arg("env.probe")
        .arg("--")
        .arg("printenv")
        .arg("THOR_ADMIT_LEASE")
        .output()
        .expect("the run executes");
    assert!(
        output.status.success(),
        "the run failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let lease: u64 = text
        .parse()
        .unwrap_or_else(|_| panic!("the command did not see its lease id: {text:?}"));
    assert!(
        daemon.log().contains(&format!("\"lease\":{lease}")),
        "the lease id the command saw ({lease}) is not the daemon's; the log:\n{}",
        daemon.log()
    );
}

// ---------------------------------------------------------------------------
// Round 12: the guard — work that is outside any lease.
// ---------------------------------------------------------------------------

/// Protect every process on the box except the ones the test names.
///
/// The guard's job is to stop the box's **biggest unleased process**, and on
/// this box that is the model server (58.9 GiB, measured 2026-11-01) and
/// whatever the other seats are running. A test's daemon must not touch any
/// of it: the hog the test started is the only process it may stop.
///
/// So the test's daemon gets a protected list naming every pid on the box
/// but its own. The list is read by the daemon when it changes, so the test
/// can write it after the hog has started.
///
/// The file is written under a temp name and renamed into place. The daemon
/// reads it without a lock, and a half-written file would leave a process
/// unprotected for as long as it took to write the rest.
fn protect_everything_but(path: &Path, mine: &[i32]) {
    let mut lines = Vec::new();
    for entry in std::fs::read_dir("/proc").unwrap().flatten() {
        let name = entry.file_name();
        let Some(text) = name.to_str() else {
            continue;
        };
        let Ok(pid) = text.parse::<i32>() else {
            continue;
        };
        if mine.contains(&pid) {
            continue;
        }
        lines.push(format!("pid {pid}"));
    }
    let temporary = path.with_extension("tmp");
    std::fs::write(&temporary, lines.join("\n")).unwrap();
    std::fs::rename(&temporary, path).unwrap();
}

/// The protection list, kept current for as long as the test runs.
///
/// The list is a snapshot of the box at one moment, and the box keeps moving:
/// a seat starts a process, and that process is not on the list. The guard
/// would then be free to stop it — and the test's daemon is pointed at the
/// **real** box, with a scripted memory number in place of the real one. So
/// the list is refreshed until the test is over, and the only processes it
/// leaves out are the test's own hogs.
struct Protection {
    /// The pids the guard may stop: the test's own hogs.
    mine: Arc<Mutex<Vec<i32>>>,
    stop: Arc<std::sync::atomic::AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl Protection {
    /// Start refreshing the list.
    fn start(path: &Path) -> Protection {
        let mine = Arc::new(Mutex::new(Vec::new()));
        let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let thread = {
            let path = path.to_path_buf();
            let mine = Arc::clone(&mine);
            let stop = Arc::clone(&stop);
            std::thread::spawn(move || {
                while !stop.load(std::sync::atomic::Ordering::Relaxed) {
                    let mine = mine.lock().unwrap().clone();
                    protect_everything_but(&path, &mine);
                    std::thread::sleep(Duration::from_millis(50));
                }
            })
        };
        Protection {
            mine,
            stop,
            thread: Some(thread),
        }
    }

    /// Let the guard stop this process.
    fn spare(&self, pid: i32) {
        self.mine.lock().unwrap().push(pid);
    }

    /// Stop refreshing.
    fn finish(&mut self) {
        self.stop
            .store(true, std::sync::atomic::Ordering::Relaxed);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

/// The guard's events in the daemon's log, in order.
fn guard_events(daemon: &DaemonUnderTest, event: &str) -> Vec<Value> {
    daemon
        .log()
        .lines()
        .filter(|line| line.contains(&format!("\"{event}\"")))
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .collect()
}

/// Round 12: the guard stops work that is **outside** any lease.
///
/// The daemon's watchdog of §4 only knew about leases: when the box ran
/// short it picked the largest *lease* and terminated it. A process that was
/// never leased was invisible to that rule, and the 2026-11-01 incident was
/// exactly that — a JAX run started outside `thor-admit` took 94.5 GB of
/// the box's unified memory in 20 seconds, the desktop died, the Wi-Fi
/// driver died, and the box needed a power cycle.
///
/// The memory **curve** is scripted here: the daemon, the hog, the
/// `SIGTERM`, the grace and the timing are all real; only the number the
/// daemon reads is written by the test. The real box cannot be taken to 8
/// GiB free for a test, and the brief caps a test's memory at 60 GiB.
#[test]
fn the_guard_stops_an_unleased_hog_before_the_box_runs_out() {
    let _serial = serial_gate();
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
    let total = 122 * GIB;
    let floor = 8 * GIB;
    let scratch = std::env::temp_dir().join(format!("thor-admit-guard-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let meminfo = scratch.join("meminfo");
    write_meminfo(&meminfo, total, 100 * GIB);
    let protected = scratch.join("protected.txt");

    // `--guard-drop 512G` switches the runaway trigger off, so this test is
    // about the floor and about nothing else. The runaway trigger has its
    // own test below.
    let daemon = DaemonUnderTest::start_named(
        "guard-on-a-scripted-curve",
        &[
            "--meminfo",
            meminfo.to_str().unwrap(),
            "--guard-protected-file",
            protected.to_str().unwrap(),
            "--guard-min-rss",
            "1G",
            "--guard-drop",
            "512G",
        ],
    );
    let oom_before = oom_kills();

    // Everything on the box is protected, and the list is kept current.
    let mut protection = Protection::start(&protected);

    // The hog: a real process, holding real memory, and **no lease**. It is
    // started the way the incident's run was started — from a shell, with
    // nothing to say so.
    let mut hog = Command::new(HOG)
        .arg("--bytes")
        .arg("4G")
        .arg("--hold")
        .arg("180")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("the hog starts");
    let hog_pid = hog.id() as i32;
    protection.spare(hog_pid);

    // Wait until the hog is really holding memory, so the guard has
    // something to find.
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut hog_rss = 0;
    while Instant::now() < deadline {
        hog_rss = rss_of(hog_pid as u32);
        if hog_rss >= GIB {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        hog_rss >= GIB,
        "the hog never grew to be a candidate ({hog_rss} bytes)"
    );

    // The curve: the box loses a lot of memory at once — the shape of the
    // 13:22 OOM — and then keeps sliding down, a quarter of a gibibyte a
    // step, through the emergency floor and on past the 2 GiB line.
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

    // Wait for the guard to act.
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut terminated: Option<Value> = None;
    let mut observed_at = None;
    while Instant::now() < deadline {
        let events = guard_events(&daemon, "guard.terminated");
        if let Some(event) = events.first() {
            terminated = Some(event.clone());
            observed_at = Some(Instant::now());
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let Some(event) = terminated else {
        let _ = hog.kill();
        let _ = hog.wait();
        panic!(
            "the guard did not terminate the unleased hog; the log was:\n{}",
            daemon.log()
        );
    };

    // It stopped the right process: the hog, and nothing else.
    assert_eq!(
        event["pid"].as_i64(),
        Some(hog_pid as i64),
        "the guard stopped the wrong process: {event}"
    );
    assert_eq!(
        event["trigger"].as_str(),
        Some("floor"),
        "the guard's trigger should be the floor: {event}"
    );
    assert!(
        event["total_bytes"].as_u64().unwrap_or(0) >= GIB,
        "the guard should say how much the process held: {event}"
    );
    assert!(
        event["command"]
            .as_str()
            .unwrap_or("")
            .contains("thor-admit-hog"),
        "the guard should say what it stopped: {event}"
    );

    // It acted at the floor, not deep in the danger zone: the daemon
    // samples every 250 ms and the curve moves 256 MiB every 50 ms, so the
    // number it reads can be a gibibyte or so below the floor. It must not
    // be far below that, or the daemon would be acting late.
    let available_at_stop = event["mem_available_bytes"].as_u64().unwrap_or(0);
    assert!(
        available_at_stop <= floor && floor - available_at_stop <= 2 * GIB,
        "the guard acted at {} MiB free, which is not the {} MiB floor",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024)
    );

    // The hog must actually die: a termination is not a stop. On this box a
    // stopped process keeps every page it took, and the emergency gets
    // worse while the daemon waits.
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut died = false;
    while Instant::now() < deadline {
        if hog.try_wait().ok().flatten().is_some() {
            died = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        died,
        "the unleased hog was terminated but never died; the log was:\n{}",
        daemon.log()
    );
    assert_eq!(
        oom_kills(),
        oom_before,
        "the kernel's OOM killer fired; the guard was too late"
    );

    // And the status says what happened, so an operator can see it without
    // reading the log.
    assert!(
        wait_until(10, || {
            daemon.status()["guard"]["last_pid"].as_i64() == Some(hog_pid as i64)
        }),
        "the status did not report the guard's action: {}",
        daemon.status()
    );

    // Let the curve finish, so the test has shown the danger zone was
    // really reached — after the stop, not before it.
    let _ = writer.join();
    let curve = steps.lock().unwrap().clone();
    let lowest = curve.last().map(|(available, _)| *available).unwrap_or(0);
    assert!(
        lowest <= 2 * GIB,
        "the curve only reached {} MiB free, so the danger zone was never reached",
        lowest / (1024 * 1024)
    );
    let crossed = curve
        .iter()
        .find(|(available, _)| *available < floor)
        .map(|(_, at)| *at);
    let latency = match (crossed, observed_at) {
        (Some(crossed), Some(observed)) => observed.saturating_duration_since(crossed),
        _ => Duration::ZERO,
    };
    eprintln!(
        "guard: the unleased hog was terminated with {} MiB free (the floor was {} MiB) and \
         died; the curve went on down to {} MiB, the daemon acted within {} ms of the floor \
         being crossed, and the kernel's OOM killer fired {} times",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024),
        lowest / (1024 * 1024),
        latency.as_millis(),
        oom_kills() - oom_before,
    );

    let _ = hog.kill();
    let _ = hog.wait();
    protection.finish();
    let _ = std::fs::remove_dir_all(&scratch);
}

/// Round 12: the guard stops a runaway **above** the emergency floor.
///
/// This is the shape the 2026-11-01 incident had, and the floor test above
/// does not cover it. The JAX run left **15 GB free** — above the 8 GiB
/// emergency floor — and the desktop had already died. A guard that only
/// answers the floor is too late for that: the box loses its desktop long
/// before the kernel would have run out of memory.
///
/// So the guard has a second trigger: the box loses memory faster than the
/// leases can explain it. Here the box stays at 20 GiB free — never near
/// the floor — and an unleased hog takes 12 GiB in one go. The guard must
/// stop it there and then.
#[test]
fn the_guard_stops_a_runaway_while_the_box_is_still_above_the_floor() {
    let _serial = serial_gate();
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
    let total = 122 * GIB;
    let floor = 8 * GIB;
    let scratch = std::env::temp_dir().join(format!("thor-admit-guard-runaway-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let meminfo = scratch.join("meminfo");
    write_meminfo(&meminfo, total, 100 * GIB);
    let protected = scratch.join("protected.txt");

    // A short window and a fast clock, so the test does not take a minute:
    // the guard has to see the hog grow inside its own window, and the
    // window is what the run away is measured over.
    let daemon = DaemonUnderTest::start_named(
        "guard-on-a-runaway",
        &[
            "--meminfo",
            meminfo.to_str().unwrap(),
            "--guard-protected-file",
            protected.to_str().unwrap(),
            "--guard-min-rss",
            "1G",
            "--guard-interval-ms",
            "500",
            "--guard-window-secs",
            "6",
            // The threshold is lowered for the test: the claim is about the
            // *shape* of the trigger, not about eight gibibytes.
            "--guard-drop",
            "2G",
        ],
    );
    let mut protection = Protection::start(&protected);

    // The daemon collects its window **before** the hog starts. The guard
    // measures the fall over that window, and the hog's growth has to be
    // inside it: a hog that had already grown before the window opened
    // would look to the guard like a process that had not moved.
    std::thread::sleep(Duration::from_secs(2));

    // The hog, and no lease: the incident's shape exactly.
    let mut hog = Command::new(HOG)
        .arg("--bytes")
        .arg("4G")
        .arg("--hold")
        .arg("180")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("the hog starts");
    let hog_pid = hog.id() as i32;
    protection.spare(hog_pid);

    // Wait until the hog is really holding memory. The guard's window has
    // to hold a look from *before* the hog grew, or the growth is not seen.
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut hog_rss = 0;
    while Instant::now() < deadline {
        hog_rss = rss_of(hog_pid as u32);
        if hog_rss >= 4 * GIB {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        hog_rss >= 4 * GIB,
        "the hog never grew to 4 GiB ({hog_rss} bytes)"
    );

    // And now the box loses memory, with no lease to explain it — but it
    // stays **above** the emergency floor. This is the incident's shape:
    // 15 GB free, the desktop already gone.
    write_meminfo(&meminfo, total, 20 * GIB);

    let deadline = Instant::now() + Duration::from_secs(30);
    let mut terminated: Option<Value> = None;
    while Instant::now() < deadline {
        if let Some(event) = guard_events(&daemon, "guard.terminated").first() {
            terminated = Some(event.clone());
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let Some(event) = terminated else {
        let _ = hog.kill();
        let _ = hog.wait();
        panic!(
            "the guard did not stop the runaway; the log was:\n{}",
            daemon.log()
        );
    };

    assert_eq!(
        event["pid"].as_i64(),
        Some(hog_pid as i64),
        "the guard stopped the wrong process: {event}"
    );
    assert_eq!(
        event["trigger"].as_str(),
        Some("runaway"),
        "the guard's trigger should be the runaway, not the floor: {event}"
    );
    // The whole point: the box was **not** below the floor.
    let available_at_stop = event["mem_available_bytes"].as_u64().unwrap_or(0);
    assert!(
        available_at_stop > floor,
        "the guard acted at {} MiB free, which is not above the {} MiB floor: {event}",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024)
    );

    // And the hog dies, so the memory comes back.
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut died = false;
    while Instant::now() < deadline {
        if hog.try_wait().ok().flatten().is_some() {
            died = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        died,
        "the runaway was terminated but never died; the log was:\n{}",
        daemon.log()
    );

    eprintln!(
        "guard runaway: the unleased hog was stopped with {} MiB free — {} MiB above the {} MiB \
         emergency floor — and died",
        available_at_stop / (1024 * 1024),
        (available_at_stop - floor) / (1024 * 1024),
        floor / (1024 * 1024),
    );

    let _ = hog.kill();
    let _ = hog.wait();
    protection.finish();
    let _ = std::fs::remove_dir_all(&scratch);
}

/// The guard's allowlist: the box's furniture, and the operator's own list.
///
/// Three processes, one daemon, one curve below the floor:
///
/// * an ordinary unleased hog — the guard must stop it;
/// * a hog whose program is called `gnome-shell` — the guard must not touch
///   it, because the desktop is never touched;
/// * a hog the operator protected by name — the guard must not touch it
///   either.
///
/// The third is the escape hatch an operator needs for the model server: it
/// is `python -m glide.server`, and every other python on the box is
/// `python` too, so the protection has to be matched against the **command
/// line**.
#[test]
fn the_guard_leaves_the_protected_processes_alone() {
    let _serial = serial_gate();
    let _lock = match Gate::take() {
        Gate::Skip => {
            eprintln!("skipping: another seat holds the box's heavy lock");
            return;
        }
        Gate::Run(file) => file,
    };
    let total = 122 * GIB;
    let floor = 8 * GIB;
    let scratch = std::env::temp_dir().join(format!("thor-admit-guard-list-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let meminfo = scratch.join("meminfo");
    write_meminfo(&meminfo, total, 100 * GIB);
    let protected = scratch.join("protected.txt");

    // A copy of the hog under the desktop's name: the guard must recognise
    // the name and leave it alone.
    let desktop = scratch.join("gnome-shell");
    std::fs::copy(HOG, &desktop).unwrap();

    // And a copy under the model server's name: the operator's list is
    // matched against the command line, and this is the case that needs it
    // — the model server and the incident's runaway are both `python`.
    let server = scratch.join("the-model-server");
    std::fs::copy(HOG, &server).unwrap();

    let daemon = DaemonUnderTest::start_named(
        "guard-and-its-allowlist",
        &[
            "--meminfo",
            meminfo.to_str().unwrap(),
            "--guard-protected-file",
            protected.to_str().unwrap(),
            "--guard-min-rss",
            "1G",
            "--guard-drop",
            "512G",
        ],
    );
    let mut protection = Protection::start(&protected);

    let mut hog = Command::new(HOG)
        .arg("--bytes")
        .arg("4G")
        .arg("--hold")
        .arg("180")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("the hog starts");
    let hog_pid = hog.id() as i32;
    protection.spare(hog_pid);

    let mut desktop_hog = Command::new(&desktop)
        .arg("--bytes")
        .arg("2G")
        .arg("--hold")
        .arg("180")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("the desktop-named hog starts");
    let desktop_pid = desktop_hog.id() as i32;

    let mut listed = Command::new(&server)
        .arg("--bytes")
        .arg("2G")
        .arg("--hold")
        .arg("180")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("the listed hog starts");
    let listed_pid = listed.id() as i32;

    // The operator's list: everything on the box but the hog, and the one
    // process the operator means to spare by name.
    protect_everything_but(&protected, &[hog_pid, desktop_pid, listed_pid]);
    let mut lines = std::fs::read_to_string(&protected).unwrap_or_default();
    lines.push_str("\n# the operator's own: the model server\n*the-model-server*\n");
    std::fs::write(&protected, lines).unwrap();

    // Wait until the hogs are holding memory.
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if rss_of(hog_pid as u32) >= GIB && rss_of(desktop_pid as u32) >= GIB {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // The curve: down through the floor in the same steps as the other
    // test, so the number the daemon reads is near the floor rather than
    // four gibibytes below it. (The first run jumped straight to 4 GiB, so
    // the daemon saw a box already deep in the danger zone, and the
    // assertion — that the guard acts *at* the floor — could not hold.)
    let writer = {
        let meminfo = meminfo.clone();
        std::thread::spawn(move || {
            write_meminfo(&meminfo, total, 12 * GIB);
            let mut available = 12 * GIB;
            while available > 0 {
                std::thread::sleep(Duration::from_millis(50));
                available = available.saturating_sub(256 * 1024 * 1024);
                write_meminfo(&meminfo, total, available);
            }
        })
    };

    // The guard must stop the ordinary hog.
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut stopped: Option<Value> = None;
    while Instant::now() < deadline {
        if let Some(event) = guard_events(&daemon, "guard.terminated").first() {
            stopped = Some(event.clone());
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let Some(event) = stopped else {
        panic!(
            "the guard did not terminate the hog; the log was:\n{}",
            daemon.log()
        );
    };
    assert_eq!(
        event["pid"].as_i64(),
        Some(hog_pid as i64),
        "the guard stopped the wrong process: {event}"
    );
    let available_at_stop = event["mem_available_bytes"].as_u64().unwrap_or(0);
    assert!(
        available_at_stop <= floor && floor - available_at_stop <= 2 * GIB,
        "the guard acted at {} MiB free, which is not the {} MiB floor",
        available_at_stop / (1024 * 1024),
        floor / (1024 * 1024)
    );

    // And the two protected processes must still be there.
    std::thread::sleep(Duration::from_secs(4));
    assert!(
        desktop_hog.try_wait().ok().flatten().is_none(),
        "the guard stopped the process named gnome-shell; the log was:\n{}",
        daemon.log()
    );
    assert!(
        listed.try_wait().ok().flatten().is_none(),
        "the guard stopped a process on the operator's list; the log was:\n{}",
        daemon.log()
    );

    let _ = writer.join();
    eprintln!(
        "guard allowlist: the ordinary hog was stopped, and the desktop-named process and the \
         operator's own were left alone"
    );

    let _ = hog.kill();
    let _ = hog.wait();
    let _ = desktop_hog.kill();
    let _ = desktop_hog.wait();
    let _ = listed.kill();
    let _ = listed.wait();
    protection.finish();
    let _ = std::fs::remove_dir_all(&scratch);
}

/// Round 12, client half: `thor-admit exec` refuses to start a framework
/// that would take the box's memory by surprise.
///
/// The refusal has to happen **before** the program runs — that is the whole
/// point. The 2026-11-01 run reached 94.5 GB in 20 seconds; by the time a
/// watchdog sees that, the desktop is already gone.
///
/// The test does not need JAX to be installed: it needs a program that
/// *looks* like a JAX program to the reader, and one that runs. So the test
/// puts a stub `jax` module on the child's `PYTHONPATH` — the import works,
/// the program's own output is the test's own.
#[test]
fn the_exec_refuses_a_framework_that_would_take_the_box() {
    let _serial = serial_gate();

    let directory = std::env::temp_dir().join(format!("thor-admit-exec-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&directory);
    std::fs::create_dir_all(&directory).unwrap();
    // A stub `jax`: importable, harmless, and enough for the program's own
    // output to be the test's output.
    std::fs::write(directory.join("jax.py"), "__version__ = 'stub'\n").unwrap();
    let pythonpath = directory.to_str().unwrap().to_string();

    // Caught by the code it is given.
    let refused = Command::new(BIN)
        .arg("exec")
        .arg("--")
        .arg("python3")
        .arg("-c")
        .arg("import jax; print('this must never run')")
        .env("PYTHONPATH", &pythonpath)
        .output()
        .expect("the exec runs");
    assert_eq!(
        refused.status.code(),
        Some(2),
        "the refusal must be a failure: {}",
        String::from_utf8_lossy(&refused.stderr)
    );
    let message = String::from_utf8_lossy(&refused.stderr);
    assert!(
        message.contains("XLA_PYTHON_CLIENT_PREALLOCATE"),
        "the refusal must say what would make it safe: {message}"
    );
    assert!(
        !String::from_utf8_lossy(&refused.stdout).contains("this must never run"),
        "the program ran anyway"
    );

    // Caught by the script on disk: the incident's run was
    // `train_spike.py --backend mjx --nworld 256`, and the file's name says
    // nothing — the import does.
    let script = directory.join("train_spike.py");
    std::fs::write(
        &script,
        "import jax\nimport jax.numpy as jnp\nprint('this must never run')\n",
    )
    .unwrap();
    let refused = Command::new(BIN)
        .arg("exec")
        .arg("--")
        .arg("python3")
        .arg(script.to_str().unwrap())
        .env("PYTHONPATH", &pythonpath)
        .output()
        .expect("the exec runs");
    assert_eq!(
        refused.status.code(),
        Some(2),
        "a script that imports jax must be refused: {}",
        String::from_utf8_lossy(&refused.stderr)
    );

    // Safe: the allocator has been told not to take the box.
    let ran = Command::new(BIN)
        .arg("exec")
        .arg("--")
        .arg("python3")
        .arg("-c")
        .arg("import jax; print('ran')")
        .env("PYTHONPATH", &pythonpath)
        .env("XLA_PYTHON_CLIENT_PREALLOCATE", "false")
        .output()
        .expect("the exec runs");
    assert!(
        ran.status.success(),
        "a safe allocator must let the program run: {}",
        String::from_utf8_lossy(&ran.stderr)
    );
    assert!(
        String::from_utf8_lossy(&ran.stdout).contains("ran"),
        "the program did not run: {}",
        String::from_utf8_lossy(&ran.stdout)
    );

    // A command that has nothing to do with a framework is not touched.
    let ran = Command::new(BIN)
        .arg("exec")
        .arg("--")
        .arg("echo")
        .arg("plain")
        .output()
        .expect("the exec runs");
    assert!(
        ran.status.success(),
        "a plain command must run: {}",
        String::from_utf8_lossy(&ran.stderr)
    );
    assert!(String::from_utf8_lossy(&ran.stdout).contains("plain"));

    // And the operator's override says so, loudly.
    let ran = Command::new(BIN)
        .arg("exec")
        .arg("--allow-preallocation")
        .arg("--")
        .arg("python3")
        .arg("-c")
        .arg("import jax; print('ran anyway')")
        .env("PYTHONPATH", &pythonpath)
        .output()
        .expect("the exec runs");
    assert!(
        ran.status.success(),
        "the override must let the program run: {}",
        String::from_utf8_lossy(&ran.stderr)
    );
    assert!(
        String::from_utf8_lossy(&ran.stderr).contains("--allow-preallocation"),
        "the override must say that it was used: {}",
        String::from_utf8_lossy(&ran.stderr)
    );
    assert!(
        String::from_utf8_lossy(&ran.stdout).contains("ran anyway"),
        "the program did not run: {}",
        String::from_utf8_lossy(&ran.stdout)
    );

    let _ = std::fs::remove_dir_all(&directory);
}
