"""The nightly retrain: the loop that makes the system get better.

The rules under test:

* it learns from the **play records**, one measure at a time — the critic's
  verdict is not the owner's keep, and mixing them would let one become
  the other;
* every rate keeps its **denominator**, and carries an interval;
* the tiles that lost are **retired**, with the reason and their plays;
* the losers go back to the **cloud author** as a feedback packet, and what
  comes back is admitted as the next version of the family;
* the chooser is **refit** from the same records;
* the night is written to the log.
"""

from __future__ import annotations

import pytest

from core.tiles.chooser import ContextualBandit
from core.tiles.library import TileLibrary
from core.tiles.models import Outcome, PlayCost, Tile
from core.tiles.plays import record_play
from core.tiles.retrain import retrain


@pytest.fixture
def library(registry, ledger):
    return TileLibrary(registry=registry, ledger=ledger)


def _play(library, ledger, tile, *, result, measure="critic", context=None, night="night_2026-10-30"):
    return record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context=context or {"phase": "dusk"},
        outcome=Outcome(result=result, measure=measure),
        cost=PlayCost(),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        night=night,
    )


def test_the_retrain_scores_the_tiles(library, ledger, make_tile):
    good = library.add(make_tile(title="weathered crates"))
    bad = library.add(make_tile(title="stained crates"))
    for _ in range(4):
        _play(library, ledger, good, result="win")
        _play(library, ledger, bad, result="lose")

    report = retrain(events=ledger.events(), library=library)
    assert report.plays == 8
    assert len(report.scores) == 2
    assert report.scores[0].tile_id == good.id
    assert report.scores[0].basis == "4/4 won by critic"


def test_the_retrain_keeps_the_denominator_and_an_interval(library, ledger, make_tile):
    tile = library.add(make_tile())
    for _ in range(3):
        _play(library, ledger, tile, result="win")
    _play(library, ledger, tile, result="lose")

    report = retrain(events=ledger.events(), library=library)
    score = report.scores[0]
    assert score.plays == 4
    assert score.wins == 3
    assert score.win_rate == 0.75
    low, high = score.interval
    assert 0.0 <= low < score.win_rate < high <= 1.0


def test_the_retrain_retires_the_losers(library, ledger, make_tile):
    good = library.add(make_tile(title="weathered crates"))
    bad = library.add(make_tile(title="stained crates"))
    for _ in range(4):
        _play(library, ledger, good, result="win")
        _play(library, ledger, bad, result="lose")

    report = retrain(events=ledger.events(), library=library)
    assert report.retired == (bad.id,)
    assert library.get(bad.id).status == "retired"
    assert "lost 4/4" in library.get(bad.id).retire_reason
    assert library.get(good.id).status == "active"


def test_the_retrain_does_not_retire_a_tile_with_too_few_plays(library, ledger, make_tile):
    tile = library.add(make_tile())
    _play(library, ledger, tile, result="lose")

    report = retrain(events=ledger.events(), library=library, min_plays=3)
    assert report.retired == ()
    assert library.get(tile.id).status == "active"


def test_the_retrain_trains_on_one_measure_at_a_time(library, ledger, make_tile):
    """The critic's verdict is not the owner's keep."""
    tile = library.add(make_tile())
    for _ in range(4):
        _play(library, ledger, tile, result="lose", measure="critic")
    for _ in range(4):
        _play(library, ledger, tile, result="win", measure="owner_keep")

    critic = retrain(events=ledger.events(), library=library, measure="critic")
    owner = retrain(events=ledger.events(), library=library, measure="owner")

    assert critic.plays == 4
    assert critic.scores[0].wins == 0
    assert owner.plays == 4
    assert owner.scores[0].wins == 4


def test_the_retrain_feeds_the_losers_back_to_the_cloud(library, ledger, make_tile):
    from core.tiles.author import ScriptedAuthor

    bad = library.add(make_tile(title="stained crates"))
    for _ in range(4):
        _play(library, ledger, bad, result="lose")

    author = ScriptedAuthor(
        [
            {
                "family": "harbor.crates.style",
                "kind": "recipe_edit",
                "title": "weathered crates, take two",
                "steps": [
                    {
                        "word": "props.harbor.crates",
                        "path": "harbor.crates",
                        "params": {
                            "count": 12,
                            "style": "weathered",
                            "from_library": 0,
                        },
                    }
                ],
            }
        ]
    )
    report = retrain(events=ledger.events(), library=library, author=author)

    assert len(report.feedback) == 1
    packet = report.feedback[0]
    assert packet.tile_id == bad.id
    assert packet.plays == 4
    assert packet.wins == 0
    assert "here is why it lost" in packet.request
    assert author.calls[0].feedback == (packet,)

    assert len(report.new_tiles) == 1
    assert report.new_tiles[0].version == 2
    assert library.versions("harbor.crates.style")[1].id == report.new_tiles[0].id


def test_the_retrain_refits_the_chooser(library, ledger, make_tile):
    good = library.add(make_tile(title="weathered crates"))
    bad = library.add(make_tile(title="stained crates"))
    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    for _ in range(4):
        _play(library, ledger, good, result="win")
        _play(library, ledger, bad, result="lose")

    report = retrain(events=ledger.events(), library=library, chooser=chooser)
    assert chooser.plays() == report.plays
    assert chooser.choose({"phase": "dusk"}, [good, bad]).tile_id == good.id


def test_the_retrain_writes_the_log(library, ledger, make_tile):
    tile = library.add(make_tile())
    _play(library, ledger, tile, result="win")

    retrain(events=ledger.events(), library=library, ledger=ledger)
    types = [event.type for event in ledger.events()]
    assert types[-1] == "tile.retrained"
    payload = ledger.events()[-1].payload
    assert payload["plays"] == 1
    assert payload["measure"] == "critic"


def test_the_retrain_says_where_the_losers_lost(library, ledger, make_tile):
    tile = library.add(make_tile())
    for _ in range(3):
        _play(library, ledger, tile, result="lose", context={"phase": "dusk"})
    for _ in range(3):
        _play(library, ledger, tile, result="lose", context={"phase": "noon"})

    chooser = ContextualBandit(feature_keys=("phase",), epsilon=0.0, seed=1)
    report = retrain(events=ledger.events(), library=library, chooser=chooser)
    assert report.scores[0].contexts_lost == ("phase=dusk", "phase=noon")


def test_the_retrain_refuses_a_measure_it_cannot_train_on(library, ledger, make_tile):
    with pytest.raises(ValueError):
        retrain(events=ledger.events(), library=library, measure="vibes")


def test_the_report_has_a_line(library, ledger, make_tile):
    tile = library.add(make_tile())
    _play(library, ledger, tile, result="win")
    report = retrain(events=ledger.events(), library=library)
    assert "retrained on 1 plays by critic" in report.line()
    assert report.night == "night_2026-10-30"
