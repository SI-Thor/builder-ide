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
use std::time::Duration;

use thor_admit::client::{self, Client};
use thor_admit::daemon::{Config, Daemon, DEFAULT_EMERGENCY_FLOOR, DEFAULT_FLOOR};
use thor_admit::gpu::GpuProbe;
use thor_admit::history::History;
use thor_admit::protocol::PeakArg;
use thor_admit::sizes::{human, Size};

static STOP: AtomicBool = AtomicBool::new(false);

extern "C" fn on_signal(_signal: libc::c_int) {
    STOP.store(true, Ordering::SeqCst);
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        print_help();
        return ExitCode::from(2);
    }
    let command = args[0].clone();
    match command.as_str() {
        "daemon" => run_daemon(&args[1..]),
        "run" => run_command(&args[1..]),
        "status" => run_status(&args[1..]),
        "peaks" => run_peaks(&args[1..]),
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

  thor-admit run --peak <size|auto> --label <name> [--priority N] -- <command>
        Take a lease, run the command under it, and give the lease back.

  thor-admit status [--json]
        Show the leases, the free memory and the queue.

  thor-admit peaks [--label <name>] [--json] [--state-dir <path>]
        Show the learned peaks: the p50 and p95 of each label's history.

  thor-admit stop
        Ask the running daemon to stop.

Daemon options (all have defaults):
  --floor <size>            the floor a lease must clear      (default 25G)
  --emergency-floor <size>  below this, the watchdog acts     (default 8G)
  --sample-interval-ms <n>  how often the box is sampled      (default 250)
  --scan-interval-ms <n>    how often the processes' memory is read (default 1000)
  --stop-grace-samples <n>  samples before a stopped lease is killed (default 8)
  --min-victim-rss <size>   the smallest lease the watchdog will touch (default 2G)
  --socket <path>           the socket to listen on
  --state-dir <path>        where the lease files and the log live
  --history <path>          where the learned peaks are written
  --meminfo <path>          where the box's memory is read (default /proc/meminfo)
  --gpu-probe <auto|nvidia|tegrastats|off>   the GPU's view (default auto)
  --idle-exit <seconds>     leave after this long with nothing to do (default 900)
  --no-stop-on-client-gone  leave a dead client's command running (default: stop it)
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
    if Client::connect(socket).is_ok() {
        return Ok(());
    }
    let program = std::env::current_exe().map_err(|e| e.to_string())?;
    let state_dir = thor_admit::daemon::default_state_dir();
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
    command.spawn().map_err(|e| format!("cannot start the daemon: {e}"))?;
    for _ in 0..100 {
        std::thread::sleep(Duration::from_millis(100));
        if Client::connect(socket).is_ok() {
            return Ok(());
        }
    }
    Err(format!(
        "the daemon did not come up on {}",
        socket.display()
    ))
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
    if let Some(value) = options.get("socket") {
        config.socket = PathBuf::from(value);
    }
    if let Some(value) = options.get("state-dir") {
        config.state_dir = PathBuf::from(value);
        config.history = config.state_dir.join("peaks.jsonl");
    }
    if let Some(value) = options.get("history") {
        config.history = PathBuf::from(value);
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
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    let daemon = match Daemon::new(config) {
        Ok(daemon) => daemon,
        Err(error) => {
            eprintln!("thor-admit: cannot start the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    // The pid file, so `thor-admit stop` can find it.
    let pid_path = daemon.socket_path().with_extension("pid");
    let _ = std::fs::write(&pid_path, std::process::id().to_string());

    let watcher = {
        let daemon = std::sync::Arc::clone(&daemon);
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(100));
            if STOP.load(Ordering::SeqCst) {
                daemon.stop();
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
    let mut connection = match Client::connect(&socket) {
        Ok(connection) => connection,
        Err(error) => {
            eprintln!("thor-admit: cannot reach the daemon: {error}");
            return ExitCode::from(1);
        }
    };
    let outcome = match client::run_under_lease(
        &mut connection,
        &label,
        peak,
        priority,
        &options.rest,
    ) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("thor-admit: {error}");
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
        "memory: {} free of {} (floor {}, emergency floor {})",
        human(report.mem_available_bytes),
        human(report.mem_total_bytes),
        human(report.floor_bytes),
        human(report.emergency_floor_bytes)
    );
    println!("gpu view: {}", report.gpu_source);
    println!("leases: {}", report.leases.len());
    for lease in &report.leases {
        println!(
            "  #{} {:<16} peak {:>8}  now {:>8}  saw {:>8}  pid {}  {:.0}s",
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
        println!(
            "  {}. {:<16} peak {:>8}  priority {}",
            waiter.position, waiter.label, human(waiter.peak_bytes), waiter.priority
        );
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
