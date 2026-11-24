//! The domain model: jobs, bids, awards, checkpoints, change orders, closes,
//! retoolings — and the replay that rebuilds all of it from the ledger.
//!
//! Nothing is stored twice. The ledger rows are the record; this module folds
//! them into the state the rest of the program reasons about. A number that
//! appears in a report is always either read from a row or recomputed from
//! rows — never remembered from a previous run.

use crate::clause::{self, Clause};
use crate::forecast::{self, Forecast, ForecastVerdict};
use crate::json::Json;
use crate::ledger::Row;
use crate::verdict::Verdict;

#[derive(Clone, Debug, PartialEq)]
pub enum JobStatus {
    Open,
    Awarded,
    Closed,
    Cancelled,
}

impl JobStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            JobStatus::Open => "open",
            JobStatus::Awarded => "awarded",
            JobStatus::Closed => "closed",
            JobStatus::Cancelled => "cancelled",
        }
    }
}

/// The goal line: what "done" means, in a form a machine can check.
#[derive(Clone, Debug)]
pub struct Acceptance {
    /// "cmd" (a command that must exit 0), "metric" (a named number that must
    /// cross a threshold), or "report" (a human/desk judgement, used only for
    /// reconstructed history where no command was ever written down).
    pub kind: String,
    pub cmd: String,
    pub metric: String,
    pub threshold: Option<f64>,
    pub note: String,
}

impl Acceptance {
    pub fn describe(&self) -> String {
        match self.kind.as_str() {
            "cmd" => format!("`{}` exits 0", self.cmd),
            "metric" => match self.threshold {
                Some(t) => format!("`{}` >= {}", self.metric, t),
                None => format!("`{}` crosses its threshold", self.metric),
            },
            other => other.to_string(),
        }
    }

    fn from_json(v: &Json) -> Acceptance {
        Acceptance {
            kind: v.str_at("kind").unwrap_or("report").to_string(),
            cmd: v.str_at("cmd").unwrap_or("").to_string(),
            metric: v.str_at("metric").unwrap_or("").to_string(),
            threshold: v.f64_at("threshold"),
            note: v.str_at("note").unwrap_or("").to_string(),
        }
    }

