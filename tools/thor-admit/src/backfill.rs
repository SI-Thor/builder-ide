//! EASY-style backfill: a request may pass the head of the queue only when
//! it cannot delay the head's earliest possible start.
//!
//! The queue keeps its order (§2.2 of the design record): the head must fit
//! before anything behind it is *considered*. That rule held small requests
//! (1.5–12 GiB) behind a 58 GiB `serve.glide` promise for about two hours on
//! 2026-11-01 while ~35 GiB stood above the floor — the head could not fit,
//! and nothing behind it was even looked at. Backfill is the classical
//! answer (EASY, Lifka 1995): reserve the head's earliest possible start,
//! then let a smaller request behind it use the room *now* iff doing so
//! cannot move that reservation.
//!
//! The reservation is computed from what is running. A running lease owes
//! its whole promise until it releases, and when it releases the whole
//! promise comes back to the headroom (the pages it held go back to
//! `MemAvailable` and the shortfall charge goes away with the lease —
//! net `+reserved`, the same arithmetic the admission rule uses). So the
//! head can start at the earliest time by which enough running leases have
//! released for `projected ≥ head_peak + floor`, and a lease whose
//! remaining time cannot be estimated never releases — the conservative
//! word, because a lease with no history could end in ten seconds or in
//! three hours, and a reservation built on a guess that short would let a
//! backfill job delay the head by the whole error.
//!
//! Two guards, both deliberate:
//!
//! * **a candidate with no duration estimate never backfills.** It would
//!   hold its promise for an unknowable time, and "cannot delay the head"
//!   cannot be checked against an unknown. It still runs when it reaches
//!   the head — only the passing is refused.
//! * **a bound on the head's wait** (`--backfill-max-head-wait`). The
//!   no-delay guarantee is only as good as the estimates, and the estimates
//!   come from history that can be wrong by hours (`serve.glide`'s one
//!   clean run lasted 2 874 s; the box's servers run for days). Once the
//!   head has waited the bound, nothing more passes: the queue goes back to
//!   strict order, so whatever room appears next is the head's, and the
//!   delay a wrong estimate can still add is bounded by what was already
//!   admitted inside the bound's window.

/// One running lease as the backfill rule sees it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Running {
    /// What the lease still owes the headroom: its whole promise, because
    /// the rule admits against promises.
    pub reserved: u64,
    /// How much longer the lease is expected to run, in seconds. `None`
    /// means no estimate — no history at all, or a run that has outlasted
    /// its history's number (an estimate demonstrated wrong is not an
    /// estimate) — and such a lease never releases as far as the head's
    /// reservation is concerned.
    pub remaining_s: Option<f64>,
}

/// The earliest the head could start, in seconds from now.
///
/// `None` means "not within any estimate's reach": the running leases that
/// would have to release include at least one with no estimate, so no
/// reservation can be promised. A candidate that fits now can still pass a
/// `None` head (it cannot delay a start that is not in sight), but a
/// candidate without an estimate of its own cannot (see [`may_backfill`]).
pub fn earliest_head_start(
    projected_now: u64,
    head_peak: u64,
    floor: u64,
    running: &[Running],
) -> Option<f64> {
    let need = head_peak.saturating_add(floor);
    if projected_now >= need {
        // The head fits now; the reservation is immediate. (The caller
        // grants the head before any backfill, so this is the branch that
        // ends the passing: there is no head to pass.)
        return Some(0.0);
    }
    let shortfall = need - projected_now;
    // The leases that can be waited out, soonest first. A lease may owe
    // nothing by now (current_rss at its promise); it still counts, because
    // a release of zero freed bytes at its end changes nothing — including
    // it is harmless and keeps the walk honest.
    let mut awaited: Vec<(f64, u64)> = running
        .iter()
        .filter_map(|lease| lease.remaining_s.map(|remaining| (remaining.max(0.0), lease.reserved)))
        .collect();
    awaited.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let mut freed: u64 = 0;
    for (remaining, reserved) in awaited {
        freed = freed.saturating_add(reserved);
        if freed >= shortfall {
            return Some(remaining);
        }
    }
    None
}

