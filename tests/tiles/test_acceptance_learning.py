"""The acceptance run: the system's win rate rises above a uniform pick.

This is the seat's whole claim, exercised end to end:

1. a **scripted cloud author** writes K tiles — no real LLM call, the
   author sits behind the adapter and the adapter's fake is used;
2. a **simulated game** scores them over N plays — a play wins when the
   tile's style is the one the context asks for, with a seeded draw so the
   run is reproducible;
3. the **contextual bandit** chooses, and its win rate is compared with a
   **uniform pick** over the same contexts, with the difference stated as a
   **95% confidence interval** (Newcombe's method).

The claim under test is not "the chooser won a lot" — it is "the chooser
beat a uniform pick, and the interval on the difference does not include
zero". A win rate without that comparison is a number somebody could have
picked.
"""

from __future__ import annotations

import hashlib

import pytest

from core.night.ledger import InMemoryLedger
from core.tiles.chooser import ContextualBandit
from core.tiles.library import TileLibrary
from core.tiles.models import Outcome, Tile
from core.tiles.plays import fold_plays, record_play
from core.tiles.retrain import retrain
from core.tiles.stats import newcombe_difference, two_proportion_z

#: How many tiles the scripted author writes, and how many plays they get.
K_TILES = 6
N_PLAYS = 600

#: The three styles of the M1 slice's crates word — the context asks for
#: one of them, and a tile carries one in its params.
STYLES = ("plain", "weathered", "stained")

#: How often a play wins when the tile matches what the context asked for,
#: and when it does not. Not 1.0 and 0.0: a game is not a switch.
P_MATCH = 0.85
P_MISS = 0.15


def _spec(style: str, title: str) -> dict:
    """A tile the scripted author writes: the crates word, one style."""
    return {
        "family": "harbor.crates.style",
        "kind": "recipe_edit",
        "title": title,
        "steps": [
            {
                "word": "props.harbor.crates",
                "path": "harbor.crates",
                "params": {"count": 12, "style": style, "from_library": 0},
            }
        ],
    }


def _style_of(tile: Tile) -> str:
    """The style a tile carries — the thing the game rewards."""
    return str(tile.steps[0].params.get("style", ""))


def _draw(tile_id: str, bucket: str, play_index: int) -> float:
    """A seeded draw in [0, 1) for one play — reproducible, not random."""
    digest = hashlib.sha256(
        f"{tile_id}|{bucket}|{play_index}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _contexts(n: int, seed: int = 17) -> list[dict]:
    """The night's contexts — a seeded shuffle of the three styles."""
    import random

    rng = random.Random(seed)
    styles = [STYLES[index % len(STYLES)] for index in range(n)]
    rng.shuffle(styles)
    return [{"phase": "dusk", "wanted_style": style} for style in styles]


def _play_outcome(tile: Tile, context: dict, bucket: str, play_index: int) -> Outcome:
    """The simulated game's verdict on one play."""
    wanted = context["wanted_style"]
    chance = P_MATCH if _style_of(tile) == wanted else P_MISS
    won = _draw(tile.id, bucket, play_index) < chance
    return Outcome(
        result="win" if won else "lose",
        measure="critic",
        detail="the crates read the way the context asked for"
        if won
        else "the crates read wrong",
    )


@pytest.fixture
def library(registry, ledger):
    return TileLibrary(registry=registry, ledger=ledger)


def _author_tiles(library, registry):
    """The scripted cloud author writes the night's options."""
    from core.tiles.author import AuthorRequest, ScriptedAuthor

    specs = []
    for style in STYLES:
        for attempt in (1, 2):
            specs.append(_spec(style, f"{style} crates, take {attempt}"))

    author = ScriptedAuthor(specs, registry=registry)
    tiles = author.write(
        AuthorRequest(
            goal="make the crates read the way the builder wants them",
            words=("props.harbor.crates",),
        )
    )
    for tile in tiles:
        library.add(tile)
    return author, tiles


def _run_night(library, ledger, chooser, tiles, contexts, *, seed_offset: int = 0):
    """Play the night: choose, play, record, learn."""
    wins = 0
    picks: list[str] = []
    for index, context in enumerate(contexts):
        bucket = chooser.bucket(context)
        choice = chooser.choose(context, tiles)
        tile = library.require(choice.tile_id)
        outcome = _play_outcome(tile, context, bucket, index + seed_offset)
        record = record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser=chooser.name,
            chooser_version=chooser.version,
            night="night_2026-10-30",
        )
        chooser.update(record)
        picks.append(choice.tile_id)
        if outcome.result == "win":
            wins += 1
    return wins, picks