    #[allow(dead_code)]
    pub fn to_json(&self) -> Json {
        let mut o = Json::obj();
        o.set("kind", Json::s(self.kind.clone()));
        o.set("cmd", Json::s(self.cmd.clone()));
        o.set("metric", Json::s(self.metric.clone()));
        o.set(
            "threshold",
            match self.threshold {
                Some(t) => Json::n(t),
                None => Json::Null,
            },
        );
        o.set("note", Json::s(self.note.clone()));
        o
    }
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct Bid {
    pub id: String,
    pub job_id: String,
    pub sub: String,
    /// The promise: crew-time in minutes. `None` for a bid whose promise was
    /// never written down (reconstructed history uses the plan allowance as
    /// a proxy instead, and says so with `proxy`).
    pub crew_min: Option<f64>,
    pub job_min: Option<f64>,
    pub confidence: f64,
    pub milestones: Vec<String>,
    pub computed: bool,
    /// A proxy bid stands for the seat's plan allowance, not for a promise
    /// the seat made. Its overrun means the seat blew its plan window.
    pub proxy: bool,
    /// Whether this run is clean enough to calibrate a bid from: it finished
    /// its work without being cut short by a quota stop or a relaunch.
    pub calibratable: bool,
    pub basis: String,
    pub ts: String,
}

impl Bid {
    pub fn from_json(v: &Json) -> Bid {
        let milestones = v
            .get("milestones")
            .and_then(|m| m.as_arr())
            .map(|items| {
                items
                    .iter()
                    .filter_map(|i| i.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        Bid {
            id: v.str_at("id").unwrap_or("").to_string(),
            job_id: v.str_at("job_id").unwrap_or("").to_string(),
            sub: v.str_at("sub").unwrap_or("").to_string(),
            crew_min: v.f64_at("crew_min"),
            job_min: v.f64_at("job_min"),
            confidence: v.f64_at("confidence").unwrap_or(0.0),
            milestones,
            computed: v.bool_at("computed").unwrap_or(false),
            proxy: v.bool_at("proxy").unwrap_or(false),
            calibratable: v.bool_at("calibratable").unwrap_or(true),
            basis: v.str_at("basis").unwrap_or("").to_string(),
            ts: v.str_at("ts").unwrap_or("").to_string(),
        }
    }

    #[allow(dead_code)]
    pub fn to_json(&self) -> Json {
        let mut o = Json::obj();
        o.set("id", Json::s(self.id.clone()));
        o.set("job_id", Json::s(self.job_id.clone()));
        o.set("sub", Json::s(self.sub.clone()));
        o.set(
            "crew_min",
            match self.crew_min {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        o.set(
            "job_min",
            match self.job_min {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        o.set("confidence", Json::n(self.confidence));
        let mut ms = Json::arr();
        for m in &self.milestones {
            ms.push(Json::s(m.clone()));
        }
        o.set("milestones", ms);
        o.set("computed", Json::b(self.computed));
        o.set("proxy", Json::b(self.proxy));
        o.set("calibratable", Json::b(self.calibratable));
        o.set("basis", Json::s(self.basis.clone()));
        o.set("ts", Json::s(self.ts.clone()));
        o
    }
}

/// One clause check, as recorded at a checkpoint or a close.
#[derive(Clone, Debug)]
pub struct ClauseResult {
    pub metric: String,
    pub verdict: Verdict,
    /// The value the clause was checked against, when there was one.
    pub value: Option<f64>,
    pub penalty_min: f64,
}

impl ClauseResult {
    fn from_json(v: &Json) -> ClauseResult {
        ClauseResult {
            metric: v.str_at("metric").unwrap_or("").to_string(),
            verdict: v
                .str_at("verdict")
                .and_then(Verdict::parse)
                .unwrap_or(Verdict::Inconclusive),
            value: v.f64_at("value"),
            penalty_min: v.f64_at("penalty_min").unwrap_or(0.0),
        }
    }

    pub fn to_json(&self) -> Json {
        let mut o = Json::obj();
        o.set("metric", Json::s(self.metric.clone()));
        o.set("verdict", Json::s(self.verdict.as_str()));
        o.set(
            "value",
            match self.value {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        o.set("penalty_min", Json::n(self.penalty_min));
        o
    }
}

fn clause_results_from_json(v: Option<&Json>) -> Vec<ClauseResult> {
    v.and_then(|x| x.as_arr())
        .map(|items| items.iter().map(ClauseResult::from_json).collect())
        .unwrap_or_default()
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct Checkpoint {
    pub crew_used_min: f64,
    pub burn: f64,
    pub milestones_done: usize,
    pub note: String,
    /// True when the burn crossed the stop ratio without the goal line: from
    /// here the sub must stop and report, and the ledger refuses more burn
    /// until the GC issues a change order or cancels.
    pub stop_required: bool,
    /// The verdict of the acceptance check at this checkpoint. An old row
    /// that only said `acceptance_passed` stands for pass or fail; a row
    /// with no check at all is inconclusive.
    pub check_verdict: Verdict,
    pub check_by: String,
    pub check_exit_code: Option<i64>,
    pub check_note: String,
    /// Metric values in play at this checkpoint: those the seat reported
    /// and those gc computed, one entry each.
    pub metrics: Vec<(String, f64)>,
    /// Clause checks at this checkpoint.
    pub clauses: Vec<ClauseResult>,
    /// The spend-rate forecast as of this checkpoint.
    pub forecast: Option<Forecast>,
    pub ts: String,
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct ChangeOrder {
    pub seq: u32,
    pub reason: String,
    pub add_crew_min: f64,
    pub add_job_min: f64,
    pub ts: String,
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct CloseRec {
    pub accepted: bool,
    /// The verdict of the goal-line check at close: gc re-ran the
    /// acceptance command (or compared the metric, or took a human's word
    /// on a report-kind job). Inconclusive means the check could not run —
    /// the close stands, but it earns no credit and counts as neither a
    /// pass nor a miss in the reports.
    pub acceptance_verdict: Verdict,
    pub check_by: String,
    pub check_exit_code: Option<i64>,
    pub check_note: String,
    pub actual_crew_min: f64,
    pub actual_job_min: f64,
    pub late_days: f64,
    pub effective_bid_min: f64,
    pub overrun_min: f64,
    pub penalty_min: f64,
    /// The part of the penalty that came from breached clauses.
    pub clause_penalty_min: f64,
    /// Clause checks at close.
    pub clause_results: Vec<ClauseResult>,
    /// Debt added (or repaid) by this close. Negative means the underrun
    /// repaid debt.
    pub debt_delta_min: f64,
    pub repayment_min: f64,
    /// How crew-time was measured: "wall", "tokens" or "estimated".
    pub method: String,
    pub tokens: Option<u64>,
    pub goal_line: String,
    pub ts: String,
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct Retool {
    pub sub: String,
    pub class: String,
    pub reason: String,
    pub action: String,
    pub ts: String,
}

#[derive(Clone, Debug)]
// The record keeps fields the report does not print yet; they are part of
// what the ledger holds and are not dead weight.
#[allow(dead_code)]
pub struct Job {
    pub id: String,
    /// The caller's own id of this job — a builder-ide work order, a ticket.
    /// Empty when nobody said; gc's own id is always there.
    pub external_id: String,
    pub title: String,
    pub scope: String,
    pub class: String,
    pub acceptance: Acceptance,
    /// Job-time allowance in minutes (the T-minus).
    pub deadline_min: f64,
    /// The general contractor's own estimate of the crew-time the work
    /// needs. The seat's calibrated factor is applied to this.
    pub estimate_min: f64,
    /// Crew-time allowance in minutes (the ceiling).
    pub budget_min: f64,
    pub penalty_per_day_min: f64,
    /// The fraction of the bid's crew-time at which the sub must stop.
    pub stop_ratio: f64,
    /// Contract clauses written with the job (`--clause`).
    pub clauses: Vec<Clause>,
    /// Clauses the award negotiated on top (same metric = override).
    pub award_clauses: Vec<Clause>,
    /// When the award happened; the forecast and the clause windows count
    /// job-time from here.
    pub award_ts: String,
    pub created_ts: String,
    pub reconstructed: bool,
    pub source: String,
    pub status: JobStatus,
    pub awarded_bid: String,
    pub awarded_sub: String,
    pub checkpoints: Vec<Checkpoint>,
    pub change_orders: Vec<ChangeOrder>,
    pub close: Option<CloseRec>,
    pub cancel_reason: String,
}

impl Job {
    /// The bid ceiling in force: the awarded promise plus every change order.
    pub fn effective_bid_min(&self, bid: Option<&Bid>) -> f64 {
        let base = bid.and_then(|b| b.crew_min).unwrap_or(0.0);
        base + self.change_orders.iter().map(|c| c.add_crew_min).sum::<f64>()
    }

    /// The crew-time ceiling in force: the budget plus every change order.
    /// A change order extends the job, so the allowance moves with it.
    pub fn effective_budget_min(&self) -> f64 {
        self.budget_min + self.change_orders.iter().map(|c| c.add_crew_min).sum::<f64>()
    }

    /// The job-time allowance in force.
    pub fn effective_deadline_min(&self) -> f64 {
        self.deadline_min + self.change_orders.iter().map(|c| c.add_job_min).sum::<f64>()
    }

    pub fn awarded_bid<'a>(&self, bids: &'a [Bid]) -> Option<&'a Bid> {
        bids.iter()
            .find(|b| b.id == self.awarded_bid && !self.awarded_bid.is_empty())
    }

    /// The last checkpoint that demanded a stop, if any.
    pub fn last_stop(&self) -> Option<&Checkpoint> {
        self.checkpoints.iter().rev().find(|c| c.stop_required)
    }

    /// True when a change order was recorded after the stop demand, which is
    /// the GC's way of re-scoping or extending the job so work may continue.
    pub fn re_scoped_after_stop(&self) -> bool {
        match self.last_stop() {
            None => false,
            Some(stop) => self
                .change_orders
                .iter()
                .any(|c| c.ts.as_str() >= stop.ts.as_str()),
        }
    }

    /// The clauses in force: the job's own, with the award's overrides.
    pub fn clauses_in_force(&self) -> Vec<Clause> {
        clause::merge(&self.clauses, &self.award_clauses)
    }

    /// Job-minutes from the award to `ts`, when both timestamps parse.
    pub fn job_elapsed_min_at(&self, ts: &str) -> Option<f64> {
        if self.award_ts.is_empty() {
            None
        } else {
            forecast::elapsed_minutes(&self.award_ts, ts)
        }
    }
}

#[derive(Clone, Debug)]
pub struct State {
    pub jobs: Vec<Job>,
    pub bids: Vec<Bid>,
    pub retools: Vec<Retool>,
    pub rows: usize,
}

impl State {
    pub fn job(&self, id: &str) -> Option<&Job> {
        self.jobs.iter().find(|j| j.id == id)
    }

    pub fn job_mut(&mut self, id: &str) -> Option<&mut Job> {
        self.jobs.iter_mut().find(|j| j.id == id)
    }

    /// Bids for a job, in ledger order.
    pub fn bids_for(&self, job_id: &str) -> Vec<&Bid> {
        self.bids.iter().filter(|b| b.job_id == job_id).collect()
    }

    /// Next free job id.
    pub fn next_job_id(&self) -> String {
        format!("J{:03}", self.jobs.len() + 1)
    }

    /// Next free bid id.
    pub fn next_bid_id(&self) -> String {
        format!("B{:03}", self.bids.len() + 1)
    }

    /// Debt carried by a subcontractor on a job class, in crew-minutes.
    /// Recomputed by summing the debt deltas recorded at each close.
    pub fn debt_min(&self, sub: &str, class: &str) -> f64 {
        let mut total = 0.0;
        for job in &self.jobs {
            if job.class != class {
                continue;
            }
            if let Some(close) = &job.close {
                if job.awarded_sub == sub {
                    total += close.debt_delta_min;
                }
            }
        }
        total
    }

    /// A retooling recorded for this subcontractor on this class at or after
    /// the given timestamp. The ledger's clock has one-second resolution, so
    /// a retool recorded in the same second as the close that opened the
    /// debt counts as being after it.
    pub fn retooled_after(&self, sub: &str, class: &str, ts: &str) -> Option<&Retool> {
        self.retools
            .iter()
            .filter(|r| r.sub == sub && r.class == class && r.ts.as_str() >= ts)
            .next_back()
    }
}

/// Rebuild the state from the ledger rows.
pub fn replay(rows: &[Row]) -> State {
    let mut state = State {
        jobs: Vec::new(),
        bids: Vec::new(),
        retools: Vec::new(),
        rows: rows.len(),
    };

    for row in rows {
        match row.kind.as_str() {
            "job.new" => {
                let job = Job {
                    id: row.body.str_at("id").unwrap_or("").to_string(),
                    external_id: row.body.str_at("external_id").unwrap_or("").to_string(),
                    title: row.body.str_at("title").unwrap_or("").to_string(),
                    scope: row.body.str_at("scope").unwrap_or("").to_string(),
                    class: row.body.str_at("class").unwrap_or("").to_string(),
                    acceptance: row
                        .body
                        .get("acceptance")
                        .map(Acceptance::from_json)
                        .unwrap_or(Acceptance {
                            kind: "report".to_string(),
                            cmd: String::new(),
                            metric: String::new(),
                            threshold: None,
                            note: String::new(),
                        }),
                    deadline_min: row.body.f64_at("deadline_min").unwrap_or(0.0),
                    estimate_min: row
                        .body
                        .f64_at("estimate_min")
                        .unwrap_or(row.body.f64_at("budget_min").unwrap_or(0.0)),
                    budget_min: row.body.f64_at("budget_min").unwrap_or(0.0),
                    penalty_per_day_min: row.body.f64_at("penalty_per_day_min").unwrap_or(30.0),
                    stop_ratio: row.body.f64_at("stop_ratio").unwrap_or(0.8),
                    clauses: clause::from_json_array(row.body.get("clauses")),
                    award_clauses: Vec::new(),
                    award_ts: String::new(),
                    created_ts: row.ts.clone(),
                    reconstructed: row.body.bool_at("reconstructed").unwrap_or(false),
                    source: row.body.str_at("source").unwrap_or("").to_string(),
                    status: JobStatus::Open,
                    awarded_bid: String::new(),
                    awarded_sub: String::new(),
                    checkpoints: Vec::new(),
                    change_orders: Vec::new(),
                    close: None,
                    cancel_reason: String::new(),
                };
                state.jobs.push(job);
            }
            "bid.new" => {
                state.bids.push(Bid::from_json(&row.body));
            }
            "award" => {
                let job_id = row.body.str_at("job_id").unwrap_or("").to_string();
                if let Some(job) = state.job_mut(&job_id) {
                    job.awarded_bid = row.body.str_at("bid_id").unwrap_or("").to_string();
                    job.awarded_sub = row.body.str_at("sub").unwrap_or("").to_string();
                    job.award_clauses = clause::from_json_array(row.body.get("clauses"));
                    job.award_ts = row.ts.clone();
                    if job.status == JobStatus::Open {
                        job.status = JobStatus::Awarded;
                    }
                }
            }
            "checkpoint" => {
                let job_id = row.body.str_at("job_id").unwrap_or("").to_string();
                if let Some(job) = state.job_mut(&job_id) {
                    job.checkpoints.push(Checkpoint {
                        crew_used_min: row.body.f64_at("crew_used_min").unwrap_or(0.0),
                        burn: row.body.f64_at("burn").unwrap_or(0.0),
                        milestones_done: row.body.u64_at("milestones_done").unwrap_or(0) as usize,
                        note: row.body.str_at("note").unwrap_or("").to_string(),
                        stop_required: row.body.bool_at("stop_required").unwrap_or(false),
                        check_verdict: checkpoint_verdict(&row.body),
                        check_by: row
                            .body
                            .get("check")
                            .and_then(|c| c.str_at("by"))
                            .unwrap_or("")
                            .to_string(),
                        check_exit_code: row
                            .body
                            .get("check")
                            .and_then(|c| c.f64_at("exit_code"))
                            .map(|c| c as i64),
                        check_note: row
                            .body
                            .get("check")
                            .and_then(|c| c.str_at("note"))
                            .unwrap_or("")
                            .to_string(),
                        metrics: metrics_from_json(row.body.get("metrics")),
                        clauses: clause_results_from_json(row.body.get("clauses")),
                        forecast: row.body.get("forecast").map(forecast_from_json),
                        ts: row.ts.clone(),
                    });
                }
            }
            "change-order" => {
                let job_id = row.body.str_at("job_id").unwrap_or("").to_string();
                if let Some(job) = state.job_mut(&job_id) {
                    job.change_orders.push(ChangeOrder {
                        seq: row.body.u64_at("seq").unwrap_or(0) as u32,
                        reason: row.body.str_at("reason").unwrap_or("").to_string(),
                        add_crew_min: row.body.f64_at("add_crew_min").unwrap_or(0.0),
                        add_job_min: row.body.f64_at("add_job_min").unwrap_or(0.0),
                        ts: row.ts.clone(),
                    });
                }
            }
            "close" => {
                let job_id = row.body.str_at("job_id").unwrap_or("").to_string();
                if let Some(job) = state.job_mut(&job_id) {
                    job.close = Some(CloseRec {
                        accepted: row.body.bool_at("accepted").unwrap_or(false),
                        acceptance_verdict: row
                            .body
                            .str_at("acceptance_verdict")
                            .and_then(Verdict::parse)
                            .unwrap_or_else(|| {
                                Verdict::from_claim(row.body.bool_at("accepted").unwrap_or(false))
                            }),
                        check_by: row
                            .body
                            .get("check")
                            .and_then(|c| c.str_at("by"))
                            .unwrap_or("")
                            .to_string(),
                        check_exit_code: row
                            .body
                            .get("check")
                            .and_then(|c| c.f64_at("exit_code"))
                            .map(|c| c as i64),
                        check_note: row
                            .body
                            .get("check")
                            .and_then(|c| c.str_at("note"))
                            .unwrap_or("")
                            .to_string(),
                        actual_crew_min: row.body.f64_at("actual_crew_min").unwrap_or(0.0),
                        actual_job_min: row.body.f64_at("actual_job_min").unwrap_or(0.0),
                        late_days: row.body.f64_at("late_days").unwrap_or(0.0),
                        effective_bid_min: row.body.f64_at("effective_bid_min").unwrap_or(0.0),
                        overrun_min: row.body.f64_at("overrun_min").unwrap_or(0.0),
                        penalty_min: row.body.f64_at("penalty_min").unwrap_or(0.0),
                        clause_penalty_min: row.body.f64_at("clause_penalty_min").unwrap_or(0.0),
                        clause_results: clause_results_from_json(row.body.get("clauses")),
                        debt_delta_min: row.body.f64_at("debt_delta_min").unwrap_or(0.0),
                        repayment_min: row.body.f64_at("repayment_min").unwrap_or(0.0),
                        method: row.body.str_at("method").unwrap_or("estimated").to_string(),
                        tokens: row.body.u64_at("tokens"),
                        goal_line: row.body.str_at("goal_line").unwrap_or("").to_string(),
                        ts: row.ts.clone(),
                    });
                    job.status = JobStatus::Closed;
                }
            }
            "cancel" => {
                let job_id = row.body.str_at("job_id").unwrap_or("").to_string();
                if let Some(job) = state.job_mut(&job_id) {
                    job.status = JobStatus::Cancelled;
                    job.cancel_reason = row.body.str_at("reason").unwrap_or("").to_string();
                }
            }
            "retool" => {
                state.retools.push(Retool {
                    sub: row.body.str_at("sub").unwrap_or("").to_string(),
                    class: row.body.str_at("class").unwrap_or("").to_string(),
                    reason: row.body.str_at("reason").unwrap_or("").to_string(),
                    action: row.body.str_at("action").unwrap_or("").to_string(),
                    ts: row.ts.clone(),
                });
            }
            _ => {}
        }
    }
    state
}

/// The verdict of a checkpoint's acceptance check, in the order the ledger
/// learned it: the three-valued `check.verdict` when the row has one, the
/// old `acceptance_passed` boolean when that is all it says, and
/// inconclusive when the row never recorded a check.
fn checkpoint_verdict(body: &Json) -> Verdict {
    if let Some(v) = body.get("check").and_then(|c| c.str_at("verdict")) {
        if let Some(verdict) = Verdict::parse(v) {
            return verdict;
        }
    }
    match body.bool_at("acceptance_passed") {
        Some(passed) => Verdict::from_claim(passed),
        None => Verdict::Inconclusive,
    }
}

fn metrics_from_json(v: Option<&Json>) -> Vec<(String, f64)> {
    v.and_then(|x| x.as_arr())
        .map(|items| {
            items
                .iter()
                .filter_map(|m| {
                    let name = m.str_at("name")?.to_string();
                    let value = m.f64_at("value")?;
                    Some((name, value))
                })
                .collect()
        })
        .unwrap_or_default()
}

fn forecast_from_json(v: &Json) -> Forecast {
    Forecast {
        rate_per_job_min: v.f64_at("rate_per_job_min"),
        projected_crew_at_deadline: v.f64_at("projected_crew_at_deadline"),
        minutes_to_stop_line: v.f64_at("minutes_to_stop_line"),
        verdict: v
            .str_at("verdict")
            .and_then(ForecastVerdict::parse)
            .unwrap_or(ForecastVerdict::Inconclusive),
        note: v.str_at("note").unwrap_or("").to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A v1 checkpoint row, with only the boolean: it must replay as pass,
    /// and a row with no check at all as inconclusive — history neither
    /// changes meaning nor quietly turns into misses.
    #[test]
    fn old_checkpoint_rows_keep_their_meaning() {
        let mut body = Json::obj();
        body.set("acceptance_passed", Json::b(true));
        assert_eq!(checkpoint_verdict(&body), Verdict::Pass);
        body.set("acceptance_passed", Json::b(false));
        assert_eq!(checkpoint_verdict(&body), Verdict::Fail);

        let bare = Json::obj();
        assert_eq!(checkpoint_verdict(&bare), Verdict::Inconclusive);

        let mut check = Json::obj();
        check.set("verdict", Json::s("inconclusive"));
        let mut modern = Json::obj();
        modern.set("check", check);
        assert_eq!(checkpoint_verdict(&modern), Verdict::Inconclusive);
    }

    #[test]
    fn an_old_close_row_replays_with_its_verdict_derived() {
        let mut body = Json::obj();
        body.set("accepted", Json::b(true));
        // accepted: true with no recorded verdict reads as a pass.
        assert_eq!(
            body.str_at("acceptance_verdict")
                .and_then(Verdict::parse)
                .unwrap_or_else(|| Verdict::from_claim(body.bool_at("accepted").unwrap_or(false))),
            Verdict::Pass
        );
    }
}
