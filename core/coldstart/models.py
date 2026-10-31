"""The records of the cold-start seat, shaped exactly as `docs/design/core-spec.md` (v2) says.

The citations in each docstring are the contract. If the spec changes, these
change with it; nothing here is invented.

    §1.7  Prediction, ReasonCode, TasteRow (the ledger row, not the entry aggregate)
    §1.8  AuditEvent, Actor

`Actor`, `AuditEvent`, `Prediction` and the closed code sets are field-for-field
the `vocab` seat's records (branch `vocab`, `core/vocab/models.py`): that seat is
done and this one builds on its gate and sealed predictions, so the two must
agree on the one shape that crosses the merge — **the audit event payload**.
Everything the panels and the folds read is a payload in the one log, and that
is the compatibility contract (see `stubs.py` and the README's stub table).

The cold-start records below are this seat's own:

    §3.5  SeedStarter, ColdOpen — the empty project's first screen
    §3.5  Chip, AskCandidate, AskQuestion, AskOutcome — ask-mode, two chips
          over two artifacts
    §1.9  ReferenceMember, PlantedDefect, CheckResult, ConfusionCounts,
          CalibrationRow — the calibration batch and its FP/FN table
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Actor",
    "AuditEvent",
    "ReasonCode",
    "REASON_CODES",
    "ClaimType",
    "CLAIM_TYPES",
    "Prediction",
    "TasteRow",
    "TasteVerdict",
    "TasteStatus",
    "kept_verdicts",
    "SeedStarter",
    "ColdOpen",
    "Chip",
    "AskCandidate",
    "AskQuestion",
    "DefectKind",
    "DEFECT_KINDS",
    "ReferenceMember",
    "CheckName",
    "CHECK_NAMES",
    "CheckResult",
    "ConfusionCounts",
    "CalibrationRow",
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

#: §1.1 — `RecipeEdit.author` is `{kind, id, via}`; §1.8 adds the audit-only kinds.
ActorKind = Literal[
    "owner", "character", "engineer", "critic", "core", "scheduler", "client"
]


class Actor(BaseModel):
    """§1.1 / §1.8 — who did it, and through which door."""

    model_config = ConfigDict(frozen=True)

    kind: ActorKind
    id: str
    via: str | None = None


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


class Prediction(BaseModel):
    """§1.7 — a bet, sealed before the render that could disprove it.

    Frozen: a sealed record cannot be edited. Only `verdict` is written later,
    by somebody other than the builder (never self-scored).
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


TasteVerdict = Literal["keep", "reject", "keep_with_caveat"]
TasteStatus = Literal["active", "pending_ratification"]

#: A "keep with caveat" is a keep that carries a condition; it counts as kept.
kept_verdicts: frozenset[str] = frozenset({"keep", "keep_with_caveat"})


@dataclass(frozen=True)
class TasteRow:
    """One row of the taste ledger — a judgement about an artifact, not a feeling.

    §1.7 / T §"Taste note fields". Written by the owner's verdict event and by
    nothing else; builders read and cite, they never write. Author-scoped:
    Casey's rows and Magnus's rows never mix, and Magnus's `pending_ratification`
    rows are inert (excluded from every slice a builder reads).

    This is the row exactly as it rides inside a `taste.note.appended` payload
    (`payload["row"]`) — the fold in `stubs.taste_rows_from_events` reads it
    back out, and the `vocab` seat's identical fold must keep reading it.
    """

    id: str
    at: str
    author: str
    status: TasteStatus
    subject: dict[str, Any]
    artifact_ref: str
    verdict: TasteVerdict
    reason_code: str
    words: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def param_path(self) -> str | None:
        path = self.subject.get("param_path")
        return path if isinstance(path, str) else None

    @property
    def kept(self) -> bool:
        return self.verdict in kept_verdicts


# ---------------------------------------------------------------------------
# §3.5 — the empty project's first screen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedStarter:
    """§3.5 — a starter chip: **a seed, not a guess**, with the seed on its face.

    Provenance from the first tap, because the technology already requires it
    of every artifact, so it is free.
    """

    name: str
    seed: int

    @property
    def label(self) -> str:
        """What the chip shows: `harbor hamlet · seed 4471`."""
        return f"{self.name} · seed {self.seed}"


@dataclass(frozen=True)
class ColdOpen:
    """§3.5 — the first screen: one line over an empty store, four starters.

    The line is computed from ledger counts and nothing else — the builder of
    the line takes counts, not descriptions, so there is no parameter through
    which an adjective about the owner could enter (the property gaps §7
    test 1 asserts, made structural).
    """

    line: str
    starters: tuple[SeedStarter, ...]
    taste_rows: int
    kept: int


