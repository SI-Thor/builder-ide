"""The author seam: the fake behind it, and the real one in front of it.

The rules under test:

* the **fake** writes deterministic tiles and records what it was asked —
  no network, no model, no money;
* the **cloud** author is told *why* the last tile lost, in the request;
* the tiles the cloud returns carry **its own identity** — the model, the
  provider, the prompt hash and the cost of the call;
* and they come through **the same door**: a tile the vocabulary does not
  admit is refused, whoever wrote it.
"""

from __future__ import annotations

import pytest

from core.tiles.author import AuthorRequest, CloudAuthor, ScriptedAuthor
from core.tiles.models import FeedbackPacket, TileRefusal

CRATES_SPEC = {
    "family": "harbor.crates.style",
    "kind": "recipe_edit",
    "title": "weathered crates",
    "steps": [
        {
            "word": "props.harbor.crates",
            "path": "harbor.crates",
            "params": {"count": 12, "style": "weathered", "from_library": 0},
        }
    ],
}

BAD_SPEC = {
    "family": "harbor.crates.style",
    "kind": "recipe_edit",
    "title": "a tile that names a word that does not exist",
    "steps": [{"word": "props.harbor.nope", "path": "harbor.crates", "params": {}}],
}


def test_the_scripted_author_writes_the_scripted_tiles():
    author = ScriptedAuthor([CRATES_SPEC])
    tiles = author.write(AuthorRequest(goal="weather the crates"))
    assert len(tiles) == 1
    assert tiles[0].family == "harbor.crates.style"
    assert tiles[0].id.startswith("tile_")


def test_the_scripted_author_records_what_it_was_asked():
    author = ScriptedAuthor([CRATES_SPEC])
    request = AuthorRequest(goal="weather the crates", words=("props.harbor.crates",))
    author.write(request)
    assert author.calls == [request]


def test_the_scripted_author_is_deterministic():
    author = ScriptedAuthor([CRATES_SPEC])
    first = author.write(AuthorRequest(goal="g"))
    second = author.write(AuthorRequest(goal="g"))
    assert first[0].id == second[0].id


def test_the_scripted_author_refuses_a_tile_the_vocabulary_does_not_admit(registry):
    author = ScriptedAuthor([BAD_SPEC], registry=registry)
    with pytest.raises(TileRefusal) as exc:
        author.write(AuthorRequest(goal="g"))
    assert exc.value.reason == "word_unknown"


def test_the_cloud_author_tells_the_cloud_why_the_last_tile_lost():
    seen: list[dict] = []

    def transport(payload):
        seen.append(dict(payload))
        return {"tiles": [CRATES_SPEC], "cost_cents": 4}

    author = CloudAuthor(
        endpoint="https://example.invalid/tiles",
        model="minimax/MiniMax-M2.1",
        provider="minimax",
        transport=transport,
    )
    packet = FeedbackPacket(
        tile_id="tile_abc",
        family="harbor.crates.style",
        kind="recipe_edit",
        words=("props.harbor.crates",),
        plays=11,
        wins=2,
        win_rate=2 / 11,
        measure="critic",
        contexts=("phase=dusk",),
        request="write a better tile for this family; here is why it lost",
    )
    author.write(
        AuthorRequest(
            goal="weather the crates",
            words=("props.harbor.crates",),
            feedback=(packet,),
        )
    )
    prompt = seen[0]["prompt"]
    assert "tile_abc" in prompt
    assert "2/11" in prompt
    assert "here is why it lost" in prompt
    assert seen[0]["request"]["feedback"][0]["tile_id"] == "tile_abc"


def test_the_cloud_author_gives_its_tiles_its_own_identity():
    author = CloudAuthor(
        endpoint="https://example.invalid/tiles",
        model="minimax/MiniMax-M2.1",
        provider="minimax",
        transport=lambda payload: {"tiles": [CRATES_SPEC], "cost_cents": 4},
    )
    tile = author.write(AuthorRequest(goal="g"))[0]
    assert tile.author.model == "minimax/MiniMax-M2.1"
    assert tile.author.provider == "minimax"
    assert tile.author.prompt_hash.startswith("sha256:")
    assert tile.author.cost_cents == 4


def test_the_cloud_author_refuses_a_tile_the_vocabulary_does_not_admit(registry):
    author = CloudAuthor(
        endpoint="https://example.invalid/tiles",
        model="m",
        provider="p",
        registry=registry,
        transport=lambda payload: {"tiles": [BAD_SPEC]},
    )
    with pytest.raises(TileRefusal) as exc:
        author.write(AuthorRequest(goal="g"))
    assert exc.value.reason == "word_unknown"


def test_the_cloud_author_refuses_a_malformed_response():
    author = CloudAuthor(
        endpoint="https://example.invalid/tiles",
        model="m",
        provider="p",
        transport=lambda payload: {"nope": True},
    )
    with pytest.raises(TileRefusal) as exc:
        author.write(AuthorRequest(goal="g"))
    assert exc.value.reason == "author_response_malformed"


def test_the_cloud_author_refuses_a_malformed_tile():
    author = CloudAuthor(
        endpoint="https://example.invalid/tiles",
        model="m",
        provider="p",
        transport=lambda payload: {"tiles": [{"kind": "recipe_edit"}]},
    )
    with pytest.raises(TileRefusal) as exc:
        author.write(AuthorRequest(goal="g"))
    assert exc.value.reason == "author_tile_malformed"
