"""The recipe models of core-spec v2 §1.1, §1.2, §1.4.0 and §1.8.

Field names and shapes follow the spec exactly; the comments carry the spec's
own wording so the two can be diffed by eye.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Actor",
    "ActorKind",
    "EntryKind",
    "ConstraintKind",
    "BranchPurpose",
    "EnginePin",
    "GeneratorRef",
    "Constraint",
    "RecipeEntry",
    "Recipe",
    "Op",
    "RecipeEdit",
    "RecipeVersion",
    "Branch",
    "NodeRef",
    "AuditEvent",
    "RecipeRecord",
    "ValidationReport",
    "MAX_OPS_PER_EDIT",
    "MAX_EDIT_MESSAGE_CHARS",
]

ActorKind = Literal[
    "owner", "character", "engineer", "critic", "core", "scheduler", "client"
]
EntryKind = Literal[
    "generator",
    "structure",
    "prop_set",
    "material",
    "terrain",
    "character",
    "motion",
    "light",
    "weather",
    "asset_ref",
]
ConstraintKind = Literal[
    "keep_clear", "load_floor", "reachability", "budget_custom", "watertight", "scale_bounds"
]
BranchPurpose = Literal[
    "main", "night", "work-order", "morning-option", "standing", "rejected"
]

MAX_OPS_PER_EDIT = 32
MAX_EDIT_MESSAGE_CHARS = 80

_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")
_HEX = re.compile(r"^[0-9a-f]+$")


class Actor(BaseModel):
    """Who did it. ``via`` says through which door (a word, a work order)."""

    model_config = ConfigDict(frozen=True)

    kind: ActorKind
    id: str
    via: str | None = None


class EnginePin(BaseModel):
    """The pinned engine. RV patch 13: the config hash is load-bearing."""

    model_config = ConfigDict(frozen=True)

    repo: str
    commit: str
    config: str
    blender: str
    python: str

    @field_validator("config")
    @classmethod
    def _config_is_a_pinned_hash(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("engine_pin.config must be a pinned sha256 hash")
        digits = value[len("sha256:") :]
        if len(digits) < 4 or not _HEX.fullmatch(digits):
            raise ValueError("engine_pin.config must be a pinned sha256 hash")
        return value


class GeneratorRef(BaseModel):
    """Where an entry's generator comes from, and from which engine commit."""

    model_config = ConfigDict(frozen=True)

    module: str
    func: str
    variant: str | None = None
    rev: str


class Constraint(BaseModel):
    """A constraint on an entry or on the project."""

    name: str
    kind: ConstraintKind
    ref: str | None = None
    value: float | None = None


class RecipeEntry(BaseModel):
    """One typed entry of a recipe: a generator, its params, its seeds."""

    path: str
    kind: EntryKind
    generator: GeneratorRef | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    constraints: list[Constraint] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    origin: str | None = None

    @field_validator("path")
    @classmethod
    def _path_is_dotted_and_short(cls, value: str) -> str:
        segments = value.split(".")
        if not 1 <= len(segments) <= 3:
            raise ValueError("entry path must be dotted with at most 3 segments")
        if not all(_PATH_SEGMENT.fullmatch(s) for s in segments):
            raise ValueError("entry path segments must be alphanumeric or underscore")
        return value


class Recipe(BaseModel):
    """A project is its recipe. Meshes and renders are caches."""

    id: str
    name: str
    schema_version: int = 2
    engine_pin: EnginePin
    seeds: dict[str, int] = Field(default_factory=dict)
    entries: dict[str, RecipeEntry] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _entry_paths_match_their_keys(self) -> "Recipe":
        for key, entry in self.entries.items():
            if entry.path != key:
                raise ValueError(
                    f"entry {key!r} carries path {entry.path!r}; the key is the path"
                )
        return self


class Op(BaseModel):
    """One typed operation against a recipe document."""

    model_config = ConfigDict(frozen=True)

    op: Literal["set", "add", "remove"]
    path: str
    value: Any | None = None


class RecipeEdit(BaseModel):
    """A typed change: a list of ops against a parent version."""

    id: str
    base: str
    ops: list[Op] = Field(default_factory=list)
    author: Actor
    message: str
    prediction: str | None = None

    @field_validator("message")
    @classmethod
    def _message_is_one_short_line(cls, value: str) -> str:
        if len(value) > MAX_EDIT_MESSAGE_CHARS:
            raise ValueError(f"edit message is capped at {MAX_EDIT_MESSAGE_CHARS} chars")
        if "\n" in value or "\r" in value:
            raise ValueError("edit message is one line")
        return value

    @field_validator("ops")
    @classmethod
    def _ops_are_bounded(cls, value: list[Op]) -> list[Op]:
        if len(value) > MAX_OPS_PER_EDIT:
            raise ValueError(f"an edit carries at most {MAX_OPS_PER_EDIT} ops")
        return value


class RecipeVersion(BaseModel):
    """A committed version: the canonical document plus its provenance."""

    id: str
    recipe: str
    parent: str | None = None
    edit: str | None = None
    root_hash: str
    at: str
    actor: Actor


class Branch(BaseModel):
    """A named commit line. The head moves only forward."""

    id: str
    name: str
    recipe: str
    head: str
    base: str | None = None
    purpose: BranchPurpose
    created_by: Actor
    protected: bool = False


class NodeRef(BaseModel):
    """A world node id mapped to its recipe entry path (the node registry)."""

    node_id: str
    entry_path: str
    kind: str
    assets: list[str] = Field(default_factory=list)
    part: str | None = None
    orphaned: bool = False


class AuditEvent(BaseModel):
    """The one log. Everything the panels show is a view over this."""

    seq: int
    id: str
    at: str
    actor: Actor
    type: str
    subject: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] | None = None


class RecipeRecord(BaseModel):
    """The projection of a recipe: its identity and its root version."""

    id: str
    name: str
    root_version: str
    created_at: str


class BranchProposal(BaseModel):
    """A kid actor's branch choice, pending the owner's confirmation.

    Magnus's apply is a proposal, not an edit: a branch apply is a real edit,
    so his is ``branch.proposed`` until Casey confirms it (§7.15).
    """

    id: str
    branch: str
    proposed_head: str
    by: Actor
    at: str
    state: Literal["pending", "confirmed", "declined"] = "pending"


class ValidationReport(BaseModel):
    """What the pre-render checks found about a candidate document."""

    ok: bool
    touched: list[str] = Field(default_factory=list)
    schema_violations: list[dict[str, Any]] = Field(default_factory=list)
    constraint_checks: list[dict[str, Any]] = Field(default_factory=list)
