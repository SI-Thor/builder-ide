"""The selection language: what it parses, what it keeps, and why it drops.

The language is the part the human touches, so these tests are about the
*words*: an expression that says what it means, a drop that says why, and a
refusal that names the field it could not read.
"""

from __future__ import annotations

import pytest

from core.rewind import LedgerRow, parse, select
from core.rewind.ledger import ledger_from_rows
from core.rewind.selection import EPOCH, TICK, SelectionError


def row(
    seq: int = 1,
    at: float = 0.0,
    actor: str = "Kite",
    agent: str = "Kite",
    kind: str = "tile.played",
    entity_id: str = "skill_1",
    verdict: str = "win",
) -> LedgerRow:
    return LedgerRow(
        seq=seq,
        at=at,
        actor=actor,
        agent=agent,
        kind=kind,
        entity_id=entity_id,
        verdict=verdict,
    )


def test_a_selection_parses_and_names_the_fields_it_reads():
    selection = parse("actor = Kite and kind in (tile.played, tile.authored)")
    assert selection.fields() == {"actor", "kind"}


def test_a_selection_keeps_the_rows_that_match():
    selection = parse("actor = Kite")
    assert selection.matches(row(actor="Kite"))
    assert not selection.matches(row(actor="Pebble"))


def test_a_dropped_row_carries_the_reason_it_was_dropped():
    selection = parse("actor = Kite")
    reason = selection.explain(row(actor="Pebble"))
    assert "Pebble" in reason
    assert "Kite" in reason


def test_a_list_on_the_right_means_one_of():
    selection = parse("kind in (tile.played, tile.authored)")
    assert selection.matches(row(kind="tile.played"))
    assert selection.matches(row(kind="tile.authored"))
    assert not selection.matches(row(kind="tile.retired"))


def test_a_list_on_the_right_of_an_equal_means_one_of_too():
    selection = parse("verdict = (win, partial)")
    assert selection.matches(row(verdict="win"))
    assert selection.matches(row(verdict="partial"))
    assert not selection.matches(row(verdict="lose"))


def test_not_and_or_combine_the_clauses():
    selection = parse("not (actor = Pebble) or verdict = lose")
    assert selection.matches(row(actor="Kite"))
    assert selection.matches(row(actor="Pebble", verdict="lose"))
    assert not selection.matches(row(actor="Pebble", verdict="win"))


def test_contains_matches_a_substring():
    selection = parse("id contains skill_")
    assert selection.matches(row(entity_id="skill_abc"))
    assert not selection.matches(row(entity_id="tile_abc"))


def test_a_time_range_selects_by_timestamp():
    selection = parse(
        "at >= 2026-11-01T05:00:00Z and at < 2026-11-01T07:00:00Z"
    )
    # 2026-11-01T05:00:00Z is 1793509200.0; 07:00:00Z is 1793516400.0
    assert selection.matches(row(at=1793509200.0))  # the start is inclusive
    assert selection.matches(row(at=1793516400.0 - 1))
    assert not selection.matches(row(at=1793509200.0 - 1))
    assert not selection.matches(row(at=1793516400.0))  # the end is exclusive


def test_the_selection_over_a_ledger_keeps_and_drops():
    ledger = ledger_from_rows(
        [
            row(seq=1, actor="Kite"),
            row(seq=2, actor="Pebble"),
            row(seq=3, actor="Sprout"),
        ],
        time_unit=EPOCH,
    )
    result = select(ledger, parse("actor = Kite"))
    assert result.kept_seqs == [1]
    assert result.dropped_seqs == [2, 3]
    assert result.reason_for(2)
    assert result.reason_for(1) == ""


def test_a_timestamp_is_refused_against_a_ledger_of_ticks():
    ledger = ledger_from_rows([row()], time_unit=TICK)
    with pytest.raises(SelectionError) as caught:
        select(ledger, parse("at >= 2026-11-01T05:00:00Z"))
    assert "tick" in str(caught.value)


def test_an_unknown_field_is_refused_by_name():
    with pytest.raises(SelectionError) as caught:
        parse("wobble = 3")
    assert "wobble" in str(caught.value)


def test_a_number_comparison_on_a_text_field_is_refused():
    with pytest.raises(SelectionError) as caught:
        parse("kind >= 3")
    assert "kind" in str(caught.value)


def test_in_without_a_list_is_refused():
    with pytest.raises(SelectionError) as caught:
        parse("kind in tile.played")
    assert "list" in str(caught.value)


def test_an_unclosed_group_is_refused():
    with pytest.raises(SelectionError):
        parse("(actor = Kite")


def test_a_trailing_bracket_is_refused():
    with pytest.raises(SelectionError):
        parse("actor = Kite)")


def test_an_empty_selection_is_refused():
    with pytest.raises(SelectionError):
        parse("   ")


def test_a_quoted_value_may_hold_anything():
    selection = parse('actor = "agent:3"')
    assert selection.matches(row(actor="agent:3"))
    assert not selection.matches(row(actor="agent:4"))
