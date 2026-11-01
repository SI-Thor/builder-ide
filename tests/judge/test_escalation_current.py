"""Escalation over the current state, refusals that escalate, never-wait.

The review's third failure, in three parts:

* **the stale state.** The next rung re-asked over "the same shared
  state" after the tick had moved, so its row cited a state and a pack
  hash that no longer matched anything real. Now the caller may wire a
  ``state_reader`` — the world's own read of the shared state — and
  every rung after the first re-reads through it and records its own
  state and pack hashes: the row cites the state it actually asked
  over, and a pack hash is the state **and** the questions it binds.
* **the halt.** A backend refusal (a d1 lock, a missing Jev key, a Clef
  network failure) is a refusal, not a low-confidence judgment — and a
  refusal left the walk with a refusal row instead of the next rung.
  Now the refusal is recorded as *refusal-then-escalate*: the row says
  the ladder moved on, and the next rung's row says whom it was
  escalated from.
* **the stall.** Never-wait (``docs/lab/exp-never-wait.md``): past the
  caller's deadline the ladder stops, the best answer so far commits,
  and a late rung's answer — one that was asked before the deadline and
  returned after it — is recorded as a supersede beside the committed
  answer. Committed history is never rewritten; the late answer lives
  in the log for whoever reads it next.
"""

from __future__ import annotations

import time

import pytest

from core.judge.backends import BackendReply, FakeBackend, JudgeRefusal
from core.judge.gate import EscalationLadder
from core.judge.judge import Judge, fold_judgments
from core.judge.models import (
    JudgeCost,
    Question,
    judgment_from_distribution,
    pack_hash,
    question_set_hash,
    state_hash,
)
from core.night.ledger import InMemoryLedger

TILES = Question(
    qid="tile",
    kind="choice",
    instructions="Which tile?",
    criteria={"plain": "plain crates", "weathered": "weathered crates", "stained": "stained crates"},
)
ALIVE = Question(qid="alive", kind="noul", instructions="The root is alive.")

CONFIDENT = {"plain": 0.9, "weathered": 0.05, "stained": 0.05}
UNCERTAIN = {"plain": 0.34, "weathered": 0.33, "stained": 0.33}


class ScriptedBackend(FakeBackend):
    """A fake whose answers come from a callable — for gate and ladder tests."""

    def __init__(self, name, model, responder, *, sleep=0.0):
        super().__init__()
        self.name = name
        self.model = model
        self._responder = responder
        self._sleep = sleep
        self.calls: list[list[str]] = []

    def ask(self, state, questions):
        self.calls.append([q.qid for q in questions])
        if self._sleep:
            time.sleep(self._sleep)
        distributions = {}
        confidences = {}
        for question in questions:
            distributions[question.qid] = self._responder(question)
            top = max(distributions[question.qid].values())
            confidences[question.qid] = top
        return BackendReply(
            backend=self.name,
            model=self.model,
            distributions=distributions,
            confidences=confidences,
            input_tokens=1,
            wall_seconds=0.001,
        )


# --- the current state --------------------------------------------------------


def test_a_pack_hash_binds_the_state_and_the_questions():
    assert pack_hash("dusk", (TILES,)) == pack_hash("dusk", (TILES,))
    assert pack_hash("dusk", (TILES,)) != pack_hash("dawn", (TILES,))
    assert pack_hash("dusk", (TILES,)) != pack_hash("dusk", (TILES, ALIVE))


def test_each_rung_re_reads_the_state_and_records_its_own_hashes(ledger):
    """The tick moved between the rungs: the second rung asks over the
    state as it is now, and its row says so — not the first rung's."""
    # the tick moved after the caller formed its pack: the reader's first
    # read — the second rung's — returns the state as it is now
    states = iter(["scene at tick 1", "scene at tick 2"])

    def d1_reply(question):
        if question.qid == "tile":
            return UNCERTAIN  # top probability 0.34, below τ
        # a noul's confidence is its top raw reading: keep it below τ
        return {"true": 0.35, "false": 0.34}

    def jev_reply(question):
        return CONFIDENT if question.qid == "tile" else {"true": 0.9, "false": 0.1}

    d1 = ScriptedBackend("d1", "d1-2B", d1_reply)
    jev = ScriptedBackend("jev", "jev-latest", jev_reply)
    judge = Judge(
        backend=d1,
        ladder=EscalationLadder([("jev", jev)]),
        ledger=ledger,
    )
    answer = judge.judge(
        "tiles.shortlist",
        "scene at tick 0",
        (TILES, ALIVE),
        state_reader=lambda: next(states),
    )

    # the answer still answers the caller's pack, at the caller's state
    assert answer.state_hash == state_hash("scene at tick 0")
    assert answer.questions_hash == question_set_hash((TILES, ALIVE))

    d1_row = fold_judgments(ledger.events(), backend="d1")[0]
    jev_row = fold_judgments(ledger.events(), backend="jev")[0]
    # the second rung's row cites the state it actually asked over
    assert d1_row["state_hash"] == state_hash("scene at tick 0")
    assert jev_row["state_hash"] == state_hash("scene at tick 1")
    assert jev_row["pack_hash"] == pack_hash("scene at tick 1", (TILES, ALIVE))
    assert d1_row["pack_hash"] != jev_row["pack_hash"]


