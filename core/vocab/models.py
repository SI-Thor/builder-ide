"""The records of the vocabulary seat, shaped exactly as `docs/design/core-spec.md` (v2) says.

The citations in each docstring are the contract. If the spec changes, these
change with it; nothing here is invented.

    §1.1  Op, RecipeEdit, Actor
    §1.2  RecipeVersion, Branch
    §1.3  AcceptanceCheck
    §1.5  VocabularyEntry, TasteNote (the entry-embedded aggregate)
    §1.7  Prediction, ReasonCode
    §1.8  AuditEvent

**These records live in :mod:`core.records`** — one definition each, shared
with every other seat, because the vocabulary, the recipe half, the API half
and the night runner all write the same records. This module re-exports them
so ``from core.vocab.models import Prediction`` still works and
``core.vocab.models.Prediction is core.records.Prediction`` is true.

The vocabulary seat's own records — the call door, the gate, the sealed
prediction service and the Prop-maker — live in the sibling modules.
"""

from __future__ import annotations

from typing import Any

from core.records import (
    CLAIM_TYPES,
    CONFIDENCE_LEVELS,
    EDIT_AUTHOR_KINDS,
    REASON_CODES,
    AcceptanceCheck,
    Actor,
    ActorKind,
    AuditEvent,
    Branch,
    BranchPurpose,
    ClaimType,
    EntryTasteNote,
    Op,
    Prediction,
    ReasonCode,
    RecipeEdit,
    RecipeVersion,
    TasteNote as LedgerTasteNote,
    VocabularyEntry,
)

#: The spec defines two classes called TasteNote: the entry-embedded
#: aggregate (§1.5) and the taste-ledger row (§1.7). This seat only uses the
#: entry-embedded one, so its name is kept here as an alias.
TasteNote = EntryTasteNote

__all__ = [
    "Actor",
    "ActorKind",
    "Op",
    "RecipeEdit",
    "AcceptanceCheck",
    "TasteNote",
    "EntryTasteNote",
    "LedgerTasteNote",
    "VocabularyEntry",
    "Prediction",
    "AuditEvent",
    "RecipeVersion",
    "Branch",
    "ReasonCode",
    "ClaimType",
    "CLAIM_TYPES",
    "REASON_CODES",
    "CONFIDENCE_LEVELS",
    "EDIT_AUTHOR_KINDS",
]

Json = Any
