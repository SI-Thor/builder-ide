"""The judgment records: four typed questions, one distribution each.

The brief's four kinds, and what each is on the record:

* ``choice`` — named options, one distribution over them, the argmax is
  the answer;
* ``score`` — an ordered scale of levels, one distribution over the
  levels (the d1 wire's own score type, 2–10 levels);
* ``noul`` — a calibrated probability that a claim is true;
* ``verify`` — a claim checked against evidence; on the wire it is a
  noul question whose instructions carry the claim and the evidence,
  because that is what the System One backends accept.

A question set (a **pack**) is asked over **one shared state** in one
call — §4.1 measured the per-question saving of the shared prefix, and
the pack's hash is what every recorded verdict cites.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.judge.models import (
    JudgeCost,
    Judgment,
    Question,
    question_set_hash,
    state_hash,
)


# --- the four kinds -----------------------------------------------------------


def test_a_choice_question_carries_named_options():
    q = Question(
        qid="tile",
        kind="choice",
        instructions="Which tile should be played?",
        criteria={"plain": "plain crates", "weathered": "weathered crates"},
    )
    wire = q.to_wire()
    assert wire["type"] == "choice"
    assert wire["instructions"] == "Which tile should be played?"
    assert wire["criteria"] == {"plain": "plain crates", "weathered": "weathered crates"}


def test_a_choice_needs_at_least_two_options():
    with pytest.raises(ValidationError):
        Question(qid="one", kind="choice", instructions="?", criteria={"a": "a"})


def test_a_score_question_is_an_ordered_scale():
    q = Question(
        qid="fit",
        kind="score",
        instructions="How well does the tile fit?",
        levels=("not at all", "somewhat", "exactly"),
    )
    wire = q.to_wire()
    assert wire["type"] == "score"
    # the d1 wire takes the levels as an array; the option keys are 0..n-1
    assert wire["criteria"] == ["not at all", "somewhat", "exactly"]
    assert q.option_keys == ("0", "1", "2")


def test_a_score_scale_has_two_to_ten_levels():
    with pytest.raises(ValidationError):
        Question(qid="one", kind="score", instructions="?", levels=("only",))
    with pytest.raises(ValidationError):
        Question(qid="eleven", kind="score", instructions="?", levels=tuple(str(i) for i in range(11)))


def test_a_noul_question_is_a_calibrated_probability():
    q = Question(qid="alive", kind="noul", instructions="The root is alive.")
    wire = q.to_wire()
    assert wire["type"] == "noul"
    assert wire["instructions"] == "The root is alive."
    assert "criteria" not in wire


def test_a_verify_question_becomes_a_noul_over_claim_and_evidence():
    q = Question(
        qid="seal",
        kind="verify",
        claim="the crates read weathered",
        evidence="critic report: the planks carry a grey patina",
    )
    wire = q.to_wire()
    assert wire["type"] == "noul"
    assert "the crates read weathered" in wire["instructions"]
    assert "grey patina" in wire["instructions"]
    assert q.distribution_keys == ("false", "true")


def test_a_verify_question_needs_a_claim():
    with pytest.raises(ValidationError):
        Question(qid="empty", kind="verify", claim="")


# --- the hashes ---------------------------------------------------------------


def test_the_state_hash_is_stable_and_content_addressed():
    assert state_hash("a scene at dusk") == state_hash("a scene at dusk")
    assert state_hash("a scene at dusk") != state_hash("a scene at dawn")
    assert state_hash("a scene at dusk").startswith("sha256:")


def test_the_question_set_hash_covers_ids_kinds_and_order():
    a = Question(qid="x", kind="noul", instructions="is it on?")
    b = Question(qid="y", kind="noul", instructions="is it off?")
    pack = (a, b)
    assert question_set_hash(pack) == question_set_hash(pack)
    assert question_set_hash(pack) != question_set_hash((b, a)), "order is part of the pack"
    assert question_set_hash(pack) != question_set_hash((a, a))


# --- the judgment -------------------------------------------------------------


def _judgment(**overrides) -> Judgment:
    fields = dict(
        qid="tile",
        kind="choice",
        distribution={"plain": 0.3, "weathered": 0.7},
        confidence=0.62,
        backend="d1",
        model="d1-2B",
    )
    fields.update(overrides)
    return Judgment(**fields)


def test_the_judgment_answers_the_argmax():
    j = _judgment()
    assert j.answer == "weathered"
    # a tie is broken by the option's own order, so a replay answers the same
    tied = _judgment(distribution={"plain": 0.5, "weathered": 0.5})
    assert tied.answer == "plain"


def test_the_author_names_the_backend_and_model():
    assert _judgment().author == "judge@d1:d1-2B"


def test_the_gate_decision_comes_from_tau():
    j = _judgment(confidence=0.62, tau=0.5)
    assert j.gate == "act"
    # below tau with a next rung: escalated away from, the answer lives elsewhere
    j = _judgment(confidence=0.49, tau=0.5, escalated=True)
    assert j.gate == "escalate"
    # below tau at the end of the ladder: surfaced, not acted on
    j = _judgment(confidence=0.49, tau=0.5)
    assert j.gate == "surfaced"
    # an ungated judgment: no policy, no decision
    assert _judgment(confidence=0.49, tau=None).gate is None


def test_a_noul_judgment_answers_true_or_false_and_keeps_both_probabilities():
    j = _judgment(
        qid="alive", kind="noul", distribution={"true": 0.93, "false": 0.07}
    )
    assert j.answer is True
    assert j.distribution["false"] == pytest.approx(0.07)


def test_a_distribution_must_sum_to_one():
    with pytest.raises(ValidationError):
        _judgment(distribution={"plain": 0.3, "weathered": 0.3})


# --- the cost -----------------------------------------------------------------


def test_the_cost_records_what_the_backend_spent():
    local = JudgeCost(wall_seconds=0.116, input_tokens=440, gpu_minutes=0.116 / 60.0)
    assert local.hosted_cents == 0
    assert local.cost_known
    cloud = JudgeCost(wall_seconds=0.4, hosted_cents=1, input_tokens=241)
    assert cloud.hosted_cents == 1
    unknown = JudgeCost(wall_seconds=0.4, input_tokens=241, cost_known=False)
    assert not unknown.cost_known and unknown.hosted_cents == 0
