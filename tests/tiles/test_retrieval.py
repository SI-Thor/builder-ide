"""The retrieval front: embed a context, find the tiles that mean the right thing.

The rules under test:

* an **embedder is a parameter** — the front takes one, and says which it
  used, so a number is never read without the model that made it;
* the front **retrieves by meaning**: the top K of the eligible tiles by
  cosine similarity, not by name;
* the front **narrows, it does not decide** — the shortlist it returns is
  what the chooser then chooses among, and a tile outside the shortlist is
  not a candidate;
* a tile that is **not eligible** is not retrieved either: eligibility comes
  before scoring (§4 of the design);
* the **hashing fallback** works with no model at all, and says so — the
  front never pretends a hashing vector is a sentence embedding.
"""

from __future__ import annotations

import math

import pytest

from core.tiles.models import Precondition
from core.tiles.retrieval import (
    HashingEmbedder,
    RetrievalFront,
    RetrievalResult,
    TileIndex,
    describe_tile,
    default_embedder,
    embedder_record,
)


# --- the embedders ----------------------------------------------------------


def test_the_hashing_fallback_works_with_no_model():
    """The floor: the front runs with no model at all."""
    embedder = HashingEmbedder()
    vectors = embedder.embed(["weathered crates", "weathered crates"])
    assert vectors.shape == (2, embedder.dimensions)
    assert math.isclose(float(vectors[0] @ vectors[1]), 1.0, rel_tol=1e-5)


def test_the_hashing_fallback_is_deterministic():
    """Same text, same vector — a replay has to give the same answer."""
    embedder = HashingEmbedder()
    first = embedder.embed(["make the crates read the way the builder wants them"])
    second = embedder.embed(["make the crates read the way the builder wants them"])
    assert (first == second).all()


def test_the_hashing_fallback_says_it_is_a_fallback():
    """A number must never be read without the model that made it."""
    record = embedder_record(HashingEmbedder())
    assert record["kind"] == "hashing"
    assert record["model"] == ""
    assert record["licence"] == "none (ours)"


def test_the_default_embedder_says_which_one_it_is():
    record = embedder_record(default_embedder())
    assert record["kind"] in {"static", "hashing"}
    assert record["licence"]
    assert record["dimensions"] > 0


def test_an_embedder_that_is_not_there_is_refused_by_name():
    """A missing model is a named refusal, not an empty index."""
    from core.tiles.retrieval import EmbedderUnavailable

    # A model id that is nowhere: not in the local cache, and not fetched,
    # because the call says downloads are not allowed.
    with pytest.raises(EmbedderUnavailable) as exc:
        default_embedder(model="minishlab/potion-no-such-model", allow_download=False)
    assert exc.value.model == "minishlab/potion-no-such-model"


# --- the index --------------------------------------------------------------


def test_the_index_finds_a_tile_by_meaning(make_tile):
    """The tiles' titles are what is indexed; the context is what is asked."""
    index = TileIndex(HashingEmbedder())
    weathered = make_tile(title="weathered crates")
    stained = make_tile(title="stained crates")
    index.add(weathered)
    index.add(stained)

    hits = index.search("weathered", k=1)
    assert hits[0].tile.id == weathered.id


def test_the_index_ranks_by_similarity_not_by_insertion(make_tile):
    index = TileIndex(HashingEmbedder())
    first = make_tile(title="weathered crates")
    second = make_tile(title="stained crates")
    index.add(first)
    index.add(second)

    hits = index.search("stained", k=2)
    assert [hit.tile.id for hit in hits] == [second.id, first.id]
    assert hits[0].score >= hits[1].score


def test_the_index_removes_a_retired_tile(make_tile):
    """A retired tile leaves the eligible set, so it leaves the index."""
    index = TileIndex(HashingEmbedder())
    tile = make_tile(title="weathered crates")
    index.add(tile)
    assert index.size == 1
    index.remove(tile.id)
    assert index.size == 0
    assert index.search("weathered", k=1) == ()


