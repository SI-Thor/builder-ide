//! The learned peaks: what each label actually used, as JSON lines.
//!
//! Every time a lease ends, the daemon writes one line: the label, the peak
//! resident set the lease reached, the GPU bytes it held if the driver could
//! be asked, and where the numbers came from. A later `--peak auto` reads the
//! p95 of that label's history.
//!
//! The lines are JSON objects, one per line, so a reader can follow the file
//! as it grows and a crashed writer can only lose the last line.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::clock;

/// One measured peak.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PeakRecord {
    /// RFC 3339 UTC.
    pub at: String,
    /// The job kind, the cost model's word for it.
    pub kind: String,
    /// The lease label.
    pub label: String,
    /// The box the measurement was taken on.
    pub host: String,
    /// The peak resident set of the lease, in bytes. The memory column.
    pub peak_rss_bytes: u64,
    /// The peak GPU bytes, when the driver could be asked.
    pub peak_gpu_bytes: Option<u64>,
    /// Whether the GPU's view was available at all.
    pub gpu_visible: bool,
    /// How long the lease ran.
    pub duration_s: f64,
    /// The box's memory total when the lease ran.
    pub mem_total_bytes: u64,
    /// The floor the daemon was holding when the lease ran.
    pub floor_bytes: u64,
    /// The cost model's word for where a number comes from.
    pub basis: String,
    /// Who measured it.
    pub source: String,
    /// Which measurement the peak came from.
    pub peak_source: String,
}

impl PeakRecord {
    /// A new record for a finished lease.
    pub fn new(label: &str, kind: &str, peak_rss_bytes: u64) -> PeakRecord {
        PeakRecord {
            at: clock::rfc3339_now(),
            kind: kind.to_string(),
            label: label.to_string(),
            host: hostname(),
            peak_rss_bytes,
            peak_gpu_bytes: None,
            gpu_visible: false,
            duration_s: 0.0,
            mem_total_bytes: 0,
            floor_bytes: 0,
            basis: "measured".to_string(),
            source: "thor-admit".to_string(),
            peak_source: "sample".to_string(),
        }
    }
}

fn hostname() -> String {
    std::fs::read_to_string("/proc/sys/kernel/hostname")
        .map(|text| text.trim().to_string())
        .unwrap_or_else(|_| "unknown".to_string())
}

/// The history of every label's peaks.
#[derive(Debug)]
pub struct History {
    path: PathBuf,
    records: Vec<PeakRecord>,
}

impl History {
    /// Read a history file. A line that cannot be read is skipped: a writer
    /// that died mid-line must not take the history with it.
    pub fn load(path: &Path) -> History {
        let mut records = Vec::new();
        if let Ok(file) = File::open(path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                if line.trim().is_empty() {
                    continue;
                }
                if let Ok(record) = serde_json::from_str::<PeakRecord>(&line) {
                    records.push(record);
                }
            }
        }
        History {
            path: path.to_path_buf(),
            records,
        }
    }

    /// The path the history is written to.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Every record.
    pub fn records(&self) -> &[PeakRecord] {
        &self.records
    }

    /// Add a record and write it as one line.
    pub fn append(&mut self, record: PeakRecord) -> std::io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut line = serde_json::to_string(&record).map_err(std::io::Error::other)?;
        line.push('\n');
        let mut file = OpenOptions::new().create(true).append(true).open(&self.path)?;
        file.write_all(line.as_bytes())?;
        file.flush()?;
        self.records.push(record);
        Ok(())
    }

    /// The peak RSS of every run of one label.
    pub fn peaks_for(&self, label: &str) -> Vec<u64> {
        self.records
            .iter()
            .filter(|record| record.label == label)
            .map(|record| record.peak_rss_bytes)
            .collect()
    }

    /// The p95 of a label's history, the number `--peak auto` uses.
    pub fn p95(&self, label: &str) -> Option<u64> {
        let peaks = self.peaks_for(label);
        if peaks.is_empty() {
            return None;
        }
        Some(percentile(&peaks, 0.95).round() as u64)
    }

    /// The p50 of a label's history.
    pub fn p50(&self, label: &str) -> Option<u64> {
        let peaks = self.peaks_for(label);
        if peaks.is_empty() {
            return None;
        }
        Some(percentile(&peaks, 0.50).round() as u64)
    }
}

