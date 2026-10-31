"""The numbers in ``docs/lab/exp-tiles-ope.md``, printed.

Run from the repo root::

    PYTHONPATH=. python docs/lab/tiles-ope-scripts/measure_ope.py

It needs nothing but numpy and the repo's own ``core.tiles``. The world it
measures is a synthetic one whose truth is exact: three tiles with known win
rates, a logging policy whose value is computable in closed form, and a
target policy whose value is computable the same way. Every estimate below
is checked against that truth, not against another estimator.
"""

from __future__ import annotations

import numpy as np

from core.tiles.chooser import ContextualBandit
from core.tiles.models import Outcome, PlayRecord, Tile, TileAuthor, TileStep
from core.tiles.ope import (
    BanditRewardModel,
    CrossFittedRewardModel,
    SoftmaxTarget,
    corrupt_propensities,
    evaluate,
)

TILES = ("tile_a", "tile_b", "tile_c")
WIN_RATES = (0.2, 0.6, 0.9)
LOGGING_SCORES = {"tile_a": 0.0, "tile_b": 1.0, "tile_c": 2.0}
TARGET_SCORES = {"tile_a": 0.0, "tile_b": 2.0, "tile_c": 4.0}
PLAYS = 30000
SEED = 20261031
PHASES = ("dusk", "dawn")


def softmax(scores: dict[str, float]) -> np.ndarray:
    raw = np.array([scores[tile] for tile in TILES], dtype=float)
    raw = raw - raw.max()
    weights = np.exp(raw)
    return weights / weights.sum()


def policy_value(scores: dict[str, float]) -> float:
    return float(np.dot(softmax(scores), np.array(WIN_RATES, dtype=float)))


def play(index: int, tile_id: str, reward: float, propensity: float) -> PlayRecord:
    return PlayRecord(
        id=f"play_{index:06d}",
        at="2026-10-31T00:00:00Z",
        tile_id=tile_id,
        tile_version=1,
        context={"phase": PHASES[index % len(PHASES)]},
        outcome=Outcome(
            result="win" if reward >= 1.0 else "lose", measure="critic", score=reward
        ),
        chooser="bandit/ctx-v1",
        chooser_version="1",
        propensity=propensity,
        candidates=TILES,
    )


def synthetic_log(plays: int = PLAYS, seed: int = SEED):
    probabilities = softmax(LOGGING_SCORES)
    rng = np.random.default_rng(seed)
    records = []
    for index in range(plays):
        tile = int(rng.choice(len(TILES), p=probabilities))
        reward = 1.0 if rng.random() < WIN_RATES[tile] else 0.0
        records.append(play(index, TILES[tile], reward, float(probabilities[tile])))
    return tuple(records)


def target(scores: dict[str, float] | None = None) -> SoftmaxTarget:
    return SoftmaxTarget(
        scores=lambda _context, tile_id: (scores or TARGET_SCORES)[tile_id],
        temperature=1.0,
        name="target",
    )


class OracleRewardModel:
    """The best a reward model can be: each tile's true mean reward."""

    name = "oracle"

    def predict(self, record: PlayRecord, tile_id: str) -> float:
        return WIN_RATES[TILES.index(tile_id)]


def fake_tiles() -> tuple[Tile, ...]:
    author = TileAuthor(
        model="fake/scripted-v1",
        provider="fake",
        prompt_hash="sha256:" + "0" * 64,
        cost_cents=0,
    )
    tiles = []
    for index, tile_id in enumerate(TILES):
        tiles.append(
            Tile(
                id=tile_id,
                version=1,
                family="harbor.crates.style",
                kind="recipe_edit",
                title=f"tile {index}",
                steps=(
                    TileStep(
                        word="props.harbor.crates", path="harbor.crates", params={}
                    ),
                ),
                author=author,
                status="active",
            )
        )
    return tuple(tiles)


