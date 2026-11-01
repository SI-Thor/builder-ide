//! The replay: 2026-11-01's queue, strict FIFO against EASY backfill.
//!
//! ```text
//! cargo run --release --example replay -- \
//!     ~/.local/state/thor-admit/daemon.log \
//!     ~/lm-tools/thor-admit-daemon.log \
//!     --history ~/.local/state/thor-admit/peaks.jsonl \
//!     [--pid <daemon pid>] [--floor 25G]
//! ```
//!
//! **What it does.** It reads the daemon's own log — the requests
//! (`lease.queued`), the grants (`lease.granted`), the releases
//! (`lease.released`) and the box's memory every ten seconds
//! (`daemon.sample`) — rebuilds the queue as it stood, and simulates the
//! admission policies on it:
//!
//! * **fifo** — the round-10 rule: the head must fit before anything
//!   behind it is considered. This is what actually ran, so this policy is
//!   also the *validation*: its simulated grants are compared against the
//!   real ones, and a waiter the simulation grants that reality never
//!   granted at all is a dead client (a waiter in the queue with nobody
//!   behind it), dropped from every policy so the comparison is
//!   like-for-like.
//! * **easy-&lt;bound&gt;** — round 11's rule: a request may pass the head
//!   when it cannot delay the head's earliest possible start, with the
//!   head's wait bounded.
//! * **easy+coalesce** — the same, with identical serve waiters coalesced
//!   into one (the daemon-side half of round 11's serve coalescing; the
//!   log carries no registry keys, so waiters with the same `serve.` label
//!   and the same peak are the same ask).
//! * **fifo+phase** — the strict order, coalescing, and the phase cue
//!   heeded: a running lease holding four times its label's learned p95
//!   with 8 GiB still owed shrinks to that p95 five minutes in (the cue
//!   `lease.overreserved` logs, answered by `thor-admit phase`). This is
//!   not what ran; it is what round 11's item 3 would have made possible.
//!
//! **The memory model, stated plainly.** The replay runs nothing. Each
//! lease is modeled as holding its **measured peak RSS** (from its release
//! record, rectangular over its run; for a lease that never released, its
//! label's learned p95, or its promise when even the history is silent)
//! while being **charged its whole promise** — the arithmetic the daemon
//! itself uses: `projected = available − Σ(reserved − current)`. Where the
//! simulation's running set differs from reality's, the measured curve is
//! adjusted by swapping the two sets' modeled RSS. The model is validated
//! by the fifo policy's grant times against the real ones; the error is
//! printed with the results, not hidden by them.
//!
//! **Durations.** A lease that really ran keeps its real duration in every
//! policy (its work is what it is); one that never released held its
//! promise to the end of the trace, and the model says the same. A lease
//! that runs only in a counterfactual (backfilled, or unblocked by a phase
//! shrink) runs for its label's duration p95 as the history knew it *at
//! that moment* — the same estimate the backfill rule itself used — or,
//! with no history, the day's median real duration. The EASY rules here
//! use those estimates too, never the real durations: the daemon could not
//! have known them.

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use thor_admit::backfill::{may_backfill, Running};

const GIB: u64 = 1024 * 1024 * 1024;

/// One request as it arrived.
#[derive(Clone, Debug)]
struct Arrival {
    at: f64,
    lease: u64,
    label: String,
    peak: u64,
    priority: i32,
}

