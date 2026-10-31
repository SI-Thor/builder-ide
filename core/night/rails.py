"""The rails: what the night may spend, and when it must stop.

Core-spec v2 §5.5 is the arithmetic of the night bar, and it is deliberately
not one number:

* the units are **lane minutes, hosted cents and wall minutes** — GPU-minutes
  come from the model registry's measured cost table, not from the wall clock,
  so a cheap CPU-lane hour does not eat the GPU bar;
* **admission is before spend** — a job whose ask the rail cannot cover is
  refused, not started and killed;
* **the throttle is graduated** — at 80% the night stops opening new batches
  and drains what it has, at 95% it stops new work entirely, at 100% (or the
  kill switch) it commits and writes the report now. A binary shutdown is how
  you get a morning report that says nothing happened;
* **the load cap is a fourth rail** — the hardware's binding constraint is
  weight-swap thrash, and no spend unit can count loads, so it is enforced at
  batch admission and reported on the night line.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from core.night.models import Rail

__all__ = [
    "BudgetExceeded",
    "LoadBudget",
    "RailBudget",
    "ThrottleLevel",
    "DRAIN_AT",
    "STOP_AT",
    "SPENT_AT",
]

#: §5.5's degradation order.
DRAIN_AT = 0.80
STOP_AT = 0.95
SPENT_AT = 1.00


class BudgetExceeded(Exception):
    """Raised when a spend is admitted against a rail that cannot cover it."""


class ThrottleLevel(str, Enum):
    """Where the night is on its bar."""

    NOMINAL = "nominal"
    DRAINING = "draining"
    STOPPING = "stopping"
    SPENT = "spent"

    @property
    def opens_new_work(self) -> bool:
        """False once the night is draining: it finishes what it has."""
        return self is ThrottleLevel.NOMINAL

    @property
    def admits_anything(self) -> bool:
        """False once the night is stopping: nothing new starts."""
        return self in (ThrottleLevel.NOMINAL, ThrottleLevel.DRAINING)


class RailBudget:
    """A ceiling and what has been spent against it."""

    def __init__(self, ceiling: Rail, spent: Rail | None = None) -> None:
        self.ceiling = ceiling
        self._spent = spent or Rail()

    @property
    def spent(self) -> Rail:
        return self._spent

    @property
    def remaining(self) -> Rail:
        return self.ceiling.subtract(self._spent)

    @property
    def utilisation(self) -> float:
        """The binding axis: the one closest to its own ceiling."""
        ratios: list[float] = []
        for spent, ceiling in (
            (self._spent.gpu_minutes, self.ceiling.gpu_minutes),
            (self._spent.hosted_cents, self.ceiling.hosted_cents),
            (self._spent.wall_minutes, self.ceiling.wall_minutes),
        ):
            if ceiling > 0:
                ratios.append(spent / ceiling)
        if not ratios:
            return 0.0
        return max(ratios)

    def can_admit(self, ask: Rail) -> bool:
        """True when ``ask`` fits in what is left of the rail."""
        return self.remaining.fits(ask)

    def admit(self, ask: Rail) -> None:
        """Record a spend; refuse it if the rail cannot cover it."""
        if not self.can_admit(ask):
            raise BudgetExceeded(
                f"the rail cannot cover {ask.model_dump()}; "
                f"{self.remaining.model_dump()} is left of {self.ceiling.model_dump()}"
            )
        self._spent = self._spent.add(ask)

    def throttle_level(self) -> ThrottleLevel:
        """Where the bar says we are (§5.5's graduated throttling)."""
        utilisation = self.utilisation
        if utilisation >= SPENT_AT:
            return ThrottleLevel.SPENT
        if utilisation >= STOP_AT:
            return ThrottleLevel.STOPPING
        if utilisation >= DRAIN_AT:
            return ThrottleLevel.DRAINING
        return ThrottleLevel.NOMINAL


class LoadBudget:
    """The fourth rail: how many times each model may be loaded tonight.

    Enforced at batch admission — a batch that would exceed a model's load
    budget waits for the drain; it is not started and killed (§5.5).
    """

    def __init__(self, caps: Mapping[str, int] | None = None) -> None:
        self._caps = dict(caps or {})
        self._loads: dict[str, int] = {}

    def cap_for(self, model: str) -> int:
        """The cap for a model: one load per model per night by default."""
        return self._caps.get(model, 1)

    def loads(self, model: str) -> int:
        return self._loads.get(model, 0)

    def can_load(self, model: str) -> bool:
        return self.loads(model) < self.cap_for(model)

    def record_load(self, model: str) -> None:
        if not self.can_load(model):
            raise BudgetExceeded(
                f"model {model!r} has already been loaded {self.loads(model)} time(s) "
                f"against a cap of {self.cap_for(model)}"
            )
        self._loads[model] = self.loads(model) + 1

    def counts(self) -> dict[str, int]:
        """The load count per model, for the night line."""
        return dict(self._loads)