/// The `q`-th percentile, linearly interpolated — the same convention
/// `core/night/cost/model.py` uses, so a number here and a number there mean
/// the same thing.
pub fn percentile(values: &[u64], q: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut ordered: Vec<u64> = values.to_vec();
    ordered.sort_unstable();
    if ordered.len() == 1 {
        return ordered[0] as f64;
    }
    let position = (ordered.len() as f64 - 1.0) * q;
    let low = position.floor();
    let high = position.ceil();
    if low == high {
        return ordered[low as usize] as f64;
    }
    let low_value = ordered[low as usize] as f64;
    let high_value = ordered[high as usize] as f64;
    low_value + (high_value - low_value) * (position - low)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_path(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("thor-admit-test-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_file(&path);
        path
    }

    #[test]
    fn the_percentile_matches_the_convention_the_cost_model_uses() {
        // NumPy's linear interpolation: position = (n - 1) * q.
        let values = [1u64, 2, 3, 4];
        assert!((percentile(&values, 0.95) - 3.85).abs() < 1e-9);
        assert!((percentile(&values, 0.50) - 2.5).abs() < 1e-9);
    }

    #[test]
    fn one_value_is_its_own_percentile() {
        assert_eq!(percentile(&[42], 0.95), 42.0);
    }

    #[test]
    fn a_record_survives_a_round_trip_as_one_line() {
        let path = temp_path("roundtrip");
        let mut history = History::load(&path);
        let mut record = PeakRecord::new("trellis", "trellis", 42_000_000_000);
        record.peak_gpu_bytes = Some(1024);
        record.gpu_visible = true;
        record.duration_s = 12.5;
        history.append(record.clone()).unwrap();

        let text = std::fs::read_to_string(&path).unwrap();
        assert_eq!(text.lines().count(), 1, "one record is one line");

        let reread = History::load(&path);
        assert_eq!(reread.records().len(), 1);
        assert_eq!(reread.records()[0].peak_rss_bytes, 42_000_000_000);
        assert_eq!(reread.records()[0].peak_gpu_bytes, Some(1024));
        assert_eq!(reread.records()[0].basis, "measured");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn auto_peak_is_the_p95_of_the_label() {
        let path = temp_path("p95");
        let mut history = History::load(&path);
        for peak in [10u64, 20, 30, 40, 100] {
            history
                .append(PeakRecord::new("trellis", "trellis", peak * 1_000_000_000))
                .unwrap();
        }
        history
            .append(PeakRecord::new("other", "other", 999_000_000_000))
            .unwrap();
        // p95 of [10, 20, 30, 40, 100] GiB: position = (5 - 1) * 0.95 = 3.8,
        // so 40 + (100 - 40) * 0.8 = 88.
        let p95 = history.p95("trellis").unwrap();
        assert_eq!(p95, 88_000_000_000);
        assert_eq!(history.p50("trellis").unwrap(), 30_000_000_000);
        assert_eq!(history.p95("other").unwrap(), 999_000_000_000);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn an_unknown_label_has_no_peak() {
        let path = temp_path("unknown");
        let history = History::load(&path);
        assert_eq!(history.p95("nothing"), None);
    }

    #[test]
    fn a_truncated_last_line_does_not_take_the_history_with_it() {
        let path = temp_path("torn");
        let mut history = History::load(&path);
        history
            .append(PeakRecord::new("trellis", "trellis", 1_000_000_000))
            .unwrap();
        let mut text = std::fs::read_to_string(&path).unwrap();
        text.push_str("{\"at\":\"2026-10-31T00:00:00Z\",\"label\":\"trellis\",\"peak_rs");
        std::fs::write(&path, text).unwrap();

        let reread = History::load(&path);
        assert_eq!(reread.records().len(), 1, "the whole record survives");
        let _ = std::fs::remove_file(&path);
    }
}
