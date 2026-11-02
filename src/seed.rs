//! Importing reconstructed history into the ledger.
//!
//! The lanes of 2026-11-01..02 were run before this program existed, so their
//! records are reconstructions: the wall time is measured, the promise is
//! not, and the plan allowance stands in for the promise. Every row written
//! by this module is marked `reconstructed: true` and carries the lane name
//! and the evidence it came from, so nothing in the ledger pretends to be
//! more certain than it is.

use crate::accounting::close_outcome;
use crate::json::Json;
use crate::ledger;
use crate::model::{replay, Job, JobStatus};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

#[derive(Clone, Debug)]
pub struct SeedSummary {
    pub lanes: usize,
    pub rows: usize,
    pub skipped: Vec<String>,
}

/// Can this ledger be thrown away and rebuilt from a seed?
///
/// Only if every row in it is a reconstructed seed row. A ledger that also
/// holds real work is never rebuilt from under the general contractor.
pub fn is_only_seed(ledger_path: &Path) -> Result<bool, String> {
    let rows = ledger::read(ledger_path)?;
    let mut seed_jobs: Vec<String> = Vec::new();
    for row in &rows {
        if row.kind == "job.new" {
            let reconstructed = row.body.bool_at("reconstructed").unwrap_or(false)
                || row
                    .body
                    .str_at("source")
                    .map(|s| s.starts_with("lane:"))
                    .unwrap_or(false);
            if !reconstructed {
                return Ok(false);
            }
            if let Some(id) = row.body.str_at("id") {
                seed_jobs.push(id.to_string());
            }
        }
    }
    // Every other row must belong to one of those reconstructed jobs.
    for row in &rows {
        if row.kind == "job.new" {
            continue;
        }
        match row.body.str_at("job_id") {
            Some(id) if seed_jobs.iter().any(|j| j == id) => {}
            _ => return Ok(false),
        }
    }
    Ok(true)
}

