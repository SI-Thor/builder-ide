//! The time ledger: what the box did with its time, and why it was not doing
//! anything.
//!
//! The brief asks for a ledger with three columns of truth:
//!
//! * **Utilisation by tier, per hour.** Every second is booked to the tier it
//!   belonged to: live, preparation, practice or study.
//! * **The GPU's power and busy share**, and **the CPU's share per core.**
//!   The box's time is not only memory: a tier that runs on the GPU is
//!   burning watts, and the ledger says so.
//! * **The share of time the box was idle without a reason.** The point of
//!   the presence scheduler is that the box is never idle when there is
//!   something useful it could be doing, so the idle time has to be broken
//!   down into *causes*, and the time that has no cause is the number to
//!   watch.
//!
//! **How the idle time is classified.** Every sample asks the same question
//! and gets one of these answers:
//!
//! | Reason | What it means |
//! |---|---|
//! | `no_work_registered` | nothing was registered to do, and nothing was asked for |
//! | `waiting_for_memory` | work was ready, but the box had no room for it |
//! | `waiting_for_gpu` | work was ready, but the GPU was busy with higher-priority work |
//! | `preempted_for_live_work` | work was stopped so live work could run |
//! | `unattributed` | the ledger cannot say — this is the number that should be zero |
//!
//! `no_work_registered` is a *cause* but not a good one: it is the presence
//! gap, the work nobody has put in the queue. It is reported on its own so
//! that "the ledger explains everything" and "the box had nothing to do" are
//! two different sentences.

use std::collections::BTreeMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::clock;
use crate::tier::Tier;

/// Why the box was idle.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdleReason {
    /// Nothing was registered to do, and nothing was asked for.
    NoWorkRegistered,
    /// Work was ready, but the box had no room for it.
    WaitingForMemory,
    /// Work was ready, but the GPU was busy with higher-priority work.
    WaitingForGpu,
    /// Work was stopped so live work could run.
    PreemptedForLiveWork,
    /// A lease was granted — the memory was committed — but the client
    /// never held it, so no work ran. Booked as its own cause so a phantom
    /// lease is neither "running" (it never ran) nor "unattributed" (the
    /// ledger knows exactly why the box looked empty while its memory was
    /// spoken for).
    GrantedNotRun,
    /// The ledger cannot say why.
    Unattributed,
}

impl IdleReason {
    pub fn as_str(&self) -> &'static str {
        match self {
            IdleReason::NoWorkRegistered => "no_work_registered",
            IdleReason::WaitingForMemory => "waiting_for_memory",
            IdleReason::WaitingForGpu => "waiting_for_gpu",
            IdleReason::PreemptedForLiveWork => "preempted_for_live_work",
            IdleReason::GrantedNotRun => "granted_not_run",
            IdleReason::Unattributed => "unattributed",
        }
    }
}

/// What one sample of the box says.
#[derive(Clone, Debug, Default)]
pub struct Sample {
    /// The tiers with work running right now.
    pub running_tiers: Vec<Tier>,
    /// The tiers with work stopped by a pre-emption right now.
    pub preempted_tiers: Vec<Tier>,
    /// Why the box is idle. `None` means something is running.
    pub idle: Option<IdleReason>,
    /// `MemAvailable`, in bytes.
    pub mem_available: u64,
    /// The GPU's power draw, in milliwatts.
    pub gpu_power_mw: Option<u64>,
    /// The GPU's busy share, in per cent.
    pub gpu_busy_pct: Option<u8>,
    /// Where the GPU's power figure came from.
    pub gpu_power_source: Option<String>,
}

/// What one tier did in an hour.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct TierStat {
    /// Seconds in which work of this tier was running.
    pub running_s: f64,
    /// How many jobs of this tier were started.
    pub runs: u64,
    /// How many times live work pre-empted this tier.
    pub preemptions: u64,
    /// Seconds in which this tier's work was stopped by a pre-emption.
    pub preempted_s: f64,
}

