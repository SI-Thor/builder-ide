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
    /// The GPU's own free pool, when something can see it (`tegrastats`'
    /// `lfb` on this box). `None` means no view, and then there is no GPU
    /// rule to apply — the memory rule is all the daemon has.
    pub gpu_available: Option<u64>,
    /// The least the GPU's own pool must keep after the new lease's device
    /// memory promise: CUDA allocations and pinned host memory are not
    /// reclaimable, so `MemAvailable` can be generous while `cudaMalloc`
    /// fails (Hy4's third failure mode).
    ///
    /// The default is **0** on this box: measured on 2026-11-01, `tegrastats`'
    /// `lfb` is a figure about the allocation pool's *contiguous* free
    /// blocks, not the GPU's headroom — the Thor's memory is unified, so
    /// the GPU's real budget is `MemAvailable`, which the memory rule
    /// already governs — and the old 2 GiB default held 21 requests for
    /// over an hour while ~100 GiB was available (round 10, item a). An
    /// operator who wants the pool rule sets `--gpu-floor` explicitly.
    pub gpu_floor: u64,
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

    /// Does a new lease that promises `gpu_peak` bytes of device memory fit
    /// in the GPU's own pool?
    ///
    /// On this box the pool is unified with the RAM, but it is *not*
    /// uniformly reclaimable: `cudaMalloc`'s blocks and pinned host memory
    /// stay put, and the kernel's `MemAvailable` does not say how fragmented
    /// or how full the non-reclaimable part is. `tegrastats`' `lfb` (the
    /// free blocks of the allocation pool) does. A lease is therefore
    /// admitted only if `lfb − gpu_peak ≥ gpu_floor` — the same shape as the
    /// memory rule, one floor deeper.
    ///
    /// **A lease that promises no device memory (`gpu_peak == 0`) skips the
    /// rule.** The pool is not its budget: a CPU-only lease takes reclaimable
    /// pages, which `MemAvailable` already accounts for, and holding it for a
    /// fragmented pool is what blocked 21 requests for over an hour on
    /// 2026-11-01 while ~100 GiB was available (round 10, item a; §11.8 of
    /// the design record, answered). The risk the other reading carried — a
    /// first run touching CUDA unmeasured, because the GPU promise is
    /// learned, not asked for — stays: a label with no GPU history starts
    /// under the memory rule alone, and if it does take device memory, its
    /// own history makes the next run wait for the pool.
    pub fn gpu_admits(&self, gpu_peak: u64) -> bool {
        if gpu_peak == 0 {
            return true;
        }
        match self.gpu_available {
            Some(free) => free.saturating_sub(gpu_peak) >= self.gpu_floor,
            None => true,
        }
    }

    /// Does a new lease of `peak` memory and `gpu_peak` device memory fit
    /// the box?
    pub fn admits_lease(&self, leases: &[LeaseMemory], peak: u64, gpu_peak: u64) -> bool {
        self.admits(leases, peak) && self.gpu_admits(gpu_peak)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GIB: u64 = 1024 * 1024 * 1024;

    fn admission(available: u64, floor: u64) -> Admission {
        Admission {
            available,
            floor,
            gpu_available: None,
            gpu_floor: 2 * GIB,
        }
    }

    fn gpu_admission(free: u64) -> Admission {
        Admission {
            available: 100 * GIB,
            floor: 25 * GIB,
            gpu_available: Some(free),
            gpu_floor: 2 * GIB,
        }
    }

    #[test]
    fn admits_when_the_plain_rule_holds() {
        let admission = admission(100 * GIB, 25 * GIB);
        assert!(admission.admits(&[], 40 * GIB));
        assert!(!admission.admits(&[], 80 * GIB));
    }

    #[test]
    fn the_floor_is_exactly_the_boundary() {
        let admission = admission(100 * GIB, 25 * GIB);
        assert!(admission.admits(&[], 75 * GIB));
        assert!(!admission.admits(&[], 75 * GIB + 1));
    }

    #[test]
    fn a_lease_that_has_not_grown_yet_still_owes_its_reservation() {
        // The kernel says 100 GiB is available, but a running lease has
        // promised 40 GiB and has used 2 GiB so far. The box really has
        // 60 GiB of room, not 100.
        let admission = admission(100 * GIB, 25 * GIB);
        let running = [LeaseMemory::new(40 * GIB, 2 * GIB)];
        assert_eq!(admission.projected_available(&running), 62 * GIB);
        assert!(admission.admits(&running, 37 * GIB));
        assert!(!admission.admits(&running, 38 * GIB));
    }

    #[test]
    fn a_lease_that_overshot_its_reservation_owes_nothing_more() {
        // It is already using more than it promised; the kernel has counted
        // that, so there is no further shortfall to charge.
        let admission = admission(100 * GIB, 25 * GIB);
        let running = [LeaseMemory::new(10 * GIB, 30 * GIB)];
        assert_eq!(admission.projected_available(&running), 100 * GIB);
    }

    #[test]
    fn several_leases_charge_together() {
        let admission = admission(100 * GIB, 25 * GIB);
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
        let admission = admission(100 * GIB, 25 * GIB);
        assert!(!admission.admits(&[], 200 * GIB));
    }

    #[test]
    fn the_gpu_pool_needs_its_own_floor() {
        // MemAvailable is generous (100 GiB free against a 25 GiB floor),
        // but the GPU's allocation pool is down to 8 GiB and the floor says
        // 2 GiB of it must stay: a lease promising 7 GiB of device memory
        // does not fit, and one promising 6 does.
        let admission = gpu_admission(8 * GIB);
        assert!(admission.admits(&[], 10 * GIB), "the memory rule fits");
        assert!(!admission.gpu_admits(7 * GIB));
        assert!(admission.gpu_admits(6 * GIB));
        assert!(!admission.admits_lease(&[], 10 * GIB, 7 * GIB));
        assert!(admission.admits_lease(&[], 10 * GIB, 6 * GIB));
    }

    #[test]
    fn a_cpu_only_lease_does_not_wait_for_the_gpus_pool() {
        // lfb down to a handful of small blocks and a floor of 2 GiB: a lease
        // that promises no device memory is not waiting for the pool — the
        // pool is not its budget. This is the 2026-11-01 incident inverted:
        // the conservative reading held 21 CPU-side requests for over an
        // hour on a box with ~100 GiB available (round 10, item a).
        let admission = gpu_admission(8 * 1024 * 1024);
        assert!(admission.gpu_admits(0));
        assert!(admission.admits_lease(&[], 1 * GIB, 0));
    }

    #[test]
    fn a_lease_with_a_gpu_promise_still_waits_for_the_pool() {
        // The same fragmented pool, a lease whose label has held device
        // memory before: the pool *is* its budget, and it waits.
        let admission = gpu_admission(8 * 1024 * 1024);
        assert!(!admission.gpu_admits(1 * GIB));
        assert!(!admission.admits_lease(&[], 1 * GIB, 1 * GIB));
    }

    #[test]
    fn without_a_gpu_view_there_is_no_gpu_rule() {
        // Nothing can see the pool (no tegrastats, no driver numbers): the
        // memory rule is all the daemon has, and it says yes.
        let admission = admission(100 * GIB, 25 * GIB);
        assert!(admission.gpu_admits(40 * GIB));
    }
}
