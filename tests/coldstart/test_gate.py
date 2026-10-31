"""Gaps §7 test 3 — the gate.

> **3. The gate:** no rendered line ever claims below two observations for
> its code; night one's predictions all read `confidence: guess`.

Two claims in one test set: the *utterance* half (a taste claim below two
observations does not render at all — T rule 4, "a hard gate at generation
time, not a style instruction") and the *bet* half (night one's sealed bets
all wear `guess` with their zero denominator on their face — §3.5; G §1
20:44: the gate forbids pretending to a view, not betting).
"""

from __future__ import annotations

import pytest

from core.coldstart import render_taste_claim
from core.coldstart.sealing import SealPolicyRefusal


class TestNoRenderedLineClaimsBelowTwoObservations:
    def test_zero_observations_the_claim_does_not_render(self, gate):
        rendered = render_taste_claim(
            gate,
            builder="companion",
            reason_code="wrong_material",
            claim="I think you'll keep the rope-handled crates",
        )
        assert not rendered.rendered
        assert rendered.line is None
        assert rendered.refusal_reason == "below_two_observations"
        assert rendered.observations == 0

    def test_one_observation_still_below_the_gate(self, gate, write_row):
        write_row(reason_code="wrong_material")
        rendered = render_taste_claim(
            gate,
            builder="companion",
            reason_code="wrong_material",
            claim="I think you'll keep the rope-handled crates",
        )
        assert not rendered.rendered
        assert rendered.refusal_reason == "below_two_observations"

    def test_at_two_observations_the_claim_renders_with_its_denominator(self, gate, write_row):
        write_row(reason_code="wrong_material")
        write_row(reason_code="wrong_material")
        rendered = render_taste_claim(
            gate,
            builder="companion",
            reason_code="wrong_material",
            claim="I think you'll keep the rope-handled crates",
        )
        assert rendered.rendered
        assert "2/2 kept" in rendered.line
        # under three observations the uncertainty leads the sentence (T rule 3)
        assert rendered.line.startswith("This is a guess.")

    def test_at_three_observations_the_lead_clause_is_gone(self, gate, write_row):
        for _ in range(3):
            write_row(reason_code="wrong_material")
        rendered = render_taste_claim(
            gate,
            builder="companion",
            reason_code="wrong_material",
            claim="I think you'll keep the rope-handled crates",
        )
        assert rendered.rendered
        assert not rendered.line.startswith("This is a guess")
        assert "3/3 kept" in rendered.line

    def test_a_rejected_observation_counts_in_the_denominator(self, gate, write_row):
        write_row(reason_code="wrong_material")
        write_row(reason_code="wrong_material", verdict="reject")
        rendered = render_taste_claim(
            gate,
            builder="companion",
            reason_code="wrong_material",
            claim="I think you'll keep the rope-handled crates",
        )
        assert rendered.rendered
        assert "1/2 kept" in rendered.line


class TestNightOnesPredictionsAllReadGuess:
    def test_taste_bets_seal_as_guesses_with_their_zero_basis(self, ledger, sealer):
        sealed = [
            sealer.seal_taste_bet(
                builder=builder,
                reason_code=reason_code,
                claim=claim,
                branch_ref="br_night1@ver_0001",
            )
            for builder, reason_code, claim in (
                ("companion", "too_clean", "you keep the deep joints"),
                ("companion", "wrong_era", "you keep the weathered wood"),
                ("architect", "wrong_scale", "you keep the big shed"),
                ("landscaper", "too_flat", "you keep the mixed stand"),
            )
        ]
        assert all(s.prediction.confidence == "guess" for s in sealed)
        assert all(s.prediction.basis == "0 observations" for s in sealed)
        assert all(s.mode == "ask" for s in sealed)
        # every seal is committed, with the sealed payload in the log
        for s in sealed:
            event = ledger.find("prediction.sealed", prediction_id=s.prediction.id)
            assert event is not None
            assert event.payload["sealed_payload"]["confidence"] == "guess"
            assert event.payload["reason_code"] in (
                "too_clean", "wrong_era", "wrong_scale", "too_flat"
            )

    def test_a_world_bet_seals_as_a_guess_too(self, sealer):
        sealed = sealer.seal_world_bet(
            builder="architect",
            claim_type="shadow_count",
            claim="three distinct shadow bands on the east face",
            branch_ref="br_night1@ver_0001",
        )
        assert sealed.prediction.confidence == "guess"
        assert sealed.prediction.basis == "0 observations"
        assert sealed.mode == "ask"  # it may bet; it may not decide

    def test_sealed_at_equals_at_the_seal_is_the_record(self, sealer):
        sealed = sealer.seal_taste_bet(
            builder="companion",
            reason_code="too_clean",
            claim="you keep the deep joints",
            branch_ref="br_night1@ver_0001",
        )
        assert sealed.prediction.sealed_at == sealed.prediction.at


