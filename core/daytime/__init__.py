"""The always-on daytime world: one room, one clock, and nothing else.

The world advances between sessions under the same recipe, and the ledger is
its only state — there is no file the room lives in. The clock is a tick
count, so the world is reproducible from ``(recipe, tick)``: the same recipe
and the same tick reconstruct the same room, exactly.

Three ideas hold it together:

* **the world is a fold.** The room is what you get when you fold the audit
  log, so it survives a kill -9 and it can be rebuilt at any time;
* **the recipe decides what moves.** The light moves through the day, a
  builder tidies the props, the terrain grows by a step — the recipe's
  entries and seeds say which, and how often;
* **the daytime yields to the night.** The night is the work; the daytime
  stands down when the night lane is busy, and says so in the log.

The public surface:

    from core.daytime import DayRunner, DayWorld, world_at

    world = world_at(recipe, version_id, 12)      # the room, from arithmetic
    runner = DayRunner(ledger, recipe, version_id)
    runner.tick()                                  # one tick, into the log
    runner.world                                   # the room, from the log
"""

from __future__ import annotations

__all__ = [
    "CHANGE_KINDS",
    "DAYTIME_EVENT_TYPES",
    "ENTRY_BEHAVIOURS",
    "DayBudget",
    "DayChange",
    "DayObject",
    "DayProjection",
    "DayRoom",
    "DayRunner",
    "DayWorld",
    "InMemoryLedger",
    "Ledger",
    "PlannedEvent",
    "advance",
    "apply_change",
    "change_event",
    "fires_at",
    "fires_by",
    "light_level",
    "light_phase",
    "plan",
    "plan_changes",
    "world_at",
]

from .budget import DayBudget
from .events import CHANGE_KINDS, DAYTIME_EVENT_TYPES, ENTRY_BEHAVIOURS
from .ledger import InMemoryLedger, Ledger
from .models import DayChange, DayObject, DayRoom, DayWorld, PlannedEvent
from .plan import change_event, plan, plan_changes
from .projection import DayProjection
from .runner import DayRunner
from .world import (
    LIGHT_CYCLE,
    advance,
    apply_change,
    fires_at,
    fires_by,
    light_level,
    light_phase,
    world_at,
)
