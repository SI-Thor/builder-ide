//! The resident daemon: it holds the leases, orders the queue, and watches
//! the box.
//!
//! **The shape of it.** One thread runs the clock: every 250 ms it samples
//! the box's memory, updates what each lease is using, checks whether the
//! clients are still alive, runs the watchdog, and admits whatever now fits.
//! One thread accepts connections; each connection gets a thread of its own.
//! All of them share one lock, so the admission decision is made in one
//! place, from one picture of the box.
//!
//! **Why the client holds the lock.** The daemon cannot tell a client that
//! crashed from one that is still working, unless the kernel tells it. So the
//! client takes an exclusive `flock(2)` on the lease's file and keeps the
//! descriptor open; the daemon watches by *trying* to take the same lock. If
//! it gets it, the client is gone and the lease is released — no matter how
//! the client died. (A forked child inherits the descriptor until it execs,
//! so a lease can outlive its client by about a millisecond; the daemon
//! polls, so it never notices.)

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use serde_json::json;

use crate::admission::{Admission, LeaseMemory};
use crate::clock;
use crate::flow::{self, FlowSignal};
use crate::gpu::{GpuProbe, GpuSample};
use crate::history::{History, PeakRecord};
use crate::lease::{self, LeaseLock};
use crate::ledger::{IdleReason, Ledger, Sample};
use crate::meminfo::MemInfo;
use crate::presence::{self, JobState, PresenceJob, PresenceQueue, PresenceSpec, PresenceStore};
use crate::procscan::{self, Target};
use crate::protocol::{
    LeaseReport, PeakArg, PresenceReport, QueueReport, Request, Response, StatusReport, TargetSpec,
};
use crate::queue::{Queue, Waiter};
use crate::tier::Tier;

/// The default floor: the box must keep this much free for everything that
/// is not a lease (the desktop, the seat's own tooling, the kernel).
pub const DEFAULT_FLOOR: u64 = 25 * 1024 * 1024 * 1024;
/// The default emergency floor: below this, the watchdog acts.
pub const DEFAULT_EMERGENCY_FLOOR: u64 = 8 * 1024 * 1024 * 1024;
/// The default sample interval.
pub const DEFAULT_SAMPLE_INTERVAL: Duration = Duration::from_millis(250);
/// The default interval for reading the processes' resident sets.
pub const DEFAULT_SCAN_INTERVAL: Duration = Duration::from_millis(1000);
/// The default memory accounting file: the kernel's own.
pub const DEFAULT_MEMINFO: &str = "/proc/meminfo";
/// The default smallest lease the watchdog will touch.
pub const DEFAULT_MIN_VICTIM_RSS: u64 = 2 * 1024 * 1024 * 1024;
/// The default grace a client's silence gets before the daemon acts: six
/// missed heartbeats at the client's one-every-five-seconds, plus slack for
/// a box under load.
pub const DEFAULT_HEARTBEAT_GRACE: Duration = Duration::from_secs(60);
/// The default grace a grant gets before the daemon gives up on the client
/// ever taking the lock.
pub const DEFAULT_GRANT_GRACE: Duration = Duration::from_secs(30);
/// The default GPU's busy share of the GPU at which live work takes the GPU from
/// the presence queue.
pub const DEFAULT_GPU_BUSY_THRESHOLD: u8 = 50;
/// The default interval for reading the CPU's counters.
pub const DEFAULT_LEDGER_INTERVAL: Duration = Duration::from_secs(1);
/// The default floor for the GPU's own allocation pool (`tegrastats`' `lfb`):
/// the least that must stay free of `cudaMalloc` blocks and pinned host
/// memory, which no amount of `MemAvailable` can reclaim.
///
/// It is **0** because, measured on this box (2026-11-01, the director's
/// overnight watch), `lfb` is a contiguous-block figure — `7x4MB` is seven
/// free 4 MiB blocks of the allocation pool, a fragmentation signal — and
/// not the GPU's headroom: the Thor's memory is unified, the GPU's real
/// budget is `MemAvailable`, and the memory rule already governs it. The
/// old 2 GiB default therefore held **21 requests for over an hour while
/// ~100 GiB was available** (round 10, item a). The rule is still there
/// for an operator who wants it — `--gpu-floor 2G` — applied to leases
/// whose labels have held device memory; a lease that promises none never
/// waits for the pool (see [`crate::admission::Admission::gpu_admits`]).
pub const DEFAULT_GPU_FLOOR: u64 = 0;
/// The default startup deadline: a daemon that has not begun serving within
/// this long stops itself.
///
/// The auto-started daemon of 04:15 on 2026-11-01 hung on the way up and
/// sat on the box indefinitely; the deadline turns "indefinitely" into a
/// bounded window after which the next auto-start recovers (round 10,
/// item b). Fifteen seconds is a long start on this box — the tests' whole
/// daemons come up in well under two — so a daemon that misses it was not
/// coming up at all.
pub const DEFAULT_STARTUP_TIMEOUT: Duration = Duration::from_secs(15);
/// How many runs a label needs before `--peak auto` will speak.
///
/// A p95 of two runs is a guess wearing a percentile's clothes: one shifted
/// workload and the reservation is half of what the label costs. Three runs
/// is the smallest sample whose p95 has seen the label misbehave once and
/// still survived (Hy4's second failure mode: the p95 reserved too little,
/// the box blew through the emergency floor before the watchdog could act).
pub const MIN_AUTO_RUNS: usize = 3;
/// How much a running lease must grow beyond what it has already over-run
/// before another interim peak is written.
const OVERRUN_WRITE_STEP: u64 = 512 * 1024 * 1024;

/// How far a lease may exceed its reservation before the over-run watch
/// speaks: 2 % of the reservation, at least 128 MiB.
///
/// A lease that reserved exactly what it meant to use still measures a
/// little over its number — the runtime itself, the allocator's own pages —
/// and calling that an over-run would cry wolf on every honest lease. The
/// tolerance is what the watch is *not* about: it is after the gross
/// under-reservations, the 40 GiB reserved against a 55 GiB reality, where
/// the box has no swap to absorb the difference.
fn overrun_tolerance(reserved: u64) -> u64 {
    (reserved / 50).max(128 * 1024 * 1024)
}

/// How the daemon is set up.
#[derive(Clone, Debug)]
pub struct Config {
    /// The socket the clients connect to.
    pub socket: PathBuf,
    /// Where the daemon keeps its state (the lease files, the log).
    pub state_dir: PathBuf,
    /// Where the learned peaks are written.
    pub history: PathBuf,
    /// Where the box's memory accounting is read from.
    ///
    /// It is the kernel's own `/proc/meminfo` in production, and it should
    /// stay that way: point the daemon at anything else and the watchdog is
    /// watching a number the kernel is not using. The option exists so a
    /// test can drive a memory **curve** — the real box cannot be taken to
    /// 2 GiB free for a test, and the watchdog's promise is about the
    /// curve, not about one snapshot.
    pub meminfo: PathBuf,
    /// The floor a new lease has to clear.
    pub floor: u64,
    /// Below this much free memory, the watchdog acts.
    pub emergency_floor: u64,
    /// How often the box is sampled.
    pub sample_interval: Duration,
    /// How often the processes' resident sets are read. The scan reads every
    /// process on the box, so it is the daemon's main cost; it does not
    /// need to be as fast as the memory sample. When the box falls below
    /// the emergency floor, the daemon scans anyway.
    pub scan_interval: Duration,
    /// How many samples the watchdog's victim is given to exit after its
    /// `SIGTERM` before the watchdog escalates to `SIGKILL`.
    pub stop_grace_samples: u32,
    /// The smallest lease the watchdog will touch. The box's own services are
    /// not leases at all, so they are never candidates; this floor is the
    /// second guard: a lease too small to be the cause is not the cause.
    pub min_victim_rss: u64,
    /// Which GPU view to use.
    pub gpu_probe: GpuProbe,
    /// Exit after this long with nothing to do. Zero means never.
    pub idle_exit: Duration,
    /// When a client's lease is released because the client died, stop the
    /// work the client was running. A client that crashes leaves its
    /// command running with nobody watching it, and an unwatched 30 GiB
    /// hog is exactly the thing this daemon exists to prevent.
    pub stop_on_client_gone: bool,
    /// Run the presence queue: the registered work that runs when the box
    /// has room and live work is not waiting.
    pub presence: bool,
    /// Where the presence queue is kept.
    pub presence_file: PathBuf,
    /// Where the time ledger's hours are written.
    pub ledger: PathBuf,
    /// How often the CPU's counters are read for the ledger.
    pub ledger_interval: Duration,
    /// The GPU's busy share, in per cent, at which live work takes the GPU
    /// from the presence queue.
    pub gpu_busy_threshold: u8,
    /// Let live work stop the presence queue's jobs so that live work can
    /// have the GPU.
    pub gpu_preempt: bool,
    /// How long an active lease's client may stay silent — no heartbeat,
    /// no release — before the daemon decides the client is stuck and takes
    /// the lease back. The lock alone is not liveness: a hung client's lock
    /// never drops.
    pub heartbeat_grace: Duration,
    /// How long a granted lease may sit unclaimed before the daemon gives
    /// up on the client ever taking the lock.
    pub grant_grace: Duration,
    /// The least the GPU's own allocation pool must keep free (see
    /// [`DEFAULT_GPU_FLOOR`]). Applied only when something can see the pool.
    pub gpu_floor: u64,
    /// How long a daemon has to begin serving after it starts. A daemon
    /// that misses the deadline stops itself: the kernel drops its socket
    /// lock, and the next client's auto-start takes the socket back
    /// (round 10, item b). Zero means no deadline.
    pub startup_timeout: Duration,
    /// The `tegrastats` to run, when it is not the one on the `PATH`.
    ///
    /// It is a test seam, like `meminfo`: the real daemon runs the real
    /// `tegrastats`, and a test runs a script that prints a pool the test
    /// controls, so the GPU rule can be driven without touching the GPU.
    pub tegrastats_command: Option<PathBuf>,
    /// Where the flow signal is published. The daemon reads it when it
    /// changes and records it in the ledger's hour; it computes nothing and
    /// decides nothing from it (see `flow`).
    pub flow_file: PathBuf,
}

impl Default for Config {
    fn default() -> Self {
        let state_dir = default_state_dir();
        Config {
            socket: default_socket_path(),
            history: state_dir.join("peaks.jsonl"),
            state_dir,
            meminfo: PathBuf::from(DEFAULT_MEMINFO),
            floor: DEFAULT_FLOOR,
            emergency_floor: DEFAULT_EMERGENCY_FLOOR,
            sample_interval: DEFAULT_SAMPLE_INTERVAL,
            scan_interval: DEFAULT_SCAN_INTERVAL,
            stop_grace_samples: 8,
            min_victim_rss: DEFAULT_MIN_VICTIM_RSS,
            gpu_probe: GpuProbe::Auto,
            idle_exit: Duration::from_secs(900),
            stop_on_client_gone: true,
            presence: true,
            presence_file: default_state_dir().join("presence.json"),
            ledger: default_state_dir().join("ledger.jsonl"),
            ledger_interval: DEFAULT_LEDGER_INTERVAL,
            gpu_busy_threshold: DEFAULT_GPU_BUSY_THRESHOLD,
            gpu_preempt: true,
            heartbeat_grace: DEFAULT_HEARTBEAT_GRACE,
            grant_grace: DEFAULT_GRANT_GRACE,
            gpu_floor: DEFAULT_GPU_FLOOR,
            startup_timeout: DEFAULT_STARTUP_TIMEOUT,
            tegrastats_command: None,
            flow_file: default_state_dir().join("flow.json"),
        }
    }
}

/// The default state directory: `$XDG_STATE_HOME/thor-admit`, or
/// `~/.local/state/thor-admit`.
pub fn default_state_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("XDG_STATE_HOME") {
        if !dir.is_empty() {
            return PathBuf::from(dir).join("thor-admit");
        }
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".local/state/thor-admit")
}

