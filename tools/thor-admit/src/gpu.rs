//! The GPU's view of memory, when the Tegra exposes one.
//!
//! **What the Thor actually exposes** (measured, see `docs/design/thor-admit.md`):
//!
//! * `nvidia-smi --query-gpu=memory.used` answers `N/A` — the Thor's memory is
//!   **unified**, so there is no separate VRAM pool to ask about.
//! * `nvidia-smi --query-compute-apps=pid,used_memory` **does** answer: the
//!   driver's per-process accounting survives the unified memory, so the
//!   daemon can attribute GPU bytes to a lease.
//! * `tegrastats` prints `RAM used/totalMB` and the largest free block
//!   (`lfb`), which is the box's memory seen the way the Tegra's memory
//!   manager sees it — the second opinion, not a separate pool.
//! * `/sys/class/misc/nvmap` exists but carries no counters a user can read.
//!
//! So the GPU probe has two shapes: per-process bytes (`nvidia-smi`) and the
//! box's RAM figure (`tegrastats`). Neither is a second memory pool, and the
//! daemon says so in its status rather than pretending otherwise.

use std::collections::HashMap;
use std::process::Command;

/// Where a GPU figure came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GpuSource {
    /// The NVIDIA driver's per-process accounting.
    Nvidia,
    /// The Tegra's own memory manager, as `tegrastats` prints it.
    Tegrastats,
}

impl GpuSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            GpuSource::Nvidia => "nvidia-smi",
            GpuSource::Tegrastats => "tegrastats",
        }
    }
}

/// One sample of the GPU's view.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GpuSample {
    /// The per-process GPU bytes, when the driver reports them.
    pub per_process: HashMap<i32, u64>,
    /// The box's used RAM as `tegrastats` sees it.
    pub box_used_bytes: Option<u64>,
    pub box_total_bytes: Option<u64>,
    /// The largest free block `tegrastats` reports, in bytes.
    pub largest_free_block: Option<u64>,
    /// The GPU's power draw, in milliwatts.
    ///
    /// `tegrastats` prints `VDD_GPU <now>/<avg>/<max>mW`, which is the
    /// Tegra's own figure for the GPU's rail; the driver prints watts. The
    /// ledger uses this figure, and says which source it came from.
    pub power_mw: Option<u64>,
    /// The GPU's busy share, in per cent.
    ///
    /// This Thor's `tegrastats` prints no 3D busy percentage, so the figure
    /// comes from the driver (`nvidia-smi --query-gpu=utilization.gpu`).
    pub busy_pct: Option<u8>,
    /// Where the power figure came from.
    pub power_source: Option<String>,
}

impl GpuSample {
    /// The GPU bytes of one process.
    pub fn for_pid(&self, pid: i32) -> u64 {
        self.per_process.get(&pid).copied().unwrap_or(0)
    }

    /// The GPU bytes of a set of processes.
    pub fn for_pids(&self, pids: &[i32]) -> u64 {
        pids.iter().map(|pid| self.for_pid(*pid)).sum()
    }
}

/// Which probe the daemon should use.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GpuProbe {
    /// Try `nvidia-smi`, fall back to `tegrastats`.
    Auto,
    /// `nvidia-smi`'s per-process accounting.
    Nvidia,
    /// `tegrastats`' box figure.
    Tegrastats,
    /// No GPU view at all.
    Off,
}

impl GpuProbe {
    pub fn parse(text: &str) -> Option<GpuProbe> {
        match text.trim().to_ascii_lowercase().as_str() {
            "auto" => Some(GpuProbe::Auto),
            "nvidia" | "nvidia-smi" => Some(GpuProbe::Nvidia),
            "tegrastats" => Some(GpuProbe::Tegrastats),
            "off" | "none" => Some(GpuProbe::Off),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            GpuProbe::Auto => "auto",
            GpuProbe::Nvidia => "nvidia-smi",
            GpuProbe::Tegrastats => "tegrastats",
            GpuProbe::Off => "off",
        }
    }
}

