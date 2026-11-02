//! `gc` — the general contractor's book.
//!
//! The general contractor writes a job, subcontracts it to a seat, watches the
//! burn against the bid, and closes the job with the numbers. Everything the
//! program knows lives in one append-only, hash-chained ledger; this file is
//! only the desk that writes to it.

mod accounting;
mod brief;
mod calib;
mod cli;
mod json;
mod ledger;
mod model;
mod report;
mod seed;
mod sha256;
mod time;

use cli::Args;
use json::Json;
use model::JobStatus;
use std::path::PathBuf;
use std::process::ExitCode;

/// A subcontractor carrying this much debt on a job class must be retooled
/// before being hired on that class again.
pub const DEEP_DEBT_MIN: f64 = 120.0;

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let args = Args::parse(&argv);

    let ledger_path: PathBuf = match args.get("ledger") {
        Some(p) => PathBuf::from(p),
        None => ledger::default_path(),
    };

    let cmd = match args.word(0) {
        Some(c) => c.to_string(),
        None => {
            eprintln!("{}", usage());
            return ExitCode::from(2);
        }
    };

    let result = match cmd.as_str() {
        "job" => cmd_job(&args, &ledger_path),
        "bid" => cmd_bid(&args, &ledger_path),
        "award" => cmd_award(&args, &ledger_path),
        "checkpoint" => cmd_checkpoint(&args, &ledger_path),
        "close" => cmd_close(&args, &ledger_path),
        "change-order" => cmd_change_order(&args, &ledger_path),
        "cancel" => cmd_cancel(&args, &ledger_path),
        "retool" => cmd_retool(&args, &ledger_path),
        "report" => cmd_report(&args, &ledger_path),
        "brief" => cmd_brief(&args, &ledger_path),
        "verify" => cmd_verify(&args, &ledger_path),
        "seed" => cmd_seed(&args, &ledger_path),
        "help" | "--help" | "-h" => {
            println!("{}", usage());
            return ExitCode::SUCCESS;
        }
        other => Err(format!("unknown command '{}'. Try `gc help`.", other)),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("gc: {}", e);
            ExitCode::from(1)
        }
    }
}

