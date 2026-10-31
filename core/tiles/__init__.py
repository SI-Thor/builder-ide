"""The tile seat — the system that gets better (Casey's B2).

The cloud writes the options; the Thor learns which ones work, and when.

    from core.tiles import TileLibrary, ContextualBandit, record_play, retrain

    library = TileLibrary(registry=registry, ledger=ledger)   # the options
    chooser = ContextualBandit(feature_keys=("phase",))        # the learner
    choice = chooser.choose(context, library.eligible(context))
    record = record_play(
        ledger=ledger, library=library, tile=library.require(choice.tile_id),
        context=context, outcome=Outcome(result="win", measure="critic"),
        chooser=chooser.name, chooser_version=chooser.version,
    )
    chooser.update(record)
    report = retrain(events=ledger.events(), library=library, chooser=chooser)

The design is `docs/design/tiles.md`; the citations in each module's
docstring point back to it.
"""

from __future__ import annotations

from .author import AuthorRequest, CloudAuthor, ScriptedAuthor, TileAuthorProtocol
from .chooser import Choice, ContextualBandit, TileChooser
from .door import validate_tile
from .events import TILE_EVENT_TYPES
from .library import TileLibrary, fold_library
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
from .plays import fold_plays, record_play
from .ports import LedgerPort, VocabularyPort
from .retrain import RetrainReport, TileScore, retrain
from .stats import newcombe_difference, two_proportion_z, wilson_interval

__all__ = [
    "AuthorRequest",
    "Choice",
    "CloudAuthor",
    "ContextualBandit",
    "FeedbackPacket",
    "LedgerPort",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "Precondition",
    "RetrainReport",
    "ScriptedAuthor",
    "TILE_EVENT_TYPES",
    "Tile",
    "TileAuthor",
    "TileAuthorProtocol",
    "TileChooser",
    "TileLibrary",
    "TileRefusal",
    "TileScore",
    "TileStep",
    "VocabularyPort",
    "build_play_record",
    "build_tile",
    "fold_library",
    "fold_plays",
    "newcombe_difference",
    "record_play",
    "retrain",
    "two_proportion_z",
    "validate_tile",
    "wilson_interval",
]
