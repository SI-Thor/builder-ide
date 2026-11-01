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
use thor_admit::ledger::Bucket;
use thor_admit::protocol::PeakArg;
use thor_admit::sizes::{human, Size};
use thor_admit::tier::Tier;

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
        "presence" => run_presence(&args[1..]),
        "ledger" => run_ledger(&args[1..]),
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

  thor-admit run --peak <size|auto> --label <name> [--tier <tier>] -- <command>
        Take a lease, run the command under it, and give the lease back.

  thor-admit status [--json]
        Show the leases, the free memory, the queue and the presence work.

  thor-admit peaks [--label <name>] [--json]
        Show the learned peaks: the p50 and p95 of each label's history.

  thor-admit presence add --tier <tier> --peak <size|auto> --label <name>
                         [--resumable] -- <command>
        Register work that runs when the box has room for it.
  thor-admit presence list [--json]
        Show the registered work and what it is doing.
  thor-admit presence remove <id>
        Take a job out of the presence queue.

  thor-admit ledger [--json] [--hours <n>]
        Show where the box's time went, by tier, and why it was idle.

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
  --no-presence             do not run the presence queue (default: run it)
  --presence-file <path>    where the presence queue is kept
  --ledger <path>           where the ledger's hours are written
  --ledger-interval-ms <n>  how often the CPU's counters are read (default 1000)
  --gpu-busy-threshold <n>  the GPU's busy share at which live work takes
                            the GPU from the presence queue (default 50)
  --no-gpu-preempt          never stop the presence work for the GPU
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
        config.presence_file = config.state_dir.join("presence.json");
        config.ledger = config.state_dir.join("ledger.jsonl");
    }
    if let Some(value) = options.get("history") {
        config.history = PathBuf::from(value);
    }
    if let Some(value) = options.get("presence-file") {
        config.presence_file = PathBuf::from(value);
    }
    if let Some(value) = options.get("ledger") {
        config.ledger = PathBuf::from(value);
    }
    if options.has("no-presence") {
        config.presence = false;
    }
    if options.has("no-gpu-preempt") {
        config.gpu_preempt = false;
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
        tier,
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
    println!("presence: {}", report.presence.len());
    for job in &report.presence {
        println!(
            "  #{} {:<16} {:<12} peak {:>8}  {:<10}  runs {}  preempted {}",
            job.id,
            job.label,
            job.tier.as_str(),
            human(job.peak_bytes),
            job.state,
            job.attempts,
            job.preemptions
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
            match connection.presence_add(&label, tier, peak, options.has("resumable"), rest.to_vec())
            {
                Ok((id, label, tier)) => {
                    println!("thor-admit: registered #{id} {label:?} as {tier}");
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
        println!(
            "  #{} {:<16} {:<12} peak {:>8}  {:<10}  runs {}  preempted {}  {}",
            job.id,
            job.label,
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
