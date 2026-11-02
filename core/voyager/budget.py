"""The budgets — the closing probe budget, and the run's own limits.

Two different things are called a budget here, and they are kept apart.

**The probe budget** is the autopilot harness's rule
(``docs/research/autopilot.md`` §4, "the closing research budget"): probes
are free until the first episode plays, then they are closed until one
does. In our loop a *probe* is any extra look at the world that is not
an execution: re-reading the facts to decide, or looking around before
committing. The rule matters because a loop with an unbounded read
budget is a loop that reads forever:

* before the first execution of a step, up to
  ``max_probes_before_first_execution`` probes are allowed;
* once a skill has executed in this step, the budget is **closed** and
  no further probe is allowed — the loop must judge what happened and
  move on;
* the budget reopens at the next step, and it reopens only because the
  previous step produced an execution.

**The run budget** is the outer limit: steps, wall clock and tokens.
It is the thing that stops an overnight run from being an endless one,
and every field of it is reported with the run's numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ProbeBudget", "RunBudget"]


@dataclass
class ProbeBudget:
    """The closing probe budget of one step.

    ``allow_probe`` is the whole interface: it answers whether the loop
    may look again, and it counts the looks it has allowed.
    """

    max_probes_before_first_execution: int = 2
    probes: int = 0
    executed: bool = False
    closed: bool = False

    def allow_probe(self) -> bool:
        """May the loop read the world again?

        No, once a skill has executed: the budget is closed until the
        next step's execution.
        """
        if self.closed:
            return False
        if self.executed:
            return False
        if self.probes >= self.max_probes_before_first_execution:
            return False
        self.probes += 1
        return True

    def note_execution(self) -> None:
        """An execution happened: the probe budget closes."""
        self.executed = True
        self.closed = True

    def reopen(self) -> None:
        """The next step starts with a fresh budget."""
        self.probes = 0
        self.executed = False
        self.closed = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_probes_before_first_execution": self.max_probes_before_first_execution,
            "probes": self.probes,
            "executed": self.executed,
            "closed": self.closed,
        }


@dataclass
class RunBudget:
    """The outer limits of a run.

    ``max_tokens`` is the one that matters for cost: the brief asks for
    the token cost of a milestone, and a run that cannot see its own
    spend coming is a run that cannot be budgeted.
    """

    max_steps: int = 200
    max_wall_seconds: float = 3600.0
    max_tokens: int = 4_000_000
    steps: int = 0
    tokens: int = 0
    started_at: float | None = None
    _clock: Any = field(default=None, repr=False)

    def start(self, clock) -> None:
        """Start the clock. The clock is injected so a test can drive it."""
        self._clock = clock
        self.started_at = clock()

    def elapsed(self) -> float:
        if self.started_at is None or self._clock is None:
            return 0.0
        return max(0.0, self._clock() - self.started_at)

    def note_step(self, tokens: int = 0) -> None:
        self.steps += 1
        self.tokens += tokens

    def exhausted(self) -> bool:
        """True when the run must stop."""
        if self.steps >= self.max_steps:
            return True
        if self.tokens >= self.max_tokens:
            return True
        if self.started_at is not None and self.elapsed() >= self.max_wall_seconds:
            return True
        return False

    def why(self) -> str:
        """Which limit stopped the run."""
        if self.steps >= self.max_steps:
            return "steps"
        if self.tokens >= self.max_tokens:
            return "tokens"
        if self.started_at is not None and self.elapsed() >= self.max_wall_seconds:
            return "wall_clock"
        return "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_wall_seconds": self.max_wall_seconds,
            "max_tokens": self.max_tokens,
            "steps": self.steps,
            "tokens": self.tokens,
            "elapsed_seconds": round(self.elapsed(), 1),
            "stopped_by": self.why(),
        }
