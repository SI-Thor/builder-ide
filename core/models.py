"""Pydantic models straight from core-spec v2 §1 (schemas) and §2.1.

One naming deviation forced by the spec itself: it defines two classes
called TasteNote — the aggregated note inside a VocabularyEntry (§1.5) and
the taste-ledger record (§1.7). The ledger one keeps the name; the
vocabulary one is VocabTasteNote.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .canon import now_utc
from .events import Actor
from .records import (
    CHECKABLE_KINDS,
    CLAIM_TYPES,
    CONFIDENCE_LEVELS,
    REASON_CODES,
    AcceptanceCheck,
    ActorKind,
    AuditEvent,
    Branch,
    BranchPurpose,
    ClaimType,
    Constraint,
    ConstraintKind,
    EDIT_AUTHOR_KINDS,
    EnginePin,
    EntryKind,
    EntryTasteNote,
    GeneratorRef,
    IterationPolicy,
    Job,
    JobState,
    NodeRef,
    Night,
    NightState,
    NightStatus,
    Op,
    Prediction,
    Recipe,
    RecipeEdit,
    RecipeEntry,
    RecipeVersion,
    ReasonCode,
    Rail,
    Task,
    TaskState,
    TasteNote,
    VocabularyEntry,
)

#: §1.5's entry-embedded aggregate. The spec defines two classes called
#: TasteNote — this one (inside a VocabularyEntry) and the taste-ledger row
#: (§1.7, :class:`TasteNote` above). The vocabulary seat's copy of the
#: entry-embedded one was the same record, so it is one class under the
#: spec's two names.
VocabTasteNote = EntryTasteNote

class Budget(BaseModel):
    per_cycle: Rail = Rail()
    per_attempt: Rail = Rail()
    per_order: Rail = Rail()
    night: str | None = None


class Estimate(BaseModel):
    build_verify: Rail
    generate_test: Rail
    basis: Literal["measured", "estimate"] = "estimate"


class Evidence(BaseModel):
    kind: Literal["commit", "code_diff", "recipe_diff", "render", "critic_verdict",
                  "test_run", "constraint_run", "geometry_run", "timing", "budget_spend",
                  "licence_scan", "log"]
    ref: str
    sha256: str
    summary: str = Field(max_length=80)


class Attempt(BaseModel):
    n: int  # 1.., monotonic; ids never reused (§5.3)
    engineer: str
    state: Literal["running", "delivered", "gate_failed", "failed", "cancelled"] = "running"
    seat: str
    started_at: str = Field(default_factory=now_utc)
    ended_at: str | None = None
    outcome: str | None = None


class Deliverable(BaseModel):
    attempt: str
    commit: dict
    recipe_edit: str | None = None
    code_diff: dict
    evidence: list[Evidence]
    vocab_proposal: dict | None = None
    notes: str = ""


class Origin(BaseModel):
    channel: Literal["voice", "text", "chip", "character", "panel"]
    packet: str
    utterance: str | None = None  # owner only; kid actors cannot set it (§4.1)
    character_line: str | None = None


WoState = Literal[
    "compiling", "questioned", "draft", "queued", "building", "testing", "landed",
    "kept", "rejected", "parked", "failed", "cancelled",
]


class WorkOrder(BaseModel):
    id: str
    at: str = Field(default_factory=now_utc)
    filed_by: Actor
    origin: Origin
    title: str
    goal: str = ""
    targets: list[str] = []
    vocabulary_gap: dict | None = None
    acceptance: list[AcceptanceCheck] = []
    budget: Budget = Budget()
    estimate: Estimate | None = None
    confirm_line: str = ""
    state: WoState = "compiling"
    # The task id of the plan goal this order is for. The spec relates an
    # order to the plan only through its context packet (origin.packet);
    # justification needs the direct link to answer "who or what does this
    # order serve". See INTEGRATION.md, decision 2.
    serves: str | None = None
    attempts: list[Attempt] = []
    evidence: list[Evidence] = []
    promote: dict | None = None
    branch: str | None = None
    # fold-maintained extras carried by events along the lifecycle
    question: str | None = None
    candidates: list[dict] | None = None
    answered_questions: list[str] = []
    confirmed_by: str | None = None
    cancelled_by: str | None = None
    park_reason: str | None = None
    resumed_by: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    last_deliverable: dict | None = None
    last_gate: dict | None = None
    preview: dict | None = None
    promotion: dict | None = None
    kept_branch: str | None = None
    spend_so_far: dict | None = None


MAX_CONFIRM_WORDS = 25


def confirm_spec_sentence(confirm_line: str) -> str:
    """The spec sentence is everything up to the two-line price; a one-line
    estimate is a build failure (§3.1), so the split marker is load-bearing."""
    for marker in ("build/verify:", "build/verify —"):
        if marker in confirm_line:
            return confirm_line.split(marker)[0].strip()
    return confirm_line.strip()


def confirm_line_valid(confirm_line: str, estimate: Estimate | None) -> bool:
    if estimate is None:
        return False
    sentence = confirm_spec_sentence(confirm_line)
    if not (0 < len(sentence.split()) <= MAX_CONFIRM_WORDS):
        return False
    # both price lines must be present and non-zero-shaped
    has_build = "build/verify:" in confirm_line or "build/verify —" in confirm_line
    has_gen = "generate/test:" in confirm_line or "generate/test —" in confirm_line
    return has_build and has_gen


# ------------------------------------------------------------------ §1.7 ledgers



def prediction_seal_hash(p: Prediction | dict) -> str:
    """sha256 over canonical {builder, at, branch_ref, claim, claim_type,
    confidence, basis, render_spec} — written before the render job exists.

    Takes a sealed record or the raw fields it will be built from: the
    record is frozen (§1.7), so the hash is computed *before* the record
    exists rather than patched onto it afterwards.
    """
    from .canon import content_hash

    def field(name: str):
        return p[name] if isinstance(p, dict) else getattr(p, name)

    return content_hash({
        "builder": field("builder"), "at": field("at"),
        "branch_ref": field("branch_ref"), "claim": field("claim"),
        "claim_type": field("claim_type"), "confidence": field("confidence"),
        "basis": field("basis"), "render_spec": field("render_spec"),
    })


# ------------------------------------------------------------------ §1.4 packet

class Gaze(BaseModel):
    ray: dict
    hits: list[dict] = []


class ConvLabel(BaseModel):
    who: str
    label: str


class History(BaseModel):
    recipe_changes: list[dict] = []
    renders: list[str] = []
    critic_notes: list[dict] = []
    work_orders_open: list[dict] = []
    landed_work_orders: list[dict] = []


class ProjectState(BaseModel):
    branch: str = ""
    head: str = ""
    budget_left_tonight: Rail = Rail()
    vocabulary_gaps: list[str] = []
    engine_pin: dict = {}
    world_time: str = ""


class View(BaseModel):
    selection: list[str] = []
    referents: list[NodeRef] = []
    params: dict[str, dict] = {}
    gaze: Gaze | None = None
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    region: str | None = None


class ContextPacket(BaseModel):
    id: str
    at: str = Field(default_factory=now_utc)
    actor: str
    view: View = View()
    history: History = History()
    conversation: list[ConvLabel] = []
    project: ProjectState = ProjectState()


PACKET_MAX_BYTES = 16 * 1024

# §1.4.1 bounds: (field path, cap, overflow behaviour)
PACKET_BOUNDS = {
    "view.selection": 32,
    "view.referents": 32,
    "view.params.entries": 8,
    "view.params.bytes": 2048,
    "view.gaze.hits": 5,
    "history.recipe_changes": 10,
    "history.renders": 3,
    "history.critic_notes": 5,
    "history.work_orders_open": 8,
    "history.landed_work_orders": 3,
    "conversation": 12,
    "project.vocabulary_gaps": 8,
}


def enforce_packet_bounds(p: ContextPacket) -> ContextPacket:
    """Hard caps at capture; on overflow drop in the order given, never view
    or project; whole packet over 16 KiB → drop history, then conversation,
    then fail loud (§1.4.1)."""
    p.view.selection = p.view.selection[:32]
    p.view.referents = p.view.referents[:32]
    if p.view.gaze:
        hits = sorted(p.view.gaze.hits, key=lambda h: h.get("dist", 1e9))[:5]
        p.view.gaze.hits = hits
    p.history.recipe_changes = p.history.recipe_changes[-10:]
    p.history.renders = p.history.renders[-3:]
    p.history.critic_notes = p.history.critic_notes[-5:]
    p.history.work_orders_open = p.history.work_orders_open[-8:]
    p.history.landed_work_orders = p.history.landed_work_orders[-3:]
    p.conversation = p.conversation[-12:]
    p.project.vocabulary_gaps = p.project.vocabulary_gaps[:8]
    # params: ≤ 8 entries / 2 KiB, largest entries first out
    from .canon import canonical_bytes

    def entry_size(item: tuple[str, dict]) -> int:
        return len(canonical_bytes({item[0]: item[1]}))

    entries = sorted(p.view.params.items(), key=entry_size)  # smallest first
    while len(entries) > 8:
        entries.pop()  # drop largest
    while entries and sum(entry_size(e) for e in entries) > 2048:
        entries.pop()
    p.view.params = dict(entries)

    from .errors import Overflow

    def packet_bytes() -> int:
        return len(canonical_bytes(p.model_dump(mode="json")))

    if packet_bytes() > PACKET_MAX_BYTES:
        p.history = History()
    if packet_bytes() > PACKET_MAX_BYTES:
        p.conversation = []
    if packet_bytes() > PACKET_MAX_BYTES:
        raise Overflow("context packet exceeds 16 KiB after drop order (§1.4.1)")
    return p


# ------------------------------------------------------------------ §1.9 night/task

class Question(BaseModel):
    id: str
    name: str
    branch: str | None = None
    options: list[str] = Field(min_length=2, max_length=2)
    wo: str | None = None
    blocking: bool = True
    asked_by: Actor
    answer: str | None = None
    answered_at: str | None = None
    assumption: dict | None = None


# ------------------------------------------------------------------ §1.6 assets

class FileRef(BaseModel):
    role: str
    path: str
    sha256: str
    bytes: int


class Licence(BaseModel):
    spdx: str
    dependency_terms: list[str] = []
    commercial_ok: bool
    checked_at: str = Field(default_factory=now_utc)
    checked_by: str = "core-licence-registry"
    notes: str | None = None


class Provenance(BaseModel):
    source: Literal["generated", "library", "cad_script", "import"]
    generator: dict | None = None


class Asset(BaseModel):
    id: str
    kind: Literal["mesh", "texture", "material", "cad_part", "motion_clip", "audio"]
    files: list[FileRef]
    provenance: Provenance
    licence: Licence
    critic: dict | None = None
