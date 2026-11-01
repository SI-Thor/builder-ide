//! The flow signal: a sign of how the box's work is going, **published by
//! the work, not computed by the daemon**.
//!
//! The three-minds design talks about the box "being in flow" — high
//! confidence, a low rate of change — and about keyframes timed to that
//! window. The admission daemon cannot know any of that: it sees memory,
//! leases and the GPU's rails, not a confidence estimate or a rate of
//! change. What it *can* do, honestly, is record what somebody else
//! publishes: whoever runs the work (the reflex, the mediator, the night
//! runner) writes a small JSON object to `<state-dir>/flow.json`, and the
//! daemon reads it when it changes and folds it into the ledger's hour.
//!
//! ```json
//! {"confidence": 0.87, "rate_of_change": 0.02}
//! ```
//!
//! The daemon also names a sign for the record — `steady` or `faded` — from
//! the published numbers. The thresholds are a **recording convention**, not
//! a trigger: nothing in this daemon acts on them. Whether the box should
//! take a keyframe, call the mediator or register preparation work during
//! the steady window is the mediator's decision, made where the confidence
//! came from. The design record (`docs/design/thor-admit.md` §13) says the
//! same thing in more words.

use serde::{Deserialize, Serialize};

/// The confidence at and above which the published signal reads `steady`.
/// A convention for the record, not a threshold the daemon acts on.
pub const STEADY_CONFIDENCE: f64 = 0.8;
/// The rate of change at and below which (in absolute value) the published
/// signal reads `steady`.
pub const STEADY_RATE: f64 = 0.05;

/// One published flow signal.
#[derive(Clone, Copy, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct FlowSignal {
    /// The publisher's own confidence, 0 to 1, if it says one.
    #[serde(default)]
    pub confidence: Option<f64>,
    /// The publisher's own rate of change, if it says one.
    #[serde(default)]
    pub rate_of_change: Option<f64>,
}

impl FlowSignal {
    /// The sign of the signal: `steady` or `faded`.
    ///
    /// A signal that says neither number has no sign. A signal that the
    /// publisher believes is steady says so by publishing numbers that read
    /// steady — there is no separate "trust me" channel.
    pub fn sign(&self) -> Option<&'static str> {
        let steady = self
            .confidence
            .map(|confidence| confidence >= STEADY_CONFIDENCE)
            .unwrap_or(true)
            && self
                .rate_of_change
                .map(|rate| rate.abs() <= STEADY_RATE)
                .unwrap_or(true);
        match (self.confidence, self.rate_of_change) {
            (None, None) => None,
            _ => Some(if steady { "steady" } else { "faded" }),
        }
    }
}

/// Read a flow.json. A file that is not a JSON object with a number in it
/// is no signal at all — the daemon records absence, never a guess.
pub fn parse(text: &str) -> Option<FlowSignal> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let confidence = value
        .get("confidence")
        .and_then(|value| value.as_f64())
        .filter(|confidence| (0.0..=1.0).contains(confidence));
    let rate = value
        .get("rate_of_change")
        .and_then(|value| value.as_f64());
    if confidence.is_none() && rate.is_none() {
        return None;
    }
    Some(FlowSignal {
        confidence,
        rate_of_change: rate,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_published_signal_is_read_as_it_is() {
        let signal = parse(r#"{"confidence": 0.87, "rate_of_change": 0.02}"#).unwrap();
        assert_eq!(signal.confidence, Some(0.87));
        assert_eq!(signal.rate_of_change, Some(0.02));
        assert_eq!(signal.sign(), Some("steady"));
    }

    #[test]
    fn a_low_confidence_reads_faded() {
        let signal = parse(r#"{"confidence": 0.42, "rate_of_change": 0.01}"#).unwrap();
        assert_eq!(signal.sign(), Some("faded"));
    }

    #[test]
    fn a_fast_charging_signal_reads_faded() {
        let signal = parse(r#"{"confidence": 0.95, "rate_of_change": 0.4}"#).unwrap();
        assert_eq!(signal.sign(), Some("faded"));
    }

    #[test]
    fn a_signal_may_publish_one_number_only() {
        let only_confidence = parse(r#"{"confidence": 0.9}"#).unwrap();
        assert_eq!(only_confidence.sign(), Some("steady"));
        let only_rate = parse(r#"{"rate_of_change": 0.5}"#).unwrap();
        assert_eq!(only_rate.sign(), Some("faded"));
    }

    #[test]
    fn a_file_that_says_nothing_is_no_signal() {
        assert!(parse("{}").is_none());
        assert!(parse("not json at all").is_none());
        assert!(parse(r#"{"confidence": "high"}"#).is_none());
    }

    #[test]
    fn a_confidence_outside_the_scale_is_refused_rather_than_clamped() {
        // A confidence of 7 is a unit error somewhere upstream; recording it
        // as 1.0 would hide it.
        assert!(parse(r#"{"confidence": 7.0}"#).is_none());
    }
}
