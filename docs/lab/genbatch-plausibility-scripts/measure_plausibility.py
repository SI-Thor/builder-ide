"""The numbers in ``docs/lab/exp-genbatch-plausibility.md``, printed.

Run from the repo root::

    PYTHONPATH=. python docs/lab/genbatch-plausibility-scripts/measure_plausibility.py

It needs nothing but numpy and the repo's own ``core.genbatch``. The world
it measures is a synthetic one with **known ground truth**: the approved
set is drawn from two kinds of real object with known labels, so
"plausible" and "implausible" are facts about the world the toy was built
from, not opinions about the scores.
"""

from __future__ import annotations

import numpy as np

from core.genbatch.plausibility import (
    FEATURE_NAMES,
    PropFeatures,
    ReferencePrior,
    fiber_width,
    judge,
)

#: The two kinds of real object in the toy. The plank is rare: 20 in 200.
MODES = {
    "mug": {
        "count": 180,
        "fill_ratio": (0.68, 0.06),
        "elongation": (1.45, 0.18),
        "log_volume": (0.0, 0.22),
    },
    "plank": {
        "count": 20,
        "fill_ratio": (0.27, 0.035),
        "elongation": (3.9, 0.55),
        "log_volume": (0.55, 0.30),
    },
}

QUIET = {
    "sphericity": (5.6, 0.5),
    "offcentre": (0.08, 0.03),
    "defect_rate": (0.002, 0.001),
}

SEED = 20261031

GHOST = PropFeatures(
    log_volume=-2.5,
    sphericity=30.0,
    elongation=12.0,
    fill_ratio=0.02,
    offcentre=0.4,
    defect_rate=0.0,
)


def features(rng: np.random.Generator, mode: str) -> PropFeatures:
    spec = MODES[mode]
    quiet = {name: rng.normal(*QUIET[name]) for name in QUIET}
    return PropFeatures(
        log_volume=float(rng.normal(*spec["log_volume"])),
        sphericity=float(quiet["sphericity"]),
        elongation=float(rng.normal(*spec["elongation"])),
        fill_ratio=float(rng.normal(*spec["fill_ratio"])),
        offcentre=float(quiet["offcentre"]),
        defect_rate=float(quiet["defect_rate"]),
    )


def reference_set():
    rng = np.random.default_rng(SEED)
    out = []
    for mode, spec in MODES.items():
        for _ in range(spec["count"]):
            out.append(features(rng, mode))
    return out


def rule(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def median_score(prior: ReferencePrior, mode: str, count: int = 200) -> float:
    rng = np.random.default_rng(SEED + 11)
    scores = [prior.score(features(rng, mode)).score for _ in range(count)]
    return float(np.median(scores))


def main() -> None:
    reference = reference_set()
    grouped = ReferencePrior(reference, clusters=2, seed=SEED)
    pooled = ReferencePrior(reference, clusters=1, seed=SEED)

    rule("1. the prior")
    print(f"approved objects            {len(reference)}")
    print(f"grouped prior: groups       {grouped.group_sizes}")
    print(f"grouped prior: ordinary width {grouped.ordinary_width:.4f}")
    print(f"plausibility spread         {grouped.plausibility_spread():.4f}")

    rule("2. the median plausibility of a fresh prop, by kind")
    print(f"{'kind':8s} {'grouped':>10s} {'pooled':>10s}")
    for mode in ("mug", "plank"):
        print(
            f"{mode:8s} {median_score(grouped, mode):10.4f} "
            f"{median_score(pooled, mode):10.4f}"
        )
    print("(the plank is 20 of 200: a pooled prior calls it a ghost)")

    rule("3. the ghost: a valid solid, the wrong shape for anything")
    score = grouped.score(GHOST)
    print(f"plausibility                {score.score:.6f}")
    print(f"distance to its group       {score.distance:.4f}")
    for name, tail in zip(FEATURE_NAMES, score.percentiles):
        print(f"  {name:14s} tail {tail:.4f}   value {getattr(GHOST, name):+.4f}")

    rule("4. the control: a consistency-only critic passes the ghost")
    consistency_population = [0.980 + 0.0004 * index for index in range(50)]
    ghost_verdict = judge(
        features=GHOST,
        consistency=0.99,
        prior=grouped,
        consistency_population=consistency_population,
    )
    rng = np.random.default_rng(SEED + 13)
    real = [
        judge(
            features=features(rng, "mug"),
            consistency=0.985,
            prior=grouped,
            consistency_population=consistency_population,
        )
        for _ in range(200)
    ]
    real_plausibility = float(np.median([v.plausibility for v in real]))
    real_combined = float(np.median([v.combined for v in real]))
    print(f"ghost:   consistency {ghost_verdict.consistency:.4f}  "
          f"plausibility {ghost_verdict.plausibility:.4f}  "
          f"two-sided {ghost_verdict.combined:.4f}")
    print(f"a real prop (median of 200): plausibility {real_plausibility:.4f}  "
          f"two-sided {real_combined:.4f}")
    print(f"the consistency-only critic sees {ghost_verdict.consistency:.4f} "
          "for the ghost and passes it")

    rule("5. the measured scale gap")
    gap = grouped.consistency_gap(consistency_population)
    print(f"consistency population       [{consistency_population[0]:.4f}, "
          f"{consistency_population[-1]:.4f}]")
    print(f"consistency spread           {np.std(consistency_population, ddof=1):.6f}")
    print(f"plausibility spread          {grouped.plausibility_spread():.6f}")
    print(f"the gap                      {gap:.6f}")
    print("  (the consistency side is that many times narrower than the")
    print("   plausibility side: a fixed weighting would have ignored it)")

    rule("6. the ambiguity gate")
    rng = np.random.default_rng(SEED + 17)
    agreeing = [features(rng, "mug") for _ in range(3)]
    disagreeing = [features(rng, "mug"), features(rng, "plank")]
    print(f"ordinary width (real objects of one kind) {grouped.ordinary_width:.4f}")
    print(f"three reconstructions of a clear image      "
          f"{fiber_width(agreeing, grouped):.4f}")
    print(f"two reconstructions of an ambiguous image    "
          f"{fiber_width(disagreeing, grouped):.4f}")
    verdict = judge(
        features=features(rng, "mug"),
        consistency=0.99,
        prior=grouped,
        reconstructions=disagreeing,
        consistency_population=consistency_population,
    )
    print(f"verdict: ambiguous={verdict.ambiguous}  escalate={verdict.escalate}")
    print(f"         {verdict.reason}")


if __name__ == "__main__":
    main()
