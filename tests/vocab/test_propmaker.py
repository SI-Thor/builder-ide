"""The Prop-maker's loop, in full (D §23:04).

The two things this file proves are the pass/fail conditions of the plan's
week 1 item 5:

* **negative cases rejected at the door** — an out-of-schema call never
  becomes an edit;
* **a sealed bet's `sealed_at` precedes its render** — the seal is committed
  and fsynced before the render job exists, so a bet cannot be rewritten
  after the fact that might have disproved it (§5.1).

And the two rules the loop exists to demonstrate: the **confidence gate**
decides when a builder may act alone, and the night's keep/revert is a
**critic verdict plus an audited branch op** — never a taste write (§1.7).
"""

from __future__ import annotations

import pytest

from core.vocab import CrateBet, LedgerError
from core.vocab.propmaker import CRATES_WORD, TASTE_AXIS


# --- the ordering guarantee -----------------------------------------------------


def test_a_sealed_bet_precedes_its_render(world):
    outcome = world.maker.run()
    assert outcome.predictions

    job = world.scheduler.job(outcome.job_id)
    assert job is not None

    for prediction in outcome.predictions:
        assert prediction.sealed_at < job.created_at

    sealed_events = world.ledger.events(types=["prediction.sealed"])
    enqueued = world.ledger.find("job.enqueued", job_id=outcome.job_id)
    assert enqueued is not None
    for event in sealed_events:
        if event.payload.get("prediction_id") in {
            prediction.id for prediction in outcome.predictions
        }:
            assert event.seq < enqueued.seq


def test_the_ledger_refuses_a_render_for_an_unsealed_prediction(world):
    from core.vocab.models import Actor, AuditEvent

    with pytest.raises(LedgerError) as error:
        world.ledger.append(
            AuditEvent(
                seq=0,
                id="aud_job_without_a_seal",
                at="2026-10-30T21:30:00Z",
                actor=Actor(kind="core", id="scheduler"),
                type="job.enqueued",
                subject={"entity_kind": "job", "entity_id": "job_rogue"},
                payload={"job_id": "job_rogue", "prediction_id": "pr_never_sealed"},
            )
        )
    assert error.value.reason == "prediction_not_sealed"


# --- the established night ------------------------------------------------------


def test_the_night_seals_two_bets_before_it_renders(world):
    outcome = world.maker.run()
    claim_types = [prediction.claim_type for prediction in outcome.predictions]
    assert claim_types == ["material_read", "taste_keep"]
    assert outcome.job_id is not None
    assert outcome.refused_claims == []


def test_the_world_bet_carries_its_denominator(world):
    outcome = world.maker.run()
    world_bet = next(p for p in outcome.predictions if p.claim_type == "material_read")
    assert world_bet.confidence == "medium"
    assert world_bet.basis == "2/3 hit"


def test_the_taste_bet_cites_the_owners_own_record(world):
    outcome = world.maker.run()
    taste_bet = next(p for p in outcome.predictions if p.claim_type == "taste_keep")
    assert taste_bet.confidence == "high"
    assert taste_bet.basis == "4/4 kept"
    assert taste_bet.claim == "Casey keeps 8 of 12 crates"


def test_the_edit_goes_through_the_vocabulary(world):
    outcome = world.maker.run()
    assert outcome.edit is not None
    assert outcome.edit.author.kind == "character"
    assert outcome.edit.author.via == "word"
    calls = world.ledger.events(types=["vocab.call"])
    assert calls and all(call.payload["word"] == CRATES_WORD for call in calls)


def test_the_critic_verdict_says_it_is_scripted(world):
    world.maker.run()
    verdict = world.ledger.find("critic.verdict")
    assert verdict is not None
    assert verdict.payload["label"] == "verdict@scripted"
    assert "verdict@scripted" in verdict.payload["summary"]
    assert verdict.payload["hollow"] == [7, 11]
    assert verdict.payload["kept"] == 10


def test_the_branch_moves_when_the_gate_allows_it(world):
    outcome = world.maker.run()
    assert outcome.head is not None
    assert outcome.parked_question is None
    moved = world.ledger.find("branch.head.moved")
    assert moved is not None
    assert moved.payload["kept"] == 10
    assert moved.payload["reverted"] == [7, 11]


def test_the_hollow_crates_fall_back_to_the_library(world):
    outcome = world.maker.run()
    document = world.recipes.document(outcome.head)
    assert document["entries"]["harbor.crates"]["params"]["from_library"] == 8
    assert document["entries"]["harbor.crates"]["params"]["count"] == 12


# --- the three writers ----------------------------------------------------------


def test_the_night_writes_no_taste_rows(world):
    before = len(world.ledger.events(types=["taste.note.appended"]))
    world.maker.run()
    after = len(world.ledger.events(types=["taste.note.appended"]))
    assert after == before
    assert after == 13  # Casey's own thirteen rows, and not one of the night's


def test_the_critic_does_not_score_the_taste_bet(world):
    outcome = world.maker.run()
    taste_bet = next(p for p in outcome.predictions if p.claim_type == "taste_keep")
    scored = [
        event
        for event in world.ledger.events(types=["prediction.scored"])
        if event.payload.get("prediction_id") == taste_bet.id
    ]
    assert scored == []


def test_the_owner_scores_the_taste_bet_when_they_apply(world):
    outcome = world.maker.run()
    scored = world.maker.owner_applies(finding=outcome.finding)
    assert [prediction.verdict for prediction in scored] == ["partial"]
    events = world.ledger.events(types=["prediction.scored"])
    assert events[-1].actor.kind == "owner"


# --- the cold night -------------------------------------------------------------


def test_the_cold_night_seals_a_guess(cold_world):
    outcome = cold_world.maker.run()
    world_bet = next(p for p in outcome.predictions if p.claim_type == "material_read")
    assert world_bet.confidence == "guess"
    assert world_bet.basis == "0 observations"


def test_the_cold_night_refuses_the_taste_claim(cold_world):
    outcome = cold_world.maker.run()
    assert outcome.refused_claims == ["taste_keep"]
    assert all(p.claim_type != "taste_keep" for p in outcome.predictions)


def test_the_cold_night_parks_a_question_and_leaves_the_branch_alone(cold_world):
    outcome = cold_world.maker.run()
    assert outcome.head is None
    assert outcome.parked_question is not None
    question = cold_world.ledger.find("question.parked")
    assert question is not None
    assert question.payload["reason"] == "below_two_observations"
    assert not cold_world.ledger.events(types=["branch.head.moved"])


def test_the_cold_night_still_scores_the_world_bet(cold_world):
    outcome = cold_world.maker.run()
    assert outcome.verdict == "hit"


# --- the door, inside the loop --------------------------------------------------


def test_the_loop_stops_at_the_door(world):
    outcome = world.maker.run(CrateBet(count=99))
    assert outcome.refusal is not None
    assert outcome.refusal.reason == "out_of_range"
    assert outcome.predictions == []
    assert outcome.job_id is None


def test_the_taste_axis_is_the_axis_the_word_carries(world):
    entry = world.registry.require(CRATES_WORD)
    assert TASTE_AXIS in {note.reason_code for note in entry.taste_notes}
