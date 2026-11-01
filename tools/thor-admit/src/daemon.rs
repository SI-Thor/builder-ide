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
use crate::lease;
use crate::meminfo::MemInfo;
use crate::procscan::{self, Target};
use crate::protocol::{
    LeaseReport, PeakArg, QueueReport, Request, Response, StatusReport, TargetSpec,
};
use crate::queue::{Queue, Waiter};

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
    /// The GPU's view, kept fresh by a child that keeps printing it.
    gpu_watch: Mutex<Option<GpuWatch>>,
    /// The daemon's own log. It has its own lock so that a log line can be
    /// written while the state lock is held.
    log: Mutex<Option<std::fs::File>>,
}

impl Daemon {
    /// Build a daemon.
    pub fn new(config: Config) -> std::io::Result<Arc<Daemon>> {
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
        };
        Ok(Arc::new(Daemon {
            config,
            state: Mutex::new(state),
            wake: Condvar::new(),
            stop: Arc::new(AtomicBool::new(false)),
            listener: Mutex::new(None),
            log: Mutex::new(log),
            gpu_watch: Mutex::new(None),
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
        let _ = std::fs::remove_file(&self.config.socket);
        Ok(())
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
        let mut gpu_counter = 0u64;
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
            // The GPU's view is only worth asking for when something is
            // running: nvidia-smi takes about 17 ms a call on this box, and
            // an idle daemon should cost nothing.
            let has_leases = {
                let state = self.state.lock().unwrap();
                !state.leases.is_empty()
            };
            let want_gpu =
                self.config.gpu_probe != GpuProbe::Off && has_leases && gpu_counter % 8 == 0;
            self.tick(want_gpu);
            gpu_counter += 1;

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
    fn tick(&self, want_gpu: bool) {
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
                    target,
                } => self.register_acquire(&mut state, label, peak, priority, target, reply),
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
        if want_gpu {
            let watch = self.gpu_watch.lock().unwrap();
            if let Some(watch) = watch.as_ref() {
                state.gpu = watch.sample.lock().unwrap().clone();
                state.gpu_source = watch.source.clone();
            }
        }

        // 3. What each lease is using. The scan reads every process on the
        // box, so it runs on its own slower clock — unless the box is short
        // of memory, when the watchdog needs a fresh ranking now.
        let scan_every = (self.config.scan_interval.as_millis()
            / self.config.sample_interval.as_millis().max(1))
            .max(1) as u64;
        let urgent = state.mem.mem_available < self.config.emergency_floor;
        if !state.leases.is_empty() && (state.samples % scan_every == 0 || urgent) {
            let procs = procscan::scan();
            let gpu = state.gpu.clone();
            for lease in state.leases.iter_mut() {
                let usage = procscan::usage_for(target_of(lease.target), &procs);
                lease.current_rss = usage.rss_bytes;
                lease.peak_rss = lease.peak_rss.max(usage.rss_bytes);
                lease.peak_gpu = lease.peak_gpu.max(gpu.for_pids(&usage.pids));
            }
        }

        // 4. Are the clients still there?
        self.check_liveness(&mut state);

        // 5. The watchdog.
        self.watchdog(&mut state);

        // 6. Admission.
        self.admit(&mut state);

        // 7. And a line in the log, every ten seconds.
        if state.samples % 40 == 0 {
            self.log_event(
                "daemon.sample",
                json!({
                    "mem_available_bytes": state.mem.mem_available,
                    "mem_total_bytes": state.mem.mem_total,
                    "leases": state.leases.len(),
                    "waiting": state.queue.len(),
                    "gpu_source": state.gpu_source,
                }),
            );
        }
    }

    /// Put a new request in the queue.
    fn register_acquire(
        &self,
        state: &mut State,
        label: String,
        peak: PeakArg,
        priority: i32,
        target: TargetSpec,
        reply: Sender<Response>,
    ) {
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
            let leases: Vec<LeaseMemory> = state.leases.iter().map(|l| l.memory()).collect();
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

    /// Start the child that keeps printing the GPU's view.
    fn start_gpu_watch(&self) {
        if self.config.gpu_probe == GpuProbe::Off {
            return;
        }
        let watch = match self.config.gpu_probe {
            GpuProbe::Nvidia => self.spawn_nvidia_watch(),
            GpuProbe::Tegrastats => self.spawn_tegrastats_watch(),
            GpuProbe::Auto => self
                .spawn_nvidia_watch()
                .or_else(|| self.spawn_tegrastats_watch()),
            GpuProbe::Off => None,
        };
        match watch {
            Some(watch) => {
                self.log_event(
                    "daemon.gpu_watch",
                    json!({"source": watch.source}),
                );
                *self.gpu_watch.lock().unwrap() = Some(watch);
            }
            None => {
                self.log_event(
                    "daemon.gpu_unavailable",
                    json!({"probe": self.config.gpu_probe.as_str()}),
                );
            }
        }
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
    }
}

/// Write one JSON line to a socket.
fn write_line(stream: &mut UnixStream, response: &Response) -> std::io::Result<()> {
    let mut text = serde_json::to_string(response).unwrap_or_default();
    text.push('\n');
    stream.write_all(text.as_bytes())?;
    stream.flush()
}
