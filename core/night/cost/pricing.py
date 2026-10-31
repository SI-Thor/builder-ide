"""What a job kind costs, as the two numbers a task carries.

The model's bands (:mod:`core.night.cost.model`) are per **job kind**: this
many GPU-minutes, that many wall-minutes, p50 and p95. A task is not a job
kind — a task is one goal, priced from a kind, and the night's records carry
two numbers about it:

* the **ask** — the p50, what the work usually costs. This is what the slate
  shows the owner and what the admission check holds the night to;
* the **rail** — the p95, the ceiling the task is held to. The seat stops the
  work when it passes it (§5.5), so it is the *bad* case, not the usual one.

Both come from the same band, and the band's own marking travels with them:
``basis`` (measured, derived or estimate) and ``source`` (where the
measurement came from). A number that does not say where it came from is a
number somebody typed.

The one rule this module adds: **the rail is never below the ask.** An owner
who files their own number is held to *their* number, not to the model's —
so an override cannot smuggle work past the ceiling it is measured against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.night.cost.model import CostModel, get_model
from core.night.models import Rail

__all__ = [
    "DEFAULT_KIND",
    "PricedAsk",
    "hold_to",
    "known_kinds",
    "price_job",
]

#: The kind a task is priced as when nobody names one: one owner's goal as the
#: box measures it — a picture, a prop and a verdict (the mini-night's shape).
#: The slate shows which kind a goal was priced as, so this is visible rather
#: than hidden.
DEFAULT_KIND = "prop.goal"


class PricedAsk(BaseModel):
    """One job kind's price, as a task carries it."""

    #: The job kind this price came from.
    kind: str
    #: The ask — the p50, what the work usually costs.
    ask: Rail = Field(default_factory=Rail)
    #: The rail — the p95, the ceiling the task is held to.
    rail: Rail = Field(default_factory=Rail)
    #: ``measured``, ``derived`` or ``estimate`` — the model's own marking.
    basis: str = ""
    #: Where the measurement came from (a document, a ledger, a sweep).
    source: str = ""
    #: Which end of the band the ask was taken from.
    quantile: str = "p50"
    #: How many recorded samples the figure rests on.
    samples: int = 0
    #: How many iterations of the kind one goal costs.
    iterations: int = 1
    #: The energy the whole box draws while the work runs.
    joules: float = 0.0
    #: The kind's own label, for the slate.
    label: str = ""

    @property
    def is_estimate(self) -> bool:
        """True when this price is an estimate rather than a measurement."""
        return self.basis == "estimate"


def known_kinds(model: CostModel | None = None) -> list[str]:
    """Every job kind the model can price — recorded and derived."""
    cost_model = model if model is not None else get_model()
    return cost_model.all_kinds()


def price_job(
    kind: str,
    *,
    count: int = 1,
    scene: str | None = None,
    model: CostModel | None = None,
) -> PricedAsk:
    """Price one job kind, ``count`` times over.

    The ask is the band's p50 and the rail its p95, both scaled by ``count`` —
    three seeds of a prop cost three p50s. The band's basis and source come
    along, because the slate has to be able to say *why* the number is what it
    is.
    """
    cost_model = model if model is not None else get_model()
    band = cost_model.band(kind, scene=scene)
    p50 = band.p50
    p95 = band.p95
    return PricedAsk(
        kind=kind,
        ask=Rail(
            gpu_minutes=p50.gpu_minutes * count,
            hosted_cents=int(p50.hosted_cents * count),
            wall_minutes=p50.wall_minutes * count,
        ),
        rail=Rail(
            gpu_minutes=p95.gpu_minutes * count,
            hosted_cents=int(p95.hosted_cents * count),
            wall_minutes=p95.wall_minutes * count,
        ),
        basis=band.basis,
        source=band.source,
        quantile="p50",
        samples=p50.samples,
        iterations=p50.iterations,
        joules=p50.joules * count,
        label=band.label,
    )


def hold_to(ask: Rail, priced: PricedAsk) -> Rail:
    """The ceiling a task is held to: the kind's p95, never below the ask.

    A model ask is inside its own p95 already. An *override* — a number the
    owner typed in — may be bigger, and then the owner is held to their own
    number rather than to the model's.
    """
    return Rail(
        gpu_minutes=max(priced.rail.gpu_minutes, ask.gpu_minutes),
        hosted_cents=max(priced.rail.hosted_cents, ask.hosted_cents),
        wall_minutes=max(priced.rail.wall_minutes, ask.wall_minutes),
    )
