//! The spend-rate forecast: warning before the stop line, not at it.
//!
//! From lucineer/cuda-budget (`should_alert()`, spend-rate forecasting) and
//! SuperInstance/build-guardian (a trend alert beats a raw threshold for
//! slow overruns): by the time the burn crosses the stop ratio it is too
//! late to re-plan. At every checkpoint the ledger already holds everything
//! a projection needs — the crew-time used and the job-time elapsed since
//! the award — so the checkpoint prints where this rate is heading.
//!
//! The forecast is a projection, not a verdict on the work: it assumes the
//! seat started working at the award (an assumption — a seat that sat idle
//! dilutes its rate and looks cheaper than it is) and that the rate so far
//! holds. It says so when it cannot say anything.

use crate::time::parse_iso;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ForecastVerdict {
    /// At this rate the stop line is not reached before the deadline.
    Ok,
    /// At this rate the stop line is reached before the deadline — warn
    /// now, while there is still job-time to re-plan with.
    Warn,
    /// Not enough has happened yet to project anything.
    Inconclusive,
}

impl ForecastVerdict {
    pub fn as_str(&self) -> &'static str {
        match self {
            ForecastVerdict::Ok => "ok",
            ForecastVerdict::Warn => "warn",
            ForecastVerdict::Inconclusive => "inconclusive",
        }
    }

    pub fn parse(text: &str) -> Option<ForecastVerdict> {
        match text {
            "ok" => Some(ForecastVerdict::Ok),
            "warn" => Some(ForecastVerdict::Warn),
            "inconclusive" => Some(ForecastVerdict::Inconclusive),
            _ => None,
        }
    }
}

/// Where the burn is heading, as of one checkpoint.
#[derive(Clone, Debug)]
pub struct Forecast {
    /// Crew-minutes spent per job-minute elapsed, since the award.
    pub rate_per_job_min: Option<f64>,
    /// Crew-minutes this rate lands on by the deadline.
    pub projected_crew_at_deadline: Option<f64>,
    /// Job-minutes from now until the stop line, at this rate. Negative
    /// once the line is already behind.
    pub minutes_to_stop_line: Option<f64>,
    pub verdict: ForecastVerdict,
    pub note: String,
}

/// Project the burn at a checkpoint.
///
/// `award_ts`/`now_ts` are ledger timestamps; `crew_used_min` is the
/// cumulative crew-time just reported; `effective_bid_min` and
/// `stop_ratio` give the stop line; `effective_deadline_min` is the
/// job-time allowance in force.
pub fn at_checkpoint(
    award_ts: &str,
    now_ts: &str,
    crew_used_min: f64,
    effective_bid_min: f64,
    stop_ratio: f64,
    effective_deadline_min: f64,
) -> Forecast {
    let elapsed_min = elapsed_minutes(award_ts, now_ts);
    let stop_line = effective_bid_min * stop_ratio;

    let (elapsed, bad_clock) = match elapsed_min {
        Some(e) if e >= 1.0 => (e, false),
        _ => (0.0, true),
    };
    if bad_clock {
        return Forecast {
            rate_per_job_min: None,
            projected_crew_at_deadline: None,
            minutes_to_stop_line: None,
            verdict: ForecastVerdict::Inconclusive,
            note: match elapsed_min {
                Some(e) if e >= 0.0 => format!(
                    "only {:.0} min of job-time has passed since the award; a rate from \
                     less than a minute would be noise, so nothing is projected",
                    e
                ),
                _ => "no job-time has passed since the award (or the clock cannot be read), \
                      so there is no rate to project"
                    .to_string(),
            },
        };
    }

    let rate = crew_used_min / elapsed;
    let minutes_to_stop = if rate > 0.0 {
        Some((stop_line - crew_used_min) / rate)
    } else {
        None
    };

    if effective_deadline_min <= 0.0 {
        return Forecast {
            rate_per_job_min: Some(rate),
            projected_crew_at_deadline: None,
            minutes_to_stop_line: minutes_to_stop,
            verdict: ForecastVerdict::Inconclusive,
            note: "the job has no deadline, so there is no 'before the deadline' to warn about; \
                   only the rate is known"
                .to_string(),
        };
    }

    let projected = rate * effective_deadline_min;
    let verdict = if projected >= stop_line && stop_line > 0.0 {
        ForecastVerdict::Warn
    } else {
        ForecastVerdict::Ok
    };
    let note = match verdict {
        ForecastVerdict::Warn => format!(
            "at {:.3} crew-min per job-min the stop line ({:.0} crew-min) is reached with {:.0} \
             job-min to spare before the deadline, and the projected spend at the deadline is \
             {:.0} crew-min against a bid of {:.0}",
            rate, stop_line, effective_deadline_min - elapsed, projected, effective_bid_min
        ),
        _ => format!(
            "at {:.3} crew-min per job-min the projected spend at the deadline is {:.0} crew-min, \
             under the stop line of {:.0}",
            rate, projected, stop_line
        ),
    };

    Forecast {
        rate_per_job_min: Some(rate),
        projected_crew_at_deadline: Some(projected),
        minutes_to_stop_line: minutes_to_stop,
        verdict,
        note,
    }
}