# ---------------------------------------------------------------------------
# §3.5 — ask-mode: a two-chip choice over two artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chip:
    """One of a question's two choices — a crop/material/silhouette, never an
    adjective floating free (G §1 20:12)."""

    id: str
    label: str
    artifact_ref: str
    value: str


@dataclass(frozen=True)
class AskCandidate:
    """A question the caller offers to ask.

    Ask-mode is a policy, not a content generator: the Companion supplies the
    bank (prompt, the two chips, the reason code the answer aggregates under),
    and the service decides *whether* a question may be asked at all — one at
    a time, ≤ 6 per session, only on reason codes still below that builder's
    two-observation gate (§3.5; decision 13a).
    """

    prompt: str
    chips: tuple[Chip, Chip]
    reason_code: ReasonCode
    subject_path: str
    artifact_ref: str
    """The thing the question judges — both chips are crops of it (G §1 20:12)."""
    builder: str = "companion"


@dataclass(frozen=True)
class AskQuestion:
    """A question actually asked — one at a time, over two artifacts."""

    id: str
    session: str
    builder: str
    prompt: str
    chips: tuple[Chip, Chip]
    reason_code: str
    subject_path: str
    at: str
    artifact_ref: str
    """The exact thing the question judges (both chips are crops of it)."""


# ---------------------------------------------------------------------------
# §1.9 — the calibration batch
# ---------------------------------------------------------------------------

#: The spec's three seeded defect classes (§1.9 critic calibration: "hollow
#: meshes, wrong scale, broken constraints"); a member with `defect=None` is
#: clean — the set needs clean members or there is nothing to false-positive on.
DefectKind = Literal["hollow_mesh", "wrong_scale", "broken_constraint"]

DEFECT_KINDS: tuple[str, ...] = ("hollow_mesh", "wrong_scale", "broken_constraint")

CheckName = Literal["watertight", "scale_bounds", "constraint"]

CHECK_NAMES: tuple[str, ...] = ("watertight", "scale_bounds", "constraint")

#: Which check targets which defect class — the reference set's ground truth.
DEFECT_TARGETS: dict[str, str] = {
    "hollow_mesh": "watertight",
    "wrong_scale": "scale_bounds",
    "broken_constraint": "constraint",
}


class ReferenceMember(BaseModel):
    """One member of the seeded-defect reference set (§1.9; RV patch 15).

    A member is a **recipe fragment with a known, planted defect** (or a clean
    one): a small typed param set the scripted checks read analytically. The
    renders the spec's registry entry eventually carries are compiled from
    these; until the engine lands the params *are* the member, and the checks
    stay deterministic (§2.3: scripted analytic computations, no physics
    engine, no "sim").

    `detectable` is the ground-truth flag the FP/FN table needs: a planted
    defect the targeted check **should** fire on. The generator plants defects
    beyond the checks' thresholds by default; a member planted just inside
    them (`detectable=False`) is a severity-graded member whose miss is an
    honest FN, not a surprise.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    index: int
    defect: DefectKind | None
    detectable: bool = True
    entry_path: str = "props.harbor.crates"
    params: dict[str, Json]
    seed: int
    night: str | None = None

    @property
    def clean(self) -> bool:
        return self.defect is None


@dataclass(frozen=True)
class CheckResult:
    """One scripted check's outcome on one member."""

    check: CheckName
    fired: bool
    detail: str


@dataclass(frozen=True)
class ConfusionCounts:
    """One check's confusion over the reference set — counts, never percentages.

    TP: the check fired on a member carrying the defect it targets.
    FP: the check fired on a clean member ("reject no more than a set fraction
        of the clean ones" — the band's other half).
    FN: a planted defect of the targeted class the check did not fire on —
        including a defect planted deliberately below the threshold, because
        a seeded defect is a seeded defect and the table must not hide a miss.
    TN: a clean member the check left alone.
    """

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def fp_rate(self) -> float | None:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else None

    @property
    def fn_rate(self) -> float | None:
        return self.fn / (self.fn + self.tp) if (self.fn + self.tp) else None


@dataclass(frozen=True)
class CalibrationRow:
    """One published row of the FP/FN table: one night × one check.

    `verdict@scripted` is on the row's face because until a critic model is
    chosen and measured, the row describes the scripted checks (§3.5; RV
    patch 15) — the first row is the baseline the critic selection later has
    to beat.
    """

    night: str
    check: CheckName
    counts: ConfusionCounts
    label: str = "verdict@scripted"
