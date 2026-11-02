//! The report: what each subcontractor's record says, per job class.
//!
//! Three curves are reported, and they are not the same curve:
//!
//! - **the factor** — q80 ÷ median of the seat's clean runs on the class.
//!   This is what a bid is built from.
//! - **all runs** — the same, over every finished run including the ones
//!   that were cut short by a quota stop. This is the pain the factor does
//!   not show.
//! - **promise** — actual crew-time ÷ the bid the seat promised. This only
//!   exists for jobs with a real bid; the reconstructed history has no
//!   promises, only plan allowances.
//!
//! Every number here is recomputed from the ledger rows.

use crate::calib::{actuals_for, quantile, reputation};
use crate::json::Json;
use crate::model::State;
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub struct ReportFilter {
    pub sub: Option<String>,
    pub class: Option<String>,
}

impl ReportFilter {
    pub fn matches_sub(&self, sub: &str) -> bool {
        match &self.sub {
            None => true,
            Some(s) => s == sub,
        }
    }

    pub fn matches_class(&self, class: &str) -> bool {
        match &self.class {
            None => true,
            Some(c) => c == class,
        }
    }
}

/// The (sub, class) pairs that appear anywhere in the ledger.
pub fn pairs_of(state: &State) -> Vec<(String, String)> {
    let mut set: BTreeMap<String, BTreeMap<String, ()>> = BTreeMap::new();
    for job in &state.jobs {
        if job.awarded_sub.is_empty() {
            continue;
        }
        set.entry(job.awarded_sub.clone())
            .or_default()
            .entry(job.class.clone())
            .or_insert(());
    }
    for bid in &state.bids {
        if bid.crew_min.is_none() {
            continue;
        }
        let class = state
            .jobs
            .iter()
            .find(|j| j.id == bid.job_id)
            .map(|j| j.class.clone())
            .unwrap_or_default();
        set.entry(bid.sub.clone())
            .or_default()
            .entry(class)
            .or_insert(());
    }
    let mut out = Vec::new();
    for (sub, classes) in set {
        for class in classes.keys() {
            out.push((sub.clone(), class.clone()));
        }
    }
    out
}

/// The plan allowance a seat worked under, as the median of the proxy bids
/// in the history. A pi seat has none: it is billed in tokens.
pub fn plan_allowance(state: &State, sub: &str) -> Option<f64> {
    let mut seen: Vec<f64> = state
        .bids
        .iter()
        .filter(|b| b.sub == sub && b.proxy)
        .filter_map(|b| b.crew_min)
        .collect();
    if seen.is_empty() {
        None
    } else {
        quantile(&seen, 0.5)
    }
}

