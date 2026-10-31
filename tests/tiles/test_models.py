"""The tile schema: what a cloud model writes, and the door it comes through.

The rules under test are the ones the design states:

* a tile is **content addressed** — the same script is the same tile;
* a tile speaks the **closed, typed vocabulary** — an unknown word or an
  out-of-schema parameter is *refused*, never repaired;
* a precondition holds only in the context it was written for;
* the reward mapping is fixed, and a measure that gives a score overrides it;
* retiring a tile keeps its body.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.canon import content_hash, short_hash

from core.tiles.door import validate_tile
from core.tiles.models import (
    Outcome,
    PlayCost,
    PlayRecord,
    Precondition,
    Tile,
    TileAuthor,
    TileRefusal,
    TileStep,
    build_tile,
)


# --- the content address ----------------------------------------------------


def test_a_tile_is_its_content_address(make_tile):
    tile = make_tile()
    assert tile.id == f"tile_{short_hash(tile.body(), 12)}"
    assert tile.id.startswith("tile_")


def test_the_same_script_is_the_same_tile(make_tile):
    first = make_tile()
    second = make_tile()
    assert first.id == second.id
    assert first.content_hash == second.content_hash


def test_a_different_script_is_a_different_tile(make_tile):
    first = make_tile()
    other = make_tile(params={"count": 12, "style": "stained", "from_library": 0})
    assert other.id != first.id


def test_the_content_hash_covers_the_body_only(make_tile):
    """Retiring a tile does not change what the tile *is*."""
    tile = make_tile()
    retired = tile.retired(reason="lost 11 times", at="2026-10-31T06:00:00Z")
    assert retired.content_hash == tile.content_hash
    assert retired.id == tile.id
    assert retired.status == "retired"
    assert retired.retire_reason == "lost 11 times"


def test_the_content_hash_is_the_canonical_hash(make_tile):
    tile = make_tile()
    assert tile.content_hash == content_hash(tile.body())


# --- the door ---------------------------------------------------------------


def test_the_door_admits_a_tile_in_the_vocabulary(make_tile, registry):
    validate_tile(make_tile(), registry)


def test_the_door_refuses_an_unknown_word(make_tile, registry):
    tile = make_tile()
    bad = tile.model_copy(
        update={
            "steps": (
                TileStep(word="props.harbor.does_not_exist", path="harbor.crates", params={}),
            )
        }
    )
    with pytest.raises(TileRefusal) as exc:
        validate_tile(bad, registry)
    assert exc.value.reason == "word_unknown"


def test_the_door_refuses_a_parameter_outside_the_schema(make_tile, registry):
    tile = make_tile(params={"count": 999, "style": "weathered", "from_library": 0})
    with pytest.raises(TileRefusal) as exc:
        validate_tile(tile, registry)
    assert exc.value.reason == "out_of_range"


def test_the_door_refuses_free_text_smuggled_into_a_parameter(make_tile, registry):
    """The cloud author is bound by the same door a builder is."""
    tile = make_tile(
        params={
            "count": 12,
            "style": "weathered",
            "from_library": 0,
            "note": "make it look nice",
        }
    )
    with pytest.raises(TileRefusal) as exc:
        validate_tile(tile, registry)
    assert exc.value.reason == "unknown_property"


def test_a_tile_with_no_steps_is_refused_at_the_door(make_tile, registry):
    """An empty tile cannot even be built — and the door refuses it too."""
    with pytest.raises(ValidationError):
        make_tile(steps=())
    tile = make_tile()
    hollow = tile.model_copy(update={"steps": ()})
    with pytest.raises(TileRefusal) as exc:
        validate_tile(hollow, registry)
    assert exc.value.reason == "no_steps"


# --- preconditions ----------------------------------------------------------


def test_a_precondition_holds_only_in_its_context(make_tile):
    tile = make_tile(
        preconditions=(Precondition(key="wanted_style", op="eq", value="weathered"),)
    )
    assert tile.is_eligible({"wanted_style": "weathered"})
    assert not tile.is_eligible({"wanted_style": "plain"})


def test_a_missing_context_key_does_not_hold(make_tile):
    tile = make_tile(
        preconditions=(Precondition(key="wanted_style", op="eq", value="weathered"),)
    )
    assert not tile.is_eligible({})


def test_the_in_operator_matches_a_membership(make_tile):
    tile = make_tile(
        preconditions=(Precondition(key="phase", op="in", value=["dusk", "night"]),)
    )
    assert tile.is_eligible({"phase": "dusk"})
    assert not tile.is_eligible({"phase": "noon"})


def test_a_numeric_precondition_compares(make_tile):
    tile = make_tile(
        preconditions=(Precondition(key="budget_left", op="gte", value=0.5),)
    )
    assert tile.is_eligible({"budget_left": 0.9})
    assert not tile.is_eligible({"budget_left": 0.1})


# --- the outcome and the reward --------------------------------------------


def test_the_reward_mapping_is_fixed():
    assert Outcome(result="win", measure="critic").reward == 1.0
    assert Outcome(result="partial", measure="critic").reward == 0.5
    assert Outcome(result="lose", measure="critic").reward == 0.0


def test_a_measured_score_overrides_the_mapping():
    assert Outcome(result="win", measure="critic", score=0.25).reward == 0.25


def test_a_score_outside_the_unit_interval_is_refused():
    with pytest.raises(ValidationError):
        Outcome(result="win", measure="critic", score=1.5)


def test_a_play_record_carries_its_measure_and_its_cost():
    record = PlayRecord(
        id="play_0001",
        at="2026-10-31T02:00:00Z",
        tile_id="tile_abc",
        tile_version=2,
        context={"wanted_style": "weathered"},
        outcome=Outcome(result="win", measure="critic"),
        cost=PlayCost(gpu_minutes=0.5, wall_seconds=12.0, hosted_cents=0),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        night="night_2026-10-30",
    )
    assert record.reward == 1.0
    assert record.won is True
    assert record.outcome.measure == "critic"


# --- the author -------------------------------------------------------------


def test_an_author_must_carry_a_prompt_hash():
    with pytest.raises(ValidationError):
        TileAuthor(model="m", provider="p", prompt_hash="not-a-hash")


def test_an_author_carries_what_the_call_cost():
    author = TileAuthor(
        model="minimax/MiniMax-M2.1",
        provider="minimax",
        prompt_hash="sha256:" + "a" * 64,
        cost_cents=3,
    )
    assert author.cost_cents == 3


# --- the record's own shape -------------------------------------------------


def test_a_tile_is_frozen():
    """The body is immutable: a tile is what it is, forever."""
    tile = build_tile(
        family="f",
        kind="behaviour",
        title="t",
        steps=(TileStep(word="w", path="p"),),
        author=TileAuthor(
            model="m", provider="p", prompt_hash="sha256:" + "b" * 64
        ),
    )
    with pytest.raises(ValidationError):
        tile.title = "something else"


def test_a_tile_with_a_retired_status_needs_a_reason():
    tile = build_tile(
        family="f",
        kind="behaviour",
        title="t",
        steps=(TileStep(word="w", path="p"),),
        author=TileAuthor(
            model="m", provider="p", prompt_hash="sha256:" + "b" * 64
        ),
    )
    with pytest.raises(ValidationError):
        Tile(
            id=tile.id,
            family=tile.family,
            kind=tile.kind,
            title=tile.title,
            steps=tile.steps,
            author=tile.author,
            status="retired",
        )