/// The default socket path: `$XDG_RUNTIME_DIR/thor-admit.sock`, or
/// `/tmp/thor-admit-<uid>.sock`.
pub fn default_socket_path() -> PathBuf {
    if let Ok(dir) = std::env::var("XDG_RUNTIME_DIR") {
        if !dir.is_empty() {
            return PathBuf::from(dir).join("thor-admit.sock");
        }
    }
    let uid = unsafe { libc::getuid() };
    PathBuf::from(format!("/tmp/thor-admit-{uid}.sock"))
}

/// What a lease is doing right now.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LeaseState {
    /// Granted, but the client has not said it holds the lock yet.
    Granted,
    /// The client holds the lock: the lease is real.
    Active,
}

/// One lease.
#[derive(Clone, Debug)]
struct Lease {
    id: u64,
    label: String,
    peak_bytes: u64,
    priority: i32,
    /// Which tier of work this lease is. The tier is an accounting band, and
    /// only a live lease may pre-empt the presence queue.
    tier: Tier,
    target: TargetSpec,
    lock_path: PathBuf,
    state: LeaseState,
    granted_at: Instant,
    /// The client that asked for this lease, from the socket's own
    /// credentials — the process the daemon signals when the client goes
    /// silent, and the one whose death explains a dropped lock.
    client_pid: i32,
    /// When the client last said it was alive (`held` or a heartbeat).
    last_heartbeat: Option<Instant>,
    /// The daemon has already signalled this lease's silent client.
    stale_signalled: bool,
    current_rss: u64,
    peak_rss: u64,
    peak_gpu: u64,
    /// The peak the client measured itself (its `rusage`).
    reported_peak: Option<u64>,
    /// The running peak already written to the history by the over-run
    /// watch, so an over-running lease is on record while it is still
    /// running — even if the box, or the daemon, does not outlive it.
    overrun_written: u64,
    /// How the command finished, as the client reported it on release: 0 is
    /// a clean exit. A lease whose run did not finish cleanly teaches the
    /// peak history nothing.
    reported_exit: Option<i32>,
    /// The watchdog has asked this lease's work to terminate (`SIGTERM`).
    ///
    /// The ask is sent once. The memory comes back when the process is
    /// actually gone — the client reaps its child and releases, or the lock
    /// drops when the client dies — and until then the reservation stays
    /// charged, because the pages are still taken.
    terminated_at: Option<Instant>,
    /// The watchdog has escalated to `SIGKILL` after the grace period.
    killed: bool,
}

impl Lease {
    fn memory(&self) -> LeaseMemory {
        LeaseMemory::new(self.peak_bytes, self.current_rss)
    }

    /// The peak to record: the client's own measurement if it gave one, and
    /// the daemon's samples otherwise; the larger of the two wins.
    fn measured_peak(&self) -> (u64, &'static str) {
        match self.reported_peak {
            Some(reported) if reported >= self.peak_rss => (reported, "rusage"),
            _ if self.peak_rss > 0 => (self.peak_rss, "sample"),
            Some(reported) => (reported, "rusage"),
            None => (0, "none"),
        }
    }
}

/// What a client asked for when it took a lease.
struct AcquireRequest {
    label: String,
    peak: PeakArg,
    priority: i32,
    tier: Tier,
    target: TargetSpec,
    /// The asking client's pid, from the socket's credentials.
    client_pid: i32,
}

/// What a client asked for when it registered a presence job.
struct PresenceRequest {
    label: String,
    tier: Tier,
    peak: PeakArg,
    resumable: bool,
    enabled: bool,
    command: Vec<String>,
}

/// A presence job that is running.
struct RunningJob {
    id: u64,
    /// The child's process group: what the daemon signals.
    pgid: i32,
    started_at: Instant,
    current_rss: u64,
    peak_rss: u64,
    /// The lease the daemon holds for this job. The daemon is the client
    /// here: it holds the lock, so the job's memory is charged to the box
    /// exactly as a client's would be.
    #[allow(dead_code)]
    lock: LeaseLock,
    /// The job was stopped (`SIGSTOP`) so live work could have the GPU. A
    /// stopped job keeps its memory: it gives up the GPU, not the memory.
    stopped: bool,
    /// The job was asked to stop (`SIGTERM`) so its memory could be given
    /// back. It is still holding that memory until it is gone.
    terminating: bool,
}

/// The presence queue and the jobs that are running from it.
struct PresenceState {
    /// The registered jobs.
    queue: PresenceQueue,
    /// Where the queue is kept.
    store: PresenceStore,
    /// The jobs with a live child.
    running: Vec<RunningJob>,
    /// The size and the modification time of the store when it was last
    /// read, so the daemon knows when it changed.
    stamp: Option<(u64, u64)>,
}

impl RunningJob {
    /// The tier of the registered job this run belongs to.
    fn tier(&self, state: &State) -> Tier {
        state
            .presence
            .queue
            .get(self.id)
            .map(|job| job.spec.tier)
            .unwrap_or(Tier::Study)
    }

    /// The label of the registered job this run belongs to.
    fn label(&self, state: &State) -> String {
        state
            .presence
            .queue
            .get(self.id)
            .map(|job| job.spec.label.clone())
            .unwrap_or_default()
    }
}

impl PresenceState {
    /// The job that is running under this id.
    fn running_job(&self, id: u64) -> Option<&RunningJob> {
        self.running.iter().find(|job| job.id == id)
    }

    /// The memory the running jobs are holding: what they promised and what
    /// they are using.
    fn memory(&self) -> Vec<LeaseMemory> {
        self.running
            .iter()
            .map(|job| {
                let reserved = self
                    .queue
                    .get(job.id)
                    .map(|registered| registered.spec.peak_bytes)
                    .unwrap_or(0);
                LeaseMemory::new(reserved, job.current_rss)
            })
            .collect()
    }
}

/// The daemon's picture of the box.
struct State {
    leases: Vec<Lease>,
    queue: Queue,
    /// Where the answer for a waiting request goes.
    waiters: HashMap<u64, Sender<Response>>,
    /// What each waiting request wants to lease.
    targets: HashMap<u64, TargetSpec>,
    /// Who asked for each waiting request, so the lease can carry the
    /// client's pid from the queue to the grant.
    client_pids: HashMap<u64, i32>,
    /// When each waiting request arrived.
    waiting_since: HashMap<u64, Instant>,
    /// Requests that arrived and are not handled yet: the request, the
    /// client that sent it (its pid, from the socket's credentials), and
    /// where the answer goes.
    inbox: Vec<(i32, Request, Sender<Response>)>,
    next_id: u64,
    mem: MemInfo,
    gpu: GpuSample,
    gpu_source: String,
    samples: u64,
    started: Instant,
    last_activity: Instant,
    history: History,
    /// The presence queue: registered work and what is running from it.
    presence: PresenceState,
    /// The time ledger: where the box's hours are going.
    ledger: Ledger,
    /// When the CPU's counters were last read.
    last_cpu_read: Instant,
    /// The waiters the GPU's own pool is holding up, so each is logged once
    /// rather than every sample.
    gpu_blocked: std::collections::HashSet<u64>,
    /// The flow signal as last published, when a publisher is speaking.
    flow: Option<FlowSignal>,
    /// The size and the modification time of the flow file when it was last
    /// read, so the daemon re-reads it only when it changed.
    flow_stamp: Option<(u64, u64)>,
}

/// A child process that keeps printing the GPU's view.
///
/// Asking `nvidia-smi` afresh every couple of seconds costs the daemon
/// a fork and an exec each time: measured on this box, 16 678 minor
/// faults and half a core's worth of reaped children's CPU over 30 s.
/// A child that keeps printing costs one fork, ever: the daemon reads
/// its lines and keeps the last sample.
struct GpuWatch {
    sample: Arc<Mutex<GpuSample>>,
    source: String,
    /// Kept alive: when it is dropped, the child is killed.
    _child: Arc<Mutex<std::process::Child>>,
}

/// The daemon.
pub struct Daemon {
    config: Config,
    state: Mutex<State>,
    wake: Condvar,
    stop: Arc<AtomicBool>,
    /// Has the acceptor been started? The startup watchdog (the CLI) asks,
    /// so a daemon that never begins serving does not sit on the box
    /// forever (round 10, item b).
    serving: AtomicBool,
    listener: Mutex<Option<UnixListener>>,
    /// The GPU's views, kept fresh by children that keep printing them.
    gpu_watch: Mutex<Vec<GpuWatch>>,
    /// The daemon's own log. It has its own lock so that a log line can be
    /// written while the state lock is held.
    log: Mutex<Option<std::fs::File>>,
    /// The lock on the socket's lock file.
    ///
    /// It is taken **after** the socket is bound, with nothing between the
    /// two but the `flock` call itself, and it is held for as long as the
    /// daemon runs. It is what makes "one daemon per socket" a fact rather
    /// than a hope: two daemons on one socket would be two admission
    /// controllers with two views of the box, which is the thing this crate
    /// exists to prevent. The kernel drops the lock when the daemon dies,
    /// whatever killed it.
    ///
    /// Nothing reads it: the descriptor *is* the lock.
    #[allow(dead_code)]
    socket_lock: std::fs::File,
}

/// The peak `--peak auto` reserves for a label: the larger of the p95 and
/// the last run, once the label has enough runs to be believed.
///
/// The p95 alone is not enough. The p95 says what the label *usually*
/// costs; the last run says what it cost the last time the workload looked
/// like this one. A label whose last run overran its history — a bigger
/// scene, a longer batch — is exactly the label a p95-only reservation
/// would under-reserve, and an under-reserved lease on a box with no swap
/// arrives at the emergency floor with the watchdog already late.
fn learned_peak(state: &State, label: &str) -> Result<u64, String> {
    let runs = state.history.runs(label);
    if runs == 0 {
        return Err(format!(
            "no history for the label {label:?}, so there is no learned peak; \
             run it once with an explicit --peak"
        ));
    }
    if runs < MIN_AUTO_RUNS {
        return Err(format!(
            "only {runs} run(s) for the label {label:?}; --peak auto needs {MIN_AUTO_RUNS} \
             before it will guess, because a p95 of so few runs under-reserves a shifted \
             workload; give it an explicit --peak until then"
        ));
    }
    let p95 = state.history.p95(label).unwrap_or(0);
    let last = state.history.last(label).unwrap_or(0);
    Ok(p95.max(last))
}

impl Daemon {
    /// Build a daemon.
    ///
    /// The order is the fix for round 10, item b: **construct, then bind,
    /// then lock.** The 04:15 daemon took the socket's lock first and hung
    /// before it bound the socket — stuck in `futex_wait_queue`, owning the
    /// one-per-socket lock, with a stale socket file beside it — so every
    /// later client got "connection refused" and every later daemon was
    /// refused with "another thor-admit daemon is already running" until a
    /// human killed the wedged process. With the order turned around:
    ///
    /// * a daemon that hangs on the way up (the history file, the log, the
    ///   meminfo — all of that comes *first*) holds nothing the next daemon
    ///   needs: no lock to refuse it with, no bound socket to answer nobody;
    /// * the socket is bound and the lock taken back to back, with nothing
    ///   between them but the `flock` call, so the window where the two
    ///   disagree is a syscall wide;
    /// * the bound socket arbitrates starters on its own — `bind` on an
    ///   existing path fails — so two daemons racing for one socket still
    ///   end with exactly one of them running.
    pub fn new(config: Config) -> std::io::Result<Arc<Daemon>> {
        hang_on_the_way_up_for_test();
        std::fs::create_dir_all(&config.state_dir)?;
        std::fs::create_dir_all(config.state_dir.join("leases"))?;
        let history = History::load(&config.history);
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(config.state_dir.join("daemon.log"))
            .ok();
        let state = State {
            leases: Vec::new(),
            queue: Queue::new(),
            waiters: HashMap::new(),
            targets: HashMap::new(),
            client_pids: HashMap::new(),
            waiting_since: HashMap::new(),
            inbox: Vec::new(),
            next_id: 1,            mem: MemInfo::read().unwrap_or_default(),
            gpu: GpuSample::default(),
            gpu_source: config.gpu_probe.as_str().to_string(),
            samples: 0,
            started: Instant::now(),
            last_activity: Instant::now(),
            history,
            presence: PresenceState {
                queue: PresenceQueue::new(),
                store: PresenceStore::new(&config.presence_file),
                running: Vec::new(),
                stamp: None,
            },
            ledger: Ledger::new(&config.ledger),
            last_cpu_read: Instant::now(),
            gpu_blocked: std::collections::HashSet::new(),
            flow: None,
            flow_stamp: None,
        };
        let socket = config.socket.clone();
        let listener = bind_listener(&socket)?;
        let socket_lock = take_socket_lock(&socket).inspect_err(|_| {
            // Somebody else owns this socket by the lock's word — a daemon
            // whose acceptor has died, or one racing us for a socket whose
            // file was stale. The socket we just bound is ours (nobody else
            // could bind it), so it goes with us.
            let _ = std::fs::remove_file(&socket);
        })?;
        Ok(Arc::new(Daemon {
            config,
            state: Mutex::new(state),
            wake: Condvar::new(),
            stop: Arc::new(AtomicBool::new(false)),
            serving: AtomicBool::new(false),
            listener: Mutex::new(Some(listener)),
            log: Mutex::new(log),
            gpu_watch: Mutex::new(Vec::new()),
            socket_lock,
        }))
    }

