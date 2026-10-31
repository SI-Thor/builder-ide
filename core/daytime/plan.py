"""The plan for a tick: the small changes it makes, in order.

The plan is the deterministic heart of the daytime seat. The runner turns it
into audit events and appends them; the projection folds them back. Both
read the same plan, so the world that comes out of the log is the world the
arithmetic says it is.

The plan carries no clock of its own — a tick's cost is measured when it is
run, not before — so the planned minutes are zero and the runner fills them
in with what the box actually did.

Within a tick the order is **the changes, then the clock**. The clock event
carries what the tick cost, and it cannot know that until the changes have
been written; writing it last also means a tick that died half-written
leaves the room a tick behind rather than a light that does not match its
clock.
"""

from __future__ import annotations

from core.records import Recipe

from .events import ENTRY_BEHAVIOURS
from .models import DayChange, DayWorld, PlannedEvent
from .world import advance, apply_change, fires_at, light_level, light_phase, seed_of, world_at

__all__ = ["change_event", "plan", "plan_changes"]


def plan_changes(world: DayWorld, recipe: Recipe, tick: int) -> list[DayChange]:
    """The changes tick ``tick`` makes, given the world as it was.

    The light moves every tick. The things in the room move on their own
    schedules, which their seeds set.
    """
    changes = [
        DayChange(
            kind="light",
            target="room",
            before={"level": world.room.light, "phase": world.room.phase},
            after={
                "level": light_level(recipe, tick),
                "phase": light_phase(recipe, tick),
            },
        )
    ]
    for obj in world.room.objects:
        behaviour = ENTRY_BEHAVIOURS[obj.kind]
        if not fires_at(seed_of(recipe, obj.path), tick):
            continue
        before = obj.changes.get(behaviour, 0)
        changes.append(
            DayChange(
                kind=behaviour,
                target=obj.path,
                before={"count": before},
                after={"count": before + 1},
            )
        )
    return changes


def change_event(change: DayChange) -> PlannedEvent:
    """The event one small change is written as."""
    return PlannedEvent(
        type="day.change", payload={"change": change.model_dump(mode="json")}
    )


def plan(recipe: Recipe, version_id: str, ticks: int) -> list[PlannedEvent]:
    """The events ``ticks`` ticks call for, starting from the room at zero.

    The first event opens the room on the recipe; then each tick
    contributes its changes and, last, the clock.
    """
    if ticks <= 0:
        return []

    world = world_at(recipe, version_id, 0)
    events: list[PlannedEvent] = [
        PlannedEvent(
            type="day.world.opened",
            payload={
                "recipe_id": recipe.id,
                "version_id": version_id,
                "room": world.room.model_dump(mode="json"),
            },
        )
    ]
    for tick in range(1, ticks + 1):
        for change in plan_changes(world, recipe, tick):
            events.append(change_event(change))
            world = apply_change(world, change)
        events.append(
            PlannedEvent(type="day.tick", payload={"tick": tick, "minutes": 0.0})
        )
        world = advance(world)
    return events
