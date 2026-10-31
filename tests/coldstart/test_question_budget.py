"""Gaps §7 test 2 — the question budget.

> **2. Question budget:** first session logs ≤ 6 questions, strictly
> sequential, every written row has a reason code and an artifact ref.

Plus the ask-mode rules of §3.5 / G §1 20:12 that the test's wording sums
up: a second question while one is open collapses into the slate (never
queues in the owner's face), any question is skippable and a skip writes
nothing, and the answer is the owner's tap — a builder's hand on the taste
pen is refused in code.
"""

from __future__ import annotations

import pytest

from core.coldstart import AskMode, AskRefusal, night_one_bank
from core.coldstart.askmode import (
    Asked,
    BudgetExhausted,
    CollapsedToSlate,
    NothingToAsk,
    Skipped,
)
from tests.coldstart.conftest import BUILDER, OWNER


class TestTheFirstSession:
    def test_the_budget_is_six_and_the_seventh_ask_is_refused(self, ledger, ask):
        session = ask.begin_session()
        bank = night_one_bank()
        spoken = []
        while True:
            outcome = ask.ask_next(session, bank)
            if isinstance(outcome, BudgetExhausted):
                break
            assert isinstance(outcome, Asked)
            spoken.append(outcome.question)
            ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)
        assert len(spoken) == 6
        assert ask.spoken_count(session) == 6  # the fold agrees with the loop

    def test_strictly_one_at_a_time_the_second_collapses_into_the_slate(self, ask):
        session = ask.begin_session()
        first = ask.ask_next(session, night_one_bank())
        assert isinstance(first, Asked)
        # a second question before the first is answered: never queued in the face
        second = ask.ask_next(session, night_one_bank())
        assert isinstance(second, CollapsedToSlate)
        assert second.open_question.id == first.question.id
        assert ask.spoken_count(session) == 1  # nothing new was spoken

    def test_every_written_row_carries_a_reason_code_and_an_artifact_ref(self, ledger, ask):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        row = ask.answer(
            session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER
        )
        assert row.reason_code in {
            "too_busy", "too_empty", "wrong_scale", "too_messy", "too_clean",
            "too_flat", "too_dark", "too_bright", "wrong_material", "wrong_era",
            "wrong_weather", "no_focus",
        }
        assert row.artifact_ref  # a claim about a thing, never a conversation
        assert "@" in row.artifact_ref
        # and the fold sees exactly what was written
        folded = ask.rows_written(session)
        assert [r.id for r in folded] == [row.id]

    def test_a_skip_writes_nothing(self, ledger, ask):
        session = ask.begin_session()
        first = ask.ask_next(session, night_one_bank())
        assert isinstance(first, Asked)
        head_before = ledger.head_seq()
        skipped = ask.skip(session, first.question.id)
        assert isinstance(skipped, Skipped)
        assert ledger.head_seq() == head_before  # not one row, not one line
        assert ask.rows_written(session) == []
        # and the session moves on: the next question is askable
        after = ask.ask_next(session, night_one_bank())
        assert isinstance(after, Asked)
        assert after.question.id != first.question.id

    def test_the_owner_writes_the_row_a_builder_may_not(self, ask):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        with pytest.raises(AskRefusal, match="not_the_owner"):
            ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=BUILDER)

    def test_a_question_is_two_chips_over_two_artifacts(self, ask):
        outcome = ask.ask_next(ask.begin_session(), night_one_bank())
        assert isinstance(outcome, Asked)
        question = outcome.question
        assert len(question.chips) == 2
        assert len({chip.artifact_ref for chip in question.chips}) == 2  # two crops, not one
        assert question.artifact_ref  # the thing both crops are crops of

    def test_only_the_third_chip_of_two_is_refused(self, ask):
        session = ask.begin_session()
        outcome = ask.ask_next(session, night_one_bank())
        assert isinstance(outcome, Asked)
        with pytest.raises(AskRefusal, match="unknown_chip"):
            ask.answer(session, outcome.question.id, "a-third-choice", actor=OWNER)


class TestTheMeltInsideTheSession:
    def test_a_melted_code_is_not_asked_again(self, ledger, ask, write_row):
        # two unprompted keeps on too_clean melt it for every builder
        write_row(reason_code="too_clean")
        write_row(reason_code="too_clean")
        session = ask.begin_session()
        bank = night_one_bank()
        first = ask.ask_next(session, bank)
        assert isinstance(first, Asked)
        assert first.question.reason_code != "too_clean"  # already melted — not asked

    def test_when_everything_is_melted_there_is_nothing_to_ask(self, ask, write_row):
        for code in ("too_clean", "wrong_era", "too_empty", "wrong_scale",
                     "too_bright", "too_flat", "wrong_material", "wrong_weather"):
            write_row(reason_code=code)
            write_row(reason_code=code)
        outcome = ask.ask_next(ask.begin_session(), night_one_bank())
        assert isinstance(outcome, NothingToAsk)


class TestRebuild:
    def test_the_session_rebuilds_from_the_ledger_alone(self, ledger, clock, ask):
        """Kill -9 the service mid-session: the spoken questions survive."""
        session = ask.begin_session()
        for _ in range(3):
            outcome = ask.ask_next(session, night_one_bank())
            assert isinstance(outcome, Asked)
            ask.answer(session, outcome.question.id, outcome.question.chips[0].id, actor=OWNER)

        rebuilt = AskMode(ledger=ledger, clock=clock)
        assert rebuilt.spoken_count(session) == 3
        rows = rebuilt.rows_written(session)
        assert len(rows) == 3
        assert all(row.reason_code for row in rows)
        assert all(row.artifact_ref for row in rows)