    /// The daemon's configuration.
    pub fn config(&self) -> &Config {
        &self.config
    }

    /// Ask the daemon to stop.
    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        self.wake.notify_all();
    }

    /// Has the daemon been asked to stop — by a signal, or by its own
    /// idle exit?
    ///
    /// A supervisor that waits on the daemon (the CLI's own signal
    /// watcher) needs this: after an idle exit the daemon's clock has
    /// already left, and without a word to say so, a watcher waiting for a
    /// signal would wait forever while the daemon's socket lock kept every
    /// future daemon out.
    pub fn is_stopped(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }

    /// Has the acceptor been started — is the daemon actually serving?
    ///
    /// The startup watchdog asks this (round 10, item b): a daemon that
    /// never got as far as serving must not sit on the box holding a bound
    /// socket that answers nobody, so the watchdog gives startup a
    /// deadline and the deadline needs a word for "it began".
    pub fn is_serving(&self) -> bool {
        self.serving.load(Ordering::SeqCst)
    }

    /// The path of the socket the daemon listens on.
    pub fn socket_path(&self) -> &Path {
        &self.config.socket
    }

    /// Run the daemon until it is stopped.
    ///
    /// The socket was bound in [`Daemon::new`]; the acceptor is the first
    /// thing that runs here, so the daemon answers from the moment the
    /// process is serving and the startup watchdog can see that it did.
    pub fn run(self: &Arc<Self>) -> std::io::Result<()> {
        let daemon = Arc::clone(self);
        let acceptor = std::thread::Builder::new()
            .name("thor-admit-accept".to_string())
            .spawn(move || daemon.accept_loop())?;
        self.serving.store(true, Ordering::SeqCst);
        self.start_gpu_watch();
        let mem_total = {
            let state = self.state.lock().unwrap();
            state.mem.mem_total
        };
        self.log_event(
            "daemon.started",
            json!({
                "socket": self.config.socket.display().to_string(),
                "floor_bytes": self.config.floor,
                "emergency_floor_bytes": self.config.emergency_floor,
                "gpu_floor_bytes": self.config.gpu_floor,
                "sample_interval_ms": self.config.sample_interval.as_millis() as u64,
                "meminfo": self.config.meminfo.display().to_string(),
                "gpu_probe": self.config.gpu_probe.as_str(),
                "mem_total_bytes": mem_total,
                "history": self.config.history.display().to_string(),
                "flow_file": self.config.flow_file.display().to_string(),
            }),
        );

        self.clock_loop();

        self.stop.store(true, Ordering::SeqCst);
        let _ = acceptor.join();
        // The presence jobs are the daemon's own children: it stops them on
        // the way out, so the box is not left with work nobody is watching.
        self.stop_presence_jobs();
        let _ = std::fs::remove_file(&self.config.socket);
        Ok(())
    }

    /// Stop the presence jobs that are running.
    fn stop_presence_jobs(&self) {
        let state = self.state.lock().unwrap();
        for job in state.presence.running.iter() {
            let signalled = terminate_group(job.pgid);
            self.log_event(
                "presence.stopped_with_daemon",
                json!({"id": job.id, "signalled": signalled}),
            );
        }
    }

    /// Accept connections until the daemon stops.
    fn accept_loop(self: Arc<Self>) {
        loop {
            if self.stop.load(Ordering::SeqCst) {
                return;
            }
            let accepted = {
                let guard = self.listener.lock().unwrap();
                match guard.as_ref() {
                    Some(listener) => listener.accept(),
                    None => return,
                }
            };
            match accepted {
                Ok((stream, _)) => {
                    let daemon = Arc::clone(&self);
                    let _ = std::thread::Builder::new()
                        .name("thor-admit-client".to_string())
                        .spawn(move || daemon.serve(stream));
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(error) => {
                    // The front door is broken. A daemon that cannot answer
                    // is worse than one that is not there: it keeps sampling
                    // the box and looking alive to everything that checks.
                    // So it says why and stops.
                    if accept_error_is_fatal(&error) {
                        self.log_event(
                            "daemon.acceptor_failed",
                            json!({
                                "error": error.to_string(),
                                "kind": format!("{:?}", error.kind()),
                            }),
                        );
                        self.stop();
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
            }
        }
    }

    /// Serve one client connection.
    fn serve(self: Arc<Self>, stream: UnixStream) {
        // Who is talking: the socket's own credentials. The daemon never
        // trusts the client to name itself — the pid is what the kernel put
        // on the connection, and it is how a silent client is told apart
        // from a dead one.
        let peer = peer_pid(&stream);
        let reader = BufReader::new(match stream.try_clone() {
            Ok(stream) => stream,
            Err(_) => return,
        });
        let mut writer = stream;
        for line in reader.lines() {
            let Ok(line) = line else { break };
            if line.trim().is_empty() {
                continue;
            }
            let request: Request = match serde_json::from_str(&line) {
                Ok(request) => request,
                Err(error) => {
                    let response = Response::Error {
                        message: format!("cannot read the request: {error}"),
                    };
                    let _ = write_line(&mut writer, &response);
                    break;
                }
            };
            let (reply_tx, reply_rx) = channel::<Response>();
            {
                let mut state = self.state.lock().unwrap();
                state.inbox.push((peer, request, reply_tx));
                state.last_activity = Instant::now();
                self.wake.notify_all();
            }
            // Every response for this request goes down the same channel, in
            // order: the client reads them until one ends the exchange.
            while let Ok(response) = reply_rx.recv() {
                let terminal = matches!(
                    response,
                    Response::Granted { .. }
                        | Response::Rejected { .. }
                        | Response::Error { .. }
                        | Response::Status(_)
                        | Response::Ok
                );
                if write_line(&mut writer, &response).is_err() {
                    break;
                }
                if terminal {
                    break;
                }
            }
        }
    }

    /// The clock: sample, watch, admit.
    fn clock_loop(&self) {
        loop {
            if self.stop.load(Ordering::SeqCst) {
                return;
            }
            {
                let state = self.state.lock().unwrap();
                let _ = self.wake.wait_timeout(state, self.config.sample_interval);
            }
            if self.stop.load(Ordering::SeqCst) {
                return;
            }
            // The GPU's children keep printing their own view; the daemon
            // reads their last line, which costs a mutex and a clone. There
            // is no fork here: the children were started once, at boot.
            self.tick();

            if self.config.idle_exit > Duration::ZERO {
                let idle = {
                    let state = self.state.lock().unwrap();
                    state.last_activity.elapsed()
                };
                if idle > self.config.idle_exit {
                    self.log_event("daemon.idle_exit", json!({"idle_s": idle.as_secs()}));
                    return;
                }
            }
        }
    }

    /// One tick of the clock.
    fn tick(&self) {
        let mut state = self.state.lock().unwrap();
        state.samples += 1;

        // 1. What the clients asked for.
        let inbox = std::mem::take(&mut state.inbox);
        for (peer, request, reply) in inbox {
            match request {
                Request::Acquire {
                    label,
                    peak,
                    priority,
                    tier,
                    target,
                } => self.register_acquire(
                    &mut state,
                    AcquireRequest {
                        label,
                        peak,
                        priority,
                        tier,
                        target,
                        client_pid: peer,
                    },
                    reply,
                ),
                Request::Held { lease } => {
                    if let Some(found) = state.leases.iter_mut().find(|l| l.id == lease) {
                        found.state = LeaseState::Active;
                        found.last_heartbeat = Some(Instant::now());
                    }
                    let _ = reply.send(Response::Ok);
                }
                Request::Heartbeat { lease } => {
                    if let Some(found) = state.leases.iter_mut().find(|l| l.id == lease) {
                        found.last_heartbeat = Some(Instant::now());
                    }
                    let _ = reply.send(Response::Ok);
                }
                Request::Release {
                    lease,
                    peak_rss_bytes,
                    exit_code,
                } => {
                    if let Some(found) = state.leases.iter_mut().find(|l| l.id == lease) {
                        if let Some(peak) = peak_rss_bytes {
                            found.reported_peak = Some(peak);
                        }
                        found.reported_exit = exit_code;
                    }
                    self.release_lease(&mut state, lease, "client");
                    let _ = reply.send(Response::Ok);
                }
                Request::PresenceAdd {
                    label,
                    tier,
                    peak,
                    resumable,
                    enabled,
                    command,
                } => self.register_presence(
                    &mut state,
                    PresenceRequest {
                        label,
                        tier,
                        peak,
                        resumable,
                        enabled,
                        command,
                    },
                    reply,
                ),
                Request::PresenceRemove { id } => {
                    self.remove_presence(&mut state, id, reply);
                }
                Request::PresenceList => {
                    let jobs = presence_reports(&state);
                    let _ = reply.send(Response::Presence { jobs });
                }
                Request::Reload => {
                    let (peaks, presence) = self.reload_state(&mut state);
                    let _ = reply.send(Response::Reloaded { peaks, presence });
                }
                Request::Ledger => {
                    let buckets = state.ledger.closed_buckets();
                    let current = Box::new(state.ledger.bucket().clone());
                    let _ = reply.send(Response::Ledger { buckets, current });
                }
                Request::Status => {
                    let report = status_report(&state, &self.config);
                    let _ = reply.send(Response::Status(Box::new(report)));
                }
                Request::Ping => {
                    let _ = reply.send(Response::Ok);
                }
            }
        }

        // 2. The box.
        if let Ok(mem) = MemInfo::read_from(&self.config.meminfo) {
            state.mem = mem;
        }
        // The GPU's children keep printing; the daemon reads their last
        // line. It is always read — the ledger wants the GPU's power and
        // busy share even when the box is doing nothing, because "the GPU
        // was idle at 3 W" is one of the numbers the ledger exists to keep.
        {
            let watches = self.gpu_watch.lock().unwrap();
            let (merged, sources) = merge_gpu_samples(watches.as_slice());
            state.gpu = merged;
            state.gpu_source = sources;
        }
        // The flow signal, when a publisher is speaking: read only when the
        // file changed, recorded only — the numbers are the publisher's and
        // so is any decision made from them.
        self.read_flow(&mut state);

        // 3. What each lease is using. The scan reads every process on the
        // box, so it runs on its own slower clock — unless the box is short
        // of memory, when the watchdog needs a fresh ranking now.
        let scan_every = (self.config.scan_interval.as_millis()
            / self.config.sample_interval.as_millis().max(1))
            .max(1) as u64;
        let urgent = state.mem.mem_available < self.config.emergency_floor;
        let has_work = !state.leases.is_empty() || !state.presence.running.is_empty();
        if has_work && (state.samples % scan_every == 0 || urgent) {
            let procs = procscan::scan();
            let gpu = state.gpu.clone();
            let mut overruns = Vec::new();
            for lease in state.leases.iter_mut() {
                let usage = procscan::usage_for(target_of(lease.target), &procs);
                lease.current_rss = usage.rss_bytes;
                lease.peak_rss = lease.peak_rss.max(usage.rss_bytes);
                lease.peak_gpu = lease.peak_gpu.max(gpu.for_pids(&usage.pids));
                // The over-run watch. A lease past its reservation is the
                // number the admission rule was wrong by, and the fact is
                // worth more than the log line: the peak goes into the
                // history *now*, while the lease is still running, so the
                // next `--peak auto` reserves it even if this run takes the
                // daemon with it. The first crossing writes; each further
                // half-gibibyte of growth writes again.
                if lease.peak_rss
                    > lease.peak_bytes.saturating_add(overrun_tolerance(lease.peak_bytes))
                    && (lease.overrun_written == 0
                        || lease.peak_rss >= lease.overrun_written + OVERRUN_WRITE_STEP)
                {
                    overruns.push((
                        lease.id,
                        lease.label.clone(),
                        lease.peak_bytes,
                        lease.peak_rss,
                        lease.peak_gpu,
                    ));
                    lease.overrun_written = lease.peak_rss;
                }
            }
            for job in state.presence.running.iter_mut() {
                let usage = procscan::usage_for(Target::Group(job.pgid), &procs);
                job.current_rss = usage.rss_bytes;
                job.peak_rss = job.peak_rss.max(usage.rss_bytes);
            }
            for (id, label, reserved, peak_rss, peak_gpu) in overruns {
                self.log_event(
                    "lease.underreserved",
                    json!({
                        "lease": id,
                        "label": label,
                        "reserved_bytes": reserved,
                        "peak_rss_bytes": peak_rss,
                        "over_by_bytes": peak_rss.saturating_sub(reserved),
                        "mem_available_bytes": state.mem.mem_available,
                    }),
                );
                let mut record = PeakRecord::new(&label, &label, peak_rss);
                record.peak_source = "overrun".to_string();
                record.peak_gpu_bytes = if peak_gpu > 0 { Some(peak_gpu) } else { None };
                record.gpu_visible =
                    state.gpu_source != "off" && !state.gpu_source.contains("unavailable");
                record.mem_total_bytes = state.mem.mem_total;
                record.floor_bytes = self.config.floor;
                if let Err(error) = state.history.append(record) {
                    self.log_event("history.write_failed", json!({"error": error.to_string()}));
                }
            }
        }

        // 4. Are the clients still there, and are the presence jobs?
        self.check_liveness(&mut state);
        self.reap_presence(&mut state);

        // 5. The watchdog.
        self.watchdog(&mut state);

        // 6. The presence queue: pick up a queue that changed, and give the
        // box's room back when live work needs it.
        self.presence_tick(&mut state);

        // 7. Admission.
        self.admit(&mut state);

        // 8. And the ledger: where the box's time went.
        self.ledger_tick(&mut state);

        // 9. And a line in the log, every ten seconds.
        if state.samples % 40 == 0 {
            self.log_event(
                "daemon.sample",
                json!({
                    "mem_available_bytes": state.mem.mem_available,
                    "mem_total_bytes": state.mem.mem_total,
                    "gpu_largest_free_block_bytes": state.gpu.largest_free_block,
                    "gpu_box_used_bytes": state.gpu.box_used_bytes,
                    "leases": state.leases.len(),
                    "waiting": state.queue.len(),
                    "presence_running": state.presence.running.len(),
                    "presence_registered": state.presence.queue.outstanding(),
                    "gpu_source": state.gpu_source,
                }),
            );
        }
    }

    /// Read the flow signal when the file has changed.
    ///
    /// A missing file is no signal — the daemon records absence, never a
    /// guess — and a file that stops changing keeps saying what it last
    /// said, which is the publisher's business, not the daemon's.
    fn read_flow(&self, state: &mut State) {
        let stamp = std::fs::metadata(&self.config.flow_file).ok().map(|meta| {
            (
                meta.len(),
                meta.modified()
                    .ok()
                    .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
                    .map(|duration| duration.as_nanos() as u64)
                    .unwrap_or(0),
            )
        });
        if stamp == state.flow_stamp {
            return;
        }
        state.flow_stamp = stamp;
        let signal = std::fs::read_to_string(&self.config.flow_file)
            .ok()
            .and_then(|text| flow::parse(&text));
        if signal != state.flow {
            self.log_event(
                "flow.sign",
                json!({
                    "confidence": signal.and_then(|signal| signal.confidence),
                    "rate_of_change": signal.and_then(|signal| signal.rate_of_change),
                    "sign": signal.and_then(|signal| signal.sign()),
                    "file": self.config.flow_file.display().to_string(),
                }),
            );
        }
        state.flow = signal;
    }

    /// Re-read what the daemon reads from disk: the peak history and the
    /// presence queue.
    ///
    /// Both live in memory once loaded, so an edit by hand — an operator
    /// cleaning no-op records out of the history at 00:50, a night runner
    /// editing the queue — is invisible to a running daemon until it
    /// reloads. `SIGHUP` and the `reload` op both land here. What reload
    /// never touches is the running leases: they are the clients' word, not
    /// the disk's.
    pub fn reload(&self) {
        let mut state = self.state.lock().unwrap();
        self.reload_state(&mut state);
    }

    /// The body of a reload, on an already-locked state.
    fn reload_state(&self, state: &mut State) -> (usize, usize) {
        let history = History::load(&self.config.history);
        let peaks = history.records().len();
        state.history = history;
        // Re-read the presence queue now, keeping the state of whatever is
        // running: the file says what is registered, not what is happening.
        state.presence.stamp = None;
        self.reload_presence(state);
        let presence = state.presence.queue.jobs().len();
        self.log_event(
            "daemon.reloaded",
            json!({
                "peaks": peaks,
                "presence": presence,
                "history": self.config.history.display().to_string(),
            }),
        );
        (peaks, presence)
    }

    /// Put a new request in the queue.
    fn register_acquire(
        &self,
        state: &mut State,
        request: AcquireRequest,
        reply: Sender<Response>,
    ) {
        let AcquireRequest {
            label,
            peak,
            priority,
            tier,
            target,
            client_pid,
        } = request;
        let peak_bytes = match peak {
            PeakArg::Bytes(bytes) => bytes,
            PeakArg::Auto => match learned_peak(state, &label) {
                Ok(learned) => learned,
                Err(reason) => {
                    let _ = reply.send(Response::Rejected { reason });
                    return;
                }
            },
        };

        let id = state.next_id;
        state.next_id += 1;
        // The GPU promise is learned, not asked for: the label's own history
        // says how much device memory it holds, and the GPU's pool has to
        // have room for that on top of the GPU floor.
        let peak_gpu = state.history.learned_gpu(&label).unwrap_or(0);
        let waiter = Waiter {
            id,
            label: label.clone(),
            peak_bytes,
            peak_gpu,
            priority,
            tier,
            seq: 0,
        };
        state.queue.push(waiter);
        state.waiters.insert(id, reply.clone());
        state.targets.insert(id, target);
        state.client_pids.insert(id, client_pid);
        state.waiting_since.insert(id, Instant::now());
        let position = state.queue.position(id).unwrap_or(0);
        self.log_event(
            "lease.queued",
            json!({
                "lease": id,
                "label": label,
                "peak_bytes": peak_bytes,
                "priority": priority,
                "tier": tier.as_str(),
                "position": position,
            }),
        );
        if reply
            .send(Response::Queued {
                position,
                waiting: state.queue.len(),
                available_bytes: state.mem.mem_available,
            })
            .is_err()
        {
            // The client went away before we could tell it anything.
            state.queue.remove(id);
            state.waiters.remove(&id);
            state.targets.remove(&id);
            state.client_pids.remove(&id);
            state.waiting_since.remove(&id);
            state.gpu_blocked.remove(&id);
        }
    }

    /// The admission rule as it stands right now: the memory rule, plus the
    /// GPU's own pool when something can see it.
    fn admission_now(&self, state: &State) -> Admission {
        Admission {
            available: state.mem.mem_available,
            floor: self.config.floor,
            gpu_available: state.gpu.largest_free_block,
            gpu_floor: self.config.gpu_floor,
        }
    }

    /// The memory rule alone, for the questions that are only about memory:
    /// would the live lease fit without the presence queue, is there room
    /// for registered work. The GPU side of those questions is the GPU
    /// pre-emption's business, not the memory pre-emption's.
    fn memory_admission(&self, state: &State) -> Admission {
        Admission {
            gpu_available: None,
            gpu_floor: 0,
            ..self.admission_now(state)
        }
    }

    /// Admit whatever fits, in the queue's order.
    fn admit(&self, state: &mut State) {
        loop {
            let Some(waiter) = state.queue.peek().cloned() else {
                return;
            };
            let leases = self.charged_memory(state);
            let admission = self.admission_now(state);
            // A waiter that fits the memory rule but not the GPU's own pool
            // is waiting for a *different* thing, and the log should say so
            // once rather than every 250 ms.
            if admission.admits(&leases, waiter.peak_bytes)
                && !admission.gpu_admits(waiter.peak_gpu)
                && state.gpu_blocked.insert(waiter.id)
            {
                self.log_event(
                    "lease.waiting_for_gpu_memory",
                    json!({
                        "lease": waiter.id,
                        "label": waiter.label,
                        "gpu_free_bytes": state.gpu.largest_free_block,
                        "gpu_floor_bytes": self.config.gpu_floor,
                        "label_gpu_peak_bytes": waiter.peak_gpu,
                        "gpu_source": state.gpu_source,
                    }),
                );
            }
            if !admission.admits_lease(&leases, waiter.peak_bytes, waiter.peak_gpu) {
                return;
            }
            state.gpu_blocked.remove(&waiter.id);
            let waiter = state.queue.pop().expect("the queue had a waiter");
            let reply = state.waiters.remove(&waiter.id);
            state.waiting_since.remove(&waiter.id);
            let target = state
                .targets
                .remove(&waiter.id)
                .unwrap_or(TargetSpec::Group { pgid: 0 });
            let client_pid = state.client_pids.remove(&waiter.id).unwrap_or(0);
            let lock_path = self
                .config
                .state_dir
                .join("leases")
                .join(format!("{}.lock", waiter.id));

            let lease = Lease {
                id: waiter.id,
                label: waiter.label.clone(),
                peak_bytes: waiter.peak_bytes,
                priority: waiter.priority,
                tier: waiter.tier,
                target,
                lock_path: lock_path.clone(),
                state: LeaseState::Granted,
                granted_at: Instant::now(),
                client_pid,
                last_heartbeat: None,
                stale_signalled: false,
                current_rss: 0,
                peak_rss: 0,
                peak_gpu: 0,
                reported_peak: None,
                reported_exit: None,
                overrun_written: 0,
                terminated_at: None,
                killed: false,
            };

            self.log_event(
                "lease.granted",
                json!({
                    "lease": waiter.id,
                    "label": waiter.label,
                    "peak_bytes": waiter.peak_bytes,
                    "tier": waiter.tier.as_str(),
                    "mem_available_bytes": state.mem.mem_available,
                }),
            );
            let granted = reply.map(|reply| {
                reply.send(Response::Granted {
                    lease: waiter.id,
                    label: waiter.label.clone(),
                    peak_bytes: waiter.peak_bytes,
                    lock_path: lock_path.display().to_string(),
                    floor_bytes: self.config.floor,
                    available_bytes: state.mem.mem_available,
                })
            });
            if let Some(Ok(())) = granted {
                state.leases.push(lease);
            } else {
                // The client was gone; the lease never existed.
                let _ = std::fs::remove_file(&lock_path);
                state.client_pids.remove(&waiter.id);
            }
        }
    }

    /// The memory the box has already promised: the clients' leases **and**
    /// the presence jobs that are running.
    ///
    /// The presence queue is charged like any other lease. That is what makes
    /// the pre-emption work: a presence job that has promised 30 GiB and used
    /// 2 GiB so far still owes 28 GiB, and a live lease that does not fit is
    /// blocked by exactly that promise.
    fn charged_memory(&self, state: &State) -> Vec<LeaseMemory> {
        let mut memory: Vec<LeaseMemory> = state.leases.iter().map(|l| l.memory()).collect();
        memory.extend(state.presence.memory());
        memory
    }

    /// Register a job in the presence queue.
    fn register_presence(
        &self,
        state: &mut State,
        request: PresenceRequest,
        reply: Sender<Response>,
    ) {
        let PresenceRequest {
            label,
            tier,
            peak,
            resumable,
            enabled,
            command,
        } = request;
        if command.is_empty() {
            let _ = reply.send(Response::Rejected {
                reason: "a presence job needs a command to run".to_string(),
            });
            return;
        }
        let peak_bytes = match peak {
            PeakArg::Bytes(bytes) => bytes,
            PeakArg::Auto => match learned_peak(state, &label) {
                Ok(learned) => learned,
                Err(reason) => {
                    let _ = reply.send(Response::Rejected { reason });
                    return;
                }
            },
        };
        let id = state.presence.queue.next_id();
        let mut spec = PresenceSpec::new(id, &label, tier, peak_bytes, resumable, command);
        spec.enabled = enabled;
        let job = PresenceJob::new(spec);
        state.presence.queue.push(job);
        self.save_presence(state);
        self.log_event(
            "presence.added",
            json!({
                "id": id,
                "label": label,
                "tier": tier.as_str(),
                "peak_bytes": peak_bytes,
                "resumable": resumable,
                "enabled": enabled,
            }),
        );
        let _ = reply.send(Response::PresenceAdded { id, label, tier });
    }

    /// Take a job out of the presence queue.
    fn remove_presence(&self, state: &mut State, id: u64, reply: Sender<Response>) {
        // A job that is running is asked to stop first: the queue and the
        // running work must not disagree.
        if let Some(running) = state.presence.running_job(id) {
            let pgid = running.pgid;
            let signalled = terminate_group(pgid);
            self.log_event(
                "presence.removed_running",
                json!({"id": id, "signalled": signalled}),
            );
        }
        match state.presence.queue.remove(id) {
            Some(job) => {
                self.save_presence(state);
                self.log_event(
                    "presence.removed",
                    json!({"id": id, "label": job.spec.label}),
                );
                let _ = reply.send(Response::Ok);
            }
            None => {
                let _ = reply.send(Response::Rejected {
                    reason: format!("there is no presence job {id}"),
                });
            }
        }
    }

    /// Write the presence queue out.
    fn save_presence(&self, state: &State) {
        if let Err(error) = state.presence.store.save(&state.presence.queue) {
            self.log_event("presence.save_failed", json!({"error": error.to_string()}));
        }
    }

    /// The presence queue's tick: pick up a queue that changed on disk, give
    /// the memory back when live work needs it, and start what fits.
    fn presence_tick(&self, state: &mut State) {
        if !self.config.presence {
            return;
        }
        // Registered work is something to do: the daemon must not idle out
        // while the presence queue is waiting for room.
        if state.presence.queue.outstanding() > 0 || !state.presence.running.is_empty() {
            state.last_activity = Instant::now();
        }
        // So is a waiter: a client queued for room is the daemon's whole
        // reason to be there, and idling out under it would strand the
        // client on a socket whose daemon has gone (measured 2026-11-01:
        // a waiter the GPU's floor was holding, and a daemon that left
        // after 600 s of "nothing happening" while the client waited).
        if !state.queue.is_empty() {
            state.last_activity = Instant::now();
        }
        self.reload_presence(state);
        self.preempt_for_live(state);
        self.preempt_gpu(state);
        self.start_presence(state);
    }

    /// Re-read the presence queue when the file has changed.
    ///
    /// The queue is a file so that it can be edited by hand and so that it
    /// survives the daemon. A job that is running is kept: the file says what
    /// is registered, not what happens to be running.
    fn reload_presence(&self, state: &mut State) {
        let path = state.presence.store.path();
        let stamp = std::fs::metadata(path)
            .ok()
            .map(|meta| (meta.len(), meta.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0)));
        if stamp == state.presence.stamp {
            return;
        }
        state.presence.stamp = stamp;
        let mut queue = state.presence.store.load();
        // Keep the runtime state of the jobs that are running: the file says
        // what is registered, not what is happening.
        for job in queue.jobs_mut().iter_mut() {
            if let Some(running) = state.presence.running_job(job.spec.id) {
                job.state = if running.stopped {
                    JobState::Stopped
                } else {
                    JobState::Running
                };
                job.attempts = job.attempts.max(1);
            }
        }
        state.presence.queue = queue;
        self.log_event(
            "presence.reloaded",
            json!({"jobs": state.presence.queue.jobs().len()}),
        );
    }

    /// Give the memory back when live work cannot be admitted.
    ///
    /// The rule: a **live** lease is waiting and it does not fit. If it
    /// *would* fit without the presence jobs, then the presence jobs are what
    /// is in the way, and the least urgent one is asked to stop. A stopped
    /// job gives its memory back when it exits; the lease is admitted on the
    /// tick after that.
    fn preempt_for_live(&self, state: &mut State) {
        let Some(waiter) = state.queue.peek().cloned() else {
            return;
        };
        if !waiter.tier.is_live() {
            return;
        }
        if state.presence.running.is_empty() {
            return;
        }
        let admission = self.memory_admission(state);
        let with_presence = self.charged_memory(state);
        if admission.admits(&with_presence, waiter.peak_bytes) {
            // It fits already. Nothing to pre-empt.
            return;
        }
        let clients_only: Vec<LeaseMemory> = state.leases.iter().map(|l| l.memory()).collect();
        if !admission.admits(&clients_only, waiter.peak_bytes) {
            // It would not fit even with an empty presence queue: the clients
            // themselves are using the room. That is the watchdog's business,
            // not this one's.
            return;
        }
        // The presence queue is in the way. Stop the least urgent job.
        let victim = state
            .presence
            .running
            .iter()
            .filter(|job| !job.terminating)
            .max_by_key(|job| job.tier(state).rank())
            .map(|job| job.id);
        let Some(victim) = victim else {
            return;
        };
        let (pgid, tier, label) = {
            let job = state.presence.running_job(victim).unwrap();
            (job.pgid, job.tier(state), job.label(state))
        };
        // The job may be frozen by the GPU pre-emption; terminate_group
        // continues it so the SIGTERM is actually delivered.
        let signalled = terminate_group(pgid);
        if let Some(job) = state.presence.running.iter_mut().find(|j| j.id == victim) {
            job.terminating = true;
        }
        if let Some(registered) = state.presence.queue.get_mut(victim) {
            registered.preemptions += 1;
        }
        state.ledger.note_preemption(tier);
        self.log_event(
            "presence.preempted",
            json!({
                "id": victim,
                "label": label,
                "tier": tier.as_str(),
                "reason": "live work needs the memory",
                "live_label": waiter.label,
                "live_peak_bytes": waiter.peak_bytes,
                "mem_available_bytes": state.mem.mem_available,
                "signalled": signalled,
            }),
        );
    }

    /// Let live work have the GPU: stop the presence jobs while a live lease
    /// is running and the GPU is busy.
    ///
    /// A stopped job keeps its memory — it gives up the GPU's streams, not
    /// the memory. That is the difference between the two pre-emptions: the
    /// GPU one is `SIGSTOP` (the work resumes where it left off), the memory
    /// one is `SIGTERM` (the work is stopped and restarted later).
    fn preempt_gpu(&self, state: &mut State) {
        if !self.config.gpu_preempt || state.presence.running.is_empty() {
            return;
        }
        let live_running = state
            .leases
            .iter()
            .any(|lease| lease.tier.is_live() && lease.state == LeaseState::Active);
        let busy = state.gpu.busy_pct.unwrap_or(0);
        if live_running && busy >= self.config.gpu_busy_threshold {
            let to_stop: Vec<(u64, i32, Tier)> = state
                .presence
                .running
                .iter()
                .filter(|job| !job.stopped && !job.terminating)
                .map(|job| (job.id, job.pgid, job.tier(state)))
                .collect();
            for (id, pgid, tier) in to_stop {
                let signalled = signal_group(pgid, libc::SIGSTOP);
                if let Some(job) = state.presence.running.iter_mut().find(|j| j.id == id) {
                    job.stopped = true;
                }
                state.ledger.note_preemption(tier);
                self.log_event(
                    "presence.gpu_stopped",
                    json!({
                        "id": id,
                        "tier": tier.as_str(),
                        "gpu_busy_pct": busy,
                        "threshold_pct": self.config.gpu_busy_threshold,
                        "signalled": signalled,
                    }),
                );
            }
        } else if !live_running {
            let to_resume: Vec<(u64, i32, Tier)> = state
                .presence
                .running
                .iter()
                .filter(|job| job.stopped)
                .map(|job| (job.id, job.pgid, job.tier(state)))
                .collect();
            for (id, pgid, tier) in to_resume {
                let signalled = signal_group(pgid, libc::SIGCONT);
                if let Some(job) = state.presence.running.iter_mut().find(|j| j.id == id) {
                    job.stopped = false;
                }
                self.log_event(
                    "presence.gpu_resumed",
                    json!({"id": id, "tier": tier.as_str(), "signalled": signalled}),
                );
            }
        }
    }

    /// Start the presence work that fits.
    ///
    /// A presence job starts only when **no live request is waiting**: the
    /// live queue has head-of-line blocking, and the presence work must not
    /// make a live request's wait longer.
    fn start_presence(&self, state: &mut State) {
        if !state.queue.is_empty() {
            // Live work is waiting. The presence queue waits behind it.
            return;
        }
        let admission = self.admission_now(state);
        loop {
            let Some(job) = state.presence.queue.next_runnable().cloned() else {
                return;
            };
            let running_ids: Vec<u64> = state.presence.running.iter().map(|j| j.id).collect();
            if running_ids.contains(&job.spec.id) {
                return;
            }
            let charged = self.charged_memory(state);
            // Registered work has to clear both rules too: the box's memory,
            // and the GPU's own pool against whatever device memory this
            // label has historically held.
            let job_gpu = state.history.learned_gpu(&job.spec.label).unwrap_or(0);
            if !admission.admits_lease(&charged, job.spec.peak_bytes, job_gpu) {
                return;
            }
            let lock_path = self
                .config
                .state_dir
                .join("leases")
                .join(format!("presence-{}.lock", job.spec.id));
            let lock = match LeaseLock::acquire(&lock_path) {
                Ok(lock) => lock,
                Err(error) => {
                    self.log_event(
                        "presence.lock_failed",
                        json!({"id": job.spec.id, "error": error.to_string()}),
                    );
                    return;
                }
            };
            let (pid, pgid) = match presence::spawn(&job.spec.command) {
                Ok(pair) => pair,
                Err(error) => {
                    self.log_event(
                        "presence.spawn_failed",
                        json!({"id": job.spec.id, "error": error.to_string()}),
                    );
                    // The job is marked failed, not left pending: a command
                    // that cannot start would otherwise be retried every
                    // tick, and a queue full of unstartable work is a queue
                    // that hides the work that can run.
                    if let Some(registered) = state.presence.queue.get_mut(job.spec.id) {
                        registered.state = JobState::Failed;
                        registered.last_exit = None;
                    }
                    self.save_presence(state);
                    return;
                }
            };
            state.presence.running.push(RunningJob {
                id: job.spec.id,
                pgid,
                started_at: Instant::now(),
                current_rss: 0,
                peak_rss: 0,
                lock,
                stopped: false,
                terminating: false,
            });
            if let Some(registered) = state.presence.queue.get_mut(job.spec.id) {
                registered.state = JobState::Running;
                registered.attempts += 1;
            }
            state.ledger.note_run(job.spec.tier);
            self.log_event(
                "presence.started",
                json!({
                    "id": job.spec.id,
                    "label": job.spec.label,
                    "tier": job.spec.tier.as_str(),
                    "peak_bytes": job.spec.peak_bytes,
                    "pid": pid,
                    "pgid": pgid,
                    "mem_available_bytes": state.mem.mem_available,
                }),
            );
        }
    }

    /// Reap the presence jobs that have finished.
    fn reap_presence(&self, state: &mut State) {
        if state.presence.running.is_empty() {
            return;
        }
        let mut finished = Vec::new();
        for job in state.presence.running.iter() {
            let mut status: libc::c_int = 0;
            let waited = unsafe { libc::waitpid(job.pgid as libc::pid_t, &mut status, libc::WNOHANG) };
            if waited == job.pgid as libc::pid_t {
                finished.push((job.id, status, job.terminating));
            }
        }
        for (id, status, terminating) in finished {
            let code = if libc::WIFEXITED(status) {
                Some(libc::WEXITSTATUS(status))
            } else if libc::WIFSIGNALED(status) {
                Some(128 + libc::WTERMSIG(status))
            } else {
                None
            };
            state.presence.running.retain(|job| job.id != id);
            let (tier, label, resumable) = match state.presence.queue.get(id) {
                Some(job) => (
                    job.spec.tier,
                    job.spec.label.clone(),
                    job.spec.resumable,
                ),
                None => (Tier::Study, String::new(), false),
            };
            let next_state = if terminating {
                // It was stopped to give live work the memory. A resumable
                // job goes back in the queue and runs again when there is
                // room.
                if resumable {
                    JobState::Preempted
                } else {
                    JobState::Failed
                }
            } else if code == Some(0) {
                JobState::Done
            } else {
                JobState::Failed
            };
            if let Some(registered) = state.presence.queue.get_mut(id) {
                registered.state = next_state;
                registered.last_exit = code;
            }
            self.log_event(
                "presence.finished",
                json!({
                    "id": id,
                    "label": label,
                    "tier": tier.as_str(),
                    "exit": code,
                    "state": next_state.as_str(),
                    "preempted": terminating,
                }),
            );
            self.save_presence(state);
        }
    }

    /// The ledger's tick: where the box's time went.
    fn ledger_tick(&self, state: &mut State) {
        let dt = self.config.sample_interval.as_secs_f64();
        let mut running_tiers: Vec<Tier> = Vec::new();
        let mut preempted_tiers: Vec<Tier> = Vec::new();
        let mut running_labels: Vec<String> = Vec::new();
        let mut preempted_labels: Vec<String> = Vec::new();
        for lease in state.leases.iter() {
            // A lease is booked from the moment the client **holds** it. A
            // lease that was granted but never held never ran anything, so
            // booking its grant as running time would invent work — the
            // ledger would say live ran for an hour in which a phantom
            // lease sat unclaimed (Hy4's fifth failure mode). The grant's
            // window is not lost: below, the box's idleness in it is booked
            // to `granted_not_run`, an attributed cause, so the committed
            // memory still explains the empty-looking box without being
            // called work.
            if lease.state == LeaseState::Active {
                if !running_tiers.contains(&lease.tier) {
                    running_tiers.push(lease.tier);
                }
                if !running_labels.contains(&lease.label) {
                    running_labels.push(lease.label.clone());
                }
            }
        }
        for job in state.presence.running.iter() {
            let tier = job.tier(state);
            let label = job.label(state);
            if job.stopped {
                if !preempted_tiers.contains(&tier) {
                    preempted_tiers.push(tier);
                }
                if !label.is_empty() && !preempted_labels.contains(&label) {
                    preempted_labels.push(label);
                }
            } else {
                if !running_tiers.contains(&tier) {
                    running_tiers.push(tier);
                }
                if !label.is_empty() && !running_labels.contains(&label) {
                    running_labels.push(label);
                }
            }
        }
        let idle = if running_tiers.is_empty() {
            Some(self.idle_reason(state))
        } else {
            None
        };
        let sample = Sample {
            running_tiers,
            preempted_tiers,
            running_labels,
            preempted_labels,
            idle,
            mem_available: state.mem.mem_available,
            gpu_power_mw: state.gpu.power_mw,
            gpu_busy_pct: state.gpu.busy_pct,
            gpu_power_source: state.gpu.power_source.clone(),
            flow_confidence: state.flow.and_then(|flow| flow.confidence),
            flow_rate: state.flow.and_then(|flow| flow.rate_of_change),
            flow_sign: state
                .flow
                .and_then(|flow| flow.sign())
                .map(|sign| sign.to_string()),
        };
        state.ledger.sample(dt, &sample);

        // The CPU's counters have their own, slower clock: they are read for
        // the ledger, not for the rule.
        if state.last_cpu_read.elapsed() >= self.config.ledger_interval {
            state.last_cpu_read = Instant::now();
            if let Some(counters) = crate::ledger::read_proc_stat() {
                state.ledger.note_cpu(&counters);
            }
        }
        state.ledger.roll();
    }

    /// Why the box is idle, right now.
    ///
    /// The answer is a cause, so the ledger can say what the idle time was
    /// spent waiting for. The last case — registered work that fits, is not
    /// running and is not stopped — is the one the ledger cannot explain, and
    /// it is the number that should be zero.
    fn idle_reason(&self, state: &State) -> IdleReason {
        if state
            .leases
            .iter()
            .any(|lease| lease.state == LeaseState::Granted)
        {
            // Memory is committed to a lease nobody has held. The box is
            // not doing nothing; it is waiting on a grant that may never be
            // claimed, and that is its own cause.
            return IdleReason::GrantedNotRun;
        }
        if !state.queue.is_empty() {
            // Live work is waiting for room.
            return IdleReason::WaitingForMemory;
        }
        let registered: Vec<&PresenceJob> = state
            .presence
            .queue
            .jobs()
            .iter()
            .filter(|job| job.spec.enabled && !matches!(job.state, JobState::Done | JobState::Failed))
            .collect();
        if registered.is_empty() {
            return IdleReason::NoWorkRegistered;
        }
        let admission = self.memory_admission(state);
        let charged = self.charged_memory(state);
        let fits = registered
            .iter()
            .find(|job| admission.admits(&charged, job.spec.peak_bytes));
        if fits.is_none() {
            // Registered work, and there is no room for it.
            return IdleReason::WaitingForMemory;
        }
        if state.presence.running.iter().any(|job| job.stopped) {
            // The work is paused so live work can have the GPU.
            return IdleReason::WaitingForGpu;
        }
        if registered
            .iter()
            .any(|job| job.state == JobState::Preempted)
        {
            // The work was stopped for live work and is waiting to run again.
            return IdleReason::PreemptedForLiveWork;
        }
        IdleReason::Unattributed
    }

    /// Release the leases whose clients are gone, and the leases whose
    /// clients went silent.
    fn check_liveness(&self, state: &mut State) {
        let mut dead = Vec::new();
        let mut stale = Vec::new();
        for lease in state.leases.iter() {
            match lease.state {
                LeaseState::Granted => {
                    if lease.granted_at.elapsed() > self.config.grant_grace {
                        dead.push((lease.id, "the client never took the lock"));
                    }
                }
                LeaseState::Active => {
                    let silent_for = lease
                        .last_heartbeat
                        .map(|at| at.elapsed())
                        .unwrap_or(Duration::ZERO);
                    if silent_for > self.config.heartbeat_grace {
                        // Alive by the lock, dead by the heartbeat. The lock
                        // is the truth about *death*; the heartbeat is the
                        // truth about *life*. A client that holds the lock
                        // and has said nothing for a grace period is stuck,
                        // and a stuck client's reservation is charged
                        // forever unless the daemon acts (Hy4's fourth
                        // failure mode).
                        stale.push(lease.id);
                        continue;
                    }
                    match lease::is_held(&lease.lock_path) {
                        Ok(true) => {}
                        Ok(false) => dead.push((lease.id, "the client is gone")),
                        Err(error) => {
                            self.log_event(
                                "lease.probe_failed",
                                json!({"lease": lease.id, "error": error.to_string()}),
                            );
                        }
                    }
                }
            }
        }
        for (id, reason) in dead {
            self.log_event("lease.client_gone", json!({"lease": id, "reason": reason}));
            if self.config.stop_on_client_gone {
                // Nobody is watching the work the client was running.
                if let Some(lease) = state.leases.iter().find(|l| l.id == id) {
                    let target = lease.target;
                    let signalled = signal_target(target, libc::SIGTERM);
                    let _ = signal_target(target, libc::SIGCONT);
                    self.log_event(
                        "lease.orphan_stopped",
                        json!({"lease": id, "signalled": signalled}),
                    );
                }
            }
            self.release_lease(state, id, "client-gone");
        }
        for id in stale {
            self.evict_silent_client(state, id);
        }
    }

    /// A lease whose client has been silent past the grace period.
    ///
    /// The client's own pid — the socket's credentials, not a claim — says
    /// which of the two failures this is:
    ///
    /// * **the client is gone** (its pid with nobody behind it): whatever
    ///   holds the lock is an inherited descriptor, not a client. The lease
    ///   is taken back at once, and the lock file goes with it, so the
    ///   descriptor's lock has nothing left to guard.
    /// * **the client is there but stuck**: it is asked to leave (SIGTERM —
    ///   the same treatment a dead client's work gets), which drops the
    ///   lock and releases the lease the honest way. If it is still stuck a
    ///   grace period later, the lease is taken back anyway: an unwatched
    ///   reservation is exactly what this daemon exists to prevent.
    fn evict_silent_client(&self, state: &mut State, id: u64) {
        let Some(index) = state.leases.iter().position(|l| l.id == id) else {
            return;
        };
        let lease = &mut state.leases[index];
        let client_alive = lease.client_pid > 0
            && Path::new(&format!("/proc/{}", lease.client_pid)).exists();
        let silent_for = lease
            .last_heartbeat
            .map(|at| at.elapsed())
            .unwrap_or(Duration::ZERO);
        if !lease.stale_signalled {
            lease.stale_signalled = true;
            self.log_event(
                "lease.stale_client",
                json!({
                    "lease": lease.id,
                    "label": lease.label,
                    "client_pid": lease.client_pid,
                    "client_alive": client_alive,
                    "silent_s": silent_for.as_secs(),
                }),
            );
            if client_alive {
                // Ask the stuck client to leave; its death drops the lock
                // and the lease releases the honest way.
                let signalled =
                    unsafe { libc::kill(lease.client_pid, libc::SIGTERM) == 0 };
                self.log_event(
                    "lease.stale_client_signalled",
                    json!({"lease": lease.id, "client_pid": lease.client_pid, "signalled": signalled}),
                );
                return;
            }
        } else if client_alive && silent_for < self.config.heartbeat_grace * 2 {
            // It was signalled and the grace has not doubled yet: give the
            // SIGTERM time to work.
            return;
        }
        // Either the client was already gone, or it ignored the SIGTERM for
        // another full grace period. Take the lease back.
        let (target, label) = (lease.target, lease.label.clone());
        let signalled = signal_target(target, libc::SIGTERM);
        self.log_event(
            "lease.force_released",
            json!({
                "lease": id,
                "label": label,
                "reason": if client_alive {
                    "the client kept the lock past its grace period after being asked to leave"
                } else {
                    "the lock is held but nobody is left to release it"
                },
                "client_pid": state.leases[index].client_pid,
                "silent_s": silent_for.as_secs(),
                "signalled": signalled,
            }),
        );
        self.release_lease(state, id, "silent-client");
    }

    /// The watchdog: when the box runs short, take the memory back.
    ///
    /// The box has **no swap**, so a `SIGSTOP`ed process keeps every page it
    /// took — `MemAvailable` does not move an inch while the victim sits
    /// stopped, and the emergency gets worse while the daemon waits (this is
    /// the first of Hy4's failure modes). Memory comes back only when the
    /// process is *gone*. So the watchdog never stops a lease for memory: it
    /// terminates the largest one outright (`SIGTERM`), and escalates to
    /// `SIGKILL` when the grace period passes and the process is somehow
    /// still there. The reservation stays charged until the lease is
    /// released, which happens after the client has reaped its child — the
    /// memory is only "back" when the process is.
    fn watchdog(&self, state: &mut State) {
        if state.mem.mem_available >= self.config.emergency_floor {
            return;
        }
        // The largest lease, by what it is using right now.
        let victim = state
            .leases
            .iter()
            .filter(|lease| lease.current_rss >= self.config.min_victim_rss)
            .max_by_key(|lease| lease.current_rss)
            .map(|lease| lease.id);

        let Some(victim_id) = victim else {
            // The pressure is not coming from a lease. The box's own services
            // are not leases, so they are never touched.
            self.log_event(
                "watchdog.pressure_outside_leases",
                json!({
                    "mem_available_bytes": state.mem.mem_available,
                    "emergency_floor_bytes": self.config.emergency_floor,
                }),
            );
            return;
        };

        let (target, label, current_rss, reserved, terminated_at, killed) = {
            let lease = state.leases.iter().find(|l| l.id == victim_id).unwrap();
            (
                lease.target,
                lease.label.clone(),
                lease.current_rss,
                lease.peak_bytes,
                lease.terminated_at,
                lease.killed,
            )
        };

        // It has not been asked to leave yet: ask it now.
        if terminated_at.is_none() {
            let signalled = signal_target(target, libc::SIGTERM);
            self.log_event(
                "watchdog.terminated",
                json!({
                    "lease": victim_id,
                    "label": label,
                    "rss_bytes": current_rss,
                    "reserved_bytes": reserved,
                    "mem_available_bytes": state.mem.mem_available,
                    "signalled": signalled,
                }),
            );
            if let Some(lease) = state.leases.iter_mut().find(|l| l.id == victim_id) {
                lease.terminated_at = Some(Instant::now());
            }
            return;
        }

        // It was asked, and the box is still short. Give it the grace
        // period, then take the memory back the only way left.
        let grace = Duration::from_millis(
            self.config.sample_interval.as_millis() as u64 * self.config.stop_grace_samples as u64,
        );
        let waited = terminated_at.map(|at| at.elapsed()).unwrap_or_default();
        if killed || waited < grace {
            return;
        }
        let signalled = signal_target(target, libc::SIGKILL);
        self.log_event(
            "watchdog.killed",
            json!({
                "lease": victim_id,
                "label": label,
                "rss_bytes": current_rss,
                "reserved_bytes": reserved,
                "mem_available_bytes": state.mem.mem_available,
                "waited_ms": waited.as_millis() as u64,
                "signal": "SIGKILL",
                "signalled": signalled,
            }),
        );
        if let Some(lease) = state.leases.iter_mut().find(|l| l.id == victim_id) {
            lease.killed = true;
        }
    }

    /// Give the memory back and write the peak down.
    ///
    /// Not every finished lease teaches the history: a run teaches only if
    /// it finished cleanly (`exit 0`) and lasted more than a few seconds
    /// (`history::MIN_LEARNED_DURATION_S`). A no-op run — a wrapper invoked
    /// with nothing to do — exits 0 in milliseconds with a few megabytes,
    /// and 25 of those taught `infinigen.mountain.coarse` to reserve 3.6 MB
    /// on 2026-11-01 while it was using 1.3 GiB. The peak is still measured
    /// and still logged (`lease.released`); it is only the *history* that
    /// refuses it, and the log says why in `history.not_learned`.
    fn release_lease(&self, state: &mut State, id: u64, reason: &str) {
        let Some(index) = state.leases.iter().position(|l| l.id == id) else {
            return;
        };
        let lease = state.leases.remove(index);
        if lease.state == LeaseState::Granted {
            // Granted, never held, now gone: the command never ran. The
            // ledger has been booking this window as granted_not_run; the
            // event names it once, plainly, for anyone reading the log.
            self.log_event(
                "lease.granted_not_run",
                json!({
                    "lease": lease.id,
                    "label": lease.label,
                    "reason": reason,
                    "granted_s": lease.granted_at.elapsed().as_secs_f64(),
                }),
            );
        }
        let (peak, peak_source) = lease.measured_peak();
        let duration_s = lease.granted_at.elapsed().as_secs_f64();
        let record = {
            let mut record = PeakRecord::new(&lease.label, &lease.label, peak);
            record.peak_gpu_bytes = if lease.peak_gpu > 0 {
                Some(lease.peak_gpu)
            } else {
                None
            };
            record.gpu_visible =
                state.gpu_source != "off" && !state.gpu_source.contains("unavailable");
            record.duration_s = duration_s;
            record.mem_total_bytes = state.mem.mem_total;
            record.floor_bytes = self.config.floor;
            record.peak_source = peak_source.to_string();
            record.exit_code = lease.reported_exit;
            record
        };
        if record.teaches() {
            if let Err(error) = state.history.append(record) {
                self.log_event("history.write_failed", json!({"error": error.to_string()}));
            }
        } else {
            let why = if lease.reported_exit.map_or(true, |code| code != 0) {
                match lease.reported_exit {
                    Some(code) => format!("the run finished with exit {code}"),
                    None => "the daemon cannot say how the run finished".to_string(),
                }
            } else {
                format!(
                    "the run lasted {duration_s:.2}s, under the {}s a run must last to teach",
                    crate::history::MIN_LEARNED_DURATION_S
                )
            };
            self.log_event(
                "history.not_learned",
                json!({
                    "lease": lease.id,
                    "label": lease.label,
                    "reason": why,
                    "peak_rss_bytes": peak,
                    "duration_s": duration_s,
                    "exit": lease.reported_exit,
                }),
            );
        }
        let _ = std::fs::remove_file(&lease.lock_path);
        self.log_event(
            "lease.released",
            json!({
                "lease": lease.id,
                "label": lease.label,
                "reason": reason,
                "peak_rss_bytes": peak,
                "peak_source": peak_source,
                "duration_s": duration_s,
                "exit": lease.reported_exit,
            }),
        );
    }

    /// Start the children that keep printing the GPU's views.
    ///
    /// There are two of them, because the box has two things to say:
    ///
    /// * `nvidia-smi` — the driver's per-process accounting (the per-lease
    ///   GPU peak) and the GPU's own busy share and power.
    /// * `tegrastats` — the Tegra's own memory figure and the GPU's rail
    ///   (`VDD_GPU`), which is the power figure the ledger uses.
    ///
    /// Each is one long-lived child that keeps printing: a fresh `nvidia-smi`
    /// every couple of seconds cost the daemon a fork and an exec each time.
    fn start_gpu_watch(&self) {
        if self.config.gpu_probe == GpuProbe::Off {
            return;
        }
        let mut watches = Vec::new();
        match self.config.gpu_probe {
            GpuProbe::Nvidia => {
                if let Some(watch) = self.spawn_nvidia_watch() {
                    watches.push(watch);
                }
                if let Some(watch) = self.spawn_nvidia_gpu_watch() {
                    watches.push(watch);
                }
            }
            GpuProbe::Tegrastats => {
                if let Some(watch) = self.spawn_tegrastats_watch() {
                    watches.push(watch);
                }
            }
            GpuProbe::Auto => {
                // Both, when both are there: the driver's per-process view
                // and the Tegra's rail answer different questions.
                if let Some(watch) = self.spawn_nvidia_watch() {
                    watches.push(watch);
                }
                if let Some(watch) = self.spawn_nvidia_gpu_watch() {
                    watches.push(watch);
                }
                if let Some(watch) = self.spawn_tegrastats_watch() {
                    watches.push(watch);
                }
            }
            GpuProbe::Off => {}
        }
        if watches.is_empty() {
            self.log_event(
                "daemon.gpu_unavailable",
                json!({"probe": self.config.gpu_probe.as_str()}),
            );
            return;
        }
        let sources: Vec<String> = watches.iter().map(|watch| watch.source.clone()).collect();
        self.log_event("daemon.gpu_watch", json!({"sources": sources}));
        *self.gpu_watch.lock().unwrap() = watches;
    }

    /// `nvidia-smi -l`: one child, printing the driver's per-process view.
    fn spawn_nvidia_watch(&self) -> Option<GpuWatch> {
        let mut command = std::process::Command::new("nvidia-smi");
        command
            .args([
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
                "-l",
                "2",
            ])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null());
        let mut child = command.spawn().ok()?;
        let stdout = child.stdout.take()?;
        let sample = Arc::new(Mutex::new(GpuSample::default()));
        let writer = Arc::clone(&sample);
        std::thread::Builder::new()
            .name("thor-admit-gpu".to_string())
            .spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    let per_process = crate::gpu::parse_compute_apps(&line);
                    if !per_process.is_empty() {
                        let mut guard = writer.lock().unwrap();
                        guard.per_process = per_process;
                    }
                }
            })
            .ok()?;
        Some(GpuWatch {
            sample,
            source: "nvidia-smi".to_string(),
            _child: Arc::new(Mutex::new(child)),
        })
    }

    /// `nvidia-smi -l`: one child, printing the GPU's busy share and power.
    fn spawn_nvidia_gpu_watch(&self) -> Option<GpuWatch> {
        let mut command = std::process::Command::new("nvidia-smi");
        command
            .args([
                "--query-gpu=utilization.gpu,power.draw",
                "--format=csv,noheader,nounits",
                "-l",
                "1",
            ])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null());
        let mut child = command.spawn().ok()?;
        let stdout = child.stdout.take()?;
        let sample = Arc::new(Mutex::new(GpuSample::default()));
        let writer = Arc::clone(&sample);
        std::thread::Builder::new()
            .name("thor-admit-gpu".to_string())
            .spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    if let Some(parsed) = crate::gpu::parse_nvidia_gpu_line(&line) {
                        let mut guard = writer.lock().unwrap();
                        guard.busy_pct = parsed.busy_pct;
                        guard.power_mw = parsed.power_mw;
                        guard.power_source = parsed.power_source;
                    }
                }
            })
            .ok()?;
        Some(GpuWatch {
            sample,
            source: "nvidia-smi:gpu".to_string(),
            _child: Arc::new(Mutex::new(child)),
        })
    }

    /// `tegrastats`: one child, printing the Tegra's own memory view.
    fn spawn_tegrastats_watch(&self) -> Option<GpuWatch> {
        let mut command = match &self.config.tegrastats_command {
            Some(path) => {
                let mut command = std::process::Command::new(path);
                // The real tegrastats takes an interval; a test double takes
                // nothing, but accepting the arguments keeps the seam honest.
                command.args(["--interval", "1000"]);
                command
            }
            None => {
                let mut command = std::process::Command::new("tegrastats");
                command.args(["--interval", "1000"]);
                command
            }
        };
        command
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null());
        let mut child = command.spawn().ok()?;
        let stdout = child.stdout.take()?;
        let sample = Arc::new(Mutex::new(GpuSample::default()));
        let writer = Arc::clone(&sample);
        std::thread::Builder::new()
            .name("thor-admit-gpu".to_string())
            .spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    if let Some(parsed) = crate::gpu::parse_tegrastats_line(&line) {
                        let mut guard = writer.lock().unwrap();
                        guard.box_used_bytes = parsed.box_used_bytes;
                        guard.box_total_bytes = parsed.box_total_bytes;
                        guard.largest_free_block = parsed.largest_free_block;
                        // The Tegra's rail is the power figure the ledger
                        // uses; it is the box's own number.
                        guard.power_mw = parsed.power_mw;
                        guard.power_source = parsed.power_source;
                    }
                }
            })
            .ok()?;
        Some(GpuWatch {
            sample,
            source: "tegrastats".to_string(),
            _child: Arc::new(Mutex::new(child)),
        })
    }

    /// Write one line to the daemon's log.
    fn log_event(&self, event: &str, payload: serde_json::Value) {
        let mut line = json!({
            "at": clock::rfc3339_now(),
            "event": event,
            "pid": std::process::id(),
        });
        if let (Some(map), Some(extra)) = (line.as_object_mut(), payload.as_object()) {
            for (key, value) in extra {
                map.insert(key.clone(), value.clone());
            }
        }
        let mut text = serde_json::to_string(&line).unwrap_or_default();
        text.push('\n');
        if let Some(log) = self.log.lock().unwrap().as_mut() {
            let _ = log.write_all(text.as_bytes());
            let _ = log.flush();
        }
        eprint!("{text}");
    }
}

