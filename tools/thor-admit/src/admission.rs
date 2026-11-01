//! The admission rule: admit only if `available - peak >= floor`.
//!
//! The plain form of the rule is not enough once two leases are running: the
//! kernel's `MemAvailable` only knows what a lease is *using right now*, not
//! what it has *promised* to use. A lease that reserved 40 GiB and has used
//! 2 GiB so far looks small to the kernel and huge to the box.
//!
//! So the rule works on the **shortfall**: the memory a lease may still take
//! beyond what it is already using. The box's headroom after every admitted
//! lease reaches its reservation is
//!
//! ```text
//! projected = available - sum(reserved - current)
//! ```
//!
//! and a new lease of `peak` is admitted only if `projected - peak >= floor`.
//! With no other lease that is exactly the plain rule: `available - peak >= floor`.

/// What one admitted lease is holding.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LeaseMemory {
    /// What the lease promised (its `--peak`).
    pub reserved: u64,
    /// What it is using right now.
    pub current: u64,
}

impl LeaseMemory {
    pub fn new(reserved: u64, current: u64) -> Self {
        LeaseMemory { reserved, current }
    }

    /// The memory this lease may still take before it breaks its promise.
    pub fn shortfall(&self) -> u64 {
        self.reserved.saturating_sub(self.current)
    }
}

/// The memory the box has for a new lease, given what is already admitted.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Admission {
    /// `MemAvailable` as the kernel just reported it.
    pub available: u64,
    /// The floor a new lease has to clear.
    pub floor: u64,
}

impl Admission {
    /// The headroom once every admitted lease has reached its reservation.
    pub fn projected_available(&self, leases: &[LeaseMemory]) -> u64 {
        let owed: u64 = leases.iter().map(LeaseMemory::shortfall).sum();
        self.available.saturating_sub(owed)
    }

    /// The headroom left after a new lease of `peak` is admitted.
    pub fn headroom_after(&self, leases: &[LeaseMemory], peak: u64) -> u64 {
        self.projected_available(leases)
            .saturating_sub(peak)
    }

    /// Does a new lease of `peak` fit?
    pub fn admits(&self, leases: &[LeaseMemory], peak: u64) -> bool {
        self.headroom_after(leases, peak) >= self.floor
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GIB: u64 = 1024 * 1024 * 1024;

    #[test]
    fn admits_when_the_plain_rule_holds() {
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        assert!(admission.admits(&[], 40 * GIB));
        assert!(!admission.admits(&[], 80 * GIB));
    }

    #[test]
    fn the_floor_is_exactly_the_boundary() {
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        assert!(admission.admits(&[], 75 * GIB));
        assert!(!admission.admits(&[], 75 * GIB + 1));
    }

    #[test]
    fn a_lease_that_has_not_grown_yet_still_owes_its_reservation() {
        // The kernel says 100 GiB is available, but a running lease has
        // promised 40 GiB and has used 2 GiB so far. The box really has
        // 60 GiB of room, not 100.
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        let running = [LeaseMemory::new(40 * GIB, 2 * GIB)];
        assert_eq!(admission.projected_available(&running), 62 * GIB);
        assert!(admission.admits(&running, 37 * GIB));
        assert!(!admission.admits(&running, 38 * GIB));
    }

    #[test]
    fn a_lease_that_overshot_its_reservation_owes_nothing_more() {
        // It is already using more than it promised; the kernel has counted
        // that, so there is no further shortfall to charge.
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        let running = [LeaseMemory::new(10 * GIB, 30 * GIB)];
        assert_eq!(admission.projected_available(&running), 100 * GIB);
    }

    #[test]
    fn several_leases_charge_together() {
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        let running = [
            LeaseMemory::new(40 * GIB, 0),
            LeaseMemory::new(30 * GIB, 10 * GIB),
        ];
        // The first owes its whole 40 GiB, the second owes 20 GiB more.
        assert_eq!(admission.projected_available(&running), 40 * GIB);
        assert!(admission.admits(&running, 15 * GIB));
        assert!(!admission.admits(&running, 16 * GIB));
    }

    #[test]
    fn a_peak_larger_than_the_box_is_never_admitted() {
        let admission = Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
        };
        assert!(!admission.admits(&[], 200 * GIB));
    }
}