/// What really happened to a lease (nothing, for the ones that never ran).
#[derive(Clone, Debug, Default)]
struct RealRun {
    granted_at: Option<f64>,
    released_at: Option<f64>,
    /// The peak RSS its release reported; a lease that never released has
    /// none, and the model falls back to the label's learned p95.
    peak_rss: Option<u64>,
    duration: Option<f64>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct Policy {
    /// EASY backfill with this bound on the head's wait; `None` is strict
    /// FIFO (the head must fit first).
    bound_s: Option<f64>,
    /// Coalesce identical serve waiters into one.
    coalesce: bool,
    /// Heed the over-reservation cue: shrink far-over-reserved running
    /// leases to their learned p95 five minutes in.
    phase: bool,
}

impl Policy {
    fn name(&self) -> String {
        let mut name = match self.bound_s {
            None => "fifo".to_string(),
            Some(bound) => format!("easy-{bound:.0}"),
        };
        if self.coalesce {
            name += "+coalesce";
        }
        if self.phase {
            name += "+phase";
        }
        name
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut logs: Vec<PathBuf> = Vec::new();
    let mut history_path: Option<PathBuf> = None;
    let mut pid: Option<u32> = None;
    let mut floor: u64 = 25 * GIB;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--history" if index + 1 < args.len() => {
                history_path = Some(PathBuf::from(args[index + 1].clone()));
                args.remove(index + 1);
                args.remove(index);
            }
            "--floor" if index + 1 < args.len() => {
                floor = thor_admit::sizes::Size::parse(&args[index + 1])
                    .expect("--floor is a size")
                    .bytes;
                args.remove(index + 1);
                args.remove(index);
            }
            "--pid" if index + 1 < args.len() => {
                pid = Some(
                    args[index + 1]
                        .parse()
                        .expect("--pid is a daemon pid"),
                );
                args.remove(index + 1);
                args.remove(index);
            }
            other => {
                if other.starts_with("--") {
                    eprintln!("unknown option {other}");
                    std::process::exit(2);
                }
                logs.push(PathBuf::from(other));
                index += 1;
            }
        }
    }
    if logs.is_empty() {
        eprintln!("usage: replay <daemon.log> [more logs] [--history peaks.jsonl] [--pid <daemon pid>] [--floor 25G]");
        std::process::exit(2);
    }
    let history = match history_path.as_deref() {
        Some(path) => thor_admit::history::History::load(path),
        None => thor_admit::history::History::load(PathBuf::from("/nonexistent").as_path()),
    };

    let trace = Trace::read(&logs, &history, pid);
    let granted = trace
        .runs
        .values()
        .filter(|run| run.granted_at.is_some())
        .count();
    println!(
        "# replay of daemon pid {} ({} → {}), {} arrivals, {} real grants, {} real \
         releases, {} samples, floor {}",
        trace.pid,
        clock_text(trace.start),
        clock_text(trace.end),
        trace.arrivals.len(),
        granted,
        trace.runs.values().filter(|run| run.released_at.is_some()).count(),
        trace.samples.len(),
        thor_admit::sizes::human(floor),
    );
    println!("# model: measured peak RSS, rectangular; each lease charged its whole promise");

    // 1. Validation: strict FIFO, with every waiter, against what really
    //    happened. Its phantom grants are dead clients; the policies below
    //    run with them excluded.
    let validation_policy = Policy { bound_s: None, coalesce: false, phase: false };
    let (_, validation) = trace.simulate(validation_policy, floor, None);
    report_validation(&validation);
    let dead: HashSet<u64> = validation.phantoms.iter().copied().collect();

    // 2. The table. Every policy — fifo included — runs on the same trace
    //    with the dead waiters excluded.
    let policies = [
        Policy { bound_s: None, coalesce: false, phase: false },
        Policy { bound_s: Some(900.0), coalesce: false, phase: false },
        Policy { bound_s: Some(1800.0), coalesce: false, phase: false },
        Policy { bound_s: Some(3600.0), coalesce: false, phase: false },
        Policy { bound_s: Some(1800.0), coalesce: true, phase: false },
        Policy { bound_s: None, coalesce: true, phase: true },
        // The daemon's own default, as round 11 ships it: backfill on with
        // the 1800 s bound, serve coalescing on, and the phase cue heeded.
        // It is the policy the box will actually run, so it is the one the
        // table has to answer for.
        Policy { bound_s: Some(1800.0), coalesce: true, phase: true },
    ];
    let results: Vec<(Policy, SimResult)> = policies
        .iter()
        .map(|policy| {
            let (result, _) = trace.simulate(*policy, floor, Some(&dead));
            (*policy, result)
        })
        .collect();
    report_table(&results, &trace);
}

// ---------------------------------------------------------------------------
// The trace
// ---------------------------------------------------------------------------

struct Trace {
    pid: u32,
    start: f64,
    end: f64,
    arrivals: Vec<Arrival>,
    /// lease id → what really happened.
    runs: HashMap<u64, RealRun>,
    /// (t, MemAvailable) every ten seconds, as the daemon sampled it.
    samples: Vec<(f64, u64)>,
    /// The history, for estimates and censored-lease RSS models.
    history: thor_admit::history::History,
    /// The day's median real duration, for counterfactual runs with no
    /// history at all.
    median_duration: f64,
}

