"""The records of the cold-start seat (core-spec v2 §3.5, §1.9).

The spec's shared records — ``Actor``, ``AuditEvent``, ``Prediction``, the
closed reason codes and claim types, and the taste row — live in
:mod:`core.records` and :mod:`core.vocab.taste`, one definition each shared
with every seat; this module re-exports them so the seat's imports are
unchanged and the classes are the same objects the rest of the tree uses.

What stays here is the cold start's own:

    §3.5  SeedStarter, ColdOpen — the empty project's first screen
    §3.5  Chip, AskCandidate, AskQuestion, AskOutcome — ask-mode, two chips
          over two artifacts
    §1.9  ReferenceMember, PlantedDefect, CheckResult, ConfusionCounts,
          CalibrationRow — the calibration batch and its FP/FN table
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.records import (
    CLAIM_TYPES,
    REASON_CODES,
    Actor,
    AuditEvent,
    ClaimType,
    Prediction,
    ReasonCode,
)
from core.vocab.taste import TasteRow, TasteStatus, TasteVerdict, kept_verdicts

Json = Any

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
