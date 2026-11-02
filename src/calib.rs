//! Calibration: how a seat's track record turns into a bid, and how a
//! track record becomes a reputation.
//!
//! The rule from the carpet example: overbidding beats underbidding. A seat
//! is judged at a high quantile of what it actually used, not at the median.
//!
//! The factor is scale-free on purpose. A job of a given class can be big or
//! small, so the GC's own estimate of the job sets the size, and the seat's
//! history sets how much bigger than that this seat makes it. The history is
//! only used for that ratio, so a small job and a large job of the same class
//! calibrate each other.

use crate::model::{Bid, State};

/// The factor used when a seat has no history on a class: the bid is 25%
/// above the GC's estimate. Deliberately generous — a bid with no evidence
/// behind it should be an overbid.
pub const PRIOR_FACTOR: f64 = 1.25;

/// Weight of the prior in the shrinkage, for a class-specific sample.
pub const SHRINK_CLASS: f64 = 2.0;

/// Weight of the prior in the shrinkage, when only the seat's other classes
/// are available.
pub const SHRINK_ALL: f64 = 4.0;

/// Confidence when there is no history at all.
pub const PRIOR_CONFIDENCE: f64 = 0.30;

/// Linear-interpolated quantile (the "type 7" rule, as numpy and R use).
/// `q` is in [0,1]; returns None for an empty sample.
pub fn quantile(values: &[f64], q: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut v: Vec<f64> = values.to_vec();
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if v.len() == 1 {
        return Some(v[0]);
    }
    let h = (v.len() - 1) as f64 * q.clamp(0.0, 1.0);
    let lo = h.floor() as usize;
    let hi = h.ceil() as usize;
    if lo == hi {
        return Some(v[lo]);
    }
    Some(v[lo] + (h - lo as f64) * (v[hi] - v[lo]))
}

/// The crew-times a seat used on finished jobs.
///
/// `clean_only` keeps the runs that were not interrupted: a run that was cut
/// short by a quota stop says how long the seat was away, not how long the
/// work takes. Those runs stay in the record — they are the debt and the
/// missed goal lines — but they do not set the bid.
pub fn actuals_for(state: &State, sub: &str, class: &str, clean_only: bool) -> Vec<f64> {
    let mut out: Vec<f64> = Vec::new();
    for job in &state.jobs {
        if job.awarded_sub != sub {
            continue;
        }
        if !class.is_empty() && job.class != class {
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
        if clean_only && !bid.calibratable {
            continue;
        }
        if close.actual_crew_min > 0.0 {
            out.push(close.actual_crew_min);
        }
    }
    out
}

/// The result of calibrating a bid for a seat on a class.
#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Calibration {
    /// The promise: crew-minutes.
    pub crew_min: f64,
    /// The promise for job-time (the T-minus). The seat's job-time is its
    /// active time, so it tracks the crew-time promise.
    pub job_min: f64,
    pub confidence: f64,
    /// The factor applied to the GC's estimate of the job.
    pub factor: f64,
    /// How many runs the factor came from.
    pub n_pairs: usize,
    /// Where the factor came from, in words a person can check.
    pub basis: String,
    /// The seat's median crew-time on this class, when known.
    pub median_min: Option<f64>,
    /// The q80 of the seat's crew-times on this class, when known.
    pub q80_min: Option<f64>,
    /// "class", "all-classes" or "prior".
    pub scope: String,
}

