//! The guard: what the daemon does about work that is **outside** any lease.
//!
//! **The gap this closes.** The watchdog of §4 only knows about leases. When
//! the box falls below the emergency floor it picks the largest *lease* and
//! terminates it; a process that was never leased is invisible to that rule.
//! The 2026-11-01 incident was exactly that: a JAX run started outside
//! `thor-admit` took **94.5 GB of the box's unified memory in 20 seconds**, and
//! the daemon could neither see it nor act on it. The desktop died first, the
//! Wi-Fi driver next, and the box needed a power cycle.
//!
//! **What the guard is.** A second watchdog path, beside the lease one, that
//! can act on a process no lease owns. It has three parts:
//!
//! * a **candidate** — a process big enough to matter, owned by no lease, and
//!   not on the protection list;
//! * a **protection list** — the things it must never touch, whatever their
//!   size;
//! * a **trigger** — the two shapes of trouble it answers: the box below the
//!   emergency floor, and a runaway taking memory faster than the leases can
//!   explain.
//!
//! **Why a candidate is measured in RSS *and* GPU bytes.** On this box the
//! GPU's memory **is** the system's memory, and the driver's accounting for it
//! is separate from the process's resident set. Measured on 2026-11-01 at
//! 12:50: `llama-server` (pid 15433) held **20 834 MiB** of GPU memory with
//! **615 MiB** of RSS — a ratio of 34 to 1. A ranking by RSS alone would not
//! have seen it, and the incident's 94.5 GB was taken the same way, through
//! the GPU's allocator. So a candidate's size is its resident set **plus** the
//! bytes the driver says it holds.
//!
//! **What it may not do.** It never touches the daemon itself, the desktop,
//! `sshd`, the system's own services, the seat agents, or anything a lease
//! owns — the lease watchdog already knows how to stop that, and knows how to
//! give the memory back. What is left is the work nobody claimed, which is
//! exactly the work the incident was.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use crate::procscan::ProcInfo;

/// A process the guard may act on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    /// The process.
    pub pid: i32,
    /// The process group it belongs to.
    pub pgrp: i32,
    /// The program's name, as it was invoked.
    pub name: String,
    /// The whole command line, for the operator's list to match against.
    pub command: String,
    /// The resident set, in bytes.
    pub rss_bytes: u64,
    /// The bytes the driver says the process holds on the GPU.
    pub gpu_bytes: u64,
}

impl Candidate {
    /// What the process holds of the box: its resident set and its GPU bytes.
    pub fn total_bytes(&self) -> u64 {
        self.rss_bytes.saturating_add(self.gpu_bytes)
    }
}

/// The programs the guard never touches, by name.
///
/// The list is deliberately about *the box's furniture* — the operator's
/// login, the desktop, the system's own services, the seat agents — and
/// deliberately **not** about interpreters. A `python` on this box is the
/// model server (58.9 GiB, pid 74344), the incident's runaway, a seat's
/// script, or a one-liner; a name cannot tell them apart, and protecting the
/// name would blind the guard to the very thing it exists for. The operator's
/// own list (below) is matched against the **command line**, which can.
pub const PROTECTED_NAMES: &[&str] = &[
    // The operator's login: the daemon may be reached over ssh, and a
    // session that dies takes the work with it.
    "sshd",
    "sshd-session",
    "ssh-agent",
    "login",
    "agetty",
    "getty",
    "nvgetty",
    // The greeter and the desktop session.
    "gdm",
    "gdm3",
    "gdm-session-worker",
    "gdm-x-session",
    "gdm-wayland-session",
    "gnome-shell",
    "gnome-session-binary",
    "gnome-session",
    "gnome-software",
    "gnome-keyring-daemon",
    "gnome-settings-daemon",
    "gnome-initial-setup",
    "gnome-terminal-server",
    "xterm",
    "Xorg",
    "Xwayland",
    "weston",
    "sway",
    "waybar",
    // The session's own services.
    "dbus-daemon",
    "dbus-broker",
    "dbus-run-session",
    "pipewire",
    "pipewire-pulse",
    "pulseaudio",
    "wireplumber",
    "ibus-daemon",
    "ibus-x11",
    "at-spi-bus-launcher",
    "at-spi2-registryd",
    "xdg-desktop-portal",
    "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-gnome",
    "gvfsd",
    "gvfsd-fuse",
    "nautilus",
    "tracker-miner-fs",
    // The system's own services.
    "systemd",
    "systemd-logind",
    "systemd-journald",
    "systemd-udevd",
    "systemd-resolved",
    "systemd-oomd",
    "systemd-userdbd",
    "systemd-timesyncd",
    "systemd-hostnamed",
    "NetworkManager",
    "wpa_supplicant",
    "iwd",
    "dhclient",
    "dhcpcd",
    "polkitd",
    "udisksd",
    "upowerd",
    "accounts-daemon",
    "colord",
    "rtkit-daemon",
    "thermald",
    "power-profiles-daemon",
    "switcheroo-control",
    "packagekitd",
    "unattended-upgr",
    "snapd",
    "containerd",
    "dockerd",
    "rsyslogd",
    "cron",
    "CRON",
    "ModemManager",
    "bluetoothd",
    "avahi-daemon",
    "cupsd",
    "plymouthd",
    "lightdm",
    "sddm",
    "xdm",
    "seatd",
    "nvidia-persistenced",
    "nvidia-powerd",
    "tailscaled",
    "rngd",
    "auditd",
    // The seat agents: the builders themselves. Killing one loses a seat's
    // session, which is the project's own work and not the box's furniture —
    // but it is work nobody handed to the daemon either, so the guard leaves
    // it alone.
    "zcode-cli",
    "minimax-code",
    "zcode-node-repl",
    "zcode",
    "mcode",
    "MainThread",
    // The operator's terminal multiplexer: the sessions the seats and the
    // director work in all live under it.
    "tmux",
];