fn usage() -> String {
    "\
gc — the general contractor's book

  gc [--ledger PATH] <command> ...

  job new        --title T --class C --scope S | --scope-file F
                [--accept-cmd CMD | --accept-metric NAME --accept-at N]
                --deadline-min M --budget-min B
                [--penalty-per-day-min P] [--stop-ratio R]
  job list       [--class C] [--status S]
  bid            --job J --sub S [--crew-min X] [--job-min Y]
                [--confidence C] [--milestones \"a|b|c\"] [--submit]
  award          --job J (--bid B | --auto) [--rationale R]
  checkpoint     --job J --crew-used-min X [--milestones-done N] [--note N]
                [--acceptance-passed]
  close          --job J --crew-min X [--job-min Y] [--late-days N]
                [--accepted | --failed] [--method wall|tokens|estimated]
                [--tokens N] [--goal-line TEXT]
  change-order   --job J --reason R [--add-crew-min X] [--add-job-min Y]
  cancel         --job J --reason R
  retool         --sub S --class C --reason R --action A
  report         [--sub S] [--class C] [--json]
  brief          --job J
  verify
  seed import    --file FILE [--rebuild]

Every writing command takes --at ISO8601 to fix the timestamp (or set GC_NOW
to unix seconds), which is how the ledger stays byte-for-byte reproducible."
        .to_string()
}

fn now(args: &Args) -> String {
    match args.get("at") {
        Some(at) => at.to_string(),
        None => time::now_iso(),
    }
}

fn load(ledger_path: &PathBuf) -> Result<model::State, String> {
    let rows = ledger::read(ledger_path)?;
    Ok(model::replay(&rows))
}

// ---------------------------------------------------------------- job -----

fn cmd_job(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    match args.word(1) {
        Some("new") => job_new(args, ledger_path),
        Some("list") => job_list(args, ledger_path),
        Some(other) => Err(format!("unknown job subcommand '{}'", other)),
        None => Err("job needs a subcommand: new or list".to_string()),
    }
}

fn job_new(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let title = args.need("title")?.to_string();
    let class = args.need("class")?.to_string();

    let scope = match args.get("scope-file") {
        Some(path) => std::fs::read_to_string(path)
            .map_err(|e| format!("cannot read --scope-file {}: {}", path, e))?,
        None => args.need("scope")?.to_string(),
    };

    let mut acceptance = Json::obj();
    if let Some(cmd) = args.get("accept-cmd") {
        acceptance.set("kind", Json::s("cmd"));
        acceptance.set("cmd", Json::s(cmd.to_string()));
        acceptance.set("metric", Json::s(""));
        acceptance.set("threshold", Json::Null);
        acceptance.set("note", Json::s(args.get("accept-note").unwrap_or("")));
    } else if let Some(metric) = args.get("accept-metric") {
        acceptance.set("kind", Json::s("metric"));
        acceptance.set("cmd", Json::s(""));
        acceptance.set("metric", Json::s(metric.to_string()));
        acceptance.set(
            "threshold",
            match args.num("accept-at")? {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        acceptance.set("note", Json::s(args.get("accept-note").unwrap_or("")));
    } else {
        acceptance.set("kind", Json::s("report"));
        acceptance.set("cmd", Json::s(""));
        acceptance.set("metric", Json::s(""));
        acceptance.set("threshold", Json::Null);
        acceptance.set("note", Json::s(
            "no machine-checkable acceptance test was written down; this job is closed by a human",
        ));
    }

    let deadline_min = args
        .duration_min("deadline")?
        .ok_or("missing required flag --deadline-min (or --deadline-hours)")?;
    // The estimate is the general contractor's own view of how much
    // crew-time the work needs; the ceiling is the most it will pay. Give
    // one and the other follows, so a job is never half-written.
    let (estimate_min, budget_min) = match (
        args.duration_min("estimate")?,
        args.duration_min("budget")?,
    ) {
        (Some(e), Some(b)) => (e, b),
        (Some(e), None) => (e, e * 1.5),
        (None, Some(b)) => (b / 1.5, b),
        (None, None) => {
            return Err(
                "missing required flag --estimate-min (the GC's estimate of the crew-time) \
                 or --budget-min (the ceiling); --deadline-min is required too"
                    .to_string(),
            )
        }
    };
    if deadline_min <= 0.0 || budget_min <= 0.0 || estimate_min <= 0.0 {
        return Err("the deadline, the estimate and the budget must all be positive".to_string());
    }

    let id = state.next_job_id();
    let mut body = Json::obj();
    body.set("id", Json::s(id.clone()));
    body.set("title", Json::s(title));
    body.set("scope", Json::s(scope));
    body.set("class", Json::s(class));
    body.set("acceptance", acceptance);
    body.set("deadline_min", Json::n(deadline_min));
    body.set("estimate_min", Json::n(estimate_min));
    body.set("budget_min", Json::n(budget_min));
    body.set(
        "penalty_per_day_min",
        Json::n(args.num("penalty-per-day-min")?.unwrap_or(30.0)),
    );
    body.set("stop_ratio", Json::n(args.num("stop-ratio")?.unwrap_or(0.8)));
    body.set("reconstructed", Json::b(false));
    body.set("source", Json::s(args.get("source").unwrap_or("gc job new").to_string()));

    let row = ledger::append(ledger_path, &now(args), "job.new", body)?;
    println!(
        "{} — {} [{}] goal line: {} — job-time {} min, GC estimate {} min, ceiling {} min",
        id,
        args.need("title")?,
        args.need("class")?,
        args.get("accept-cmd")
            .map(|c| format!("`{}` exits 0", c))
            .or_else(|| args.get("accept-metric").map(|m| format!("metric {}", m)))
            .unwrap_or_else(|| "human judgement".to_string()),
        deadline_min as i64,
        estimate_min as i64,
        budget_min as i64
    );
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

fn job_list(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let class = args.get("class");
    let status = args.get("status");
    for job in &state.jobs {
        if let Some(c) = class {
            if job.class != c {
                continue;
            }
        }
        if let Some(s) = status {
            if job.status.as_str() != s {
                continue;
            }
        }
        println!("{}", brief::job_line(&state, job));
    }
    Ok(())
}

// ---------------------------------------------------------------- bid -----

fn cmd_bid(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    let sub = args.need("sub")?.to_string();

    let hand_crew = args.num("crew-min")?;
    let hand_job = args.num("job-min")?;
    let hand_confidence = args.num("confidence")?;

    let mut factor: Option<f64> = None;
    let mut n_runs: Option<usize> = None;
    let (crew_min, job_min, confidence, basis, computed) = match (hand_crew, hand_confidence) {
        (Some(c), _) => {
            let confidence = hand_confidence.unwrap_or(0.5);
            (
                c,
                hand_job.unwrap_or(c),
                confidence,
                "submitted by hand".to_string(),
                false,
            )
        }
        (None, _) => {
            let cal = calib::calibrate_bid(&sub, &job.class, &state, job.estimate_min)?;
            factor = Some(cal.factor);
            n_runs = Some(cal.n_pairs);
            (
                cal.crew_min,
                hand_job.unwrap_or(cal.job_min),
                hand_confidence.unwrap_or(cal.confidence),
                cal.basis.clone(),
                true,
            )
        }
    };

    let milestones: Vec<String> = args
        .get("milestones")
        .map(|m| {
            m.split('|')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect()
        })
        .unwrap_or_default();

    if args.has("submit") {
        if job.status != JobStatus::Open && job.status != JobStatus::Awarded {
            return Err(format!(
                "job {} is {} — it cannot take another bid",
                job.id,
                job.status.as_str()
            ));
        }
        let bid_id = state.next_bid_id();
        let mut body = Json::obj();
        body.set("id", Json::s(bid_id.clone()));
        body.set("job_id", Json::s(job.id.clone()));
        body.set("sub", Json::s(sub.clone()));
        body.set("crew_min", Json::n(crew_min));
        body.set("job_min", Json::n(job_min));
        body.set("confidence", Json::n(confidence));
        let mut ms = Json::arr();
        for m in &milestones {
            ms.push(Json::s(m.clone()));
        }
        body.set("milestones", ms);
        body.set("computed", Json::b(computed));
        body.set("proxy", Json::b(false));
        body.set("basis", Json::s(basis.clone()));
        let row = ledger::append(ledger_path, &now(args), "bid.new", body)?;
        println!(
            "bid {} on {} by {}: {} crew-min, {} job-min, confidence {:.2} ({})",
            bid_id, job.id, sub, crew_min, job_min, confidence, basis
        );
        println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    } else {
        println!(
            "bid on {} by {}: {} crew-min, {} job-min, confidence {:.2}",
            job.id, sub, crew_min, job_min, confidence
        );
        println!("basis: {}", basis);
        if computed {
            println!(
                "the GC's estimate for this job is {} crew-min; the calibrated factor over {} clean runs is {:.2}",
                job.estimate_min as i64,
                n_runs.unwrap_or(0),
                factor.unwrap_or(1.0)
            );
        }
        if crew_min > job.budget_min {
            println!(
                "note: this bid is above the job's crew-time ceiling ({} min) — the award would be over budget",
                job.budget_min
            );
        }
        println!("(dry run — pass --submit to write it to the ledger)");
    }
    Ok(())
}

// -------------------------------------------------------------- award -----

fn cmd_award(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    if job.status == JobStatus::Closed {
        return Err(format!("job {} is closed", job.id));
    }
    if job.status == JobStatus::Cancelled {
        return Err(format!("job {} is cancelled", job.id));
    }

    let bids: Vec<model::Bid> = state
        .bids_for(&job.id)
        .into_iter()
        .cloned()
        .collect();
    if bids.is_empty() {
        return Err(format!("job {} has no bids to award", job.id));
    }

    let chosen: model::Bid = if args.has("auto") {
        let min_crew = bids
            .iter()
            .filter_map(|b| b.crew_min)
            .fold(f64::INFINITY, f64::min);
        let mut best: Option<(f64, model::Bid, (f64, f64, f64, f64))> = None;
        let mut blocked: Vec<String> = Vec::new();
        for bid in &bids {
            if let Some(reason) = blocked_reason(&state, &bid.sub, &job.class) {
                blocked.push(reason);
                continue;
            }
            let s = calib::award_score(&state, &job.class, bid, min_crew);
            let better = match &best {
                None => true,
                Some((best_score, best_bid, _)) => {
                    s.0 > *best_score + 1e-9
                        || ((s.0 - *best_score).abs() <= 1e-9
                            && (bid.crew_min.unwrap_or(f64::MAX), bid.sub.clone())
                                < (best_bid.crew_min.unwrap_or(f64::MAX), best_bid.sub.clone()))
                }
            };
            if better {
                best = Some((s.0, bid.clone(), s));
            }
        }
        for b in &blocked {
            eprintln!("gc: skipped a bid: {}", b);
        }
        match best {
            Some((_, bid, _)) => bid,
            None => {
                return Err(format!(
                    "no bid for job {} is eligible: every bidder is in deep debt on class '{}' and has not been retooled",
                    job.id, job.class
                ))
            }
        }
    } else {
        let bid_id = args.need("bid")?.to_string();
        let bid = bids
            .iter()
            .find(|b| b.id == bid_id)
            .ok_or_else(|| format!("no bid {} on job {}", bid_id, job.id))?;
        if let Some(reason) = blocked_reason(&state, &bid.sub, &job.class) {
            return Err(reason);
        }
        bid.clone()
    };

    let min_crew = bids
        .iter()
        .filter_map(|b| b.crew_min)
        .fold(f64::INFINITY, f64::min);
    let (score, cost_score, ontime, fit) = calib::award_score(&state, &job.class, &chosen, min_crew);

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("bid_id", Json::s(chosen.id.clone()));
    body.set("sub", Json::s(chosen.sub.clone()));
    body.set("score", Json::n(score));
    body.set("cost_score", Json::n(cost_score));
    body.set("on_time_probability", Json::n(ontime));
    body.set("fit", Json::n(fit));
    body.set(
        "rationale",
        Json::s(
            args.get("rationale")
                .unwrap_or("cost, on-time record and fit")
                .to_string(),
        ),
    );
    let row = ledger::append(ledger_path, &now(args), "award", body)?;
    println!(
        "awarded {} to {} (bid {}): score {:.3} = 0.40*cost {:.3} + 0.40*on-time {:.3} + 0.20*fit {:.3}",
        job.id, chosen.sub, chosen.id, score, cost_score, ontime, fit
    );
    if let Some(c) = chosen.crew_min {
        if c > job.budget_min {
            eprintln!(
                "gc: warning — the bid ({} min) is above the job's crew-time ceiling ({} min)",
                c, job.budget_min
            );
        }
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

/// Why a subcontractor cannot be hired on a job class right now, if it
/// cannot: deep debt on the class and no retooling since the debt opened.
fn blocked_reason(state: &model::State, sub: &str, class: &str) -> Option<String> {
    let debt = state.debt_min(sub, class);
    if debt < DEEP_DEBT_MIN {
        return None;
    }
    // The most recent close that pushed the debt here decides when the seat
    // was retooled.
    let mut latest = "";
    for job in &state.jobs {
        if job.class == class && job.awarded_sub == sub {
            if let Some(c) = &job.close {
                if c.debt_delta_min > 0.0 && c.ts.as_str() > latest {
                    latest = c.ts.as_str();
                }
            }
        }
    }
    if let Some(_r) = state.retooled_after(sub, class, latest) {
        return None;
    }
    Some(format!(
        "{} is in deep debt on class '{}' ({} crew-minutes) and has not been retooled since; retool before hiring again",
        sub, class, debt
    ))
}

// --------------------------------------------------------- checkpoint -----

fn cmd_checkpoint(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    if job.status == JobStatus::Closed {
        return Err(format!("job {} is closed", job.id));
    }
    if job.status == JobStatus::Cancelled {
        return Err(format!("job {} is cancelled", job.id));
    }
    if job.awarded_sub.is_empty() {
        return Err(format!("job {} has not been awarded yet", job.id));
    }

    // The stop rule: after the burn crosses the stop ratio without the goal
    // line, the sub stops and reports. No more burn is accepted until the
    // general contractor re-scopes, extends, or cancels the job.
    if job.last_stop().is_some() && !job.re_scoped_after_stop() {
        let stop = job.last_stop().unwrap();
        return Err(format!(
            "job {} stopped at {:.0}% of the bid ({} crew-minutes used) without the goal line passing. \
             The general contractor must re-scope it with a change order, extend it, or cancel it before more burn is accepted.",
            job.id,
            stop.burn * 100.0,
            stop.crew_used_min
        ));
    }

    let used = args.need_num("crew-used-min")?;
    let bid = job.awarded_bid(&state.bids);
    let effective_bid = job.effective_bid_min(bid);
    if effective_bid <= 0.0 {
        return Err(format!(
            "job {} has no bid in force, so the burn cannot be measured",
            job.id
        ));
    }
    let burn = used / effective_bid;
    let acceptance_passed = args.has("acceptance-passed");
    let stop_ratio = job.stop_ratio;
    let stop_required = burn >= stop_ratio && !acceptance_passed;

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("crew_used_min", Json::n(used));
    body.set("burn", Json::n(burn));
    body.set(
        "milestones_done",
        Json::n(args.num("milestones-done")?.unwrap_or(0.0)),
    );
    body.set("note", Json::s(args.get("note").unwrap_or("")));
    body.set("stop_required", Json::b(stop_required));
    body.set("acceptance_passed", Json::b(acceptance_passed));

    let row = ledger::append(ledger_path, &now(args), "checkpoint", body)?;
    println!(
        "checkpoint on {}: {} crew-min used of {} ({:.0}% of the bid)",
        job.id,
        used,
        effective_bid,
        burn * 100.0
    );
    if stop_required {
        println!(
            "STOP REQUIRED: the goal line has not passed at {:.0}% of the bid ({:.0}% of the allowance). \
             Report and stop; the general contractor must re-scope, extend, or cancel.",
            stop_ratio * 100.0,
            stop_ratio * 100.0
        );
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

// -------------------------------------------------------------- close -----

fn cmd_close(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    if job.close.is_some() {
        return Err(format!("job {} is already closed", job.id));
    }
    if job.awarded_sub.is_empty() {
        return Err(format!("job {} has not been awarded yet", job.id));
    }

    let actual_crew = args.need_num("crew-min")?;
    let actual_job = args.num("job-min")?.unwrap_or(actual_crew);
    let accepted = if args.has("failed") {
        false
    } else {
        args.has("accepted")
    };
    let method = args.get("method").unwrap_or("wall").to_string();
    if !["wall", "tokens", "estimated"].contains(&method.as_str()) {
        return Err(format!(
            "unknown --method '{}': use wall, tokens or estimated",
            method
        ));
    }
    let tokens = args.num("tokens")?.map(|t| t as u64);

    let bid = job.awarded_bid(&state.bids);
    let debt_before = state.debt_min(&job.awarded_sub, &job.class);
    let outcome = accounting::close_outcome(
        &job,
        bid,
        actual_crew,
        actual_job,
        args.num("late-days")?,
        debt_before,
        accepted,
    );

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("accepted", Json::b(accepted));
    body.set("actual_crew_min", Json::n(actual_crew));
    body.set("actual_job_min", Json::n(actual_job));
    body.set("late_days", Json::n(outcome.late_days));
    body.set("effective_bid_min", Json::n(outcome.effective_bid_min));
    body.set("overrun_min", Json::n(outcome.overrun_min));
    body.set("penalty_min", Json::n(outcome.penalty_min));
    body.set("repayment_min", Json::n(outcome.repayment_min));
    body.set("debt_delta_min", Json::n(outcome.debt_delta_min));
    body.set("method", Json::s(method.clone()));
    if let Some(t) = tokens {
        body.set("tokens", Json::n(t as f64));
    }
    body.set(
        "goal_line",
        Json::s(args.get("goal-line").unwrap_or("").to_string()),
    );
    body.set("reconstructed", Json::b(false));

    let row = ledger::append(ledger_path, &now(args), "close", body)?;
    println!(
        "closed {}: {} crew-min against a promise of {}, overrun {}, penalty {}, debt {:+}",
        job.id,
        actual_crew,
        outcome.effective_bid_min,
        outcome.overrun_min,
        outcome.penalty_min,
        outcome.debt_delta_min
    );
    if !accepted {
        println!("the goal line did not pass: no repayment credit, and the record says so");
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

// ------------------------------------------------------ change order -----

fn cmd_change_order(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    if job.close.is_some() {
        return Err(format!("job {} is closed", job.id));
    }
    if job.awarded_sub.is_empty() {
        return Err(format!("job {} has not been awarded yet", job.id));
    }
    let reason = args.need("reason")?.to_string();
    let add_crew = args.num("add-crew-min")?.unwrap_or(0.0);
    let add_job = args.num("add-job-min")?.unwrap_or(0.0);

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("seq", Json::n((job.change_orders.len() + 1) as f64));
    body.set("reason", Json::s(reason.clone()));
    body.set("add_crew_min", Json::n(add_crew));
    body.set("add_job_min", Json::n(add_job));

    let row = ledger::append(ledger_path, &now(args), "change-order", body)?;
    println!(
        "change order {} on {}: +{} crew-min, +{} job-min. {}",
        job.change_orders.len() + 1,
        job.id,
        add_crew,
        add_job,
        reason
    );
    if job.last_stop().is_some() {
        println!("the stop on this job is now lifted: the sub may report more burn");
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

// ------------------------------------------------------------- cancel -----

fn cmd_cancel(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    let job = state
        .job(&job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?
        .clone();
    if job.close.is_some() {
        return Err(format!("job {} is already closed", job.id));
    }
    let reason = args.need("reason")?.to_string();
    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("reason", Json::s(reason.clone()));
    let row = ledger::append(ledger_path, &now(args), "cancel", body)?;
    println!("cancelled {}: {}", job.id, reason);
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

// ------------------------------------------------------------ retool -----

fn cmd_retool(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let sub = args.need("sub")?.to_string();
    let class = args.need("class")?.to_string();
    let reason = args.need("reason")?.to_string();
    let action = args.need("action")?.to_string();
    let mut body = Json::obj();
    body.set("sub", Json::s(sub.clone()));
    body.set("class", Json::s(class.clone()));
    body.set("reason", Json::s(reason.clone()));
    body.set("action", Json::s(action.clone()));
    let row = ledger::append(ledger_path, &now(args), "retool", body)?;
    println!(
        "retooled {} on class '{}': {} (action: {})",
        sub, class, reason, action
    );
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    Ok(())
}

// ------------------------------------------------------------ report -----

fn cmd_report(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let filter = report::ReportFilter {
        sub: args.get("sub").map(|s| s.to_string()),
        class: args.get("class").map(|s| s.to_string()),
    };
    if args.has("json") {
        println!(
            "{}",
            report::json_report(&state, &filter).to_text()
        );
    } else {
        print!("{}", report::text_report(&state, &filter));
    }
    Ok(())
}

// ------------------------------------------------------------- brief -----

fn cmd_brief(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let state = load(ledger_path)?;
    let job_id = args.need("job")?.to_string();
    print!("{}", brief::brief_block(&state, &job_id)?);
    Ok(())
}

// ------------------------------------------------------------ verify -----

fn cmd_verify(_args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    let rows = ledger::read(ledger_path)?;
    let last = rows.last().map(|r| r.hash.clone()).unwrap_or_else(|| ledger::GENESIS.to_string());
    println!(
        "ledger {} verified: {} rows, chain intact, head {}",
        ledger_path.display(),
        rows.len(),
        &last[..16]
    );
    Ok(())
}

// -------------------------------------------------------------- seed -----

fn cmd_seed(args: &Args, ledger_path: &PathBuf) -> Result<(), String> {
    match args.word(1) {
        Some("import") => {
            let file = args.need("file")?.to_string();
            if args.has("rebuild") {
                if !seed::is_only_seed(ledger_path)? {
                    return Err(format!(
                        "refusing to rebuild {}: it holds rows that are not reconstructed seed rows, \
                         so it is not only history",
                        ledger_path.display()
                    ));
                }
                std::fs::write(ledger_path, "")
                    .map_err(|e| format!("cannot clear {}: {}", ledger_path.display(), e))?;
                println!("rebuilt {} from the seed", ledger_path.display());
            }
            let summary = seed::import(ledger_path, std::path::Path::new(&file))?;
            println!(
                "imported {} reconstructed lanes as {} ledger rows from {}",
                summary.lanes, summary.rows, file
            );
            for s in &summary.skipped {
                println!("  skipped {}", s);
            }
            Ok(())
        }
        other => Err(format!(
            "unknown seed subcommand '{}' (only 'import' exists)",
            other.unwrap_or("")
        )),
    }
}
