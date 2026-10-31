"""The off-policy estimators: what a **new** chooser would have earned.

The estimators are checked against a ground truth that is exact rather than
against each other. A log is drawn from a logging policy whose value is
computable in closed form, with rewards whose means are known, so the
value of any target policy over that log is a number that can be written
down before the estimator runs.

The rules under test:

* the estimates are **unbiased on the logging policy** — with the target set
  to the logger, every estimator lands on the true value;
* the estimates are **unbiased off-policy** — with the target set to a
  different policy, they land on *that* policy's true value;
* every estimate carries its **denominator**, an **interval**, and the
  **weight diagnostics** that say whether the interval means anything;
* a play whose logging propensity is missing is **not weighted** — it is
  dropped and counted, never assumed;
* the **negative control**: propensities that are wrong make the estimate
  wrong, in the direction the corruption predicts, and SNIPS's blindness to
  a uniform scale error is measured rather than assumed;
* the **propensity the chooser records is the propensity it has** — the
  empirical frequency of a choice is checked against the number the
  chooser put on it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.tiles.chooser import ContextualBandit
from core.tiles.library import TileLibrary
from core.tiles.models import Outcome, PlayRecord, Tile, TileAuthor, TileStep
from core.tiles.ope import (
    BanditRewardModel,
    CrossFittedRewardModel,
    DeterministicTarget,
    FixedTarget,
    OPEError,
    SoftmaxTarget,
    corrupt_propensities,
    evaluate,
    weights_for,
)
from core.tiles.plays import fold_plays, record_play

#: The tiles of the synthetic log.
TILES = ("tile_a", "tile_b", "tile_c")

#: The probability that each tile wins, when it is played.
WIN_RATES = (0.2, 0.6, 0.9)

#: The logging policy's scores — a softmax over them is the probability of
#: each tile, and the policy is *not* uniform: a uniform log could not
#: tell a corrupted propensity from a correct one.
LOGGING_SCORES = {"tile_a": 0.0, "tile_b": 1.0, "tile_c": 2.0}

#: The target policy's scores — a chooser that prefers the good tile.
TARGET_SCORES = {"tile_a": 0.0, "tile_b": 2.0, "tile_c": 4.0}

#: How many plays the synthetic log holds.
PLAYS = 30000

#: The seed, so every number in the lab note is reproducible.
SEED = 20261031


def _softmax(scores: dict[str, float]) -> np.ndarray:
    raw = np.array([scores[tile] for tile in TILES], dtype=float)
    raw = raw - raw.max()
    weights = np.exp(raw)
    return weights / weights.sum()


def _policy_value(scores: dict[str, float]) -> float:
    """The exact value of a policy over the synthetic world's rewards."""
    return float(np.dot(_softmax(scores), np.array(WIN_RATES, dtype=float)))


#: The phases the synthetic world's nights go through. The context varies
#: on purpose: a reward model that buckets on it has to be *fitted* per
#: bucket, and a model fitted on the plays it predicts flatters itself
#: most where the bucket is rare.
PHASES = ("dusk", "dawn")


def _play(
    index: int,
    tile_id: str,
    reward: float,
    propensity: float | None,
    candidates: tuple[str, ...] = TILES,
) -> PlayRecord:
    """One synthetic play, with the propensity the logger drew it with."""
    return PlayRecord(
        id=f"play_{index:06d}",
        at="2026-10-31T00:00:00Z",
        tile_id=tile_id,
        tile_version=1,
        context={"phase": PHASES[index % len(PHASES)]},
        outcome=Outcome(
            result="win" if reward >= 1.0 else "lose",
            measure="critic",
            score=reward,
        ),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        propensity=propensity,
        candidates=tuple(candidates),
    )


