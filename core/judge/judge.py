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
2. **the pack is pre-flighted against the ledger's payload cap** — a
   pack whose verdict row cannot fit is split into sub-packs that fit
   (the shared state kept, the questions partitioned), each asked and
   recorded as its own attempt, the answers merged in pack order; a
   refusal for size never reaches the caller as "no answer";
3. **the confidence gate is policy** — act at or above τ, escalate
   below, walking the configured ladder rung by rung, escalating only
   the questions that fell short (a confident answer is not re-asked of
   a dearer backend);
4. **every attempt is a row** — ``judge.verdict``, with the author
   (``judge@<backend>:<model>``), the distribution, the cost, the
   latency, the question set's hash and the pack's hash. Refused
   attempts and escalated-away-from attempts are rows too;
5. **below τ at the ladder's end is surfaced, not acted on** — the
   answer comes back flagged, and the row says so.

The Judge never acts. It returns verdicts and the gate's decision;
what acts on them is the caller's.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.canon import now_utc
from core.night.ledger import MAX_PAYLOAD_BYTES, canonical_bytes
from core.records import Actor

from .backends import BackendReply, FakeBackend, JudgeBackend, JudgeRefusal
from .events import JUDGE_EVENT_TYPE
from .gate import (
    DEFAULT_BAND,
    DEFAULT_DWELL_DOWN,
    DEFAULT_DWELL_UP,
    ConfidencePolicy,
    EscalationLadder,
    StandingGate,
)
from .models import JudgeCost, Judgment, Question, judgment_from_distribution, question_set_hash, state_hash
from .ports import LedgerPort

__all__ = [
    "Judge",
    "JudgeAnswer",
    "fold_judgments",
    "standing_from_rows",
    "plan_pack",
    "verdict_payload_estimate",
]

#: The widest legal JSON spelling of a probability in [0, 1] — 17
#: significant digits in exponent form. The pre-flight measures every
#: would-be row with numbers this wide, so the estimate bounds the real
#: row from above whatever comes back.
_WIDE = 1.2345678901234567e-05