fn target_of(spec: TargetSpec) -> Target {
    match spec {
        TargetSpec::Group { pgid } => Target::Group(pgid),
        TargetSpec::Process { pid } => Target::Process(pid),
    }
}

/// The pid of the process on the other end of a socket connection, as the
/// kernel sees it.
///
/// This is the one fact about a client the daemon can act on without the
/// client's cooperation: credentials are put on the connection by the
/// kernel, so a client cannot misname itself, and a pid that no longer
/// exists says the client is gone even while some inherited descriptor
/// keeps its lock alive.
fn peer_pid(stream: &UnixStream) -> i32 {
    use std::os::unix::io::AsRawFd;
    let mut credentials: libc::ucred = unsafe { std::mem::zeroed() };
    let mut length = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let rc = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            &mut credentials as *mut libc::ucred as *mut libc::c_void,
            &mut length,
        )
    };
    if rc == 0 {
        credentials.pid as i32
    } else {
        0
    }
}

/// Merge the GPU's views into one sample, and say where they came from.
///
/// The power figure prefers `tegrastats`' own rail (`VDD_GPU`): it is the
/// Tegra's number for the GPU's rail, and the brief asks for the GPU's
/// power from `tegrastats`. The driver's watts are the fallback.
fn merge_gpu_samples(watches: &[GpuWatch]) -> (GpuSample, String) {
    let mut merged = GpuSample::default();
    let mut sources: Vec<String> = Vec::new();
    let mut driver_power: Option<(u64, String)> = None;
    for watch in watches {
        let sample = watch.sample.lock().unwrap().clone();
        merged.per_process.extend(sample.per_process.clone());
        if sample.box_used_bytes.is_some() {
            merged.box_used_bytes = sample.box_used_bytes;
            merged.box_total_bytes = sample.box_total_bytes;
            merged.largest_free_block = sample.largest_free_block;
        }
        if sample.busy_pct.is_some() {
            merged.busy_pct = sample.busy_pct;
        }
        match sample.power_source.as_deref() {
            Some("tegrastats") => {
                merged.power_mw = sample.power_mw;
                merged.power_source = sample.power_source.clone();
            }
            Some(_) => {
                if let Some(power) = sample.power_mw {
                    driver_power = Some((power, sample.power_source.clone().unwrap_or_default()));
                }
            }
            None => {}
        }
        sources.push(watch.source.clone());
    }
    if merged.power_mw.is_none() {
        if let Some((power, source)) = driver_power {
            merged.power_mw = Some(power);
            merged.power_source = Some(source);
        }
    }
    (merged, sources.join(","))
}