/// Compute the bid a seat's track record supports for a job class.
///
/// `estimate_min` is the general contractor's own estimate of the crew-time
/// the work needs. The seat's history says how much bigger than its median
/// this seat runs at the 80th percentile; that ratio is the factor, shrunk
/// toward the prior when the sample is small.
pub fn calibrate_bid(
    sub: &str,
    class: &str,
    state: &State,
    estimate_min: f64,
) -> Result<Calibration, String> {
    if estimate_min <= 0.0 {
        return Err("the job has no crew-time estimate to calibrate against".to_string());
    }

    let class_samples = actuals_for(state, sub, class, true);
    let (samples, scope, shrink) = if !class_samples.is_empty() {
        (class_samples, "class", SHRINK_CLASS)
    } else {
        let all = actuals_for(state, sub, "", true);
        if all.is_empty() {
            (Vec::new(), "prior", SHRINK_CLASS)
        } else {
            (all, "all-classes", SHRINK_ALL)
        }
    };

    let n = samples.len();
    if n == 0 {
        let crew = (estimate_min * PRIOR_FACTOR).round();
        return Ok(Calibration {
            crew_min: crew,
            job_min: crew,
            confidence: PRIOR_CONFIDENCE,
            factor: PRIOR_FACTOR,
            n_pairs: 0,
            basis: format!(
                "no finished run of seat '{}' on class '{}': the prior factor {:.2} over the estimate",
                sub, class, PRIOR_FACTOR
            ),
            median_min: None,
            q80_min: None,
            scope: "prior".to_string(),
        });
    }

    let median = quantile(&samples, 0.5).unwrap_or(0.0);
    let q80 = quantile(&samples, 0.8).unwrap_or(0.0);
    let raw_factor = if median > 0.0 { q80 / median } else { PRIOR_FACTOR };
    let factor = (n as f64 * raw_factor + shrink * PRIOR_FACTOR) / (n as f64 + shrink);
    let confidence = confidence_for(&samples, n, scope);
    let crew = (estimate_min * factor).round();

    let basis = match scope {
        "class" => format!(
            "track record: q80 {:.0} min over a median of {:.0} min on {} clean runs of class '{}' (factor {:.2}, shrunk toward the prior {:.2})",
            q80, median, n, class, factor, PRIOR_FACTOR
        ),
        _ => format!(
            "track record: no clean run on class '{}'; q80 {:.0} min over a median of {:.0} min on {} clean runs of other classes (factor {:.2}, shrunk harder toward the prior {:.2})",
            class, q80, median, n, factor, PRIOR_FACTOR
        ),
    };

    Ok(Calibration {
        crew_min: crew,
        job_min: crew,
        confidence,
        factor,
        n_pairs: n,
        basis,
        median_min: Some(median),
        q80_min: Some(q80),
        scope: scope.to_string(),
    })
}

/// Confidence in a bid: how tight the seat's crew-times are, and how many of
/// them there are. A wide spread or a thin sample means a low confidence, and
/// a low confidence should make the general contractor look elsewhere.
pub fn confidence_for(samples: &[f64], n: usize, scope: &str) -> f64 {
    if n == 0 || scope == "prior" {
        return PRIOR_CONFIDENCE;
    }
    let q20 = quantile(samples, 0.2).unwrap_or(0.0);
    let q50 = quantile(samples, 0.5).unwrap_or(0.0);
    let q80 = quantile(samples, 0.8).unwrap_or(0.0);
    let spread = if q50 > 0.0 { (q80 - q20) / q50 } else { 1.0 };
    let base = (1.0 - spread / 4.0).clamp(0.05, 0.95);
    let sample = (n as f64 / (n as f64 + 3.0)).sqrt();
    (base * sample).clamp(0.05, 0.95)
}

/// A seat's standing on one job class.
#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct Reputation {
    pub sub: String,
    pub class: String,
    pub n: usize,
    /// How many of those jobs had a recorded deadline. Lateness can only be
    /// known where there was one.
    pub n_deadline: usize,
    /// Fraction of finished jobs that were not late.
    pub on_time_rate: f64,
    /// Fraction of finished jobs that crossed their goal line.
    pub goal_line_rate: f64,
    /// Fraction of finished jobs that stayed inside the bid.
    pub budget_hit_rate: f64,
    /// 0..100, the blend the award score uses.
    pub score: f64,
    /// Median actual/estimate ratio.
    pub median_ratio: Option<f64>,
    /// Crew-minutes of debt carried on this class.
    pub debt_min: f64,
}