/// The GPU's hour.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct GpuStat {
    /// The mean power draw, in milliwatts.
    pub power_mw_mean: Option<f64>,
    /// The highest power draw seen, in milliwatts.
    pub power_mw_max: Option<u64>,
    /// How many samples the power figure came from.
    pub power_samples: u64,
    /// The mean busy share, in per cent.
    pub busy_pct_mean: Option<f64>,
    /// How many samples the busy share came from.
    pub busy_samples: u64,
    /// Where the figures came from.
    pub source: Option<String>,
}

/// The CPU's hour.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CpuStat {
    /// How many cores the box has.
    pub cores: usize,
    /// The mean busy share of the whole box, 0 to 1.
    pub busy_share_mean: Option<f64>,
    /// The busy share of each core at the end of the window, 0 to 1.
    pub per_core_busy_share: Vec<f64>,
    /// How many samples the share came from.
    pub samples: u64,
}

/// The idle hour.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct IdleStat {
    /// Seconds the box was idle.
    pub total_s: f64,
    /// The idle seconds, by cause.
    pub by_reason: BTreeMap<String, f64>,
    /// Idle seconds with no cause the ledger could name.
    pub unattributed_s: f64,
    /// Idle seconds because nothing was registered to do.
    pub no_work_s: f64,
}

/// The memory hour.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct MemStat {
    /// The least free memory seen, in bytes.
    pub available_min: Option<u64>,
    /// The most free memory seen, in bytes.
    pub available_max: Option<u64>,
    /// The sum of the free memory seen, in bytes (the mean is this over the
    /// sample count).
    pub available_sum: u64,
    /// How many samples it came from.
    pub samples: u64,
}

/// One hour of the box's time.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Bucket {
    /// The hour this bucket covers, as `2026-10-31T21`.
    pub hour: String,
    /// When the bucket opened.
    pub started_at: String,
    /// How long the bucket covered, in seconds.
    pub window_s: f64,
    /// What each tier did.
    pub tiers: BTreeMap<String, TierStat>,
    /// The GPU's hour.
    pub gpu: GpuStat,
    /// The CPU's hour.
    pub cpu: CpuStat,
    /// The idle hour.
    pub idle: IdleStat,
    /// The memory hour.
    pub memory: MemStat,
    /// How many samples the bucket holds.
    pub samples: u64,
}

impl Bucket {
    /// A new, empty bucket for an hour.
    pub fn new(hour: &str) -> Bucket {
        let mut tiers = BTreeMap::new();
        for tier in Tier::all() {
            tiers.insert(tier.as_str().to_string(), TierStat::default());
        }
        Bucket {
            hour: hour.to_string(),
            started_at: clock::rfc3339_now(),
            window_s: 0.0,
            tiers,
            ..Bucket::default()
        }
    }

    /// The stat for one tier.
    pub fn tier(&self, tier: Tier) -> TierStat {
        self.tiers.get(tier.as_str()).cloned().unwrap_or_default()
    }

    /// The share of the window the box was idle, 0 to 1.
    pub fn idle_share(&self) -> f64 {
        if self.window_s <= 0.0 {
            return 0.0;
        }
        self.idle.total_s / self.window_s
    }

    /// The share of the window that was idle with no cause the ledger could
    /// name, 0 to 1.
    pub fn unattributed_share(&self) -> f64 {
        if self.window_s <= 0.0 {
            return 0.0;
        }
        self.idle.unattributed_s / self.window_s
    }

    /// The share of the window that was idle because nothing was registered,
    /// 0 to 1.
    pub fn no_work_share(&self) -> f64 {
        if self.window_s <= 0.0 {
            return 0.0;
        }
        self.idle.no_work_s / self.window_s
    }
}

