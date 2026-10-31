"""The confidence gate: when a builder may speak, and when it may act alone.

T §"The 'I think you'll like this' utterance":

    * rule 3 — when the sample is under three, the builder says so **before**
      the claim, not in a footnote;
    * rule 4 — a builder must not predict on a reason code where it has fewer
      than two prior observations. No evidence, no claim. A hard gate at
      generation time, not a style instruction.

And G §1 20:44 — the gate forbids pretending to a view, **not betting**: a
sealed record with `confidence: "guess"` is always permitted.
"""

from __future__ import annotations

import pytest

from core.vocab import Gate, ObservationCounts
from core.vocab.gate import (
    MIN_OBSERVATIONS_FOR_CERTAINTY,
    MIN_OBSERVATIONS_TO_ACT_ALONE,
    MIN_OBSERVATIONS_TO_SPEAK_TASTE,
)


def _gate(world_sealed=0, world_hit=0, taste_observed=0, taste_kept=0) -> Gate:
    counts = ObservationCounts(
        world_sealed={"material_read": world_sealed} if world_sealed else {},
        world_hit={"material_read": world_hit} if world_hit else {},
        taste_observed={"too_busy": taste_observed} if taste_observed else {},
        taste_kept={"too_busy": taste_kept} if taste_kept else {},
    )
    return Gate(counts)


# --- confidence ----------------------------------------------------------------


def test_no_observations_is_a_guess():
    result = _gate().world_confidence("material_read")
    assert result.confidence == "guess"
    assert result.basis == "0 observations"
    assert result.observations == 0


def test_confidence_rises_with_the_record():
    assert _gate(world_sealed=1, world_hit=1).world_confidence("material_read").confidence == "low"
    assert _gate(world_sealed=3, world_hit=2).world_confidence("material_read").confidence == "medium"
    assert _gate(world_sealed=4, world_hit=4).world_confidence("material_read").confidence == "high"
    assert _gate(world_sealed=4, world_hit=1).world_confidence("material_read").confidence == "low"


def test_below_three_observations_the_uncertainty_leads():
    gate = _gate(world_sealed=2, world_hit=2)
    assert gate.world_confidence("material_read").confidence == "low"
    assert gate.uncertainty_leads(2) is True
    assert gate.uncertainty_leads(MIN_OBSERVATIONS_FOR_CERTAINTY) is False
    assert gate.lead_clause(namespace="world", claim_type="material_read").startswith(
        "This is a guess"
    )


def test_the_basis_carries_a_denominator_and_never_a_percentage():
    result = _gate(world_sealed=5, world_hit=3).world_confidence("material_read")
    assert result.basis == "3/5 hit"
    assert "%" not in result.basis
    taste = _gate(taste_observed=5, taste_kept=4).taste_confidence("too_busy")
    assert taste.basis == "4/5 kept"


# --- speaking ------------------------------------------------------------------


def test_a_world_claim_needs_a_denominator():
    gate = _gate()
    decision = gate.may_speak_world("material_read")
    assert decision.allowed is False
    assert decision.reason == "no_denominator"
    assert decision.confidence == "guess"


def test_a_world_claim_is_speakable_once_there_is_a_record():
    gate = _gate(world_sealed=1, world_hit=1)
    decision = gate.may_speak_world("material_read")
    assert decision.allowed is True
    assert decision.basis == "1/1 hit"


def test_a_taste_claim_below_two_observations_is_refused():
    decision = _gate(taste_observed=1, taste_kept=1).may_speak_taste("too_busy")
    assert decision.allowed is False
    assert decision.reason == "below_two_observations"
    assert decision.observations == MIN_OBSERVATIONS_TO_SPEAK_TASTE - 1


def test_a_taste_claim_with_two_observations_is_speakable():
    decision = _gate(taste_observed=2, taste_kept=2).may_speak_taste("too_busy")
    assert decision.allowed is True
    assert decision.basis == "2/2 kept"


# --- acting alone ---------------------------------------------------------------


def test_a_builder_with_no_record_may_not_act_alone():
    decision = _gate().may_act_alone(namespace="world", claim_type="material_read")
    assert decision.allowed is False
    assert decision.reason == "below_two_observations"
    assert decision.confidence == "guess"


def test_a_builder_with_two_observations_may_act_alone():
    decision = _gate(world_sealed=2, world_hit=1).may_act_alone(
        namespace="world", claim_type="material_read"
    )
    assert decision.allowed is True
    assert decision.observations >= MIN_OBSERVATIONS_TO_ACT_ALONE


def test_a_taste_action_needs_its_reason_code():
    with pytest.raises(ValueError):
        _gate().may_act_alone(namespace="taste")
    decision = _gate(taste_observed=2, taste_kept=2).may_act_alone(
        namespace="taste", reason_code="too_busy"
    )
    assert decision.allowed is True


# --- reading the counts out of the ledger ---------------------------------------


def test_the_gate_counts_the_ledger(world):
    counts = ObservationCounts.from_events(
        world.ledger.events(), builder="prop-maker", author="casey"
    )
    assert counts.world_sealed["material_read"] == 3
    assert counts.world_hit["material_read"] == 2
    assert counts.taste_observed["too_busy"] == 6
    assert counts.taste_kept["too_busy"] == 6


def test_the_gate_counts_a_word_s_taste_rows_not_the_whole_ledger(world):
    counts = ObservationCounts.from_events(
        world.ledger.events(),
        builder="prop-maker",
        author="casey",
        subject_prefix="harbor.crates",
    )
    assert counts.taste_observed["too_busy"] == 4
    assert counts.taste_kept["too_busy"] == 4
    assert counts.taste_observed["too_empty"] == 2
    assert counts.taste_kept["too_empty"] == 0


def test_magnus_rows_are_never_counted(world):
    from core.vocab.models import Actor, AuditEvent
    from core.vocab.taste import aggregate_taste_notes, taste_rows_from_events

    world.ledger.append(
        AuditEvent(
            seq=0,
            id="aud_magnus_0001",
            at="2026-10-29T20:00:00Z",
            actor=Actor(kind="owner", id="magnus"),
            type="taste.note.appended",
            subject={"entity_kind": "taste_note", "entity_id": "tn_magnus"},
            payload={
                "row": {
                    "id": "tn_magnus",
                    "at": "2026-10-29T20:00:00Z",
                    "author": "magnus",
                    "status": "pending_ratification",
                    "subject": {
                        "node_id": "crates_0001",
                        "param_path": "harbor.crates.params.count",
                        "value": 20,
                    },
                    "artifact_ref": "br_main@ver_0180",
                    "verdict": "keep",
                    "reason_code": "too_busy",
                }
            },
        )
    )
    counts = ObservationCounts.from_events(
        world.ledger.events(),
        builder="prop-maker",
        author="casey",
        subject_prefix="harbor.crates",
    )
    assert counts.taste_observed["too_busy"] == 4  # unchanged

    # The rows are in the log — the export and erase paths need them — but
    # they are not in any aggregate a builder reads (§7.6).
    rows = taste_rows_from_events(world.ledger.events())
    assert any(row.author == "magnus" for row in rows)
    notes = aggregate_taste_notes(rows, author="casey", subject_prefix="harbor.crates")
    assert all(note.basis != "5/5 kept" for note in notes)