/// Parse the `nvidia-smi --query-compute-apps=pid,used_memory` output.
///
/// The driver prints one `pid, used MiB` row per process that has a GPU
/// context; a process with no context is simply not in the list.
pub fn parse_compute_apps(text: &str) -> HashMap<i32, u64> {
    let mut per_process = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Some((pid_text, memory_text)) = line.split_once(',') else {
            continue;
        };
        let Ok(pid) = pid_text.trim().parse::<i32>() else {
            continue;
        };
        let memory_text = memory_text.trim();
        // The driver may print "1896 MiB" or "1896" depending on the format.
        let number: f64 = match memory_text.split_whitespace().next() {
            Some(first) => match first.parse::<f64>() {
                Ok(value) => value,
                Err(_) => continue,
            },
            None => continue,
        };
        if !number.is_finite() || number < 0.0 {
            continue;
        }
        per_process.insert(pid, (number * 1024.0 * 1024.0).round() as u64);
    }
    per_process
}

/// Parse one `tegrastats` line.
///
/// A line looks like:
/// `10-31-2026 13:38:50 RAM 13993/125749MB (lfb 7x4MB) CPU [...] ...`
pub fn parse_tegrastats_line(line: &str) -> Option<GpuSample> {
    let mut sample = GpuSample::default();
    let ram = line.find("RAM ")? + 4;
    let rest = &line[ram..];
    let (used, total) = rest.split_once('/')?;
    let used: u64 = used.trim().parse().ok()?;
    let total_text = total.split_whitespace().next()?;
    let total_text = total_text.trim_end_matches("MB");
    let total: u64 = total_text.parse().ok()?;
    sample.box_used_bytes = Some(used * 1024 * 1024);
    sample.box_total_bytes = Some(total * 1024 * 1024);

    if let Some(start) = line.find("(lfb ") {
        let rest = &line[start + 5..];
        let (count, block) = rest.split_once('x')?;
        let count: u64 = count.trim().parse().ok()?;
        // The block is written "4MB)" — take the token and strip the suffix.
        let block_text = block.split_whitespace().next().unwrap_or("");
        let block_text = block_text.trim_end_matches([')', 'B', 'M']);
        let block: u64 = block_text.parse().ok()?;
        sample.largest_free_block = Some(count * block * 1024 * 1024);
    }

    // The GPU's own rail: "VDD_GPU 23616mW/23616mW/23616mW" — now, average,
    // maximum. The first number is the one that is happening now.
    if let Some(start) = line.find("VDD_GPU ") {
        let rest = &line[start + 8..];
        let first = rest.split('/').next().unwrap_or("").trim();
        let milliwatts: u64 = first.trim_end_matches("mW").trim().parse().ok()?;
        sample.power_mw = Some(milliwatts);
        sample.power_source = Some("tegrastats".to_string());
    }
    Some(sample)
}

/// Parse one line of `nvidia-smi --query-gpu=utilization.gpu,power.draw`.
///
/// The driver prints `98 %, 23.62 W` — the busy share first, then the power.
pub fn parse_nvidia_gpu_line(line: &str) -> Option<GpuSample> {
    let line = line.trim();
    if line.is_empty() {
        return None;
    }
    let mut sample = GpuSample::default();
    for part in line.split(',') {
        let part = part.trim();
        if let Some(number) = part.strip_suffix('%') {
            if let Ok(busy) = number.trim().parse::<f64>() {
                sample.busy_pct = Some(busy.clamp(0.0, 100.0) as u8);
            }
        } else if let Some(number) = part.strip_suffix("W") {
            if let Ok(watts) = number.trim().parse::<f64>() {
                if watts.is_finite() && watts >= 0.0 {
                    sample.power_mw = Some((watts * 1000.0).round() as u64);
                    sample.power_source = Some("nvidia-smi".to_string());
                }
            }
        }
    }
    if sample.busy_pct.is_none() && sample.power_mw.is_none() {
        return None;
    }
    Some(sample)
}