/// Signal a lease's target. A group is signalled with a negative pid.
pub fn signal_target(target: TargetSpec, signal: i32) -> bool {
    let me = std::process::id() as i32;
    let my_group = unsafe { libc::getpgrp() };
    match target {
        TargetSpec::Group { pgid } => {
            if pgid <= 1 || pgid == me || pgid == my_group {
                return false;
            }
            unsafe { libc::kill(-pgid, signal) == 0 }
        }
        TargetSpec::Process { pid } => {
            if pid <= 1 || pid == me {
                return false;
            }
            unsafe { libc::kill(pid, signal) == 0 }
        }
    }
}

/// Signal a process group by its number.
///
/// The daemon's own group is never signalled: the daemon is not a lease, and
/// the box's services are not leases either.
pub fn signal_group(pgid: i32, signal: i32) -> bool {
    let me = std::process::id() as i32;
    let my_group = unsafe { libc::getpgrp() };
    if pgid <= 1 || pgid == me || pgid == my_group {
        return false;
    }
    unsafe { libc::kill(-pgid, signal) == 0 }
}

/// Terminate a presence job's process group: `SIGTERM`, then `SIGCONT`.
///
/// The `SIGCONT` is not decoration. A job the GPU pre-emption stopped is
/// frozen, and a frozen process never sees its `SIGTERM` — the signal sits
/// pending while the job keeps every page it took, and the memory the
/// pre-emption was for never comes back (Hy4's first failure mode, in the
/// corner where the two pre-emptions meet).
pub fn terminate_group(pgid: i32) -> bool {
    let signalled = signal_group(pgid, libc::SIGTERM);
    let _ = signal_group(pgid, libc::SIGCONT);
    signalled
}

