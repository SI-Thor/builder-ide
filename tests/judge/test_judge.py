"""The Judge service: ask a pack, walk the ladder, record everything.

The brief's absolute rules, exercised here:

* **every judgment is recorded** in the ledger as a ``judge.verdict``
  row with its author (``judge@<backend>:<model>``), the distribution,
  the cost, the latency and the question set's hash;
* **a consequential low-confidence answer is surfaced, not acted on** —
  below τ at the ladder's end the row says ``surfaced``;
* the escalation ladder climbs rung by rung, and **every rung's row
  stays on the log** — the edges are the story.
"""

from __future__ import annotations

import pytest

from core.judge.backends import BackendReply, FakeBackend, JudgeRefusal
from core.judge.gate import ConfidencePolicy, EscalationLadder
from core.judge.judge import Judge, fold_judgments
from core.judge.models import Question, judgment_from_distribution, question_set_hash, state_hash
from core.night.ledger import InMemoryLedger
from core.records import EVENT_TYPES

TILES = Question(
    qid="tile",
    kind="choice",
    instructions="Which tile?",
    criteria={"plain": "plain crates", "weathered": "weathered crates", "stained": "stained crates"},
)
ALIVE = Question(qid="alive", kind="noul", instructions="The root is alive.")

#: A confident scripted answer, and an uncertain one — the same shape the
#: shortlist and the gate tests need.
CONFIDENT = {"plain": 0.9, "weathered": 0.05, "stained": 0.05}
UNCERTAIN = {"plain": 0.34, "weathered": 0.33, "stained": 0.33}


class ScriptedBackend(FakeBackend):
    """A fake whose answers come from a callable — for gate and ladder tests."""

    def __init__(self, name, model, responder):
        super().__init__()
        self.name = name
        self.model = model
        self._responder = responder
        self.calls: list[list[str]] = []

    def ask(self, state, questions):
        self.calls.append([q.qid for q in questions])
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


def _scripted(**script) -> FakeBackend:
    return FakeBackend(script=script)


@pytest.fixture
def ledger():
    return InMemoryLedger()


# --- the ask ------------------------------------------------------------------


def test_the_default_backend_is_the_fake(ledger):
    judge = Judge(ledger=ledger)
    answer = judge.judge("tiles.shortlist", "a dusk scene", (TILES,))
    assert answer.judgments[0].backend == "fake"


def test_the_answer_carries_distribution_confidence_cost_latency_hashes(ledger):
    judge = Judge(backend=_scripted(tile=CONFIDENT, **{"alive": {"true": 0.93, "false": 0.07}}), ledger=ledger)
    answer = judge.judge("tiles.shortlist", "a dusk scene", (TILES, ALIVE))
    tile, alive = answer.judgments
    assert tile.distribution["plain"] == pytest.approx(0.9)
    assert tile.confidence == 0.9
    assert tile.answer == "plain"
    assert alive.answer is True
    assert answer.state_hash == state_hash("a dusk scene")
    assert answer.questions_hash == question_set_hash((TILES, ALIVE))
    assert answer.cost.wall_seconds > 0
    assert answer.attempts == 1


def test_a_score_question_answers_its_level_id(ledger):
    scale = Question(
        qid="fit",
        kind="score",
        instructions="How well does it fit?",
        levels=("not", "somewhat", "exactly"),
    )
    judge = Judge(
        backend=_scripted(fit={"0": 0.1, "1": 0.2, "2": 0.7}), ledger=ledger
    )
    answer = judge.judge("task", "state", (scale,))
    assert answer.judgments[0].answer == "2"
    # one attempt, recorded as one row
    assert len(fold_judgments(ledger.events())) == 1


# --- the recording ------------------------------------------------------------


