"""The admission check: does tonight's plan fit, and what is cut, named.

§5.5 puts admission **before** spend: a job whose ask the rail cannot cover
is refused, not started and killed. This module is that check, run over a
whole plan instead of one job at a time, so the owner can ask the question
*before* the night starts — "does tonight fit?" — and get an answer that
names what would be cut.

The check is the same arithmetic the night runner does when it admits a job,
in the same order, with the same reasons. That is deliberate: a plan that
says it fits and a night that then cuts something are the same fact told
twice, and they must not disagree.

Three outcomes for a planned job:

``admitted``
    the rails cover it, and the model it needs may still be loaded.
``cut``
    a rail cannot cover it — it is re-queued for another night, and the
    reason names the ask and what was left.
``parked``
    the model it needs has already been loaded as many times as the load
    cap allows (the fourth rail). It waits for the model to drain; it is
    not refused.
"""

from __future__ import annotations

from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, Field

from core.night.models import Rail
from core.night.rails import DRAIN_AT, LoadBudget, RailBudget

__all__ = [
    "AdmissionCheck",
    "CutLine",
    "NightPlan",
    "PlannedJob",
    "admission_check",
]

#: Which end of the measured band an ask was taken from.
Quantile = Literal["p50", "p95"]


class PlannedJob(BaseModel):
    """One job on tonight's plan, and what it asks.

    ``ask`` is the cost the plan filed — the model's p50 or p95 for the job
    kind, in the night's own units. It is stored, not recomputed, because the
    ask the owner saw when the job was filed is the ask the night is held to.
    """

    id: str
    intention: str = ""
    ask: Rail = Field(default_factory=Rail)
    #: The model the job needs loaded, if it needs one. Only the job that
    #: opens a batch names it — the rest of the batch runs on the load.
    model: str | None = None
    #: The job kind the ask came from, for the record.
    kind: str = ""

    def describe(self) -> str:
        """The job's name, for a reason line."""
        return self.intention or self.id


class NightPlan(BaseModel):
    """Tonight's plan: the jobs, in the order they will be admitted."""

    jobs: list[PlannedJob] = Field(default_factory=list)

    def asks(self) -> Rail:
        """The whole plan's ask, added up."""
        total = Rail()
        for job in self.jobs:
            total = total.add(job.ask)
        return total


class CutLine(BaseModel):
    """One job the plan cannot afford, and why — in words.

    The morning names these (X C11: "the morning can name what was cut"), so
    the reason is a sentence, not a code.
    """

    id: str
    intention: str = ""
    kind: str = "cut"
    reason: str = ""

    @property
    def is_cut(self) -> bool:
        return self.kind == "cut"


class AdmissionCheck(BaseModel):
    """The answer: does the plan fit, and what falls off the end."""

    fits: bool
    rails: Rail
    projected: Rail
    remaining: Rail
    utilisation: float = 0.0
    admitted: list[str] = Field(default_factory=list)
    cut: list[CutLine] = Field(default_factory=list)
    parked: list[CutLine] = Field(default_factory=list)

    @property
    def cut_names(self) -> list[str]:
        """The names of the jobs that fall off the end."""
        return [line.intention or line.id for line in self.cut]

    @property
    def parked_names(self) -> list[str]:
        """The names of the jobs that wait for a model to drain."""
        return [line.intention or line.id for line in self.parked]


def _binding_axis(spent: Rail, ceiling: Rail) -> tuple[str, float]:
    """The axis closest to its own ceiling, and how close it is."""
    axes = (
        ("gpu_minutes", spent.gpu_minutes, ceiling.gpu_minutes),
        ("hosted_cents", spent.hosted_cents, ceiling.hosted_cents),
        ("wall_minutes", spent.wall_minutes, ceiling.wall_minutes),
    )
    ratios = [(axis, spent_value / ceiling_value) for axis, spent_value, ceiling_value in axes if ceiling_value > 0]
    if not ratios:
        return "gpu_minutes", 0.0
    axis, ratio = max(ratios, key=lambda item: item[1])
    return axis, ratio


def admission_check(
    plan: NightPlan | Sequence[PlannedJob],
    rails: Rail,
    *,
    load_budget: LoadBudget | None = None,
    load_caps: dict[str, int] | None = None,
) -> AdmissionCheck:
    """Check a plan against the night's rails, in the order it will run.

    The plan is admitted job by job: each job that fits is admitted and
    spends its ask; the first job that does not fit is **cut**, and the rest
    are cut too (the night drains what it has and does not open new work —
    §5.5's graduated throttle). A job whose model is at its load cap is
    **parked**, not cut: it waits for the model to drain.
    """
    jobs = list(plan.jobs) if isinstance(plan, NightPlan) else list(plan)
    budget = RailBudget(ceiling=rails)
    loads = load_budget if load_budget is not None else LoadBudget(load_caps)
    admitted: list[str] = []
    cut: list[CutLine] = []
    parked: list[CutLine] = []
    projected = Rail()
    stopped = False

    for job in jobs:
        if stopped:
            cut.append(
                CutLine(
                    id=job.id,
                    intention=job.describe(),
                    kind="cut",
                    reason=(
                        f"{job.describe()} was never reached — the night stopped "
                        "opening new work and drains what it has"
                    ),
                )
            )
            continue
        if job.model and not loads.can_load(job.model):
            parked.append(
                CutLine(
                    id=job.id,
                    intention=job.describe(),
                    kind="parked",
                    reason=(
                        f"waiting for {job.model} to drain — the load cap is "
                        f"{loads.cap_for(job.model)} load(s) a night"
                    ),
                )
            )
            continue
        if not budget.can_admit(job.ask):
            axis, ratio = _binding_axis(budget.spent, rails)
            remaining = getattr(budget.remaining, axis, 0.0)
            asked = getattr(job.ask, axis, 0.0)
            cut.append(
                CutLine(
                    id=job.id,
                    intention=job.describe(),
                    kind="cut",
                    reason=(
                        f"{job.describe()} does not fit the {axis} bar — it asks "
                        f"{asked:.1f} and {remaining:.1f} is left "
                        f"({ratio * 100:.0f}% of the rail spent)"
                    ),
                )
            )
            stopped = True
            continue
        budget.admit(job.ask)
        if job.model:
            loads.record_load(job.model)
        projected = projected.add(job.ask)
        admitted.append(job.id)

    return AdmissionCheck(
        fits=not cut,
        rails=rails,
        projected=projected,
        remaining=budget.remaining,
        utilisation=budget.utilisation,
        admitted=admitted,
        cut=cut,
        parked=parked,
    )


def drain_bar(rails: Rail) -> Rail:
    """The bar at which the night stops opening new work (§5.5's 80 %)."""
    return Rail(
        gpu_minutes=rails.gpu_minutes * DRAIN_AT,
        hosted_cents=int(rails.hosted_cents * DRAIN_AT),
        wall_minutes=rails.wall_minutes * DRAIN_AT,
    )


def plan_from_asks(
    jobs: Iterable[tuple[str, str, Rail]],
    *,
    models: dict[str, str] | None = None,
    kinds: dict[str, str] | None = None,
) -> NightPlan:
    """Build a plan from ``(id, intention, ask)`` triples."""
    models = models or {}
    kinds = kinds or {}
    return NightPlan(
        jobs=[
            PlannedJob(
                id=job_id,
                intention=intention,
                ask=ask,
                model=models.get(job_id),
                kind=kinds.get(job_id, ""),
            )
            for job_id, intention, ask in jobs
        ]
    )