def _run_uniform(library, ledger, tiles, contexts, *, seed: int = 99):
    """The baseline: the same contexts, the same game, a uniform pick."""
    import random

    rng = random.Random(seed)
    wins = 0
    for index, context in enumerate(contexts):
        tile = rng.choice(tiles)
        bucket = f"wanted_style={context['wanted_style']}"
        outcome = _play_outcome(tile, context, bucket, index)
        record = record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser="uniform/baseline",
            chooser_version="1",
            night="night_2026-10-30",
        )
        if outcome.result == "win":
            wins += 1
    return wins, record


def test_the_chooser_beats_a_uniform_pick_with_a_stated_confidence(
    library, ledger, registry
):
    """The acceptance claim: the win rate rises above a uniform pick.

    The stated confidence is a 95% interval on the DIFFERENCE of the two
    win rates (Newcombe's method 10). The claim is that the interval does
    not include zero.
    """
    _, tiles = _author_tiles(library, registry)
    assert len(tiles) == K_TILES

    contexts = _contexts(N_PLAYS)
    chooser = ContextualBandit(
        feature_keys=("wanted_style",),
        epsilon=0.25,
        epsilon_decay=0.995,
        min_epsilon=0.02,
        seed=7,
    )
    chooser_wins, _ = _run_night(library, ledger, chooser, tiles, contexts)

    # The baseline is a COUNTERFACTUAL: its own log, so the night's log
    # holds the night's plays and nothing else.
    baseline_ledger = InMemoryLedger()
    baseline_ledger_wins, _ = _run_uniform(
        library, baseline_ledger, tiles, contexts
    )

    chooser_rate = chooser_wins / N_PLAYS
    baseline_rate = baseline_ledger_wins / N_PLAYS
    low, high = newcombe_difference(chooser_wins, N_PLAYS, baseline_ledger_wins, N_PLAYS)
    z, p = two_proportion_z(chooser_wins, N_PLAYS, baseline_ledger_wins, N_PLAYS)

    assert chooser_wins > baseline_ledger_wins, (
        f"the chooser won {chooser_wins}/{N_PLAYS} and a uniform pick won "
        f"{baseline_ledger_wins}/{N_PLAYS}"
    )
    assert low > 0.0, (
        f"the 95% interval on the difference [{low:.3f}, {high:.3f}] includes "
        f"zero: chooser {chooser_rate:.3f} vs uniform {baseline_rate:.3f} "
        f"(z={z:.2f}, p={p:.2e})"
    )


def test_the_win_rate_rises_over_the_night(library, ledger, registry):
    """It gets better as it learns: the second half beats the first."""
    _, tiles = _author_tiles(library, registry)
    contexts = _contexts(N_PLAYS)
    chooser = ContextualBandit(
        feature_keys=("wanted_style",), epsilon=0.25, epsilon_decay=0.995, seed=7
    )
    wins, _ = _run_night(library, ledger, chooser, tiles, contexts)

    half = N_PLAYS // 2
    records = fold_plays(ledger.events())
    first_half = sum(1 for r in records[:half] if r.won)
    second_half = sum(1 for r in records[half:] if r.won)

    assert wins == first_half + second_half
    assert second_half / half > first_half / half, (
        f"the first half won {first_half}/{half} and the second half "
        f"{second_half}/{half}"
    )


def test_the_chooser_learns_which_tile_wins_in_which_context(
    library, ledger, registry
):
    """After the night, the chooser picks the tile that matches the context."""
    _, tiles = _author_tiles(library, registry)
    contexts = _contexts(N_PLAYS)
    chooser = ContextualBandit(
        feature_keys=("wanted_style",), epsilon=0.25, epsilon_decay=0.995, seed=7
    )
    _run_night(library, ledger, chooser, tiles, contexts)

    for style in STYLES:
        context = {"phase": "dusk", "wanted_style": style}
        choice = chooser.choose(context, tiles)
        assert _style_of(library.require(choice.tile_id)) == style


def test_the_nightly_retrain_keeps_what_the_night_learned(library, ledger, registry):
    """The statistics are a fold over the log: a restart loses nothing.

    A fresh chooser, fitted from the ledger, must pick exactly what the
    chooser that lived through the night picks.
    """
    _, tiles = _author_tiles(library, registry)
    contexts = _contexts(N_PLAYS)
    chooser = ContextualBandit(
        feature_keys=("wanted_style",), epsilon=0.25, epsilon_decay=0.995, seed=7
    )
    _run_night(library, ledger, chooser, tiles, contexts)

    report = retrain(events=ledger.events(), library=library, chooser=chooser)
    assert report.plays == N_PLAYS
    assert report.scores, "the night scored no tiles"

    fresh = ContextualBandit(
        feature_keys=("wanted_style",), epsilon=0.0, seed=7
    )
    fresh.fit(fold_plays(ledger.events()))
    for style in STYLES:
        context = {"phase": "dusk", "wanted_style": style}
        assert fresh.choose(context, tiles).tile_id == chooser.choose(context, tiles).tile_id
