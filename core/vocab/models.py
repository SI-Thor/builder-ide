"""The records of the vocabulary seat, shaped exactly as `docs/design/core-spec.md` (v2) says.

The citations in each docstring are the contract. If the spec changes, these
change with it; nothing here is invented.

    §1.1  Op, RecipeEdit, Actor
    §1.2  RecipeVersion, Branch
    §1.3  AcceptanceCheck
    §1.5  VocabularyEntry, TasteNote (the entry-embedded aggregate)
    §1.7  Prediction, ReasonCode
    §1.8  AuditEvent

The recipe document itself (`Recipe`, `RecipeEntry`, `EnginePin`) is **not**
mirrored here: that is `core-recipe`'s to own (branch `core-recipe`). Our stub
recipe store hashes a plain canonical-JSON document instead, so the two seats
can be merged without two definitions of the same record.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Actor",
    "Op",
    "RecipeEdit",
    "AcceptanceCheck",
    "TasteNote",
    "VocabularyEntry",
    "Prediction",
    "AuditEvent",
    "RecipeVersion",
    "Branch",
    "ReasonCode",
    "ClaimType",
    "CLAIM_TYPES",
    "REASON_CODES",
]

Json = Any

#: §1.7 — "the closed dozen" (T §"Taste note fields").
ReasonCode = Literal[
    "too_busy",
    "too_empty",
    "wrong_scale",
    "too_messy",
    "too_clean",
    "too_flat",
    "too_dark",
    "too_bright",
    "wrong_material",
    "wrong_era",
    "wrong_weather",
    "no_focus",
]

REASON_CODES: tuple[str, ...] = (
    "too_busy",
    "too_empty",
    "wrong_scale",
    "too_messy",
    "too_clean",
    "too_flat",
    "too_dark",
    "too_bright",
    "wrong_material",
    "wrong_era",
    "wrong_weather",
    "no_focus",
)

#: §1.7 — the closed set of claim types (T's six plus `weather_read`; §7.2).
ClaimType = Literal[
    "shadow_count",
    "scale_read",
    "clutter_density",
    "material_read",
    "era_read",
    "light_read",
    "weather_read",
    "taste_keep",
]

CLAIM_TYPES: tuple[str, ...] = (
    "shadow_count",
    "scale_read",
    "clutter_density",
    "material_read",
    "era_read",
    "light_read",
    "weather_read",
    "taste_keep",
)

#: §1.1 — `RecipeEdit.author` is `{kind: character|engineer|owner|core, id, via: word|wo}`.
#: §1.8 — an audit event's actor may also be `critic`, `scheduler` or `client`.
ActorKind = Literal[
    "owner", "character", "engineer", "critic", "core", "scheduler", "client"
]

#: §1.1 — the actor kinds a recipe edit may be authored by.
EDIT_AUTHOR_KINDS: tuple[str, ...] = ("character", "engineer", "owner", "core")


class Actor(BaseModel):
    """§1.1 — who did it, and through which door."""

    model_config = ConfigDict(frozen=True)

    kind: ActorKind
    id: str
    via: str | None = None


class Op(BaseModel):
    """§1.1 — one typed operation against a parent recipe version."""

    model_config = ConfigDict(frozen=True)

    op: Literal["set", "add", "remove"]
    path: str
    value: Json | None = None


class RecipeEdit(BaseModel):
    """§1.1 — a recipe never mutates in place; change is an edit (≤ 32 ops).

    `prediction` is the `pr_` id of a bet sealed **before** any render exists
    (D §23:04 step 2).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    base: str
    ops: list[Op] = Field(max_length=32)
    author: Actor
    message: str
    prediction: str | None = None

    @field_validator("message")
    @classmethod
    def _one_line_of_at_most_80_chars(cls, value: str) -> str:
        if "\n" in value:
            raise ValueError("message is one line")
        if len(value) > 80:
            raise ValueError("message is at most 80 characters")
        return value

    @field_validator("author")
    @classmethod
    def _author_is_one_of_the_four(cls, value: Actor) -> Actor:
        if value.kind not in EDIT_AUTHOR_KINDS:
            raise ValueError(
                f"an edit is authored by one of {list(EDIT_AUTHOR_KINDS)}"
            )
        return value


