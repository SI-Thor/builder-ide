"""Tests for core.ecology_bridge — the auction/rails semantics mirror.

House style notes: pure unit tests, no fixtures, no core.* imports
(the bridge is deliberately self-contained — core-spec §1.0 stays
intact). Each test names the law it checks.
"""

from __future__ import annotations

import math

import pytest

from core.ecology_bridge import (
    Importance,
    Rails,
    RailsBank,
    admit_full,
    attention_score,
    auction_order,
)


def bank(refill: float = 10.0, cap: float = 30.0, joules_factor: float = 25.0) -> RailsBank:
    return RailsBank(
        refill_per_period=Rails(gpu_seconds=refill, joules=refill * joules_factor),
        cap=Rails(gpu_seconds=cap, joules=cap * joules_factor),
    )


def bid(bid_id, u=1.0, j=1.0, o=1.0, n=1.0, ev=1.0, imp=Importance.WORLD, gpu=1.0, joules=25.0, cents=0.0):
    return (bid_id, u, j, o, n, ev, imp, Rails(gpu_seconds=gpu, joules=joules, cents=cents))


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


class TestConservation:
    def test_spends_only_what_the_bank_holds(self):
        b = bank(refill=10.0)
        # One refill; three bids of 4 gpu-s each: two fit, third waits.
        b.refill()
        result = admit_full(b, [bid(1, gpu=4.0), bid(2, gpu=4.0), bid(3, gpu=4.0)])
        assert [a.bid_id for a in result.admitted] == [1, 2]
        assert result.skipped_infeasible == 1
        assert b.balance.gpu_seconds == pytest.approx(2.0)
        assert result.conservation_ok

    def test_spend_raises_instead_of_going_negative(self):
        r = Rails(gpu_seconds=1.0)
        with pytest.raises(ValueError, match="conservation"):
            r.spend(Rails(gpu_seconds=2.0))

    def test_rollover_is_capped(self):
        b = bank(refill=10.0, cap=15.0)
        b.refill()
        b.refill()  # 20 clamped to 15
        assert b.balance.gpu_seconds == pytest.approx(15.0)


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
