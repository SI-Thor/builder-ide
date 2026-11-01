"""The pack-size pre-flight: an oversized pack is split, not refused.

The review's first failure: a large shared state or many questions blows
the ledger's 4 KiB payload cap (§1.8), the judge writes a refusal row and
no judgment, and the ladder cannot escalate a refusal — so the caller
stalls or acts on nothing. The fix is a pre-flight: before any backend is
asked, the pack is planned into sub-packs whose verdict rows fit the cap
(the shared state is kept, the questions are partitioned), each sub-pack
is asked and recorded as its own attempt, and the answers come back
merged in pack order. A refusal for size never reaches the caller as
"no answer" — the one honest exception is a single question whose own
verdict row cannot fit any cap, and that refusal is loud, not silent.
"""

from __future__ import annotations

import pytest

from core.judge.backends import BackendReply, FakeBackend, JudgeRefusal
from core.judge.gate import EscalationLadder
from core.judge.judge import Judge, fold_judgments, plan_pack, verdict_payload_estimate
from core.judge.models import Question, question_set_hash, state_hash
from core.night.ledger import MAX_PAYLOAD_BYTES, InMemoryLedger, canonical_bytes

#: Forty choice questions with five named options each — the shape that
#: overflowed the cap in the review. A verdict row is a list of
#: judgments, so the row grows with the pack whatever the state says.


def _big_pack(count: int = 40) -> tuple[Question, ...]:
    return tuple(
        Question(
            qid=f"q{index:02d}",
            kind="choice",
            instructions="Which tile should the builder play next in this context?",
            criteria={
                f"option-{index}-{letter}": f"a long description of option {letter}"
                for letter in "abcde"
            },
        )
        for index in range(count)
        if True
    )


def _monster_question() -> Question:
    """One question whose own verdict row cannot fit any cap."""
    return Question(
        qid="q" + "x" * 5000,
        kind="choice",
        instructions="Which?",
        criteria={f"opt-{i}": "d" for i in range(5)},
    )


class HashBackend(FakeBackend):
    """A fake that answers every question from its hash — deterministic."""

    name = "hash"


class GatedHashBackend(HashBackend):
    """The hash backend with a confidence dial: even-position ids clear
    τ, odd-position ids fall below it — the split pack still escalates.

    The dial is in the **distribution**, not in the backend's own
    confidence number. The judge reads the confidence from the vector the
    backend returned, under one definition for every backend
    (``core.judge.calibration``); a number the backend reported beside
    the vector rides on the log and is never the one the gate compares
    with τ. So the dial has to be the shape of the answer itself: an
    even-position id is answered with a 0.9 top probability, an
    odd-position id with a 0.3 one.
    """

    def __init__(self, tau_line: float = 0.5):
        super().__init__()
        self.tau_line = tau_line

    def ask(self, state, questions):
        reply = super().ask(state, questions)
        distributions = {}
        confidences = {}
        for question in questions:
            odd = int(question.qid[1:]) % 2 == 1
            top = 0.3 if odd else 0.9
            keys = question.option_keys
            rest = (1.0 - top) / (len(keys) - 1)
            vector = {key: rest for key in keys}
            vector[keys[0]] = top
            distributions[question.qid] = vector
            confidences[question.qid] = top
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=1,
            wall_seconds=reply.wall_seconds,
        )


# --- the plan -----------------------------------------------------------------


def test_a_pack_that_fits_is_one_chunk():
    pack = _big_pack(4)
    assert plan_pack(pack, task="task", backend_name="fake", model="fake") == (pack,)


def test_an_oversized_pack_is_planned_into_chunks_that_fit():
    pack = _big_pack(40)
    for standing in (False, True):
        chunks = plan_pack(
            pack, task="task", backend_name="fake", model="fake", standing=standing
        )
        assert len(chunks) > 1
        # the questions survive the plan, in order
        assert [q.qid for chunk in chunks for q in chunk] == [q.qid for q in pack]
        # and every chunk's verdict row fits the cap at the widest legal width
        for chunk in chunks:
            row = verdict_payload_estimate(
                task="task",
                questions=chunk,
                backend_name="fake",
                model="fake",
                standing=standing,
            )
            assert len(canonical_bytes(row)) <= MAX_PAYLOAD_BYTES


def test_a_single_question_that_cannot_fit_any_row_plans_alone():
    monster = _monster_question()
    chunks = plan_pack((monster,), task="task", backend_name="fake", model="fake")
    assert chunks == ((monster,),)


# --- the ask ------------------------------------------------------------------


def test_an_oversized_pack_is_answered_and_merged_not_refused(ledger):
    pack = _big_pack(40)
    judge = Judge(backend=HashBackend(), ledger=ledger)
    answer = judge.judge("task", "one shared state", pack)

    # the caller gets a judgment per question, in pack order — not a refusal
    assert [j.qid for j in answer.judgments] == [q.qid for q in pack]
    assert all(j.backend == "hash" for j in answer.judgments)
    assert answer.state_hash == state_hash("one shared state")
    assert answer.questions_hash == question_set_hash(pack)

    # each sub-pack was its own recorded attempt over the same state
    events = ledger.events()
    assert len(events) > 1
    assert all(not event.payload["refused"] for event in events)
    assert answer.attempts == len(events)
    assert sum(event.payload["n_questions"] for event in events) == 40
    assert len({event.payload["questions_hash"] for event in events}) == len(events)
    assert {event.payload["state_hash"] for event in events} == {answer.state_hash}
    # every row on the log fits the cap it was planned for
    for event in events:
        assert len(canonical_bytes(event.payload)) <= MAX_PAYLOAD_BYTES
    # and the bill is the sum of the attempts
    assert answer.cost.wall_seconds >= max(
        event.payload["cost"]["wall_seconds"] for event in events
    )


def test_a_split_pack_still_escalates_its_below_tau_questions(ledger):
    pack = _big_pack(8)
    even = GatedHashBackend()
    script = {}
    for index in range(1, 8, 2):
        keys = [f"option-{index}-{letter}" for letter in "abcde"]
        script[f"q{index:02d}"] = {keys[0]: 0.9, **{key: 0.025 for key in keys[1:]}}
    cloud = FakeBackend(script=script)
    cloud.name = "jev"
    judge = Judge(
        backend=even,
        ladder=EscalationLadder([("jev", cloud)]),
        ledger=ledger,
    )
    answer = judge.judge("task", "one shared state", pack)

    by_qid = {j.qid: j for j in answer.judgments}
    # every odd question fell below τ, was re-asked of the cloud rung,
    # and its answer governs
    escalated = sorted(qid for qid, j in by_qid.items() if j.backend == "jev")
    assert escalated == [f"q{i:02d}" for i in range(1, 8, 2)]
    assert all(by_qid[qid].gate == "act" for qid in escalated)
    assert answer.attempts >= 2


def test_a_single_question_that_cannot_fit_any_row_is_refused_loudly():
    judge = Judge(ledger=InMemoryLedger())
    with pytest.raises(JudgeRefusal) as excinfo:
        judge.judge("task", "state", (_monster_question(),))
    assert excinfo.value.code == "payload_too_large"