class AcceptanceCheck(BaseModel):
    """§1.3 — a machine-checkable acceptance item.

    `spec` may hold `{node}` placeholders, bound at call time (§1.5).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "constraint", "geometry", "critic", "test_suite", "render_rung", "manual"
    ]
    spec: dict[str, Json]


class TasteNote(BaseModel):
    """§1.5 — the aggregate the **core** keeps on an entry; read-only to characters.

    `basis` carries counts with denominators, never percentages (T §"The taste
    ledger"): "4/5 kept".
    """

    model_config = ConfigDict(frozen=True)

    code: Literal["keep", "avoid"]
    reason_code: ReasonCode
    note: str = ""
    basis: str

    @field_validator("note")
    @classmethod
    def _at_most_six_words(cls, value: str) -> str:
        if len(value.split()) > 6:
            raise ValueError("note is at most 6 words")
        return value


class VocabularyEntry(BaseModel):
    """§1.5 — the closed, typed vocabulary entry.

    A word is added only by the core, only from a kept work order or by the
    owner; characters read and cite, never write.
    """

    model_config = ConfigDict(frozen=True)

    word: str
    kind: Literal[
        "structure",
        "prop",
        "material",
        "terrain",
        "weather",
        "motion",
        "light",
        "constraint",
        "character",
    ]
    owner_character: str
    status: Literal["active", "coming-soon", "retired"]
    params: dict[str, Json]
    acceptance_template: AcceptanceCheck | None = None
    taste_notes: list[TasteNote] = Field(default_factory=list)
    provenance: dict[str, Json] = Field(default_factory=dict)
    version: int = 1

    @field_validator("word")
    @classmethod
    def _dotted_at_most_three_segments(cls, value: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= 3:
            raise ValueError("word is dotted with at most 3 segments")
        if any(not part for part in parts):
            raise ValueError("word has an empty segment")
        return value

    @field_validator("provenance")
    @classmethod
    def _provenance_has_an_origin(cls, value: dict[str, Json]) -> dict[str, Json]:
        if "origin" not in value:
            raise ValueError("provenance carries an origin")
        return value


class Prediction(BaseModel):
    """§1.7 — a bet, sealed before the render that could disprove it.

    The model is frozen: a sealed record cannot be edited. Only `verdict` is
    written later, by somebody other than the builder (never self-scored).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    builder: str
    at: str
    sealed_at: str
    branch_ref: str
    claim: str
    claim_type: ClaimType
    namespace: Literal["world", "taste"]
    confidence: Literal["guess", "low", "medium", "high"]
    basis: str
    render_spec: dict[str, Json] | None = None
    seal_hash: str
    verdict: Literal["hit", "miss", "partial"] | None = None

    @field_validator("claim")
    @classmethod
    def _claim_is_at_most_120_chars(cls, value: str) -> str:
        if len(value) > 120:
            raise ValueError("claim is at most 120 characters")
        return value

    @field_validator("basis")
    @classmethod
    def _basis_carries_a_denominator(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("basis is not empty")
        if "%" in value:
            raise ValueError("basis carries counts with denominators, never percentages")
        return value

    @model_validator(mode="after")
    def _namespace_follows_the_claim_type(self) -> "Prediction":
        # §1.7: "taste iff claim_type == taste_keep — two gates".
        expected = "taste" if self.claim_type == "taste_keep" else "world"
        if self.namespace != expected:
            raise ValueError(
                f"namespace must be {expected!r} for claim_type {self.claim_type!r}"
            )
        return self


class AuditEvent(BaseModel):
    """§1.8 — the one log. Every panel is a view over this table."""

    model_config = ConfigDict(frozen=True)

    seq: int
    id: str
    at: str
    actor: Actor
    type: str
    subject: dict[str, Json] = Field(default_factory=dict)
    payload: dict[str, Json] = Field(default_factory=dict)
    artifact: dict[str, Json] | None = None


class RecipeVersion(BaseModel):
    """§1.2 — a committed recipe version; `root_hash` is the canonical document's hash."""

    model_config = ConfigDict(frozen=True)

    id: str
    recipe: str
    parent: str | None = None
    edit: str | None = None
    root_hash: str
    at: str
    actor: Actor


class Branch(BaseModel):
    """§1.2 — a named commit of the world; `head` moves forward only."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    recipe: str
    head: str
    base: str | None = None
    purpose: Literal[
        "main", "night", "work-order", "morning-option", "standing", "rejected"
    ]
    created_by: Actor
    protected: bool = False