impl Trace {
    fn read(
        logs: &[PathBuf],
        history: &thor_admit::history::History,
        pid: Option<u32>,
    ) -> Trace {
        let mut lines: HashSet<String> = HashSet::new();
        let mut events: Vec<serde_json::Value> = Vec::new();
        for log in logs {
            if let Ok(text) = std::fs::read_to_string(log) {
                for line in text.lines() {
                    if line.trim().is_empty() || !lines.insert(line.to_string()) {
                        continue;
                    }
                    if let Ok(value) = serde_json::from_str::<serde_json::Value>(line) {
                        events.push(value);
                    }
                }
            }
        }
        // One daemon owns the replay: lease ids restart with a daemon, and a
        // restart empties the queue, so two daemons' leases cannot be
        // replayed as one queue. `--pid` names it; without the flag the one
        // with the most lease events does, which is the daemon that ran the
        // box most, not necessarily the one that ran the queue worth
        // replaying.
        let mut by_pid: HashMap<u32, usize> = HashMap::new();
        for event in &events {
            let is_lease = event
                .get("event")
                .and_then(|event| event.as_str())
                .map_or(false, |name| name.starts_with("lease."));
            if is_lease {
                if let Some(pid) = event.get("pid").and_then(|pid| pid.as_u64()) {
                    *by_pid.entry(pid as u32).or_default() += 1;
                }
            }
        }
        let pid = match pid {
            Some(pid) => {
                if !by_pid.contains_key(&pid) {
                    eprintln!("pid {pid} has no lease events in the log");
                    std::process::exit(2);
                }
                pid
            }
            None => *by_pid
                .iter()
                .max_by_key(|(_, count)| **count)
                .map(|(pid, _)| pid)
                .expect("the log holds at least one lease event"),
        };
        let ours = |event: &serde_json::Value| {
            event.get("pid").and_then(|pid| pid.as_u64()) == Some(pid as u64)
        };

        let mut arrivals: Vec<Arrival> = Vec::new();
        let mut runs: HashMap<u64, RealRun> = HashMap::new();
        let mut samples: Vec<(f64, u64)> = Vec::new();
        let mut start = f64::INFINITY;
        let mut end = f64::NEG_INFINITY;
        for event in &events {
            if !ours(event) {
                continue;
            }
            let Some(at) = event
                .get("at")
                .and_then(|at| at.as_str())
                .and_then(parse_clock)
            else {
                continue;
            };
            let name = event.get("event").and_then(|event| event.as_str()).unwrap_or("");
            let lease = event.get("lease").and_then(|lease| lease.as_u64()).unwrap_or(0);
            start = start.min(at);
            end = end.max(at);
            match name {
                "lease.queued" => arrivals.push(Arrival {
                    at,
                    lease,
                    label: event
                        .get("label")
                        .and_then(|label| label.as_str())
                        .unwrap_or("?")
                        .to_string(),
                    peak: event
                        .get("peak_bytes")
                        .and_then(|peak| peak.as_u64())
                        .unwrap_or(0),
                    priority: event
                        .get("priority")
                        .and_then(|priority| priority.as_i64())
                        .unwrap_or(0) as i32,
                }),
                "lease.granted" => {
                    runs.entry(lease).or_default().granted_at = Some(at);
                }
                "lease.released" => {
                    let run = runs.entry(lease).or_default();
                    run.released_at = Some(at);
                    run.peak_rss = event
                        .get("peak_rss_bytes")
                        .and_then(|peak| peak.as_u64());
                    run.duration = event.get("duration_s").and_then(|d| d.as_f64());
                }
                "daemon.sample" => {
                    if let Some(free) = event
                        .get("mem_available_bytes")
                        .and_then(|free| free.as_u64())
                    {
                        samples.push((at, free));
                    }
                }
                _ => {}
            }
        }
        arrivals.sort_by(|a, b| a.at.total_cmp(&b.at));
        samples.sort_by(|a, b| a.0.total_cmp(&b.0));
        let mut durations: Vec<f64> = runs
            .values()
            .filter_map(|run| run.duration)
            .filter(|duration| *duration > 0.0)
            .collect();
        durations.sort_by(|a, b| a.total_cmp(b));
        let median_duration = durations.get(durations.len() / 2).copied().unwrap_or(300.0);
        Trace {
            pid,
            start,
            end,
            arrivals,
            runs,
            samples,
            history: clone_history(history),
            median_duration,
        }
    }

    /// `MemAvailable` at time `t`, linear between the daemon's samples.
    fn available_at(&self, t: f64) -> u64 {
        let samples = &self.samples;
        if samples.is_empty() {
            return 0;
        }
        if t <= samples[0].0 {
            return samples[0].1;
        }
        if t >= samples[samples.len() - 1].0 {
            return samples[samples.len() - 1].1;
        }
        let index = samples.partition_point(|(at, _)| *at < t);
        let (t0, v0) = samples[index - 1];
        let (t1, v1) = samples[index];
        if t1 <= t0 {
            return v0;
        }
        let share = (t - t0) / (t1 - t0);
        (v0 as f64 + (v1 as f64 - v0 as f64) * share).round() as u64
    }

    /// The label's duration p95 as the history knew it at `t` — the same
    /// estimate the daemon's backfill rule would have used at that moment.
    fn duration_estimate_at(&self, label: &str, t: f64) -> Option<f64> {
        let cutoff = clock_text(t);
        let durations: Vec<u64> = self
            .history
            .records()
            .iter()
            .filter(|record| record.label == label && record.at.as_str() <= cutoff.as_str())
            .filter(|record| teaches(record))
            .map(|record| (record.duration_s.max(0.0) * 1000.0).round() as u64)
            .collect();
        if durations.is_empty() {
            return None;
        }
        Some(thor_admit::history::percentile(&durations, 0.95) / 1000.0)
    }