/// Name prefixes the guard never touches.
///
/// The systemd family's own services are all `systemd-*`; the session's
/// helpers are all `gnome-*`; the desktop portals are all
/// `xdg-desktop-portal*`. A prefix catches the whole family, including the
/// members that were installed after this list was written.
pub const PROTECTED_PREFIXES: &[&str] = &[
    "systemd-",
    "gnome-",
    "dbus-",
    "at-spi",
    "ibus-",
    "gvfs",
    "tracker",
    "pipewire",
    "xdg-desktop-portal",
    "NetworkManager-",
    "nvidia-",
    "snapd",
    "avahi-",
    "gdm-",
    "udisksd",
    "fwupd",
    "geoclue",
    "colord",
    "switcheroo",
    "power-profiles",
    "evolution",
    "firefox",
    "chromium",
    "google-chrome",
    "thunderbird",
];

/// Is this program one the guard must never touch?
pub fn protected_by_name(name: &str) -> bool {
    if PROTECTED_NAMES.iter().any(|protected| *protected == name) {
        return true;
    }
    PROTECTED_PREFIXES
        .iter()
        .any(|prefix| name.starts_with(prefix))
}

/// Does a glob pattern match the whole text?
///
/// `*` stands for any run of characters, including none. The pattern's first
/// part must be a prefix of the text, its last part a suffix, and the parts
/// in between must appear in order.
fn glob_matches(pattern: &str, text: &str) -> bool {
    let parts: Vec<&str> = pattern.split('*').collect();
    if parts.len() == 1 {
        return text == pattern;
    }
    // The shortest text the pattern can match: its parts, without the stars.
    let shortest: usize = parts.iter().map(|part| part.len()).sum();
    if text.len() < shortest {
        return false;
    }
    let first = parts[0];
    let last = parts[parts.len() - 1];
    if !text.starts_with(first) || !text.ends_with(last) {
        return false;
    }
    let mut rest = &text[first.len()..text.len() - last.len()];
    for part in &parts[1..parts.len() - 1] {
        match rest.find(part) {
            Some(at) => rest = &rest[at + part.len()..],
            None => return false,
        }
    }
    true
}

/// Does the operator's list protect this command line?
///
/// A line is a pattern. A pattern with a `*` is matched as a glob against the
/// whole command line; a pattern without one is matched as a substring. The
/// list is the operator's escape hatch for the work that is legitimately big
/// and legitimately outside a lease — the model server, the operator's own
/// long-running job — and it is matched against the **command line**, because
/// that is the only thing that can tell one `python` from another.
pub fn operator_protects(command: &str, patterns: &[String]) -> bool {
    patterns.iter().any(|pattern| {
        let pattern = pattern.trim();
        if pattern.is_empty() {
            return false;
        }
        if pattern.contains('*') {
            glob_matches(pattern, command)
        } else {
            command.contains(pattern)
        }
    })
}

/// The operator's list of things the guard must never touch.
///
/// A line is either a **pattern** or a **pid**:
///
/// * a pattern is matched against the whole command line — as a substring,
///   or as a glob when it holds a `*`;
/// * `pid 1234` protects one process, whatever it is called.
///
/// The pid form is what a test needs, and what an operator needs when a
/// single process must be spared: the model server is `python -m
/// glide.server`, and every other python on the box is `python` too. A name
/// cannot tell them apart; a command line can; and a pid can tell one
/// process from every other.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Protection {
    /// The command-line patterns.
    pub patterns: Vec<String>,
    /// The pids.
    pub pids: Vec<i32>,
}

