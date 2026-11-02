//! The drift budget: how far the projector's extrapolation can be from the truth between
//! two corrections, derived from the world's motion parameters rather than observed.
//!
//! The derivation, in one place so the README and the code agree:
//!
//! The projector's pose for an object is the position of its last correction, extrapolated
//! with the velocity of that correction: `p(t0) + v(t0) * (t - t0)`. Write the true
//! velocity over the interval as `v(s)`, and the quantised anchor velocity as `vh`. Then
//!
//! ```text
//! error(t) = p(t) - p(t0) - vh * (t - t0)
//!          = (v(t0) - vh) * (t - t0) + integral of (v(s) - v(t0)) over [t0, t]
//! ```
//!
//! The first term is the velocity quantisation (half a velocity quantum). The second term
//! is the sum, over every velocity change in the interval, of that change times the time it
//! persists. So the bound is: the quantisation, plus the change times the time it lives.
//!
//! * An **orbiter** turns uniformly, so its acceleration is exactly `v^2 / r`, and the
//!   integral is the usual half-acceleration term.
//! * A **walker** holds its velocity for 6 ticks and then changes it by a bounded amount;
//!   a **fast mover** does the same every 3 ticks. Those changes are impulsive, so they
//!   are summed one by one.
//! * An object that **reflects** off the arena wall has a velocity component flipped. No
//!   constant-velocity extrapolation can see that, so an interval containing a reflection
//!   gets its own (much larger) bound.
//!
//! Every number here comes from `world::bounds`, which is where the world's parameters
//! live; nothing here is a measurement.

use crate::world::{bounds, Kind, DT};

/// The largest distance, in metres, that the extrapolation can be from the truth, for an
/// object of this kind over `s` ticks without a correction.
///
/// Three terms: the motion (what the world's parameters allow), the velocity quantisation
/// (half a velocity quantum, carried for the whole interval), and the position quantisation
/// (the anchor is the quantised truth, the comparison is against the quantised truth, and
/// the displacement is rounded to a quantum: three half-quanta).
pub fn drift_bound_m(kind: Kind, s: u32) -> f64 {
    let sf = s as f64;
    // the velocity quantisation: half a velocity quantum, carried for the whole interval
    let quant = bounds::velocity_quantum_error() * sf * DT;
    // the position quantisation: the anchor, the comparison and the rounding
    let pos = 1.5 * crate::world::Q;
    let motion = match kind {
        Kind::Orbiter => {
            // uniform circular motion: the velocity grows by `a` every tick, and the
            // displacement of the k-th tick after the anchor is off by `a * k * dt * dt`
            let a = bounds::orbiter_a_max();
            a * DT * DT * sf * (sf + 1.0) * 0.5
        }
        Kind::Walker => impulse_bound(bounds::walker_dv_max(), bounds::WALKER_EPOCH, sf),
        Kind::Fast => impulse_bound(bounds::fast_dv_max(), bounds::FAST_EPOCH, sf),
    };
    motion + quant + pos
}

/// The bound for an interval that contains a wall reflection: the velocity component flips,
/// so the extrapolation is wrong by up to `2 v` per tick from then on.
pub fn drift_bound_reflect_m(s: u32) -> f64 {
    bounds::reflect_dv_max() * s as f64 * DT
}

/// The bound for a motion that changes by at most `dv`, at most once per `epoch` ticks.
///
/// A change at tick `tau` is already in effect for the displacement of tick `tau` itself,
/// so it persists for `s - (tau - anchor)` ticks of the interval. The worst case is a
/// change one tick after the anchor, and then every `epoch` ticks after that.
fn impulse_bound(dv: f64, epoch: u32, s: f64) -> f64 {
    let mut acc = 0.0;
    let mut k = 0.0f64;
    let e = epoch as f64;
    while k < s {
        acc += dv * (s - k) * DT;
        k += e;
    }
    acc
}

/// The bound as a table over the delivery tiers: the interval, in ticks, and the bound for
/// each kind of object.
pub fn tier_table(intervals: &[u32]) -> Vec<(u32, f64, f64, f64)> {
    intervals
        .iter()
        .map(|&s| (s, drift_bound_m(Kind::Orbiter, s), drift_bound_m(Kind::Walker, s), drift_bound_m(Kind::Fast, s)))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bound_grows_with_the_interval() {
        let mut prev = 0.0;
        for s in 1..=30u32 {
            let b = drift_bound_m(Kind::Orbiter, s);
            assert!(b >= prev, "orbiter bound shrank at {} ticks", s);
            prev = b;
        }
        for s in 1..=30u32 {
            let b = drift_bound_m(Kind::Fast, s);
            assert!(b > 0.0);
        }
    }

    /// A smooth orbit over one tick cannot drift further than half the acceleration times
    /// the square of the tick, plus the quantisation.
    #[test]
    fn the_orbiter_bound_is_the_acceleration_term() {
        let s = 1u32;
        let a = bounds::orbiter_a_max();
        let expect = a * DT * DT * 1.0 * 2.0 * 0.5 + bounds::velocity_quantum_error() * DT + 1.5 * crate::world::Q;
        assert!((drift_bound_m(Kind::Orbiter, s) - expect).abs() < 1e-12);
    }
}