/// Minutes between two ledger timestamps, when both parse.
pub fn elapsed_minutes(from_ts: &str, to_ts: &str) -> Option<f64> {
    let from = parse_iso(from_ts).ok()?;
    let to = parse_iso(to_ts).ok()?;
    Some((to - from) as f64 / 60.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    const AWARD: &str = "2026-11-02T10:00:00Z";

    #[test]
    fn a_fast_start_warns_before_the_stop_line() {
        // 40 crew-min in 30 job-min against a 100-minute bid, stop at 80:
        // rate 1.33/min, projected 160 at a 120-minute deadline — over the
        // 80-minute stop line, so warn, even though only 40% is spent.
        let f = at_checkpoint(AWARD, "2026-11-02T10:30:00Z", 40.0, 100.0, 0.8, 120.0);
        assert_eq!(f.verdict, ForecastVerdict::Warn);
        assert!((f.rate_per_job_min.unwrap() - 40.0 / 30.0).abs() < 1e-9);
        assert!((f.projected_crew_at_deadline.unwrap() - 160.0).abs() < 1e-9);
        // The stop line (80) is 40 crew-min away at 1.33/min: 30 more minutes.
        assert!((f.minutes_to_stop_line.unwrap() - 30.0).abs() < 1e-9);
    }

    #[test]
    fn a_slow_start_does_not_warn() {
        // 10 crew-min in 30 job-min: rate 0.33, projected 40 at the deadline.
        let f = at_checkpoint(AWARD, "2026-11-02T10:30:00Z", 10.0, 100.0, 0.8, 120.0);
        assert_eq!(f.verdict, ForecastVerdict::Ok);
        assert!(f.note.contains("under the stop line"), "{}", f.note);
    }

    #[test]
    fn no_elapsed_time_is_inconclusive_not_ok() {
        let same_second = at_checkpoint(AWARD, AWARD, 0.0, 100.0, 0.8, 120.0);
        assert_eq!(same_second.verdict, ForecastVerdict::Inconclusive);
        let unreadable = at_checkpoint("not-a-timestamp", "2026-11-02T10:30:00Z", 10.0, 100.0, 0.8, 120.0);
        assert_eq!(unreadable.verdict, ForecastVerdict::Inconclusive);
    }

    #[test]
    fn sub_minute_elapsed_is_noise_and_says_so() {
        // 30 seconds elapsed: an honest rate would be astronomic and say
        // nothing. The forecast keeps quiet instead.
        let f = at_checkpoint(AWARD, "2026-11-02T10:00:30Z", 12.0, 25.0, 0.8, 60.0);
        assert_eq!(f.verdict, ForecastVerdict::Inconclusive);
        assert!(f.note.contains("noise"), "{}", f.note);
    }

    #[test]
    fn a_job_with_no_deadline_reports_only_the_rate() {
        let f = at_checkpoint(AWARD, "2026-11-02T11:00:00Z", 30.0, 100.0, 0.8, 0.0);
        assert_eq!(f.verdict, ForecastVerdict::Inconclusive);
        assert!(f.note.contains("no deadline"), "{}", f.note);
        assert_eq!(f.rate_per_job_min, Some(0.5));
    }

    #[test]
    fn a_projection_that_lands_exactly_on_the_line_warns() {
        // 60 in 60 against bid 100 stop 0.8, deadline 80: projected exactly 80.
        let f = at_checkpoint(AWARD, "2026-11-02T11:00:00Z", 60.0, 100.0, 0.8, 80.0);
        assert_eq!(f.verdict, ForecastVerdict::Warn);
    }
}
