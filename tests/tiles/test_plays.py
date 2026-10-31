"""The play record: one use of a tile, written to the log.

The rules under test:

* a tile that is not in the library cannot be played — the option must
  exist before it is used;
* a retired tile cannot be played;
* the play carries the **context** it was chosen in, the outcome, the
  measure that decided it, the cost and the chooser that picked it;
* a play that would not fit in the ledger's payload cap is **refused**, not
  truncated — a truncated context is a lie about the context;
* the fold over the log gives the records back.
"""

from __future__ import annotations

import pytest

from core.tiles.library import TileLibrary
from core.tiles.models import Outcome, PlayCost, TileRefusal
from core.tiles.plays import fold_plays, record_play


@pytest.fixture
def library(registry, ledger):
    return TileLibrary(registry=registry, ledger=ledger)


def test_a_play_is_written_to_the_log(library, ledger, make_tile):
    tile = library.add(make_tile())
    record = record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={"phase": "dusk"},
        outcome=Outcome(result="win", measure="critic"),
        chooser="bandit/ctx-v1",
        chooser_version="1",
    )
    events = ledger.events()
    assert [event.type for event in events] == ["tile.authored", "tile.played"]
    assert events[1].subject["entity_id"] == tile.id
    assert record.tile_id == tile.id
    assert record.reward == 1.0


def test_a_play_folds_back_into_its_record(library, ledger, make_tile):
    tile = library.add(make_tile())
    record = record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={"phase": "dusk"},
        outcome=Outcome(result="partial", measure="owner_keep"),
        cost=PlayCost(gpu_minutes=0.5, wall_seconds=12.0),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        night="night_2026-10-30",
    )
    folded = fold_plays(ledger.events())
    assert folded == (record,)
    assert folded[0].outcome.measure == "owner_keep"
    assert folded[0].context == {"phase": "dusk"}
    assert folded[0].cost.gpu_minutes == 0.5
    assert folded[0].night == "night_2026-10-30"
    assert folded[0].chooser == "bandit/ctx-v1"


def test_a_tile_that_is_not_in_the_library_cannot_be_played(library, ledger, make_tile):
    tile = make_tile()
    with pytest.raises(TileRefusal) as exc:
        record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context={},
            outcome=Outcome(result="win", measure="critic"),
        )
    assert exc.value.reason == "tile_not_admitted"
    assert [event.type for event in ledger.events()] == []


def test_a_retired_tile_cannot_be_played(library, ledger, make_tile):
    tile = library.add(make_tile())
    library.retire(tile.id, reason="lost 11 times")
    with pytest.raises(TileRefusal) as exc:
        record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context={},
            outcome=Outcome(result="win", measure="critic"),
        )
    assert exc.value.reason == "tile_retired"


def test_a_play_that_would_not_fit_is_refused(library, ledger, make_tile):
    """Refused, not truncated: a truncated context is a lie about the context."""
    tile = library.add(make_tile())
    with pytest.raises(TileRefusal) as exc:
        record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context={"blob": "x" * 5000},
            outcome=Outcome(result="win", measure="critic"),
        )
    assert exc.value.reason == "play_payload_too_large"
    assert [event.type for event in ledger.events()] == ["tile.authored"]


def test_the_fold_ignores_the_rows_that_are_not_plays(library, ledger, make_tile):
    tile = library.add(make_tile())
    record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={},
        outcome=Outcome(result="win", measure="critic"),
    )
    folded = fold_plays(ledger.events())
    assert len(folded) == 1
    assert folded[0].id.startswith("play_")


def test_two_plays_of_the_same_tile_in_the_same_context_are_two_records(
    library, ledger, make_tile
):
    tile = library.add(make_tile())
    first = record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={"phase": "dusk"},
        outcome=Outcome(result="win", measure="critic"),
    )
    second = record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={"phase": "dusk"},
        outcome=Outcome(result="lose", measure="critic"),
    )
    assert first.id != second.id
    assert len(fold_plays(ledger.events())) == 2