impl Protection {
    /// Is this process spared?
    pub fn spares(&self, pid: i32, command: &str) -> bool {
        self.pids.contains(&pid) || operator_protects(command, &self.patterns)
    }
}

/// Read the operator's protected list.
///
/// A missing file is an empty list: the operator has protected nothing, which
/// is the ordinary case. A line that is empty or starts with `#` is a
/// comment.
pub fn read_protected_list(path: &std::path::Path) -> Protection {
    let mut protection = Protection::default();
    let Ok(text) = std::fs::read_to_string(path) else {
        return protection;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(rest) = line.strip_prefix("pid ") {
            if let Ok(pid) = rest.trim().parse::<i32>() {
                protection.pids.push(pid);
                continue;
            }
        }
        protection.patterns.push(line.to_string());
    }
    protection
}

/// The biggest candidate, or none if there is none.
///
/// The caller has already filtered out the processes that are not candidates
/// (too small, owned by a lease, on the protection list); this is the choice
/// among what is left.
pub fn largest(candidates: &[Candidate]) -> Option<&Candidate> {
    candidates
        .iter()
        .max_by_key(|candidate| candidate.total_bytes())
}

/// One look at the box: what was free, what each process held, and what each
/// lease held.
#[derive(Clone, Debug)]
pub struct Snapshot {
    /// When it was taken.
    pub at: Instant,
    /// The box's free memory, in bytes.
    pub available: u64,
    /// What each process held: its resident set plus its GPU bytes.
    pub totals: HashMap<i32, u64>,
    /// What each lease held, the same way.
    pub leases: HashMap<u64, u64>,
}

/// The guard's short memory of the box.
///
/// The guard answers two questions: "is the box below the floor?" (a
/// snapshot of now is enough) and "is something taking the memory faster than
/// the leases can explain?" (a question about a **window**, which needs the
/// last few looks). The window is kept as a handful of snapshots and pruned
/// to the window's length.
#[derive(Clone, Debug, Default)]
pub struct History {
    samples: Vec<Snapshot>,
}

impl History {
    /// A history with nothing in it yet.
    pub fn new() -> History {
        History { samples: Vec::new() }
    }

    /// Take a look, and forget the looks older than the window.
    pub fn push(&mut self, snapshot: Snapshot, window: Duration) {
        self.samples.push(snapshot);
        let cutoff = Instant::now() - window;
        self.samples.retain(|sample| sample.at >= cutoff);
    }

    /// The oldest look still inside the window, if the window is full enough
    /// to mean anything.
    pub fn oldest(&self) -> Option<&Snapshot> {
        self.samples.first()
    }

    /// The newest look.
    pub fn newest(&self) -> Option<&Snapshot> {
        self.samples.last()
    }

    /// How much the box lost between the oldest and the newest look.
    pub fn lost_bytes(&self) -> u64 {
        match (self.oldest(), self.newest()) {
            (Some(oldest), Some(newest)) => oldest.available.saturating_sub(newest.available),
            _ => 0,
        }
    }

    /// How much the box lost, and over how long.
    pub fn loss(&self) -> (u64, Duration) {
        match (self.oldest(), self.newest()) {
            (Some(oldest), Some(newest)) => (
                oldest.available.saturating_sub(newest.available),
                newest.at.saturating_duration_since(oldest.at),
            ),
            _ => (0, Duration::ZERO),
        }
    }

    /// How much a process grew between the oldest and the newest look.
    pub fn growth(&self, pid: i32) -> u64 {
        match (self.oldest(), self.newest()) {
            (Some(oldest), Some(newest)) => {
                let before = oldest.totals.get(&pid).copied().unwrap_or(0);
                let after = newest.totals.get(&pid).copied().unwrap_or(0);
                after.saturating_sub(before)
            }
            _ => 0,
        }
    }

    /// How much the leases grew between the oldest and the newest look.
    pub fn lease_growth(&self) -> u64 {
        match (self.oldest(), self.newest()) {
            (Some(oldest), Some(newest)) => oldest
                .leases
                .iter()
                .map(|(id, before)| {
                    let after = newest.leases.get(id).copied().unwrap_or(0);
                    after.saturating_sub(*before)
                })
                .sum(),
            _ => 0,
        }
    }
}

