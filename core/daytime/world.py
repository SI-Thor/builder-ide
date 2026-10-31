"""The world: a pure function of the recipe and the tick count.

Nothing in this module touches the ledger. The daytime seat's promise is
that the same recipe and the same tick reconstruct the same world exactly
(plan item 19), so the derivation has to be arithmetic — a room, a clock,
and a light that moves through the day.

What moves is decided by the recipe, not by taste:

* the **light** moves every tick, up through the day and down again; if the
  recipe has a ``light`` entry, its seed says what hour the room wakes at;
* a **prop_set** gets tidied by a builder every so often;
* **terrain** grows by a step every so often.

How often is the entry's seed: the seed picks a period of two, three or four
ticks and a phase within it, so two entries never fall into lockstep.
"""

from __future__ import annotations

from core.records import Recipe

from .events import ENTRY_BEHAVIOURS
from .models import DayChange, DayObject, DayRoom, DayWorld

__all__ = [
    "LIGHT_CYCLE",
    "advance",
    "apply_change",
    "fires_at",
    "fires_by",
    "light_level",
    "light_offset",
    "light_phase",
    "period_of",
    "phase_of",
    "seed_of",
    "world_at",
]

#: Ticks in one day. The clock counts these.
LIGHT_CYCLE = 24

#: The light's full scale.
LIGHT_SCALE = 100


def seed_of(recipe: Recipe, path: str) -> int:
    """The entry's seed: its own, else the recipe's, else none.

    The recipe carries seeds per entry and per group (``recipe.seeds``); an
    entry's own seed wins. Zero is a real seed here — it just means the
    entry's behaviour falls on the first tick of its period.
    """
    entry = recipe.entries.get(path)
    if entry is not None and entry.seed is not None:
        return entry.seed
    return recipe.seeds.get(path, 0)


def light_offset(recipe: Recipe) -> int:
    """What hour the room's day starts at.

    The recipe's light entry says: its seed is the offset, so a project with
    a lantern line wakes the room earlier. A recipe without one wakes at
    midnight, because that is where a tick count starts.
    """
    for path in sorted(recipe.entries):
        if recipe.entries[path].kind == "light":
            return seed_of(recipe, path) % LIGHT_CYCLE
    return 0


def light_level(recipe: Recipe, tick: int) -> int:
    """The light in the room at ``tick``: a day, as a triangle.

    Integer arithmetic throughout — the light has to be the same number on
    every machine, or the world is not reproducible.
    """
    p = (tick + light_offset(recipe)) % LIGHT_CYCLE
    half = LIGHT_CYCLE // 2
    if p <= half:
        return p * LIGHT_SCALE // half
    return (LIGHT_CYCLE - p) * LIGHT_SCALE // half


def light_phase(recipe: Recipe, tick: int) -> str:
    """Which part of the day the room is in.

    Four phases, because that is all a room needs: night, dawn, day, dusk.
    """
    p = (tick + light_offset(recipe)) % LIGHT_CYCLE
    if p == 0:
        return "night"
    if p < LIGHT_CYCLE // 4:
        return "dawn"
    if p < (LIGHT_CYCLE * 3) // 4:
        return "day"
    return "dusk"


def period_of(seed: int) -> int:
    """How many ticks between two of an entry's behaviours."""
    return 2 + seed % 3


def phase_of(seed: int) -> int:
    """Which tick within that period the behaviour fires on."""
    return seed % period_of(seed)


def fires_at(seed: int, tick: int) -> bool:
    """Does this entry's behaviour fire on this tick?

    Ticks start at one: the world at tick zero is the room as it was opened,
    before anything has happened in it.
    """
    if tick < 1:
        return False
    return tick % period_of(seed) == phase_of(seed)


def fires_by(seed: int, tick: int) -> int:
    """How many times the behaviour fired in the first ``tick`` ticks."""
    period = period_of(seed)
    phase = phase_of(seed)
    if tick < phase:
        return 0
    if phase == 0:
        return tick // period
    return (tick - phase) // period + 1


def _behaviours(recipe: Recipe) -> list[tuple[str, str, int]]:
    """The recipe's entries that do something in the room: path, kind, seed.

    Sorted by path, so the room's order does not depend on how the recipe
    document was built.
    """
    out: list[tuple[str, str, int]] = []
    for path in sorted(recipe.entries):
        kind = recipe.entries[path].kind
        if kind not in ENTRY_BEHAVIOURS:
            continue
        out.append((path, kind, seed_of(recipe, path)))
    return out


def world_at(recipe: Recipe, version_id: str, tick: int) -> DayWorld:
    """The world after ``tick`` ticks.

    A pure function of the recipe, the version and the tick count — this is
    the reproducibility promise, written as arithmetic.
    """
    objects = tuple(
        DayObject(
            path=path,
            kind=kind,
            changes={ENTRY_BEHAVIOURS[kind]: fires_by(seed, tick)},
        )
        for path, kind, seed in _behaviours(recipe)
    )
    return DayWorld(
        recipe_id=recipe.id,
        version_id=version_id,
        tick=tick,
        room=DayRoom(
            light=light_level(recipe, tick),
            phase=light_phase(recipe, tick),
            objects=objects,
        ),
    )


def advance(world: DayWorld) -> DayWorld:
    """The clock advances one tick."""
    return world.model_copy(update={"tick": world.tick + 1})


def apply_change(world: DayWorld, change: DayChange) -> DayWorld:
    """One small change lands on the world."""
    if change.kind == "light":
        room = world.room.model_copy(
            update={
                "light": int(change.after["level"]),
                "phase": str(change.after["phase"]),
            }
        )
        return world.model_copy(update={"room": room})

    objects = []
    for obj in world.room.objects:
        if obj.path != change.target:
            objects.append(obj)
            continue
        changes = dict(obj.changes)
        changes[change.kind] = int(change.after["count"])
        objects.append(obj.model_copy(update={"changes": changes}))
    room = world.room.model_copy(update={"objects": tuple(objects)})
    return world.model_copy(update={"room": room})
