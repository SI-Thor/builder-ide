"""The closed set of audit event types (§1.8) — the tile group's share.

The set is closed: a new type is a schema change. The tile seat writes four:

- ``tile.authored`` — a tile entered the library, with its author's model
  and prompt hash;
- ``tile.retired`` — a tile left the eligible set, with the reason and the
  plays it had;
- ``tile.played`` — one use of a tile, with the context it was chosen in,
  the outcome and the measure that decided it, the cost, and the chooser
  that picked it;
- ``tile.retrained`` — the night refitted the chooser from the play
  records.

The set itself is :data:`core.records.EVENT_TYPES` — the one copy every
seat shares, so no two packages can drift apart on the one list they all
append to.
"""

from __future__ import annotations

from core.records import EVENT_TYPES

__all__ = ["EVENT_TYPES", "TILE_EVENT_TYPES"]

#: The four types this seat writes. Mirrored in :mod:`core.records`,
#: :mod:`core.night.events` and :mod:`core.recipe.events` so every reader
#: of the log agrees.
TILE_EVENT_TYPES = frozenset(
    {
        "tile.authored",
        "tile.retired",
        "tile.played",
        "tile.retrained",
    }
)
