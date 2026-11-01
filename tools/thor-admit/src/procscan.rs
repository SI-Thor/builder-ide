//! What the box's processes are using, read from `/proc`.
//!
//! The daemon samples the resident set of the processes in a lease so that it
//! can (a) rank leases by size when the box runs short, and (b) record the
//! peak a lease actually reached.
//!
//! `/proc/<pid>/stat` is read rather than `/proc/<pid>/status` because it is
//! one short line instead of fifty; the exact high-water mark comes from
//! `/proc/<pid>/status`'s `VmHWM` for the lease's own process.

use std::collections::HashMap;

/// One process, as the kernel sees it.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ProcInfo {
    pub pid: i32,
    pub ppid: i32,
    /// The process group.
    pub pgrp: i32,
    /// The resident set, in bytes.
    pub rss_bytes: u64,
    /// The kernel's own high-water mark for this process, in bytes.
    pub hwm_bytes: Option<u64>,
}

/// Parse one `/proc/<pid>/stat` line.
///
/// The second field is the command in parentheses and may itself contain
/// spaces and parentheses, so the fields after it are found by splitting on
/// the **last** `)`.
pub fn parse_stat_line(line: &str) -> Option<ProcInfo> {
    let close = line.rfind(')')?;
    let head = &line[..close];
    let pid: i32 = head.split_whitespace().next()?.parse().ok()?;
    let rest = &line[close + 1..];
    let fields: Vec<&str> = rest.split_whitespace().collect();
    // After the command, the fields start at the state: index 0 is state,
    // 1 ppid, 2 pgrp, ... 21 rss (in pages).
    if fields.len() < 22 {
        return None;
    }
    let ppid = fields[1].parse().ok()?;
    let pgrp = fields[2].parse().ok()?;
    let rss_pages: u64 = fields[21].parse().ok()?;
    Some(ProcInfo {
        pid,
        ppid,
        pgrp,
        rss_bytes: rss_pages * 4096,
        hwm_bytes: None,
    })
}

/// Read `/proc/<pid>/status`'s `VmHWM`, the kernel's peak RSS for the process.
pub fn read_hwm(pid: i32) -> Option<u64> {
    let text = std::fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("VmHWM:") {
            let kb: u64 = rest.split_whitespace().next()?.parse().ok()?;
            return Some(kb * 1024);
        }
    }
    None
}

/// Every process the kernel is listing.
pub fn scan() -> HashMap<i32, ProcInfo> {
    let mut out = HashMap::new();
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return out;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(pid_text) = name.to_str() else {
            continue;
        };
        let Ok(pid) = pid_text.parse::<i32>() else {
            continue;
        };
        let Ok(text) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else {
            continue;
        };
        let Some(mut info) = parse_stat_line(text.trim_end()) else {
            continue;
        };
        if pid == std::process::id() as i32 {
            info.hwm_bytes = read_hwm(pid);
        }
        out.insert(pid, info);
    }
    out
}

/// Which processes belong to a lease.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Target {
    /// A whole process group (what the CLI leases: the command it spawns).
    Group(i32),
    /// One process (what the Python shim leases: the calling process).
    Process(i32),
}

/// The processes of a lease, and their resident set together.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TargetUsage {
    pub pids: Vec<i32>,
    pub rss_bytes: u64,
    pub hwm_bytes: u64,
}

/// The usage of one lease, from a scan of `/proc`.
pub fn usage_for(target: Target, procs: &HashMap<i32, ProcInfo>) -> TargetUsage {
    let mut usage = TargetUsage::default();
    match target {
        Target::Group(pgid) => {
            for (pid, info) in procs {
                if info.pgrp == pgid {
                    usage.pids.push(*pid);
                    usage.rss_bytes += info.rss_bytes;
                    usage.hwm_bytes += info.hwm_bytes.unwrap_or(0);
                }
            }
        }
        Target::Process(pid) => {
            let children: Vec<i32> = procs
                .values()
                .filter(|info| info.ppid == pid)
                .map(|info| info.pid)
                .collect();
            let mut wanted = vec![pid];
            wanted.extend(children);
            for pid in wanted {
                if let Some(info) = procs.get(&pid) {
                    usage.pids.push(pid);
                    usage.rss_bytes += info.rss_bytes;
                    usage.hwm_bytes += info.hwm_bytes.unwrap_or(0);
                }
            }
        }
    }
    usage.pids.sort_unstable();
    usage
}

#[cfg(test)]
mod tests {
    use super::*;

    // A real line from the Thor, taken from /proc/<pid>/stat.
    const REAL: &str = "13996 (cat) R 13991 13991 13991 0 -1 4194304 79 0 0 0 0 0 0 0 20 0 1 0 55961 8192000 384 18446744073709551615 187650207449088 187650207474332 281474807232256 0 0 0 0 0 0 0 0 0 17 11 0 0 0 0 0 187650207578720 187650207580360 187650498203648 281474807237027 281474807237047 281474807237047 281474807238635 0";

    #[test]
    fn reads_pid_parent_group_and_rss() {
        let info = parse_stat_line(REAL).unwrap();
        assert_eq!(info.pid, 13996);
        assert_eq!(info.ppid, 13991);
        assert_eq!(info.pgrp, 13991);
        assert_eq!(info.rss_bytes, 384 * 4096);
    }

    #[test]
    fn a_command_with_spaces_and_parentheses_does_not_confuse_it() {
        let line = "42 (my (weird) cmd) S 7 8 9 0 -1 4194304 1 0 0 0 0 0 0 0 20 0 1 0 100 8192000 512 0 0 0 0";
        let info = parse_stat_line(line).unwrap();
        assert_eq!(info.pid, 42);
        assert_eq!(info.ppid, 7);
        assert_eq!(info.pgrp, 8);
        assert_eq!(info.rss_bytes, 512 * 4096);
    }

    #[test]
    fn a_short_line_is_not_a_process() {
        assert!(parse_stat_line("42 (cat) R 1 2").is_none());
        assert!(parse_stat_line("").is_none());
    }

    #[test]
    fn a_group_lease_collects_its_whole_group() {
        let mut procs = HashMap::new();
        procs.insert(1, ProcInfo { pid: 1, ppid: 0, pgrp: 100, rss_bytes: 10, hwm_bytes: None });
        procs.insert(2, ProcInfo { pid: 2, ppid: 1, pgrp: 100, rss_bytes: 20, hwm_bytes: None });
        procs.insert(3, ProcInfo { pid: 3, ppid: 2, pgrp: 200, rss_bytes: 40, hwm_bytes: None });
        let usage = usage_for(Target::Group(100), &procs);
        assert_eq!(usage.pids, vec![1, 2]);
        assert_eq!(usage.rss_bytes, 30);
    }

    #[test]
    fn a_process_lease_collects_the_process_and_its_children() {
        let mut procs = HashMap::new();
        procs.insert(1, ProcInfo { pid: 1, ppid: 0, pgrp: 100, rss_bytes: 10, hwm_bytes: None });
        procs.insert(2, ProcInfo { pid: 2, ppid: 1, pgrp: 100, rss_bytes: 20, hwm_bytes: None });
        procs.insert(3, ProcInfo { pid: 3, ppid: 2, pgrp: 100, rss_bytes: 40, hwm_bytes: None });
        let usage = usage_for(Target::Process(1), &procs);
        assert_eq!(usage.pids, vec![1, 2]);
        assert_eq!(usage.rss_bytes, 30);
    }

    #[test]
    fn the_scan_sees_this_process() {
        let procs = scan();
        let me = std::process::id() as i32;
        assert!(procs.contains_key(&me), "the scan must see its own process");
    }
}
