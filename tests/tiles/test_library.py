"""The library: content addressed, versioned, and never deleted.

The rules under test:

* a tile enters only if the vocabulary admits it;
* the same script is the same tile — adding it twice is a no-op;
* a new body in a family is the family's next version, and the library
  owns the number;
* a tile is **never deleted** — it is retired, with a reason, and it keeps
  its body and its history;
* a retired tile is not an option any more;
* the library is a **fold over the log**: rebuild it from the audit events
  and you get the same library.
"""

from __future__ import annotations

import pytest

from core.tiles.library import TileLibrary, fold_library
from core.tiles.models import TileRefusal


@pytest.fixture
def library(registry):
    return TileLibrary(registry=registry)


# --- admission ---------------------------------------------------------------


def test_the_library_admits_a_valid_tile(library, make_tile):
    tile = library.add(make_tile())
    assert library.get(tile.id) == tile


def test_the_library_refuses_a_tile_the_vocabulary_does_not_admit(library, make_tile):
    bad = make_tile(params={"count": 999, "style": "weathered", "from_library": 0})
    with pytest.raises(TileRefusal) as exc:
        library.add(bad)
    assert exc.value.reason == "out_of_range"
    assert library.tiles() == ()


def test_the_library_refuses_an_unknown_word(library, make_tile):
    tile = make_tile()
    bad = tile.model_copy(
        update={
            "steps": (
                tile.steps[0].model_copy(update={"word": "props.harbor.nope"}),
            )
        }
    )
    with pytest.raises(TileRefusal) as exc:
        library.add(bad)
    assert exc.value.reason == "word_unknown"


# --- content addressing ------------------------------------------------------


def test_the_same_tile_twice_is_one_tile(library, make_tile):
    tile = make_tile()
    first = library.add(tile)
    second = library.add(tile)
    assert first == second
    assert len(library.tiles()) == 1


def test_a_new_body_in_a_family_is_the_next_version(library, make_tile):
    first = library.add(make_tile())
    second = library.add(
        make_tile(params={"count": 12, "style": "stained", "from_library": 0})
    )
    assert first.version == 1
    assert second.version == 2
    assert library.versions("harbor.crates.style") == (first, second)


def test_a_different_family_starts_at_one(library, make_tile):
    first = library.add(make_tile())
    other = library.add(make_tile(family="harbor.racks.style"))
    assert other.version == 1
    assert library.families() == ("harbor.crates.style", "harbor.racks.style")


def test_the_library_families_are_ordered(library, make_tile):
    library.add(make_tile(family="zulu"))
    library.add(make_tile(family="alpha"))
    assert library.families() == ("alpha", "zulu")


# --- retirement --------------------------------------------------------------


def test_a_tile_is_never_deleted(library, make_tile):
    tile = library.add(make_tile())
    with pytest.raises(TileRefusal) as exc:
        library.delete(tile.id)
    assert exc.value.reason == "tiles_are_never_deleted"
    assert library.get(tile.id) == tile


def test_retiring_keeps_the_tile_and_says_why(library, make_tile):
    tile = library.add(make_tile())
    retired = library.retire(tile.id, reason="lost 11 times")
    assert retired.status == "retired"
    assert retired.retire_reason == "lost 11 times"
    assert retired.content_hash == tile.content_hash
    assert library.get(tile.id) == retired


def test_a_retired_tile_is_not_an_option(library, make_tile):
    tile = library.add(make_tile())
    library.retire(tile.id, reason="lost 11 times")
    assert library.active() == ()
    assert library.eligible({}) == ()


def test_a_retired_tile_cannot_be_retired_again(library, make_tile):
    tile = library.add(make_tile())
    library.retire(tile.id, reason="lost 11 times")
    with pytest.raises(TileRefusal) as exc:
        library.retire(tile.id, reason="and again")
    assert exc.value.reason == "already_retired"


def test_retiring_an_unknown_tile_is_refused(library):
    with pytest.raises(TileRefusal) as exc:
        library.retire("tile_nope", reason="lost")
    assert exc.value.reason == "tile_unknown"


# --- eligibility -------------------------------------------------------------


def test_only_tiles_whose_preconditions_hold_are_eligible(library, make_tile):
    from core.tiles.models import Precondition

    plain = library.add(make_tile(title="plain crates"))
    dusk = library.add(
        make_tile(
            title="dusk crates",
            preconditions=(Precondition(key="phase", op="eq", value="dusk"),),
        )
    )
    assert library.eligible({"phase": "dusk"}) == (plain, dusk)
    assert library.eligible({"phase": "noon"}) == (plain,)


# --- the log -----------------------------------------------------------------


def test_the_library_writes_the_log(registry, ledger, make_tile):
    lib = TileLibrary(registry=registry, ledger=ledger)
    tile = lib.add(make_tile())
    types = [event.type for event in ledger.events()]
    assert types == ["tile.authored"]
    assert ledger.events()[0].subject["entity_id"] == tile.id


def test_retiring_writes_the_log(registry, ledger, make_tile):
    lib = TileLibrary(registry=registry, ledger=ledger)
    tile = lib.add(make_tile())
    lib.retire(tile.id, reason="lost 11 times")
    types = [event.type for event in ledger.events()]
    assert types == ["tile.authored", "tile.retired"]


def test_the_library_is_a_fold_over_the_log(registry, ledger, make_tile):
    lib = TileLibrary(registry=registry, ledger=ledger)
    tile = lib.add(make_tile())
    lib.retire(tile.id, reason="lost 11 times")

    rebuilt = fold_library(ledger.events(), registry=registry)
    assert rebuilt.get(tile.id) is not None
    assert rebuilt.get(tile.id).status == "retired"
    assert rebuilt.get(tile.id).retire_reason == "lost 11 times"
    assert len(rebuilt.tiles()) == len(lib.tiles())
