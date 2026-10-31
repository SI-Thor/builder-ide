"""Decision 13(a) — the melt, mechanically: per builder, per reason code, at two observations.

`docs/plan.md` decision 13: cold start is **a mechanism, not a number of
nights** — questions and `guess` confidence decay per builder, per reason
code, at two observations, auditable in the ledger rather than tuned by
hand. These tests hold the mechanism to exactly that: the flip happens at
two (not one, not three), it is per builder (an answer to the Companion's
question melts the Companion, not the Architect), per reason code (melting
`too_clean` says nothing about `wrong_era`), and every decision involved is
a fold over the audit log, so the melt survives a kill -9 and can be
re-derived by anyone.
"""

from __future__ import annotations

from core.coldstart import ColdStartGate, night_one_bank
from core.coldstart.askmode import Asked, NothingToAsk
from core.coldstart.gate import asked_by_tag
from tests.coldstart.conftest import OWNER


class TestTheFlipAtTwo:
    def test_zero_and_one_observe_ask_and_guess_two_acts_and_claims(self, ledger, ask, gate):
        session = ask.begin_session()
        bank = night_one_bank()
        first = ask.ask_next(session, bank)
        assert isinstance(first, Asked)
        assert first.question.reason_code == "too_clean"

        decision = gate.decide("companion", "too_clean")
        assert decision.mode == "ask" and decision.confidence == "guess"

        ask.answer(session, first.question.id, first.question.chips[0].id, actor=OWNER)
        decision = gate.decide("companion", "too_clean")
        assert decision.observations == 1
        assert decision.mode == "ask"  # one observation is still asking
        assert decision.confidence == "guess"
        assert decision.basis == "1 observation"  # the true count, never hidden

        # the second answer flips it: ask → act, guess → claim, at exactly two
        session2 = ask.begin_session()
        second = ask.ask_next(session2, bank)
        assert isinstance(second, Asked)
        assert second.question.reason_code == "too_clean"
        ask.answer(session2, second.question.id, second.question.chips[0].id, actor=OWNER)

        decision = gate.decide("companion", "too_clean")
        assert decision.observations == 2
        assert decision.mode == "act"
        assert decision.confidence == "low"  # under three, low — honestly
        assert decision.basis == "2/2 kept"
        assert decision.may_speak

    def test_the_answer_carries_the_attribution_that_makes_it_per_builder(self, ledger, ask):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        row = ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)
        assert asked_by_tag("companion") in row.tags


class TestPerBuilder:
    def _answer_the_first_code_twice(self, ask, gate) -> None:
        """Two sittings, one question each: both land on the bank's first
        unmelted code (too_clean), because ask-mode keeps offering it until
        its denominator passes two."""
        for _ in range(2):
            session = ask.begin_session()
            outcome = ask.ask_next(session, night_one_bank())
            assert isinstance(outcome, Asked)
            assert outcome.question.reason_code == "too_clean"
            ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

    def test_an_answer_to_the_companion_does_not_melt_the_architect(self, ask, gate):
        self._answer_the_first_code_twice(ask, gate)
        assert gate.decide("companion", "too_clean").mode == "act"
        # the architect never asked: the Companion's melt is not its melt
        architect = gate.decide("architect", "too_clean")
        assert architect.mode == "ask"
        assert architect.observations == 0

    def test_an_unprompted_keep_melts_every_builder(self, gate, write_row):
        write_row(reason_code="wrong_material")
        write_row(reason_code="wrong_material")
        for builder in ("companion", "architect", "landscaper", "prop-maker"):
            decision = gate.decide(builder, "wrong_material")
            assert decision.mode == "act", builder
            assert decision.basis == "2/2 kept"

    def test_another_authors_rows_never_melt_anyone(self, gate, write_row):
        write_row(reason_code="too_busy", author="magnus", status="pending_ratification")
        write_row(reason_code="too_busy", author="magnus", status="pending_ratification")
        write_row(reason_code="too_busy", author="magnus")
        decision = gate.decide("companion", "too_busy")
        assert decision.observations == 0  # Magnus's rows are author-scoped, always


class TestPerReasonCode:
    def test_melting_one_code_says_nothing_about_another(self, ask, gate):
        for _ in range(2):  # two sittings on the bank's first code
            session = ask.begin_session()
            outcome = ask.ask_next(session, night_one_bank())
            assert isinstance(outcome, Asked)
            ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

        assert gate.decide("companion", "too_clean").mode == "act"
        assert gate.decide("companion", "wrong_era").mode == "ask"  # untouched


class TestAuditable:
    def test_the_melt_is_a_fold_rebuild_the_gate_gets_the_same_answers(self, ledger, ask, gate):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

        # a freshly folded gate — the kill -9 rebuild — agrees on every axis
        rebuilt = ColdStartGate(ledger)
        for builder in ("companion", "architect"):
            for code in ("too_clean", "wrong_era", "wrong_material"):
                assert rebuilt.decide(builder, code) == gate.decide(builder, code)

    def test_the_melted_set_is_derivable_per_builder(self, ledger, ask, gate):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)
        assert gate.melted_codes("companion") == set()
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)
        assert gate.melted_codes("companion") == {"too_clean"}


class TestTheMeltAcrossSessions:
    def test_questions_fall_to_zero_as_denominators_pass_two(self, ledger, clock, ask, gate):
        """The first-week table of G §1.9 as a *prediction*, not a schedule:
        a fake owner answers every question; questions must decline to zero
        per code as each code's denominator passes two, and nothing asks
        past its own gate."""
        spoken_per_session = []
        for _ in range(5):  # five sittings
            session = ask.begin_session()
            spoken = 0
            while True:
                outcome = ask.ask_next(session, night_one_bank())
                if not isinstance(outcome, Asked):
                    break
                ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)
                spoken += 1
            spoken_per_session.append(spoken)

        # 8 codes in the bank, two answers each to melt, ≤ 6 per sitting:
        # 6, 6, 2, 2 and then silence — questions fell to zero per code,
        # exactly as denominators passed two, never by a calendar.
        assert spoken_per_session == [6, 6, 2, 2, 0]
        # every code the bank covers has melted for the companion
        assert gate.melted_codes("companion") >= {
            "too_clean", "wrong_era", "too_empty", "wrong_scale",
            "too_bright", "too_flat", "wrong_material", "wrong_weather",
        }
        # and a sixth sitting has nothing left to ask
        final = ask.ask_next(ask.begin_session(), night_one_bank())
        assert isinstance(final, NothingToAsk)

    def test_guesses_are_gone_per_code_once_the_denominator_passes_two(self, ledger, clock, ask, sealer, gate):
        # sit once: one observation on the bank's first code
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        code = outcome.question.reason_code
        ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

        still_cold = sealer.seal_taste_bet(
            builder="companion", reason_code=code, claim="a bet", branch_ref="br_n1@v1"
        )
        assert still_cold.prediction.confidence == "guess"

        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

        warmed = sealer.seal_taste_bet(
            builder="companion", reason_code=code, claim="a bet", branch_ref="br_n1@v2"
        )
        assert warmed.prediction.confidence != "guess"
        assert warmed.prediction.basis == "2/2 kept"
