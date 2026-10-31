"""The Judge: one seam for typed judgments, every verdict recorded.

`docs/research/jev.md` named it: *a small adapter in the core
(``core/judge/``): Jev behind one interface with a fake for tests.
Every judgment is recorded in the ledger with its distribution and
cost.* The liquid study (Part 3, item 1) widened it to the three real
backends — the local d1 the box measured, the cloud Jev, the cloud
Clef — and supplied the policy (E1's τ) and the first caller (the tiles
shortlist).

The contract, in order:

1. **one call asks a pack** — a question set over one shared state,
   because §4.1 measured the per-question saving of the shared prefix;
2. **the confidence gate is policy** — act at or above τ, escalate
   below, walking the configured ladder rung by rung, escalating only
   the questions that fell short (a confident answer is not re-asked of
   a dearer backend);
3. **every attempt is a row** — ``judge.verdict``, with the author
   (``judge@<backend>:<model>``), the distribution, the cost, the
   latency, the question set's hash and the pack's hash. Refused
   attempts and escalated-away-from attempts are rows too;
4. **below τ at the ladder's end is surfaced, not acted on** — the
   answer comes back flagged, and the row says so.

The Judge never acts. It returns verdicts and the gate's decision;
what acts on them is the caller's.
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, ConfigDict

from core.canon import now_utc
from core.records import Actor

from .backends import BackendReply, FakeBackend, JudgeBackend, JudgeRefusal
from .events import JUDGE_EVENT_TYPE
from .gate import ConfidencePolicy, EscalationLadder
from .models import JudgeCost, Judgment, Question, judgment_from_distribution, question_set_hash, state_hash
from .ports import LedgerPort

__all__ = ["Judge", "JudgeAnswer", "fold_judgments"]


class JudgeAnswer(BaseModel):
    """What one ask returned: the governing judgments, and the bill.

    ``judgments`` is one per question asked, in pack order — the
    judgment that governs each question (the first rung whose
    confidence cleared τ, or the last rung's when the ladder was
    exhausted). The authors are on the judgments.
    """

    model_config = ConfigDict(frozen=True)

    task: str
    state_hash: str
    questions_hash: str
    judgments: tuple[Judgment, ...]
    attempts: int
    surfaced: bool
    cost: JudgeCost
    latency_seconds: float

    @property
    def authors(self) -> tuple[str, ...]:
        """The governing judgments' authors, in pack order."""
        return tuple(judgment.author for judgment in self.judgments)

    def judgment(self, qid: str) -> Judgment:
        """The governing judgment for one question id."""
        for judgment in self.judgments:
            if judgment.qid == qid:
                return judgment
        raise KeyError(qid)


