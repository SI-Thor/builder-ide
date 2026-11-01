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
use crate::gpu::{GpuProbe, GpuSample};
use crate::history::{History, PeakRecord};
use crate::journal::Chain;
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
/// How long a granted lease may sit unlocked before the daemon gives up on it.
const GRANT_GRACE: Duration = Duration::from_secs(30);
/// The default busy share of the GPU at which live work takes the GPU from
/// the presence queue.
pub const DEFAULT_GPU_BUSY_THRESHOLD: u8 = 50;
/// The default interval for reading the CPU's counters.
pub const DEFAULT_LEDGER_INTERVAL: Duration = Duration::from_secs(1);

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
    /// How many samples the victim is given to come back before it is killed.
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
    current_rss: u64,
    peak_rss: u64,
    peak_gpu: u64,
    /// The peak the client measured itself (its `rusage`).
    reported_peak: Option<u64>,
    /// The watchdog has stopped this lease.
    stopped: bool,
    stopped_at: Option<Instant>,
    /// The watchdog has killed this lease.
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
}

/// What a client asked for when it registered a presence job.
struct PresenceRequest {
    label: String,
    tier: Tier,
    peak: PeakArg,
    resumable: bool,
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
    /// When each waiting request arrived.
    waiting_since: HashMap<u64, Instant>,
    /// Requests that arrived and are not handled yet.
    inbox: Vec<(Request, Sender<Response>)>,
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
    listener: Mutex<Option<UnixListener>>,
    /// The GPU's views, kept fresh by children that keep printing them.
    gpu_watch: Mutex<Vec<GpuWatch>>,
    /// The daemon's own log. It has its own lock so that a log line can be
    /// written while the state lock is held.
    log: Mutex<Option<std::fs::File>>,
    /// The log's hash chain, sealed under the same lock as the log so a
    /// line and its chain field are written as one act. Resumed from the
    /// log's tail at startup, so a restart continues the same chain.
    chain: Mutex<Chain>,
}

impl Daemon {
    /// Build a daemon.
    pub fn new(config: Config) -> std::io::Result<Arc<Daemon>> {
        std::fs::create_dir_all(&config.state_dir)?;
        std::fs::create_dir_all(config.state_dir.join("leases"))?;
        let history = History::load(&config.history);
        let log_path = config.state_dir.join("daemon.log");
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .ok();
        // Resume the chain from the log's tail: a restart keeps counting
        // and `verify` still passes over the whole file, restarts and all.
        let chain = Chain::resume(&log_path);
        let state = State {
            leases: Vec::new(),
            queue: Queue::new(),
            waiters: HashMap::new(),
            targets: HashMap::new(),
            waiting_since: HashMap::new(),
            inbox: Vec::new(),
            next_id: 1,
            mem: MemInfo::read().unwrap_or_default(),
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
        };
        Ok(Arc::new(Daemon {
            config,
            state: Mutex::new(state),
            wake: Condvar::new(),
            stop: Arc::new(AtomicBool::new(false)),
            listener: Mutex::new(None),
            log: Mutex::new(log),
            chain: Mutex::new(chain),
            gpu_watch: Mutex::new(Vec::new()),
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

    /// The path of the socket the daemon listens on.
    pub fn socket_path(&self) -> &Path {
        &self.config.socket
    }

    /// Run the daemon until it is stopped.
    pub fn run(self: &Arc<Self>) -> std::io::Result<()> {
        self.bind_socket()?;
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
                "sample_interval_ms": self.config.sample_interval.as_millis() as u64,
                "meminfo": self.config.meminfo.display().to_string(),
                "gpu_probe": self.config.gpu_probe.as_str(),
                "mem_total_bytes": mem_total,
                "history": self.config.history.display().to_string(),
            }),
        );

        // The acceptor runs in its own thread; the clock runs here.
        let daemon = Arc::clone(self);
        let acceptor = std::thread::Builder::new()
            .name("thor-admit-accept".to_string())
            .spawn(move || daemon.accept_loop())?;

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
            let signalled = signal_group(job.pgid, libc::SIGTERM);
            self.log_event(
                "presence.stopped_with_daemon",
                json!({"id": job.id, "signalled": signalled}),
            );
        }
    }