    /// The label's peak p95 as the history knew it at `t`.
    fn peak_p95_at(&self, label: &str, t: f64) -> Option<u64> {
        let cutoff = clock_text(t);
        let records: Vec<&thor_admit::history::PeakRecord> = self
            .history
            .records()
            .iter()
            .filter(|record| record.label == label)
            .collect();
        let peaks: Vec<u64> = records
            .iter()
            .filter(|record| record.at.as_str() <= cutoff.as_str() && teaches(record))
            .map(|record| record.peak_rss_bytes)
            .collect();
        if std::env::var("THOR_ADMIT_REPLAY_DEBUG").is_ok() && !records.is_empty() {
            eprintln!(
                "    peak_p95_at({label}, {cutoff}): {} records, {} usable → {:?}",
                records.len(),
                peaks.len(),
                peaks.last()
            );
        }
        if peaks.is_empty() {
            return None;
        }
        Some(thor_admit::history::percentile(&peaks, 0.95).round() as u64)
    }

    /// The peak `--peak auto` reserves for a label at `t`: the larger of the
    /// p95 and the last teaching run, as the daemon's `learned_peak` computes
    /// it (`src/daemon.rs`, round 8). The replay's phase policy has to use the
    /// same number the daemon would resolve, or it is not measuring the
    /// daemon.
    fn learned_peak_at(&self, label: &str, t: f64) -> Option<u64> {
        let cutoff = clock_text(t);
        let peaks: Vec<u64> = self
            .history
            .records()
            .iter()
            .filter(|record| record.label == label)
            .filter(|record| record.at.as_str() <= cutoff.as_str() && teaches(record))
            .map(|record| record.peak_rss_bytes)
            .collect();
        if peaks.is_empty() {
            return None;
        }
        let p95 = thor_admit::history::percentile(&peaks, 0.95).round() as u64;
        Some(p95.max(*peaks.last().unwrap_or(&0)))
    }

    fn arrival_of(&self, lease: &u64) -> Option<&Arrival> {
        self.arrivals.iter().find(|arrival| &arrival.lease == lease)
    }

    /// The RSS a lease is modeled as holding while it runs: its measured
    /// release peak when there is one, the label's learned p95 otherwise,
    /// and its promise as the last resort (an over-statement the
    /// validation pass prices).
    fn rss_model(&self, lease: &u64) -> u64 {
        if let Some(peak) = self
            .runs
            .get(lease)
            .and_then(|run| run.peak_rss)
            .filter(|peak| *peak > 0)
        {
            return peak;
        }
        let at = self
            .runs
            .get(lease)
            .and_then(|run| run.granted_at)
            .unwrap_or(self.start);
        match self.arrival_of(lease) {
            Some(arrival) => self
                .peak_p95_at(&arrival.label, at)
                .unwrap_or(arrival.peak),
            None => 0,
        }
    }

    // The simulation -------------------------------------------------------

