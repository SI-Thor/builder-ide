"""The attention auction, mirrored from ecology-thor (attention.rs/rails.rs).

Units note (rebase onto core-judge, 2026-11-01): this mirror originally
spoke ``gpu_seconds/joules/cents`` — the kernel's own rail axes. The
review asked the right question: bids should be priced in the units
``core/night/cost`` already uses, and that is the night's ``Rail`` —
**gpu-minutes, hosted cents and wall-minutes** (``core.records.Rail``,
§1.3/§5.5). This module now speaks exactly those axes, with the same
field names and the same arithmetic (``add``/``subtract``/``fits``/
``is_zero``), so a bridge rails vector and a core ``Rail`` are
duck-type interchangeable without either importing the other. Joules
are not lost: the cost model carries them per job (``CostEstimate.joules``,
the measured ``VIN`` rail) as a *reported* column, not a bar axis; the
kernel's joules rail maps onto that column when the ecology prices work.

Laws carried over verbatim from the kernel:

- THE VETO LAW: a bid scoring <= 0 never transacts — for any importance
  class, including Kernel. Dead lineages (justification 0) cannot buy
  GPU-minutes.
- CONSERVATION: the auction spends only what the bank holds; infeasible
  bids are skipped, never discounted; balances never go negative.
- DETERMINISM: candidates order by (class desc, score desc, id asc) —
  a strict total order; same inputs, same admissions, any platform.
- ADMISSION BEFORE SPEND: the night's own rule (§5.5), which is the
  auction's rule too — the ask is checked before the work starts, and
  the spend is booked at the actual when the work is done.

Float note: like the Rust kernel, money is float here on purpose —
these are admission envelopes, not accounting truth. The ledger keeps
the books.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Sequence, Tuple


class Importance(IntEnum):
    """IBM-WLM-style importance classes. Kernel never gets starved by the
    admission cap; it never escapes the veto law or the rails."""

    MAINTENANCE = 0
    SCENERY = 1
    WORLD = 2
    KERNEL = 3


@dataclass
class Rails:
    """A vector of the night's currencies — field-for-field the core's
    ``Rail`` (gpu-minutes, hosted cents, wall-minutes), with the same
    arithmetic, so the two are interchangeable by keyword construction.

    Not frozen on purpose: banks mutate balances. (Costs should be
    constructed once and treated as immutable by convention — same rule
    as the Rust side, where Rails is Copy.)
    """

    gpu_minutes: float = 0.0
    hosted_cents: int = 0
    wall_minutes: float = 0.0

    # --- the core Rail's own arithmetic, mirrored method-for-method ---

    def add(self, other: "Rails") -> "Rails":
        return Rails(
            gpu_minutes=self.gpu_minutes + other.gpu_minutes,
            hosted_cents=self.hosted_cents + other.hosted_cents,
            wall_minutes=self.wall_minutes + other.wall_minutes,
        )

    def subtract(self, other: "Rails") -> "Rails":
        return Rails(
            gpu_minutes=self.gpu_minutes - other.gpu_minutes,
            hosted_cents=self.hosted_cents - other.hosted_cents,
            wall_minutes=self.wall_minutes - other.wall_minutes,
        )

    def fits(self, ask: "Rails") -> bool:
        """True when ``ask`` fits inside this rails (used as a ceiling) —
        the core Rail's own semantics, §5.5's admission check."""
        return (
            ask.gpu_minutes <= self.gpu_minutes
            and ask.hosted_cents <= self.hosted_cents
            and ask.wall_minutes <= self.wall_minutes
        )

    @property
    def is_zero(self) -> bool:
        return (
            self.gpu_minutes == 0.0
            and self.hosted_cents == 0
            and self.wall_minutes == 0.0
        )

    # --- the bank's spend guard (the kernel's, not the core's) ---

    def afford(self, cost: "Rails") -> bool:
        return self.fits(cost)

    def spend(self, cost: "Rails") -> None:
        if not self.afford(cost):
            raise ValueError(
                "rails conservation violated: cannot spend what the bank lacks"
            )
        self.gpu_minutes -= cost.gpu_minutes
        self.hosted_cents -= cost.hosted_cents
        self.wall_minutes -= cost.wall_minutes


@dataclass
class RailsBank:
    """Refillable, roll-over-able balance — the shape of a night's rail:
    unbounded rollover lets ancient savings starve fresh work, so the
    balance is clamped to ``cap`` after every refill."""

    refill_per_period: Rails
    cap: Rails
    balance: Rails = field(default_factory=Rails)
    spent_total: Rails = field(default_factory=Rails)

    def refill(self) -> None:
        for attr in ("gpu_minutes", "hosted_cents", "wall_minutes"):
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
    expected_value, importance, cost)`` — cost in the night's units.

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
        bank.spent_total = bank.spent_total.add(cost)
        result.admitted.append(Admission(bid_id, score, importance, cost))
        admitted_n += 1

    b = bank.balance
    result.conservation_ok = (
        b.gpu_minutes >= 0.0 and b.hosted_cents >= 0 and b.wall_minutes >= 0.0
    )
    return result


# ---------------------------------------------------------------------------
# The lease mapping: a winning bid becomes a thor-admit lease.
#
# The box's memory admission daemon (``tools/thor-admit`` on the
# ``thor-admit`` branch) owns the memory axis: a heavy thing may not start
# until the box has room for it, leases are kernel-held (a dead client
# cannot leak one), and learned peaks (the p95 of a label's history) feed
# the cost model's memory column. The auction owns the value/cost axes.
# They compose exactly once per admission: **the auction decides whether
# work is worth its GPU-minutes; thor-admit decides whether the box can
# hold it while it runs.** Neither subsumes the other.
# ---------------------------------------------------------------------------

#: Importance class -> thor-admit queue priority (higher goes first).
LEASE_PRIORITY = {
    Importance.MAINTENANCE: 0,
    Importance.SCENERY: 1,
    Importance.WORLD: 2,
    Importance.KERNEL: 5,
}


@dataclass(frozen=True)
class LeaseRequest:
    """One admitted bid, as the thor-admit ``acquire`` the runner sends
    before spawning the work (the daemon's protocol §4). ``peak`` is
    ``"auto"`` — the daemon's learned p95 for the label — which it
    refuses for a label with no history; on refusal the caller falls
    back to the cost model's memory column (the same p50/p95 bands,
    measured by the daemon itself), never to a guess."""

    label: str
    peak: object = "auto"  # "auto" or an explicit byte count
    priority: int = 0
    pgid: Optional[int] = None

    def acquire_json(self) -> str:
        """The wire request, JSON, as the daemon's protocol spells it."""
        import json

        target = {"group": {"pgid": self.pgid}} if self.pgid is not None else {"group": {}}
        return json.dumps(
            {
                "op": "acquire",
                "label": self.label,
                "peak": self.peak,
                "priority": self.priority,
                "target": target,
            }
        )


