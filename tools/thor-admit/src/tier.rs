//! The tiers the box's work falls into.
//!
//! The brief puts the work in four tiers, most urgent first:
//!
//! | Tier | What it is |
//! |---|---|
//! | **live** | nights, previews, first-mile requests |
//! | **preparation** | pre-generating likely-needed assets, refreshing keyframes |
//! | **practice** | retraining choosers, recalibrating confidence, FP4-aware training, replaying proposed changes against recorded inputs |
//! | **study** | the Infinigen sweep, hardware experiment batches, parity and benchmark suites |
//!
//! Two things are true of a tier, and both are used by the daemon:
//!
//! * **It is an accounting band.** Every second of work is booked to the tier
//!   it belongs to, so the ledger can say where the box's time went.
//! * **Only `live` may pre-empt.** A live lease is work somebody is waiting
//!   for; the other three are work the box does when it has room, and they
//!   give way when live work arrives.

use serde::{Deserialize, Serialize};

/// A tier of work. The order of the variants is the order of urgency:
/// `Live` is the most urgent, `Study` the least.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Tier {
    /// Nights, previews, first-mile requests. Work somebody is waiting for.
    Live,
    /// Pre-generating likely-needed assets, refreshing keyframes.
    Preparation,
    /// Retraining choosers, recalibrating confidence, replaying proposals.
    Practice,
    /// The Infinigen sweep, hardware experiment batches, parity suites.
    Study,
}

impl Tier {
    /// Every tier, most urgent first.
    pub fn all() -> [Tier; 4] {
        [
            Tier::Live,
            Tier::Preparation,
            Tier::Practice,
            Tier::Study,
        ]
    }

    /// The tier's name, as it is written in the records.
    pub fn as_str(&self) -> &'static str {
        match self {
            Tier::Live => "live",
            Tier::Preparation => "preparation",
            Tier::Practice => "practice",
            Tier::Study => "study",
        }
    }

    /// The tier's rank: 0 is the most urgent.
    pub fn rank(&self) -> usize {
        match self {
            Tier::Live => 0,
            Tier::Preparation => 1,
            Tier::Practice => 2,
            Tier::Study => 3,
        }
    }

    /// Read a tier's name.
    pub fn parse(text: &str) -> Option<Tier> {
        match text.trim().to_ascii_lowercase().as_str() {
            "live" => Some(Tier::Live),
            "preparation" | "prep" => Some(Tier::Preparation),
            "practice" => Some(Tier::Practice),
            "study" => Some(Tier::Study),
            _ => None,
        }
    }

    /// Is this tier allowed to pre-empt other work?
    ///
    /// Only live work is: a live lease is somebody waiting for an answer, and
    /// the other tiers are the work the box does with the time it has left.
    pub fn is_live(&self) -> bool {
        matches!(self, Tier::Live)
    }
}

impl Default for Tier {
    /// A lease that does not say what tier it is is **live**.
    ///
    /// That is the safe default: an unlabelled request is somebody's work
    /// happening now, and it should not wait behind the box's background
    /// queue. It also keeps every client that predates the tiers working
    /// unchanged.
    fn default() -> Tier {
        Tier::Live
    }
}

impl std::fmt::Display for Tier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_order_is_urgency() {
        let mut tiers = Tier::all();
        tiers.sort();
        assert_eq!(
            tiers,
            [
                Tier::Live,
                Tier::Preparation,
                Tier::Practice,
                Tier::Study
            ]
        );
        assert!(Tier::Live < Tier::Study);
    }

    #[test]
    fn a_tier_reads_its_own_name() {
        for tier in Tier::all() {
            assert_eq!(Tier::parse(tier.as_str()), Some(tier));
        }
        assert_eq!(Tier::parse("LIVE"), Some(Tier::Live));
        assert_eq!(Tier::parse(" prep "), Some(Tier::Preparation));
        assert_eq!(Tier::parse("nightly"), None);
        assert_eq!(Tier::parse(""), None);
    }

    #[test]
    fn only_live_work_may_preempt() {
        assert!(Tier::Live.is_live());
        assert!(!Tier::Preparation.is_live());
        assert!(!Tier::Practice.is_live());
        assert!(!Tier::Study.is_live());
    }

    #[test]
    fn an_unlabelled_lease_is_live() {
        assert_eq!(Tier::default(), Tier::Live);
    }

    #[test]
    fn a_tier_survives_the_json_round_trip() {
        for tier in Tier::all() {
            let text = serde_json::to_string(&tier).unwrap();
            assert_eq!(text, format!("\"{}\"", tier.as_str()));
            let back: Tier = serde_json::from_str(&text).unwrap();
            assert_eq!(back, tier);
        }
    }

    #[test]
    fn a_lease_without_a_tier_still_reads_as_live() {
        // The shape an older client writes.
        let text = r#"{"op":"acquire","label":"seat","peak":1024,"priority":0,
                       "target":{"process":{"pid":42}}}"#;
        let request: crate::protocol::Request = serde_json::from_str(text).unwrap();
        match request {
            crate::protocol::Request::Acquire { tier, .. } => assert_eq!(tier, Tier::Live),
            other => panic!("wrong request: {other:?}"),
        }
    }
}