def rule(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main() -> None:
    log = synthetic_log()
    truth = policy_value(TARGET_SCORES)
    logger_value = policy_value(LOGGING_SCORES)

    rule("1. the truth")
    print(f"logging policy's value        {logger_value:.6f}")
    print(f"target policy's value         {truth:.6f}")
    print(f"plays                         {PLAYS}")
    print(f"logging probabilities         {np.round(softmax(LOGGING_SCORES), 6)}")
    print(f"target probabilities          {np.round(softmax(TARGET_SCORES), 6)}")

    rule("2. the estimates, on the target policy")
    for method in ("ips", "snips"):
        estimate = evaluate(log, target(), method=method)
        print(
            f"{method.upper():5s} {estimate.value:.6f}  "
            f"CI [{estimate.ci_low:.6f}, {estimate.ci_high:.6f}]  "
            f"se {estimate.stderr:.6f}  ESS {estimate.effective_n:.1f}  "
            f"max w {estimate.max_weight:.4f}"
        )
    dr = evaluate(log, target(), method="dr", reward_model=OracleRewardModel())
    print(
        f"{'DR':5s} {dr.value:.6f}  "
        f"CI [{dr.ci_low:.6f}, {dr.ci_high:.6f}]  "
        f"se {dr.stderr:.6f}  ESS {dr.effective_n:.1f}  "
        f"max w {dr.max_weight:.4f}"
    )

    rule("3. the same estimates, on the logging policy")
    for method in ("ips", "snips"):
        estimate = evaluate(log, target(LOGGING_SCORES), method=method)
        print(
            f"{method.upper():5s} {estimate.value:.6f}  "
            f"CI [{estimate.ci_low:.6f}, {estimate.ci_high:.6f}]  "
            f"(truth {logger_value:.6f})"
        )

    rule("4. the reward model fitted on the log (in-sample) and cross-fitted")
    chooser = ContextualBandit(feature_keys=("phase",))
    chooser.fit(log)
    in_sample = evaluate(
        log, target(), method="dr", reward_model=BanditRewardModel(chooser)
    )
    cross = evaluate(
        log,
        target(),
        method="dr",
        reward_model=CrossFittedRewardModel(
            log, folds=5, seed=SEED, feature_keys=("phase",)
        ),
    )
    print(f"in-sample   {in_sample.value:.6f}  se {in_sample.stderr:.6f}")
    print(f"cross-fitted {cross.value:.6f}  se {cross.stderr:.6f}")

    rule("5. the negative control: wrong propensities")
    honest = evaluate(log, target(), method="snips")
    scaled = corrupt_propensities(log, mode="scale", factor=0.5)
    uniform = corrupt_propensities(log, mode="uniform")
    shuffled = corrupt_propensities(log, mode="shuffle", seed=SEED)
    for name, corrupted in (
        ("scaled x0.5", scaled),
        ("uniform", uniform),
        ("shuffled", shuffled),
    ):
        ips = evaluate(corrupted, target(), method="ips")
        snips = evaluate(corrupted, target(), method="snips")
        print(
            f"{name:11s} IPS {ips.value:9.6f}   SNIPS {snips.value:9.6f}   "
            f"ESS {snips.effective_n:8.1f}  max w {snips.max_weight:.4f}"
        )
    print(f"{'honest':11s} IPS {honest.value:9.6f}   SNIPS {honest.value:9.6f}   "
          f"ESS {honest.effective_n:8.1f}  max w {honest.max_weight:.4f}")
    print(f"truth: {truth:.6f}   logger's value: {logger_value:.6f}")

    rule("6. the propensity the chooser records is the propensity it has")
    chooser = ContextualBandit(epsilon=0.25, seed=7)
    tiles = fake_tiles()
    counts = {tile_id: 0 for tile_id in TILES}
    draws = 20000
    for _ in range(draws):
        choice = chooser.choose({}, tiles)
        counts[choice.tile_id] += 1
    greedy = min(TILES)
    print(f"draws {draws}, epsilon 0.25, three eligible tiles")
    for tile_id, count in counts.items():
        observed = count / draws
        expected = (
            (1.0 - 0.25) + 0.25 / len(TILES)
            if tile_id == greedy
            else 0.25 / len(TILES)
        )
        print(
            f"  {tile_id}  observed {observed:.4f}  recorded {expected:.4f}  "
            f"difference {observed - expected:+.4f}"
        )


if __name__ == "__main__":
    main()