/// May a candidate pass the head?
///
/// `candidate_remaining_s` is the candidate's own estimated duration (it
/// has not started, so its remaining time is its whole estimate), and
/// `head_waited_s` is how long the head has already waited. The candidate
/// is charged its whole promise from now until its estimated end, exactly
/// as it will be charged once admitted, and the head's earliest start is
/// recomputed with that lease in the picture: the candidate passes only if
/// the start does not move.
pub fn may_backfill(
    head_peak: u64,
    floor: u64,
    projected_now: u64,
    running: &[Running],
    candidate_peak: u64,
    candidate_remaining_s: Option<f64>,
    head_waited_s: f64,
    max_head_wait_s: f64,
) -> bool {
    if max_head_wait_s > 0.0 && head_waited_s >= max_head_wait_s {
        // The head has waited the bound: nothing more passes, and whatever
        // room appears next is the head's.
        return false;
    }
    let Some(candidate_remaining) = candidate_remaining_s else {
        // No estimate: the candidate would hold its promise for an
        // unknowable time, and the no-delay rule cannot be checked against
        // an unknown.
        return false;
    };
    let without = earliest_head_start(projected_now, head_peak, floor, running);
    let mut with: Vec<Running> = Vec::with_capacity(running.len() + 1);
    with.extend_from_slice(running);
    with.push(Running {
        reserved: candidate_peak,
        remaining_s: Some(candidate_remaining),
    });
    let charged = projected_now.saturating_sub(candidate_peak);
    let after = earliest_head_start(charged, head_peak, floor, &with);
    without == after
}

#[cfg(test)]
mod tests {
    use super::*;

    const GIB: u64 = 1024 * 1024 * 1024;

    fn running(reserved_gib: u64, remaining_s: f64) -> Running {
        Running {
            reserved: reserved_gib * GIB,
            remaining_s: Some(remaining_s),
        }
    }

    fn blocker(reserved_gib: u64) -> Running {
        Running {
            reserved: reserved_gib * GIB,
            remaining_s: None,
        }
    }

    #[test]
    fn a_head_that_fits_now_has_no_reservation_to_pass() {
        // 100 GiB projected, a 40 GiB head, a 25 GiB floor: the head fits,
        // and there is nothing to backfill past.
        assert_eq!(
            earliest_head_start(100 * GIB, 40 * GIB, 25 * GIB, &[]),
            Some(0.0)
        );
    }

    #[test]
    fn the_head_starts_when_enough_leases_release() {
        // Projected 40 GiB, head 58 GiB, floor 25 GiB: the head needs
        // 43 GiB more. One lease owing 30 GiB releases in 600 s, another
        // owing 20 GiB in 1200 s: the second release is what covers the
        // shortfall, so the head starts at 1200 s.
        let running = [running(30, 600.0), running(20, 1200.0)];
        assert_eq!(
            earliest_head_start(40 * GIB, 58 * GIB, 25 * GIB, &running),
            Some(1200.0)
        );
    }

    #[test]
    fn a_lease_with_no_estimate_blocks_the_reservation() {
        // The same numbers, but the 30 GiB lease has no history: however
        // long the 20 GiB lease is given, the head cannot be promised a
        // start.
        let running = [blocker(30), running(20, 1200.0)];
        assert_eq!(earliest_head_start(40 * GIB, 58 * GIB, 25 * GIB, &running), None);
    }

    #[test]
    fn a_short_job_in_the_hole_does_not_delay_the_head() {
        // The 2026-11-01 shape, at unit scale: the head (58 GiB) starts at
        // 1200 s, and a 6 GiB request behind it would run for 300 s. It
        // fits the 35 GiB hole now and is gone 900 s before the head's
        // reservation: classic EASY, it passes.
        let running = [running(30, 600.0), running(20, 1200.0)];
        assert!(may_backfill(
            58 * GIB,
            25 * GIB,
            (40 + 6) * GIB, // the hole after the candidate is charged below
            &running,
            6 * GIB,
            Some(300.0),
            0.0,
            1800.0,
        ));
    }

