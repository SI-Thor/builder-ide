"""The vocabulary seat of builder-ide's core.

Three things live here, and they are the three things a builder needs in order
to change the world without writing code:

* **the vocabulary** — a closed, typed set of words (`VocabularyEntry`), each
  with a bounded param schema, taste notes and provenance (§1.5);
* **the door** — a character's typed call, validated at the threshold and
  refused with a reason code when it falls outside the schema (§1.5);
* **sealed predictions** — bets hashed into the ledger *before* the render that
  could disprove them, and the **confidence gate** that decides when a builder
  may speak a claim and when it may act alone (§1.7).

Plus the **Prop-maker's scripted loop** (D §23:04), which ties the three
together: edit → predict and seal → preview → critic → act.

The modules mirror `docs/design/core-spec.md` (v2); the docstring of each one
cites the section it implements. The seams to the seats building the core in
parallel (`core-api`, `core-recipe`) are in `ports.py`, with in-memory stubs in
`stubs.py`.
"""

from __future__ import annotations

from .call import CallRefusal, VocabularyService, bind_acceptance_template
from .clock import Clock, FixedClock, SteppingClock, SystemClock
from .gate import Gate, GateDecision, ObservationCounts
from .hashing import canonical_json, content_hash, short_hash
from .models import (
    AcceptanceCheck,
    Actor,
    AuditEvent,
    Branch,
    Op,
    Prediction,
    RecipeEdit,
    RecipeVersion,
    TasteNote,
    VocabularyEntry,
)
from .ports import LedgerPort, RecipeStorePort, RenderJob, RenderRequest, SchedulerPort
from .predictions import PredictionService, build_prediction, seal_hash_for, verify_seal
from .projections import fold_predictions
from .propmaker import CrateBet, NightOutcome, PropMaker, ScriptedCritic, ScriptedFinding
from .registry import CapabilityRow, VocabularyRegistry, entry_path_for
from .schema import ParamsError, SchemaError, validate_params, validate_schema
from .stubs import InMemoryLedger, InMemoryRecipeStore, InMemoryScheduler, LedgerError
from .taste import TasteRow, aggregate_taste_notes
from .words import default_entries

__all__ = [
    "AcceptanceCheck",
    "Actor",
    "AuditEvent",
    "Branch",
    "CallRefusal",
    "CapabilityRow",
    "CrateBet",
    "Clock",
    "FixedClock",
    "Gate",
    "GateDecision",
    "InMemoryLedger",
    "InMemoryRecipeStore",
    "InMemoryScheduler",
    "LedgerError",
    "LedgerPort",
    "NightOutcome",
    "ObservationCounts",
    "Op",
    "ParamsError",
    "Prediction",
    "PredictionService",
    "PropMaker",
    "RecipeEdit",
    "RecipeStorePort",
    "RecipeVersion",
    "RenderJob",
    "RenderRequest",
    "SchedulerPort",
    "SchemaError",
    "ScriptedCritic",
    "ScriptedFinding",
    "SteppingClock",
    "SystemClock",
    "TasteNote",
    "TasteRow",
    "VocabularyEntry",
    "VocabularyRegistry",
    "VocabularyService",
    "aggregate_taste_notes",
    "bind_acceptance_template",
    "build_prediction",
    "canonical_json",
    "content_hash",
    "default_entries",
    "entry_path_for",
    "fold_predictions",
    "seal_hash_for",
    "short_hash",
    "validate_params",
    "validate_schema",
    "verify_seal",
]