/// The presence queue, as the status shows it.
fn presence_reports(state: &State) -> Vec<PresenceReport> {
    state
        .presence
        .queue
        .jobs()
        .iter()
        .map(|job| {
            let running = state.presence.running_job(job.spec.id);
            PresenceReport {
                id: job.spec.id,
                label: job.spec.label.clone(),
                tier: job.spec.tier,
                peak_bytes: job.spec.peak_bytes,
                resumable: job.spec.resumable,
                enabled: job.spec.enabled,
                state: job.state.as_str().to_string(),
                command: job.spec.command.join(" "),
                pgid: running.map(|job| job.pgid).unwrap_or(0),
                age_s: running
                    .map(|job| job.started_at.elapsed().as_secs_f64())
                    .unwrap_or(0.0),
                current_rss_bytes: running.map(|job| job.current_rss).unwrap_or(0),
                attempts: job.attempts,
                preemptions: job.preemptions,
                last_exit: job.last_exit,
            }
        })
        .collect()
}

/// The status the CLI shows.
fn status_report(state: &State, config: &Config) -> StatusReport {
    let leases = state
        .leases
        .iter()
        .map(|lease| LeaseReport {
            lease: lease.id,
            label: lease.label.clone(),
            peak_bytes: lease.peak_bytes,
            current_rss_bytes: lease.current_rss,
            peak_rss_bytes: lease.peak_rss,
            peak_gpu_bytes: lease.peak_gpu,
            priority: lease.priority,
            tier: lease.tier,
            age_s: lease.granted_at.elapsed().as_secs_f64(),
            pid: lease.target.pid().unwrap_or_else(|| lease.target.pgid().unwrap_or(0)),
            pgid: lease.target.pgid().unwrap_or(0),
        })
        .collect();
    let queue = state
        .queue
        .iter()
        .enumerate()
        .map(|(index, waiter)| QueueReport {
            position: index + 1,
            label: waiter.label.clone(),
            peak_bytes: waiter.peak_bytes,
            priority: waiter.priority,
            waiting_s: state
                .waiting_since
                .get(&waiter.id)
                .map(|since| since.elapsed().as_secs_f64())
                .unwrap_or(0.0),
        })
        .collect();
    StatusReport {
        mem_total_bytes: state.mem.mem_total,
        mem_available_bytes: state.mem.mem_available,
        floor_bytes: config.floor,
        emergency_floor_bytes: config.emergency_floor,
        gpu_floor_bytes: config.gpu_floor,
        leases,
        queue,
        gpu_source: state.gpu_source.clone(),
        gpu_visible: state.gpu_source != "off" && !state.gpu_source.contains("unavailable"),
        gpu_box_used_bytes: state.gpu.box_used_bytes,
        gpu_largest_free_block_bytes: state.gpu.largest_free_block,
        uptime_s: state.started.elapsed().as_secs_f64(),
        samples: state.samples,
        presence: presence_reports(state),
    }
}