def _synthetic_log(
    *,
    plays: int = PLAYS,
    seed: int = SEED,
    logging_scores: dict[str, float] | None = None,
) -> tuple[PlayRecord, ...]:
    """A log drawn from a known logging policy, with known rewards."""
    scores = logging_scores or LOGGING_SCORES
    probabilities = _softmax(scores)
    rng = np.random.default_rng(seed)
    records = []
    for index in range(plays):
        tile = int(rng.choice(len(TILES), p=probabilities))
        reward = 1.0 if rng.random() < WIN_RATES[tile] else 0.0
        records.append(
            _play(index, TILES[tile], reward, float(probabilities[tile]))
        )
    return tuple(records)


def _target(scores: dict[str, float] | None = None) -> SoftmaxTarget:
    return SoftmaxTarget(
        scores=lambda _context, tile_id: (scores or TARGET_SCORES)[tile_id],
        temperature=1.0,
        name="target",
    )


# --- the estimators on a log with an exact truth ----------------------------


def test_the_estimates_land_on_the_true_value_when_the_target_is_the_logger():
    """On-policy, every estimator is unbiased and the interval covers."""
    log = _synthetic_log()
    truth = _policy_value(LOGGING_SCORES)
    logger = _target(LOGGING_SCORES)

    for method in ("ips", "snips"):
        estimate = evaluate(log, logger, method=method)
        assert estimate.value == pytest.approx(truth, abs=4.0 * estimate.stderr)
        assert estimate.ci_low <= truth <= estimate.ci_high


def test_the_estimates_land_on_the_new_policys_true_value():
    """Off-policy, the estimate is the *target's* value, not the logger's."""
    log = _synthetic_log()
    truth = _policy_value(TARGET_SCORES)
    logger_value = _policy_value(LOGGING_SCORES)

    for method in ("ips", "snips"):
        estimate = evaluate(log, _target(), method=method)
        assert estimate.value == pytest.approx(truth, abs=4.0 * estimate.stderr)
        # It is the target's value, and it is a different number from the
        # logger's — otherwise the estimate is measuring the log.
        assert estimate.value > logger_value
        assert estimate.ci_low <= truth <= estimate.ci_high


def test_the_estimate_carries_its_denominator_and_its_diagnostics():
    log = _synthetic_log()
    estimate = evaluate(log, _target(), method="snips")

    assert estimate.n == PLAYS
    assert estimate.n_offered == PLAYS
    assert estimate.coverage == 1.0
    assert estimate.support == 1.0
    # The weights are the target's probability over the logger's, so they
    # are all in a narrow band: the effective sample size is most of n.
    assert estimate.effective_n > 0.8 * PLAYS
    assert estimate.max_weight < 2.0
    assert estimate.stderr > 0.0
    assert estimate.ci_low < estimate.value < estimate.ci_high
    assert "plays weighted" in estimate.basis


def test_the_doubly_robust_estimator_needs_a_reward_model():
    log = _synthetic_log()
    with pytest.raises(OPEError) as raised:
        evaluate(log, _target(), method="dr")
    assert raised.value.code == "no_reward_model"


def test_the_doubly_robust_estimator_lands_on_the_true_value():
    log = _synthetic_log()
    truth = _policy_value(TARGET_SCORES)

    class OracleRewardModel:
        """The best a reward model can be: the tile's true mean reward."""

        name = "oracle"

        def predict(self, record: PlayRecord, tile_id: str) -> float:
            return WIN_RATES[TILES.index(tile_id)]

    estimate = evaluate(log, _target(), method="dr", reward_model=OracleRewardModel())
    assert estimate.value == pytest.approx(truth, abs=4.0 * estimate.stderr)
    assert estimate.ci_low <= truth <= estimate.ci_high


