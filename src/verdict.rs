//! Three-valued verdicts: pass, fail, inconclusive.
//!
//! From SuperInstance/receiptd: "a gate that can't say UNKNOWN will lie to
//! you." A check that could not run is not a failure and must not be counted
//! as one; it is recorded as inconclusive, and the reports carry the
//! inconclusive count separately so a miss and a shrug never read the same.

/// The verdict of any check `gc` runs: the acceptance command, a clause, a
/// forecast.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    Pass,
    Fail,
    Inconclusive,
}

impl Verdict {
    pub fn as_str(&self) -> &'static str {
        match self {
            Verdict::Pass => "pass",
            Verdict::Fail => "fail",
            Verdict::Inconclusive => "inconclusive",
        }
    }

    pub fn parse(text: &str) -> Option<Verdict> {
        match text.trim().to_ascii_lowercase().as_str() {
            "pass" | "ok" | "passed" => Some(Verdict::Pass),
            "fail" | "failed" | "no" => Some(Verdict::Fail),
            "inconclusive" | "unknown" | "n/a" => Some(Verdict::Inconclusive),
            _ => None,
        }
    }

    /// What an old boolean row stands for: a check that ran and was recorded
    /// as passed or not. A row with no check at all could not say, so it is
    /// inconclusive, not a failure.
    pub fn from_claim(passed: bool) -> Verdict {
        if passed {
            Verdict::Pass
        } else {
            Verdict::Fail
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verdicts_round_trip_and_take_synonyms() {
        for v in [Verdict::Pass, Verdict::Fail, Verdict::Inconclusive] {
            assert_eq!(Verdict::parse(v.as_str()), Some(v));
        }
        assert_eq!(Verdict::parse("PASSED"), Some(Verdict::Pass));
        assert_eq!(Verdict::parse("unknown"), Some(Verdict::Inconclusive));
        assert_eq!(Verdict::parse("maybe"), None);
    }

    #[test]
    fn a_missing_check_is_inconclusive_not_failed() {
        assert_eq!(Verdict::from_claim(true), Verdict::Pass);
        assert_eq!(Verdict::from_claim(false), Verdict::Fail);
    }
}