def test_every_ask_writes_a_row_with_author_distribution_cost_latency_and_hash(ledger):
    judge = Judge(backend=_scripted(tile=CONFIDENT), ledger=ledger)
    judge.judge("tiles.shortlist", "a dusk scene", (TILES,))
    (row,) = fold_judgments(ledger.events())
    assert row["author"] == "judge@fake:fake/scripted-v1"
    assert row["distribution"]["plain"] == pytest.approx(0.9)
    assert "cost" in row and row["cost"]["wall_seconds"] >= 0
    assert row["latency_seconds"] >= 0
    assert row["questions_hash"] == question_set_hash((TILES,))
    assert row["task"] == "tiles.shortlist"


def test_the_row_type_is_in_the_closed_set(ledger):
    assert "judge.verdict" in EVENT_TYPES


def test_a_pack_that_cannot_fit_the_payload_cap_is_refused_not_truncated(ledger):
    """The ledger caps a payload at 4 KiB (§1.8). A *pack* that cannot fit
    is split and answered (tests/judge/test_pack_split.py); the one honest
    exception is a single question whose own verdict row cannot fit any
    cap — that refusal is loud, never a truncated or missing answer."""
    monster = Question(
        qid="q" + "x" * 5000,
        kind="choice",
        instructions="Which tile should the builder play next in this context?",
        criteria={
            f"option-{letter}": f"a long description of option {letter}"
            for letter in "abcde"
        },
    )
    judge = Judge(ledger=ledger)
    with pytest.raises(JudgeRefusal) as excinfo:
        judge.judge("task", "state", (monster,))
    assert excinfo.value.code == "payload_too_large"


# --- the gate and the ladder --------------------------------------------------


def test_only_the_below_tau_questions_are_escalated(ledger):
    """A pack escalates question by question: the confident ones are not re-asked."""

    def d1_reply(question):
        if question.qid == "tile":
            return CONFIDENT  # 0.9, at or above τ
        return {"true": 0.35, "false": 0.34}  # 0.35, below τ

    d1 = ScriptedBackend("d1", "d1-2B", d1_reply)
    jev = ScriptedBackend(
        "jev", "jev-latest", lambda q: {"true": 0.9, "false": 0.1} if q.qid == "alive" else UNCERTAIN
    )
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("tiles.shortlist", "state", (TILES, ALIVE))

    # only the uncertain noul went to the second rung
    assert jev.calls == [["alive"]]
    (jev_entry,) = fold_judgments(ledger.events(), backend="jev")
    assert jev_entry["judgment"].qid == "alive"
    assert jev_entry["n_questions"] == 1
    # the escalated sub-pack is its own question set: a different hash, same pack
    assert jev_entry["questions_hash"] != jev_entry["pack_hash"]
    # the governing pair: the tile from d1, the noul from jev
    by_qid = {j.qid: j for j in answer.judgments}
    assert by_qid["tile"].backend == "d1" and by_qid["tile"].gate == "act"
    assert by_qid["alive"].backend == "jev" and by_qid["alive"].gate == "act"
    assert answer.attempts == 2


def test_a_low_confidence_first_rung_is_escalated_and_the_second_governs(ledger):
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN)
    jev = ScriptedBackend("jev", "jev-latest", lambda q: {"plain": 0.1, "weathered": 0.85, "stained": 0.05})
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("tiles.shortlist", "state", (TILES,))

    assert answer.judgments[0].backend == "jev"
    assert answer.judgments[0].answer == "weathered"
    assert answer.judgments[0].gate == "act"
    assert answer.attempts == 2
    assert d1.calls == [["tile"]] and jev.calls == [["tile"]]

    rows = fold_judgments(ledger.events())
    assert len(rows) == 2
    by_backend = {row["backend"]: row for row in rows}
    # the d1 row stays on the log, marked escalated away from
    assert by_backend["d1"]["escalated"] is True
    assert by_backend["d1"]["gate"] == "escalate"
    # the jev row governs, and says who it was escalated from
    assert by_backend["jev"]["gate"] == "act"
    assert by_backend["jev"]["escalated_from"] == "d1"


