"""Propensities through a retrieval front, so the OPE estimators still work.

The rules under test:

* the **propensity of a choice made through the front** is the probability
  of the *whole* policy — the retrieval's own draw times the chooser's draw
  inside the shortlist — because that is the number the importance weight
  divides by;
* the **candidates on the record** are the set the choice was actually made
  from, so a target policy normalises over the same set;
* a front that **narrows** the options does not make the propensity bigger:
  it makes the chooser's own probability larger inside a smaller set, and
  the two multiply to something that is still a probability in (0, 1];
* the front is **transparent**: the tile it chose and the reason it chose
  it are both on the record.
"""

from __future__ import annotations

import pytest

from core.tiles.chooser import ContextualBandit
from core.tiles.models import Outcome, PlayCost, TileRefusal, build_play_record
from core.tiles.retrieval import (
    HashingEmbedder,
    RetrievalChooser,
    RetrievalFront,
    TileIndex,
)


@pytest.fixture
def two_tiles(make_tile):
    first = make_tile(title="weathered crates")
    second = make_tile(title="stained crates")
    return first, second


def _record(tile, context, reward, result="win"):
    outcome = Outcome(
        result=result,
        measure="critic",
        score=None if result == "win" else reward,
    )
    return build_play_record(
        at="2026-10-31T02:00:00Z",
        tile=tile,
        context=context,
        outcome=outcome,
        cost=PlayCost(),
        chooser="bandit/ctx-v1",
        chooser_version="1",
    )


def test_the_front_chooses_from_the_shortlist(two_tiles):
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    chooser = RetrievalChooser(front=front, inner=ContextualBandit(seed=1))

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.tile_id == weathered.id


def test_the_choice_says_it_came_through_the_front(two_tiles):
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    chooser = RetrievalChooser(front=front, inner=ContextualBandit(seed=1))

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.reason.startswith("retrieved")
    assert choice.bucket


def test_the_propensity_is_the_whole_policy(two_tiles):
    """Retrieval x choice: the number the weight divides by is the product."""
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    inner = ContextualBandit(epsilon=0.5, seed=3)
    chooser = RetrievalChooser(front=front, inner=inner)

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.propensity is not None
    assert 0.0 < choice.propensity <= 1.0


def test_a_deterministic_inner_gives_a_propensity_of_one(two_tiles):
    """No exploration and one option in the shortlist: the choice was certain."""
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    chooser = RetrievalChooser(
        front=front, inner=ContextualBandit(epsilon=0.0, seed=1)
    )

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.propensity == 1.0


def test_the_shortlist_is_the_candidate_set(two_tiles):
    """The record's candidates are what the choice was made from."""
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    chooser = RetrievalChooser(front=front, inner=ContextualBandit(seed=1))

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.candidates == (weathered.id,)


def test_the_shortlist_is_recorded_on_the_play(two_tiles, registry):
    """The candidates travel with the record, so OPE can normalise over them."""
    from core.night.ledger import InMemoryLedger
    from core.tiles.library import TileLibrary
    from core.tiles.plays import fold_plays, record_play

    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=1)
    chooser = RetrievalChooser(front=front, inner=ContextualBandit(seed=1))

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    ledger = InMemoryLedger()
    library = TileLibrary(registry=registry, ledger=ledger)
    library.add(weathered)
    library.add(stained)
    record_play(
        ledger=ledger,
        library=library,
        tile=weathered,
        context={"wanted_style": "weathered"},
        outcome=Outcome(result="win", measure="critic"),
        chooser=chooser.name,
        chooser_version=chooser.version,
        propensity=choice.propensity,
        candidates=choice.candidates,
    )
    folded = fold_plays(ledger.events())
    assert folded[0].propensity == choice.propensity
    assert folded[0].candidates == choice.candidates


def test_the_front_refuses_when_nothing_is_eligible(two_tiles):
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=2)
    chooser = RetrievalChooser(front=front, inner=ContextualBandit(seed=1))

    with pytest.raises(TileRefusal) as exc:
        chooser.choose({"wanted_style": "weathered"}, [])
    assert exc.value.reason == "no_eligible_tile"


def test_the_front_learns_from_the_plays_it_made(two_tiles):
    """The inner chooser is updated, so the front learns like the bandit."""
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=2)
    inner = ContextualBandit(feature_keys=("wanted_style",), epsilon=0.0, seed=1)
    chooser = RetrievalChooser(front=front, inner=inner)

    for _ in range(20):
        chooser.update(_record(weathered, {"wanted_style": "weathered"}, 1.0))
        chooser.update(
            _record(stained, {"wanted_style": "weathered"}, 0.0, result="lose")
        )

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.tile_id == weathered.id


def test_the_inner_choosers_own_bucket_is_used(two_tiles):
    """The front does not bucket; the chooser does, and it is on the record."""
    weathered, stained = two_tiles
    index = TileIndex(HashingEmbedder())
    index.add(weathered)
    index.add(stained)
    front = RetrievalFront(index=index, k=2)
    inner = ContextualBandit(feature_keys=("wanted_style",), epsilon=0.0, seed=1)
    chooser = RetrievalChooser(front=front, inner=inner)

    choice = chooser.choose({"wanted_style": "weathered"}, [weathered, stained])
    assert choice.bucket == "wanted_style=weathered"
