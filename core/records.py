"""The spec's shared records — one definition each (core-spec v2 §1).

Seven seats each grew their own copy of the records the spec names in §1:
the API half, the recipe half, the vocabulary, the night runner, the cold
start, the justification layer and the USD backbone. Left alone, that is
seven ``Actor`` classes that are not equal to each other, and a record
written by one seat cannot be read by another.

This module is the single home. The seats import from here; their old
modules re-export these names, so **every import path still works** and
``core.models.Actor is core.records.Actor`` is true exactly once.

Where two seats disagreed, the richer definition won — the one carrying the
spec's validators — and the loser's extra defaults were folded back in so
that neither seat's construction sites break. The decisions, record by
record, are in INTEGRATION.md.

What lives here is the *shared* set. Records only one seat owns (a work
order, a context packet, a question, a night's report) stay in that seat's
module — there is nothing to reconcile.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canon import now_utc

Json = Any

__all__ = [
    # §1.8 the one log
    "EVENT_TYPES",
    "ActorKind",
    "Actor",
    "EDIT_AUTHOR_KINDS",
    "AuditEvent",
    # §1.3 rails
    "Rail",
    # §1.9 the night
    "TaskState",
    "NightState",
    "NightStatus",
    "JobState",
    "IterationPolicy",
    "Task",
    "Job",
    "Night",
    # §1.1/§1.2 the recipe
    "EntryKind",
    "ConstraintKind",
    "BranchPurpose",
    "MAX_OPS_PER_EDIT",
    "MAX_EDIT_MESSAGE_CHARS",
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
    # §1.3 acceptance
    "AcceptanceCheck",
    "CHECKABLE_KINDS",
    # §1.5 the vocabulary
    "EntryTasteNote",
    "VocabularyEntry",
    # §1.7 the ledgers
    "ReasonCode",
    "REASON_CODES",
    "ClaimType",
    "CLAIM_TYPES",
    "CONFIDENCE_LEVELS",
    "Prediction",
    "TasteNote",
]


# ==================================================================== §1.8
# The one log. Event types are a closed set; adding one is a schema change.

#: The closed set, verbatim from §1.8 ("New in v2" types included).
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # work orders
        "wo.filed", "wo.compiled", "wo.questioned", "wo.confirmed", "wo.queued",
        "wo.attempt.started", "wo.attempt.delivered", "wo.testing", "wo.landed",
        "wo.kept", "wo.rejected", "wo.parked", "wo.resumed", "wo.failed",
        "wo.cancelled",
        # recipe (appended by the recipe half; folded here)
        "edit.proposed", "edit.validated", "version.committed", "branch.created",
        "branch.head.moved", "branch.rejected", "branch.proposed",
        "constraint.failed",
        # predictions
        "prediction.sealed", "prediction.scored",
        # taste
        "taste.note.appended", "taste.erased", "taste.ratified",
        # vocabulary
        "vocab.word.added", "vocab.word.status", "vocab.call",
        # night
        "night.started", "night.stopped", "night.preflight", "night.tick",
        "night.task.created", "night.task.state", "line.spoken",
        # daytime (the always-on world between sessions; one room, one clock)
        "day.world.opened", "day.tick", "day.change", "day.yielded",
        # scheduler (appended by the runner half; folded here)
        "sched.model.load", "sched.model.unload", "sched.demote", "job.enqueued",
        "job.started", "job.done", "job.requeued", "render.completed",
        "scene.loaded", "scene.evicted", "power.mode.set",
        # critic
        "critic.verdict",
        # budget
        "budget.spend", "budget.threshold", "kill.switch",
        # assets
        "asset.created", "asset.licence.checked",
        # questions
        "question.parked", "question.answered", "assumption.recorded",
        # continuity
        "model.change.noticed",
        # client
        "client.attach", "client.detach",
        # system
        "core.boot", "core.recovered", "projection.rebuilt", "integrity.failure",
        "call.refused",
    }
)


# ==================================================================== §1.1
# Who did it.

ActorKind = Literal["owner", "character", "engineer", "critic", "core", "scheduler", "client"]

#: §1.1 — the actor kinds a recipe edit may be authored by.
EDIT_AUTHOR_KINDS: tuple[str, ...] = ("character", "engineer", "owner", "core")


class Actor(BaseModel):
    """Who did it. ``via`` says through which door (a word, a work order).

    §1.1: ``{kind: character|engineer|owner|core, id, via: word|wo}``.
    §1.8: an audit event's actor may also be ``critic``, ``scheduler`` or
    ``client``.

    Frozen: an actor is an identity, and the log must not be able to
    rewrite who did something after the fact.
    """

    model_config = ConfigDict(frozen=True)

    kind: ActorKind
    id: str
    via: str | None = None


class AuditEvent(BaseModel):
    """§1.8 — the one log. Every panel is a view over this table.

    The API half's version was the richest of the four copies (it carries
    the closed type check, the subject accessors and the refusal flag), so
    it is the one that survived; the recipe half's, the vocabulary's and
    the night runner's were the same shape with fewer guarantees.
    """

    seq: int | None = None  # assigned at commit; gapless per project (§1.8)
    id: str = Field(min_length=4)
    at: str = Field(default_factory=now_utc)
    actor: Actor
    type: str
    subject: dict[str, Json] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] | None = None  # {sha256, kind, bytes}
    # Refused events (the vocab.call precedent: "refused calls included —
    # the edges are the story") commit to the log but change no projection.
    refused: bool = False

    def validate_type(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.type!r}; the set is closed (§1.8)")

    @property
    def subject_id(self) -> str:
        """The subject's entity id. Named to match the audit table's
        `subject_kind`/`subject_id` columns, so the fold can read the
        subject the same way it writes it."""
        return self.subject.get("entity_id", "")

    @property
    def subject_kind(self) -> str:
        return self.subject.get("entity_kind", "")

    def payload_bytes(self) -> int:
        from .canon import canonical_bytes

        return len(canonical_bytes(self.payload))


# ==================================================================== §1.3
# The three axes of spend.

class Rail(BaseModel):
    """Three axes of spend: lane time, hosted cents and wall clock (§1.3, §5.5).

    GPU-minutes come from the model registry's measured cost table, not from
    wall clock, so a cheap CPU-lane hour does not eat the GPU bar (§5.5).

    The night runner's copy carried the arithmetic (``add``/``subtract``/
    ``fits``/``is_zero``) and the API half's carried the same three fields
    without it. One record, with the arithmetic.
    """

    gpu_minutes: float = 0.0
    hosted_cents: int = 0
    wall_minutes: float = 0.0

    def add(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=self.gpu_minutes + other.gpu_minutes,
            hosted_cents=self.hosted_cents + other.hosted_cents,
            wall_minutes=self.wall_minutes + other.wall_minutes,
        )

    def subtract(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=self.gpu_minutes - other.gpu_minutes,
            hosted_cents=self.hosted_cents - other.hosted_cents,
            wall_minutes=self.wall_minutes - other.wall_minutes,
        )

    def fits(self, ask: "Rail") -> bool:
        """True when ``ask`` fits inside this rail (used as a ceiling)."""
        return (
            ask.gpu_minutes <= self.gpu_minutes
            and ask.hosted_cents <= self.hosted_cents
            and ask.wall_minutes <= self.wall_minutes
        )

    @property
    def is_zero(self) -> bool:
        return (
            self.gpu_minutes == 0.0
            and self.hosted_cents == 0
            and self.wall_minutes == 0.0
        )


# ==================================================================== §1.9
# The night: the plan, the jobs it dispatches, the night itself.

#: §1.9's closed Task states. ``dropped`` is the owner's morning *kill
#: this goal* decision — the spec's ``cut`` is budget-driven ("dropped at
#: the bar, requeued for tomorrow"), which is a deferral, not a kill. See
#: INTEGRATION.md, decision 1.
TaskState = Literal[
    "slated", "queued", "running", "kept", "reverted", "parked", "cut", "dropped",
]

JobState = Literal["queued", "running", "done", "failed", "requeued"]

NightState = Literal["starting", "running", "stopping", "stopped"]

NightStatus = Literal["ran as planned", "ran short", "ran degraded", "did not run"]


class IterationPolicy(BaseModel):
    """How deep the night goes on one goal — N, K and ε.

    It is a **rail**, not a preference: the budget can cut a loop short, and
    the morning says where it was cut. It rides on the night (the night's
    ``iteration``), so the depth the night ran at is foldable from the log
    like everything else.
    """

    variants_per_round: int = Field(default=3, ge=1)
    max_rounds: int = Field(default=3, ge=1)
    min_gain: float = Field(default=0.02, ge=0.0)


class Task(BaseModel):
    """One unit of the owner's plan (§1.9).

    A task exists before any night (RV patch 11): ``night`` is ``None`` and
    ``state`` is ``"slated"`` on the plan slate, which is why ``cost_estimate``
    — the *ask* — is stored, so the morning can name what was cut (X C11).

    The ask comes from the **cost model** (``core/night/cost``): the task
    names the job kind it is (``kind``) and the model prices it. Three fields
    keep that honest on the record:

    ``kind``
        the job kind the ask was priced from.
    ``ask_source``
        ``"model"`` when the model priced it, ``"override"`` when the owner
        filed their own number. An override is kept, not overwritten — the
        owner is held to the number they filed.
    ``ask_basis``
        the model's own marking of the ask: ``measured``, ``derived`` or
        ``estimate``. An owner's own number is an estimate until the box
        measures it.
    """

    id: str
    night: str | None = None
    author: str = "casey"
    ends_at: str | None = None
    owner_character: str = ""
    intention: str
    recipe_scope: list[str] = Field(default_factory=list)
    cost_estimate: Rail = Field(default_factory=Rail)
    rail: Rail = Field(default_factory=Rail)
    #: The cost model's job kind this task's ask was priced from.
    kind: str = ""
    #: ``model`` (the measured price) or ``override`` (the owner's own number).
    ask_source: str = "model"
    #: The model's marking of the ask: measured, derived or estimate.
    ask_basis: str = ""
    state: TaskState = "slated"
    predictions: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)
    #: When the goal was put on the slate — the anchor of its justification
    #: attestation ("alive since ...").
    slated_at: str | None = None
    #: The slate's soft expiry for this goal: an untouched goal goes
    #: questionable rather than silently live forever. The spec has no
    #: goal-horizon field; this is the minimal extension the justification
    #: layer needs. See INTEGRATION.md, decision 4.
    review_by: str | None = None


class Job(BaseModel):
    """One dispatched unit of work on a lane (§1.9)."""

    id: str
    lane: Literal["cpu", "gpu"] = "cpu"
    worker: str = "thor"
    model: str | None = None
    request: dict = Field(default_factory=dict)
    cost_estimate: Rail = Field(default_factory=Rail)
    claim_token: str = ""
    lease_until: str | None = None
    heartbeat_at: str | None = None
    power_mode: int | None = None
    stage_cache: str | None = None
    state: JobState = "queued"
    outputs: list[str] = Field(default_factory=list)
    task_id: str | None = None


class Night(BaseModel):
    """One night: its rails, its load budget and its computed status (§1.9).

    ``status`` is **computed** at stop from the heartbeats and the admission
    waits — never narrated by whoever is awake to write it (§3.4).
    """

    id: str
    started_at: str = Field(default_factory=now_utc)
    stopped_at: str | None = None
    rails: Rail = Field(default_factory=Rail)
    load_budget: dict[str, int] = Field(default_factory=dict)
    power_mode: int = 0
    batch_start: Literal["detach", "deadline", "both"] = "both"
    detach_deadline: str | None = None
    state: NightState = "starting"
    status: str | None = None  # computed at stop from heartbeats (§3.4)
    stop_reason: str | None = None  # why it stopped — never hidden (D, T, G §2)
    report: str | None = None  # the report artifact's hash
    #: The night's depth policy — how many variants per round, how many
    #: rounds, and the ε the loop stops below (the iterator's rails).
    iteration: IterationPolicy | None = None


# ==================================================================== §1.1/§1.2
# The recipe: a project is its recipe; meshes and renders are caches.

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
    """One typed operation against a recipe document (§1.1)."""

    model_config = ConfigDict(frozen=True)

    op: Literal["set", "add", "remove"]
    path: str
    value: Json | None = None


class RecipeEdit(BaseModel):
    """§1.1 — a recipe never mutates in place; change is an edit (≤ 32 ops).

    ``prediction`` is the ``pr_`` id of a bet sealed **before** any render
    exists (D §23:04 step 2).
    """

    model_config = ConfigDict(frozen=True)

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
            raise ValueError("edit message is capped at 80 chars")
        if "\n" in value or "\r" in value:
            raise ValueError("edit message is one line")
        return value

    @field_validator("ops")
    @classmethod
    def _ops_are_bounded(cls, value: list[Op]) -> list[Op]:
        if len(value) > MAX_OPS_PER_EDIT:
            raise ValueError("an edit carries at most 32 ops")
        return value


class RecipeVersion(BaseModel):
    """§1.2 — a committed recipe version; ``root_hash`` is the canonical
    document's hash."""

    model_config = ConfigDict(frozen=True)

    id: str
    recipe: str
    parent: str | None = None
    edit: str | None = None
    root_hash: str
    at: str
    actor: Actor


