"""The two ledgers' other half: sealed predictions (§1.7).

A sealed prediction is a bet the builder makes *before* the render job
exists, so the ledger can check later whether it was right. Three things
have to hold: the seal precedes the job, the payload carries the inputs
the verdict will be scored against, and nothing ever self-scores.
"""
from __future__ import annotations

import pytest

from core.errors import Refused
from core.events import core_actor, owner_actor
from core.models import prediction_seal_hash
from core.svc.predictions import PredictionsService


def render_spec(seed: int = 7) -> dict:
    return {"rung": 2, "resolution": "1024", "seed": seed}


# ------------------------------------------------------------- sealing

def test_a_prediction_is_sealed_with_its_hash(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "the rope reads as wet",
                 "taste_keep", "medium", basis="1 observation",
                 render_spec=render_spec())
    assert p.seal_hash.startswith("sha256:")
    assert p.sealed_at == p.at
    assert p.verdict is None
    assert p.namespace == "taste"


def test_a_world_claim_lives_in_the_world_namespace(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "the span is 2m",
                 "scale_read", "low", render_spec=render_spec())
    assert p.namespace == "world"


def test_a_claim_type_outside_the_closed_set_is_refused(core):
    svc = PredictionsService(core)
    with pytest.raises(Refused) as e:
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "vibes",
                 "low", render_spec=render_spec())
    assert "closed set" in e.value.message


def test_a_confidence_outside_the_set_is_refused(core):
    svc = PredictionsService(core)
    with pytest.raises(Refused):
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "scale_read",
                 "certain", render_spec=render_spec())


def test_a_claim_over_120_chars_is_refused(core):
    svc = PredictionsService(core)
    with pytest.raises(Refused) as e:
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x" * 121,
                 "scale_read", "low", render_spec=render_spec())
    assert "120" in e.value.message


def test_a_seal_without_a_render_spec_is_refused(core):
    """X R7: a verdict must be re-scorable against the same inputs."""
    svc = PredictionsService(core)
    with pytest.raises(Refused) as e:
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low")
    assert "render_spec" in e.value.message


def test_a_render_spec_missing_a_key_is_refused(core):
    svc = PredictionsService(core)
    with pytest.raises(Refused) as e:
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec={"rung": 2, "resolution": "1024"})
    assert "seed" in e.value.message


def test_the_seal_must_precede_the_render_job(core):
    """§5.1: a bet sealed after the render existed is not a bet."""
    svc = PredictionsService(core)
    core.store.append(core.store.new_event(
        "job.enqueued", core_actor(), {"entity_kind": "job", "entity_id": "job_1"},
        {"request": {"branch_ref": "br_main@ver_1"}, "state": "queued"}))
    with pytest.raises(Refused) as e:
        svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec=render_spec())
    assert "before the render job exists" in e.value.message


def test_a_seal_for_another_branch_is_fine(core):
    svc = PredictionsService(core)
    core.store.append(core.store.new_event(
        "job.enqueued", core_actor(), {"entity_kind": "job", "entity_id": "job_1"},
        {"request": {"branch_ref": "br_main@ver_1"}, "state": "queued"}))
    p = svc.seal(owner_actor("prop-maker"), "br_other@ver_2", "x", "taste_keep", "low",
                 render_spec=render_spec())
    assert p.id


def test_a_guess_is_always_permitted(core):
    """G §1: the gate forbids pretending to a view, not betting. A sealed
    zero-prior bet is always allowed."""
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep",
                 "guess", render_spec=render_spec())
    assert p.confidence == "guess"


# ------------------------------------------------------------- the gates

def test_a_builder_may_not_speak_a_taste_claim_below_two_observations(core):
    svc = PredictionsService(core)
    assert svc.observations_for("prop-maker", "taste_keep") == 0
    assert svc.may_speak_claim("prop-maker", "taste_keep") is False
    # a world claim has no such gate
    assert svc.may_speak_claim("prop-maker", "scale_read") is True


def test_two_observations_open_the_taste_gate(core):
    svc = PredictionsService(core)
    for _ in range(2):
        p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep",
                     "low", render_spec=render_spec())
        svc.score(p.id, "hit", owner_actor("casey"))
    assert svc.observations_for("prop-maker", "taste_keep") == 2
    assert svc.may_speak_claim("prop-maker", "taste_keep") is True


# ------------------------------------------------------------- scoring

def test_only_a_closed_verdict_is_accepted(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec=render_spec())
    with pytest.raises(Refused):
        svc.score(p.id, "probably", owner_actor("casey"))


def test_a_prediction_is_scored_once(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec=render_spec())
    svc.score(p.id, "hit", owner_actor("casey"))
    with pytest.raises(Refused):
        svc.score(p.id, "miss", owner_actor("casey"))


def test_a_world_claim_is_scored_by_the_critic(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "scale_read", "low",
                 render_spec=render_spec())
    out = svc.score_world_from_critic(p.id, "keep")
    assert out.verdict in ("hit", "miss", "partial")


# ------------------------------------------------------------- the tally

def test_the_tally_never_produces_a_single_score(core):
    """X C2: a lone "8/10" is deleted. The tally is counts and denominators."""
    svc = PredictionsService(core)
    for i in range(3):
        p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", f"claim {i}",
                     "taste_keep", "low", render_spec=render_spec(seed=i))
        svc.score(p.id, "hit", owner_actor("casey"))
    row = svc.tally()["tally"][0]
    assert row["hits"] == 3
    assert row["sealed"] == 3
    assert row["denominator"] == 3
    assert "3 of 3" in row["line"]
    assert not any(k in row for k in ("score", "rating", "accuracy"))


def test_the_tally_reports_unscored_predictions_in_the_denominator(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec=render_spec())
    row = svc.tally()["tally"][0]
    assert row["sealed"] == 1
    assert row["scored"] == 0
    assert row["denominator"] == 1
    assert "not taste yet" in row["line"]


def test_the_tally_groups_by_builder_and_claim_type(core):
    svc = PredictionsService(core)
    svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
             render_spec=render_spec())
    svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "y", "scale_read", "low",
             render_spec=render_spec())
    svc.seal(owner_actor("companion"), "br_main@ver_1", "z", "taste_keep", "low",
             render_spec=render_spec())
    rows = svc.tally()["tally"]
    assert len(rows) == 3
    assert {r["builder"] for r in rows} == {"prop-maker", "companion"}


def test_the_tally_can_be_filtered(core):
    svc = PredictionsService(core)
    svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
             render_spec=render_spec())
    svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "y", "scale_read", "low",
             render_spec=render_spec())
    rows = svc.tally(claim_type="scale_read")["tally"]
    assert len(rows) == 1
    assert rows[0]["claim_type"] == "scale_read"


# ------------------------------------------------------------- the seal hash

def test_the_seal_hash_covers_the_sealed_payload(core):
    svc = PredictionsService(core)
    p = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                 render_spec=render_spec())
    assert p.seal_hash == prediction_seal_hash(p)
    # changing the inputs changes the hash
    other = svc.seal(owner_actor("prop-maker"), "br_main@ver_1", "x", "taste_keep", "low",
                     render_spec=render_spec(seed=99))
    assert other.seal_hash != p.seal_hash