def test_cross_fitting_never_narrows_the_doubly_robust_interval():
    """A reward model fitted on the plays it predicts flatters itself.

    Measured: at 200 plays the cross-fitted interval is wider by 2% of the
    standard error; at 30,000 the gap has vanished under the sixth
    decimal, because the reward's own noise dominates the model's error
    long before the log is big. Cross-fitting is correct and, at this
    size, nearly free.
    """
    truth = _policy_value(TARGET_SCORES)

    for plays in (200, PLAYS):
        log = _synthetic_log(plays=plays)

        chooser = ContextualBandit(feature_keys=("phase",))
        chooser.fit(log)
        in_sample = evaluate(
            log, _target(), method="dr", reward_model=BanditRewardModel(chooser)
        )
        cross = evaluate(
            log,
            _target(),
            method="dr",
            reward_model=CrossFittedRewardModel(
                log, folds=5, seed=SEED, feature_keys=("phase",)
            ),
        )

        # Both estimate the same thing...
        assert in_sample.value == pytest.approx(truth, abs=4.0 * in_sample.stderr)
        assert cross.value == pytest.approx(truth, abs=4.0 * cross.stderr)
        # ...but the in-sample model has seen the answer it is asked for, so
        # its residual is smaller and its interval is never wider.
        assert cross.stderr >= in_sample.stderr

    # On a short log the gap is there, and it is small.
    short = _synthetic_log(plays=200)
    chooser = ContextualBandit(feature_keys=("phase",))
    chooser.fit(short)
    in_sample = evaluate(
        short, _target(), method="dr", reward_model=BanditRewardModel(chooser)
    )
    cross = evaluate(
        short,
        _target(),
        method="dr",
        reward_model=CrossFittedRewardModel(
            short, folds=5, seed=SEED, feature_keys=("phase",)
        ),
    )
    assert cross.stderr > in_sample.stderr


# --- the negative control: propensities that are wrong ------------------------


def test_a_scaled_propensity_biases_ips_by_exactly_the_factor():
    """The control that keeps SNIPS honest.

    A propensity that is wrong by a constant factor scales every weight, so
    the IPS estimate scales with it — and the SNIPS estimate does not,
    because it divides by the sum of the weights. The bias is exactly the
    factor, and no diagnostic on the shape of the weights can see it.
    """
    log = _synthetic_log()
    truth = _policy_value(TARGET_SCORES)
    # Halved: the propensities stay possible (a probability is in (0, 1])
    # while every weight doubles.
    corrupted = corrupt_propensities(log, mode="scale", factor=0.5)

    ips = evaluate(corrupted, _target(), method="ips")
    snips = evaluate(corrupted, _target(), method="snips")

    # The IPS estimate scales with the corruption, exactly.
    assert ips.value == pytest.approx(2.0 * truth, abs=4.0 * ips.stderr)
    # The self-normalised one does not: it divides by the sum of the
    # weights, and a uniform scale cancels.
    assert snips.value == pytest.approx(truth, abs=4.0 * snips.stderr)
    # The effective sample size is a ratio of sums of weights, so a uniform
    # scale cancels there too: the diagnostic that answers "how many plays
    # are carrying this" cannot see the corruption either. The raw largest
    # weight can — it doubled — which is the only reason a scale error
    # would ever be noticed at all.
    honest = evaluate(log, _target(), method="snips")
    assert snips.effective_n == pytest.approx(honest.effective_n, rel=0.02)
    assert snips.max_weight == pytest.approx(2.0 * honest.max_weight, rel=0.02)


def test_a_uniform_propensity_pushes_the_estimate_out_of_the_reward_range():
    """The corruption a system that *guesses* a propensity produces."""
    log = _synthetic_log()
    truth = _policy_value(TARGET_SCORES)
    corrupted = corrupt_propensities(log, mode="uniform")

    ips = evaluate(corrupted, _target(), method="ips")
    # Every weight is now the target's probability times three, so the
    # estimate is pushed above what any play could pay.
    assert ips.value > 1.0
    assert not (ips.ci_low <= truth <= ips.ci_high)
    assert any("reward range" in warning for warning in ips.warnings)


