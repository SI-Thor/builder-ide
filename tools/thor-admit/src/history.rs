//! The learned peaks: what each label actually used, as JSON lines.
//!
//! Every time a lease ends, the daemon writes one line: the label, the peak
//! resident set the lease reached, the GPU bytes it held if the driver could
//! be asked, and where the numbers came from. A later `--peak auto` reads the
//! p95 of that label's history.
//!
//! **Not every finished run teaches.** A run teaches only if it ran to a
//! clean exit and lasted more than a few seconds: a no-op run (a wrapper
//! invoked with nothing to do, a misconfigured step) exits 0 in milliseconds
//! with a few megabytes of RSS, and a history full of those will happily
//! reserve 3.6 MB for a job that really takes 1.4 GiB — which is what
//! happened to `infinigen.mountain.coarse` on 2026-11-01, when 25 no-op
//! records taught the daemon nothing worth knowing. The one exception runs
//! the other way: an **over-run** record (written while a lease is past its
//! reservation) always teaches, because it can only raise the reserve.
//!
//! The lines are JSON objects, one per line, so a reader can follow the file
//! as it grows and a crashed writer can only lose the last line.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::clock;

/// How long a run must last before it may teach the reserve, in seconds.
///
/// The no-op records that taught `infinigen.mountain.coarse` to reserve
/// 3.6 MB all lasted under 30 ms. Five seconds is the "the work actually
/// happened" line: a real step of anything on this box takes longer than
/// that, and a run that does not is a wrapper invocation with nothing to do.
pub const MIN_LEARNED_DURATION_S: f64 = 5.0;

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
    /// The command's exit status: `Some(0)` is a clean finish, `Some(n)` a
    /// failure, `128 + signal` a kill. `None` is a record from before the
    /// exit status was written (or one written mid-run), where the duration
    /// is all the record can say about whether the work happened.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,
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
            exit_code: None,
        }
    }

    /// May this record teach a future reservation?
    ///
    /// Two kinds may:
    ///
    /// * a run that **finished cleanly** — exit 0 — and lasted at least
    ///   [`MIN_LEARNED_DURATION_S`]. A failed run teaches nothing (it may
    ///   have died halfway, and its half-a-peak is not what the next run
    ///   costs), and a run that lasted no time did no work.
    /// * an **over-run** record, whatever its duration: it is written only
    ///   while a lease is past its reservation by more than the tolerance,
    ///   so it is a real measurement of real work, and the only direction it
    ///   can move a reserve is up.
    ///
    /// A record with no exit status (`None`) is one from before the exit
    /// status was written; the duration still applies to it, which is what
    /// cleaned the 25 no-op records out of the box's history by hand on
    /// 2026-11-01 — this predicate does the same job on every read.
    pub fn teaches(&self) -> bool {
        if self.peak_source == "overrun" {
            return true;
        }
        self.exit_code.unwrap_or(0) == 0 && self.duration_s >= MIN_LEARNED_DURATION_S
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

    /// A history holding exactly these records, written to `path` if
    /// anything is ever appended to it.
    ///
    /// The replay (`examples/replay.rs`) builds one from a snapshot it has
    /// already read; nothing on the box writes to it.
    pub fn from_records(path: &Path, records: &[PeakRecord]) -> History {
        History {
            path: path.to_path_buf(),
            records: records.to_vec(),
        }
    }

    /// The records of one label that may teach a reservation.
    pub fn teachers(&self, label: &str) -> Vec<&PeakRecord> {
        self.records
            .iter()
            .filter(|record| record.label == label && record.teaches())
            .collect()
    }

    /// The peak RSS of every run of one label.
    ///
    /// Only the runs that teach count (see [`PeakRecord::teaches`]): a
    /// no-op's few megabytes are in the file's past, not in the label's
    /// future.
    pub fn peaks_for(&self, label: &str) -> Vec<u64> {
        self.teachers(label)
            .into_iter()
            .map(|record| record.peak_rss_bytes)
            .collect()
    }

    /// The p95 of a label's history, the number `--peak auto` starts from.
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

    /// The peak of the label's most recent run.
    ///
    /// `--peak auto` reserves the larger of this and the p95: the p95 says
    /// what the label *usually* costs, the last run says what it cost the
    /// last time the workload looked like this one — and a label whose last
    /// run overran its history is exactly the label a p95-only reservation
    /// would under-reserve (Hy4's second failure mode). Only a run that
    /// teaches counts as the last run: a no-op in between changes nothing.
    pub fn last(&self, label: &str) -> Option<u64> {
        self.teachers(label)
            .last()
            .map(|record| record.peak_rss_bytes)
    }

    /// How many runs of one label the history holds that may teach.
    pub fn runs(&self, label: &str) -> usize {
        self.teachers(label).len()
    }

    /// The GPU peak `--peak auto` reserves for a label: the larger of the
    /// p95 and the last run of the GPU column, when the driver could be
    /// asked for one at all.
    ///
    /// `None` means the history has never seen this label hold device
    /// memory (CPU-only work, or no driver view), and then there is no GPU
    /// promise to make.
    pub fn learned_gpu(&self, label: &str) -> Option<u64> {
        let peaks: Vec<u64> = self
            .teachers(label)
            .into_iter()
            .filter_map(|record| record.peak_gpu_bytes)
            .collect();
        if peaks.is_empty() {
            return None;
        }
        let p95 = percentile(&peaks, 0.95).round() as u64;
        Some(p95.max(*peaks.last().unwrap_or(&0)))
    }

    /// The p95 of a label's teaching runs' durations, in seconds — the
    /// backfill rule's estimate of how long a lease of this label will hold
    /// its promise (round 11). The p95 rather than the p50, because an
    /// underestimate is the dangerous direction: a candidate given 60 s and
    /// running for an hour holds the hole for an hour past what the rule
    /// checked. `None` when the label has no teaching run — and a lease
    /// with no estimate never backfills (`crate::backfill`).
    pub fn duration_p95(&self, label: &str) -> Option<f64> {
        let durations: Vec<u64> = self
            .teachers(label)
            .into_iter()
            .map(|record| (record.duration_s.max(0.0) * 1000.0).round() as u64)
            .collect();
        if durations.is_empty() {
            return None;
        }
        Some(percentile(&durations, 0.95) / 1000.0)
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

    /// A record from a clean, real run: the shape every teaching record has.
    fn taught(label: &str, peak: u64) -> PeakRecord {
        let mut record = PeakRecord::new(label, label, peak);
        record.duration_s = MIN_LEARNED_DURATION_S + 1.0;
        record.exit_code = Some(0);
        record
    }

    #[test]
    fn a_record_survives_a_round_trip_as_one_line() {
        let path = temp_path("roundtrip");
        let mut history = History::load(&path);
        let mut record = taught("trellis", 42_000_000_000);
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
    fn a_record_with_an_exit_code_survives_the_round_trip() {
        let path = temp_path("exit-roundtrip");
        let mut history = History::load(&path);
        let mut record = taught("trellis", 42_000_000_000);
        record.exit_code = Some(0);
        history.append(record).unwrap();
        let text = std::fs::read_to_string(&path).unwrap();
        assert!(text.contains("\"exit_code\":0"), "the exit status is written: {text}");

        let reread = History::load(&path);
        assert_eq!(reread.records()[0].exit_code, Some(0));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn auto_peak_is_the_p95_of_the_label() {
        let path = temp_path("p95");
        let mut history = History::load(&path);
        for peak in [10u64, 20, 30, 40, 100] {
            history
                .append(taught("trellis", peak * 1_000_000_000))
                .unwrap();
        }
        history
            .append(taught("other", 999_000_000_000))
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
        assert_eq!(history.last("nothing"), None);
        assert_eq!(history.runs("nothing"), 0);
        assert_eq!(history.duration_p95("nothing"), None);
    }

    #[test]
    fn the_duration_estimate_is_the_p95_of_the_teaching_runs() {
        // The backfill rule's estimate. A no-op (under the teaching
        // duration) contributes nothing however many there are, and the
        // estimate leans high: [60, 60, 60, 600] s of teaching runs gives
        // a p95 of 60 + (600 - 60) * 0.85 = 519 s, not the p50's 60 s.
        let path = temp_path("duration-p95");
        let mut history = History::load(&path);
        for seconds in [60.0, 60.0, 60.0, 600.0] {
            let mut record = taught("trellis", 4_000_000_000);
            record.duration_s = seconds;
            history.append(record).unwrap();
        }
        let mut noop = PeakRecord::new("trellis", "trellis", 3_670_000);
        noop.duration_s = 0.4;
        noop.exit_code = Some(0);
        history.append(noop).unwrap();
        let estimate = history.duration_p95("trellis").unwrap();
        assert!((estimate - 519.0).abs() < 0.01, "the estimate was {estimate}");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn the_last_run_is_what_the_p95_has_not_caught_up_with() {
        // Three quiet runs and one loud one: the p95 is still mostly made of
        // the quiet runs, so reserving the p95 alone would under-reserve the
        // next run. The last run is the louder number, and the reservation
        // takes the larger of the two.
        let path = temp_path("last");
        let mut history = History::load(&path);
        for peak in [10u64, 10, 10, 40] {
            history
                .append(taught("trellis", peak * 1_000_000_000))
                .unwrap();
        }
        assert_eq!(history.runs("trellis"), 4);
        assert_eq!(history.last("trellis").unwrap(), 40_000_000_000);
        assert!(history.p95("trellis").unwrap() < 40_000_000_000);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_truncated_last_line_does_not_take_the_history_with_it() {
        let path = temp_path("torn");
        let mut history = History::load(&path);
        history
            .append(taught("trellis", 1_000_000_000))
            .unwrap();
        let mut text = std::fs::read_to_string(&path).unwrap();
        text.push_str("{\"at\":\"2026-10-31T00:00:00Z\",\"label\":\"trellis\",\"peak_rs");
        std::fs::write(&path, text).unwrap();

        let reread = History::load(&path);
        assert_eq!(reread.records().len(), 1, "the whole record survives");
        let _ = std::fs::remove_file(&path);
    }

    /// The 2026-11-01 incident, at unit scale: 25 no-op records — every one
    /// of them under 30 ms and under 4 MB, with no exit status, exactly as
    /// the wrapper wrote them — sat in the history of
    /// `infinigen.mountain.coarse`, and the next `--peak auto` reserved
    /// 3.6 MB for a job that was already using 1.3 GiB. None of those
    /// records may teach, however many of them there are.
    #[test]
    fn no_op_records_cannot_teach_no_matter_how_many_there_are() {
        let path = temp_path("noops");
        let mut history = History::load(&path);
        for _ in 0..25 {
            let mut record = PeakRecord::new("infinigen.mountain.coarse", "kind", 3_801_088);
            record.duration_s = 0.027;
            history.append(record).unwrap();
        }
        assert_eq!(history.records().len(), 25, "the records are in the file");
        assert_eq!(
            history.runs("infinigen.mountain.coarse"),
            0,
            "not one of them teaches"
        );
        assert_eq!(history.p95("infinigen.mountain.coarse"), None);
        assert_eq!(history.last("infinigen.mountain.coarse"), None);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_run_that_failed_cannot_teach() {
        let path = temp_path("failed");
        let mut history = History::load(&path);
        let mut failed = taught("trellis", 42_000_000_000);
        failed.exit_code = Some(1);
        history.append(failed).unwrap();
        let mut killed = taught("trellis", 42_000_000_000);
        killed.exit_code = Some(137); // 128 + SIGKILL: the watchdog's work
        history.append(killed).unwrap();
        assert_eq!(history.runs("trellis"), 0, "neither failure teaches");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn an_overrun_record_teaches_even_though_it_is_unfinished() {
        // The over-run watch writes mid-run, before the duration or the exit
        // status exists — and it writes only past a gross over-reservation,
        // so it can only raise a reserve. It must not be filtered out by the
        // very rule that keeps no-ops quiet.
        let path = temp_path("overrun-teaches");
        let mut history = History::load(&path);
        let mut overrun = PeakRecord::new("trellis", "trellis", 42_000_000_000);
        overrun.peak_source = "overrun".to_string();
        history.append(overrun).unwrap();
        assert_eq!(history.runs("trellis"), 1);
        assert_eq!(history.last("trellis"), Some(42_000_000_000));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_long_record_from_before_exit_codes_teaches() {
        // Records written before the exit status existed carry `None`; their
        // duration is the only word they have, and a real run's record
        // still counts.
        let path = temp_path("legacy");
        let mut history = History::load(&path);
        let mut legacy = PeakRecord::new("trellis", "trellis", 42_000_000_000);
        legacy.duration_s = 52.9; // the shape of the real infinigen renders
        history.append(legacy).unwrap();
        assert_eq!(history.runs("trellis"), 1);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_no_op_between_real_runs_does_not_become_the_last_run() {
        let path = temp_path("noop-last");
        let mut history = History::load(&path);
        history.append(taught("trellis", 40_000_000_000)).unwrap();
        let mut noop = PeakRecord::new("trellis", "trellis", 3_670_000);
        noop.duration_s = 0.4;
        noop.exit_code = Some(0);
        history.append(noop).unwrap();
        assert_eq!(history.runs("trellis"), 1);
        assert_eq!(history.last("trellis"), Some(40_000_000_000));
        let _ = std::fs::remove_file(&path);
    }
}
