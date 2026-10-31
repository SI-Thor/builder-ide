"""The tile seat — the system that gets better (Casey's B2).

The cloud writes the options; the Thor learns which ones work, and when.

The design is `docs/design/tiles.md`; the citations in each module's
docstring point back to it.
"""

from __future__ import annotations

from .door import validate_tile
from .events import TILE_EVENT_TYPES
from .models import (
    FeedbackPacket,
    Outcome,
    PlayCost,
    PlayRecord,
    Precondition,
    Tile,
    TileAuthor,
    TileRefusal,
    TileStep,
    build_play_record,
    build_tile,
)
from .ports import LedgerPort, VocabularyPort

__all__ = [
    "FeedbackPacket",
    "LedgerPort",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "Precondition",
    "TILE_EVENT_TYPES",
    "Tile",
    "TileAuthor",
    "TileRefusal",
    "TileStep",
    "VocabularyPort",
    "build_play_record",
    "build_tile",
    "validate_tile",
]