/// The processes a process started: its children, and their children.
///
/// A runaway does not hold the memory by itself. A job that forks a
/// dataloader, or a renderer that forks workers, holds it in several
/// processes, and stopping only the parent leaves the children holding the
/// pages the parent was holding. So the guard signals the children too.
///
/// The family is built from the kernel's own parent links, not from the
/// process group: a process group may also hold the operator's shell, and a
/// group is not a family.
pub fn descendants(procs: &HashMap<i32, ProcInfo>, pid: i32) -> Vec<i32> {
    let mut out = Vec::new();
    let mut seen: HashSet<i32> = HashSet::from([pid]);
    let mut frontier = vec![pid];
    while let Some(current) = frontier.pop() {
        for (child, info) in procs {
            if info.ppid == current && seen.insert(*child) {
                out.push(*child);
                frontier.push(*child);
            }
        }
    }
    out
}

/// Is a process group exactly the family of one process?
///
/// The group is safe to signal as a whole when every other member of it is
/// a descendant of the candidate: then the group **is** the job, and the
/// job's children go with it. When the group holds anything else — the
/// operator's shell, say — the group is not signalled, and the family is
/// signalled process by process instead.
pub fn group_is_family(
    procs: &HashMap<i32, ProcInfo>,
    candidate: &Candidate,
) -> bool {
    let family = descendants(procs, candidate.pid);
    procs
        .values()
        .filter(|info| info.pgrp == candidate.pgrp && info.pid != candidate.pid)
        .all(|info| family.contains(&info.pid))
}