/// Compute a seat's standing on a class from the closed jobs it ran.
pub fn reputation(state: &State, sub: &str, class: &str) -> Reputation {
    let mut n = 0usize;
    let mut n_deadline = 0usize;
    let mut on_time = 0usize;
    let mut goal_line = 0usize;
    let mut in_budget = 0usize;
    // Jobs with no promise in force (a pi seat, whose history records no
    // minute allowance) are not counted as misses: there was nothing to
    // stay inside.
    let mut with_promise = 0usize;
    let mut all_ratios: Vec<f64> = Vec::new();

    for job in &state.jobs {
        if job.awarded_sub != sub {
            continue;
        }
        if !class.is_empty() && job.class != class {
            continue;
        }
        let close = match &job.close {
            Some(c) => c,
            None => continue,
        };
        n += 1;
        // A job with no recorded deadline has no lateness to measure: the
        // seat is neither late nor on time, it is unmeasured.
        if job.effective_deadline_min() > 0.0 {
            n_deadline += 1;
            if close.late_days <= 0.0 {
                on_time += 1;
            }
        }
        if close.accepted {
            goal_line += 1;
        }
        if close.effective_bid_min > 0.0 {
            with_promise += 1;
            if close.actual_crew_min <= close.effective_bid_min + 1e-9 {
                in_budget += 1;
            }
            all_ratios.push(close.actual_crew_min / close.effective_bid_min);
        }
    }

    let (on_time_rate, goal_line_rate, budget_hit_rate) = if n == 0 {
        (0.0, 0.0, 0.0)
    } else {
        (
            if n_deadline == 0 {
                0.0
            } else {
                on_time as f64 / n_deadline as f64
            },
            goal_line as f64 / n as f64,
            if with_promise == 0 {
                0.0
            } else {
                in_budget as f64 / with_promise as f64
            },
        )
    };
    // A component that could not be measured is dropped from the score and
    // its weight is taken off the denominator: a seat is not punished for a
    // deadline nobody recorded, and not credited for a promise it never
    // made.
    let w_ontime = if n_deadline > 0 { 0.4 } else { 0.0 };
    let w_goal = 0.4;
    let w_budget = if with_promise > 0 { 0.2 } else { 0.0 };
    let weight = w_ontime + w_goal + w_budget;
    let score = if n == 0 || weight == 0.0 {
        0.0
    } else {
        100.0 * (w_ontime * on_time_rate + w_goal * goal_line_rate + w_budget * budget_hit_rate)
            / weight
    };

    Reputation {
        sub: sub.to_string(),
        class: class.to_string(),
        n,
        n_deadline,
        on_time_rate,
        goal_line_rate,
        budget_hit_rate,
        score,
        median_ratio: quantile(&all_ratios, 0.5),
        debt_min: state.debt_min(sub, class),
    }
}

/// The probability a seat finishes on time, used by the award score.
/// With no history the prior is 0.5: unknown is not good.
pub fn on_time_probability(state: &State, sub: &str, class: &str) -> f64 {
    let rep = reputation(state, sub, class);
    if rep.n == 0 || rep.n_deadline == 0 {
        // Unknown is not good: with no deadline to be late against, the
        // prior is a coin toss.
        0.5
    } else {
        rep.on_time_rate
    }
}

/// How well a seat fits a class: 1.0 when it has closed work on the class,
/// 0.4 when it has not.
pub fn fit_score(state: &State, sub: &str, class: &str) -> f64 {
    let rep = reputation(state, sub, class);
    if rep.n > 0 {
        1.0
    } else {
        0.4
    }
}

/// The award score for one bid. Lower cost is better; on-time record and fit
/// push the other way. Weights are fixed and documented.
pub fn award_score(
    state: &State,
    job_class: &str,
    bid: &Bid,
    min_crew_min: f64,
) -> (f64, f64, f64, f64) {
    let crew = bid.crew_min.unwrap_or(f64::MAX);
    let cost_score = if crew <= 0.0 || min_crew_min <= 0.0 {
        0.0
    } else {
        (min_crew_min / crew).clamp(0.0, 1.0)
    };
    let ontime = on_time_probability(state, &bid.sub, job_class);
    let fit = fit_score(state, &bid.sub, job_class);
    let confidence = bid.confidence.clamp(0.0, 1.0);
    // A bid nobody is confident in is discounted, but a confident bid does
    // not outrank a cheaper one on its own.
    let adjusted_ontime = ontime * (0.5 + 0.5 * confidence);
    let score = 0.40 * cost_score + 0.40 * adjusted_ontime + 0.20 * fit;
    (score, cost_score, adjusted_ontime, fit)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quantile_matches_the_type_7_rule() {
        let v = vec![1.0, 2.0, 3.0, 4.0];
        assert_eq!(quantile(&v, 0.0), Some(1.0));
        assert_eq!(quantile(&v, 0.5), Some(2.5));
        assert!((quantile(&v, 0.8).unwrap() - 3.4).abs() < 1e-9);
        assert_eq!(quantile(&[], 0.5), None);
        assert_eq!(quantile(&[7.0], 0.9), Some(7.0));
    }

    #[test]
    fn confidence_falls_with_a_wide_spread() {
        let tight = vec![100.0, 104.0, 102.0, 98.0, 100.0];
        let wide = vec![20.0, 180.0, 40.0, 280.0, 100.0];
        let a = confidence_for(&tight, 5, "class");
        let b = confidence_for(&wide, 5, "class");
        assert!(a > b, "{} !> {}", a, b);
        assert!(a <= 0.95 && b >= 0.05);
    }

    #[test]
    fn no_history_means_the_prior() {
        assert_eq!(confidence_for(&[], 0, "prior"), PRIOR_CONFIDENCE);
    }
}