/// The text report.
pub fn text_report(state: &State, filter: &ReportFilter) -> String {
    let mut out = String::new();

    let closed: Vec<_> = state.jobs.iter().filter(|j| j.close.is_some()).collect();
    let reconstructed = state.jobs.iter().filter(|j| j.reconstructed).count();
    let cancelled = state
        .jobs
        .iter()
        .filter(|j| j.status == crate::model::JobStatus::Cancelled)
        .count();
    let open = state
        .jobs
        .iter()
        .filter(|j| j.status == crate::model::JobStatus::Open)
        .count();

    out.push_str("gc report — the general contractor's book\n");
    out.push_str(&format!(
        "ledger: {} rows, {} jobs ({} open, {} closed, {} cancelled, {} reconstructed from history), {} bids, {} retoolings\n\n",
        state.rows,
        state.jobs.len(),
        open,
        closed.len(),
        cancelled,
        reconstructed,
        state.bids.len(),
        state.retools.len()
    ));

    // ---- the seats -------------------------------------------------------
    out.push_str("SEATS (per subcontractor, per job class)\n");
    out.push_str(&format!(
        "{:<14} {:<22} {:>3} {:>7} {:>9} {:>9} {:>6} {:>10} {:>9}  {}\n",
        "seat", "class", "n", "on-time", "goal-line", "in-budget", "rep", "debt(min)", "allow", "status"
    ));
    let mut any_seat = false;
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        any_seat = true;
        let rep = reputation(state, &sub, &class);
        let allowance = plan_allowance(state, &sub).unwrap_or(0.0);
        let status = if rep.debt_min >= crate::DEEP_DEBT_MIN {
            "IN DEBT — retool before hiring on this class"
        } else if rep.n == 0 {
            "no history"
        } else {
            "ok"
        };
        out.push_str(&format!(
            "{:<14} {:<22} {:>3} {:>6.0}% {:>8.0}% {:>8.0}% {:>6.0} {:>10} {:>9}  {}\n",
            sub,
            class,
            rep.n,
            rep.on_time_rate * 100.0,
            rep.goal_line_rate * 100.0,
            rep.budget_hit_rate * 100.0,
            rep.score,
            fmt_min(rep.debt_min),
            fmt_min(allowance),
            status
        ));
    }
    if !any_seat {
        out.push_str("(no subcontractor has a record yet)\n");
    }

    // ---- the factor ------------------------------------------------------
    out.push_str("\nTHE FACTOR — q80 ÷ median of the seat's clean runs (this is what a bid is built from)\n");
    let mut any_factor = false;
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        let clean = actuals_for(state, &sub, &class, true);
        if clean.is_empty() {
            continue;
        }
        any_factor = true;
        let med = quantile(&clean, 0.5).unwrap_or(0.0);
        let q80 = quantile(&clean, 0.8).unwrap_or(0.0);
        let factor = if med > 0.0 { q80 / med } else { 0.0 };
        out.push_str(&format!(
            "{:<14} {:<22} n={:<3} median {:>6.1} min  q80 {:>6.1} min  factor {:.2}   runs [{}]\n",
            sub,
            class,
            clean.len(),
            med,
            q80,
            factor,
            fmt_list(&clean)
        ));
    }
    if !any_factor {
        out.push_str("(no clean runs yet — every bid falls back to the prior factor of 1.25)\n");
    }

    // ---- all runs, including the ones that went wrong --------------------
    out.push_str("\nALL RUNS — every finished run, including the ones that were cut short\n");
    out.push_str("(the factor above ignores these; the debt and the missed goal lines below do not)\n");
    let mut any_all = false;
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        let all = actuals_for(state, &sub, &class, false);
        if all.is_empty() {
            continue;
        }
        any_all = true;
        let med = quantile(&all, 0.5).unwrap_or(0.0);
        let q80 = quantile(&all, 0.8).unwrap_or(0.0);
        let clean = actuals_for(state, &sub, &class, true).len();
        out.push_str(&format!(
            "{:<14} {:<22} n={:<3} median {:>6.1} min  q80 {:>6.1} min  ({}/{} clean)   runs [{}]\n",
            sub,
            class,
            all.len(),
            med,
            q80,
            clean,
            all.len(),
            fmt_list(&all)
        ));
    }
    if !any_all {
        out.push_str("(no finished runs yet)\n");
    }

    // ---- promise ---------------------------------------------------------
    out.push_str("\nPROMISE — actual crew-time ÷ the bid the seat promised\n");
    let mut any_promise = false;
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        let mut ratios: Vec<f64> = Vec::new();
        for job in &state.jobs {
            if job.awarded_sub != sub || job.class != class {
                continue;
            }
            let close = match &job.close {
                Some(c) => c,
                None => continue,
            };
            let bid = match job.awarded_bid(&state.bids) {
                Some(b) => b,
                None => continue,
            };
            if bid.proxy || bid.crew_min.unwrap_or(0.0) <= 0.0 {
                continue;
            }
            ratios.push(close.actual_crew_min / bid.crew_min.unwrap_or(1.0));
        }
        if ratios.is_empty() {
            continue;
        }
        any_promise = true;
        let under = ratios.iter().filter(|x| **x <= 1.0).count();
        out.push_str(&format!(
            "{:<14} {:<22} n={:<3} median {:.3}  q80 {:.3}  came in under the promise {}/{}  ratios [{}]\n",
            sub,
            class,
            ratios.len(),
            quantile(&ratios, 0.5).unwrap_or(0.0),
            quantile(&ratios, 0.8).unwrap_or(0.0),
            under,
            ratios.len(),
            fmt_list(&ratios)
        ));
    }
    if !any_promise {
        out.push_str("(no promise/actual pairs yet — the reconstructed history records allowances, not promises)\n");
    }

    // ---- the book --------------------------------------------------------
    let mut promised = 0.0;
    let mut spent = 0.0;
    let mut penalties = 0.0;
    let mut overrun = 0.0;
    let mut late_jobs = 0usize;
    let mut missed = 0usize;
    for job in &closed {
        if let Some(c) = &job.close {
            promised += c.effective_bid_min;
            spent += c.actual_crew_min;
            penalties += c.penalty_min;
            overrun += c.overrun_min;
            if c.late_days > 0.0 {
                late_jobs += 1;
            }
            if !c.accepted {
                missed += 1;
            }
        }
    }
    let mut debt_total = 0.0;
    for job in &closed {
        if let Some(c) = &job.close {
            debt_total += c.debt_delta_min;
        }
    }

    out.push_str("\nTHE BOOK\n");
    out.push_str(&format!(
        "  crew-time promised {}   spent {}   overrun {}   penalties {}\n",
        fmt_min(promised),
        fmt_min(spent),
        fmt_min(overrun),
        fmt_min(penalties)
    ));
    out.push_str(&format!(
        "  jobs late {} of {}   goal lines missed {} of {}   debt outstanding {} crew-minutes\n",
        late_jobs,
        closed.len(),
        missed,
        closed.len(),
        fmt_min(debt_total)
    ));

    // ---- how the crew-time was measured ----------------------------------
    let mut wall = 0usize;
    let mut tokens = 0usize;
    let mut estimated = 0usize;
    for job in &closed {
        if let Some(c) = &job.close {
            match c.method.as_str() {
                "wall" => wall += 1,
                "tokens" => tokens += 1,
                _ => estimated += 1,
            }
        }
    }
    out.push_str("\nHOW CREW-TIME WAS MEASURED\n");
    out.push_str(&format!(
        "  wall-clock {}   token-counted {}   estimated {}\n",
        wall, tokens, estimated
    ));
    out.push_str(
        "  a zcode or mcode seat is a flat plan on a five-hour window: its crew-time is wall time\n  \
         against that window, and the window share is the 'allow' column above. A pi seat reports\n  \
         tokens, so its crew-time is a token count, not minutes, and it forms no pair here.\n",
    );

    // ---- blocked seats ---------------------------------------------------
    let blocked: Vec<String> = pairs_of(state)
        .iter()
        .filter(|(sub, class)| filter.matches_sub(sub) && filter.matches_class(class))
        .filter(|(sub, class)| {
            let rep = reputation(state, sub, class);
            rep.debt_min >= crate::DEEP_DEBT_MIN
                && state.retooled_after(sub, class, "9999").is_none()
        })
        .map(|(sub, class)| {
            format!(
                "  {} on '{}': debt {} crew-minutes — retool before hiring again",
                sub,
                class,
                fmt_min(reputation(state, &sub, &class).debt_min)
            )
        })
        .collect();
    if !blocked.is_empty() {
        out.push_str("\nBLOCKED (deep debt, not retooled)\n");
        for line in blocked {
            out.push_str(&line);
            out.push('\n');
        }
    }

    out
}