class Branch(BaseModel):
    """§1.2 — a named commit of the world; ``head`` moves forward only.

    Deliberately **not** frozen: a branch row is a projection, and the
    fold moves ``head`` (and flips ``purpose`` on rejection) in place as
    ``branch.head.moved`` events replay — the log is the source of truth,
    the record is a view over it (§1.0).
    """

    id: str
    name: str
    recipe: str = ""
    head: str = ""
    base: str | None = None
    purpose: BranchPurpose = "work-order"
    created_by: Actor | None = None
    protected: bool = False


class NodeRef(BaseModel):
    """§1.4.0 — a world node id mapped to its recipe entry path.

    Not frozen for the same reason as ``Branch``: the registry's projection
    marks removed entries' nodes ``orphaned`` in place — ids are never
    reused, and the registry is rebuildable from the compiler's artifact.
    """

    node_id: str
    entry_path: str
    kind: str
    assets: list[str] = Field(default_factory=list)
    part: str | None = None
    orphaned: bool = False


# ==================================================================== §1.3
# A machine-checkable acceptance item.

class AcceptanceCheck(BaseModel):
    """§1.3 — a machine-checkable acceptance item.

    ``spec`` may hold ``{node}`` placeholders, bound at call time (§1.5).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "constraint", "geometry", "critic", "test_suite", "render_rung", "manual"
    ]
    spec: dict[str, Json]


CHECKABLE_KINDS = frozenset({"constraint", "geometry", "critic", "test_suite", "render_rung"})


# ==================================================================== §1.5
# The closed, typed vocabulary.

class EntryTasteNote(BaseModel):
    """§1.5 — the aggregate the **core** keeps on an entry; read-only to
    characters.

    ``basis`` carries counts with denominators, never percentages (T §"The
    taste ledger"): "4/5 kept".
    """

    model_config = ConfigDict(frozen=True)

    code: Literal["keep", "avoid"]
    reason_code: "ReasonCode"
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
    status: Literal["active", "coming-soon", "retired"] = "active"
    params: dict[str, Json] = Field(default_factory=dict)
    acceptance_template: AcceptanceCheck | None = None
    taste_notes: list[EntryTasteNote] = Field(default_factory=list)
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


# ==================================================================== §1.7
# The ledgers: a bet, and the taste notes.

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

#: §1.7 — the closed set of claim types (T's six plus ``weather_read``; §7.2).
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

CONFIDENCE_LEVELS = frozenset({"guess", "low", "medium", "high"})


class Prediction(BaseModel):
    """§1.7 — a bet, sealed before the render that could disprove it.

    The model is frozen: a sealed record cannot be edited. Only ``verdict``
    is written later, by somebody other than the builder (never self-scored).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    builder: str
    at: str = Field(default_factory=now_utc)
    sealed_at: str = ""
    branch_ref: str
    claim: str = Field(max_length=120)
    claim_type: ClaimType
    namespace: Literal["world", "taste"]
    confidence: Literal["guess", "low", "medium", "high"]
    basis: str
    render_spec: dict[str, Json] | None = None
    seal_hash: str = ""
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


class TasteNote(BaseModel):
    """§1.7 — one row of the taste ledger.

    (The spec defines two classes called TasteNote: this one, the ledger
    row, and the aggregate kept on a vocabulary entry, which is
    :class:`EntryTasteNote` above.)
    """

    id: str
    at: str = Field(default_factory=now_utc)
    author: str
    status: Literal["active", "pending_ratification"] = "active"
    subject: dict
    artifact_ref: str
    verdict: Literal["keep", "reject", "keep_with_caveat"]
    reason_code: ReasonCode
    words: str | None = Field(default=None, max_length=48)
    tags: list[str] = Field(default_factory=list)