/// Import a JSONL file of reconstructed lanes into the ledger.
pub fn import(ledger_path: &Path, file: &Path) -> Result<SeedSummary, String> {
    let file = File::open(file).map_err(|e| format!("cannot open {}: {}", file.display(), e))?;
    let reader = BufReader::new(file);

    let rows = ledger::read(ledger_path)?;
    let state = replay(&rows);
    let mut job_seq = state.jobs.len();
    let mut bid_seq = state.bids.len();
    let mut summary = SeedSummary {
        lanes: 0,
        rows: 0,
        skipped: Vec::new(),
    };

    // Lanes already in the ledger are not imported twice.
    let mut seen: Vec<String> = state
        .jobs
        .iter()
        .filter_map(|j| j.source.strip_prefix("lane:").map(|s| s.to_string()))
        .collect();

    // Debt carries from lane to lane for the same seat on the same class, in
    // the order the lanes are imported, exactly as it would in the live path.
    let mut debts: std::collections::BTreeMap<(String, String), f64> = std::collections::BTreeMap::new();

    for (n, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("cannot read line {}: {}", n + 1, e))?;
        if line.trim().is_empty() || line.trim_start().starts_with('#') {
            continue;
        }
        let lane = Json::parse(&line).map_err(|e| format!("line {}: {}", n + 1, e))?;
        let name = lane.str_at("lane").unwrap_or("").to_string();
        if name.is_empty() {
            summary.skipped.push(format!("line {}: no lane name", n + 1));
            continue;
        }
        if seen.contains(&name) {
            summary.skipped.push(format!("{}: already in the ledger", name));
            continue;
        }
        seen.push(name.clone());

        let job_id = format!("J{:03}", job_seq + 1);
        let bid_id = format!("B{:03}", bid_seq + 1);
        job_seq += 1;
        bid_seq += 1;

        let seat = lane.str_at("seat").unwrap_or("unknown").to_string();
        let class = lane.str_at("class").unwrap_or("unclassified").to_string();
        let allowance = lane.f64_at("allowance_min").unwrap_or(0.0);
        let actual_crew = lane.f64_at("actual_crew_min").unwrap_or(0.0);
        let actual_job = lane.f64_at("actual_job_min").unwrap_or(actual_crew);
        let start = lane.str_at("start").unwrap_or("").to_string();
        let end = lane.str_at("end").unwrap_or(start.as_str()).to_string();
        let accepted = lane.bool_at("crossed_goal_line").unwrap_or(false);

        // --- the job -------------------------------------------------------
        let mut acceptance = Json::obj();
        let acc_kind = lane
            .get("acceptance")
            .and_then(|a| a.str_at("kind"))
            .unwrap_or("report")
            .to_string();
        acceptance.set("kind", Json::s(acc_kind.clone()));
        acceptance.set(
            "cmd",
            Json::s(
                lane.get("acceptance")
                    .and_then(|a| a.str_at("cmd"))
                    .unwrap_or("")
                    .to_string(),
            ),
        );
        acceptance.set(
            "metric",
            Json::s(
                lane.get("acceptance")
                    .and_then(|a| a.str_at("metric"))
                    .unwrap_or("")
                    .to_string(),
            ),
        );
        acceptance.set(
            "threshold",
            match lane.get("acceptance").and_then(|a| a.f64_at("threshold")) {
                Some(t) => Json::n(t),
                None => Json::Null,
            },
        );
        acceptance.set(
            "note",
            Json::s(
                lane.get("acceptance")
                    .and_then(|a| a.str_at("note"))
                    .unwrap_or("")
                    .to_string(),
            ),
        );

        let mut job_body = Json::obj();
        job_body.set("id", Json::s(job_id.clone()));
        job_body.set(
            "title",
            Json::s(lane.str_at("title").unwrap_or(&name).to_string()),
        );
        job_body.set(
            "scope",
            Json::s(lane.str_at("scope").unwrap_or("").to_string()),
        );
        job_body.set("class", Json::s(class.clone()));
        job_body.set("acceptance", acceptance);
        job_body.set("deadline_min", Json::n(allowance));
        job_body.set("estimate_min", Json::n(allowance));
        job_body.set("budget_min", Json::n(allowance));
        job_body.set(
            "penalty_per_day_min",
            Json::n(lane.f64_at("penalty_per_day_min").unwrap_or(30.0)),
        );
        job_body.set("stop_ratio", Json::n(lane.f64_at("stop_ratio").unwrap_or(0.8)));
        job_body.set("reconstructed", Json::b(true));
        job_body.set("source", Json::s(format!("lane:{}", name)));
        job_body.set("lane", Json::s(name.clone()));
        job_body.set("seat", Json::s(seat.clone()));
        job_body.set("where", Json::s(lane.str_at("where").unwrap_or("").to_string()));
        job_body.set("exit_code", Json::n(lane.f64_at("exit_code").unwrap_or(0.0)));
        job_body.set(
            "outcome",
            Json::s(lane.str_at("outcome").unwrap_or("").to_string()),
        );
        job_body.set("relaunches", Json::n(lane.f64_at("relaunches").unwrap_or(0.0)));
        job_body.set("quota_stops", Json::n(lane.f64_at("quota_stops").unwrap_or(0.0)));
        job_body.set("start", Json::s(start.clone()));
        job_body.set("end", Json::s(end.clone()));
        if let Some(ev) = lane.get("evidence").and_then(|e| e.as_arr()) {
            let mut arr = Json::arr();
            for e in ev {
                arr.push(e.clone());
            }
            job_body.set("evidence", arr);
        }
        if let Some(notes) = lane.str_at("notes") {
            job_body.set("notes", Json::s(notes));
        }
        ledger::append(ledger_path, &start, "job.new", job_body)?;
        summary.rows += 1;

        // --- the bid (a proxy: the plan allowance, not a promise) ----------
        let mut bid_body = Json::obj();
        bid_body.set("id", Json::s(bid_id.clone()));
        bid_body.set("job_id", Json::s(job_id.clone()));
        bid_body.set("sub", Json::s(seat.clone()));
        // No allowance (a pi seat): the promise is unknown, so there is none.
        // The run's wall time is still recorded, and it still calibrates.
        if allowance > 0.0 {
            bid_body.set("crew_min", Json::n(allowance));
            bid_body.set("job_min", Json::n(allowance));
        } else {
            bid_body.set("crew_min", Json::Null);
            bid_body.set("job_min", Json::Null);
        }
        bid_body.set("confidence", Json::n(0.0));
        let mut ms = Json::arr();
        ms.push(Json::s(format!("run the lane ({})", name)));
        bid_body.set("milestones", ms);
        bid_body.set("computed", Json::b(false));
        bid_body.set("proxy", Json::b(true));
        bid_body.set("reconstructed", Json::b(true));
        bid_body.set(
            "calibratable",
            Json::b(lane.bool_at("calibratable").unwrap_or(false)),
        );
        bid_body.set(
            "basis",
            Json::s(
                lane.str_at("estimate_basis")
                    .unwrap_or("seat plan allowance")
                    .to_string(),
            ),
        );
        ledger::append(ledger_path, &start, "bid.new", bid_body)?;
        summary.rows += 1;

        // --- the award ------------------------------------------------------
        let mut award_body = Json::obj();
        award_body.set("job_id", Json::s(job_id.clone()));
        award_body.set("bid_id", Json::s(bid_id.clone()));
        award_body.set("sub", Json::s(seat.clone()));
        award_body.set("score", Json::n(0.0));
        award_body.set("reconstructed", Json::b(true));
        award_body.set(
            "rationale",
            Json::s(format!(
                "reconstructed: the director ran this lane on seat {}",
                seat
            )),
        );
        ledger::append(ledger_path, &start, "award", award_body)?;
        summary.rows += 1;

        // --- the close ------------------------------------------------------
        // The job and the bid are needed to work out the same arithmetic the
        // live path uses, so the seeded history is accounted for by the same
        // code, not by a second set of rules.
        let job = Job {
            id: job_id.clone(),
            title: lane.str_at("title").unwrap_or(&name).to_string(),
            scope: lane.str_at("scope").unwrap_or("").to_string(),
            class: class.clone(),
            acceptance: crate::model::Acceptance {
                kind: acc_kind,
                cmd: String::new(),
                metric: String::new(),
                threshold: None,
                note: String::new(),
            },
            deadline_min: allowance,
            estimate_min: allowance,
            budget_min: allowance,
            penalty_per_day_min: lane.f64_at("penalty_per_day_min").unwrap_or(30.0),
            stop_ratio: 0.8,
            created_ts: start.clone(),
            reconstructed: true,
            source: format!("lane:{}", name),
            status: JobStatus::Awarded,
            awarded_bid: bid_id.clone(),
            awarded_sub: seat.clone(),
            checkpoints: Vec::new(),
            change_orders: Vec::new(),
            close: None,
            cancel_reason: String::new(),
        };
        let bid = crate::model::Bid {
            id: bid_id.clone(),
            job_id: job_id.clone(),
            sub: seat.clone(),
            crew_min: if allowance > 0.0 { Some(allowance) } else { None },
            job_min: if allowance > 0.0 { Some(allowance) } else { None },
            confidence: 0.0,
            milestones: Vec::new(),
            computed: false,
            proxy: true,
            calibratable: lane.bool_at("calibratable").unwrap_or(false),
            basis: String::new(),
            ts: start.clone(),
        };
        let debt_key = (seat.clone(), class.clone());
        let debt_before = *debts.get(&debt_key).unwrap_or(&0.0);
        let outcome = close_outcome(
            &job,
            Some(&bid),
            actual_crew,
            actual_job,
            lane.f64_at("late_days"),
            debt_before,
            accepted,
        );
        debts.insert(debt_key, debt_before + outcome.debt_delta_min);

        let mut close_body = Json::obj();
        close_body.set("job_id", Json::s(job_id.clone()));
        close_body.set("accepted", Json::b(accepted));
        close_body.set("actual_crew_min", Json::n(actual_crew));
        close_body.set("actual_job_min", Json::n(actual_job));
        close_body.set("late_days", Json::n(outcome.late_days));
        close_body.set("effective_bid_min", Json::n(outcome.effective_bid_min));
        close_body.set("overrun_min", Json::n(outcome.overrun_min));
        close_body.set("penalty_min", Json::n(outcome.penalty_min));
        close_body.set("repayment_min", Json::n(outcome.repayment_min));
        close_body.set("debt_delta_min", Json::n(outcome.debt_delta_min));
        close_body.set(
            "method",
            Json::s(lane.str_at("crew_time_method").unwrap_or("wall").to_string()),
        );
        if let Some(t) = lane.u64_at("tokens") {
            close_body.set("tokens", Json::n(t as f64));
        }
        close_body.set(
            "goal_line",
            Json::s(lane.str_at("goal_line").unwrap_or("").to_string()),
        );
        close_body.set("reconstructed", Json::b(true));
        ledger::append(ledger_path, &end, "close", close_body)?;
        summary.rows += 1;

        summary.lanes += 1;
    }

    Ok(summary)
}
