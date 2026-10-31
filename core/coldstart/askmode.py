"""Ask-mode: a new builder starts by asking rather than guessing (spec §3.5; G §1 20:12).

The rules this service enforces — all of them structural, none of them prompt
instructions:

* **One question at a time**; a second question that arrives before the first
  is answered **collapses into the slate** as a card and is never queued in
  the owner's face. (The collapse writes no event: nothing was spoken. The
  slate itself is the night-runner seat's `Task` rows; the outcome carries
  the card.)
* **A question is a two-chip choice over two artifacts** — two crops, two
  materials on the same shed — never two adjectives floating free, and never
  a question about the owner (T: builders "express taste about artifacts,
  never about the owner" — a candidate *is* an artifact reference; there is
  no slot for anything else).
* **≤ 6 questions in the first session** (the 3–6 conversational beats per
  hour, spent at once because night one is short).
* **Any question is skippable, and a skip writes nothing** — not one row
  (G §1). The consequence, accepted deliberately: a skip is session-local
  state, invisible to the fold; after a rebuild the unanswered question is
  simply re-offered (or skipped again), and the counts that matter — what was
  spoken, what was answered — are all in the log.
* **Cold start *is* taste acquisition**: each answer writes one `taste_note`
  by the owner's own tap — `taste.note.appended`, actor `owner`, the
  three-writer rule enforced in code — with the reason code the question
  aggregates under and the exact artifact judged.
* **The melt decides what may still be asked**: a question is offered only on
  a reason code where the asking builder holds fewer than two observations
  (decision 13a) — asking is how the builder earns the observations that end
  the asking.

Every spoken question is a `line.spoken` audit event (the closed set's only
builder-utterance type; the line budget of §5.6 applies to it), so the
question budget is checkable from the ledger alone — gaps §7 test 2 is a fold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .gate import MELT_AT, ColdStartGate
from .models import Actor, AskCandidate, AskQuestion, AuditEvent, Chip, TasteRow
from .stubs import short_hash, taste_rows_from_events

__all__ = [
    "MAX_QUESTIONS_PER_SESSION",
    "AskSession",
    "AskRefusal",
    "Asked",
    "CollapsedToSlate",
    "BudgetExhausted",
    "NothingToAsk",
    "Skipped",
    "AskOutcome",
    "AskMode",
]

#: G §1 20:12 — the first session's question budget.
MAX_QUESTIONS_PER_SESSION = 6


@dataclass(frozen=True)
class AskSession:
    """One owner sitting (an evening). The budget is per session, across builders."""

    id: str
    started_at: str


class AskRefusal(Exception):
    """An ask-mode write refused. Closed reason codes."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Asked:
    """A question was spoken (one `line.spoken` event)."""

    question: AskQuestion


@dataclass(frozen=True)
class CollapsedToSlate:
    """A second question arrived before the first was answered.

    It collapses into the slate as a card — never queued in the owner's face.
    Nothing was spoken, so nothing is audited here; `card` is what the slate
    row needs.
    """

    open_question: AskQuestion
    card: AskCandidate


@dataclass(frozen=True)
class BudgetExhausted:
    """The session's ≤ 6 questions are spent; the ask was refused."""

    spoken: int


@dataclass(frozen=True)
class NothingToAsk:
    """Every candidate is either melted (two observations — decision 13a) or
    already asked this session. Asking is done; the builder may act."""

    melted: tuple[str, ...]


@dataclass(frozen=True)
class Skipped:
    """The open question was skipped. Nothing was written (G §1)."""

    question_id: str


AskOutcome = Asked | CollapsedToSlate | BudgetExhausted | NothingToAsk


