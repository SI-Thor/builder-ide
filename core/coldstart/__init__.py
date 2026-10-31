"""Cold start: ask-mode, the melt, and the calibration batch.

Week 2 item 12 of `docs/plan.md`, against `docs/design/core-spec.md` (v2)
§3.5 and decision 13(a): cold start is **a mechanism, not a number of
nights** — questions and `guess` confidence decay per builder, per reason
code, at two observations, auditable in the ledger. The calibration batch's
first members grow nightly, sized to the unused lane, and publish the FP/FN
table's first row with `verdict@scripted` on its face.
"""

from .models import (
    DEFECT_KINDS,
    REASON_CODES,
    CLAIM_TYPES,
    AskCandidate,
    AskQuestion,
    AuditEvent,
    Actor,
    CalibrationRow,
    CheckResult,
    Chip,
    ColdOpen,
    ConfusionCounts,
    Prediction,
    ReferenceMember,
    SeedStarter,
    TasteRow,
)
from .ports import Clock, LedgerPort, SealerPort
from .stubs import (
    FixedClock,
    InMemoryLedger,
    PredictionSealer,
    Rail,
    SteppingClock,
    SystemClock,
    content_hash,
    taste_rows_from_events,
)

__all__ = [
    "REASON_CODES",
    "CLAIM_TYPES",
    "DEFECT_KINDS",
    "Actor",
    "AskCandidate",
    "AskQuestion",
    "AuditEvent",
    "CalibrationRow",
    "CheckResult",
    "Chip",
    "ColdOpen",
    "ConfusionCounts",
    "Prediction",
    "ReferenceMember",
    "SeedStarter",
    "TasteRow",
    "Clock",
    "LedgerPort",
    "SealerPort",
    "FixedClock",
    "InMemoryLedger",
    "PredictionSealer",
    "Rail",
    "SteppingClock",
    "SystemClock",
    "content_hash",
    "taste_rows_from_events",
]
