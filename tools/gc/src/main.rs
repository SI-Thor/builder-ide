//! `gc` — the general contractor's book.
//!
//! The general contractor writes a job, subcontracts it to a seat, watches the
//! burn against the bid, and closes the job with the numbers. Everything the
//! program knows lives in one append-only, hash-chained ledger; this file is
//! only the desk that writes to it.

mod accounting;
mod brief;
mod calib;
mod check;
mod clause;
mod cli;
mod forecast;
mod json;
mod ledger;
mod model;
mod report;
mod seed;
mod sha256;
mod time;
mod verdict;

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
                [--external-id ID] [--json]
                [--clause \"metric <= target [window W] [penalty P]\" ...]
  job list       [--class C] [--status S]
  bid            --job J --sub S [--crew-min X] [--job-min Y]
                [--confidence C] [--milestones \"a|b|c\"] [--submit] [--json]
  award          --job J (--bid B | --auto) [--rationale R] [--json]
                [--clause \"metric <= target [window W] [penalty P]\" ...]
  checkpoint     --job J --crew-used-min X [--check auto|pass|fail|inconclusive]
                [--metric name=value ...] [--milestones-done N] [--note N]
                [--check-timeout-sec S] [--json]
  close          --job J --crew-min X [--job-min Y] [--late-days N]
                [--metric name=value ...] [--method wall|tokens|estimated]
                [--tokens N] [--goal-line TEXT] [--check-timeout-sec S]
                [--accepted | --failed | --check inconclusive]
                                                  (report-kind jobs only)
                [--json]
  change-order   --job J --reason R [--add-crew-min X] [--add-job-min Y]
  cancel         --job J --reason R
  retool         --sub S --class C --reason R --action A
  report         [--sub S] [--class C] [--json]
  brief          --job J
  verify
  seed import    --file FILE [--rebuild]

The goal line is not taken on trust. A job whose acceptance is a command is
closed by gc running that command itself and reading the exit code; a metric
acceptance is compared to the value reported with --metric. A check that
could not run is recorded inconclusive — never failed.

The writing commands take --json: the row they wrote is printed as one line
of JSON on stdout, after the human-readable lines. It is the row body
itself, so a caller can read the ids back without parsing prose.
`gc job new --external-id ID` records the caller's own id of the job (a
work order, a ticket) in the row, so gc's job can be found again from
outside.

Every checkpoint prints a spend-rate forecast, so a burn heading for the
stop line is visible before it gets there.

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

// ------------------------------------------------------------- checks -----

/// Parse the repeatable `--metric name=value` flags into (name, value)
/// pairs. A name given twice keeps the last value.
fn metric_flags(args: &Args) -> Result<Vec<(String, f64)>, String> {
    let mut out: Vec<(String, f64)> = Vec::new();
    for m in args.get_all("metric") {
        let (name, value) = m
            .split_once('=')
            .ok_or_else(|| format!("--metric '{}' wants name=value", m))?;
        let v: f64 = value
            .trim()
            .parse()
            .map_err(|_| format!("--metric '{}': the value must be a number", m))?;
        let name = name.trim().to_string();
        if let Some(slot) = out.iter_mut().find(|(n, _)| *n == name) {
            slot.1 = v;
        } else {
            out.push((name, v));
        }
    }
    Ok(out)
}

/// The metrics gc computes itself at a checkpoint or a close. A number the
/// ledger can recompute is never taken on assertion, so these win over a
/// supplied metric of the same name.
fn builtin_metrics(
    crew_used_min: f64,
    effective_bid_min: f64,
    job_elapsed_min: Option<f64>,
) -> Vec<(String, f64)> {
    let mut out = vec![("crew_used_min".to_string(), crew_used_min)];
    if effective_bid_min > 0.0 {
        out.push(("burn".to_string(), crew_used_min / effective_bid_min));
    }
    if let Some(e) = job_elapsed_min {
        out.push(("job_elapsed_min".to_string(), e));
    }
    out
}

/// Builtins first, then the supplied metrics that do not collide.
fn merged_metrics(
    builtins: Vec<(String, f64)>,
    supplied: Vec<(String, f64)>,
) -> Vec<(String, f64)> {
    let mut out = builtins;
    for (name, value) in supplied {
        if !out.iter().any(|(n, _)| *n == name) {
            out.push((name, value));
        }
    }
    out
}

/// Check every clause in force against the metrics of this moment. Clauses
/// whose window has passed (or has not placed them in time) are not checked;
/// a clause whose metric has no value is inconclusive, not breached.
fn check_clauses(
    clauses: &[clause::Clause],
    metrics: &[(String, f64)],
    job_elapsed_min: Option<f64>,
) -> Vec<model::ClauseResult> {
    clauses
        .iter()
        .filter(|c| c.in_force_at(job_elapsed_min))
        .map(|c| model::ClauseResult {
            metric: c.metric.clone(),
            verdict: c.evaluate(metrics.iter().find(|(n, _)| n == &c.metric).map(|(_, v)| *v)),
            value: metrics
                .iter()
                .find(|(n, _)| n == &c.metric)
                .map(|(_, v)| *v),
            penalty_min: c.penalty_min,
        })
        .collect()
}

/// Decide the goal-line check for a checkpoint. `--check auto` (the
/// default) runs the acceptance command or compares the metric itself;
/// `pass`/`fail` are a human's word and only count on a report-kind job —
/// a command or a metric decides for itself, and saying otherwise would be
/// exactly the blank check this program exists to avoid.
fn resolve_check(
    args: &Args,
    job: &model::Job,
    metrics: &[(String, f64)],
    timeout_sec: u64,
) -> Result<check::CheckResult, String> {
    if args.has("acceptance-passed") {
        return Err(
            "--acceptance-passed is gone: checks are three-valued now. Let --check auto run \
             the goal line, or pass --check pass|fail on a report-kind job, or --check \
             inconclusive when the check could not run."
                .to_string(),
        );
    }
    let requested = args.get("check").unwrap_or("auto");
    match requested {
        "auto" => Ok(match job.acceptance.kind.as_str() {
            "cmd" => check::run_cmd(&job.acceptance.cmd, timeout_sec),
            "metric" => metric_check(job, metrics),
            _ => check::CheckResult::cannot(
                "none",
                "no machine-checkable acceptance test was written down",
            ),
        }),
        "inconclusive" => Ok(check::CheckResult::cannot(
            "human",
            "the check could not be run at this moment",
        )),
        word @ ("pass" | "fail") => {
            if job.acceptance.kind == "report" {
                Ok(check::CheckResult::human(word == "pass"))
            } else {
                Err(format!(
                    "--check {} states an outcome the goal line decides for itself: job {}'s \
                     acceptance is {}-kind, so it is run (or measured) here, not said. \
                     --check inconclusive records that it could not run.",
                    word,
                    job.id,
                    job.acceptance.kind
                ))
            }
        }
        other => Err(format!(
            "--check wants auto, pass, fail or inconclusive, not '{}'",
            other
        )),
    }
}

fn metric_check(job: &model::Job, metrics: &[(String, f64)]) -> check::CheckResult {
    let value = metrics
        .iter()
        .find(|(n, _)| n == &job.acceptance.metric)
        .map(|(_, v)| *v);
    check::CheckResult::metric(job.acceptance.threshold, value)
}

fn check_timeout_sec(args: &Args) -> Result<u64, String> {
    Ok(args.num("check-timeout-sec")?.unwrap_or(600.0).max(1.0) as u64)
}

fn check_json(c: &check::CheckResult) -> Json {
    let mut o = Json::obj();
    o.set("verdict", Json::s(c.verdict.as_str()));
    o.set("by", Json::s(c.by.clone()));
    o.set(
        "exit_code",
        match c.exit_code {
            Some(e) => Json::n(e as f64),
            None => Json::Null,
        },
    );
    o.set("note", Json::s(c.note.clone()));
    o
}

fn metrics_json(metrics: &[(String, f64)]) -> Json {
    let mut arr = Json::arr();
    for (name, value) in metrics {
        let mut m = Json::obj();
        m.set("name", Json::s(name.clone()));
        m.set("value", Json::n(*value));
        arr.push(m);
    }
    arr
}

fn clauses_json(results: &[model::ClauseResult]) -> Json {
    let mut arr = Json::arr();
    for r in results {
        arr.push(r.to_json());
    }
    arr
}

fn forecast_json(f: &forecast::Forecast) -> Json {
    let mut o = Json::obj();
    o.set(
        "rate_per_job_min",
        match f.rate_per_job_min {
            Some(v) => Json::n(v),
            None => Json::Null,
        },
    );
    o.set(
        "projected_crew_at_deadline",
        match f.projected_crew_at_deadline {
            Some(v) => Json::n(v),
            None => Json::Null,
        },
    );
    o.set(
        "minutes_to_stop_line",
        match f.minutes_to_stop_line {
            Some(v) => Json::n(v),
            None => Json::Null,
        },
    );
    o.set("verdict", Json::s(f.verdict.as_str()));
    o.set("note", Json::s(f.note.clone()));
    o
}

/// Print the body of the row that was just written as one line of JSON, for
/// a caller that reads gc's stdout instead of its ledger.
///
/// The line is ADDED after the human-readable ones, never in place of them:
/// the prose is what a person reads at the desk, and the JSON is what the
/// night cycle's bridge reads. Same bytes in the row, same bytes here.
fn print_body_json(args: &Args, body: &Json) {
    if args.has("json") {
        println!("{}", body.to_text());
    }
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
    let mut clauses = Json::arr();
    let mut clause_count = 0usize;
    for text in args.get_all("clause") {
        let c = clause::parse(text)?;
        clauses.push(c.to_json());
        clause_count += 1;
    }
    let mut body = Json::obj();
    body.set("id", Json::s(id.clone()));
    // The caller's own id of the job — a builder-ide work order, a ticket.
    // Empty when nobody said; the row is still a complete row.
    body.set(
        "external_id",
        Json::s(args.get("external-id").unwrap_or("").to_string()),
    );
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
    body.set("clauses", clauses);
    body.set("reconstructed", Json::b(false));
    body.set("source", Json::s(args.get("source").unwrap_or("gc job new").to_string()));

    let row = ledger::append(ledger_path, &now(args), "job.new", body.clone())?;
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
    if clause_count > 0 {
        println!("{} clause{} in the contract", clause_count, if clause_count == 1 { "" } else { "s" });
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    print_body_json(args, &body);
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

    if args.has("submit") && job.status != JobStatus::Open && job.status != JobStatus::Awarded {
        return Err(format!(
            "job {} is {} — it cannot take another bid",
            job.id,
            job.status.as_str()
        ));
    }

    // The body is built whether or not the bid is written, so that `--json`
    // says the same thing in a dry run as in a submitted one. The id is
    // deterministic: it is the next free one, so a dry run's id is the id
    // the same bid would take.
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

    if args.has("submit") {
        let row = ledger::append(ledger_path, &now(args), "bid.new", body.clone())?;
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
    print_body_json(args, &body);
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

    // Clauses the award negotiates on top of the job's own, overriding by
    // metric name.
    let mut negotiated = Json::arr();
    let mut negotiated_count = 0usize;
    for text in args.get_all("clause") {
        let c = clause::parse(text)?;
        negotiated.push(c.to_json());
        negotiated_count += 1;
    }

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("bid_id", Json::s(chosen.id.clone()));
    body.set("sub", Json::s(chosen.sub.clone()));
    body.set("score", Json::n(score));
    body.set("cost_score", Json::n(cost_score));
    body.set("on_time_probability", Json::n(ontime));
    body.set("fit", Json::n(fit));
    body.set("clauses", negotiated);
    body.set(
        "rationale",
        Json::s(
            args.get("rationale")
                .unwrap_or("cost, on-time record and fit")
                .to_string(),
        ),
    );
    let row = ledger::append(ledger_path, &now(args), "award", body.clone())?;
    println!(
        "awarded {} to {} (bid {}): score {:.3} = 0.40*cost {:.3} + 0.40*on-time {:.3} + 0.20*fit {:.3}",
        job.id, chosen.sub, chosen.id, score, cost_score, ontime, fit
    );
    if negotiated_count > 0 {
        println!(
            "{} clause{} negotiated at award (overriding the job's own by metric name)",
            negotiated_count,
            if negotiated_count == 1 { "" } else { "s" }
        );
    }
    if let Some(c) = chosen.crew_min {
        if c > job.budget_min {
            eprintln!(
                "gc: warning — the bid ({} min) is above the job's crew-time ceiling ({} min)",
                c, job.budget_min
            );
        }
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    print_body_json(args, &body);
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
    let now_ts = now(args);
    let burn = used / effective_bid;
    let elapsed = job.job_elapsed_min_at(&now_ts);

    // The metrics of this moment: what gc computes, then what the seat
    // reported where the name does not collide.
    let metrics = merged_metrics(
        builtin_metrics(used, effective_bid, elapsed),
        metric_flags(args)?,
    );

    let check = resolve_check(args, &job, &metrics, check_timeout_sec(args)?)?;
    let clauses = check_clauses(&job.clauses_in_force(), &metrics, elapsed);
    let stop_ratio = job.stop_ratio;
    let stop_required = burn >= stop_ratio && check.verdict != verdict::Verdict::Pass;

    let fc = forecast::at_checkpoint(
        &job.award_ts,
        &now_ts,
        used,
        effective_bid,
        stop_ratio,
        job.effective_deadline_min(),
    );

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
    body.set("check", check_json(&check));
    body.set("metrics", metrics_json(&metrics));
    body.set("clauses", clauses_json(&clauses));
    body.set("forecast", forecast_json(&fc));

    let row = ledger::append(ledger_path, &now_ts, "checkpoint", body.clone())?;
    println!(
        "checkpoint on {}: {} crew-min used of {} ({:.0}% of the bid)",
        job.id,
        used,
        effective_bid,
        burn * 100.0
    );
    println!(
        "goal line: {} ({})",
        check.verdict.as_str(),
        describe_check(&check)
    );
    for c in &clauses {
        if c.verdict != verdict::Verdict::Inconclusive || c.value.is_some() {
            println!(
                "clause {}: {} ({})",
                c.metric,
                c.verdict.as_str(),
                match c.value {
                    Some(v) => format!("{:.3}", v),
                    None => "no value".to_string(),
                }
            );
        } else {
            println!("clause {}: inconclusive (no value reported)", c.metric);
        }
    }
    println!("forecast: {}", fc.note);
    if fc.verdict == forecast::ForecastVerdict::Warn {
        println!(
            "FORECAST WARNING: the stop line ({:.0}% of the bid) is reached before the deadline at this rate — \
             this is a warning, not a stop; re-plan while there is job-time left",
            stop_ratio * 100.0
        );
    }
    if stop_required {
        println!(
            "STOP REQUIRED: the goal line has not passed at {:.0}% of the bid ({:.0}% of the allowance). \
             Report and stop; the general contractor must re-scope, extend, or cancel.",
            stop_ratio * 100.0,
            stop_ratio * 100.0
        );
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    print_body_json(args, &body);
    Ok(())
}

/// How a check was decided, in one short line.
fn describe_check(c: &check::CheckResult) -> String {
    let mut s = match c.by.as_str() {
        "gc" => match c.exit_code {
            Some(code) => format!("command re-run by gc, exit {}", code),
            None => "command re-run by gc".to_string(),
        },
        "metric" => "the reported metric against its threshold".to_string(),
        "human" => "a human's judgement".to_string(),
        _ => "no check ran".to_string(),
    };
    if !c.note.is_empty() {
        s.push_str(&format!(" — {}", c.note));
    }
    s
}

// -------------------------------------------------------------- close -----

/// The goal-line check at close.
///
/// A command-kind or metric-kind job has a machine-checkable goal line, and
/// gc decides it here — it runs the command or compares the metric. A stated
/// outcome on such a job is refused: saying "done" is not the same as
/// proving it.
///
/// A report-kind job never had a machine check written down, so the desk's
/// word is the check: `--accepted`, `--failed`, or `--check inconclusive`
/// when it could not be judged at all. The third one matters: a night cycle
/// that cannot tell whether the work landed must be able to say so, and
/// "could not tell" is not "failed".
fn resolve_close_check(
    args: &Args,
    job: &model::Job,
    metrics: &[(String, f64)],
    timeout_sec: u64,
) -> Result<check::CheckResult, String> {
    let requested = args.get("check").unwrap_or("auto").to_string();
    if !["auto", "pass", "fail", "inconclusive"].contains(&requested.as_str()) {
        return Err(format!(
            "--check wants auto, pass, fail or inconclusive, not '{}'",
            requested
        ));
    }
    let accepted = args.has("accepted");
    let failed = args.has("failed");
    if accepted && failed {
        return Err("pick one: --accepted or --failed".to_string());
    }
    if (accepted || failed) && requested != "auto" {
        return Err(format!(
            "job {}: state the outcome once — --accepted/--failed or --check, not both",
            job.id
        ));
    }

    if job.acceptance.kind == "report" {
        if accepted {
            return Ok(check::CheckResult::human(true));
        }
        if failed {
            return Ok(check::CheckResult::human(false));
        }
        return match requested.as_str() {
            "pass" => Ok(check::CheckResult::human(true)),
            "fail" => Ok(check::CheckResult::human(false)),
            "inconclusive" => Ok(check::CheckResult::cannot(
                "human",
                "the outcome could not be judged",
            )),
            _ => Err(format!(
                "job {} has a report-kind goal line: state the outcome with --accepted or \
                 --failed, or --check inconclusive when it could not be judged",
                job.id
            )),
        };
    }

    // A command or a metric decides for itself.
    if accepted || failed {
        return Err(format!(
            "the goal line of job {} is {}-kind: gc decides it at close by {} — \
             --accepted/--failed are for report-kind jobs only",
            job.id,
            job.acceptance.kind,
            if job.acceptance.kind == "cmd" {
                "re-running the acceptance command"
            } else {
                "comparing the metric against its threshold"
            }
        ));
    }
    if requested == "pass" || requested == "fail" {
        return Err(format!(
            "--check {} states an outcome the goal line decides for itself: job {}'s \
             acceptance is {}-kind, so it is run (or measured) here, not said. \
             --check inconclusive records that it could not run.",
            requested,
            job.id,
            job.acceptance.kind
        ));
    }
    if requested == "inconclusive" {
        return Ok(check::CheckResult::cannot(
            "human",
            "the check could not be run at this moment",
        ));
    }
    match job.acceptance.kind.as_str() {
        "cmd" => Ok(check::run_cmd(&job.acceptance.cmd, timeout_sec)),
        _ => Ok(metric_check(job, metrics)),
    }
}

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

    // Honest actuals, part one: the close cannot report less crew-time than
    // a checkpoint already wrote to the ledger. The floor is recomputable;
    // the ceiling is not, so it is not checked.
    if let Some(cp) = job.checkpoints.last() {
        if actual_crew < cp.crew_used_min - 1e-9 {
            return Err(format!(
                "job {} cannot close on {} crew-minutes: checkpoint at {} already reported {}",
                job.id, actual_crew, cp.ts, cp.crew_used_min
            ));
        }
    }

    let method = args.get("method").unwrap_or("wall").to_string();
    if !["wall", "tokens", "estimated"].contains(&method.as_str()) {
        return Err(format!(
            "unknown --method '{}': use wall, tokens or estimated",
            method
        ));
    }
    let tokens = args.num("tokens")?.map(|t| t as u64);
    let now_ts = now(args);

    let bid = job.awarded_bid(&state.bids);
    let effective_bid = job.effective_bid_min(bid);
    let elapsed = job.job_elapsed_min_at(&now_ts);
    let metrics = merged_metrics(
        builtin_metrics(actual_crew, effective_bid, elapsed),
        metric_flags(args)?,
    );

    // Honest actuals, part two: the goal line is decided here, not reported.
    // A command-kind acceptance is re-run and its exit code read; a metric
    // kind is compared against the reported value; only a report-kind job —
    // no machine check was ever written down — takes a human's --accepted
    // or --failed, or says it could not be judged at all.
    let check = resolve_close_check(args, &job, &metrics, check_timeout_sec(args)?)?;
    let accepted = check.verdict == verdict::Verdict::Pass;

    let clauses = check_clauses(&job.clauses_in_force(), &metrics, elapsed);
    let clause_penalty: f64 = clauses
        .iter()
        .filter(|c| c.verdict == verdict::Verdict::Fail)
        .map(|c| c.penalty_min)
        .sum();

    let debt_before = state.debt_min(&job.awarded_sub, &job.class);
    let outcome = accounting::close_outcome(
        &job,
        bid,
        actual_crew,
        actual_job,
        args.num("late-days")?,
        debt_before,
        accepted,
        clause_penalty,
    );

    let mut body = Json::obj();
    body.set("job_id", Json::s(job.id.clone()));
    body.set("accepted", Json::b(accepted));
    body.set("acceptance_verdict", Json::s(check.verdict.as_str()));
    body.set("check", check_json(&check));
    body.set("actual_crew_min", Json::n(actual_crew));
    body.set("actual_job_min", Json::n(actual_job));
    body.set("late_days", Json::n(outcome.late_days));
    body.set("effective_bid_min", Json::n(outcome.effective_bid_min));
    body.set("overrun_min", Json::n(outcome.overrun_min));
    body.set("penalty_min", Json::n(outcome.penalty_min));
    body.set("clause_penalty_min", Json::n(clause_penalty));
    body.set("clauses", clauses_json(&clauses));
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

    let row = ledger::append(ledger_path, &now_ts, "close", body.clone())?;
    println!(
        "closed {}: {} crew-min against a promise of {}, overrun {}, penalty {}, debt {:+}",
        job.id,
        actual_crew,
        outcome.effective_bid_min,
        outcome.overrun_min,
        outcome.penalty_min,
        outcome.debt_delta_min
    );
    println!(
        "goal line: {} ({})",
        check.verdict.as_str(),
        describe_check(&check)
    );
    for c in &clauses {
        if c.verdict == verdict::Verdict::Fail {
            println!(
                "clause {} breached: {} — penalty {} crew-min",
                c.metric,
                c.value.map(|v| format!("{:.3}", v)).unwrap_or_default(),
                c.penalty_min
            );
        }
    }
    if !accepted {
        println!(
            "the goal line did not pass{}: no repayment credit, and the record says so",
            if check.verdict == verdict::Verdict::Inconclusive {
                " (the check could not run)"
            } else {
                ""
            }
        );
    }
    println!("row {} written (hash {})", row.seq, &row.hash[..12]);
    print_body_json(args, &body);
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
