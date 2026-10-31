"""Gaps §7 test 1 — the cold open.

> **1. Cold open:** fresh project → first line has a zero-denominator, no
> adjective about the owner, one offer of four seeds.

The zero-denominator is the only admissible claim on night one (G §1 19:58;
X C1 killed `ux-day`'s "I'm reading that as 'straight lines, weathered
wood'" opener for exactly this). The adjective check below uses the closed
list of the adjectives the killed opener used and their kin — the structural
guarantee (the line builder takes counts, not descriptions) is the real
defense; the list is its tripwire.
"""

from __future__ import annotations

from core.coldstart import FOUR_STARTERS, companion_opening

#: Adjectives about the owner that a zero-row ledger has no basis to say.
OWNER_ADJECTIVES = (
    "straight",
    "weathered",
    "minimalist",
    "minimal",
    "modern",
    "rustic",
    "natural",
    "tidy",
    "bold",
    "understated",
    "eclectic",
    "traditional",
)


class TestColdOpen:
    def test_fresh_project_the_first_line_carries_its_zero_denominator(self, ledger):
        opening = companion_opening(ledger.events())
        assert "0 of 0" in opening.line
        assert opening.taste_rows == 0 and opening.kept == 0

    def test_no_adjective_about_the_owner(self, ledger):
        line = companion_opening(ledger.events()).line.lower()
        for adjective in OWNER_ADJECTIVES:
            assert adjective not in line, f"{adjective!r} crept into the cold line"

    def test_exactly_one_offer_of_choices_and_it_is_four_seeds(self, ledger):
        opening = companion_opening(ledger.events())
        assert opening.line.count("Four ways to start") == 1
        assert len(opening.starters) == 4
        assert opening.starters == FOUR_STARTERS
        # seeds, not guesses: every chip carries its seed on its face
        for starter in opening.starters:
            assert f"seed {starter.seed}" in starter.label

    def test_once_rows_exist_the_zero_denominator_is_gone(self, ledger, write_row):
        write_row(reason_code="wrong_material")
        write_row(reason_code="wrong_material", verdict="reject")
        opening = companion_opening(ledger.events())
        assert "0 of 0" not in opening.line
        assert "1 of 2" in opening.line  # the same sentence shape, honestly grown

    def test_magnus_rows_never_inform_caseys_opener(self, ledger, write_row):
        write_row(reason_code="too_busy", author="magnus", status="pending_ratification")
        opening = companion_opening(ledger.events())
        assert opening.taste_rows == 0
        assert "0 of 0" in opening.line
