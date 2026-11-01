//! `thor-admit` — a memory-admission daemon for the Thor.
//!
//! ```text
//! thor-admit daemon                       # the resident daemon
//! thor-admit run --peak 40G --label trellis -- <command>
//! thor-admit status [--json]
//! thor-admit peaks [--label L] [--json]
//! thor-admit stop
//! ```
//!
//! The daemon is user-level on purpose: no systemd unit is installed or
//! enabled. `docs/design/thor-admit.md` has the unit the operator can drop
//! in if they want one.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use thor_admit::client::{self, Client};
use thor_admit::daemon::{Config, Daemon, DEFAULT_EMERGENCY_FLOOR, DEFAULT_FLOOR};
use thor_admit::gpu::GpuProbe;
use thor_admit::history::History;
use thor_admit::ledger::Bucket;
use thor_admit::prealloc;
use thor_admit::protocol::PeakArg;
use thor_admit::sizes::{human, Size};
use thor_admit::tier::Tier;

static STOP: AtomicBool = AtomicBool::new(false);
static RELOAD: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(signal: libc::c_int) {
    // Only flag-setting is safe in a handler; the watcher threads act.
    if signal == libc::SIGHUP {
        RELOAD.store(true, Ordering::SeqCst);
        return;
    }
    STOP.store(true, Ordering::SeqCst);
}

fn main() -> ExitCode {
    // A CLI that is piped into `head` must die quietly when the pipe closes,
    // not panic on the broken pipe. Rust ignores SIGPIPE by default, so the
    // write fails with EPIPE and the printing macro panics; the default
    // disposition of SIGPIPE — die, quietly, like every other tool — is
    // restored here.
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_DFL);
    }
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        print_help();
        return ExitCode::from(2);
    }
    let command = args[0].clone();
    match command.as_str() {
        "daemon" => run_daemon(&args[1..]),
        "run" => run_command(&args[1..]),
        "exec" => run_exec(&args[1..]),
        "serve" => run_serve(&args[1..]),
        "phase" => run_phase(&args[1..]),
        "status" => run_status(&args[1..]),
        "peaks" => run_peaks(&args[1..]),
        "presence" => run_presence(&args[1..]),
        "ledger" => run_ledger(&args[1..]),
        "reload" => run_reload(&args[1..]),
        "stop" => run_stop(&args[1..]),
        "help" | "--help" | "-h" => {
            print_help();
            ExitCode::SUCCESS
        }
        other => {
            eprintln!("thor-admit: unknown command {other:?}");
            print_help();
            ExitCode::from(2)
        }
    }
}

fn print_help() {
    println!(
        "\
thor-admit — a memory-admission daemon for the Thor

  thor-admit daemon [options]
        Run the resident daemon in the foreground.

  thor-admit run --peak <size|auto> --label <name> [--tier <tier>] [--lock <path>] -- <command>
        Take a lease, run the command under it, and give the lease back.
        --lock names the box's legacy lock (~/lm-wt/heavy.lock); it is taken
        **after** the lease is granted, so a seat that is waiting for room
        holds nothing. Never write `flock heavy.lock thor-admit run ...`: the
        seat then holds the lock for the whole of its wait.

  thor-admit exec [--allow-preallocation] [--lock <path>] -- <command>
        Start a command WITHOUT a lease, and refuse to start one that takes
        the box's memory by surprise. JAX/XLA needs
        XLA_PYTHON_CLIENT_PREALLOCATE=false (or the platform allocator, or a
        memory fraction of at most 0.15); TensorFlow needs
        TF_FORCE_GPU_ALLOW_GROWTH=true. On 2026-11-01 a JAX run outside
        thor-admit held 94.5 GB of the box's unified memory in 20 seconds and
        the box needed a power cycle.

  thor-admit serve <model> --port <n> [--peak <size|auto>] [--tier <tier>] -- <command>
        Run a shared model server under a lease, or return the port of one
        that is already answering. A model is loaded once per box, not once
        per seat: the registry is keyed on the model file (path + hash) and
        the command's other flags, so the same model under any name is one
        server, and a variant whose flags really differ is its own.
        Identical asks waiting side by side are coalesced into one waiter:
        the second asker is told which lease is starting the server and
        waits for the port instead of promising the memory twice.

  thor-admit phase <lease-id|label> --peak <size|auto>
        Change a running lease's reservation: the work changed phase. A
        shrink is taken at once (the freed bytes return to the box); a grow
        is taken only if the box has the room. A workload can phase itself:
        run puts the lease id in THOR_ADMIT_LEASE for the command.

  thor-admit status [--json]
        Show the leases, the free memory, the queue, the presence work and who
        holds the box's legacy lock.

  thor-admit peaks [--label <name>] [--json]
        Show the learned peaks: the p50 and p95 of each label's history.

  thor-admit presence add --tier <tier> --peak <size|auto> --label <name>
                         [--resumable] [--disabled] -- <command>
        Register work that runs when the box has room for it. --disabled
        registers it without running it (an example, or held-over work).
  thor-admit presence list [--json]
        Show the registered work and what it is doing.
  thor-admit presence remove <id>
        Take a job out of the presence queue.

  thor-admit ledger [--json] [--hours <n>]
        Show where the box's time went, by tier and by label, and why it
        was idle.

  thor-admit reload
        Ask the running daemon to re-read its peak history and its presence
        queue (SIGHUP does the same). For an edit made by hand.

  thor-admit stop
        Ask the running daemon to stop.

The tiers, most urgent first:
  live          nights, previews, first-mile requests
  preparation   pre-generating likely-needed assets, refreshing keyframes
  practice      retraining choosers, replaying proposed changes
  study         the Infinigen sweep, experiment batches, parity suites

Daemon options (all have defaults):
  --floor <size>            the floor a lease must clear      (default 25G)
  --emergency-floor <size>  below this, the watchdog acts     (default 8G)
  --gpu-floor <size>        the least the GPU's own allocation pool must
                            keep free (tegrastats' lfb; default 2G)
  --sample-interval-ms <n>  how often the box is sampled      (default 250)
  --scan-interval-ms <n>    how often the processes' memory is read (default 1000)
  --stop-grace-samples <n>  samples a watchdog-terminated lease is given
                            before the watchdog escalates to SIGKILL (default 8)
  --heartbeat-grace-secs <n> how long a silent client keeps its lease
                            (the client heartbeats every 5s; default 60)
  --grant-grace-secs <n>    how long a grant waits for its client to take
                            the lock (default 30)
  --min-victim-rss <size>   the smallest lease the watchdog will touch (default 2G)
  --socket <path>           the socket to listen on
  --state-dir <path>        where the lease files and the log live
  --history <path>          where the learned peaks are written
  --meminfo <path>          where the box's memory is read (default /proc/meminfo)
  --gpu-probe <auto|nvidia|tegrastats|off>   the GPU's view (default auto)
  --tegrastats-command <path>  a test seam: run this instead of tegrastats
  --idle-exit <seconds>     leave after this long with nothing to do (default 900)
  --no-stop-on-client-gone  leave a dead client's command running (default: stop it)
  --no-presence             do not run the presence queue (default: run it)
  --no-backfill             do not pass requests around a blocked head
                            (default: backfill when it cannot delay the head)
  --backfill-max-head-wait <seconds>
                            once the head has waited this long, nothing more
                            passes it (default 1800; 0 = no bound)
  --presence-file <path>    where the presence queue is kept
  --flow-file <path>        where the flow signal is published, if anyone
                            publishes one (default <state-dir>/flow.json)
  --ledger <path>           where the ledger's hours are written
  --ledger-interval-ms <n>  how often the CPU's counters are read (default 1000)
  --gpu-busy-threshold <n>  the GPU's busy share at which live work takes
                            the GPU from the presence queue (default 50)
  --no-gpu-preempt          never stop the presence work for the GPU
  --no-guard                never stop work that is outside a lease
                            (default: stop it when the box is in trouble)
  --guard-min-rss <size>    the smallest unleased process the guard will
                            touch (default 4G)
  --guard-drop <size>       the fall in free memory that counts as a runaway
                            (default 8G inside the window)
  --guard-window-secs <n>   the window the fall is measured over (default 10)
  --guard-interval-ms <n>  how often the guard looks at the box (default 2000)
  --guard-protected-file <path>
                            the operator's list of command lines the guard
                            must never touch (default <state-dir>/protected.txt)
"
    );
}

/// A tiny option reader: `--key value` and `--key=value`.
struct Options {
    values: HashMap<String, String>,
    flags: Vec<String>,
    rest: Vec<String>,
}

impl Options {
    fn parse(args: &[String]) -> Options {
        let mut values = HashMap::new();
        let mut flags = Vec::new();
        let mut rest = Vec::new();
        let mut index = 0;
        while index < args.len() {
            let arg = &args[index];
            if arg == "--" {
                rest.extend_from_slice(&args[index + 1..]);
                break;
            }
            if let Some(name) = arg.strip_prefix("--") {
                if let Some((key, value)) = name.split_once('=') {
                    values.insert(key.to_string(), value.to_string());
                } else if index + 1 < args.len() && !args[index + 1].starts_with("--") {
                    values.insert(name.to_string(), args[index + 1].clone());
                    index += 1;
                } else {
                    flags.push(name.to_string());
                }
            } else {
                rest.push(arg.clone());
            }
            index += 1;
        }
        Options {
            values,
            flags,
            rest,
        }
    }

    fn get(&self, key: &str) -> Option<&str> {
        self.values.get(key).map(String::as_str)
    }

    fn has(&self, key: &str) -> bool {
        self.flags.iter().any(|flag| flag == key)
    }

    fn size(&self, key: &str) -> Result<Option<u64>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(text) => Size::parse(text)
                .map(|size| Some(size.bytes))
                .map_err(|error| format!("--{key}: {error}")),
        }
    }

    fn number(&self, key: &str) -> Result<Option<u64>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(text) => text
                .parse::<u64>()
                .map(Some)
                .map_err(|_| format!("--{key}: {text:?} is not a number")),
        }
    }
}

