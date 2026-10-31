"""The contextual bandit: the chooser that learns which option wins where.

The rules under test:

* a tile whose preconditions do not hold is **not an option** — it is not
  picked, and a context with no option is a refusal with a named reason;
* the chooser **explores** before it exploits, and says which it did;
* it **learns**: after enough plays it prefers the tile that wins;
* it keeps the **contexts apart** — the same tile can be the right one in
  one context and the wrong one in another;
* it is **deterministic given a seed**, so a night is replayable.
"""

from __future__ import annotations

import pytest

from core.tiles.chooser import Choice, ContextualBandit
from core.tiles.models import Outcome, PlayCost, TileRefusal, build_play_record


def _record(tile, context, reward, *, result="win", measure="critic"):
    outcome = Outcome(
        result=result,
        measure=measure,
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


@pytest.fixture
def two_tiles(make_tile):
    """Two tiles in the same family, told apart by their title."""
    first = make_tile(title="weathered crates")
    second = make_tile(title="stained crates")
    return first, second


def test_the_chooser_picks_an_eligible_tile(two_tiles):
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    choice = chooser.choose({"phase": "dusk"}, list(two_tiles))
    assert isinstance(choice, Choice)
    assert choice.tile_id in {tile.id for tile in two_tiles}
    assert choice.bucket == "phase=dusk"


def test_the_chooser_refuses_when_no_tile_is_eligible(two_tiles):
    from core.tiles.models import Precondition

    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    dusk_only = two_tiles[0].model_copy(
        update={
            "preconditions": (Precondition(key="phase", op="eq", value="dusk"),)
        }
    )
    with pytest.raises(TileRefusal) as exc:
        chooser.choose({"phase": "noon"}, [dusk_only])
    assert exc.value.reason == "no_eligible_tile"


def test_the_chooser_only_picks_tiles_whose_preconditions_hold(two_tiles):
    from core.tiles.models import Precondition

    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    dusk_only = two_tiles[0].model_copy(
        update={
            "preconditions": (Precondition(key="phase", op="eq", value="dusk"),)
        }
    )
    choice = chooser.choose({"phase": "noon"}, [dusk_only, two_tiles[1]])
    assert choice.tile_id == two_tiles[1].id


def test_the_chooser_explores(two_tiles):
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=1.0, seed=3)
    choice = chooser.choose({"phase": "dusk"}, list(two_tiles))
    assert choice.reason == "explore"


def test_a_cold_chooser_says_so(two_tiles):
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=3)
    choice = chooser.choose({"phase": "dusk"}, list(two_tiles))
    assert choice.reason == "cold"


def test_the_chooser_learns_the_winning_tile(two_tiles):
    good, bad = two_tiles
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    for _ in range(20):
        chooser.update(_record(good, {"phase": "dusk"}, 1.0))
        chooser.update(_record(bad, {"phase": "dusk"}, 0.0, result="lose"))

    choice = chooser.choose({"phase": "dusk"}, [good, bad])
    assert choice.tile_id == good.id
    assert choice.reason == "greedy"
    assert choice.score > 0.5


def test_the_chooser_keeps_the_contexts_apart(two_tiles):
    """The same tile can be right in one context and wrong in another."""
    dusk_good, noon_good = two_tiles
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    for _ in range(20):
        chooser.update(_record(dusk_good, {"phase": "dusk"}, 1.0))
        chooser.update(_record(noon_good, {"phase": "dusk"}, 0.0, result="lose"))
        chooser.update(_record(noon_good, {"phase": "noon"}, 1.0))
        chooser.update(_record(dusk_good, {"phase": "noon"}, 0.0, result="lose"))

    assert chooser.choose({"phase": "dusk"}, [dusk_good, noon_good]).tile_id == dusk_good.id
    assert chooser.choose({"phase": "noon"}, [dusk_good, noon_good]).tile_id == noon_good.id


def test_the_chooser_fits_from_play_records(two_tiles):
    good, bad = two_tiles
    records = [_record(good, {"phase": "dusk"}, 1.0) for _ in range(10)]
    records += [_record(bad, {"phase": "dusk"}, 0.0, result="lose") for _ in range(10)]

    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    chooser.fit(records)
    assert chooser.plays() == 20
    assert chooser.choose({"phase": "dusk"}, [good, bad]).tile_id == good.id


def test_the_chooser_is_deterministic_for_a_seed(two_tiles):
    first = ContextualBandit(feature_keys=("phase",), epsilon=0.5, seed=11)
    second = ContextualBandit(feature_keys=("phase",), epsilon=0.5, seed=11)
    picks_a = [first.choose({"phase": "dusk"}, list(two_tiles)).tile_id for _ in range(20)]
    picks_b = [second.choose({"phase": "dusk"}, list(two_tiles)).tile_id for _ in range(20)]
    assert picks_a == picks_b


def test_the_exploration_rate_decays_with_the_plays(two_tiles):
    good, bad = two_tiles
    chooser = ContextualBandit(
        feature_keys=("phase",), epsilon=0.25, epsilon_decay=0.9, min_epsilon=0.02, seed=1
    )
    start = chooser.current_epsilon()
    for _ in range(50):
        chooser.update(_record(good, {"phase": "dusk"}, 1.0))
    assert chooser.current_epsilon() < start
    assert chooser.current_epsilon() >= 0.02


def test_a_context_without_the_feature_is_its_own_bucket(two_tiles):
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    choice = chooser.choose({}, list(two_tiles))
    assert choice.bucket == "phase=<none>"


def test_a_chooser_with_no_features_is_one_bucket(two_tiles):
    chooser = ContextualBandit(epsilon=0.0, seed=1)
    assert chooser.bucket({"phase": "dusk"}) == ""
    assert chooser.bucket({}) == ""


def test_the_stats_say_what_the_chooser_knows(two_tiles):
    good, bad = two_tiles
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    chooser.update(_record(good, {"phase": "dusk"}, 1.0))
    stats = chooser.stats()
    assert stats["plays"] == 1
    assert stats["buckets"]["phase=dusk"][good.id]["plays"] == 1
    assert stats["overall"][good.id]["reward"] == 1.0