/// The pids a lease owns: the processes of its target, and the children of a
/// process target.
///
/// A lease's memory is the daemon's business. The guard must never take it:
/// the lease watchdog knows how to stop that work, how to wait for it, and how
/// to give the memory back to the accounting.
pub fn lease_pids(
    targets: &[(crate::protocol::TargetSpec, Vec<i32>)],
) -> HashSet<i32> {
    let mut pids = HashSet::new();
    for (_, owned) in targets {
        pids.extend(owned.iter().copied());
    }
    pids
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::TargetSpec;

    fn candidate(pid: i32, name: &str, rss: u64, gpu: u64) -> Candidate {
        Candidate {
            pid,
            pgrp: pid,
            name: name.to_string(),
            command: name.to_string(),
            rss_bytes: rss,
            gpu_bytes: gpu,
        }
    }

    #[test]
    fn a_candidate_is_as_big_as_its_memory_and_its_gpu_bytes() {
        let c = candidate(1, "python", 615 * 1024 * 1024, 20_834 * 1024 * 1024);
        assert_eq!(c.total_bytes(), (615 + 20_834) * 1024 * 1024);
    }

    #[test]
    fn the_desktop_and_the_login_are_never_touched() {
        for name in [
            "gnome-shell",
            "gnome-software",
            "gdm-session-worker",
            "gdm3",
            "sshd",
            "sshd-session",
            "dbus-daemon",
            "pipewire",
            "systemd",
            "systemd-logind",
            "gnome-session-binary",
            "xdg-desktop-portal-gtk",
            "NetworkManager",
        ] {
            assert!(protected_by_name(name), "{name} must be protected");
        }
    }

    #[test]
    fn the_seat_agents_are_never_touched() {
        for name in ["zcode-cli", "minimax-code", "zcode-node-repl", "MainThread"] {
            assert!(protected_by_name(name), "{name} must be protected");
        }
    }

    #[test]
    fn an_interpreter_is_not_protected() {
        // The incident's runaway was a python; protecting the name would
        // blind the guard to the thing it exists for.
        for name in ["python", "python3", "java", "node", "llama-server", "bash"] {
            assert!(!protected_by_name(name), "{name} must not be protected");
        }
    }

    #[test]
    fn the_operator_list_matches_a_command_line() {
        let patterns = vec!["*glide*".to_string(), "llama-server".to_string()];
        assert!(operator_protects(
            "/home/casey/.venv/bin/python -m glide.server",
            &patterns
        ));
        assert!(operator_protects("/usr/bin/llama-server -m qwen", &patterns));
        assert!(!operator_protects("/usr/bin/python train.py", &patterns));
    }

    #[test]
    fn a_glob_matches_the_ends_and_the_middle() {
        let patterns = vec!["*/python -m glide.*".to_string()];
        assert!(operator_protects(
            "/home/casey/.venv/bin/python -m glide.server",
            &patterns
        ));
        // The middle is what the pattern names, so another module does not
        // match it.
        assert!(!operator_protects(
            "/home/casey/.venv/bin/python -m jax.train",
            &patterns
        ));
        // And the head is a head: the text has to start the way the pattern
        // says.
        assert!(!operator_protects("python -m glide.server", &patterns));
    }

    #[test]
    fn the_largest_candidate_wins() {
        let candidates = vec![
            candidate(1, "python", 2 * 1024 * 1024 * 1024, 0),
            candidate(2, "python", 600 * 1024 * 1024, 20 * 1024 * 1024 * 1024),
            candidate(3, "python", 4 * 1024 * 1024 * 1024, 0),
        ];
        assert_eq!(largest(&candidates).unwrap().pid, 2);
    }

    #[test]
    fn the_protected_list_reads_patterns_and_pids() {
        let directory = std::env::temp_dir().join(format!("thor-admit-protected-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("protected.txt");
        std::fs::write(
            &path,
            "# the operator's list\n*glide*\npid 4321\nllama-server\n",
        )
        .unwrap();
        let protection = read_protected_list(&path);
        assert_eq!(protection.patterns, vec!["*glide*", "llama-server"]);
        assert_eq!(protection.pids, vec![4321]);
        // A pid is spared whatever it is called.
        assert!(protection.spares(4321, "python train.py"));
        // And a pattern is matched against the command line.
        assert!(protection.spares(99, "python -m glide.server"));
        assert!(!protection.spares(99, "python train.py"));
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn a_missing_protected_list_protects_nothing() {
        let protection = read_protected_list(std::path::Path::new("/nonexistent/protected.txt"));
        assert!(protection.patterns.is_empty());
        assert!(protection.pids.is_empty());
        assert!(!protection.spares(1, "python train.py"));
    }

    #[test]
    fn a_lease_owns_its_processes() {        let owned = lease_pids(&[
            (TargetSpec::Group { pgid: 7 }, vec![7, 8]),
            (TargetSpec::Process { pid: 9 }, vec![9]),
        ]);
        assert!(owned.contains(&7));
        assert!(owned.contains(&8));
        assert!(owned.contains(&9));
        assert!(!owned.contains(&10));
    }

    #[test]
    fn a_family_is_the_processes_a_process_started() {
        let mut procs: HashMap<i32, ProcInfo> = HashMap::new();
        for (pid, ppid, pgrp) in [(1, 0, 1), (10, 1, 10), (11, 10, 10), (12, 11, 10), (20, 1, 20)] {
            procs.insert(
                pid,
                ProcInfo {
                    pid,
                    ppid,
                    pgrp,
                    rss_bytes: 0,
                    hwm_bytes: None,
                },
            );
        }
        let family = descendants(&procs, 10);
        assert_eq!(family.len(), 2, "the child and the grandchild: {family:?}");
        assert!(family.contains(&11) && family.contains(&12));
        assert!(!family.contains(&20), "a sibling is not a descendant");
        // The group 10 is the job and nothing else, so it may be signalled
        // as a whole.
        let candidate = Candidate {
            pid: 10,
            pgrp: 10,
            name: "job".to_string(),
            command: "job".to_string(),
            rss_bytes: 0,
            gpu_bytes: 0,
        };
        assert!(group_is_family(&procs, &candidate));
        // The group 1 holds the whole box, so it is not.
        let shell = Candidate {
            pid: 12,
            pgrp: 1,
            name: "shell".to_string(),
            command: "shell".to_string(),
            rss_bytes: 0,
            gpu_bytes: 0,
        };
        assert!(!group_is_family(&procs, &shell));
    }

    #[test]
    fn the_history_measures_the_loss_over_its_window() {
        let mut history = History::new();
        let start = Instant::now();
        history.push(
            Snapshot {
                at: start,
                available: 100 * 1024 * 1024 * 1024,
                totals: HashMap::from([(1, 1024 * 1024 * 1024)]),
                leases: HashMap::from([(1, 1024 * 1024 * 1024)]),
            },
            Duration::from_secs(10),
        );
        std::thread::sleep(Duration::from_millis(10));
        history.push(
            Snapshot {
                at: Instant::now(),
                available: 60 * 1024 * 1024 * 1024,
                totals: HashMap::from([(1, 21 * 1024 * 1024 * 1024)]),
                leases: HashMap::from([(1, 1024 * 1024 * 1024)]),
            },
            Duration::from_secs(10),
        );
        assert_eq!(history.lost_bytes(), 40 * 1024 * 1024 * 1024);
        assert_eq!(history.growth(1), 20 * 1024 * 1024 * 1024);
        // The lease grew nothing: the loss was nobody's but the process's.
        assert_eq!(history.lease_growth(), 0);
    }
}