fn socket_path(options: &Options) -> Result<PathBuf, String> {
    match options.get("socket") {
        Some(path) => Ok(PathBuf::from(path)),
        None => Ok(thor_admit::daemon::default_socket_path()),
    }
}

/// Start the daemon if it is not already running, and wait for its socket.
fn ensure_daemon(socket: &PathBuf) -> Result<(), String> {
    // The probe *asks* the daemon something, it does not just connect: a
    // bound socket accepts connections into its backlog even when nobody
    // ever accepts them, so a daemon wedged between its bind and its
    // acceptor would otherwise count as "up" (round 10, item b).
    if client::daemon_answers(socket) {
        return Ok(());
    }
    let program = std::env::current_exe().map_err(|e| e.to_string())?;
    // A daemon started for a socket that is not the box's own keeps its
    // state beside that socket. Without this the daemon fell back to the
    // default state directory — the box's real one — and wrote its history,
    // its ledger and its log there, so a test's daemon became part of the
    // box's own record.
    let state_dir = state_dir_for(socket);
    let _ = std::fs::create_dir_all(&state_dir);
    let errors = std::fs::File::create(state_dir.join("daemon.err"))
        .map_err(|e| e.to_string())?;
    let mut command = std::process::Command::new(program);
    command
        .arg("daemon")
        .arg("--socket")
        .arg(socket)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::from(errors));
    if *socket != thor_admit::daemon::default_socket_path() {
        command.arg("--state-dir").arg(&state_dir);
    }
    command.spawn().map_err(|e| format!("cannot start the daemon: {e}"))?;
    for _ in 0..100 {
        std::thread::sleep(Duration::from_millis(100));
        if client::daemon_answers(socket) {
            return Ok(());
        }
    }
    Err(format!(
        "the daemon did not come up on {}",
        socket.display()
    ))
}

/// Where a daemon's state lives: beside its socket when that socket is not
/// the box's own, and in the default place when it is.
fn state_dir_for(socket: &PathBuf) -> PathBuf {
    if *socket != thor_admit::daemon::default_socket_path() {
        if let Some(parent) = socket.parent() {
            return parent.to_path_buf();
        }
    }
    thor_admit::daemon::default_state_dir()
}

