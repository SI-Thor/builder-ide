"""Sealed predictions: the bet that cannot be edited after the fact.

Spec §1.7 and §5.1. The properties that matter:

* the seal hash covers the whole payload, `render_spec` included, so a verdict
  is re-scorable against the same inputs (X R7; RV patch 16);
* a sealed record cannot be edited — only a verdict is written later;
* three record types, three writers (X C5/D1/D2): a world prediction is scored
  by the Critic, a taste prediction by the owner, and nobody scores their own
  bet.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.vocab import Actor, Prediction, build_prediction, seal_hash_for
from core.vocab.hashing import content_hash
from core.vocab.predictions import SEALED_FIELDS, PredictionRefusal, verify_seal


@pytest.fixture
def service(world):
    return world.predictions


def _seal(service, **overrides):
    arguments = {
        "builder": "prop-maker",
        "claim": "Weathered timber reads as weathered on all 12 crates",
        "claim_type": "material_read",
        "confidence": "medium",
        "basis": "2/3 hit",
        "branch_ref": "br_main@ver_root",
        "render_spec": {"rung": 2, "resolution": "480p", "seed": 42},
    }
    arguments.update(overrides)
    return service.seal(**arguments)


# --- sealing -------------------------------------------------------------------


def test_a_sealed_prediction_hashes_its_own_payload(service):
    prediction = _seal(service)
    assert prediction.seal_hash.startswith("sha256:")
    assert verify_seal(prediction)
    expected = content_hash(
        {
            "builder": prediction.builder,
            "at": prediction.at,
            "branch_ref": prediction.branch_ref,
            "claim": prediction.claim,
            "claim_type": prediction.claim_type,
            "confidence": prediction.confidence,
            "basis": prediction.basis,
            "render_spec": prediction.render_spec,
        }
    )
    assert prediction.seal_hash == expected


def test_the_render_spec_is_inside_the_sealed_payload(service):
    prediction = _seal(service, render_spec={"rung": 2, "resolution": "480p", "seed": 7})
    assert prediction.render_spec == {"rung": 2, "resolution": "480p", "seed": 7}
    assert verify_seal(prediction)
    # A different render spec is a different seal.
    other = build_prediction(
        id="pr_other",
        builder="prop-maker",
        at=prediction.at,
        sealed_at=prediction.sealed_at,
        branch_ref=prediction.branch_ref,
        claim=prediction.claim,
        claim_type=prediction.claim_type,
        confidence=prediction.confidence,
        basis=prediction.basis,
        render_spec={"rung": 3, "resolution": "480p", "seed": 7},
    )
    assert other.seal_hash != prediction.seal_hash


def test_sealed_at_equals_at_at_seal_time(service):
    prediction = _seal(service)
    assert prediction.sealed_at == prediction.at


def test_a_sealed_record_cannot_be_edited(service):
    prediction = _seal(service)
    with pytest.raises(ValidationError):
        prediction.claim = "something else"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        prediction.sealed_at = "2026-10-30T22:00:00Z"  # type: ignore[misc]


def test_the_namespace_follows_the_claim_type():
    with pytest.raises(ValidationError):
        Prediction(
            id="pr_x",
            builder="prop-maker",
            at="2026-10-30T21:00:00Z",
            sealed_at="2026-10-30T21:00:00Z",
            branch_ref="br_main@ver_root",
            claim="a claim",
            claim_type="taste_keep",
            namespace="world",
            confidence="low",
            basis="0 observations",
            render_spec=None,
            seal_hash="sha256:00",
        )


def test_a_claim_over_120_characters_is_refused():
    with pytest.raises(ValidationError):
        build_prediction(
            id="pr_x",
            builder="prop-maker",
            at="2026-10-30T21:00:00Z",
            sealed_at="2026-10-30T21:00:00Z",
            branch_ref="br_main@ver_root",
            claim="x" * 121,
            claim_type="material_read",
            confidence="low",
            basis="0 observations",
            render_spec=None,
        )


def test_a_basis_may_not_be_a_percentage(service):
    with pytest.raises(ValidationError):
        _seal(service, basis="80% hit")


def test_an_unknown_claim_type_is_refused(service):
    with pytest.raises(PredictionRefusal) as error:
        _seal(service, claim_type="vibes")
    assert error.value.reason == "claim_type_unknown"


# --- scoring: three writers, one store -----------------------------------------


def test_the_critic_scores_a_world_prediction(service):
    prediction = _seal(service)
    scored = service.score(
        prediction, verdict="hit", actor=Actor(kind="critic", id="critic-local")
    )
    assert scored.verdict == "hit"
    assert prediction.verdict is None  # the sealed record is untouched


def test_the_owner_may_not_score_a_world_prediction(service):
    prediction = _seal(service)
    with pytest.raises(PredictionRefusal) as error:
        service.score(prediction, verdict="hit", actor=Actor(kind="owner", id="casey"))
    assert error.value.reason == "not_the_critic"


def test_the_critic_may_not_score_a_taste_prediction(service):
    prediction = _seal(service, claim_type="taste_keep")
    with pytest.raises(PredictionRefusal) as error:
        service.score(
            prediction, verdict="hit", actor=Actor(kind="critic", id="critic-local")
        )
    assert error.value.reason == "not_the_owner"


def test_a_builder_never_scores_their_own_bet(service):
    prediction = _seal(service)
    with pytest.raises(PredictionRefusal) as error:
        service.score(
            prediction, verdict="hit", actor=Actor(kind="critic", id="prop-maker")
        )
    assert error.value.reason == "self_scored"


def test_a_prediction_is_scored_once(service):
    prediction = _seal(service)
    critic = Actor(kind="critic", id="critic-local")
    service.score(prediction, verdict="hit", actor=critic)
    with pytest.raises(PredictionRefusal) as error:
        service.score(prediction, verdict="miss", actor=critic)
    assert error.value.reason == "already_scored"


def test_sealing_and_scoring_are_audited(service, world):
    prediction = _seal(service)
    service.score(
        prediction, verdict="hit", actor=Actor(kind="critic", id="critic-local")
    )
    types = [event.type for event in world.ledger.events()]
    assert "prediction.sealed" in types
    assert "prediction.scored" in types


def test_the_seal_hash_covers_exactly_the_sealed_fields():
    payload = {
        "builder": "prop-maker",
        "at": "2026-10-30T21:00:00Z",
        "branch_ref": "br_main@ver_root",
        "claim": "a claim",
        "claim_type": "material_read",
        "confidence": "low",
        "basis": "0 observations",
        "render_spec": None,
        "something_else": "not sealed",
    }
    assert seal_hash_for(payload) == content_hash(
        {key: payload[key] for key in SEALED_FIELDS}
    )
