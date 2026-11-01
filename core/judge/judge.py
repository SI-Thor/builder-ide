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

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.canon import now_utc
from core.records import Actor

from .backends import BackendReply, FakeBackend, JudgeBackend, JudgeRefusal
from .calibration import CANONICAL_CONFIDENCE, CalibrationScale, ConfidenceDefinition
from .events import JUDGE_EVENT_TYPE
from .gate import ConfidencePolicy, EscalationLadder, StandingGate
from .models import JudgeCost, Judgment, Question, judgment_from_distribution, question_set_hash, state_hash
from .ports import LedgerPort

__all__ = ["Judge", "JudgeAnswer", "fold_judgments"]


class JudgeAnswer(BaseModel):
    """What one ask returned: the governing judgments, and the bill.

    ``judgments`` is one per question asked, in pack order — the
    judgment that governs each question (the first rung whose
    confidence cleared τ, or the last rung's when the ladder was
    exhausted). The authors are on the judgments. ``standing_words``
    carries the hysteresis standing's word per question id when a
    standing governed the first rung (the row has it too); ``surfaced``
    follows the standing where it governed, and the raw gate word
    elsewhere.
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
    standing_words: dict[str, str | None] = Field(default_factory=dict)

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
    """The seam. The backend is a parameter with a default (the fake).

    ``standing`` wires the escalation trigger of the ladder through the
    hysteresis standing: the first rung's act-or-escalate decision is
    then the standing's word (per question id, the subject), not the
    per-tick τ comparison — a confidence that wanders across τ does not
    flap the ladder, and a sustained drop escalates within the dwell
    bound. The standing consumes the **first** rung's confidences (the
    signal it was configured for); the later rungs stay gated by the
    policy's τ. ``now`` — the standing's clock, the caller's — is
    required when a standing is wired; for the adopted configuration it
    is the tick number.
    """

    def __init__(
        self,
        backend: JudgeBackend | None = None,
        *,
        ladder: EscalationLadder | None = None,
        policy: ConfidencePolicy | None = None,
        standing: StandingGate | None = None,
        ledger: LedgerPort,
        clock=now_utc,
        confidence_definition: ConfidenceDefinition = CANONICAL_CONFIDENCE,
        scales: Mapping[tuple[str, str, str], CalibrationScale] | None = None,
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
        self.standing = standing
        self.ledger = ledger
        self._clock = clock
        #: The one definition every backend's confidence is computed under.
        self.confidence_definition = confidence_definition
        #: The recalibrations, per (backend, model, task). Where one is
        #: fitted, the gate's τ is read in the calibrated space.
        self.scales = dict(scales or {})

    # -- the ask ---------------------------------------------------------------

    def judge(
        self,
        task: str,
        state: str,
        questions: Sequence[Question],
        *,
        at: str | None = None,
        now: float | None = None,
        scope: str | None = None,
    ) -> JudgeAnswer:
        """Ask one pack over one state, under the confidence policy.

        Escalation is per question and the wire is the pack: each rung
        is asked only the questions the previous rung fell short on,
        over the same shared state. With a standing wired, the first
        rung's fall-short-or-act word is the standing's; ``now`` is then
        required, because a standing without the caller's clock cannot
        replay.

        ``scope`` names the thing being judged — the bucket, the artifact,
        the job. It rides on the row, and it is the join key the
        calibration fold uses to find the outcome that answers this
        judgment (the tiles' play, the critic's verdict, the owner's
        keep). A judgment with no scope is still judged and still
        recorded; it is simply not scored, because nothing names it.
        """
        if self.standing is not None and now is None:
            raise ValueError(
                "a standing gate is a clock over ticks: pass now= (the "
                "caller's clock; the adopted configuration's dwells are "
                "ticks of the decision loop)"
            )
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
        # the standing's word per qid for the row being written, the
        # words it read on the first rung (the answer carries them), and
        # the words that actually made a governing decision — the
        # standing's word is the gate's word where it governs, even
        # where the raw τ comparison would have said otherwise
        standing_words: dict[str, str | None] = {}
        standing_readings: dict[str, str | None] = {}
        governed_by: dict[str, str] = {}

        for index, (name, backend) in enumerate(self.rungs):
            if not pending:
                break
            tau = self.policy.tau_for(backend.name, backend.model, task)
            standing_governs = self.standing is not None and index == 0
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
                    scope=scope,
                )
                prev_backend = name
                continue

            judged = {
                question.qid: self._judged(backend, task, question, reply, tau)
                for question in pending
            }
            act: list[Judgment] = []
            still_pending: list[Question] = []
            standing_words = {}
            for question in pending:
                judgment = judged[question.qid]
                signal = judgment.gated_confidence
                if standing_governs:
                    if signal is None:
                        # a judgment with no confidence cannot feed a
                        # continuous gate: it never passes (the policy's
                        # own rule), and the standing takes no reading
                        acts = False
                        standing_words[question.qid] = None
                    else:
                        word = self.standing.step_for(
                            question.qid, signal, now
                        ).state
                        standing_words[question.qid] = word
                        acts = word == "act"
                else:
                    acts = (
                        self.policy.decision(confidence=signal, tau=tau)
                        == "act"
                    )
                if acts:
                    act.append(judgment)
                    governing[question.qid] = judgment
                    if standing_governs and standing_words.get(question.qid):
                        governed_by[question.qid] = standing_words[question.qid]
                elif index + 1 < len(self.rungs):
                    still_pending.append(question)
                else:
                    act.append(judgment)
                    governing[question.qid] = judgment  # surfaced
                    if standing_governs and standing_words.get(question.qid):
                        governed_by[question.qid] = standing_words[question.qid]
            escalated_qids = {question.qid for question in still_pending}
            if standing_governs:
                standing_readings.update(standing_words)

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
                standing_words=standing_words,
                scope=scope,
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

        def _surfaced(judgment: Judgment) -> bool:
            # the standing's word is the gate's word where it governed
            word = governed_by.get(judgment.qid)
            if word is not None:
                return word != "act"
            return judgment.gate == "surfaced"

        return JudgeAnswer(
            task=task,
            state_hash=s_hash,
            questions_hash=pack_hash,
            judgments=ordered,
            attempts=attempts,
            surfaced=any(_surfaced(judgment) for judgment in ordered),
            cost=total,
            latency_seconds=total.wall_seconds,
            standing_words=dict(standing_readings),
        )

    # -- the record ------------------------------------------------------------

    def _judged(
        self,
        backend: JudgeBackend,
        task: str,
        question: Question,
        reply: BackendReply,
        tau: float,
    ) -> Judgment:
        """One question's judgment: the confidence, the τ and the scale.

        The confidence is computed from the distribution under the judge's
        **one** definition, so every backend's confidence is the same kind
        of number; the backend's own number rides beside it on the row.
        Where a recalibration is fitted for this cell, the calibrated
        confidence is computed as well and the gate reads that one, so τ is
        read in the calibrated space.
        """
        judgment = judgment_from_distribution(
            question=question,
            backend=backend.name,
            model=backend.model,
            distribution=reply.distributions.get(question.qid, {}),
            confidence=reply.confidences.get(question.qid),
            definition=self.confidence_definition,
        ).model_copy(update={"tau": tau})
        scale = self.scales.get((backend.name, backend.model, task))
        if scale is None:
            return judgment
        return judgment.model_copy(
            update={"calibrated_confidence": scale.calibrated_confidence(judgment.distribution)}
        )

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
        standing_words: Mapping[str, str | None] | None = None,
        scope: str | None = None,
    ) -> None:
        """One ``judge.verdict`` row per attempt — refused attempts included.

        ``standing_words`` is the hysteresis standing's word per question
        id when a standing governs the rung (``None`` where it took no
        reading — a no-confidence judgment, or no standing wired). The
        row carries it beside the raw gate's word because a log that
        needs a computation to say what governed is a log that lies by
        omission.

        ``scope`` names the thing judged; the calibration fold joins the
        row to the outcome that answers it by that name.
        """
        standing_words = standing_words or {}
        payload: dict[str, object] = {
            "task": task,
            "state_hash": state_hash,
            "pack_hash": pack_hash,
            "questions_hash": question_set_hash(questions),
            "backend": backend.name,
            "model": backend.model,
            "author": f"judge@{backend.name}:{backend.model}",
            "n_questions": len(questions),
            "scope": scope,
            # the definition the confidences on this row were computed
            # under — every backend's confidence is the same kind of
            # number, and the row says which one it is
            "confidence_definition": self.confidence_definition,
            # the gate decision is derived (confidence, τ, escalated), but the
            # row carries it anyway: a log that needs a computation to say
            # what was acted on is a log that lies by omission — and the
            # standing's word rides beside it for the same reason
            "judgments": [
                {
                    **judgment.model_dump(),
                    "gate": judgment.gate,
                    "standing": standing_words.get(judgment.qid),
                }
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
    rung it was escalated from, and the hysteresis standing's word where
    one governed). A **refused attempt** is its own judgment-less entry,
    because the edges are the story and a refusal is an edge.
    ``entry["judgment"]`` is the :class:`Judgment`; ``entry["distribution"]``,
    ``entry["gate"]`` and ``entry["standing"]`` are conveniences.
    """
    from .models import Judgment

    entries: list[dict] = []
    for event in events:
        if getattr(event, "type", None) != JUDGE_EVENT_TYPE:
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        if backend is not None and payload.get("backend") != backend:
            continue
        raw_judgments = payload.get("judgments", [])
        attempt = tuple(Judgment.model_validate(raw) for raw in raw_judgments)
        for raw, judgment in zip(raw_judgments, attempt):
            entry = dict(payload)
            entry["judgment"] = judgment
            entry["qid"] = judgment.qid
            entry["distribution"] = judgment.distribution
            entry["gate"] = judgment.gate
            entry["escalated"] = judgment.escalated
            entry["standing"] = raw.get("standing") if isinstance(raw, dict) else None
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