def test_without_a_state_reader_every_rung_sees_the_same_state(ledger):
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN)
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT)
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    judge.judge("task", "one state", (TILES,))
    rows = fold_judgments(ledger.events())
    assert {row["state_hash"] for row in rows} == {state_hash("one state")}


# --- refusal-then-escalate ----------------------------------------------------


@pytest.mark.parametrize("code", ["transport_error", "key_missing", "http_error"])
def test_a_backend_refusal_moves_to_the_next_rung_and_says_so(ledger, code):
    class RefusingBackend(ScriptedBackend):
        def ask(self, state, questions):
            self.calls.append([q.qid for q in questions])
            raise JudgeRefusal(code, f"{code} under the heavy lock")

    d1 = RefusingBackend("d1", "d1-2B", lambda q: {})
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT)
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("task", "state", (TILES,))

    assert answer.judgments[0].backend == "jev"
    refusal_row, jev_row = fold_judgments(ledger.events())
    # the refusal row says the ladder moved on, and to where
    assert refusal_row["refused"] is True
    assert refusal_row["refusal_then_escalate"] is True
    assert refusal_row["escalated_to"] == "jev"
    # the cloud row says whom it was escalated from
    assert jev_row["escalated_from"] == "d1"


def test_a_refusal_at_the_ladder_s_end_says_there_was_nowhere_to_go(ledger):
    class RefusingBackend(ScriptedBackend):
        def ask(self, state, questions):
            raise JudgeRefusal("transport_error", "dead")

    judge = Judge(backend=RefusingBackend("d1", "d1-2B", lambda q: {}), ledger=ledger)
    with pytest.raises(JudgeRefusal):
        judge.judge("task", "state", (TILES,))
    (refusal_row,) = [
        row for row in fold_judgments(ledger.events()) if row["refused"]
    ]
    assert refusal_row["refusal_then_escalate"] is False
    assert refusal_row["escalated_to"] is None


# --- never-wait ---------------------------------------------------------------


def test_past_the_deadline_the_best_answer_so_far_commits(ledger):
    """The local rung answered below τ but slowly; the deadline passes
    before the cloud rung is asked; the below-τ answer commits (surfaced
    — the caller decides), and the log records the deadline that
    committed it. The first rung is the fallback: it commits whenever it
    answered, late or not."""
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN, sleep=0.06)
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT)
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("task", "state", (TILES,), deadline_seconds=0.05)

    # the cloud rung was never asked
    assert jev.calls == []
    # the local answer governs, flagged as what it is
    assert answer.judgments[0].backend == "d1"
    assert answer.surfaced is True
    # and the log records the commit: a judgment-less row with the
    # deadline on it, listing what it committed
    deadline_rows = [
        row
        for row in fold_judgments(ledger.events())
        if row.get("deadline_committed")
    ]
    assert len(deadline_rows) == 1
    assert deadline_rows[0]["judgment"] is None
    assert deadline_rows[0]["committed_qids"] == ["tile"]
    assert deadline_rows[0]["backend"] == "deadline"


def test_a_late_answer_is_recorded_as_a_supersede_and_does_not_govern(ledger):
    """Asked before the deadline, returned after it: the answer is on the
    log as a supersede, and the committed answer is the one the caller
    got. Committed history is never rewritten."""
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN)
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT, sleep=0.08)
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("task", "state", (TILES,), deadline_seconds=0.05)

    # the caller got the committed answer — the local one, surfaced
    assert answer.judgments[0].backend == "d1"
    assert answer.surfaced is True
    # the late row is a full row, marked as the supersede it is
    supersede_rows = [
        row for row in fold_judgments(ledger.events()) if row.get("supersede")
    ]
    assert len(supersede_rows) == 1
    assert supersede_rows[0]["backend"] == "jev"
    assert supersede_rows[0]["late_by_seconds"] > 0
    assert supersede_rows[0]["judgment"].qid == "tile"
    # and the deadline commit is on the log beside it
    assert any(
        row.get("deadline_committed") for row in fold_judgments(ledger.events())
    )


def test_a_deadline_that_passes_before_any_answer_refuses_loudly(ledger):
    """A zero budget: the local rung refuses outright, so at the deadline
    there is no best answer to commit — the walk stops and the caller is
    told there is no answer, loudly, instead of being stalled by the
    next rung."""
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: {})
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT)

    class RefusingBackend(ScriptedBackend):
        def ask(self, state, questions):
            self.calls.append([q.qid for q in questions])
            raise JudgeRefusal("transport_error", "dead under the heavy lock")

    d1 = RefusingBackend("d1", "d1-2B", lambda q: {})
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    with pytest.raises(JudgeRefusal) as excinfo:
        judge.judge("task", "state", (TILES,), deadline_seconds=0.0)
    assert excinfo.value.code == "no_backend"
    # nothing further was asked once the budget was spent
    assert jev.calls == []


def test_without_a_deadline_nothing_of_this_appears(ledger):
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN)
    judge = Judge(backend=d1, ledger=ledger)
    answer = judge.judge("task", "state", (TILES,))
    assert answer.surfaced is True
    rows = fold_judgments(ledger.events())
    assert not any(
        row.get("supersede") or row.get("deadline_committed") for row in rows
    )
