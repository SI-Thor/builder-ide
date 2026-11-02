//! Running a check ourselves, instead of taking a report's word for it.
//!
//! From SuperInstance/nursery-v2 ("audit by recomputation — don't trust the
//! record, recompute it") and crab-cell's "does it report honestly?"
//! question at every cycle: the goal line of a job whose acceptance is a
//! command is decided by running that command and reading its exit code —
//! at close by the general contractor, not by the seat saying "done".
//!
//! Nothing here measures time. The result of a check must not depend on the
//! clock, or the same close would write different ledger bytes on a slow
//! day.

use crate::verdict::Verdict;
use std::process::{Command, Stdio};

/// How a check was decided.
#[derive(Clone, Debug)]
pub struct CheckResult {
    pub verdict: Verdict,
    /// "gc" (the command was run), "metric" (a reported value was compared
    /// to the threshold), "human" (a person judged it), or "none".
    pub by: String,
    /// The exit code, when a command ran.
    pub exit_code: Option<i64>,
    /// Why an inconclusive check could not say: timed out, could not spawn,
    /// no value reported.
    pub note: String,
}

impl CheckResult {
    fn gc(exit_code: i64) -> CheckResult {
        CheckResult {
            verdict: if exit_code == 0 {
                Verdict::Pass
            } else {
                Verdict::Fail
            },
            by: "gc".to_string(),
            exit_code: Some(exit_code),
            note: String::new(),
        }
    }

    pub fn cannot(by: &str, note: &str) -> CheckResult {
        CheckResult {
            verdict: Verdict::Inconclusive,
            by: by.to_string(),
            exit_code: None,
            note: note.to_string(),
        }
    }

    /// A human's judgement on a job with no machine-checkable goal line.
    pub fn human(passed: bool) -> CheckResult {
        CheckResult {
            verdict: Verdict::from_claim(passed),
            by: "human".to_string(),
            exit_code: None,
            note: String::new(),
        }
    }

    /// A metric value compared against its threshold.
    pub fn metric(threshold: Option<f64>, value: Option<f64>) -> CheckResult {
        match (threshold, value) {
            (Some(t), Some(v)) => CheckResult {
                verdict: if v >= t { Verdict::Pass } else { Verdict::Fail },
                by: "metric".to_string(),
                exit_code: None,
                note: String::new(),
            },
            (Some(_), None) => Self::cannot("metric", "the metric was not reported"),
            (None, _) => Self::cannot("none", "no threshold was written down for this metric"),
        }
    }
}

/// Run an acceptance command and read its exit code: 0 is pass, anything
/// else is fail, and a command that cannot run or finish in time is
/// inconclusive — the check did not happen, and saying "fail" would be
/// saying more than we know.
///
/// The command runs under `sh -c`, so it may cd, chain and redirect. Its
/// output is discarded: the verdict is the exit code, and the ledger must
/// stay byte-identical for the same command. (A timeout kills the shell;
/// a grandchild it already spawned may outlive it — an untested edge,
/// noted in docs/model.md.)
pub fn run_cmd(cmd: &str, timeout_sec: u64) -> CheckResult {
    let child = Command::new("sh")
        .arg("-c")
        .arg(cmd)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    let mut child = match child {
        Ok(c) => c,
        Err(e) => {
            return CheckResult::cannot("gc", &format!("could not run the command: {}", e))
        }
    };
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_sec);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return match status.code() {
                    Some(code) => CheckResult::gc(code as i64),
                    // Killed by a signal: not zero, so the goal line did not
                    // pass, but the check itself did run to its end.
                    None => CheckResult::gc(-1),
                };
            }
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    let _ = child.kill();
                    return CheckResult::cannot(
                        "gc",
                        &format!("the command did not finish in {}s", timeout_sec),
                    );
                }
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(e) => return CheckResult::cannot("gc", &format!("waiting on the command failed: {}", e)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_exit_zero_is_a_pass_and_an_exit_nonzero_is_a_fail() {
        assert_eq!(run_cmd("true", 10).verdict, Verdict::Pass);
        assert_eq!(run_cmd("exit 3", 10).verdict, Verdict::Fail);
        let pass = run_cmd("true", 10);
        assert_eq!(pass.exit_code, Some(0));
        assert_eq!(pass.by, "gc");
    }

    #[test]
    fn a_command_that_cannot_say_is_inconclusive() {
        let timed_out = run_cmd("sleep 5", 1);
        assert_eq!(timed_out.verdict, Verdict::Inconclusive);
        assert!(timed_out.note.contains("did not finish"), "{}", timed_out.note);

        let missing = run_cmd("definitely-not-a-command-anywhere", 10);
        // sh exists, so this is a fail (exit 127), not inconclusive: the
        // check ran and the goal line did not pass.
        assert_eq!(missing.verdict, Verdict::Fail);
    }

    #[test]
    fn the_command_may_chain_and_cd() {
        assert_eq!(run_cmd("cd /tmp && touch .gc-check-test && test -f .gc-check-test", 10).verdict, Verdict::Pass);
    }

    #[test]
    fn a_metric_needs_both_a_threshold_and_a_value() {
        assert_eq!(CheckResult::metric(Some(1.0), Some(1.0)).verdict, Verdict::Pass);
        assert_eq!(CheckResult::metric(Some(1.0), Some(0.9)).verdict, Verdict::Fail);
        assert_eq!(CheckResult::metric(Some(1.0), None).verdict, Verdict::Inconclusive);
        assert_eq!(CheckResult::metric(None, Some(1.0)).verdict, Verdict::Inconclusive);
    }
}