class Judge:
    """The seam. The backend is a parameter with a default (the fake)."""

    def __init__(
        self,
        backend: JudgeBackend | None = None,
        *,
        ladder: EscalationLadder | None = None,
        policy: ConfidencePolicy | None = None,
        ledger: LedgerPort,
        clock=now_utc,
    ) -> None:
        rungs: list[tuple[str, JudgeBackend]] = []
        if backend is not None:
            rungs.append((backend.name, backend))
            if ladder is not None:
                rungs.extend(ladder.rungs)
        elif ladder is not None:
            rungs.extend(ladder.rungs)
        else:
            rungs.append((FakeBackend().name, FakeBackend()))
        self.rungs = tuple(rungs)
        self.policy = policy or ConfidencePolicy()
        self.ledger = ledger
        self._clock = clock

    # -- the ask ---------------------------------------------------------------

    def judge(
        self,
        task: str,
        state: str,
        questions: Sequence[Question],
        *,
        at: str | None = None,
    ) -> JudgeAnswer:
        """Ask one pack over one state, under the confidence policy.

        Escalation is per question and the wire is the pack: each rung
        is asked only the questions the previous rung fell short on,
        over the same shared state.
        """
        pack = tuple(questions)
        if not pack:
            raise ValueError("a question pack is not empty")
        moment = at or self._clock()
        pack_hash = question_set_hash(pack)
        s_hash = state_hash(state)

        governing: dict[str, Judgment] = {}
        pending = pack
        prev_backend: str | None = None
        attempts = 0
        total = JudgeCost(wall_seconds=0.0)

        for index, (name, backend) in enumerate(self.rungs):
            if not pending:
                break
            tau = self.policy.tau_for(backend.name, backend.model, task)
            try:
                reply = backend.ask(state, pending)
            except JudgeRefusal as refusal:
                self._record(
                    task=task,
                    state_hash=s_hash,
                    pack_hash=pack_hash,
                    questions=pending,
                    backend=backend,
                    tau=tau,
                    judgments=(),
                    reply=None,
                    escalated_from=prev_backend,
                    refusal=refusal,
                    at=moment,
                )
                prev_backend = name
                continue

            judged = {
                question.qid: judgment_from_distribution(
                    question=question,
                    backend=backend.name,
                    model=backend.model,
                    distribution=reply.distributions.get(question.qid, {}),
                    confidence=reply.confidences.get(question.qid),
                ).model_copy(update={"tau": tau})
                for question in pending
            }
            act: list[Judgment] = []
            still_pending: list[Question] = []
            for question in pending:
                judgment = judged[question.qid]
                if self.policy.decision(confidence=judgment.confidence, tau=tau) == "act":
                    act.append(judgment)
                    governing[question.qid] = judgment
                elif index + 1 < len(self.rungs):
                    still_pending.append(question)
                else:
                    act.append(judgment)
                    governing[question.qid] = judgment  # surfaced
            escalated_qids = {question.qid for question in still_pending}

            row_judgments = tuple(
                judged[question.qid].model_copy(
                    update={"escalated": question.qid in escalated_qids}
                )
                for question in pending
            )
            cost = backend.cost_of(reply)
            self._record(
                task=task,
                state_hash=s_hash,
                pack_hash=pack_hash,
                questions=pending,
                backend=backend,
                tau=tau,
                judgments=row_judgments,
                reply=reply,
                escalated_from=prev_backend,
                refusal=None,
                at=moment,
            )
            total = total.added(cost)
            attempts += 1
            prev_backend = name
            pending = tuple(still_pending)

        if len(governing) != len(pack):
            raise JudgeRefusal(
                "no_backend",
                "every backend this ladder names failed for this pack; "
                "the refusals are on the log",
            )
        ordered = tuple(governing[question.qid] for question in pack)
        return JudgeAnswer(
            task=task,
            state_hash=s_hash,
            questions_hash=pack_hash,
            judgments=ordered,
            attempts=attempts,
            surfaced=any(judgment.gate == "surfaced" for judgment in ordered),
            cost=total,
            latency_seconds=total.wall_seconds,
        )

    # -- the record ------------------------------------------------------------

    def _record(
        self,
        *,
        task: str,
        state_hash: str,
        pack_hash: str,
        questions: Sequence[Question],
        backend: JudgeBackend,
        tau: float,
        judgments: tuple[Judgment, ...],
        reply: BackendReply | None,
        escalated_from: str | None,
        refusal: JudgeRefusal | None,
        at: str,
    ) -> None:
        """One ``judge.verdict`` row per attempt — refused attempts included."""
        payload: dict[str, object] = {
            "task": task,
            "state_hash": state_hash,
            "pack_hash": pack_hash,
            "questions_hash": question_set_hash(questions),
            "backend": backend.name,
            "model": backend.model,
            "author": f"judge@{backend.name}:{backend.model}",
            "n_questions": len(questions),
            # the gate decision is derived (confidence, τ, escalated), but the
            # row carries it anyway: a log that needs a computation to say
            # what was acted on is a log that lies by omission
            "judgments": [
                {**judgment.model_dump(), "gate": judgment.gate}
                for judgment in judgments
            ],
            "latency_seconds": reply.wall_seconds if reply else 0.0,
            "cost": (
                backend.cost_of(reply).model_dump()
                if reply
                else JudgeCost(wall_seconds=0.0).model_dump()
            ),
            "escalated_from": escalated_from,
            "refused": refusal is not None,
            "tau": tau,
        }
        if refusal is not None:
            payload["error"] = {"code": refusal.code, "detail": refusal.detail}
        try:
            self.ledger.append(
                type=JUDGE_EVENT_TYPE,
                actor=Actor(kind="core", id=payload["author"], via="judge"),  # type: ignore[arg-type]
                subject={"entity_kind": "judgment", "entity_id": str(payload["questions_hash"])},
                payload=payload,  # type: ignore[arg-type]
                at=at,
            )
        except ValueError as error:
            raise JudgeRefusal(
                "payload_too_large",
                f"this pack's verdict cannot fit the ledger's payload cap: {error}",
            ) from error


# --- the fold -----------------------------------------------------------------


def fold_judgments(events, *, backend: str | None = None) -> list[dict]:
    """The recorded judgments, folded back out of the log.

    One entry **per judgment** — the unit the brief names — with its
    attempt's context flattened on (author, cost, latency, hashes, the
    rung it was escalated from). A **refused attempt** is its own
    judgment-less entry, because the edges are the story and a refusal
    is an edge. ``entry["judgment"]`` is the :class:`Judgment`;
    ``entry["distribution"]`` and ``entry["gate"]`` are conveniences.
    """
    from .models import Judgment

    entries: list[dict] = []
    for event in events:
        if getattr(event, "type", None) != JUDGE_EVENT_TYPE:
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        if backend is not None and payload.get("backend") != backend:
            continue
        attempt = tuple(Judgment.model_validate(raw) for raw in payload.get("judgments", []))
        for judgment in attempt:
            entry = dict(payload)
            entry["judgment"] = judgment
            entry["qid"] = judgment.qid
            entry["distribution"] = judgment.distribution
            entry["gate"] = judgment.gate
            entry["escalated"] = judgment.escalated
            entry["seq"] = getattr(event, "seq", None)
            entry["at"] = getattr(event, "at", "")
            entry["attempt_judgments"] = attempt
            entries.append(entry)
        if not attempt:
            entry = dict(payload)
            entry["judgment"] = None
            entry["qid"] = None
            entry["distribution"] = None
            entry["gate"] = None
            entry["escalated"] = False
            entry["seq"] = getattr(event, "seq", None)
            entry["at"] = getattr(event, "at", "")
            entry["attempt_judgments"] = ()
            entries.append(entry)
    return entries
