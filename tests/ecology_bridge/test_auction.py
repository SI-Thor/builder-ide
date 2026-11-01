"""Tests for core.ecology_bridge — the auction/rails semantics mirror.

House style notes: pure unit tests, no fixtures, no core.* imports
(the bridge is deliberately self-contained — core-spec §1.0 stays
intact). Each test names the law it checks.

Since the rebase onto core-judge, the rails speak the night's own units
(gpu_minutes / hosted_cents / wall_minutes — the core ``Rail`` axes),
and the lease mapping (winning bid -> thor-admit acquire) is tested
here too.
"""

from __future__ import annotations

import json
import math

import pytest

from core.ecology_bridge import (
    LEASE_PRIORITY,
    Admission,
    Importance,
    LeaseRequest,
    Rails,
    RailsBank,
    admit_full,
    attention_score,
    auction_order,
    lease_for,
)


def bank(refill: float = 10.0, cap: float = 30.0) -> RailsBank:
    return RailsBank(
        refill_per_period=Rails(gpu_minutes=refill),
        cap=Rails(gpu_minutes=cap),
    )


def bid(bid_id, u=1.0, j=1.0, o=1.0, n=1.0, ev=1.0, imp=Importance.WORLD,
        gpu=1.0, cents=0, wall=0.0):
    return (bid_id, u, j, o, n, ev, imp, Rails(gpu_minutes=gpu, hosted_cents=cents, wall_minutes=wall))


class TestTheVetoLaw:
    def test_zero_attention_never_transacts_even_for_kernel(self):
        b = bank()
        result = admit_full(b, [bid(1, u=0.0, imp=Importance.KERNEL)])
        assert result.vetoed == 1
        assert result.admitted == []

    def test_dead_lineage_cannot_buy_gpu(self):
        # justification 0 is what the WHY ledger prices a dead-rooted
        # purpose at; the auction must agree, without special-casing.
        b = bank()
        result = admit_full(b, [bid(1, j=0.0, imp=Importance.KERNEL)])
        assert result.vetoed == 1
        assert result.admitted == []

    def test_nan_factors_veto_never_poison(self):
        b = bank()
        result = admit_full(b, [bid(1, u=math.nan)])
        assert result.vetoed == 1
        assert result.conservation_ok


class TestTheNightsUnits:
    """The rebase's own question: bids priced in the units core/night/cost
    already uses — gpu-minutes, hosted cents, wall-minutes, the core
    Rail's field-for-field shape and arithmetic."""

    def test_rails_is_the_core_rails_shape(self):
        r = Rails(gpu_minutes=1.5, hosted_cents=3, wall_minutes=2.0)
        assert r.add(Rails(gpu_minutes=0.5)).gpu_minutes == 2.0
        assert r.subtract(Rails(gpu_minutes=0.5)).gpu_minutes == 1.0
        assert Rails(gpu_minutes=1.0).fits(Rails(gpu_minutes=0.5))
        assert not Rails(gpu_minutes=0.5).fits(Rails(gpu_minutes=1.0))
        assert Rails().is_zero
        assert not r.is_zero

    def test_wall_minutes_is_a_rail_axis(self):
        # the mini-night's binding lesson: a cheap GPU job can eat the
        # wall bar (the mesh tail); the auction must refuse on wall too.
        b = RailsBank(refill_per_period=Rails(gpu_minutes=30.0, wall_minutes=10.0),
                      cap=Rails(gpu_minutes=30.0, wall_minutes=10.0))
        b.refill()
        result = admit_full(b, [bid(1, gpu=1.0, wall=6.0), bid(2, gpu=1.0, wall=6.0)])
        # both fit on gpu; only one fits the wall rail
        assert [a.bid_id for a in result.admitted] == [1]
        assert result.skipped_infeasible == 1

    def test_hosted_cents_refuse_cloud_work_the_rail_cannot_pay(self):
        b = RailsBank(refill_per_period=Rails(hosted_cents=10),
                      cap=Rails(hosted_cents=10))
        b.refill()
        result = admit_full(b, [bid(1, gpu=0.0, cents=7), bid(2, gpu=0.0, cents=7)])
        assert [a.bid_id for a in result.admitted] == [1]
        assert result.skipped_infeasible == 1