/// The same report as JSON.
pub fn json_report(state: &State, filter: &ReportFilter) -> Json {
    let mut root = Json::obj();
    root.set("rows", Json::n(state.rows as f64));
    root.set("jobs", Json::n(state.jobs.len() as f64));
    root.set("bids", Json::n(state.bids.len() as f64));

    let mut seats = Json::arr();
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        let rep = reputation(state, &sub, &class);
        let mut o = Json::obj();
        o.set("sub", Json::s(sub.clone()));
        o.set("class", Json::s(class.clone()));
        o.set("jobs", Json::n(rep.n as f64));
        o.set("on_time_rate", Json::n(rep.on_time_rate));
        o.set("goal_line_rate", Json::n(rep.goal_line_rate));
        o.set("budget_hit_rate", Json::n(rep.budget_hit_rate));
        o.set("reputation", Json::n(rep.score));
        o.set("debt_min", Json::n(rep.debt_min));
        o.set(
            "median_ratio",
            match rep.median_ratio {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        o.set(
            "plan_allowance_min",
            match plan_allowance(state, &sub) {
                Some(v) => Json::n(v),
                None => Json::Null,
            },
        );
        o.set("blocked", Json::b(rep.debt_min >= crate::DEEP_DEBT_MIN));
        seats.push(o);
    }
    root.set("seats", seats);

    let mut factor = Json::arr();
    let mut all_runs = Json::arr();
    let promise = Json::arr();
    for (sub, class) in pairs_of(state) {
        if !filter.matches_sub(&sub) || !filter.matches_class(&class) {
            continue;
        }
        let clean = actuals_for(state, &sub, &class, true);
        if !clean.is_empty() {
            let med = quantile(&clean, 0.5).unwrap_or(0.0);
            let q80 = quantile(&clean, 0.8).unwrap_or(0.0);
            let mut o = Json::obj();
            o.set("sub", Json::s(sub.clone()));
            o.set("class", Json::s(class.clone()));
            o.set("n", Json::n(clean.len() as f64));
            o.set("median_min", Json::n(med));
            o.set("q80_min", Json::n(q80));
            o.set("factor", Json::n(if med > 0.0 { q80 / med } else { 0.0 }));
            o.set("runs", num_array(&clean));
            factor.push(o);
        }
        let all = actuals_for(state, &sub, &class, false);
        if !all.is_empty() {
            let mut o = Json::obj();
            o.set("sub", Json::s(sub.clone()));
            o.set("class", Json::s(class.clone()));
            o.set("n", Json::n(all.len() as f64));
            o.set("median_min", Json::n(quantile(&all, 0.5).unwrap_or(0.0)));
            o.set("q80_min", Json::n(quantile(&all, 0.8).unwrap_or(0.0)));
            o.set("runs", num_array(&all));
            all_runs.push(o);
        }
    }
    root.set("factor_curve", factor);
    root.set("all_runs_curve", all_runs);
    root.set("promise_curve", promise);
    root
}

fn num_array(values: &[f64]) -> Json {
    let mut arr = Json::arr();
    for v in values {
        arr.push(Json::n(*v));
    }
    arr
}

fn fmt_list(values: &[f64]) -> String {
    values
        .iter()
        .map(|x| format!("{:.1}", x))
        .collect::<Vec<String>>()
        .join(", ")
}

fn fmt_min(min: f64) -> String {
    if (min - min.round()).abs() < 0.05 {
        format!("{}", min.round() as i64)
    } else {
        format!("{:.1}", min)
    }
}