/// The ledger: the current hour, and the file the closed hours are written to.
#[derive(Debug)]
pub struct Ledger {
    path: PathBuf,
    bucket: Bucket,
    cpu_previous: Option<CpuCounters>,
    cpu_busy_sum: f64,
    cpu_share_samples: u64,
}

impl Ledger {
    /// A ledger that writes its closed hours to `path`.
    pub fn new(path: &Path) -> Ledger {
        let hour = clock::hour_key(clock::unix_seconds());
        Ledger {
            path: path.to_path_buf(),
            bucket: Bucket::new(&hour),
            cpu_previous: None,
            cpu_busy_sum: 0.0,
            cpu_share_samples: 0,
        }
    }

    /// The path the closed hours are written to.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The hour being kept right now.
    pub fn bucket(&self) -> &Bucket {
        &self.bucket
    }

    /// The closed hours, read back from the file.
    pub fn closed_buckets(&self) -> Vec<Bucket> {
        read_buckets(&self.path)
    }

    /// Fold one sample of the box into the ledger.
    pub fn sample(&mut self, dt: f64, sample: &Sample) {
        self.bucket.window_s += dt;
        self.bucket.samples += 1;

        for tier in &sample.running_tiers {
            let stat = self
                .bucket
                .tiers
                .entry(tier.as_str().to_string())
                .or_default();
            stat.running_s += dt;
        }
        for tier in &sample.preempted_tiers {
            let stat = self
                .bucket
                .tiers
                .entry(tier.as_str().to_string())
                .or_default();
            stat.preempted_s += dt;
        }

        if sample.running_tiers.is_empty() {
            let reason = sample.idle.unwrap_or(IdleReason::Unattributed);
            self.bucket.idle.total_s += dt;
            *self
                .bucket
                .idle
                .by_reason
                .entry(reason.as_str().to_string())
                .or_insert(0.0) += dt;
            if reason == IdleReason::Unattributed {
                self.bucket.idle.unattributed_s += dt;
            }
            if reason == IdleReason::NoWorkRegistered {
                self.bucket.idle.no_work_s += dt;
            }
        }

        if let Some(power) = sample.gpu_power_mw {
            self.bucket.gpu.power_mw_mean = Some(match self.bucket.gpu.power_mw_mean {
                Some(mean) => {
                    // The running mean, so the bucket does not need the sum.
                    let count = self.bucket.gpu.power_samples as f64;
                    (mean * count + power as f64) / (count + 1.0)
                }
                None => power as f64,
            });
            self.bucket.gpu.power_mw_max = Some(
                self.bucket.gpu
                    .power_mw_max
                    .map(|max| max.max(power))
                    .unwrap_or(power),
            );
            self.bucket.gpu.power_samples += 1;
            if let Some(source) = &sample.gpu_power_source {
                self.bucket.gpu.source = Some(source.clone());
            }
        }
        if let Some(busy) = sample.gpu_busy_pct {
            self.bucket.gpu.busy_pct_mean = Some(match self.bucket.gpu.busy_pct_mean {
                Some(mean) => {
                    let count = self.bucket.gpu.busy_samples as f64;
                    (mean * count + busy as f64) / (count + 1.0)
                }
                None => busy as f64,
            });
            self.bucket.gpu.busy_samples += 1;
        }

        if sample.mem_available > 0 {
            self.bucket.memory.available_min = Some(
                self.bucket
                    .memory
                    .available_min
                    .map(|min| min.min(sample.mem_available))
                    .unwrap_or(sample.mem_available),
            );
            self.bucket.memory.available_max = Some(
                self.bucket
                    .memory
                    .available_max
                    .map(|max| max.max(sample.mem_available))
                    .unwrap_or(sample.mem_available),
            );
            self.bucket.memory.available_sum += sample.mem_available;
            self.bucket.memory.samples += 1;
        }
    }

    /// Note that a job of a tier was started.
    pub fn note_run(&mut self, tier: Tier) {
        let stat = self
            .bucket
            .tiers
            .entry(tier.as_str().to_string())
            .or_default();
        stat.runs += 1;
    }