def test_below_tau_at_the_ladder_s_end_is_surfaced_not_acted_on(ledger):
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: UNCERTAIN)
    judge = Judge(backend=d1, ledger=ledger)
    answer = judge.judge("tiles.shortlist", "state", (TILES,))
    assert answer.judgments[0].gate == "surfaced"
    assert answer.surfaced is True
    (row,) = fold_judgments(ledger.events())
    assert row["gate"] == "surfaced"


def test_tau_is_taken_from_the_policy_for_the_backend_model_and_task(ledger):
    d1 = ScriptedBackend("d1", "d1-2B", lambda q: {"plain": 0.45, "weathered": 0.35, "stained": 0.20})
    policy = ConfidencePolicy(taus={("d1", "d1-2B", "tiles.shortlist"): 0.40})
    judge = Judge(backend=d1, policy=policy, ledger=ledger)
    answer = judge.judge("tiles.shortlist", "state", (TILES,))
    # confidence 0.45 clears the task's τ = 0.40 where the default 0.5 would not
    assert answer.judgments[0].gate == "act"


def test_the_tau_travels_on_the_row(ledger):
    judge = Judge(ledger=ledger, policy=ConfidencePolicy(default=0.6))
    judge.judge("task", "state", (TILES,))
    (row,) = fold_judgments(ledger.events())
    assert row["tau"] == 0.6


def test_a_dead_first_rung_escalates_and_all_failures_refuse_with_rows(ledger):
    class DeadBackend(ScriptedBackend):
        def ask(self, state, questions):
            raise JudgeRefusal("transport_error", "dead")

    d1 = DeadBackend("d1", "d1-2B", lambda q: {})
    jev = ScriptedBackend("jev", "jev-latest", lambda q: CONFIDENT)
    judge = Judge(backend=d1, ladder=EscalationLadder([("jev", jev)]), ledger=ledger)
    answer = judge.judge("task", "state", (TILES,))
    assert answer.judgments[0].backend == "jev"

    all_dead = Judge(
        backend=DeadBackend("d1", "d1-2B", lambda q: {}),
        ladder=EscalationLadder([("clef", DeadBackend("clef", "clef-flash", lambda q: {}))]),
        ledger=InMemoryLedger(),
    )
    with pytest.raises(JudgeRefusal):
        all_dead.judge("task", "state", (TILES,))
    # the refusals are rows too — the edges are the story
    refusals = [row for row in fold_judgments(all_dead.ledger.events()) if row["refused"]]
    assert len(refusals) == 2
    assert {row["backend"] for row in refusals} == {"d1", "clef"}


# --- the fold -----------------------------------------------------------------


def test_the_fold_reads_the_rows_back_into_judgments(ledger):
    judge = Judge(backend=_scripted(tile=CONFIDENT, **{"alive": {"true": 0.93, "false": 0.07}}), ledger=ledger)
    judge.judge("task", "state", (TILES, ALIVE))
    judgments = [row["judgment"] for row in fold_judgments(ledger.events())]
    assert [j.qid for j in judgments] == ["tile", "alive"]
    assert judgments[0].author == "judge@fake:fake/scripted-v1"
    assert judgments[1].answer is True


def test_judgment_from_distribution_completes_missing_options():
    """A backend that never mentions an option gives it its probability at zero."""
    j = judgment_from_distribution(
        question=TILES,
        backend="d1",
        model="d1-2B",
        distribution={"plain": 0.6, "weathered": 0.4},
        confidence=0.6,
    )
    assert j.distribution["stained"] == pytest.approx(0.0)
    assert sum(j.distribution.values()) == pytest.approx(1.0)


def test_judgment_from_distribution_refuses_an_unknown_option():
    with pytest.raises(ValueError):
        judgment_from_distribution(
            question=TILES,
            backend="d1",
            model="d1-2B",
            distribution={"plain": 0.6, "weathered": 0.4, "mossy": 0.0},
            confidence=0.6,
        )