    /// Simulate one policy. `dead` names the waiters the validation pass
    /// found never to have had a client behind them.
    fn simulate(
        &self,
        policy: Policy,
        floor: u64,
        dead: Option<&HashSet<u64>>,
    ) -> (SimResult, Validation) {
        // One lease the simulation has running: what it promised (a phase
        // shrink lowers it), when it started, when it ends.
        struct SimLease {
            lease: u64,
            label: String,
            started: f64,
            ends: f64,
            reserved: u64,
            shrunk: bool,
        }
        let mut running: Vec<SimLease> = Vec::new();
        let mut queue: Vec<Arrival> = Vec::new();
        let mut next_arrival = 0usize;
        let mut grants: HashMap<u64, f64> = HashMap::new();
        let mut backfilled: HashSet<u64> = HashSet::new();
        let mut coalesced: HashSet<u64> = HashSet::new();

        let step = 1.0;
        let mut t = self.start;
        while t <= self.end {
            // Arrivals join the queue (a higher priority in front, arrival
            // order within a priority — the daemon's own order).
            while next_arrival < self.arrivals.len() && self.arrivals[next_arrival].at <= t {
                let arrival = self.arrivals[next_arrival].clone();
                next_arrival += 1;
                if dead.map_or(false, |dead| dead.contains(&arrival.lease)) {
                    continue;
                }
                if policy.coalesce && arrival.label.starts_with("serve.") {
                    // Identical serve asks waiting side by side are one
                    // waiter: the log carries no registry keys, so the same
                    // label with the same peak is the same ask.
                    if queue
                        .iter()
                        .any(|waiting| waiting.label == arrival.label && waiting.peak == arrival.peak)
                    {
                        coalesced.insert(arrival.lease);
                        continue;
                    }
                }
                let position = queue
                    .iter()
                    .position(|waiting| waiting.priority < arrival.priority)
                    .unwrap_or(queue.len());
                queue.insert(position, arrival);
            }

            // The leases that ended give their promises back.
            running.retain(|lease| lease.ends > t);

            // The phase cue, heeded: five minutes in, a lease holding four
            // times both its label's learned peak and its own measured peak,
            // with 8 GiB of the promise still owed, shrinks to that learned
            // peak. The condition is the daemon's own (`lease.overreserved`:
            // four times the larger of the learned p95 and the lease's
            // measured peak, 8 GiB owed, held for five minutes), and the
            // shrink is the one `thor-admit phase --peak auto` would make.
            // (The daemon logs the cue; this policy assumes the night runner
            // answers it.)
            if policy.phase {
                for lease in running.iter_mut() {
                    if lease.shrunk || t - lease.started < 300.0 {
                        continue;
                    }
                    if let Some(learned) = self.learned_peak_at(&lease.label, lease.started) {
                        let touched = self.rss_model(&lease.lease);
                        let reference = learned.max(touched);
                        let owed = lease.reserved.saturating_sub(touched);
                        if lease.reserved >= 4 * reference.max(1) && owed >= 8 * GIB {
                            lease.reserved = learned.max(touched);
                            lease.shrunk = true;
                        }
                    }
                }
            }

            // The box as the simulation has it: the measured curve, with
            // the modeled RSS of leases running in reality but not in the
            // sim added back, and the modeled RSS of leases running in the
            // sim but not in reality taken out.
            let mut available = self.available_at(t) as f64;
            for lease in &running {
                let really_running = self.really_running(&lease.lease, t);
                if !really_running {
                    available -= self.rss_model(&lease.lease) as f64;
                }
            }
            for (id, _) in self.runs.iter() {
                if self.really_running(id, t)
                    && !running.iter().any(|lease| lease.lease == *id)
                {
                    available += self.rss_model(id) as f64;
                }
            }
            let headroom = available.max(0.0) as u64;
            let owed: u64 = running
                .iter()
                .map(|lease| lease.reserved.saturating_sub(self.rss_model(&lease.lease)))
                .sum();
            let projected = headroom.saturating_sub(owed);
            if std::env::var("THOR_ADMIT_REPLAY_DEBUG").is_ok() && queue.len() == 1 {
                eprintln!(
                    "[{:.0}] head #{} {} peak {:.0}G: measured {:.1}G headroom {:.1}G owed {}",
                    t - self.start,
                    queue[0].lease,
                    queue[0].label,
                    queue[0].peak as f64 / 1_073_741_824.0,
                    self.available_at(t) as f64 / 1_073_741_824.0,
                    headroom as f64 / 1_073_741_824.0,
                    running
                        .iter()
                        .map(|lease| format!(
                            "#{} {:.0}G res, {:.1}G rss → owes {:.1}G",
                            lease.lease,
                            lease.reserved as f64 / 1_073_741_824.0,
                            self.rss_model(&lease.lease) as f64 / 1_073_741_824.0,
                            lease.reserved.saturating_sub(self.rss_model(&lease.lease)) as f64
                                / 1_073_741_824.0
                        ))
                        .collect::<Vec<_>>()
                        .join(" | ")
                );
            }

            // Admission. The head first; then, under EASY, the first
            // waiter behind it that may pass.
            let start_lease = |arrival: &Arrival, at: f64| SimLease {
                lease: arrival.lease,
                label: arrival.label.clone(),
                started: at,
                ends: at + self.duration_of(arrival),
                reserved: arrival.peak,
                shrunk: false,
            };
            if let Some(head) = queue.first().cloned() {
                if projected >= head.peak + floor {
                    if std::env::var("THOR_ADMIT_REPLAY_DEBUG").is_ok() {
                        eprintln!(
                            "[{:.0}] grant #{:<3} {:<28} peak {:>5.0}G projected {:>5.0}G \
                             running {} queue {}",
                            t - self.start,
                            head.lease,
                            head.label,
                            head.peak as f64 / 1_073_741_824.0,
                            projected as f64 / 1_073_741_824.0,
                            running.len(),
                            queue.len(),
                        );
                    }
                    queue.remove(0);
                    grants.insert(head.lease, t);
                    running.push(start_lease(&head, t));
                    t += step;
                    continue;
                }
            }
            if let (Some(bound), Some(head)) = (policy.bound_s, queue.first().cloned()) {
                let head_waited = t - head.at;
                let running_view: Vec<Running> = running
                    .iter()
                    .map(|lease| Running {
                        reserved: lease.reserved,
                        remaining_s: self
                            .duration_estimate_at(&lease.label, lease.started)
                            // An estimate the run has outlasted was
                            // demonstrated wrong: no estimate.
                            .filter(|estimate| *estimate > t - lease.started),
                    })
                    .collect();
                for index in 1..queue.len() {
                    let candidate = queue[index].clone();
                    if projected < candidate.peak + floor {
                        continue;
                    }
                    let estimate = self.duration_estimate_at(&candidate.label, candidate.at);
                    if may_backfill(
                        head.peak,
                        floor,
                        projected,
                        &running_view,
                        candidate.peak,
                        estimate,
                        head_waited,
                        bound,
                    ) {
                        queue.remove(index);
                        grants.insert(candidate.lease, t);
                        backfilled.insert(candidate.lease);
                        running.push(start_lease(&candidate, t));
                        break;
                    }
                }
            }
            t += step;
        }

        let result = SimResult {
            grants,
            backfilled,
            coalesced,
            end: self.end,
        };
        // Validation is only meaningful for strict fifo (what ran).
        let mut validation = Validation::default();
        if policy.bound_s.is_none() && !policy.coalesce && !policy.phase {
            for (lease, at) in result.grants.iter() {
                match self.runs.get(lease).and_then(|run| run.granted_at) {
                    Some(real) => validation.errors.push((*at - real).abs()),
                    None => validation.phantoms.push(*lease),
                }
            }
            validation.errors.sort_by(|a, b| a.total_cmp(b));
        }
        (result, validation)
    }

