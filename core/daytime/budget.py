"""The daytime lane's cheap budget.

The daytime is a room that keeps breathing between sessions; it is not a
job. It has to stay cheap for two reasons: the night is the work, and the
ledger is shared.

So the daytime stands down whenever the night lane is busy (that is the
*yield*, and it lives in the log), and it has ceilings of its own for the
rest of the time:

* **ticks** — how far the room may live through in one day. The clock is
  the daytime's own; a room that advanced without bound would be a second
  night, and the night is already spoken for;
* **wall minutes** — how much of the box the daytime may take. The ticks
  are measured, so the ceiling is measured too.

Both counters are folded out of the log, so the budget is state rather than
a number somebody has to remember.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DayBudget", "DEFAULT_MAX_TICKS", "DEFAULT_MAX_MINUTES"]

#: Ticks the room may live through in one day — one day of the clock.
DEFAULT_MAX_TICKS = 24

#: Wall minutes the daytime lane may take in one day. A tick costs
#: microseconds; this is the ceiling that says "and that is enough".
DEFAULT_MAX_MINUTES = 1.0


@dataclass(frozen=True)
class DayBudget:
    """What the daytime lane may spend in one day.

    Frozen: a budget is a decision, and it does not change while the room
    is living.
    """

    max_ticks: int = DEFAULT_MAX_TICKS
    max_minutes: float = DEFAULT_MAX_MINUTES

    def admits(self, ticks: int, minutes: float) -> bool:
        """Is there room in the budget for another tick?

        Admission is before spend (§5.5): a tick the budget cannot cover is
        not started and cut afterwards — it is simply not run, and the log
        says why.
        """
        return ticks < self.max_ticks and minutes < self.max_minutes