fn run_daemon(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let mut config = Config::default();
    match options.size("floor") {
        Ok(Some(value)) => config.floor = value,
        Ok(None) => config.floor = DEFAULT_FLOOR,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.size("emergency-floor") {
        Ok(Some(value)) => config.emergency_floor = value,
        Ok(None) => config.emergency_floor = DEFAULT_EMERGENCY_FLOOR,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.size("min-victim-rss") {
        Ok(Some(value)) => config.min_victim_rss = value,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.size("gpu-floor") {
        Ok(Some(value)) => config.gpu_floor = value,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("startup-timeout-secs") {
        Ok(Some(value)) => config.startup_timeout = Duration::from_secs(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    if let Some(value) = options.get("tegrastats-command") {
        config.tegrastats_command = Some(PathBuf::from(value));
    }
    if let Some(value) = options.get("socket") {
        config.socket = PathBuf::from(value);
    }
    if let Some(value) = options.get("state-dir") {
        config.state_dir = PathBuf::from(value);
        config.history = config.state_dir.join("peaks.jsonl");
        config.presence_file = config.state_dir.join("presence.json");
        config.ledger = config.state_dir.join("ledger.jsonl");
        config.flow_file = config.state_dir.join("flow.json");
        config.guard_protected_file = config.state_dir.join("protected.txt");
    }
    if let Some(value) = options.get("history") {
        config.history = PathBuf::from(value);
    }
    if let Some(value) = options.get("presence-file") {
        config.presence_file = PathBuf::from(value);
    }
    if let Some(value) = options.get("flow-file") {
        config.flow_file = PathBuf::from(value);
    }
    if let Some(value) = options.get("ledger") {
        config.ledger = PathBuf::from(value);
    }
    if options.has("no-presence") {
        config.presence = false;
    }
    if options.has("no-backfill") {
        config.backfill = false;
    }
    match options.number("backfill-max-head-wait") {
        Ok(Some(value)) => {
            config.backfill_max_head_wait = Duration::from_secs(value);
        }
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    if options.has("no-gpu-preempt") {
        config.gpu_preempt = false;
    }
    if options.has("no-guard") {
        config.guard = false;
    }
    match options.size("guard-min-rss") {
        Ok(Some(value)) => config.guard_min_rss = value,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.size("guard-drop") {
        Ok(Some(value)) => config.guard_drop_bytes = value,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("guard-window-secs") {
        Ok(Some(value)) => config.guard_window = Duration::from_secs(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("guard-interval-ms") {
        Ok(Some(value)) => config.guard_interval = Duration::from_millis(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    if let Some(value) = options.get("guard-protected-file") {
        config.guard_protected_file = PathBuf::from(value);
    }
    match options.number("gpu-busy-threshold") {
        Ok(Some(value)) => config.gpu_busy_threshold = value.min(100) as u8,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("ledger-interval-ms") {
        Ok(Some(value)) => config.ledger_interval = Duration::from_millis(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    if let Some(value) = options.get("meminfo") {
        config.meminfo = PathBuf::from(value);
    }
    match options.number("sample-interval-ms") {
        Ok(Some(value)) => config.sample_interval = Duration::from_millis(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("scan-interval-ms") {
        Ok(Some(value)) => config.scan_interval = Duration::from_millis(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("stop-grace-samples") {
        Ok(Some(value)) => config.stop_grace_samples = value as u32,
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("heartbeat-grace-secs") {
        Ok(Some(value)) => config.heartbeat_grace = Duration::from_secs(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("grant-grace-secs") {
        Ok(Some(value)) => config.grant_grace = Duration::from_secs(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    match options.number("idle-exit") {
        Ok(Some(value)) => config.idle_exit = Duration::from_secs(value),
        Ok(None) => {}
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    }
    if options.has("no-stop-on-client-gone") {
        config.stop_on_client_gone = false;
    }
    if let Some(value) = options.get("gpu-probe") {
        match GpuProbe::parse(value) {
            Some(probe) => config.gpu_probe = probe,
            None => {
                eprintln!("thor-admit: --gpu-probe: {value:?} is not one of auto, nvidia, tegrastats, off");
                return ExitCode::from(2);
            }
        }
    }

    unsafe {
        libc::signal(libc::SIGINT, on_signal as *const () as libc::sighandler_t);
        libc::signal(libc::SIGTERM, on_signal as *const () as libc::sighandler_t);
        libc::signal(libc::SIGHUP, on_signal as *const () as libc::sighandler_t);
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    // The startup watchdog (round 10, item b). The auto-started daemon of
    // 04:15 on 2026-11-01 hung on the way up — wedged in `futex_wait_queue`,
    // holding the socket's lock, never having bound the socket — and sat on
    // the box until a human killed it. The bind now comes before the lock,
    // so a daemon wedging on the way up holds nothing; the deadline is the
    // belt to that: a daemon that has not begun serving in time says why
    // and exits, the kernel drops whatever it holds, and the next client's
    // auto-start takes the socket back. It watches from *before* the daemon
    // is built, because a wedge in the building is the wedge it is for.
    let startup_timeout = config.startup_timeout;
    let daemon_seat: Arc<Mutex<Option<Arc<Daemon>>>> = Arc::new(Mutex::new(None));
    let watched = Arc::clone(&daemon_seat);
    let _startup_watchdog = std::thread::spawn(move || {
        if startup_timeout.is_zero() {
            return;
        }
        let deadline = Instant::now() + startup_timeout;
        while Instant::now() < deadline {
            let up = {
                let seat = watched.lock().unwrap();
                match seat.as_ref() {
                    Some(daemon) => daemon.is_serving() || daemon.is_stopped(),
                    None => false,
                }
            };
            if up {
                return;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        eprintln!(
            "thor-admit: the daemon did not begin serving within {} s; exiting so the \
             socket is free for the next start",
            startup_timeout.as_secs()
        );
        std::process::exit(1);
    });

    let daemon = match Daemon::new(config) {
        Ok(daemon) => daemon,
        Err(error) => {
            eprintln!("thor-admit: cannot start the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    *daemon_seat.lock().unwrap() = Some(Arc::clone(&daemon));
    // The pid file, so `thor-admit stop` can find it.
    let pid_path = daemon.socket_path().with_extension("pid");
    let _ = std::fs::write(&pid_path, std::process::id().to_string());

    let watcher = {
        let daemon = std::sync::Arc::clone(&daemon);
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(100));
            if RELOAD.swap(false, Ordering::SeqCst) {
                // SIGHUP: re-read the history and the presence queue, so an
                // edit made by hand reaches a daemon that is mid-flight.
                daemon.reload();
                continue;
            }
            if STOP.load(Ordering::SeqCst) {
                daemon.stop();
            }
            // The daemon's own word matters as much as the signal's: after
            // an idle exit the clock has already stopped, and a watcher
            // that waited only for a signal would keep the process — and
            // with it the socket's lock — alive with nothing behind it.
            if daemon.is_stopped() {
                return;
            }
        })
    };

    let result = daemon.run();
    let _ = watcher.join();
    let _ = std::fs::remove_file(&pid_path);
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("thor-admit: the daemon stopped: {error}");
            ExitCode::from(1)
        }
    }
}

fn run_command(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let label = match options.get("label") {
        Some(label) => label.to_string(),
        None => {
            eprintln!("thor-admit: run needs a --label");
            return ExitCode::from(2);
        }
    };
    if options.rest.is_empty() {
        eprintln!("thor-admit: run needs a command after --");
        return ExitCode::from(2);
    }
    let peak = match options.get("peak") {
        None => {
            eprintln!("thor-admit: run needs a --peak (a size, or \"auto\")");
            return ExitCode::from(2);
        }
        Some(text) if text.eq_ignore_ascii_case("auto") => PeakArg::Auto,
        Some(text) => match Size::parse(text) {
            Ok(size) => PeakArg::Bytes(size.bytes),
            Err(error) => {
                eprintln!("thor-admit: --peak: {error}");
                return ExitCode::from(2);
            }
        },
    };
    let priority = match options.number("priority") {
        Ok(Some(value)) => value as i32,
        Ok(None) => 0,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    let tier = match options.get("tier") {
        None => Tier::Live,
        Some(text) => match Tier::parse(text) {
            Some(tier) => tier,
            None => {
                eprintln!(
                    "thor-admit: --tier: {text:?} is not one of live, preparation, practice, study"
                );
                return ExitCode::from(2);
            }
        },
    };
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    // The box's legacy lock, if the seat asked for it. It is taken **after**
    // the lease is granted (round 13), so a seat that is waiting for room
    // holds nothing.
    let lock = match options.get("lock") {
        Some(path) => Some(PathBuf::from(path)),
        None => None,
    };
    if let Err(error) = ensure_daemon(&socket) {
        eprintln!("thor-admit: {error}");
        return ExitCode::from(1);
    }
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("thor-admit: cannot reach the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    let mut revive = {
        let socket = socket.clone();
        move || {
            if let Err(error) = ensure_daemon(&socket) {
                eprintln!("thor-admit: {error}");
            }
        }
    };
    let under_lease = match client::run_under_lease(
        &mut connection,
        &socket,
        &label,
        peak,
        priority,
        tier,
        None,
        &options.rest,
        lock.as_deref(),
        &mut revive,
    ) {
        Ok(under_lease) => under_lease,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(1);
        }
    };
    let outcome = match under_lease {
        client::UnderLease::Ran(outcome) => outcome,
        client::UnderLease::Coalesced { lease } => {
            // Only a serve ask carries a coalescing key, and `run` never
            // does: reaching this means the daemon answered a plain ask
            // with a serve answer, which is its bug to fix, not ours.
            eprintln!("thor-admit: the daemon coalesced {label:?} into lease {lease}, which a run cannot be");
            return ExitCode::from(1);
        }
    };
    eprintln!(
        "thor-admit: {label:?} finished with {} (peak RSS {})",
        match outcome.signal {
            Some(signal) => format!("signal {signal}"),
            None => format!("code {}", outcome.code),
        },
        human(outcome.peak_rss_bytes)
    );
    ExitCode::from((outcome.code & 0xff) as u8)
}

/// `thor-admit exec -- <command>`
///
/// Start a command on the box **without** a lease, and refuse to start one
/// that would take the box's memory by surprise.
///
/// The refusal is the point of the command. On a discrete GPU, JAX/XLA's
/// preallocation takes a private pool on the card and the rest of the machine
/// never notices. On the Thor the GPU's memory **is** the system's memory,
/// so the same preallocation takes most of the machine's RAM before the
/// program computes anything: on 2026-11-01 a MJX run held 94.5 GB in 20
/// seconds, the desktop died, the Wi-Fi driver died, and the box needed a
/// power cycle (see `docs/lab/incident-2026-11-01-jax-hang.md`).
///
/// So `exec` reads the command line, finds out whether it starts a framework
/// that preallocates — by the module it runs, by the code it passes to `-c`,
/// or by what the script on disk imports — and refuses unless the
/// environment has told the framework not to preallocate:
///
/// * JAX/XLA — `XLA_PYTHON_CLIENT_PREALLOCATE=false`, or
///   `XLA_PYTHON_CLIENT_ALLOCATOR=platform`, or
///   `XLA_PYTHON_CLIENT_MEM_FRACTION` at most 0.15;
/// * TensorFlow — `TF_FORCE_GPU_ALLOW_GROWTH=true`.
///
/// The work still runs **outside** a lease, which is what makes this the
/// guard's counterpart: the daemon's guard (round 12) can stop a runaway
/// after it has started, and this stops it before. `--allow-preallocation`
/// overrides the refusal, loudly, for the case where the operator knows the
/// run is safe.
fn run_exec(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    if options.rest.is_empty() {
        eprintln!("thor-admit: exec needs a command after --");
        return ExitCode::from(2);
    }
    let command = &options.rest;

    if let Some(detected) = prealloc::detect(command) {
        let framework = prealloc::FRAMEWORKS
            .iter()
            .find(|framework| framework.name == detected.framework)
            .expect("a detected framework is one of the known ones");
        if options.has("allow-preallocation") {
            eprintln!(
                "thor-admit: starting a {} process with --allow-preallocation: its allocator \
                 was not made safe on purpose ({}).",
                detected.framework, detected.evidence
            );
        } else {
            match prealloc::safety(framework, &|key: &str| std::env::var(key).ok()) {
                Ok(reason) => {
                    eprintln!(
                        "thor-admit: {} is safe here ({reason}); starting it.",
                        detected.framework
                    );
                }
                Err(_) => {
                    eprintln!("{}", prealloc::refusal(&detected, command));
                    return ExitCode::from(2);
                }
            }
        }
    }

    eprintln!(
        "thor-admit: exec runs the command without a lease. The daemon's guard can stop it \
         if the box runs short; heavy work belongs under one: thor-admit run --peak 16G --label \
         <name> -- <command>"
    );
    // `exec` has no lease, so there is no "after the lease" to wait for: the
    // box's lock is taken here, before the command starts, and held for as
    // long as the command runs.
    if let Some(path) = options.get("lock") {
        let path = PathBuf::from(path);
        eprintln!("thor-admit: taking the box's lock {}", path.display());
        let _lock = match thor_admit::boxlock::BoxLock::acquire(&path) {
            Ok(lock) => lock,
            Err(error) => {
                eprintln!("thor-admit: cannot take {}: {error}", path.display());
                return ExitCode::from(1);
            }
        };
        client::exec_now(command)
    }
    client::exec_now(command)
}

/// `thor-admit serve <model> --port <n> [--peak S|auto] [--tier T] -- <command>`
///
/// The seat's side of the shared-model registry. The registry is keyed on
/// what the command identifies — the **model file** (path + content hash)
/// and the **config tuple** (the command's other flags) — not on the name
/// the seat types, so `d1-2B`, `d1-2B-baseline` and `d1-2B-batch` are three
/// names for one server when the command is the same, and a variant only
/// when its flags really differ. Three answers, in order:
///
/// 1. this model file under these flags is already answering on a
///    registered port — say the port and run nothing (this is the point: a
///    model is loaded once per box);
/// 2. the port is answering but nobody registered it — say so and stop,
///    because starting a second server on that port cannot work;
/// 3. nothing — take a live lease (`serve.<model>`) and run the server
///    under it, recording the port once it answers. `serve` stays in front
///    of the server for its whole life: the lease, the heartbeat and the
///    daemon's cleanup all hold through it, and when it is killed the
///    server goes with it.
fn run_serve(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let Some(model) = options.rest.first().cloned() else {
        eprintln!("thor-admit: serve needs a model name (serve d1-2B ...)");
        return ExitCode::from(2);
    };
    let command = options.rest[1..].to_vec();
    if command.is_empty() {
        eprintln!("thor-admit: serve needs a command after --");
        return ExitCode::from(2);
    }
    let Some(port) = options
        .number("port")
        .ok()
        .flatten()
        .and_then(|value| u16::try_from(value).ok())
    else {
        eprintln!("thor-admit: serve needs a --port (a number between 1 and 65535)");
        return ExitCode::from(2);
    };
    let peak = match options.get("peak") {
        None => PeakArg::Auto,
        Some(text) if text.eq_ignore_ascii_case("auto") => PeakArg::Auto,
        Some(text) => match Size::parse(text) {
            Ok(size) => PeakArg::Bytes(size.bytes),
            Err(error) => {
                eprintln!("thor-admit: --peak: {error}");
                return ExitCode::from(2);
            }
        },
    };
    let tier = match options.get("tier") {
        None => Tier::Live,
        Some(text) => match Tier::parse(text) {
            Some(tier) => tier,
            None => {
                eprintln!(
                    "thor-admit: --tier: {text:?} is not one of live, preparation, practice, study"
                );
                return ExitCode::from(2);
            }
        },
    };
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    if let Err(error) = ensure_daemon(&socket) {
        eprintln!("thor-admit: {error}");
        return ExitCode::from(1);
    }
    let registry = thor_admit::serve::Registry::new(&state_dir_for(&socket));

    // What this command actually is: the model file (path + hash) and the
    // flags around it. The name the seat typed is not in it.
    let key = thor_admit::serve::key_for(&command);
    match key.basis {
        "file" => eprintln!(
            "thor-admit: {model:?} is the model {} (hash {}), flags {:?}",
            key.model_file.as_ref().map(|path| path.display().to_string()).unwrap_or_default(),
            key.model_hash.as_deref().unwrap_or("-"),
            key.config
        ),
        _ => eprintln!(
            "thor-admit: {model:?} named no model file; keying on the command {:?}",
            key.config
        ),
    }

    // 1. Somebody is already serving this model under these flags.
    if let Some(entry) = registry.find(&key.key) {
        eprintln!(
            "thor-admit: {model:?} is {:?} already serving on port {} — \
             same model file, same flags; nothing to load",
            entry.model, entry.port
        );
        return report_serve(&model, entry.port, "existing", options.has("json"));
    }
    // 2. The port is taken by something the registry does not know.
    if thor_admit::serve::port_answers(port) {
        eprintln!(
            "thor-admit: port {port} is answering but {model:?} is not in the registry; \
             is the server running outside `thor-admit serve`?"
        );
        return ExitCode::from(1);
    }

    // 3. Ours to start. The watcher records the port the moment the server
    //    answers it, so a second seat arriving seconds from now finds it.
    eprintln!("thor-admit: serving {model:?} on port {port} (nothing answered there)");
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("thor-admit: cannot reach the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    let recorded = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let watcher = {
        let recorded = std::sync::Arc::clone(&recorded);
        let registry = thor_admit::serve::Registry::new(&state_dir_for(&socket));
        let key = key.clone();
        let model = model.clone();
        std::thread::spawn(move || {
            for _ in 0..480 {
                if thor_admit::serve::port_answers(port) {
                    registry.record(thor_admit::serve::entry(&key, &model, port));
                    recorded.store(true, std::sync::atomic::Ordering::SeqCst);
                    return;
                }
                std::thread::sleep(Duration::from_millis(250));
            }
        })
    };
    let label = format!("serve.{model}");
    let mut revive = {
        let socket = socket.clone();
        move || {
            if let Err(error) = ensure_daemon(&socket) {
                eprintln!("thor-admit: {error}");
            }
        }
    };
    let outcome = client::run_under_lease(
        &mut connection,
        &socket,
        &label,
        peak,
        0,
        tier,
        Some(&key.key),
        &command,
        // A model server does not take the box's legacy lock: the daemon
        // already accounts for its memory, and the lock would only stop the
        // seats that have not migrated from starting their own copy.
        None,
        &mut revive,
    );
    // A coalesced ask does not wait on the lease it joined: the leader's
    // server is the answer, and the registry is where the leader's watcher
    // records it the moment the port answers. While waiting, the lease
    // itself is the other thing to watch: if it ends without the registry
    // ever naming a port, the leader's server never answered, and this
    // ask should fail rather than wait out the half hour.
    if let Ok(client::UnderLease::Coalesced { lease }) = &outcome {
        eprintln!(
            "thor-admit: waiting for {model:?} to answer under lease {lease} (the ask was coalesced)"
        );
        let registry = thor_admit::serve::Registry::new(&state_dir_for(&socket));
        let deadline = Instant::now() + Duration::from_secs(1800);
        let mut lease_ended_at: Option<Instant> = None;
        loop {
            if let Some(entry) = registry.find(&key.key) {
                return report_serve(&model, entry.port, "coalesced", options.has("json"));
            }
            let lease_alive = connection
                .status()
                .map(|report| report.leases.iter().any(|running| running.lease == *lease))
                .unwrap_or(true);
            if lease_alive {
                lease_ended_at = None;
            } else {
                // A short grace: the leader's watcher may record the port in
                // the moments after the lease releases.
                match lease_ended_at {
                    None => lease_ended_at = Some(Instant::now()),
                    Some(at) if at.elapsed() > Duration::from_secs(5) => break,
                    Some(_) => {}
                }
            }
            if Instant::now() > deadline {
                break;
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        eprintln!(
            "thor-admit: the coalesced lease {lease} for {model:?} never answered a port"
        );
        return ExitCode::from(1);
    }
    let _ = watcher.join();
    let outcome = match outcome {
        Ok(client::UnderLease::Ran(outcome)) => outcome,
        Ok(client::UnderLease::Coalesced { .. }) => unreachable!("handled above"),
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(1);
        }
    };
    // The server is gone; its entry goes with it. An entry that somehow
    // stays is harmless — `find` probes the port — but the file should not
    // remember servers that are not there.
    if recorded.load(std::sync::atomic::Ordering::SeqCst) {
        registry.remove(&key.key);
    }
    if !recorded.load(std::sync::atomic::Ordering::SeqCst) {
        eprintln!(
            "thor-admit: {model:?} never answered on port {port} in two minutes; \
             nothing was registered"
        );
    }
    eprintln!(
        "thor-admit: {model:?} on port {port} finished with code {}",
        outcome.code
    );
    ExitCode::from((outcome.code & 0xff) as u8)
}

/// `thor-admit phase <lease-id|label> --peak <size|auto>`
///
/// A lease that reserved far above its use can give the difference back
/// while it runs: the work changed phase, and the reservation should say
/// so (round 11). The lease is named by its id (what `run` leaves in the
/// command's `THOR_ADMIT_LEASE`) or by its label, when exactly one lease of
/// that label is running. A shrink is always taken; a grow needs the room.
fn run_phase(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let Some(selector) = options.rest.first().cloned() else {
        eprintln!("thor-admit: phase needs a lease id or a label (phase 7 --peak 4G)");
        return ExitCode::from(2);
    };
    let peak = match options.get("peak") {
        None => {
            eprintln!("thor-admit: phase needs a --peak (a size, or \"auto\")");
            return ExitCode::from(2);
        }
        Some(text) if text.eq_ignore_ascii_case("auto") => PeakArg::Auto,
        Some(text) => match Size::parse(text) {
            Ok(size) => PeakArg::Bytes(size.bytes),
            Err(error) => {
                eprintln!("thor-admit: --peak: {error}");
                return ExitCode::from(2);
            }
        },
    };
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("thor-admit: cannot reach the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    // The lease to phase: an id outright, or a label when exactly one lease
    // of that label is running. Two leases of one label is not ambiguity
    // the daemon can resolve — it is two leases, and the operator names one.
    let lease = match selector.parse::<u64>() {
        Ok(id) => id,
        Err(_) => {
            let report = match connection.status() {
                Ok(report) => report,
                Err(error) => {
                    eprintln!("thor-admit: cannot ask the daemon: {error}");
                    return ExitCode::from(1);
                }
            };
            let matches: Vec<&thor_admit::protocol::LeaseReport> = report
                .leases
                .iter()
                .filter(|lease| lease.label == selector)
                .collect();
            match matches.as_slice() {
                [only] => only.lease,
                [] => {
                    eprintln!(
                        "thor-admit: no running lease is labelled {selector:?}; the leases are {}",
                        report
                            .leases
                            .iter()
                            .map(|lease| format!("#{} {}", lease.lease, lease.label))
                            .collect::<Vec<_>>()
                            .join(", ")
                    );
                    return ExitCode::from(1);
                }
                several => {
                    eprintln!(
                        "thor-admit: {} leases are labelled {selector:?}; name one by id: {}",
                        several.len(),
                        several
                            .iter()
                            .map(|lease| format!("#{}", lease.lease))
                            .collect::<Vec<_>>()
                            .join(", ")
                    );
                    return ExitCode::from(1);
                }
            }
        }
    };
    match connection.phase(lease, peak) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            ExitCode::from(1)
        }
    }
}

/// Say where a model is served.
fn report_serve(model: &str, port: u16, status: &str, json: bool) -> ExitCode {
    if json {
        println!(
            "{}",
            client::json_line(&serde_json::json!({
                "model": model,
                "port": port,
                "status": status,
            }))
        );
    } else {
        println!("thor-admit: {model:?} is served on port {port}");
    }
    ExitCode::SUCCESS
}

fn run_status(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            if options.has("json") {
                let value = client::unreachable_json(&socket, &error);
                println!("{}", client::json_line(&value));
            } else {
                eprintln!(
                    "thor-admit: the daemon is not running on {} ({error})",
                    socket.display()
                );
            }
            return ExitCode::from(1);
        }
    };
    let report = match connection.status() {
        Ok(report) => report,
        Err(error) => {
            eprintln!("thor-admit: cannot ask the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    if options.has("json") {
        let value = serde_json::to_value(&report).unwrap_or_default();
        println!("{}", client::json_line(&value));
        return ExitCode::SUCCESS;
    }
    println!(
        "memory: {} free of {} (floor {}, emergency floor {}, gpu floor {})",
        human(report.mem_available_bytes),
        human(report.mem_total_bytes),
        human(report.floor_bytes),
        human(report.emergency_floor_bytes),
        human(report.gpu_floor_bytes)
    );
    println!("gpu view: {}", report.gpu_source);
    if let Some(free) = report.gpu_largest_free_block_bytes {
        println!(
            "gpu pool: {} free of the allocation pool (from {})",
            human(free), report.gpu_source
        );
    }
    println!("leases: {}", report.leases.len());
    for lease in &report.leases {
        // A lease the daemon has named as over-reserved says so here, with
        // the peak it would suggest, so the holder can answer without
        // reading the log: `thor-admit phase <id> --peak <suggested>`.
        let over = if lease.over_reserved {
            format!("  over-reserved, would fit {}", human(lease.suggested_peak_bytes))
        } else {
            String::new()
        };
        println!(
            "  #{} {:<16} peak {:>8}  now {:>8}  saw {:>8}  pid {}  {:.0}s{over}",
            lease.lease,
            lease.label,
            human(lease.peak_bytes),
            human(lease.current_rss_bytes),
            human(lease.peak_rss_bytes),
            lease.pid,
            lease.age_s
        );
    }
    println!("queue: {}", report.queue.len());
    for waiter in &report.queue {
        let coalesced = if waiter.coalesced > 0 {
            format!("  +{} coalesced", waiter.coalesced)
        } else {
            String::new()
        };
        println!(
            "  {}. {:<16} peak {:>8}  priority {}  waiting {:.0}s{}",
            waiter.position,
            waiter.label,
            human(waiter.peak_bytes),
            waiter.priority,
            waiter.waiting_s,
            coalesced
        );
    }
    println!("presence: {}", report.presence.len());
    for job in &report.presence {
        let label = if job.enabled {
            job.label.clone()
        } else {
            format!("{} (disabled)", job.label)
        };
        println!(
            "  #{} {:<28} {:<12} peak {:>8}  {:<10}  runs {}  preempted {}",
            job.id,
            label,
            job.tier.as_str(),
            human(job.peak_bytes),
            job.state,
            job.attempts,
            job.preemptions
        );
    }
    // The box's legacy lock, and who holds it. This is read from the kernel's
    // own record of the locks on the box (`/proc/locks`), not from the
    // daemon, so it is true even for a seat that never took a lease (round
    // 13).
    let box_lock = match options.get("box-lock") {
        Some(path) => PathBuf::from(path),
        None => thor_admit::boxlock::default_lock_path(),
    };
    match thor_admit::boxlock::holder(&box_lock) {
        Ok(Some(pid)) => {
            let who = thor_admit::boxlock::command_line(pid)
                .map(|line| format!(" — {line}"))
                .unwrap_or_default();
            println!("box lock: {} held by pid {pid}{who}", box_lock.display());
        }
        Ok(None) => println!("box lock: {} free", box_lock.display()),
        Err(error) => println!(
            "box lock: {} — cannot be read ({error})",
            box_lock.display()
        ),
    }
    ExitCode::SUCCESS
}

fn run_peaks(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let history_path = match options.get("history") {
        Some(path) => PathBuf::from(path),
        // The daemon's own --state-dir is where its history lives, so the
        // command that reads that history must be able to find it too.
        None => match options.get("state-dir") {
            Some(dir) => PathBuf::from(dir).join("peaks.jsonl"),
            None => Config::default().history,
        },
    };
    let history = History::load(&history_path);
    let wanted = options.get("label");
    let mut labels: Vec<String> = Vec::new();
    for record in history.records() {
        if let Some(wanted) = wanted {
            if record.label != wanted {
                continue;
            }
        }
        if !labels.contains(&record.label) {
            labels.push(record.label.clone());
        }
    }
    if options.has("json") {
        let mut out = Vec::new();
        for label in &labels {
            let peaks = history.peaks_for(label);
            out.push(serde_json::json!({
                "label": label,
                "samples": peaks.len(),
                "p50_bytes": history.p50(label),
                "p95_bytes": history.p95(label),
                "last_peak_rss_bytes": peaks.last().copied(),
            }));
        }
        println!("{}", client::json_line(&serde_json::json!({"peaks": out})));
        return ExitCode::SUCCESS;
    }
    if labels.is_empty() {
        println!("no peaks recorded yet in {}", history_path.display());
        return ExitCode::SUCCESS;
    }
    for label in &labels {
        let peaks = history.peaks_for(label);
        println!(
            "{label}: {} samples, p50 {}, p95 {}",
            peaks.len(),
            history.p50(label).map(human).unwrap_or("-".to_string()),
            history.p95(label).map(human).unwrap_or("-".to_string()),
        );
    }
    ExitCode::SUCCESS
}

/// The presence queue: the work that runs when the box has room.
fn run_presence(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let action = options.rest.first().map(String::as_str).unwrap_or("list");
    let rest = &options.rest[options.rest.len().min(1)..];
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    match action {
        "add" => {
            let label = match options.get("label") {
                Some(label) => label.to_string(),
                None => {
                    eprintln!("thor-admit: presence add needs a --label");
                    return ExitCode::from(2);
                }
            };
            let tier = match options.get("tier") {
                None => Tier::Study,
                Some(text) => match Tier::parse(text) {
                    Some(tier) => tier,
                    None => {
                        eprintln!(
                            "thor-admit: --tier: {text:?} is not one of live, preparation, \
                             practice, study"
                        );
                        return ExitCode::from(2);
                    }
                },
            };
            let peak = match options.get("peak") {
                None => {
                    eprintln!("thor-admit: presence add needs a --peak (a size, or \"auto\")");
                    return ExitCode::from(2);
                }
                Some(text) if text.eq_ignore_ascii_case("auto") => PeakArg::Auto,
                Some(text) => match Size::parse(text) {
                    Ok(size) => PeakArg::Bytes(size.bytes),
                    Err(error) => {
                        eprintln!("thor-admit: --peak: {error}");
                        return ExitCode::from(2);
                    }
                },
            };
            if rest.is_empty() {
                eprintln!("thor-admit: presence add needs a command after --");
                return ExitCode::from(2);
            }
            if let Err(error) = ensure_daemon(&socket) {
                eprintln!("thor-admit: {error}");
                return ExitCode::from(1);
            }
            let mut connection = match Client::connect(&socket) {
                Ok(connection) => connection,
                Err(error) => {
                    eprintln!("thor-admit: cannot reach the daemon: {error}");
                    return ExitCode::from(1);
                }
            };
            match connection.presence_add(
                &label,
                tier,
                peak,
                options.has("resumable"),
                !options.has("disabled"),
                rest.to_vec(),
            ) {
                Ok((id, label, tier)) => {
                    if options.has("disabled") {
                        println!(
                            "thor-admit: registered #{id} {label:?} as {tier} (disabled: \
                             it stays registered and does not run)"
                        );
                    } else {
                        println!("thor-admit: registered #{id} {label:?} as {tier}");
                    }
                    ExitCode::SUCCESS
                }
                Err(error) => {
                    eprintln!("thor-admit: {error}");
                    ExitCode::from(1)
                }
            }
        }
        "remove" => {
            let Some(id) = rest.first().and_then(|text| text.parse::<u64>().ok()) else {
                eprintln!("thor-admit: presence remove needs a job id");
                return ExitCode::from(2);
            };
            let mut connection = match Client::connect(&socket) {
                Ok(connection) => connection,
                Err(error) => {
                    eprintln!("thor-admit: cannot reach the daemon: {error}");
                    return ExitCode::from(1);
                }
            };
            match connection.presence_remove(id) {
                Ok(_) => {
                    println!("thor-admit: removed #{id}");
                    ExitCode::SUCCESS
                }
                Err(error) => {
                    eprintln!("thor-admit: {error}");
                    ExitCode::from(1)
                }
            }
        }
        "list" => {
            let jobs = match Client::connect(&socket) {
                Ok(mut connection) => match connection.presence_list() {
                    Ok(jobs) => jobs,
                    Err(error) => {
                        eprintln!("thor-admit: cannot ask the daemon: {error}");
                        return ExitCode::from(1);
                    }
                },
                Err(_) => {
                    // The daemon is not running: the queue is a file, so it
                    // can still be read.
                    let path = match options.get("presence-file") {
                        Some(path) => PathBuf::from(path),
                        None => Config::default().presence_file,
                    };
                    let queue = thor_admit::presence::PresenceStore::new(&path).load();
                    return print_presence_jobs(&queue.jobs().iter().map(|job| {
                        thor_admit::protocol::PresenceReport {
                            id: job.spec.id,
                            label: job.spec.label.clone(),
                            tier: job.spec.tier,
                            peak_bytes: job.spec.peak_bytes,
                            resumable: job.spec.resumable,
                            enabled: job.spec.enabled,
                            state: job.state.as_str().to_string(),
                            command: job.spec.command.join(" "),
                            pgid: 0,
                            age_s: 0.0,
                            current_rss_bytes: 0,
                            attempts: job.attempts,
                            preemptions: job.preemptions,
                            last_exit: job.last_exit,
                        }
                    }).collect::<Vec<_>>(), options.has("json"));
                }
            };
            print_presence_jobs(&jobs, options.has("json"))
        }

        other => {
            eprintln!("thor-admit: presence: unknown action {other:?}");
            eprintln!("thor-admit: the actions are add, list and remove");
            ExitCode::from(2)
        }
    }
}

/// Print the presence queue.
fn print_presence_jobs(jobs: &[thor_admit::protocol::PresenceReport], json: bool) -> ExitCode {
    if json {
        println!(
            "{}",
            client::json_line(&serde_json::json!({"presence": jobs}))
        );
        return ExitCode::SUCCESS;
    }
    if jobs.is_empty() {
        println!("no presence work is registered");
        return ExitCode::SUCCESS;
    }
    for job in jobs {
        let label = if job.enabled {
            job.label.clone()
        } else {
            format!("{} (disabled)", job.label)
        };
        println!(
            "  #{} {:<28} {:<12} peak {:>8}  {:<10}  runs {}  preempted {}  {}",
            job.id,
            label,
            job.tier.as_str(),
            human(job.peak_bytes),
            job.state,
            job.attempts,
            job.preemptions,
            job.command
        );
    }
    ExitCode::SUCCESS
}

/// The ledger: where the box's time went.
fn run_ledger(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    let mut buckets: Vec<Bucket>;
    let mut current: Option<Bucket> = None;
    match Client::connect(&socket) {
        Ok(mut connection) => match connection.ledger() {
            Ok((closed, now)) => {
                buckets = closed;
                current = Some(now);
            }
            Err(error) => {
                eprintln!("thor-admit: cannot ask the daemon: {error}");
                return ExitCode::from(1);
            }
        },
        Err(error) => {
            if !options.has("json") {
                eprintln!(
                    "thor-admit: the daemon is not running on {} ({error}); \
                     showing the closed hours only",
                    socket.display()
                );
            }
            let path = match options.get("ledger") {
                Some(path) => PathBuf::from(path),
                None => Config::default().ledger,
            };
            buckets = thor_admit::ledger::read_buckets(&path);
        }
    }
    if let Some(current) = &current {
        buckets.push(current.clone());
    }
    let hours = match options.number("hours") {
        Ok(Some(value)) => value as usize,
        Ok(None) => 24,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    if buckets.len() > hours {
        buckets = buckets.split_off(buckets.len() - hours);
    }
    if options.has("json") {
        println!(
            "{}",
            client::json_line(&serde_json::json!({"ledger": buckets}))
        );
        return ExitCode::SUCCESS;
    }
    if buckets.is_empty() {
        println!("no hours have been recorded yet");
        return ExitCode::SUCCESS;
    }
    print_ledger_table(&buckets);
    ExitCode::SUCCESS
}

/// The ledger, as a table.
fn print_ledger_table(buckets: &[Bucket]) {
    println!(
        "{:<18} {:>8} {:>9} {:>9} {:>9} {:>9} {:>9} {:>8} {:>7} {:>7}",
        "hour", "window", "live", "prep", "practice", "study", "idle", "unexpl", "gpu W", "gpu %"
    );
    for bucket in buckets {
        let live = bucket.tier(Tier::Live).running_s;
        let preparation = bucket.tier(Tier::Preparation).running_s;
        let practice = bucket.tier(Tier::Practice).running_s;
        let study = bucket.tier(Tier::Study).running_s;
        let power = bucket
            .gpu
            .power_mw_mean
            .map(|milliwatts| format!("{:.1}", milliwatts / 1000.0))
            .unwrap_or_else(|| "-".to_string());
        let busy = bucket
            .gpu
            .busy_pct_mean
            .map(|percent| format!("{percent:.0}"))
            .unwrap_or_else(|| "-".to_string());
        println!(
            "{:<18} {:>7.0}s {:>8.0}s {:>8.0}s {:>8.0}s {:>8.0}s {:>8.0}s {:>7.1}% {:>7} {:>6}%",
            bucket.hour,
            bucket.window_s,
            live,
            preparation,
            practice,
            study,
            bucket.idle.total_s,
            bucket.unattributed_share() * 100.0,
            power,
            busy
        );
    }
    let last = buckets.last().expect("the table has a row");
    if !last.idle.by_reason.is_empty() {
        println!("\nidle, by cause (the last hour, {}):", last.hour);
        for (reason, seconds) in &last.idle.by_reason {
            println!("  {reason:<24} {seconds:>8.0}s");
        }
    }
    let labels: Vec<(&String, &thor_admit::ledger::LabelStat)> = last
        .by_label
        .iter()
        .filter(|(_, stat)| stat.running_s > 0.0 || stat.preempted_s > 0.0)
        .collect();
    if !labels.is_empty() {
        println!("\nby label (the last hour, {}):", last.hour);
        for (label, stat) in labels {
            println!(
                "  {label:<28} ran {:>7.0}s  preempted {:>7.0}s",
                stat.running_s, stat.preempted_s
            );
        }
    }
    if last.flow.samples > 0 {
        println!(
            "\nflow, as published (the last hour, {}): {} samples, confidence min {}, mean {}, \
             sign at the end {}",
            last.hour,
            last.flow.samples,
            last.flow
                .confidence_min
                .map(|value| format!("{value:.2}"))
                .unwrap_or_else(|| "-".to_string()),
            last.flow
                .confidence_mean
                .map(|value| format!("{value:.2}"))
                .unwrap_or_else(|| "-".to_string()),
            last.flow.sign.as_deref().unwrap_or("-"),
        );
    }
}

fn run_stop(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    match client::stop_daemon(&socket) {
        Ok(()) => {
            println!("thor-admit: the daemon was asked to stop");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("thor-admit: {error}");
            ExitCode::from(1)
        }
    }
}

/// `thor-admit reload`: ask a running daemon to re-read what it reads from
/// disk — the peak history and the presence queue.
///
/// Both live in the daemon's memory once loaded, so an edit made by hand
/// (an operator cleaning no-op records out of the history, a night runner
/// rewriting the queue) is invisible to the daemon until it reloads. The
/// alternative is a restart, and a restart waits for a box with no leases.
fn run_reload(args: &[String]) -> ExitCode {
    let options = Options::parse(args);
    let socket = match socket_path(&options) {
        Ok(socket) => socket,
        Err(error) => {
            eprintln!("thor-admit: {error}");
            return ExitCode::from(2);
        }
    };
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("thor-admit: the daemon is not running on {socket:?} ({error})");
            return ExitCode::from(1);
        }
    };
    match connection.reload() {
        Ok((peaks, presence)) => {
            println!(
                "thor-admit: reloaded: {peaks} peak records, {presence} presence jobs"
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("thor-admit: {error}");
            ExitCode::from(1)
        }
    }
}