    /// Was this lease really running at `t`, per the log?
    fn really_running(&self, lease: &u64, t: f64) -> bool {
        self.runs
            .get(lease)
            .map_or(false, |run| {
                run.granted_at.map_or(false, |granted| granted <= t)
                    && run.released_at.map_or(true, |released| released > t)
            })
    }

    /// How long a lease holds its promise once the simulation starts it.
    fn duration_of(&self, arrival: &Arrival) -> f64 {
        if let Some(run) = self.runs.get(&arrival.lease) {
            if let Some(duration) = run.duration.filter(|d| *d > 0.0) {
                return duration;
            }
            // Granted in reality but killed without a duration (the client
            // went): the release still named its end; use the span.
            if let (Some(granted), Some(released)) = (run.granted_at, run.released_at) {
                return (released - granted).max(1.0);
            }
            // Never released at all: it held its promise to the end of the
            // trace, and the simulation says the same.
            return f64::INFINITY;
        }
        // A counterfactual run: the estimate the rule itself used.
        self.duration_estimate_at(&arrival.label, arrival.at)
            .unwrap_or(self.median_duration)
    }
}

/// The history's teaching rule, applied the way `PeakRecord::teaches`
/// applies it.
fn teaches(record: &thor_admit::history::PeakRecord) -> bool {
    if record.peak_source == "overrun" {
        return true;
    }
    record.exit_code.unwrap_or(0) == 0
        && record.duration_s >= thor_admit::history::MIN_LEARNED_DURATION_S
}

/// `History` has no clone; hold the snapshot's records under a path
/// nothing will write to (the replay only reads).
fn clone_history(history: &thor_admit::history::History) -> thor_admit::history::History {
    thor_admit::history::History::from_records(
        PathBuf::from("/nonexistent").as_path(),
        history.records(),
    )
}

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

#[derive(Default)]
struct Validation {
    errors: Vec<f64>,
    /// Waiters the model granted that reality never granted at all: dead
    /// clients, whose waiters the real queue carried for hours.
    phantoms: Vec<u64>,
}

struct SimResult {
    /// lease → grant time. Coalesced-away asks and never-granted waiters
    /// are absent.
    grants: HashMap<u64, f64>,
    backfilled: HashSet<u64>,
    coalesced: HashSet<u64>,
    #[allow(dead_code)]
    end: f64,
}

fn report_validation(validation: &Validation) {
    println!("\n## validation: strict fifo against what really happened");
    if validation.errors.is_empty() {
        println!("no comparable grants (the window granted nothing the model also grants)");
        return;
    }
    let errors = &validation.errors;
    let mean = errors.iter().sum::<f64>() / errors.len() as f64;
    let median = errors[errors.len() / 2];
    let within_30 = errors.iter().filter(|error| **error <= 30.0).count();
    println!(
        "{} grants compared: |simulated − real| median {:.0}s, mean {:.0}s, max {:.0}s; \
         {} of {} within 30 s",
        errors.len(),
        median,
        mean,
        errors.iter().cloned().fold(0.0, f64::max),
        within_30,
        errors.len(),
    );
    if !validation.phantoms.is_empty() {
        println!(
            "{} waiters the model granted that reality never did — dead clients, dropped \
             from every policy below (lease ids {:?})",
            validation.phantoms.len(),
            validation.phantoms
        );
    }
}