    /// Note that live work pre-empted a tier.
    pub fn note_preemption(&mut self, tier: Tier) {
        let stat = self
            .bucket
            .tiers
            .entry(tier.as_str().to_string())
            .or_default();
        stat.preemptions += 1;
    }

    /// Fold the CPU's counters in, and work out the busy share.
    pub fn note_cpu(&mut self, counters: &CpuCounters) {
        if let Some(previous) = &self.cpu_previous {
            let shares = counters.busy_shares_since(previous);
            if !shares.is_empty() {
                let mean = shares.iter().sum::<f64>() / shares.len() as f64;
                self.cpu_busy_sum += mean;
                self.cpu_share_samples += 1;
                self.bucket.cpu.per_core_busy_share = shares;
                self.bucket.cpu.busy_share_mean = Some(self.cpu_busy_sum / self.cpu_share_samples as f64);
                self.bucket.cpu.samples = self.cpu_share_samples;
            }
        }
        self.bucket.cpu.cores = counters.per_core.len();
        self.cpu_previous = Some(counters.clone());
    }

    /// Close the hour if the wall clock has moved on, and open the next one.
    pub fn roll(&mut self) {
        let hour = clock::hour_key(clock::unix_seconds());
        if hour == self.bucket.hour {
            return;
        }
        self.close_bucket();
    }

    /// Write the bucket out and start a new one.
    pub fn close_bucket(&mut self) {
        let hour = clock::hour_key(clock::unix_seconds());
        let finished = std::mem::replace(&mut self.bucket, Bucket::new(&hour));
        if let Err(error) = append_bucket(&self.path, &finished) {
            eprintln!(
                "thor-admit: cannot write the ledger at {}: {error}",
                self.path.display()
            );
        }
        self.cpu_previous = None;
        self.cpu_busy_sum = 0.0;
        self.cpu_share_samples = 0;
    }
}

/// Write one bucket to the ledger file, as one line.
pub fn append_bucket(path: &Path, bucket: &Bucket) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut line = serde_json::to_string(bucket).map_err(std::io::Error::other)?;
    line.push('\n');
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    file.write_all(line.as_bytes())?;
    file.flush()
}

/// Read the closed hours back.
pub fn read_buckets(path: &Path) -> Vec<Bucket> {
    let mut buckets = Vec::new();
    let Ok(file) = File::open(path) else {
        return buckets;
    };
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        if line.trim().is_empty() {
            continue;
        }
        if let Ok(bucket) = serde_json::from_str::<Bucket>(&line) {
            buckets.push(bucket);
        }
    }
    buckets
}

/// One core's counters, from `/proc/stat`.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct CoreCounters {
    pub user: u64,
    pub nice: u64,
    pub system: u64,
    pub idle: u64,
    pub iowait: u64,
    pub irq: u64,
    pub softirq: u64,
    pub steal: u64,
    /// Everything, including the fields this box's kernel does not print.
    pub total: u64,
    /// Everything that was not idle or waiting for I/O.
    pub busy: u64,
}

impl CoreCounters {
    fn from_fields(fields: &[u64]) -> CoreCounters {
        let get = |index: usize| fields.get(index).copied().unwrap_or(0);
        let user = get(0);
        let nice = get(1);
        let system = get(2);
        let idle = get(3);
        let iowait = get(4);
        let irq = get(5);
        let softirq = get(6);
        let steal = get(7);
        let total: u64 = fields.iter().sum();
        CoreCounters {
            user,
            nice,
            system,
            idle,
            iowait,
            irq,
            softirq,
            steal,
            total,
            busy: total.saturating_sub(idle).saturating_sub(iowait),
        }
    }
}

/// The box's CPU counters.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CpuCounters {
    /// The aggregate line.
    pub total: CoreCounters,
    /// One entry per core, in the kernel's order.
    pub per_core: Vec<CoreCounters>,
}