def test_a_shuffled_propensity_decorrelates_the_weights_from_the_rewards():
    log = _synthetic_log()
    truth = _policy_value(TARGET_SCORES)
    logger_value = _policy_value(LOGGING_SCORES)
    corrupted = corrupt_propensities(log, mode="shuffle", seed=SEED)

    estimate = evaluate(corrupted, _target(), method="snips")
    honest = evaluate(log, _target(), method="snips")

    # The weights no longer say anything about which tile was played: the
    # estimate leaves the truth further than the honest one does.
    assert abs(estimate.value - truth) > abs(honest.value - truth)
    # And the weights are more spread out, so fewer of them carry the
    # estimate.
    assert estimate.effective_n < honest.effective_n
    assert logger_value != truth  # the two policies are not the same value


# --- what the estimator refuses ----------------------------------------------


def test_a_play_without_a_propensity_is_dropped_and_counted():
    log = _synthetic_log(plays=100)
    without = list(log[:50]) + [
        record.model_copy(update={"propensity": None}) for record in log[50:]
    ]

    estimate = evaluate(without, _target(), method="snips")
    assert estimate.n == 50
    assert estimate.n_offered == 100
    assert estimate.coverage == 0.5
    assert any("no logging propensity" in warning for warning in estimate.warnings)


def test_a_log_with_no_propensities_at_all_is_refused():
    log = [
        record.model_copy(update={"propensity": None}) for record in _synthetic_log(plays=10)
    ]
    with pytest.raises(OPEError) as raised:
        evaluate(log, _target(), method="snips")
    assert raised.value.code == "no_usable_plays"


def test_a_propensity_of_zero_is_a_refusal_not_a_number():
    log = list(_synthetic_log(plays=10))
    log[0] = log[0].model_copy(update={"propensity": 0.0})
    with pytest.raises(OPEError) as raised:
        evaluate(log, _target(), method="snips")
    assert raised.value.code == "bad_propensity"


def test_a_target_with_no_support_is_refused():
    """The target never agrees with the log: there is nothing to estimate."""
    log = _synthetic_log(plays=100)
    with pytest.raises(OPEError) as raised:
        evaluate(log, FixedTarget({"tile_never_played": 1.0}), method="snips")
    assert raised.value.code == "no_support"


def test_a_policy_without_the_candidate_set_is_refused():
    """A softmax needs the options to normalise over."""
    log = [
        record.model_copy(update={"candidates": ()})
        for record in _synthetic_log(plays=10)
    ]
    with pytest.raises(OPEError) as raised:
        evaluate(log, _target(), method="snips")
    assert raised.value.code == "no_candidates"


def test_a_deterministic_target_scores_the_plays_it_would_have_chosen():
    """The practical shape: "would the new chooser have picked this one?"."""
    log = _synthetic_log(plays=5000)
    estimate = evaluate(
        log,
        DeterministicTarget(pick=lambda _context, _candidates: "tile_c"),
        method="snips",
    )
    # It can only be weighted on the plays the logger also picked tile_c,
    # and its value is that tile's win rate.
    assert estimate.value == pytest.approx(WIN_RATES[2], abs=0.05)
    # The support is the logger's own frequency of that tile: the plays it
    # disagreed with carry no weight at all.
    assert estimate.support == pytest.approx(0.665, abs=0.05)
    assert estimate.effective_n < estimate.n


# --- the propensity the chooser records is the propensity it has ------------