def lease_for(admission: Admission, label: str, pgid: Optional[int] = None) -> LeaseRequest:
    """Map a winning bid onto its thor-admit lease.

    The mapping is deliberately thin: the auction's decision (worth it,
    affordable on the rails) is *before* the lease, and the lease's
    decision (does the box have room) is *before* the process. A lease
    refused by thor-admit does not refund the auction's rails until the
    work is actually abandoned — the runner books the spend at the
    actual, and an unspawned job books zero.
    """
    return LeaseRequest(
        label=label,
        peak="auto",
        priority=LEASE_PRIORITY[admission.importance],
        pgid=pgid,
    )


#: The lease lifecycle, as the daemon reports it, mapped onto the WHY
#: ledger's states (the ecology's side of the composition — what the
#: kernel journals when the daemon acts):
LEASE_EVENTS_TO_WHY = {
    "lease.granted": "run_under (the purpose is served; its chain attests)",
    "watchdog.stopped": "harvest to UNKNOWN (questionable, not gone; "
    "SIGSTOP loses nothing)",
    "watchdog.killed": "dead, reason recorded (the grace period ran out)",
    "lease.client_gone": "harvest to UNKNOWN (the client cannot speak; "
    "the kernel's flock can)",
    "lease.released": "service complete; the peak lands in the history",
}