impl CpuCounters {
    /// The busy share of each core since `previous`, 0 to 1.
    pub fn busy_shares_since(&self, previous: &CpuCounters) -> Vec<f64> {
        let mut shares = Vec::new();
        for (before, after) in previous.per_core.iter().zip(self.per_core.iter()) {
            let total = after.total.saturating_sub(before.total);
            if total == 0 {
                // The counters did not move: the core was asleep, or the
                // window was too short. It counts as idle, not as busy.
                shares.push(0.0);
                continue;
            }
            let busy = after.busy.saturating_sub(before.busy);
            shares.push((busy as f64 / total as f64).clamp(0.0, 1.0));
        }
        shares
    }
}

/// Parse `/proc/stat`.
pub fn parse_proc_stat(text: &str) -> CpuCounters {
    let mut counters = CpuCounters::default();
    for line in text.lines() {
        let mut parts = line.split_whitespace();
        let Some(name) = parts.next() else {
            continue;
        };
        if name == "cpu" {
            let fields: Vec<u64> = parts.filter_map(|part| part.parse().ok()).collect();
            counters.total = CoreCounters::from_fields(&fields);
        } else if name.starts_with("cpu") && name[3..].chars().all(|c| c.is_ascii_digit()) {
            let fields: Vec<u64> = parts.filter_map(|part| part.parse().ok()).collect();
            counters.per_core.push(CoreCounters::from_fields(&fields));
        }
    }
    counters
}

