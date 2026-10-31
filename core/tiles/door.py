"""The door: a tile enters the library only if the vocabulary admits it.

The vocabulary seat has a door of its own — a character's typed call is
validated or refused (`core/vocab/call.py`). This is the same door for a
cloud model's script, and it is deliberately the same door: **the cloud
author is bound by exactly the rules a builder is**.

So a tile that names an unknown word, or carries a parameter outside that
word's schema, is *refused* — not repaired, not clamped, not "best effort".
Free text does not enter the world through the cloud, any more than it
enters through a child.
"""

from __future__ import annotations

import re

from .models import Tile, TileRefusal
from .ports import VocabularyPort

__all__ = ["validate_tile", "PATH_SEGMENT"]

#: The recipe's own path rule (core-spec §1.1): dotted, at most three
#: segments, alphanumeric or underscore.
PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")


def validate_tile(tile: Tile, registry: VocabularyPort) -> None:
    """Raise `TileRefusal` unless the vocabulary admits this tile.

    The reasons are the vocabulary's own reason codes where it has them
    (``out_of_range``, ``not_in_enum``, ``unknown_property`` …), so a
    refusal reads the same whether it came from a builder or from the cloud.
    """
    if not tile.steps:
        raise TileRefusal("no_steps", "a tile has at least one step")

    for step in tile.steps:
        if not _valid_path(step.path):
            raise TileRefusal(
                "path_invalid",
                f"{step.path!r} is not a dotted entry path of at most three segments",
            )

        try:
            registry.require(step.word)
        except KeyError:
            raise TileRefusal(
                "word_unknown", f"{step.word!r} is not a word of the vocabulary"
            ) from None

        try:
            registry.validate_params(step.word, step.params)
        except Exception as exc:  # the vocabulary's own refusal, re-stated
            reason = getattr(exc, "reason", "params_invalid")
            raise TileRefusal(
                str(reason), f"{step.word}: {getattr(exc, 'detail', str(exc))}"
            ) from exc


def _valid_path(path: str) -> bool:
    segments = path.split(".")
    if not 1 <= len(segments) <= 3:
        return False
    return all(PATH_SEGMENT.fullmatch(segment) for segment in segments)
