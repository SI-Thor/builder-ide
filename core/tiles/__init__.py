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
from .bands import (
    BandConfig,
    BandDecision,
    BandGate,
    DEFAULT_BAND,
    DEFAULT_TAU_HI,
    DEFAULT_TAU_LO,
)
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
from .nail import NAIL_FORMAT, NailBundle, export_nail, read_nail, write_nail
from .ope import (
    BanditRewardModel,
    CrossFittedRewardModel,
    DeterministicTarget,
    FixedTarget,
    OPEError,
    OPEEstimate,
    SoftmaxTarget,
    TargetPolicy,
    corrupt_propensities,
    evaluate,
    weights_for,
)
from .plays import fold_plays, record_play
from .ports import LedgerPort, VocabularyPort
from .retrieval import (
    Embedder,
    EmbedderUnavailable,
    HashingEmbedder,
    RetrievalChooser,
    RetrievalFront,
    RetrievalResult,
    StaticEmbedder,
    TileIndex,
    default_embedder,
    describe_tile,
    embedder_record,
)
from .retrain import RetrainReport, TileScore, retrain
from .stats import newcombe_difference, two_proportion_z, wilson_interval

__all__ = [
    "AuthorRequest",
    "BandConfig",
    "BandDecision",
    "BandGate",
    "BanditRewardModel",
    "Choice",
    "CrossFittedRewardModel",
    "DEFAULT_BAND",
    "DEFAULT_TAU_HI",
    "DEFAULT_TAU_LO",
    "DeterministicTarget",
    "CloudAuthor",
    "ContextualBandit",
    "Embedder",
    "EmbedderUnavailable",
    "FeedbackPacket",
    "FixedTarget",
    "HashingEmbedder",
    "LedgerPort",
    "NAIL_FORMAT",
    "NailBundle",
    "OPEError",
    "OPEEstimate",
    "Outcome",
    "PlayCost",
    "PlayRecord",
    "Precondition",
    "RetrievalChooser",
    "RetrievalFront",
    "RetrievalResult",
    "RetrainReport",
    "ScriptedAuthor",
    "SoftmaxTarget",
    "StaticEmbedder",
    "TILE_EVENT_TYPES",
    "Tile",
    "TileAuthor",
    "TileAuthorProtocol",
    "TileChooser",
    "TileIndex",
    "TileLibrary",
    "TileRefusal",
    "TileScore",
    "TileStep",
    "TargetPolicy",
    "VocabularyPort",
    "build_play_record",
    "build_tile",
    "corrupt_propensities",
    "default_embedder",
    "describe_tile",
    "embedder_record",
    "evaluate",
    "export_nail",
    "fold_library",
    "fold_plays",
    "newcombe_difference",
    "read_nail",
    "record_play",
    "retrain",
    "two_proportion_z",
    "validate_tile",
    "weights_for",
    "wilson_interval",
    "write_nail",
]