fn report_table(results: &[(Policy, SimResult)], trace: &Trace) {
    println!("\n## the queue, policy by policy");
    println!(
        "{:<26} {:>8} {:>8} {:>9} {:>9}",
        "policy", "granted", "waiting", "backfill", "coalescd"
    );
    for (policy, result) in results {
        let mut granted = 0usize;
        for arrival in &trace.arrivals {
            if result.coalesced.contains(&arrival.lease) {
                continue;
            }
            if result.grants.contains_key(&arrival.lease) {
                granted += 1;
            }
        }
        let still_waiting = trace
            .arrivals
            .iter()
            .filter(|arrival| {
                !result.coalesced.contains(&arrival.lease)
                    && !result.grants.contains_key(&arrival.lease)
            })
            .count();
        println!(
            "{:<26} {:>8} {:>8} {:>9} {:>9}",
            policy.name(),
            granted,
            still_waiting,
            result.backfilled.len(),
            result.coalesced.len(),
        );
    }

    // The class the backfill rule is for: the requests of 12 GiB or less
    // that waited behind the blocking head. Their number granted and their
    // number still waiting are the first two columns, because the wait
    // percentiles alone hide the trade: a policy that grants fewer of them
    // has a *shorter* median wait among the ones it granted.
    println!("\n## the requests of 12 GiB or less (the class behind the blocking head)");
    println!(
        "{:<26} {:>8} {:>8}   {:>20}",
        "policy", "granted", "waiting", "wait p50/p95/max"
    );
    for (policy, result) in results {
        let mut small: Vec<f64> = Vec::new();
        let mut granted = 0usize;
        let mut waiting = 0usize;
        for arrival in &trace.arrivals {
            if result.coalesced.contains(&arrival.lease) {
                continue;
            }
            if arrival.peak > 12 * GIB {
                continue;
            }
            match result.grants.get(&arrival.lease) {
                Some(at) => {
                    granted += 1;
                    small.push(at - arrival.at);
                }
                None => waiting += 1,
            }
        }
        small.sort_by(|a, b| a.total_cmp(b));
        let pick = |values: &[f64], q: f64| -> String {
            if values.is_empty() {
                "-".to_string()
            } else {
                format!("{:.0}", values[((values.len() as f64 - 1.0) * q) as usize])
            }
        };
        println!(
            "{:<26} {:>8} {:>8}   {:>20}",
            policy.name(),
            granted,
            waiting,
            format!("{}/{}/{}", pick(&small, 0.5), pick(&small, 0.95), pick(&small, 1.0)),
        );
    }

    // The leases the round is about: the biggest never-granted waiter under
    // fifo (the blocking head), the small ones behind it, and the big
    // reservation that held the room.
    for (policy, result) in results.iter() {
        if !result.backfilled.is_empty() {
            let names: Vec<String> = result
                .backfilled
                .iter()
                .filter_map(|lease| {
                    trace.arrival_of(lease).map(|arrival| {
                        format!(
                            "#{} {} ({:.0}G) at +{:.0}s",
                            arrival.lease,
                            arrival.label,
                            arrival.peak as f64 / 1_073_741_824.0,
                            result.grants.get(lease).copied().unwrap_or(0.0) - arrival.at
                        )
                    })
                })
                .collect();
            println!("backfilled under {}: {}", policy.name(), names.join(", "));
        }
    }
    println!("\n## particular leases (wait until granted, seconds; the window is {:.0}s)",
        trace.end - trace.start,
    );
    let fifo = &results[0].1;
    let mut stars: Vec<(u64, String)> = Vec::new();
    let mut never: Vec<&Arrival> = trace
        .arrivals
        .iter()
        .filter(|arrival| !fifo.grants.contains_key(&arrival.lease))
        .collect();
    never.sort_by(|a, b| b.peak.cmp(&a.peak).then(a.at.total_cmp(&b.at)));
    for arrival in never.iter().take(3) {
        stars.push((
            arrival.lease,
            format!("{} {}", arrival.label, thor_admit::sizes::human(arrival.peak)),
        ));
    }
    let mut behind: Vec<&Arrival> = trace
        .arrivals
        .iter()
        .filter(|arrival| {
            arrival.peak <= 12 * GIB && !fifo.grants.contains_key(&arrival.lease)
        })
        .collect();
    behind.sort_by(|a, b| a.at.total_cmp(&b.at));
    for arrival in behind.iter().take(3) {
        stars.push((
            arrival.lease,
            format!("{} {}", arrival.label, thor_admit::sizes::human(arrival.peak)),
        ));
    }
    // The over-reservation the phase cue would have named: the running
    // lease with the largest owed promise that never released.
    let mut owed: Vec<(u64, u64, String)> = trace
        .runs
        .iter()
        .filter(|(_, run)| run.granted_at.is_some() && run.released_at.is_none())
        .filter_map(|(lease, _run)| {
            trace
                .arrival_of(lease)
                .map(|arrival| (*lease, arrival.peak, arrival.label.clone()))
                .or(Some((*lease, 0, format!("lease {lease}"))))
        })
        .collect();
    owed.sort_by(|a, b| b.1.cmp(&a.1));
    for (lease, peak, label) in owed.iter().take(1) {
        stars.push((
            *lease,
            format!(
                "{label} {} reserved, never released",
                thor_admit::sizes::human(*peak)
            ),
        ));
    }
    print!("{:<34}", "lease");
    for (policy, _) in results {
        print!("{:>18}", policy.name());
    }
    println!();
    for (lease, note) in &stars {
        print!("{:<34}", format!("#{lease} {note}"));
        for (_, result) in results {
            let cell = match result.grants.get(lease) {
                Some(at) => match trace.arrival_of(lease) {
                    Some(arrival) => format!("{:.0}", at - arrival.at),
                    None => format!("{:.0}", at - trace.start),
                },
                None => {
                    if result.coalesced.contains(lease) {
                        "coalesced".to_string()
                    } else {
                        "never".to_string()
                    }
                }
            };
            print!("{:>18}", cell);
        }
        println!();
    }

    // The head-delay guarantee: a policy that passes requests around the
    // head must not start the blocking head later than strict fifo did.
    println!();
    if let Some((head, note)) = stars.first() {
        let fifo_head = fifo.grants.get(head).copied();
        println!("the blocking head is #{head} {note}");
        for (policy, result) in results.iter().skip(1) {
            let policy_at = result.grants.get(head).copied();
            // What each policy did with the head, said plainly.
            let happened = match (fifo_head, policy_at) {
                (Some(fifo_at), Some(at)) => format!(
                    "fifo started it {:.0}s in, this policy {:.0}s in",
                    fifo_at - trace.start,
                    at - trace.start
                ),
                (Some(fifo_at), None) => format!(
                    "fifo started it {:.0}s in, this policy never started it",
                    fifo_at - trace.start
                ),
                (None, Some(at)) => format!(
                    "fifo never started it, this policy started it {:.0}s in",
                    at - trace.start
                ),
                (None, None) => "neither started it inside the window".to_string(),
            };
            if policy.bound_s.is_none() {
                // The guarantee is the backfill rule's; a policy without
                // backfill makes no promise about the head's start.
                println!("  {:<24} {happened}", policy.name());
                continue;
            }
            let verdict = match (fifo_head, policy_at) {
                // Both started it: the pass must not have moved it later.
                (Some(fifo_at), Some(at)) => {
                    if at <= fifo_at {
                        "holds".to_string()
                    } else {
                        "VIOLATED".to_string()
                    }
                }
                // fifo started it and this policy did not: the head waits
                // longer than it did, which is the failure the rule forbids.
                (Some(_), None) => "VIOLATED".to_string(),
                // fifo never started it: no start can be delayed, and a
                // policy that starts it is ahead of fifo, not behind it.
                (None, Some(_)) => "holds (fifo never started it)".to_string(),
                (None, None) => {
                    "holds trivially (fifo never started it either)".to_string()
                }
            };
            println!("  {:<24} {verdict}: {happened}", policy.name());
        }
    }
}