class TestConservation:
    def test_spends_only_what_the_bank_holds(self):
        b = bank(refill=10.0)
        # One refill; three bids of 4 gpu-min each: two fit, third waits.
        b.refill()
        result = admit_full(b, [bid(1, gpu=4.0), bid(2, gpu=4.0), bid(3, gpu=4.0)])
        assert [a.bid_id for a in result.admitted] == [1, 2]
        assert result.skipped_infeasible == 1
        assert b.balance.gpu_minutes == pytest.approx(2.0)
        assert result.conservation_ok

    def test_spend_raises_instead_of_going_negative(self):
        r = Rails(gpu_minutes=1.0)
        with pytest.raises(ValueError, match="conservation"):
            r.spend(Rails(gpu_minutes=2.0))

    def test_rollover_is_capped(self):
        b = bank(refill=10.0, cap=15.0)
        b.refill()
        b.refill()  # 20 clamped to 15
        assert b.balance.gpu_minutes == pytest.approx(15.0)

    def test_spent_total_accumulates_in_the_nights_units(self):
        b = RailsBank(refill_per_period=Rails(gpu_minutes=10.0, wall_minutes=10.0),
                      cap=Rails(gpu_minutes=10.0, wall_minutes=10.0))
        b.refill()
        admit_full(b, [bid(1, gpu=2.0, wall=1.0), bid(2, gpu=3.0, wall=1.5)])
        assert b.spent_total.gpu_minutes == pytest.approx(5.0)
        assert b.spent_total.wall_minutes == pytest.approx(2.5)


class TestDeterminism:
    def test_strict_order_class_score_id(self):
        # (class, score, id): class desc, score desc, id asc — ties by id.
        ordered = auction_order([(1, 0.9, 7), (3, 0.9, 8), (3, 0.9, 6), (2, 0.5, 9)])
        assert ordered == [(3, 0.9, 6), (3, 0.9, 8), (2, 0.5, 9), (1, 0.9, 7)]

    def test_same_inputs_same_admissions(self):
        bids = [bid(i, u=(i % 5) / 5, gpu=0.7) for i in range(20)]
        r1 = admit_full(bank(), bids)
        r2 = admit_full(bank(), bids)
        assert [a.bid_id for a in r1.admitted] == [a.bid_id for a in r2.admitted]

    def test_world_outranks_scenery_at_lower_score(self):
        b = bank(refill=5.0)
        b.refill()
        result = admit_full(
            b,
            [
                bid(1, u=0.5, imp=Importance.WORLD, gpu=1.0),
                bid(2, u=1.0, imp=Importance.SCENERY, gpu=1.0),
            ],
        )
        assert [a.bid_id for a in result.admitted] == [1, 2]


class TestKernelClass:
    def test_kernel_bypasses_top_k_not_rails(self):
        b = bank(refill=2.0)
        b.refill()
        bids = [bid(i, imp=Importance.KERNEL, gpu=1.0) for i in range(1, 6)]
        result = admit_full(b, bids, top_k=1)
        # Cap would allow 1; kernel bypass admits until the rails say no.
        assert [a.bid_id for a in result.admitted] == [1, 2]
        assert result.skipped_infeasible == 3


class TestScore:
    def test_canonical_product_and_clamping(self):
        assert attention_score(1, 1, 1, 1, 1) == 1.0
        assert attention_score(2.0, 1, 1, 1, 1) == 1.0  # clamped
        assert attention_score(0.5, 0.5, 1, 1, 1) == 0.25


class TestTheLeaseMapping:
    """A winning bid becomes a thor-admit acquire: the auction prices
    value and rails, the daemon prices memory, they compose once per
    admission. The daemon's protocol is its design doc §4."""

    def test_a_winning_bid_maps_onto_a_lease(self):
        admission = Admission(bid_id=7, score=0.8, importance=Importance.WORLD,
                              cost=Rails(gpu_minutes=0.7, wall_minutes=3.3))
        lease = lease_for(admission, label="prop:crate_r1_v2", pgid=1234)
        assert lease.label == "prop:crate_r1_v2"
        assert lease.peak == "auto"  # the daemon's learned p95
        assert lease.priority == LEASE_PRIORITY[Importance.WORLD]

    def test_kernel_maps_to_the_front_of_the_queue(self):
        admission = Admission(bid_id=1, score=1.0, importance=Importance.KERNEL,
                              cost=Rails())
        lease = lease_for(admission, label="journal.flush")
        assert lease.priority == 5  # the daemon: higher goes first

    def test_the_acquire_is_the_daemons_wire_shape(self):
        admission = Admission(bid_id=1, score=1.0, importance=Importance.SCENERY,
                              cost=Rails())
        lease = lease_for(admission, label="tile.thumb", pgid=99)
        wire = json.loads(lease.acquire_json())
        assert wire["op"] == "acquire"
        assert wire["label"] == "tile.thumb"
        assert wire["peak"] == "auto"
        assert wire["priority"] == LEASE_PRIORITY[Importance.SCENERY]
        assert wire["target"] == {"group": {"pgid": 99}}

    def test_a_lease_without_a_process_group_is_still_well_formed(self):
        admission = Admission(bid_id=1, score=1.0, importance=Importance.MAINTENANCE,
                              cost=Rails())
        wire = json.loads(lease_for(admission, label="sweep.stats").acquire_json())
        assert wire["target"] == {"group": {}}
