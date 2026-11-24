//! The arithmetic of finishing a job: overrun, penalty, debt and repayment.
//!
//! Kept in one place so the numbers in the ledger, the numbers in the report
//! and the numbers in the tests cannot drift apart.

use crate::model::{Bid, Job};

#[derive(Clone, Debug)]
pub struct CloseOutcome {
    /// Days past the job-time allowance.
    pub late_days: f64,
    /// The promise in force when the job closed (bid plus change orders).
    pub effective_bid_min: f64,
    /// Crew-minutes spent beyond the promise.
    pub overrun_min: f64,
    /// Penalty for the late days.
    pub penalty_min: f64,
    /// Debt repaid by an underrun (never more than the debt carried).
    pub repayment_min: f64,
    /// Change to the debt: positive is debt taken on, negative is repaid.
    pub debt_delta_min: f64,
}

/// Work out how a job ended.
///
/// `current_debt_min` is what the subcontractor already carried on this job
/// class before this job; an underrun repays that debt, never more.
/// `clause_penalty_min` is what breached contract clauses cost (already
/// computed from the clause records); it lands on top of the late penalty.
pub fn close_outcome(
    job: &Job,
    bid: Option<&Bid>,
    actual_crew_min: f64,
    actual_job_min: f64,
    late_days_override: Option<f64>,
    current_debt_min: f64,
    accepted: bool,
    clause_penalty_min: f64,
) -> CloseOutcome {
    let effective_bid_min = job.effective_bid_min(bid);
    let effective_deadline_min = job.effective_deadline_min();

    // With no promise in force there is nothing to overrun and no deadline
    // to be late against. A pi seat is billed in tokens: its history has no
    // minute allowance, so it carries no overrun debt and no lateness.
    let has_promise = effective_bid_min > 0.0;
    let has_deadline = effective_deadline_min > 0.0;

    let late_days = match late_days_override {
        Some(d) => d.max(0.0),
        None => {
            if has_deadline && actual_job_min > effective_deadline_min {
                ((actual_job_min - effective_deadline_min) / 1440.0).ceil()
            } else {
                0.0
            }
        }
    };

    let overrun_min = if has_promise {
        (actual_crew_min - effective_bid_min).max(0.0)
    } else {
        0.0
    };
    let penalty_min = if has_deadline {
        late_days * job.penalty_per_day_min
    } else {
        0.0
    } + clause_penalty_min.max(0.0);

    // An underrun repays debt, but only a job that actually delivered: work
    // that did not cross its goal line earns no credit.
    let underrun_min = (effective_bid_min - actual_crew_min).max(0.0);
    let repayment_min = if accepted {
        underrun_min.min(current_debt_min.max(0.0))
    } else {
        0.0
    };

    let debt_delta_min = overrun_min + penalty_min - repayment_min;

    CloseOutcome {
        late_days,
        effective_bid_min,
        overrun_min,
        penalty_min,
        repayment_min,
        debt_delta_min,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Acceptance;

    fn job() -> Job {
        Job {
            id: "J001".to_string(),
            external_id: String::new(),
            title: "t".to_string(),
            scope: "s".to_string(),
            class: "lab-experiment".to_string(),
            acceptance: Acceptance {
                kind: "cmd".to_string(),
                cmd: "cargo test".to_string(),
                metric: String::new(),
                threshold: None,
                note: String::new(),
            },
            deadline_min: 1440.0,
            estimate_min: 240.0,
            budget_min: 240.0,
            penalty_per_day_min: 30.0,
            stop_ratio: 0.8,
            clauses: Vec::new(),
            award_clauses: Vec::new(),
            award_ts: "2026-11-02T10:00:00Z".to_string(),
            created_ts: "2026-11-02T10:00:00Z".to_string(),
            reconstructed: false,
            source: String::new(),
            status: crate::model::JobStatus::Awarded,
            awarded_bid: "B001".to_string(),
            awarded_sub: "mcode".to_string(),
            checkpoints: Vec::new(),
            change_orders: Vec::new(),
            close: None,
            cancel_reason: String::new(),
        }
    }

    fn bid(crew: f64) -> Bid {
        Bid {
            id: "B001".to_string(),
            job_id: "J001".to_string(),
            sub: "mcode".to_string(),
            crew_min: Some(crew),
            job_min: Some(crew),
            confidence: 0.5,
            milestones: Vec::new(),
            computed: true,
            proxy: false,
            calibratable: true,
            basis: String::new(),
            ts: "2026-11-02T10:00:00Z".to_string(),
        }
    }

    #[test]
    fn an_overrun_becomes_debt() {
        let out = close_outcome(&job(), Some(&bid(120.0)), 150.0, 120.0, None, 0.0, true, 0.0);
        assert_eq!(out.overrun_min, 30.0);
        assert_eq!(out.penalty_min, 0.0);
        assert_eq!(out.debt_delta_min, 30.0);
        assert_eq!(out.late_days, 0.0);
    }

    #[test]
    fn late_days_cost_a_penalty() {
        // 2 days past a 1440-minute allowance.
        let out = close_outcome(&job(), Some(&bid(120.0)), 100.0, 1440.0 + 2880.0, None, 0.0, true, 0.0);
        assert_eq!(out.late_days, 2.0);
        assert_eq!(out.penalty_min, 60.0);
        assert_eq!(out.debt_delta_min, 60.0);
    }

    #[test]
    fn a_breached_clause_costs_its_penalty_on_top() {
        // One day late (30) plus a clause breach (45): 75 of penalty.
        let out = close_outcome(&job(), Some(&bid(120.0)), 100.0, 1440.0 + 1440.0, None, 0.0, true, 45.0);
        assert_eq!(out.penalty_min, 75.0);
        assert_eq!(out.debt_delta_min, 75.0);
    }

    #[test]
    fn an_underrun_repays_debt_but_no_more() {
        let out = close_outcome(&job(), Some(&bid(120.0)), 100.0, 100.0, None, 45.0, true, 0.0);
        assert_eq!(out.repayment_min, 20.0);
        assert_eq!(out.debt_delta_min, -20.0);

        let out2 = close_outcome(&job(), Some(&bid(120.0)), 100.0, 100.0, None, 5.0, true, 0.0);
        assert_eq!(out2.repayment_min, 5.0);
        assert_eq!(out2.debt_delta_min, -5.0);
    }

    #[test]
    fn work_that_did_not_land_earns_no_credit() {
        let out = close_outcome(&job(), Some(&bid(120.0)), 100.0, 100.0, None, 45.0, false, 0.0);
        assert_eq!(out.repayment_min, 0.0);
        assert_eq!(out.debt_delta_min, 0.0);
    }

    #[test]
    fn no_promise_means_no_overrun_and_no_debt() {
        // A pi seat: the history has no minute allowance to promise against.
        let mut j = job();
        j.budget_min = 0.0;
        j.deadline_min = 0.0;
        let out = close_outcome(&j, None, 400.0, 400.0, None, 0.0, true, 0.0);
        assert_eq!(out.overrun_min, 0.0);
        assert_eq!(out.penalty_min, 0.0);
        assert_eq!(out.debt_delta_min, 0.0);
        assert_eq!(out.late_days, 0.0);
    }

    #[test]
    fn a_change_order_moves_the_promise() {
        let mut j = job();
        j.change_orders.push(crate::model::ChangeOrder {
            seq: 1,
            reason: "scope grew".to_string(),
            add_crew_min: 60.0,
            add_job_min: 600.0,
            ts: "2026-11-02T11:00:00Z".to_string(),
        });
        let out = close_outcome(&j, Some(&bid(120.0)), 150.0, 150.0, None, 0.0, true, 0.0);
        assert_eq!(out.effective_bid_min, 180.0);
        assert_eq!(out.overrun_min, 0.0);
    }
}