// ---------------------------------------------------------------------------
// The clock
// ---------------------------------------------------------------------------

/// Parse `2026-11-01T15:23:55Z` (a fractional second is tolerated) into
/// seconds since the epoch. The daemon's log clock is UTC, whole seconds.
fn parse_clock(text: &str) -> Option<f64> {
    let text = text.trim();
    let bytes = text.as_bytes();
    if bytes.len() < 20 || bytes[4] != b'-' || bytes[7] != b'-' || bytes[10] != b'T' {
        return None;
    }
    let year: i64 = text.get(0..4)?.parse().ok()?;
    let month: i64 = text.get(5..7)?.parse().ok()?;
    let day: i64 = text.get(8..10)?.parse().ok()?;
    let hour: i64 = text.get(11..13)?.parse().ok()?;
    let minute: i64 = text.get(14..16)?.parse().ok()?;
    let second: f64 = text.get(17..19)?.parse().ok()?;
    let days = days_from_civil(year, month, day);
    Some((days * 86400 + hour * 3600 + minute * 60) as f64 + second)
}

/// Days since 1970-01-01 (Howard Hinnant's `days_from_civil`).
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let year_of_era = year - era * 400;
    let month_shift = if month > 2 { month - 3 } else { month + 9 };
    let day_of_year = (153 * month_shift + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146097 + day_of_era - 719468
}

/// Seconds since the epoch back to the daemon's clock text.
fn clock_text(t: f64) -> String {
    let days = t.div_euclid(86400.0) as i64;
    let seconds_of_day = t.rem_euclid(86400.0) as i64;
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        seconds_of_day / 3600,
        (seconds_of_day % 3600) / 60,
        seconds_of_day % 60
    )
}

fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let day_of_era = z - era * 146097;
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36524 - day_of_era / 146096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let mp = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    (if month <= 2 { year + 1 } else { year }, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_clock_round_trips_the_daemons_own_stamps() {
        let text = "2026-11-01T15:23:55Z";
        let t = parse_clock(text).unwrap();
        assert_eq!(clock_text(t), text);
        assert_eq!(parse_clock("2026-11-01T15:23:55.123Z"), Some(t));
    }

    #[test]
    fn the_civil_algorithms_agree_with_known_dates() {
        assert_eq!(days_from_civil(1970, 1, 1), 0);
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        // 2026-01-01 is 56 years on: 56 * 365 + 14 leap days = 20454.
        assert_eq!(days_from_civil(2026, 1, 1), 20454);
        assert_eq!(civil_from_days(20454), (2026, 1, 1));
        // And 2026-11-01 is 304 days later (2026 is not a leap year).
        assert_eq!(days_from_civil(2026, 11, 1), 20758);
        assert_eq!(civil_from_days(20758), (2026, 11, 1));
    }
}