def test_the_index_embeds_a_tile_once(make_tile):
    """Re-adding the same tile does not embed it twice."""
    index = TileIndex(HashingEmbedder())
    tile = make_tile(title="weathered crates")
    index.add(tile)
    index.add(tile)
    assert index.size == 1


# --- describing a tile -----------------------------------------------------


def test_a_tile_is_described_by_what_it_does(make_tile):
    """The description is the tile's body in words: title, family, words."""
    tile = make_tile(title="weathered crates")
    text = describe_tile(tile)
    assert "weathered crates" in text
    assert "harbor.crates.style" in text
    assert "props.harbor.crates" in text


def test_a_tile_description_carries_its_params(make_tile):
    """The style is what the game rewards, so it must be in the text."""
    tile = make_tile(params={"count": 12, "style": "weathered", "from_library": 0})
    assert "weathered" in describe_tile(tile)


# --- the front --------------------------------------------------------------


def test_the_front_returns_a_shortlist(make_tile):
    index = TileIndex(HashingEmbedder())
    index.add(make_tile(title="weathered crates"))
    index.add(make_tile(title="stained crates"))
    front = RetrievalFront(index=index, k=1)

    result = front.retrieve({"wanted_style": "weathered"})
    assert isinstance(result, RetrievalResult)
    assert len(result.candidates) == 1
    assert result.candidates[0].title == "weathered crates"


def test_the_front_narrows_to_k(make_tile):
    index = TileIndex(HashingEmbedder())
    for style in ("plain", "weathered", "stained"):
        index.add(make_tile(title=f"{style} crates"))
    front = RetrievalFront(index=index, k=2)

    result = front.retrieve({"wanted_style": "weathered"})
    assert len(result.candidates) == 2


def test_the_front_excludes_an_ineligible_tile(make_tile):
    """Eligibility comes before scoring: a retired tile is not a candidate."""
    index = TileIndex(HashingEmbedder())
    index.add(make_tile(title="weathered crates"))
    retired = make_tile(title="weathered crates, retired").model_copy(
        update={"status": "retired", "retired_at": "2026-10-31T00:00:00Z",
                "retire_reason": "not the one"}
    )
    index.add(retired)
    front = RetrievalFront(index=index, k=5)

    result = front.retrieve({"wanted_style": "weathered"})
    assert [tile.id for tile in result.candidates] == [
        tile.id for tile in result.candidates if tile.status == "active"
    ]


def test_the_front_reports_the_score_of_its_top_hit(make_tile):
    index = TileIndex(HashingEmbedder())
    index.add(make_tile(title="weathered crates"))
    front = RetrievalFront(index=index, k=1)

    result = front.retrieve({"wanted_style": "weathered"})
    assert 0.0 < result.top_score <= 1.0


def test_the_front_returns_nothing_when_the_index_is_empty():
    front = RetrievalFront(index=TileIndex(HashingEmbedder()), k=3)
    result = front.retrieve({"wanted_style": "weathered"})
    assert result.candidates == ()
    assert result.top_score == 0.0


def test_the_front_says_which_embedder_made_its_numbers(make_tile):
    """The record travels with the result — a score without a model is a rumour."""
    index = TileIndex(HashingEmbedder())
    index.add(make_tile(title="weathered crates"))
    front = RetrievalFront(index=index, k=1)

    result = front.retrieve({"wanted_style": "weathered"})
    assert result.embedder["kind"] == "hashing"
    assert result.embedder["licence"]


def test_the_front_lets_a_precondition_keep_a_tile_out(make_tile):
    """A tile whose precondition does not hold is not eligible, so not retrieved."""
    index = TileIndex(HashingEmbedder())
    dusk_only = make_tile(title="weathered crates").model_copy(
        update={
            "preconditions": (Precondition(key="phase", op="eq", value="dusk"),)
        }
    )
    index.add(dusk_only)
    front = RetrievalFront(index=index, k=5)

    assert front.retrieve({"phase": "dusk"}).candidates
    assert front.retrieve({"phase": "noon"}).candidates == ()