    #[test]
    fn a_job_that_outstays_the_heads_reservation_cannot_pass() {
        // Projected 46 GiB, head 58 GiB, floor 25 GiB: the head needs
        // 37 GiB more, and the releases cover it exactly at 1200 s (17 at
        // 600, 37 by 1200 — no slack). A 6 GiB candidate behind the head
        // would run 1500 s, past that reservation: while it holds its 6,
        // the 1200 s release no longer covers the shortfall, and the head's
        // start would move to the candidate's own end. Blocked.
        let running = [running(17, 600.0), running(20, 1200.0)];
        assert_eq!(
            earliest_head_start(46 * GIB, 58 * GIB, 25 * GIB, &running),
            Some(1200.0)
        );
        assert!(!may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            6 * GIB,
            Some(1500.0),
            0.0,
            1800.0,
        ));
    }

    #[test]
    fn a_big_candidate_cannot_take_the_room_the_head_was_promised() {
        // The same tight hole, and a 25 GiB candidate that would outlast
        // the head's 1200 s reservation: with it charged, even both
        // releases together are not enough, and the head would wait for
        // the candidate itself to end. Blocked.
        let running = [running(17, 600.0), running(20, 1200.0)];
        assert!(!may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            25 * GIB,
            Some(1500.0),
            0.0,
            1800.0,
        ));
    }

    #[test]
    fn a_candidate_with_no_estimate_never_passes() {
        let running = [running(30, 600.0), running(20, 1200.0)];
        assert!(!may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            6 * GIB,
            None,
            0.0,
            1800.0,
        ));
    }

    #[test]
    fn a_head_that_cannot_be_promised_is_not_delayed_by_a_pass() {
        // One blocker has no estimate, so the head has no reservation in
        // sight. A candidate with an estimate that fits now cannot move a
        // start that does not exist, and it passes: refusing it would empty
        // the hole for a head that no estimate says will ever start.
        let running = [blocker(30), running(20, 1200.0)];
        assert!(may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            6 * GIB,
            Some(300.0),
            0.0,
            1800.0,
        ));
        // …but a candidate without an estimate still cannot: an unknown
        // hold on the hole is exactly the delay the rule refuses.
        assert!(!may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            6 * GIB,
            None,
            0.0,
            1800.0,
        ));
    }

    #[test]
    fn the_bound_stops_the_passing_once_the_head_has_waited_it() {
        let running = [running(30, 600.0), running(20, 1200.0)];
        let args = (58 * GIB, 25 * GIB, 46 * GIB, &running, 6 * GIB, Some(300.0));
        assert!(may_backfill(args.0, args.1, args.2, args.3, args.4, args.5, 1799.0, 1800.0));
        assert!(!may_backfill(args.0, args.1, args.2, args.3, args.4, args.5, 1800.0, 1800.0));
        assert!(!may_backfill(args.0, args.1, args.2, args.3, args.4, args.5, 2500.0, 1800.0));
    }

    #[test]
    fn a_zero_bound_never_stops_the_passing() {
        // `--backfill-max-head-wait 0` is "no bound", not "no backfill":
        // the knob that turns backfill off is `--no-backfill`.
        let running = [running(30, 600.0), running(20, 1200.0)];
        assert!(may_backfill(
            58 * GIB,
            25 * GIB,
            46 * GIB,
            &running,
            6 * GIB,
            Some(300.0),
            9_000.0,
            0.0,
        ));
    }

    #[test]
    fn the_reservation_counts_a_release_of_nothing() {
        // A lease that has reached its promise owes nothing more to the
        // rule, but its release still returns its promise to the headroom
        // when it ends. Here the head needs 20 GiB more and the only lease
        // running has fully grown: the head starts when it ends.
        let running = [running(20, 400.0)];
        assert_eq!(
            earliest_head_start(80 * GIB, 58 * GIB, 25 * GIB, &running),
            Some(400.0)
        );
    }
}
