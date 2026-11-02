//! The clause grammar: metric + target + window + penalty.
//!
//! From lucineer/cuda-contract (`SlaClause { metric, target, minimum,
//! penalty_per_violation, window_ms }`): contract terms as arithmetic on
//! recorded numbers, not prose. A clause is one line of text a person can
//! read and a parser can check:
//!
//! ```text
//! coverage >= 0.8 window 1440 penalty 30
//! ```
//!
//! — the metric `coverage` must be at least `0.8`, checked within 1440
//! job-minutes of the award, and a breach at close costs 30 crew-minutes.
//!
//! Metric values arrive two ways at a checkpoint or a close: the seat
//! reports them (`--metric name=value`), or `gc` computes them itself
//! (`crew_used_min`, `burn`, `job_elapsed_min`). The computed ones win: a
//! number the ledger can recompute is never taken on assertion. A clause
//! whose metric has no value this time is **inconclusive**, not failed —
//! the check could not run.

use crate::json::Json;
use crate::verdict::Verdict;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Op {
    /// The metric must be greater than or equal to the target.
    Ge,
    /// The metric must be less than or equal to the target.
    Le,
}

impl Op {
    pub fn as_str(&self) -> &'static str {
        match self {
            Op::Ge => ">=",
            Op::Le => "<=",
        }
    }

    pub fn parse(text: &str) -> Option<Op> {
        match text {
            ">=" | "=>" | "ge" => Some(Op::Ge),
            "<=" | "=<" | "le" => Some(Op::Le),
            _ => None,
        }
    }

    pub fn holds(&self, value: f64, target: f64) -> bool {
        match self {
            Op::Ge => value >= target,
            Op::Le => value <= target,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Clause {
    pub metric: String,
    pub op: Op,
    pub target: f64,
    /// The clause is checked only within this many job-minutes of the award.
    /// `None` means it is in force for the whole job.
    pub window_min: Option<f64>,
    /// Crew-minutes charged at close for a breach.
    pub penalty_min: f64,
}

/// Parse one clause from its text form:
/// `<metric> <op> <target> [window <minutes>] [penalty <crew-min>]`.
pub fn parse(text: &str) -> Result<Clause, String> {
    let tokens: Vec<&str> = text.split_whitespace().collect();
    if tokens.len() < 3 {
        return Err(format!(
            "clause '{}' is too short: it is '<metric> <op> <target> [window <minutes>] [penalty <crew-min>]'",
            text
        ));
    }
    let metric = tokens[0];
    if metric.contains('=') || metric.contains('>') || metric.contains('<') {
        return Err(format!(
            "clause '{}': the metric name comes first, then the operator ('{} >= 0.8', not '>= 0.8')",
            text, metric
        ));
    }
    let op = Op::parse(tokens[1]).ok_or_else(|| {
        format!(
            "clause '{}': the operator must be >= or <=, not '{}'",
            text, tokens[1]
        )
    })?;
    let target: f64 = tokens[2]
        .parse()
        .map_err(|_| format!("clause '{}': the target '{}' must be a number", text, tokens[2]))?;

    let mut window_min: Option<f64> = None;
    let mut penalty_min: Option<f64> = None;
    let mut i = 3;
    while i < tokens.len() {
        let keyword = tokens[i];
        let value = tokens
            .get(i + 1)
            .ok_or_else(|| format!("clause '{}': '{}' needs a number after it", text, keyword))?;
        let n: f64 = value.parse().map_err(|_| {
            format!("clause '{}': the value after '{}' must be a number", text, keyword)
        })?;
        match keyword {
            "window" | "window-min" => {
                if n <= 0.0 {
                    return Err(format!(
                        "clause '{}': a window must be positive (leave it off for the whole job)",
                        text
                    ));
                }
                window_min = Some(n);
            }
            "penalty" | "penalty-min" => {
                if n < 0.0 {
                    return Err(format!("clause '{}': a penalty cannot be negative", text));
                }
                penalty_min = Some(n);
            }
            other => {
                return Err(format!(
                    "clause '{}': '{}' is not a clause keyword (window, penalty)",
                    text, other
                ))
            }
        }
        i += 2;
    }

    Ok(Clause {
        metric: metric.to_string(),
        op,
        target,
        window_min,
        penalty_min: penalty_min.unwrap_or(0.0),
    })
}

impl Clause {
    /// True when the clause is in force at this moment: a windowed clause
    /// only counts inside its window from the award. When the elapsed
    /// job-time is unknown, a windowed clause cannot be placed in time, so
    /// it does not apply.
    pub fn in_force_at(&self, job_elapsed_min: Option<f64>) -> bool {
        match (self.window_min, job_elapsed_min) {
            (None, _) => true,
            (Some(_), None) => false,
            (Some(w), Some(elapsed)) => elapsed <= w,
        }
    }

    /// Check the clause against a metric value. No value: the check could
    /// not run, which is inconclusive, not a breach.
    pub fn evaluate(&self, value: Option<f64>) -> Verdict {
        match value {
            Some(v) if self.op.holds(v, self.target) => Verdict::Pass,
            Some(_) => Verdict::Fail,
            None => Verdict::Inconclusive,
        }
    }

    pub fn describe(&self) -> String {
        let mut s = format!("{} {} {}", self.metric, self.op.as_str(), fmt_num(self.target));
        if let Some(w) = self.window_min {
            s.push_str(&format!(", within {} job-min of the award", fmt_num(w)));
        }
        if self.penalty_min > 0.0 {
            s.push_str(&format!(
                ", breach costs {} crew-min",
                fmt_num(self.penalty_min)
            ));
        }
        s
    }

    pub fn to_json(&self) -> Json {
        let mut o = Json::obj();
        o.set("metric", Json::s(self.metric.clone()));
        o.set("op", Json::s(self.op.as_str()));
        o.set("target", Json::n(self.target));
        o.set(
            "window_min",
            match self.window_min {
                Some(w) => Json::n(w),
                None => Json::Null,
            },
        );
        o.set("penalty_min", Json::n(self.penalty_min));
        o
    }

    pub fn from_json(v: &Json) -> Clause {
        Clause {
            metric: v.str_at("metric").unwrap_or("").to_string(),
            op: Op::parse(v.str_at("op").unwrap_or(">=")).unwrap_or(Op::Ge),
            target: v.f64_at("target").unwrap_or(0.0),
            window_min: v.f64_at("window_min"),
            penalty_min: v.f64_at("penalty_min").unwrap_or(0.0),
        }
    }
}

/// The clauses in force on a job: the job's own, with any clause the award
/// negotiated overriding by metric name.
pub fn merge(job_clauses: &[Clause], award_clauses: &[Clause]) -> Vec<Clause> {
    let mut out: Vec<Clause> = Vec::new();
    for c in job_clauses {
        if !award_clauses.iter().any(|a| a.metric == c.metric) {
            out.push(c.clone());
        }
    }
    out.extend(award_clauses.iter().cloned());
    out
}

/// Read a clauses array out of a row body.
pub fn from_json_array(v: Option<&Json>) -> Vec<Clause> {
    v.and_then(|x| x.as_arr())
        .map(|items| items.iter().map(Clause::from_json).collect())
        .unwrap_or_default()
}

fn fmt_num(n: f64) -> String {
    if (n - n.round()).abs() < 1e-9 {
        format!("{}", n.round() as i64)
    } else {
        format!("{}", n)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clauses_parse_from_text() {
        let c = parse("coverage >= 0.8 window 1440 penalty 30").unwrap();
        assert_eq!(c.metric, "coverage");
        assert_eq!(c.op, Op::Ge);
        assert_eq!(c.target, 0.8);
        assert_eq!(c.window_min, Some(1440.0));
        assert_eq!(c.penalty_min, 30.0);

        let bare = parse("max_rss_mb <= 8192").unwrap();
        assert_eq!(bare.window_min, None);
        assert_eq!(bare.penalty_min, 0.0);
    }

    #[test]
    fn bad_clauses_say_what_is_wrong() {
        assert!(parse("coverage 0.8").is_err());
        assert!(parse("coverage == 0.8").is_err());
        assert!(parse(">= 0.8").is_err());
        assert!(parse("coverage >= eight").is_err());
        assert!(parse("coverage >= 0.8 sometime 5").is_err());
        assert!(parse("coverage >= 0.8 window 0").is_err());
    }

    #[test]
    fn a_missing_value_is_inconclusive() {
        let c = parse("coverage >= 0.8").unwrap();
        assert_eq!(c.evaluate(Some(0.9)), Verdict::Pass);
        assert_eq!(c.evaluate(Some(0.79)), Verdict::Fail);
        assert_eq!(c.evaluate(None), Verdict::Inconclusive);
        let le = parse("burn <= 0.5").unwrap();
        assert_eq!(le.evaluate(Some(0.5)), Verdict::Pass);
        assert_eq!(le.evaluate(Some(0.6)), Verdict::Fail);
    }

    #[test]
    fn a_window_places_the_clause_in_time() {
        let c = parse("coverage >= 0.8 window 60").unwrap();
        assert!(c.in_force_at(Some(10.0)));
        assert!(c.in_force_at(Some(60.0)));
        assert!(!c.in_force_at(Some(61.0)));
        assert!(!c.in_force_at(None));
        let whole = parse("coverage >= 0.8").unwrap();
        assert!(whole.in_force_at(None));
        assert!(whole.in_force_at(Some(100000.0)));
    }

    #[test]
    fn award_clauses_override_by_metric() {
        let job = vec![parse("coverage >= 0.8 penalty 30").unwrap()];
        let award = vec![parse("coverage >= 0.9 penalty 45").unwrap()];
        let merged = merge(&job, &award);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].target, 0.9);
        assert_eq!(merged[0].penalty_min, 45.0);
    }

    #[test]
    fn clauses_round_trip_through_json() {
        let c = parse("burn <= 0.8 window 480 penalty 20").unwrap();
        let back = Clause::from_json(&c.to_json());
        assert_eq!(back, c);
    }
}
