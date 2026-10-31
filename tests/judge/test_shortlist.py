"""The first caller: the tiles shortlist, with the judge as the cold-start prior.

The brief's wiring, exercised: the judge answers ``choice`` over the
chooser's K candidates for a context; **the bandit is kept** — the
judge's distribution is the bandit's *prior mean* over the tiles in a
cold context bucket, exactly where the pseudo-observations sat before —
and as plays accumulate the estimate washes the prior out at the rate
the bandit's own prior count sets. Every play keeps the propensity the
chooser measured at the choice, so the log stays off-policy evaluable.

The judge row itself (author, distribution, cost) is in the ledger —
the play carries the propensity; the judgment carries the why.
"""

from __future__ import annotations

import pytest

from core.judge.backends import FakeBackend
from core.judge.judge import Judge
from core.judge.shortlist import JudgePriorChooser
from core.night.ledger import InMemoryLedger
from core.tiles.chooser import ContextualBandit, TileChooser
from core.tiles.library import TileLibrary
from core.tiles.models import Outcome
from core.tiles.ope import FixedTarget, evaluate
from core.tiles.plays import fold_plays, record_play

STYLES = ("plain", "weathered", "stained")


@pytest.fixture
def library(registry, ledger):
    return TileLibrary(registry=registry, ledger=ledger)


@pytest.fixture
def six_tiles(library, make_tile):
    """The acceptance rig's six tiles, admitted: two per style, like the rig's."""
    tiles = []
    for style in STYLES:
        for take in (1, 2):
            tiles.append(make_tile(style=style, title=f"{style} crates, take {take}"))
    for tile in tiles:
        library.add(tile)
    return tiles


def _context(style: str) -> dict:
    return {"phase": "dusk", "wanted_style": style}


def _script_by_style(six_tiles, weights: dict[str, float]) -> dict[str, float]:
    """A script keyed the way the question is keyed: by tile id, not by style.

    The question's option keys are tile ids; a test that thinks in
    styles states its weights per style and this translates. Each
    style's mass lands on its lowest-id tile (the rig's two takes are
    near-duplicates; the model would break the tie somehow), so a
    script's confidence is the weight it names.
    """
    distribution = {tile.id: 0.0 for tile in six_tiles}
    for style, weight in weights.items():
        first = min(
            (tile.id for tile in six_tiles if tile.steps[0].params["style"] == style),
            default=None,
        )
        if first is not None:
            distribution[first] = weight
    return distribution


def _judged_chooser(library, ledger, six_tiles, weights, **kwargs) -> JudgePriorChooser:
    judge = Judge(
        backend=FakeBackend(script={"tile": _script_by_style(six_tiles, weights)}),
        ledger=ledger,
    )
    return JudgePriorChooser(judge, feature_keys=("wanted_style",), **kwargs)


# --- the cold start -----------------------------------------------------------


def test_a_cold_bucket_chooses_what_the_judge_says(library, ledger, six_tiles):
    chooser = _judged_chooser(
        library, ledger, six_tiles, {"plain": 0.2, "weathered": 0.7, "stained": 0.1}
    )
    choice = chooser.choose(_context("weathered"), six_tiles)
    chosen = next(t for t in six_tiles if t.id == choice.tile_id)
    assert chosen.steps[0].params["style"] == "weathered"
    # the score of the choice is the judge's prior mean for that tile
    assert choice.score == pytest.approx(0.7)


def test_the_judge_is_asked_once_per_bucket(library, ledger, six_tiles):
    chooser = _judged_chooser(
        library,
        ledger,
        six_tiles,
        {"plain": 0.4, "weathered": 0.35, "stained": 0.25},
        epsilon=0.0,
    )
    for _ in range(5):
        chooser.choose(_context("plain"), six_tiles)
    for _ in range(5):
        chooser.choose(_context("stained"), six_tiles)
    assert chooser.judge_calls == 2  # one per bucket, not one per play


def test_only_eligible_tiles_are_candidates(library, ledger, six_tiles):
    """A tile whose precondition fails is not an option; it is not judged either."""
    eligible_only = six_tiles[:4]
    seen = {}

    class RecordingJudge(Judge):
        def judge(self, task, state, questions, **kwargs):
            seen["criteria"] = dict(questions[0].criteria)
            return super().judge(task, state, questions, **kwargs)

    chooser = JudgePriorChooser(
        RecordingJudge(backend=FakeBackend(), ledger=ledger),
        feature_keys=("wanted_style",),
    )
    chooser.choose(_context("plain"), eligible_only)
    assert len(seen["criteria"]) == 4
    assert set(seen["criteria"]) <= {t.id for t in eligible_only}


def test_a_single_candidate_needs_no_judgment(library, ledger, make_tile):
    only = make_tile(style="plain")
    chooser = _judged_chooser(
        library, ledger, [only], {"plain": 0.9, "weathered": 0.1}
    )
    choice = chooser.choose(_context("plain"), [only])
    assert choice.tile_id == only.id
    assert chooser.judge_calls == 0


