"""The daytime tick: one room, one clock, and a lane that yields.

The runner is the seat's whole write path. It does four things, in this
order:

1. **stand down** if the night lane is busy — the night is the work, and
   the daytime must not compete with it;
2. **stand down** if the cheap budget cannot cover another tick;
3. **tick** — move the clock, and record the small changes the tick made;
4. **say so** — every stand-down is written to the log, because the edges
   are the story.

There is no state to keep: the world is folded out of the log every time
it is asked for, so a runner that is restarted mid-day picks the room up
where it was left, and two runners on the same log agree.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from core.daytime.budget import DayBudget
from core.daytime.ledger import Ledger
from core.daytime.models import Actor, AuditEvent, DayWorld
from core.daytime.plan import plan_changes
from core.daytime.projection import DayProjection
from core.daytime.world import world_at

__all__ = ["DayRunner", "DAY_ACTOR"]

#: Who the daytime acts as: the core, moving its own room.
DAY_ACTOR = Actor(kind="core", id="daytime")

#: Why the daytime stood down.
REASON_NIGHT_BUSY = "the night is working"
REASON_BUDGET_SPENT = "the daytime budget is spent"


class DayRunner:
    """The daytime tick."""

    def __init__(
        self,
        ledger: Ledger,
        recipe: Any,
        version_id: str,
        *,
        actor: Actor | None = None,
        budget: DayBudget | None = None,
        lane_busy: Callable[[], bool] | None = None,
    ) -> None:
        self.ledger = ledger
        self.recipe = recipe
        self.version_id = version_id
        self.actor = actor or DAY_ACTOR
        self.budget = budget or DayBudget()
        #: A live lane's word, if there is one. Without it the lane is read
        #: out of the log — the night starts and stops in the log, so the
        #: log knows.
        self._lane_busy = lane_busy

    @classmethod
    def resume(
        cls,
        ledger: Ledger,
        recipe: Any,
        version_id: str,
        **kwargs: Any,
    ) -> "DayRunner":
        """A runner that picks the room back up.

        There is nothing to restore: the log is the world's only state, so
        resuming is reading it.
        """
        return cls(ledger, recipe, version_id, **kwargs)

    # -- reads ------------------------------------------------------------

    def projection(self) -> DayProjection:
        """The log, folded."""
        return DayProjection(self.ledger.events())

    def world(self) -> DayWorld | None:
        """The room, as the log says it is."""
        return self.projection().world

    def night_lane_busy(self) -> bool:
        """Is the night working right now?"""
        if self._lane_busy is not None:
            return self._lane_busy()
        return self.projection().night_lane_busy

    # -- writes -----------------------------------------------------------

    def open(self) -> DayWorld:
        """Open the room on the recipe. Idempotent."""
        world = self.world()
        if world is not None:
            return world
        room = world_at(self.recipe, self.version_id, 0).room
        self._append(
            "day.world.opened",
            {
                "recipe_id": self.recipe.id,
                "version_id": self.version_id,
                "room": room.model_dump(mode="json"),
            },
        )
        opened = self.world()
        if opened is None:  # pragma: no cover — the log just took the event
            raise RuntimeError("the room did not open; the log refused the event")
        return opened

    def tick(self) -> DayWorld | None:
        """One tick of the room's clock.

        Returns the new world, or ``None`` when the daytime stood down —
        to the night lane, or to its own budget. The stand-down is in the
        log either way.
        """
        if self.night_lane_busy():
            self._append(
                "day.yielded", {"reason": REASON_NIGHT_BUSY, "lane": "night"}
            )
            return None

        world = self.world()
        if world is None:
            world = self.open()

        projection = self.projection()
        if not self.budget.admits(projection.day_ticks, projection.day_minutes):
            self._append(
                "day.yielded", {"reason": REASON_BUDGET_SPENT, "lane": "daytime"}
            )
            return None

        next_tick = world.tick + 1
        started = time.perf_counter()
        for change in plan_changes(world, self.recipe, next_tick):
            self._append("day.change", {"change": change.model_dump(mode="json")})
        minutes = (time.perf_counter() - started) / 60.0
        # The clock is written last, so it can carry what the tick cost.
        # A tick that died half-written leaves the room a tick behind
        # rather than a light that does not match its clock.
        self._append("day.tick", {"tick": next_tick, "minutes": minutes})
        return self.world()

    def _append(self, type: str, payload: dict[str, Any]) -> AuditEvent:
        # The ledger stamps the event: its clock is the log's clock, and a
        # test that injects one gets deterministic timestamps.
        return self.ledger.append(
            type=type,
            actor=self.actor,
            subject={"entity_kind": "daytime", "entity_id": self.version_id},
            payload=payload,
        )