    fn bind_socket(&self) -> std::io::Result<()> {
        if let Some(parent) = self.config.socket.parent() {
            std::fs::create_dir_all(parent)?;
        }
        // If somebody is already listening, this is not our socket to take.
        if self.config.socket.exists() {
            if UnixStream::connect(&self.config.socket).is_ok() {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::AddrInUse,
                    "another thor-admit daemon is already running",
                ));
            }
            let _ = std::fs::remove_file(&self.config.socket);
        }
        let listener = UnixListener::bind(&self.config.socket)?;
        listener.set_nonblocking(true)?;
        // The socket is the daemon's front door: only its owner may open it.
        let _ = std::fs::set_permissions(
            &self.config.socket,
            std::os::unix::fs::PermissionsExt::from_mode(0o600),
        );
        *self.listener.lock().unwrap() = Some(listener);
        Ok(())
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
                Err(_) => return,
            }
        }
    }

    /// Serve one client connection.
    fn serve(self: Arc<Self>, stream: UnixStream) {
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
                state.inbox.push((request, reply_tx));
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
        for (request, reply) in inbox {
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
                    },
                    reply,
                ),
                Request::Held { lease } => {
                    if let Some(found) = state.leases.iter_mut().find(|l| l.id == lease) {
                        found.state = LeaseState::Active;
                    }
                    let _ = reply.send(Response::Ok);
                }
                Request::Release {
                    lease,
                    peak_rss_bytes,
                } => {
                    if let Some(found) = state.leases.iter_mut().find(|l| l.id == lease) {
                        if let Some(peak) = peak_rss_bytes {
                            found.reported_peak = Some(peak);
                        }
                    }
                    self.release_lease(&mut state, lease, "client");
                    let _ = reply.send(Response::Ok);
                }
                Request::PresenceAdd {
                    label,
                    tier,
                    peak,
                    resumable,
                    command,
                } => self.register_presence(
                    &mut state,
                    PresenceRequest {
                        label,
                        tier,
                        peak,
                        resumable,
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
            for lease in state.leases.iter_mut() {
                let usage = procscan::usage_for(target_of(lease.target), &procs);
                lease.current_rss = usage.rss_bytes;
                lease.peak_rss = lease.peak_rss.max(usage.rss_bytes);
                lease.peak_gpu = lease.peak_gpu.max(gpu.for_pids(&usage.pids));
            }
            for job in state.presence.running.iter_mut() {
                let usage = procscan::usage_for(Target::Group(job.pgid), &procs);
                job.current_rss = usage.rss_bytes;
                job.peak_rss = job.peak_rss.max(usage.rss_bytes);
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
                    "leases": state.leases.len(),
                    "waiting": state.queue.len(),
                    "presence_running": state.presence.running.len(),
                    "presence_registered": state.presence.queue.outstanding(),
                    "gpu_source": state.gpu_source,
                }),
            );
        }
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
        } = request;
        let peak_bytes = match peak {
            PeakArg::Bytes(bytes) => bytes,
            PeakArg::Auto => match state.history.p95(&label) {
                Some(p95) => p95,
                None => {
                    let _ = reply.send(Response::Rejected {
                        reason: format!(
                            "no history for the label {label:?}, so there is no learned peak; \
                             run it once with an explicit --peak"
                        ),
                    });
                    return;
                }
            },
        };

        let id = state.next_id;
        state.next_id += 1;
        let waiter = Waiter {
            id,
            label: label.clone(),
            peak_bytes,
            priority,
            tier,
            seq: 0,
        };
        state.queue.push(waiter);
        state.waiters.insert(id, reply.clone());
        state.targets.insert(id, target);
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
            state.waiting_since.remove(&id);
        }
    }

    /// Admit whatever fits, in the queue's order.
    fn admit(&self, state: &mut State) {
        loop {
            let Some(waiter) = state.queue.peek().cloned() else {
                return;
            };
            let leases = self.charged_memory(state);
            let admission = Admission {
                available: state.mem.mem_available,
                floor: self.config.floor,
            };
            if !admission.admits(&leases, waiter.peak_bytes) {
                return;
            }
            let waiter = state.queue.pop().expect("the queue had a waiter");
            let reply = state.waiters.remove(&waiter.id);
            state.waiting_since.remove(&waiter.id);
            let target = state
                .targets
                .remove(&waiter.id)
                .unwrap_or(TargetSpec::Group { pgid: 0 });
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
                current_rss: 0,
                peak_rss: 0,
                peak_gpu: 0,
                reported_peak: None,
                stopped: false,
                stopped_at: None,
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
            PeakArg::Auto => match state.history.p95(&label) {
                Some(p95) => p95,
                None => {
                    let _ = reply.send(Response::Rejected {
                        reason: format!(
                            "no history for the label {label:?}, so there is no learned peak; \
                             register it once with an explicit --peak"
                        ),
                    });
                    return;
                }
            },
        };
        let id = state.presence.queue.next_id();
        let spec = PresenceSpec::new(id, &label, tier, peak_bytes, resumable, command);
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
            let signalled = signal_group(pgid, libc::SIGTERM);
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
        let admission = Admission {
            available: state.mem.mem_available,
            floor: self.config.floor,
        };
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
        let signalled = signal_group(pgid, libc::SIGTERM);
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
        let admission = Admission {
            available: state.mem.mem_available,
            floor: self.config.floor,
        };
        loop {
            let Some(job) = state.presence.queue.next_runnable().cloned() else {
                return;
            };
            let running_ids: Vec<u64> = state.presence.running.iter().map(|j| j.id).collect();
            if running_ids.contains(&job.spec.id) {
                return;
            }
            let charged = self.charged_memory(state);
            if !admission.admits(&charged, job.spec.peak_bytes) {
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
        for lease in state.leases.iter() {
            // A lease is booked from the **grant**, not from the client's
            // confirmation. The memory is committed at the grant — that is
            // exactly what the admission rule charges — and the client's
            // "held" arrives a tick later, so counting only the confirmed
            // leases would leave a sample of the box looking idle while a
            // lease was already committed to it.
            if matches!(lease.state, LeaseState::Granted | LeaseState::Active)
                && !running_tiers.contains(&lease.tier)
            {
                running_tiers.push(lease.tier);
            }
        }
        for job in state.presence.running.iter() {
            let tier = job.tier(state);
            if job.stopped {
                if !preempted_tiers.contains(&tier) {
                    preempted_tiers.push(tier);
                }
            } else if !running_tiers.contains(&tier) {
                running_tiers.push(tier);
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
            idle,
            mem_available: state.mem.mem_available,
            gpu_power_mw: state.gpu.power_mw,
            gpu_busy_pct: state.gpu.busy_pct,
            gpu_power_source: state.gpu.power_source.clone(),
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
        let admission = Admission {
            available: state.mem.mem_available,
            floor: self.config.floor,
        };
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

    /// Release the leases whose clients are gone.
    fn check_liveness(&self, state: &mut State) {
        let mut dead = Vec::new();
        for lease in state.leases.iter() {
            match lease.state {
                LeaseState::Granted => {
                    if lease.granted_at.elapsed() > GRANT_GRACE {
                        dead.push((lease.id, "the client never took the lock"));
                    }
                }
                LeaseState::Active => match lease::is_held(&lease.lock_path) {
                    Ok(true) => {}
                    Ok(false) => dead.push((lease.id, "the client is gone")),
                    Err(error) => {
                        self.log_event(
                            "lease.probe_failed",
                            json!({"lease": lease.id, "error": error.to_string()}),
                        );
                    }
                },
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
    }

    /// The watchdog: when the box runs short, stop the largest lease.
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

        let (target, label, current_rss, stopped, stopped_at) = {
            let lease = state.leases.iter().find(|l| l.id == victim_id).unwrap();
            (
                lease.target,
                lease.label.clone(),
                lease.current_rss,
                lease.stopped,
                lease.stopped_at,
            )
        };

        if !stopped {
            let signalled = signal_target(target, libc::SIGSTOP);
            self.log_event(
                "watchdog.stopped",
                json!({
                    "lease": victim_id,
                    "label": label,
                    "rss_bytes": current_rss,
                    "mem_available_bytes": state.mem.mem_available,
                    "signalled": signalled,
                }),
            );
            if let Some(lease) = state.leases.iter_mut().find(|l| l.id == victim_id) {
                lease.stopped = true;
                lease.stopped_at = Some(Instant::now());
            }
            return;
        }

        // It was stopped and the box is still short: give it the grace
        // period, then kill it.
        let grace = Duration::from_millis(
            self.config.sample_interval.as_millis() as u64 * self.config.stop_grace_samples as u64,
        );
        let waited = stopped_at.map(|at| at.elapsed()).unwrap_or_default();
        if waited < grace {
            return;
        }
        let signalled = signal_target(target, libc::SIGTERM);
        // A stopped process never sees its SIGTERM until it runs again.
        let _ = signal_target(target, libc::SIGCONT);
        self.log_event(
            "watchdog.killed",
            json!({
                "lease": victim_id,
                "label": label,
                "rss_bytes": current_rss,
                "mem_available_bytes": state.mem.mem_available,
                "waited_ms": waited.as_millis() as u64,
                "signalled": signalled,
            }),
        );
        if let Some(lease) = state.leases.iter_mut().find(|l| l.id == victim_id) {
            lease.killed = true;
        }
    }

    /// Give the memory back and write the peak down.
    fn release_lease(&self, state: &mut State, id: u64, reason: &str) {
        let Some(index) = state.leases.iter().position(|l| l.id == id) else {
            return;
        };
        let lease = state.leases.remove(index);
        // A lease that the watchdog stopped must not be left frozen. A
        // stopped process keeps its memory, and once the lease is over
        // nobody is watching it any more: an unwatched hog holding tens of
        // gigabytes is exactly what this daemon exists to prevent. So the
        // work is asked to stop (SIGTERM) and then let go (SIGCONT) — a
        // stopped process never sees its SIGTERM until it runs again.
        if lease.stopped {
            let signalled = signal_target(lease.target, libc::SIGTERM);
            let _ = signal_target(lease.target, libc::SIGCONT);
            self.log_event(
                "lease.released_while_stopped",
                json!({"lease": lease.id, "signalled": signalled}),
            );
        }
        let (peak, peak_source) = lease.measured_peak();
        let mut record = PeakRecord::new(&lease.label, &lease.label, peak);
        record.peak_gpu_bytes = if lease.peak_gpu > 0 {
            Some(lease.peak_gpu)
        } else {
            None
        };
        record.gpu_visible = state.gpu_source != "off" && !state.gpu_source.contains("unavailable");
        record.duration_s = lease.granted_at.elapsed().as_secs_f64();
        record.mem_total_bytes = state.mem.mem_total;
        record.floor_bytes = self.config.floor;
        record.peak_source = peak_source.to_string();
        if let Err(error) = state.history.append(record) {
            self.log_event("history.write_failed", json!({"error": error.to_string()}));
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
                "duration_s": lease.granted_at.elapsed().as_secs_f64(),
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
        let mut command = std::process::Command::new("tegrastats");
        command
            .args(["--interval", "1000"])
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
        // Seal the chain over the line's own bytes (before `seq` and
        // `chain` are added), then let the two fields ride along. The
        // verifier removes them and re-serializes the rest — writer and
        // reader fold over identical bytes, so the file is self-verifying.
        let (seq, mix) = {
            let mut chain = self.chain.lock().unwrap();
            chain.seal(&line)
        };
        line["seq"] = json!(seq);
        line["chain"] = json!(format!("{mix:016x}"));
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
        leases,
        queue,
        gpu_source: state.gpu_source.clone(),
        gpu_visible: state.gpu_source != "off" && !state.gpu_source.contains("unavailable"),
        gpu_box_used_bytes: state.gpu.box_used_bytes,
        uptime_s: state.started.elapsed().as_secs_f64(),
        samples: state.samples,
        presence: presence_reports(state),
    }
}

/// Write one JSON line to a socket.
fn write_line(stream: &mut UnixStream, response: &Response) -> std::io::Result<()> {
    let mut text = serde_json::to_string(response).unwrap_or_default();
    text.push('\n');
    stream.write_all(text.as_bytes())?;
    stream.flush()
}