class AskMode:
    """The ask-half of the cold start, over the ledger and the gate."""

    def __init__(
        self,
        *,
        ledger: Any,
        clock: Any,
        gate: ColdStartGate | None = None,
        author: str = "casey",
        max_questions: int = MAX_QUESTIONS_PER_SESSION,
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._gate = gate or ColdStartGate(ledger, author=author)
        self._author = author
        self._max_questions = max_questions
        self._open: dict[str, AskQuestion] = {}

    # -- sessions ---------------------------------------------------------------

    def begin_session(self) -> AskSession:
        """A session with no questions yet writes nothing — an empty sitting
        leaves no trace, which is the honest shape for a look around.

        The id folds in the ledger's head seq: on one store a sitting is
        distinguished by *when in the log* it starts, not only by the clock —
        two sittings at the same clock moment (a fixed test clock; also any
        clock that repeats) must never share a session id, or the second
        inherits the first's question budget from the shared `line.spoken`
        fold (found by the rewired acceptance run, branch m1-real)."""
        started_at = self._clock.now()
        return AskSession(
            id=f"cs_{short_hash({'started_at': started_at,
                                'after': self._ledger.head_seq()})}",
            started_at=started_at,
        )

    # -- asking -----------------------------------------------------------------

    def ask_next(self, session: AskSession, candidates: Sequence[AskCandidate]) -> AskOutcome:
        """Offer the first askable candidate, under every ask-mode rule.

        One at a time; ≤ 6 per session; only codes below the asking builder's
        two-observation gate; never the same question twice in a session.
        """
        open_question = self._open.get(session.id)
        if open_question is not None:
            if not candidates:
                return NothingToAsk(melted=())
            for candidate in candidates:
                if self._is_askable(session, candidate):
                    return CollapsedToSlate(open_question=open_question, card=candidate)
            return CollapsedToSlate(open_question=open_question, card=candidates[0])

        if self.spoken_count(session) >= self._max_questions:
            return BudgetExhausted(spoken=self.spoken_count(session))

        asked_prompts = self._asked_prompts(session)
        melted: list[str] = []
        for candidate in candidates:
            if candidate.prompt in asked_prompts:
                continue
            observed, _ = self._gate.observations(candidate.builder, candidate.reason_code)
            if observed >= MELT_AT:
                melted.append(candidate.reason_code)
                continue
            return Asked(self._speak(session, candidate))
        return NothingToAsk(melted=tuple(melted))

    def skip(self, session: AskSession, question_id: str) -> Skipped:
        """Skip the open question: it closes, and nothing is written."""
        open_question = self._open.get(session.id)
        if open_question is None or open_question.id != question_id:
            raise AskRefusal("question_not_open", f"{question_id} is not this session's open question")
        del self._open[session.id]
        return Skipped(question_id=question_id)

    # -- answering --------------------------------------------------------------

    def answer(
        self,
        session: AskSession,
        question_id: str,
        chip_id: str,
        *,
        actor: Actor,
    ) -> TasteRow:
        """One tap: the owner keeps one of the two artifacts, and the row is written.

        The taste ledger's single-writer rule is enforced here, in code: only
        an `owner` actor writes a `taste_note`, and the row's author is that
        owner (§1.7; T §"The taste ledger": the builder never holds the pen).
        """
        if actor.kind != "owner" or actor.id != self._author:
            raise AskRefusal(
                "not_the_owner",
                "a taste row is written by the owner's verdict and by nothing else",
            )
        question = self._open.get(session.id)
        if question is None or question.id != question_id:
            raise AskRefusal("question_not_open", f"{question_id} is not this session's open question")
        chip = next((c for c in question.chips if c.id == chip_id), None)
        if chip is None:
            raise AskRefusal("unknown_chip", f"{chip_id!r} is not one of the two choices")

        at = self._clock.now()
        row = TasteRow(
            id=f"tn_{short_hash({'q': question.id, 'chip': chip.id, 'at': at})}",
            at=at,
            author=self._author,
            status="active",
            subject={"param_path": question.subject_path, "value": chip.value},
            artifact_ref=chip.artifact_ref,
            verdict="keep",
            reason_code=question.reason_code,
            words=None,
            tags=(f"asked-by:{question.builder}", f"ask:{question.id}"),
        )
        self._ledger.append(
            _event(
                at=at,
                actor=actor,
                type="taste.note.appended",
                subject={"entity_kind": "taste_note", "entity_id": row.id},
                payload={"row": _row_payload(row)},
            )
        )
        del self._open[session.id]
        return row

    # -- the fold side ----------------------------------------------------------

    def spoken_count(self, session: AskSession) -> int:
        """Questions spoken in this session — a fold over `line.spoken`."""
        return len(self._asked_events(session))

    def rows_written(self, session: AskSession) -> list[TasteRow]:
        """The taste rows this session's answers wrote — a fold."""
        wanted = {q.id for q in self._asked_events(session)}
        return [
            row
            for row in taste_rows_from_events(self._ledger.events())
            if any(tag.startswith("ask:") and tag[4:] in wanted for tag in row.tags)
        ]

    # -- internals --------------------------------------------------------------

    def _is_askable(self, session: AskSession, candidate: AskCandidate) -> bool:
        if candidate.prompt in self._asked_prompts(session):
            return False
        observed, _ = self._gate.observations(candidate.builder, candidate.reason_code)
        return observed < MELT_AT

    def _speak(self, session: AskSession, candidate: AskCandidate) -> AskQuestion:
        at = self._clock.now()
        question = AskQuestion(
            id=f"q_{short_hash({'session': session.id, 'prompt': candidate.prompt, 'at': at})}",
            session=session.id,
            builder=candidate.builder,
            prompt=candidate.prompt,
            chips=candidate.chips,
            reason_code=candidate.reason_code,
            subject_path=candidate.subject_path,
            at=at,
            artifact_ref=candidate.artifact_ref,
        )
        self._ledger.append(
            _event(
                at=at,
                actor=Actor(kind="character", id=candidate.builder, via="ask"),
                type="line.spoken",
                subject={"entity_kind": "question", "entity_id": question.id},
                payload={
                    "kind": "coldstart.ask",
                    "session": session.id,
                    "question_id": question.id,
                    "builder": candidate.builder,
                    "prompt": candidate.prompt,
                    "reason_code": candidate.reason_code,
                    "subject_path": candidate.subject_path,
                    "artifact_ref": candidate.artifact_ref,
                    "chips": [
                        {
                            "id": chip.id,
                            "label": chip.label,
                            "artifact_ref": chip.artifact_ref,
                            "value": chip.value,
                        }
                        for chip in candidate.chips
                    ],
                },
            )
        )
        self._open[session.id] = question
        return question

    def _asked_events(self, session: AskSession) -> list[AskQuestion]:
        questions: list[AskQuestion] = []
        for event in self._ledger.events(types=["line.spoken"]):
            payload = event.payload or {}
            if payload.get("kind") != "coldstart.ask":
                continue
            if payload.get("session") != session.id:
                continue
            chips = tuple(
                Chip(
                    id=str(chip["id"]),
                    label=str(chip["label"]),
                    artifact_ref=str(chip["artifact_ref"]),
                    value=str(chip["value"]),
                )
                for chip in payload.get("chips", ())
            )
            questions.append(
                AskQuestion(
                    id=str(payload["question_id"]),
                    session=session.id,
                    builder=str(payload["builder"]),
                    prompt=str(payload["prompt"]),
                    chips=chips,
                    reason_code=str(payload["reason_code"]),
                    subject_path=str(payload.get("subject_path", "")),
                    at=event.at,
                    artifact_ref=str(payload.get("artifact_ref", "")),
                )
            )
        return questions

    def _asked_prompts(self, session: AskSession) -> set[str]:
        return {question.prompt for question in self._asked_events(session)}


def _event(
    *, at: str, actor: Actor, type: str, subject: dict, payload: dict
) -> AuditEvent:
    return AuditEvent(
        seq=0,  # the ledger assigns the sequence
        id=f"aud_{short_hash({'type': type, 'subject': subject, 'at': at})}",
        at=at,
        actor=actor,
        type=type,
        subject=subject,
        payload=payload,
    )


def _row_payload(row: TasteRow) -> dict:
    """The row exactly as it rides in `payload["row"]` — the merge contract
    with the `vocab` seat's `taste_rows_from_events`."""
    return {
        "id": row.id,
        "at": row.at,
        "author": row.author,
        "status": row.status,
        "subject": row.subject,
        "artifact_ref": row.artifact_ref,
        "verdict": row.verdict,
        "reason_code": row.reason_code,
        "words": row.words,
        "tags": list(row.tags),
    }