/// The path of the lock file that goes with a socket.
///
/// The daemon's front door is its socket, and two daemons on one socket
/// would be two admission controllers with two views of the box. The socket
/// alone cannot say who owns it: a daemon that dies leaves the socket file
/// behind, and a daemon whose acceptor has died leaves a socket that
/// answers nobody while the daemon is still running. The lock file can say
/// it, because the kernel drops the lock when the daemon dies.
pub fn socket_lock_path(socket: &Path) -> PathBuf {
    let mut path = socket.as_os_str().to_os_string();
    path.push(".lock");
    PathBuf::from(path)
}

/// Bind the socket a daemon will answer on, refusing one that is spoken for.
///
/// This runs *before* the socket's lock is taken (round 10, item b), so the
/// checks it makes are the socket's own word:
///
/// * a socket somebody answers on belongs to a running daemon — not ours;
/// * a socket that answers nobody, with the lock held, belongs to a daemon
///   that is alive but not accepting (its acceptor has died) — also not
///   ours. The lock is the truth in that case: the kernel drops it when
///   the daemon dies, and it is held for as long as the daemon lives;
/// * anything else is a stale file, and it goes.
///
/// `bind` on an existing path fails on its own, so two daemons racing for
/// one socket still end with exactly one of them bound.
fn bind_listener(socket: &Path) -> std::io::Result<UnixListener> {
    if let Some(parent) = socket.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if socket.exists() {
        if UnixStream::connect(socket).is_ok() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AddrInUse,
                "another thor-admit daemon is already running",
            ));
        }
        if socket_lock_is_held(socket)? {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AddrInUse,
                "another thor-admit daemon is already running: it holds the lock on \
                 this socket, so it is alive even though the socket answers nobody",
            ));
        }
        let _ = std::fs::remove_file(socket);
    }
    let listener = UnixListener::bind(socket)?;
    listener.set_nonblocking(true)?;
    // The socket is the daemon's front door: only its owner may open it.
    let _ = std::fs::set_permissions(
        socket,
        std::os::unix::fs::PermissionsExt::from_mode(0o600),
    );
    Ok(listener)
}

