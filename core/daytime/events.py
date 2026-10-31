"""The always-on daytime world (plan item 19, B3).

One room, one clock: the world advances between sessions under the same
recipe, and the ledger is its only state. The clock is a tick count, so the
world is reproducible from ``(recipe, tick)`` — and the daytime lane yields
to the night, because the night is the work.

This module names the closed vocabularies the daytime seat speaks: the four
audit event types it writes, the kinds of small change it records, and the
map from a recipe entry kind to the behaviour that entry has in the room.
"""

from __future__ import annotations

from core.records import EVENT_TYPES

__all__ = [
    "EVENT_TYPES",
    "DAYTIME_EVENT_TYPES",
    "CHANGE_KINDS",
    "ENTRY_BEHAVIOURS",
]

#: The one closed set (§1.8), re-exported from :mod:`core.records` so the
#: daytime seat codes against the same list every other seat does. The
#: groups below say which rows *this* seat writes.

#: The four types this seat writes. §1.8's set is closed; these four are a
#: schema change, mirrored in :mod:`core.records`, :mod:`core.night.events`
#: and :mod:`core.recipe.events` so every reader of the log agrees.
#:
#: - ``day.world.opened`` — the room opens on a recipe version (tick 0)
#: - ``day.tick`` — the clock advances one tick
#: - ``day.change`` — one small change in the room
#: - ``day.yielded`` — the daytime lane stood down for the night
DAYTIME_EVENT_TYPES = frozenset(
    {
        "day.world.opened",
        "day.tick",
        "day.change",
        "day.yielded",
    }
)

#: The kinds of small change a tick can record. A closed set, because the
#: log's payloads are typed, not free text.
CHANGE_KINDS = frozenset({"light", "tidy", "grow"})

#: Which behaviour a recipe entry has in the room. An entry kind that is not
#: here simply sits still — the room does not invent behaviour for it.
ENTRY_BEHAVIOURS: dict[str, str] = {
    "prop_set": "tidy",  # a builder tidies it, every so often
    "terrain": "grow",  # its plants grow by a step, every so often
}
