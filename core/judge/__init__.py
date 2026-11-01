"""The judgment seam — one interface, three real backends, a fake (B2).

    from core.judge import Judge, Question
    from core.judge.backends import D1Backend
    from core.night.ledger import InMemoryLedger

    judge = Judge(
        D1Backend(port=8295, model="d1-2B"),
        ledger=ledger,                       # every judgment becomes a row
    )
    answer = judge.judge(
        "tiles.shortlist",
        state="Scene context: phase=dusk, wanted_style=weathered.",
        questions=(
            Question(
                qid="tile", kind="choice",
                instructions="Which tile should be played next?",
                criteria={tile.id: tile.title for tile in shortlist},
            ),
        ),
    )
    if answer.surfaced:
        ...  # below τ at the ladder's end: recorded, not acted on

The seam the research named (jev.md's "next" §1; liquid-study Part 3
item 1): typed judgments — ``choice``, ``score``, ``noul``, ``verify``
— over one shared state, on the backend the caller configures, under
the confidence gate that E1 measured (act at or above τ, escalate
below, surface at the ladder's end), every attempt recorded in the
ledger with its author, distribution, cost and latency.
"""

from __future__ import annotations

from .backends import (
    BackendReply,
    ClefBackend,
    D1Backend,
    FakeBackend,
    JevBackend,
    JudgeBackend,
    JudgeRefusal,
)
from .events import JUDGE_EVENT_TYPE, JUDGE_EVENT_TYPES
from .gate import (
    DEFAULT_BAND,
    DEFAULT_DWELL_DOWN,
    DEFAULT_DWELL_UP,
    DEFAULT_TAU,
    ConfidencePolicy,
    EscalationLadder,
    StandingConfig,
    StandingGate,
)
from .judge import Judge, JudgeAnswer, fold_judgments, plan_pack, verdict_payload_estimate
from .models import (
    GateDecision,
    JudgeCost,
    Judgment,
    Question,
    QuestionKind,
    judgment_from_distribution,
    question_set_hash,
    state_hash,
)
from .shortlist import JudgePriorChooser

__all__ = [
    # the service
    "Judge",
    "JudgeAnswer",
    "fold_judgments",
    "plan_pack",
    "verdict_payload_estimate",
    # the questions and their answers
    "Question",
    "QuestionKind",
    "Judgment",
    "JudgeCost",
    "GateDecision",
    "judgment_from_distribution",
    "question_set_hash",
    "state_hash",
    # the gate as policy
    "DEFAULT_TAU",
    "DEFAULT_BAND",
    "DEFAULT_DWELL_UP",
    "DEFAULT_DWELL_DOWN",
    "StandingConfig",
    "ConfidencePolicy",
    "EscalationLadder",
    "StandingGate",
    # the backends
    "JudgeBackend",
    "BackendReply",
    "JudgeRefusal",
    "FakeBackend",
    "D1Backend",
    "JevBackend",
    "ClefBackend",
    # the first caller
    "JudgePriorChooser",
    # the audit type
    "JUDGE_EVENT_TYPE",
    "JUDGE_EVENT_TYPES",
]