def test_the_choosers_propensity_matches_the_frequency_it_chooses_at():
    """The number the record carries is the number the choice was drawn from.

    This is the link the whole module rests on: if the chooser wrote down a
    propensity that was not the probability of the choice it made, every
    weight downstream would be wrong in a way no estimator can detect.
    """
    chooser = ContextualBandit(epsilon=0.25, seed=7)
    tiles = _fake_tiles()

    counts = {tile_id: 0 for tile_id in TILES}
    draws = 20000
    for _ in range(draws):
        choice = chooser.choose({}, tiles)
        counts[choice.tile_id] += 1
        assert choice.propensity is not None

    # Nothing has been played, so every arm sits at the prior and the
    # greedy tile is the one the tie-break picks: the lowest id.
    greedy = min(TILES)
    for tile_id, count in counts.items():
        observed = count / draws
        if tile_id == greedy:
            expected = (1.0 - 0.25) + 0.25 / len(TILES)
        else:
            expected = 0.25 / len(TILES)
        assert observed == pytest.approx(expected, abs=0.02)


def test_a_forced_choice_has_a_propensity_of_one():
    """With no other option there is no exploration: the choice was certain."""
    chooser = ContextualBandit(seed=3)
    choice = chooser.choose({}, _fake_tiles()[:1])
    assert choice.propensity == 1.0
    assert choice.reason == "only_option"


def test_the_explore_branch_records_its_own_rate():
    """The exploration branch's propensity is eps / |eligible|."""
    chooser = ContextualBandit(epsilon=1.0, seed=11)
    tiles = _fake_tiles()
    props = []
    for _ in range(200):
        choice = chooser.choose({}, tiles)
        props.append((choice.reason, choice.propensity))
    explored = [p for reason, p in props if reason == "explore"]
    assert explored, "an always-exploring chooser never exploits"
    assert all(p == pytest.approx(1.0 / len(TILES)) for p in explored)


def _fake_tiles():
    """Three eligible tiles with no preconditions."""
    author = TileAuthor(
        model="fake/scripted-v1",
        provider="fake",
        prompt_hash="sha256:" + "0" * 64,
        cost_cents=0,
    )
    tiles = []
    for index, tile_id in enumerate(TILES):
        step = TileStep(word="props.harbor.crates", path="harbor.crates", params={})
        tiles.append(
            Tile(
                id=tile_id,
                version=1,
                family="harbor.crates.style",
                kind="recipe_edit",
                title=f"tile {index}",
                steps=(step,),
                author=author,
                status="active",
            )
        )
    return tuple(tiles)


# --- the propensity survives the log -----------------------------------------


def test_the_propensity_survives_the_ledger_round_trip(ledger, make_tile, registry):
    """What the log carries is what the fold gives back."""
    library = TileLibrary(registry=registry, ledger=ledger)
    tile = library.add(make_tile())
    record = record_play(
        ledger=ledger,
        library=library,
        tile=tile,
        context={"phase": "dusk"},
        outcome=Outcome(result="win", measure="critic"),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        propensity=0.375,
        candidates=(tile.id, "tile_other"),
    )
    folded = fold_plays(ledger.events())
    assert len(folded) == 1
    assert folded[0].propensity == pytest.approx(0.375)
    assert folded[0].candidates == (tile.id, "tile_other")
    assert folded[0].id == record.id


def test_the_weighted_plays_are_the_ones_that_can_be_weighted():
    log = list(_synthetic_log(plays=20))
    log[3] = log[3].model_copy(update={"propensity": None})
    weights, rewards, used, warnings = weights_for(log, _target())
    assert len(weights) == len(rewards) == len(used) == 19
    assert all(w > 0.0 for w in weights)
    assert any("no logging propensity" in warning for warning in warnings)


def test_the_bootstrap_interval_is_deterministic_and_wider():
    """A seeded bootstrap gives the same interval twice, and a wider one
    than the normal approximation when the weights are heavy-tailed."""
    log = _synthetic_log()
    first = evaluate(log, _target(), method="snips", bootstrap=500, seed=5)
    second = evaluate(log, _target(), method="snips", bootstrap=500, seed=5)
    assert (first.ci_low, first.ci_high) == (second.ci_low, second.ci_high)

    analytic = evaluate(log, _target(), method="snips")
    assert (first.ci_high - first.ci_low) >= (analytic.ci_high - analytic.ci_low)
