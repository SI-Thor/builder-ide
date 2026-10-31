"""The attention auction, mirrored from ecology-thor (attention.rs/rails.rs).

Laws carried over verbatim:

- THE VETO LAW: a bid scoring <= 0 never transacts — for any importance
  class, including Kernel. Dead lineages (justification 0) cannot buy
  GPU-seconds.
- CONSERVATION: the auction spends only what the bank holds; infeasible
  bids are skipped, never discounted; balances never go negative.
- DETERMINISM: candidates order by (class desc, score desc, id asc) —
  a strict total order; same inputs, same admissions, any platform.
- RAILS: the currencies are the box's real ones (gpu_seconds, joules,
  cents) — builder-ide's cost model units.

Float note: like the Rust kernel, money is float here on purpose —
these are admission envelopes, not accounting truth. The ledger keeps
the books.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Sequence, Tuple


class Importance(IntEnum):
    """IBM-WLM-style importance classes. Kernel never gets starved by the
    admission cap; it never escapes the veto law or the rails."""

    MAINTENANCE = 0
    SCENERY = 1
    WORLD = 2
    KERNEL = 3


@dataclass
class Rails:
    """A vector of the box's currencies (cost, budget, or spend).

    Not frozen on purpose: banks mutate balances. (Costs should be
    constructed once and treated as immutable by convention — same rule
    as the Rust side, where Rails is Copy.)
    """

    gpu_seconds: float = 0.0
    joules: float = 0.0
    cents: float = 0.0

    def afford(self, cost: "Rails") -> bool:
        return (
            self.gpu_seconds >= cost.gpu_seconds
            and self.joules >= cost.joules
            and self.cents >= cost.cents
        )

    def spend(self, cost: "Rails") -> None:
        if not self.afford(cost):
            raise ValueError("rails conservation violated: cannot spend what the bank lacks")
        self.gpu_seconds -= cost.gpu_seconds
        self.joules -= cost.joules
        self.cents -= cost.cents


@dataclass
class RailsBank:
    """Refillable, roll-over-able balance — the shape of builder-ide's
    rails: unbounded rollover lets ancient savings starve fresh work, so
    the balance is clamped to `cap` after every refill."""

    refill_per_period: Rails
    cap: Rails
    balance: Rails = field(default_factory=Rails)
    spent_total: Rails = field(default_factory=Rails)

    def refill(self) -> None:
        for attr in ("gpu_seconds", "joules", "cents"):
            refilled = getattr(self.balance, attr) + getattr(self.refill_per_period, attr)
            setattr(self.balance, attr, min(refilled, getattr(self.cap, attr)))


def _clamp01(x: float) -> float:
    # NaN vetoes (never poisons) — same construction as the kernel.
    if math.isnan(x) or x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def attention_score(
    urgency: float,
    justification: float,
    opportunity: float,
    novelty: float,
    expected_value: float,
) -> float:
    """The law: urgency * justification * opportunity * novelty * ev,
    canonical multiply order, operands clamped to [0, 1]."""
    return (
        _clamp01(urgency)
        * _clamp01(justification)
        * _clamp01(opportunity)
        * _clamp01(novelty)
        * _clamp01(expected_value)
    )


def auction_order(candidates: Sequence[Tuple[int, float, int]]) -> List[Tuple[int, float, int]]:
    """Strict total order: class desc, score desc, id asc. Deterministic
    across platforms (no dict iteration, no float ties — ids break them)."""
    return sorted(candidates, key=lambda c: (-c[0], -c[1], c[2]))


@dataclass(frozen=True)
class Admission:
    bid_id: int
    score: float
    importance: Importance
    cost: Rails


@dataclass
class AuctionResult:
    admitted: List[Admission] = field(default_factory=list)
    vetoed: int = 0
    skipped_infeasible: int = 0
    conservation_ok: bool = True


def admit_full(
    bank: RailsBank,
    bids: Sequence[Tuple[int, float, float, float, float, float, Importance, Rails]],
    top_k: int = 32,
) -> AuctionResult:
    """One auction. Each bid is
    ``(bid_id, urgency, justification, opportunity, novelty,
    expected_value, importance, cost)``.

    Order of operations (same as the kernel's ``run_auction``):

      1. score every candidate — the veto law applied here, once, in
         one place;
      2. strict order: class desc, score desc, id asc;
      3. greedy admit while (non-Kernel admits < ``top_k``) and the
         bank can pay; Kernel bypasses the cap, never the rails;
      4. conservation check: balances never negative.
    """
    result = AuctionResult()
    candidates: List[Tuple[int, float, int]] = []
    by_id: Dict[int, Tuple[float, Importance, Rails]] = {}

    for bid_id, u, j, o, n, ev, importance, cost in bids:
        score = attention_score(u, j, o, n, ev)
        by_id[bid_id] = (score, importance, cost)
        if score <= 0.0:
            result.vetoed += 1  # THE VETO LAW
            continue
        candidates.append((int(importance), score, bid_id))

    admitted_n = 0
    for klass, score, bid_id in auction_order(candidates):
        if admitted_n >= top_k and klass != int(Importance.KERNEL):
            break
        _s, importance, cost = by_id[bid_id]
        if not bank.balance.afford(cost):
            result.skipped_infeasible += 1
            continue
        bank.balance.spend(cost)
        bank.spent_total.gpu_seconds += cost.gpu_seconds
        bank.spent_total.joules += cost.joules
        bank.spent_total.cents += cost.cents
        result.admitted.append(Admission(bid_id, score, importance, cost))
        admitted_n += 1

    b = bank.balance
    result.conservation_ok = b.gpu_seconds >= 0.0 and b.joules >= 0.0 and b.cents >= 0.0
    return result