#: Slack for the fields the estimate holds at a stand-in (the gate word,
#: the latency, the cost, the escalated-from name). The estimate has to
#: bound the real row, so the slack is generous.
_ESTIMATE_MARGIN_BYTES = 512


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

    # -- the ask ---------------------------------------------------------------

    def judge(
        self,
        task: str,
        state: str,
        questions: Sequence[Question],
        *,
        at: str | None = None,
        now: float | None = None,
    ) -> JudgeAnswer:
        """Ask one pack over one state, under the confidence policy.

        Escalation is per question and the wire is the pack: each rung
        is asked only the questions the previous rung fell short on,
        over the same shared state. With a standing wired, the first
        rung's fall-short-or-act word is the standing's; ``now`` is then
        required, because a standing without the caller's clock cannot
        replay.
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
            standing_governs = self.standing is not None and index == 0
            # the τ that governs this rung, and where it came from: on
            # the standing-governed rung the standing's bound decides —
            # explicitly bound (configured), else the policy's, which
            # ships the measured calibration and falls back to
            # DEFAULT_TAU for an uncalibrated pair. The row says which.
            tau = self.policy.tau_for(backend.name, backend.model, task)
            tau_source = self.policy.source_for(backend.name, backend.model, task)
            if standing_governs and self.standing.tau is not None:
                tau, tau_source = self.standing.tau, "configured"
            if standing_governs:
                self.standing.bind_tau(tau)
            # the rung's rows wait for the rung's escalated flags (a
            # question is escalated when a later rung re-asks it — known
            # only after the whole rung's sub-packs are asked), and they
            # are written in ask order
            rung_records: list[dict] = []
            next_pending: list[Question] = []

            for sub_pack in plan_pack(
                pending,
                task=task,
                backend_name=backend.name,
                model=backend.model,
                standing=standing_governs,
            ):
                try:
                    reply = backend.ask(state, sub_pack)
                except JudgeRefusal as refusal:
                    rung_records.append(
                        dict(
                            refusal=True,
                            questions=sub_pack,
                            reply=None,
                            refusal_error=refusal,
                            standing_words={},
                            judgments=(),
                        )
                    )
                    # the refused questions were not answered: the next
                    # rung (if there is one) is asked them whole
                    next_pending.extend(sub_pack)
                    continue

                judged = {
                    question.qid: judgment_from_distribution(
                        question=question,
                        backend=backend.name,
                        model=backend.model,
                        distribution=reply.distributions.get(question.qid, {}),
                        confidence=reply.confidences.get(question.qid),
                    ).model_copy(update={"tau": tau})
                    for question in sub_pack
                }
                still_pending: list[Question] = []
                standing_words = {}
                for question in sub_pack:
                    judgment = judged[question.qid]
                    if standing_governs:
                        if judgment.confidence is None:
                            # a judgment with no confidence cannot feed a
                            # continuous gate: it never passes (the policy's
                            # own rule), and the standing takes no reading
                            acts = False
                            standing_words[question.qid] = None
                        else:
                            word = self.standing.step_for(
                                question.qid, judgment.confidence, now
                            ).state
                            standing_words[question.qid] = word
                            acts = word == "act"
                    else:
                        acts = (
                            self.policy.decision(confidence=judgment.confidence, tau=tau)
                            == "act"
                        )
                    if acts:
                        governing[question.qid] = judgment
                        if standing_governs and standing_words.get(question.qid):
                            governed_by[question.qid] = standing_words[question.qid]
                    elif index + 1 < len(self.rungs):
                        still_pending.append(question)
                    else:
                        governing[question.qid] = judgment  # surfaced
                        if standing_governs and standing_words.get(question.qid):
                            governed_by[question.qid] = standing_words[question.qid]
                if standing_governs:
                    standing_readings.update(standing_words)
                rung_records.append(
                    dict(
                        refusal=False,
                        questions=sub_pack,
                        reply=reply,
                        refusal_error=None,
                        standing_words=standing_words,
                        judgments=judged,
                    )
                )
                next_pending.extend(still_pending)

            escalated_qids = {question.qid for question in next_pending}
            standing_config = (
                {
                    "tau": tau,
                    "band": self.standing.band,
                    "dwell_up": self.standing.dwell_up,
                    "dwell_down": self.standing.dwell_down,
                }
                if standing_governs
                else None
            )
            for record in rung_records:
                if record["refusal"]:
                    self._record(
                        task=task,
                        state_hash=s_hash,
                        pack_hash=pack_hash,
                        questions=record["questions"],
                        backend=backend,
                        tau=tau,
                        judgments=(),
                        reply=None,
                        escalated_from=prev_backend,
                        refusal=record["refusal_error"],
                        at=moment,
                        tau_source=tau_source,
                        standing_governed=standing_governs,
                        tick=now if standing_governs else None,
                        standing_config=standing_config,
                    )
                    continue
                raw = record["judgments"]
                row_judgments = tuple(
                    raw[question.qid].model_copy(
                        update={"escalated": question.qid in escalated_qids}
                    )
                    for question in record["questions"]
                )
                cost = backend.cost_of(record["reply"])
                self._record(
                    task=task,
                    state_hash=s_hash,
                    pack_hash=pack_hash,
                    questions=record["questions"],
                    backend=backend,
                    tau=tau,
                    judgments=row_judgments,
                    reply=record["reply"],
                    escalated_from=prev_backend,
                    refusal=None,
                    at=moment,
                    standing_words=record["standing_words"],
                    tau_source=tau_source,
                    standing_governed=standing_governs,
                    tick=now if standing_governs else None,
                    standing_config=standing_config,
                )
                total = total.added(cost)
                attempts += 1
            prev_backend = name
            pending = tuple(next_pending)

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
        tau_source: str = "default",
        standing_governed: bool = False,
        tick: float | None = None,
        standing_config: Mapping[str, float] | None = None,
    ) -> None:
        """One ``judge.verdict`` row per attempt — refused attempts included.

        ``standing_words`` is the hysteresis standing's word per question
        id when a standing governs the rung (``None`` where it took no
        reading — a no-confidence judgment, or no standing wired). The
        row carries it beside the raw gate's word because a log that
        needs a computation to say what governed is a log that lies by
        omission. A standing-governed row also carries what fed the
        gate — the ``tick`` and the ``standing_config`` (the bound τ,
        the band, the dwells) — because those are what a rebuild replays;
        and every row carries ``tau_source``, the provenance of the τ it
        was judged under.
        """
        standing_words = standing_words or {}
        payload = _verdict_payload(
            task=task,
            state_hash=state_hash,
            pack_hash=pack_hash,
            questions_hash=question_set_hash(questions),
            backend_name=backend.name,
            model=backend.model,
            tau=tau,
            judgments=judgments,
            n_questions=len(questions),
            standing_words=standing_words,
            escalated_from=escalated_from,
            refusal=refusal,
            latency_seconds=reply.wall_seconds if reply else 0.0,
            cost=backend.cost_of(reply) if reply else JudgeCost(wall_seconds=0.0),
            tau_source=tau_source,
            standing_governed=standing_governed,
            tick=tick,
            standing_config=standing_config,
        )
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


# --- the row's shape, and the pack's plan -------------------------------------


def _verdict_payload(
    *,
    task: str,
    state_hash: str,
    pack_hash: str,
    questions_hash: str,
    backend_name: str,
    model: str,
    tau: float,
    judgments: tuple[Judgment, ...],
    n_questions: int,
    standing_words: Mapping[str, str | None],
    escalated_from: str | None,
    refusal: JudgeRefusal | None,
    latency_seconds: float,
    cost: JudgeCost,
    tau_source: str = "default",
    standing_governed: bool = False,
    tick: float | None = None,
    standing_config: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """The ``judge.verdict`` row's payload, in its one canonical shape.

    The pre-flight (:func:`plan_pack`) measures would-be rows through
    this same builder, so what it counts is what the ledger will be
    handed, not a guess beside it.
    """
    payload: dict[str, object] = {
        "task": task,
        "state_hash": state_hash,
        "pack_hash": pack_hash,
        "questions_hash": questions_hash,
        "backend": backend_name,
        "model": model,
        "author": f"judge@{backend_name}:{model}",
        "n_questions": n_questions,
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
        "latency_seconds": latency_seconds,
        "cost": cost.model_dump(),
        "escalated_from": escalated_from,
        "refused": refusal is not None,
        "tau": tau,
        "tau_source": tau_source,
        "standing_governed": standing_governed,
    }
    if tick is not None:
        payload["tick"] = tick
    if standing_config is not None:
        payload["standing_config"] = dict(standing_config)
    if refusal is not None:
        payload["error"] = {"code": refusal.code, "detail": refusal.detail}
    return payload


def verdict_payload_estimate(
    *,
    task: str,
    questions: Sequence[Question],
    backend_name: str,
    model: str,
    standing: bool = False,
) -> dict[str, object]:
    """The would-be verdict row for ``questions``, at the widest legal width.

    Every probability, confidence and τ is measured at the widest JSON
    spelling a float in [0, 1] can have, so the estimate bounds the real
    row from above whatever the backend answers. ``standing`` adds the
    hysteresis word the row would carry when a standing governs the rung.
    """
    questions = tuple(questions)
    # model_construct, not the constructor: the stand-in is measured, not
    # judged — its all-wide distribution deliberately breaks the
    # sum-to-one rule the real judgment enforces
    stand_ins = tuple(
        Judgment.model_construct(
            qid=question.qid,
            kind=question.kind,
            backend=backend_name,
            model=model,
            distribution={key: _WIDE for key in question.option_keys},
            confidence=_WIDE,
            tau=_WIDE,
            escalated=True,
        )
        for question in questions
    )
    return _verdict_payload(
        task=task,
        state_hash=state_hash(""),
        pack_hash=question_set_hash(questions),
        questions_hash=question_set_hash(questions),
        backend_name=backend_name,
        model=model,
        tau=_WIDE,
        judgments=stand_ins,
        n_questions=len(questions),
        standing_words=(
            {question.qid: "escalate" for question in questions} if standing else {}
        ),
        escalated_from=backend_name,
        refusal=None,
        latency_seconds=0.0,
        cost=JudgeCost(wall_seconds=0.0),
        tau_source="calibrated" if standing else "default",
        standing_governed=standing,
        tick=_WIDE if standing else None,
        standing_config=(
            {"tau": _WIDE, "band": _WIDE, "dwell_up": _WIDE, "dwell_down": _WIDE}
            if standing
            else None
        ),
    )


def plan_pack(
    questions: Sequence[Question],
    *,
    task: str,
    backend_name: str,
    model: str,
    standing: bool = False,
    limit: int = MAX_PAYLOAD_BYTES,
) -> tuple[tuple[Question, ...], ...]:
    """Partition ``questions`` so every sub-pack's verdict row fits the cap.

    The shared state is not the planner's business — it is kept whole by
    the caller and every sub-pack is asked over it; only the questions
    are partitioned, in pack order, by the pre-flight measurement. A
    single question whose own row cannot fit any partition comes back as
    its own (doomed) sub-pack: the judge will ask it, and the ledger's
    refusal will be the loud refusal it should be.
    """
    pack = tuple(questions)
    if not pack:
        return ()
    budget = limit - _ESTIMATE_MARGIN_BYTES

    def fits(candidate: tuple[Question, ...]) -> bool:
        row = verdict_payload_estimate(
            task=task,
            questions=candidate,
            backend_name=backend_name,
            model=model,
            standing=standing,
        )
        return len(canonical_bytes(row)) <= budget

    chunks: list[tuple[Question, ...]] = []
    current: list[Question] = []
    for question in pack:
        if current and not fits((*current, question)):
            chunks.append(tuple(current))
            current = [question]
        else:
            # a first question is kept even when it cannot fit: one
            # question cannot be partitioned further, and the honest
            # outcome is the ledger's own refusal, not a silent drop
            current.append(question)
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


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


# --- the rebuild --------------------------------------------------------------


def standing_from_rows(rows) -> StandingGate:
    """The standing, rebuilt from the folded ``judge.verdict`` rows.

    A standing's state — dwell counters, last standing, the bound τ per
    question id — used to live in memory only: a restart, a new process
    or a clock jump lost it, and the ledger's ``standing_words`` could
    not be reproduced. The fix is that a standing-governed row carries
    everything the gate consumed — the confidence (in the judgment), the
    ``tick``, the ``tau`` it was judged under and the ``standing_config``
    (band, dwells) — so this rebuild replays the rows through a fresh
    gate, subject by subject, and refuses anything it cannot reproduce:

    * a row whose recorded word the replay does not return — the ledger
      and the gate disagree, and the disagreement is raised, not
      papered over;
    * a null-confidence tick with a standing word on it — a continuous
      gate takes no reading from a null;
    * a τ (or a band or dwell) that moved under a live subject — a
      standing judged at one bound is not silently re-bound.

    The returned gate continues exactly where the log ends: hand it to a
    fresh :class:`Judge` as its ``standing`` and the next word is the
    word the old process would have said.

        standing = standing_from_rows(fold_judgments(ledger.events()))
        judge = Judge(backend=backend, standing=standing, ledger=ledger)
    """
    governed = [
        row
        for row in rows
        if row.get("standing_governed") and row.get("judgment") is not None
    ]
    standing = StandingGate()
    shape: tuple | None = None
    for row in governed:
        config = row.get("standing_config") or {}
        current_shape = (
            config.get("band", DEFAULT_BAND),
            config.get("dwell_up", DEFAULT_DWELL_UP),
            config.get("dwell_down", DEFAULT_DWELL_DOWN),
        )
        if shape is None:
            shape = current_shape
            standing = StandingGate(
                band=current_shape[0],
                dwell_up=current_shape[1],
                dwell_down=current_shape[2],
            )
        elif current_shape != shape:
            raise ValueError(
                f"seq {row.get('seq')}: the standing's shape moved "
                f"mid-history: {current_shape} after {shape} — a replay "
                "cannot reproduce a gate whose numbers changed under it"
            )
        subject = row["qid"]
        judgment = row["judgment"]
        word = row.get("standing")
        tau = row["tau"]
        if judgment.confidence is None:
            if word is not None:
                raise ValueError(
                    f"seq {row.get('seq')}: a null-confidence tick moved "
                    f"the standing on {subject!r} — a continuous gate "
                    "takes no reading from a null"
                )
            continue
        standing.bind_subject(subject, tau)
        transition = standing.step_for(subject, judgment.confidence, row["tick"])
        if transition.state != word:
            raise ValueError(
                f"seq {row.get('seq')}: {subject!r}'s row says {word!r}; "
                f"the replay says {transition.state!r} — the ledger and "
                "the gate disagree"
            )
    return standing
