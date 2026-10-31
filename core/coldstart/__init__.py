"""Cold start: ask-mode, the melt, and the calibration batch.

Week 2 item 12 of `docs/plan.md`, against `docs/design/core-spec.md` (v2)
§3.5 and decision 13(a): cold start is **a mechanism, not a number of
nights** — questions and `guess` confidence decay per builder, per reason
code, at two observations, auditable in the ledger. The calibration batch's
first members grow nightly, sized to the unused lane, and publish the FP/FN
table's first row with `verdict@scripted` on its face.

Layout:

```
core/coldstart/
  models.py        the spec's records + this seat's own (questions, members, tables)
  ports.py         the seams: LedgerPort (core-api), SealerPort (vocab), Clock
  stubs.py         in-memory stand-ins for the sibling seats, each headed by its owner
  openline.py      §3.5 the empty project's first screen (gaps §7 test 1)
  askmode.py       §3.5 ask-mode: one question at a time, ≤ 6, skip writes nothing
  gate.py          decision 13a: ask→act and guess→claim at two observations, per builder
  sealing.py       the melt's seal policy: the confidence is computed, never chosen
  claims.py        the utterance gate: a claim below two observations does not render
  bank.py          the night-one question bank (eight two-chip questions)
  calibration.py   §1.9 the seeded-defect reference set, nightly growth, FP/FN table
```
"""

from .askmode import AskMode, AskRefusal, AskSession, AskOutcome
from .bank import night_one_bank
from .claims import ClaimLine, render_taste_claim
from .gate import MELT_AT, ColdDecision, ColdStartGate
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
from .openline import FOUR_STARTERS, companion_opening, opening_line
from .ports import Clock, LedgerPort, SealerPort
from .sealing import ColdStartSealer, SealPolicyRefusal
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
    # ask-mode and the melt
    "AskMode",
    "AskRefusal",
    "AskSession",
    "AskOutcome",
    "AskCandidate",
    "AskQuestion",
    "Chip",
    "night_one_bank",
    "MELT_AT",
    "ColdDecision",
    "ColdStartGate",
    "ColdStartSealer",
    "SealPolicyRefusal",
    "ClaimLine",
    "render_taste_claim",
    # the first screen
    "FOUR_STARTERS",
    "ColdOpen",
    "SeedStarter",
    "companion_opening",
    "opening_line",
    "CalibrationRow",
    "ConfusionCounts",
    "CheckResult",
    "ReferenceMember",
    "DEFECT_KINDS",
    # the records and the seams
    "REASON_CODES",
    "CLAIM_TYPES",
    "Actor",
    "AuditEvent",
    "Prediction",
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