def test_the_judge_row_lands_in_the_ledger_with_its_distribution(
    library, ledger, six_tiles
):
    from core.judge.judge import fold_judgments

    chooser = _judged_chooser(
        library, ledger, six_tiles, {"plain": 0.2, "weathered": 0.7, "stained": 0.1}
    )
    chooser.choose(_context("weathered"), six_tiles)
    (entry,) = fold_judgments(ledger.events())
    assert entry["author"] == "judge@fake:fake/scripted-v1"
    # the judge's distribution is over the candidates the chooser offered
    assert sum(entry["distribution"].values()) == pytest.approx(1.0)
    top_tile, top_probability = max(
        entry["distribution"].items(), key=lambda item: item[1]
    )
    assert top_probability == pytest.approx(0.7)
    chosen = next(t for t in six_tiles if t.id == top_tile)
    assert chosen.steps[0].params["style"] == "weathered"
    assert entry["task"] == "tiles.shortlist"


# --- the bandit is kept -------------------------------------------------------


def test_plays_wash_the_prior_out(library, ledger, make_tile):
    """The judge says plain; the game rewards weathered; the bandit follows the game."""
    tiles = [make_tile(style=style, title=f"{style} crates") for style in STYLES]
    for tile in tiles:
        library.add(tile)
    chooser = _judged_chooser(
        library,
        ledger,
        tiles,
        {"plain": 0.8, "weathered": 0.1, "stained": 0.1},
        epsilon=0.0,  # greedy only: every pick is the estimate's argmax
    )
    context = _context("plain")
    bucket = chooser.bucket(context)
    weathered = next(t for t in tiles if t.steps[0].params["style"] == "weathered")

    cold = chooser.choose(context, tiles)
    assert cold.score == pytest.approx(0.8)  # the judge's prior, cold

    for _ in range(30):
        choice = chooser.choose(context, tiles)
        tile = next(t for t in tiles if t.id == choice.tile_id)
        outcome = Outcome(
            result="win" if tile.id == weathered.id else "lose", measure="critic"
        )
        record = record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser=chooser.name,
            chooser_version=chooser.version,
        )
        chooser.update(record)

    assert chooser.choose(context, tiles).tile_id == weathered.id
    # and the prior is now a rounding error beside thirty plays
    assert chooser.estimate(bucket, weathered.id) > 0.9


def test_a_surfaced_judge_leaves_the_bandit_its_own_prior(library, ledger, six_tiles):
    """Below τ with nowhere to escalate: surfaced, not acted on — no prior is set.

    The chooser must not act on the surfaced judgment; the bandit keeps
    its own flat prior and picks as it would have.
    """
    from core.judge.gate import ConfidencePolicy

    flat = {tile.id: 1.0 / len(six_tiles) for tile in six_tiles}  # confidence 1/6 < τ
    judge = Judge(
        backend=FakeBackend(script={"tile": flat}),
        policy=ConfidencePolicy(default=0.5),
        ledger=ledger,
    )
    chooser = JudgePriorChooser(judge, feature_keys=("wanted_style",), epsilon=0.0)
    choice = chooser.choose(_context("plain"), six_tiles)
    assert chooser.judge_surfaced == 1
    # a flat prior: every estimate is 0.5, and the tie is broken by tile id —
    # which is what a plain bandit would have done
    plain = ContextualBandit(feature_keys=("wanted_style",), epsilon=0.0)
    assert choice.tile_id == plain.choose(_context("plain"), six_tiles).tile_id


def test_the_chooser_satisfies_the_tilechooser_door(library, ledger, six_tiles):
    chooser = _judged_chooser(
        library, ledger, six_tiles, {"plain": 0.4, "weathered": 0.4, "stained": 0.2}
    )
    assert isinstance(chooser, TileChooser)
    assert isinstance(chooser, ContextualBandit)


# --- the propensity, and OPE --------------------------------------------------


def test_every_play_keeps_a_propensity_and_ope_can_read_the_log(
    library, ledger, six_tiles
):
    chooser = _judged_chooser(
        library,
        ledger,
        six_tiles,
        {"plain": 0.7, "weathered": 0.2, "stained": 0.1},
        epsilon=0.1,
        epsilon_decay=1.0,
    )
    context = _context("plain")
    for index in range(40):
        choice = chooser.choose(context, six_tiles)
        tile = next(t for t in six_tiles if t.id == choice.tile_id)
        outcome = Outcome(result="win" if index % 3 else "lose", measure="critic")
        record_play(
            ledger=ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            chooser=chooser.name,
            chooser_version=chooser.version,
            propensity=choice.propensity,
            candidates=tuple(t.id for t in six_tiles),
        )

    plays = fold_plays(ledger.events())
    assert len(plays) == 40
    assert all(play.propensity is not None for play in plays), (
        "a play without its propensity cannot be weighted — never defaulted"
    )
    assert all(0.0 < play.propensity <= 1.0 for play in plays)

    # the log is off-policy evaluable: what would a fixed target have earned?
    target = FixedTarget(probabilities={t.id: 1.0 / len(six_tiles) for t in six_tiles})
    estimate = evaluate(plays, target, method="ips")
    assert 0.0 <= estimate.value <= 1.0