/// Ask `nvidia-smi` for the GPU bytes of every process that has a context.
pub fn query_nvidia_processes() -> Option<HashMap<i32, u64>> {
    let output = Command::new("nvidia-smi")
        .args([
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    Some(parse_compute_apps(&text))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_drivers_per_process_accounting() {
        let text = "9961, 1896 MiB\n10234, 512 MiB\n";
        let per_process = parse_compute_apps(text);
        assert_eq!(per_process.get(&9961), Some(&(1896 * 1024 * 1024)));
        assert_eq!(per_process.get(&10234), Some(&(512 * 1024 * 1024)));
    }

    #[test]
    fn a_process_with_no_gpu_context_is_simply_absent() {
        let per_process = parse_compute_apps("");
        assert!(per_process.is_empty());
    }

    #[test]
    fn a_row_that_is_not_a_pair_is_skipped() {
        let per_process = parse_compute_apps("no processes found\n");
        assert!(per_process.is_empty());
    }

    #[test]
    fn reads_the_tegrastats_ram_figure() {
        let line = "10-31-2026 13:38:50 RAM 13993/125749MB (lfb 7x4MB) CPU [19%@972,26%@972] cpu@48.593C/48.593C tj@48.593C/48.593C VDD_GPU 7872mW/7872mW/7872mW";
        let sample = parse_tegrastats_line(line).unwrap();
        assert_eq!(sample.box_used_bytes, Some(13993 * 1024 * 1024));
        assert_eq!(sample.box_total_bytes, Some(125749 * 1024 * 1024));
        assert_eq!(sample.largest_free_block, Some(7 * 4 * 1024 * 1024));
    }

    #[test]
    fn reads_the_gpus_own_rail_out_of_tegrastats() {
        let line = "10-31-2026 21:03:11 RAM 49013/125749MB (lfb 184x4MB) CPU [10%@1512] cpu@52.156C/52.156C tj@53.531C/53.531C soc012@52.843C/52.843C gpu@53.531C/53.531C soc345@52.906C/52.906C VDD_GPU 23616mW/23616mW/23616mW VDD_CPU_SOC_MSS 10627mW/10627mW/10627mW";
        let sample = parse_tegrastats_line(line).unwrap();
        assert_eq!(sample.power_mw, Some(23616));
        assert_eq!(sample.power_source.as_deref(), Some("tegrastats"));
    }

    #[test]
    fn reads_the_drivers_busy_share_and_power() {
        let sample = parse_nvidia_gpu_line("98 %, 23.62 W").unwrap();
        assert_eq!(sample.busy_pct, Some(98));
        assert_eq!(sample.power_mw, Some(23620));
        assert_eq!(sample.power_source.as_deref(), Some("nvidia-smi"));
    }

    #[test]
    fn a_line_that_is_not_a_gpu_reading_is_not_a_sample() {
        assert!(parse_nvidia_gpu_line("").is_none());
        assert!(parse_nvidia_gpu_line("No devices were found").is_none());
    }

    #[test]
    fn a_line_without_ram_is_not_a_sample() {
        assert!(parse_tegrastats_line("10-31-2026 13:38:50 CPU [19%@972]").is_none());
    }

    #[test]
    fn the_probe_is_named_by_its_argument() {
        assert_eq!(GpuProbe::parse("auto"), Some(GpuProbe::Auto));
        assert_eq!(GpuProbe::parse("nvidia"), Some(GpuProbe::Nvidia));
        assert_eq!(GpuProbe::parse("tegrastats"), Some(GpuProbe::Tegrastats));
        assert_eq!(GpuProbe::parse("off"), Some(GpuProbe::Off));
        assert_eq!(GpuProbe::parse("vulkan"), None);
    }

    #[test]
    fn the_sum_over_pids_is_the_lease_total() {
        let mut sample = GpuSample::default();
        sample.per_process.insert(10, 100);
        sample.per_process.insert(11, 50);
        assert_eq!(sample.for_pids(&[10, 11, 12]), 150);
    }
}