/// Read `/proc/stat`.
pub fn read_proc_stat() -> Option<CpuCounters> {
    let text = std::fs::read_to_string("/proc/stat").ok()?;
    Some(parse_proc_stat(&text))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tier_stat(bucket: &Bucket, tier: Tier) -> TierStat {
        bucket.tier(tier)
    }

    #[test]
    fn a_sample_of_live_work_is_booked_to_the_live_tier() {
        let mut ledger = Ledger::new(Path::new("/tmp/thor-admit-ledger-test.jsonl"));
        let sample = Sample {
            running_tiers: vec![Tier::Live],
            mem_available: 100 * 1024 * 1024 * 1024,
            ..Sample::default()
        };
        ledger.sample(1.0, &sample);
        ledger.sample(2.0, &sample);
        let bucket = ledger.bucket();
        assert_eq!(tier_stat(bucket, Tier::Live).running_s, 3.0);
        assert_eq!(tier_stat(bucket, Tier::Study).running_s, 0.0);
        assert_eq!(bucket.window_s, 3.0);
        assert_eq!(bucket.idle.total_s, 0.0);
    }

    #[test]
    fn idle_time_is_booked_to_its_cause() {
        let mut ledger = Ledger::new(Path::new("/tmp/thor-admit-ledger-test.jsonl"));
        let idle = Sample {
            idle: Some(IdleReason::NoWorkRegistered),
            ..Sample::default()
        };
        ledger.sample(4.0, &idle);
        let bucket = ledger.bucket();
        assert_eq!(bucket.idle.total_s, 4.0);
        assert_eq!(bucket.idle.by_reason["no_work_registered"], 4.0);
        assert_eq!(bucket.idle.no_work_s, 4.0);
        assert_eq!(bucket.idle.unattributed_s, 0.0);
        assert!((bucket.no_work_share() - 1.0).abs() < 1e-9);
    }

    #[test]
    fn idle_time_with_no_cause_is_counted_as_unattributed() {
        let mut ledger = Ledger::new(Path::new("/tmp/thor-admit-ledger-test.jsonl"));
        let idle = Sample {
            idle: Some(IdleReason::Unattributed),
            ..Sample::default()
        };
        ledger.sample(2.0, &idle);
        let bucket = ledger.bucket();
        assert_eq!(bucket.idle.unattributed_s, 2.0);
        assert!((bucket.unattributed_share() - 1.0).abs() < 1e-9);
    }

    #[test]
    fn a_sample_with_nothing_running_and_no_reason_is_unattributed() {
        let mut ledger = Ledger::new(Path::new("/tmp/thor-admit-ledger-test.jsonl"));
        let sample = Sample {
            mem_available: 1,
            ..Sample::default()
        };
        ledger.sample(0.5, &sample);
        assert_eq!(ledger.bucket().idle.unattributed_s, 0.5);
    }

    #[test]
    fn the_gpu_figures_are_averaged_over_the_samples() {
        let mut ledger = Ledger::new(Path::new("/tmp/thor-admit-ledger-test.jsonl"));
        for power in [1000u64, 2000, 3000] {
            let sample = Sample {
                running_tiers: vec![Tier::Study],
                gpu_power_mw: Some(power),
                gpu_busy_pct: Some(50),
                gpu_power_source: Some("tegrastats".to_string()),
                ..Sample::default()
            };
            ledger.sample(1.0, &sample);
        }
        let bucket = ledger.bucket();
        assert_eq!(bucket.gpu.power_samples, 3);
        assert_eq!(bucket.gpu.power_mw_mean, Some(2000.0));
        assert_eq!(bucket.gpu.power_mw_max, Some(3000));
        assert_eq!(bucket.gpu.busy_pct_mean, Some(50.0));
        assert_eq!(bucket.gpu.source.as_deref(), Some("tegrastats"));
    }

    #[test]
    fn the_cpu_share_is_the_busy_share_of_each_core() {
        let before = CpuCounters {
            total: CoreCounters::default(),
            per_core: vec![
                CoreCounters {
                    total: 100,
                    busy: 10,
                    ..CoreCounters::default()
                },
                CoreCounters {
                    total: 100,
                    busy: 90,
                    ..CoreCounters::default()
                },
            ],
        };
        let after = CpuCounters {
            total: CoreCounters::default(),
            per_core: vec![
                CoreCounters {
                    total: 200,
                    busy: 110,
                    ..CoreCounters::default()
                },
                CoreCounters {
                    total: 200,
                    busy: 110,
                    ..CoreCounters::default()
                },
            ],
        };
        let shares = after.busy_shares_since(&before);
        assert!((shares[0] - 1.0).abs() < 1e-9, "all of it was busy");
        assert!((shares[1] - 0.2).abs() < 1e-9, "a fifth of it was busy");
    }

    #[test]
    fn the_proc_stat_parser_reads_the_aggregate_and_the_cores() {
        let text = "cpu  100 10 50 800 20 5 5 0 0 0\ncpu0 50 5 25 400 10 2 2 0 0 0\ncpu1 50 5 25 400 10 3 3 0 0 0\nintr 12345\n";
        let counters = parse_proc_stat(text);
        assert_eq!(counters.per_core.len(), 2);
        assert_eq!(counters.total.idle, 800);
        assert_eq!(counters.total.total, 990);
        assert_eq!(counters.total.busy, 990 - 800 - 20);
        assert_eq!(counters.per_core[0].total, 494);
    }

    #[test]
    fn a_bucket_survives_the_round_trip_through_the_file() {
        let path = std::env::temp_dir().join(format!(
            "thor-admit-ledger-{}-roundtrip.jsonl",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        let mut ledger = Ledger::new(&path);
        let sample = Sample {
            running_tiers: vec![Tier::Live],
            mem_available: 42,
            gpu_power_mw: Some(1234),
            ..Sample::default()
        };
        ledger.sample(1.0, &sample);
        ledger.close_bucket();

        let buckets = read_buckets(&path);
        assert_eq!(buckets.len(), 1);
        assert_eq!(buckets[0].tier(Tier::Live).running_s, 1.0);
        assert_eq!(buckets[0].gpu.power_mw_max, Some(1234));
        assert_eq!(buckets[0].memory.available_min, Some(42));
        let _ = std::fs::remove_file(&path);
    }
}