class TestTheMeltedSeal:
    def test_below_the_gate_a_real_confidence_is_refused(self, sealer):
        with pytest.raises(SealPolicyRefusal, match="no_basis_yet"):
            sealer.seal_taste_bet(
                builder="companion",
                reason_code="too_clean",
                claim="you keep the deep joints",
                branch_ref="br_night1@ver_0001",
                confidence="low",
            )

    def test_past_the_gate_a_guess_is_refused(self, sealer, write_row):
        write_row(reason_code="too_clean")
        write_row(reason_code="too_clean")
        with pytest.raises(SealPolicyRefusal, match="guess_expired"):
            sealer.seal_taste_bet(
                builder="companion",
                reason_code="too_clean",
                claim="you keep the deep joints",
                branch_ref="br_night1@ver_0001",
                confidence="guess",
            )

    def test_past_the_gate_the_confidence_comes_from_the_ledger(self, sealer, write_row):
        write_row(reason_code="too_clean")
        write_row(reason_code="too_clean")
        sealed = sealer.seal_taste_bet(
            builder="companion",
            reason_code="too_clean",
            claim="you keep the deep joints",
            branch_ref="br_night1@ver_0001",
        )
        assert sealed.prediction.confidence == "low"  # 2 observations < 3: low, honestly
        assert sealed.prediction.basis == "2/2 kept"
        assert sealed.mode == "act"

    def test_a_world_bet_with_a_history_is_no_longer_a_guess(self, ledger, clock, sealer):
        from core.coldstart import PredictionSealer

        raw = PredictionSealer(ledger=ledger, clock=clock)
        for _ in range(2):
            bet = raw.seal(
                builder="architect",
                claim="three shadow bands",
                claim_type="shadow_count",
                confidence="guess",
                basis="0 observations",
                branch_ref="br_night1@ver_0001",
            )
            # the critic scores it a hit
            from core.coldstart.models import Actor, AuditEvent
            from core.coldstart.stubs import short_hash

            ledger.append(
                AuditEvent(
                    seq=0,
                    id=f"aud_{short_hash({'t': 'scored', 'p': bet.id})}",
                    at=clock.now(),
                    actor=Actor(kind="critic", id="critic-scripted"),
                    type="prediction.scored",
                    subject={"entity_kind": "prediction", "entity_id": bet.id},
                    payload={"prediction_id": bet.id, "verdict": "hit"},
                )
            )
        with pytest.raises(SealPolicyRefusal, match="guess_expired"):
            sealer.seal_world_bet(
                builder="architect",
                claim_type="shadow_count",
                claim="three shadow bands again",
                branch_ref="br_night1@ver_0002",
                confidence="guess",
            )
        sealed = sealer.seal_world_bet(
            builder="architect",
            claim_type="shadow_count",
            claim="three shadow bands again",
            branch_ref="br_night1@ver_0002",
        )
        assert sealed.prediction.confidence == "low"
        assert sealed.prediction.basis == "2/2 hit"
