"""The two lines the owner reads before the night starts.

The owner should never have to ask what tonight will cost or whether it
fits — those are two lines, written before the night, and they are the same
two lines the morning measures against.

**Line one — the ask.** What tonight will cost, in the owner's units: the
GPU bar, the wall bar, the hosted cents, and the energy the rails will
draw. The numbers come from the measured cost model, so the ask is not a
guess dressed as a number.

**Line two — the verdict.** Whether it fits, and what falls off the end if
it does not, *named*. A plan that does not fit is not a failure to be
discovered at 3 a.m.; it is a sentence the owner read this evening.

Both lines are written into the log when the night starts, so the morning
can put them beside what actually happened.
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from core.night.cost.admission import AdmissionCheck, NightPlan, PlannedJob, admission_check
from core.night.cost.model import CostModel, get_model
from core.night.models import Rail

__all__ = ["OwnerEstimate", "owner_estimate"]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class OwnerEstimate(BaseModel):
    """The two lines, and the numbers behind them."""

    line_one: str
    line_two: str
    ask: Rail = Field(default_factory=Rail)
    rails: Rail = Field(default_factory=Rail)
    fits: bool = True
    joules: float | None = None
    cut: list[str] = Field(default_factory=list)
    parked: list[str] = Field(default_factory=list)

    def lines(self) -> list[str]:
        """The two lines, as a list."""
        return [self.line_one, self.line_two]

    def as_text(self) -> str:
        """The two lines, as one block of text."""
        return "\n".join(self.lines())


def _joules_for(ask: Rail, model: CostModel) -> float | None:
    """The energy the plan's wall time will draw, above the box's idle floor."""
    marginal = model.data.rails.marginal_vin_w * ask.wall_minutes * 60.0 / 1000.0
    return marginal if marginal > 0 else None


def owner_estimate(
    plan: NightPlan | Sequence[PlannedJob],
    rails: Rail,
    *,
    model: CostModel | None = None,
    check: AdmissionCheck | None = None,
) -> OwnerEstimate:
    """Write the owner's two lines for tonight's plan.

    The plan's asks are spent as written; the check says whether they fit.
    """
    cost_model = model if model is not None else get_model()
    jobs = list(plan.jobs) if isinstance(plan, NightPlan) else list(plan)
    ask = Rail()
    for job in jobs:
        ask = ask.add(job.ask)
    verdict = check if check is not None else admission_check(jobs, rails)
    joules = _joules_for(ask, cost_model)

    goal_count = len(jobs)
    line_one = (
        f"Tonight: {_plural(goal_count, 'goal')} — "
        f"{ask.gpu_minutes / 60:.1f} GPU-h of the {rails.gpu_minutes / 60:.1f} h bar · "
        f"{ask.wall_minutes / 60:.1f} wall-h of the {rails.wall_minutes / 60:.1f} h · "
        f"${ask.hosted_cents / 100:.2f} hosted (local)"
    )
    if joules is not None:
        line_one += f" · {joules / 1000:.1f} kJ on the rails"

    if verdict.fits:
        spare_gpu = verdict.remaining.gpu_minutes / 60
        line_two = (
            f"It fits, with {spare_gpu:.1f} GPU-h to spare. Nothing is cut."
        )
    else:
        first = verdict.cut[0]
        line_two = f"It does not fit: {first.reason}."
    if verdict.parked:
        line_two += (
            f" {_plural(len(verdict.parked), 'goal')} parked waiting for a model to drain."
        )

    return OwnerEstimate(
        line_one=line_one,
        line_two=line_two,
        ask=ask,
        rails=rails,
        fits=verdict.fits,
        joules=joules,
        cut=verdict.cut_names,
        parked=verdict.parked_names,
    )