/// A test seam: wedge on the way up, before anything is held or bound.
///
/// This reproduces the 04:15 daemon of 2026-11-01 (round 10, item b): one
/// auto-started by a client, hung in `futex_wait_queue` before it ever
/// bound its socket, holding the socket's lock and so refusing every later
/// daemon until a human killed it. `THOR_ADMIT_TEST_CONSTRUCTION_HANG_MS`
/// is set only by the integration tests; production never sets it, and the
/// hang sits *before* the bind and the lock, which is exactly where the
/// old order left the box wedged.
fn hang_on_the_way_up_for_test() {
    if let Ok(text) = std::env::var("THOR_ADMIT_TEST_CONSTRUCTION_HANG_MS") {
        if let Ok(millis) = text.parse::<u64>() {
            std::thread::sleep(Duration::from_millis(millis));
        }
    }
}

/// Take the exclusive lock on a socket's lock file.
///
/// The descriptor is the lock: as long as it is open, the lock is held, and
/// the kernel releases it whatever kills the daemon.
fn take_socket_lock(socket: &Path) -> std::io::Result<std::fs::File> {
    use std::os::unix::io::AsRawFd;
    let path = socket_lock_path(socket);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&path)?;
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc != 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AddrInUse,
            format!(
                "another thor-admit daemon is already running: it holds the lock on {}",
                path.display()
            ),
        ));
    }
    Ok(file)
}

/// Is somebody holding the lock on this socket's lock file?
fn socket_lock_is_held(socket: &Path) -> std::io::Result<bool> {
    use std::os::unix::io::AsRawFd;
    let path = socket_lock_path(socket);
    let file = match std::fs::OpenOptions::new().read(true).write(true).open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc == 0 {
        unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_UN) };
        return Ok(false);
    }
    Ok(true)
}

/// Write one JSON line to a socket.
fn write_line(stream: &mut UnixStream, response: &Response) -> std::io::Result<()> {
    let mut text = serde_json::to_string(response).unwrap_or_default();
    text.push('\n');
    stream.write_all(text.as_bytes())?;
    stream.flush()
}

/// Should the accept loop give up on this error?
///
/// The listener is non-blocking, so "would block" is the normal "nothing is
/// waiting yet" and a signal is a signal: neither is a reason to stop. Any
/// other error means the front door is broken, and a daemon that cannot
/// answer is worse than a daemon that is not there: it keeps sampling the
/// box, keeps its log moving, and looks alive to everything that checks. So
/// the daemon stops instead.
pub fn accept_error_is_fatal(error: &std::io::Error) -> bool {
    !matches!(
        error.kind(),
        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_transient_accept_error_is_not_fatal() {
        assert!(!accept_error_is_fatal(&std::io::Error::from(
            std::io::ErrorKind::WouldBlock
        )));
        assert!(!accept_error_is_fatal(&std::io::Error::from(
            std::io::ErrorKind::Interrupted
        )));
    }

    #[test]
    fn any_other_accept_error_is_fatal() {
        // The acceptor dying quietly is how a daemon ends up alive, still
        // sampling the box, and answering nobody. The box would then have an
        // admission controller that looks fine and is not there.
        assert!(accept_error_is_fatal(&std::io::Error::from(
            std::io::ErrorKind::InvalidInput
        )));
        assert!(accept_error_is_fatal(&std::io::Error::from(
            std::io::ErrorKind::ConnectionAborted
        )));
    }
}
