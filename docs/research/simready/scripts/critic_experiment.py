"""Measure the SimReady priors against the prop critic's test set.

**The question.** The brief asks whether the priors that SimReady carries —
mass, size, material, category — give the plausibility critic real-world
priors, and in particular whether they *flag the known-bad props in the
critic's test set*.

**The test set has ground truth.** ``tests/genbatch/test_plausibility.py``
builds a toy world with two kinds of real object (a **mug**, 180 of 200
approved assets, and a **plank**, 20 of 200), and a **ghost** — a valid
solid whose shape is the wrong shape for anything. The test file calls the
ghost the control a consistency-only critic cannot pass, and asserts its
plausibility score is below 0.05.

**What is measured here.**

1. The critic's own prior, fitted on its own toy approved set, scoring the
   ghost — the baseline that already passes.
2. The critic's prior refitted on the SimReady sample (the same six
   features, measured by the critic's own pipeline over the SimReady GLBs),
   scoring the same ghost.
3. Where the ghost and the toy mug and plank sit **per feature** inside the
   SimReady distribution — the percentiles, so the reason for the answer is
   visible and not just asserted.
4. Whether the SimReady prior flags the critic's **own approved set**, which
   is the other direction of the same question.

The measurement is a rank inside a small group, so the scores are coarse.
That is stated rather than smoothed over.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BUILDER_IDE = Path("/home/caseydigennaro/src/builder-ide")

#: The ghost, as the critic's test file defines it.
GHOST = {
    "log_volume": -2.5,
    "sphericity": 30.0,
    "elongation": 12.0,
    "fill_ratio": 0.02,
    "offcentre": 0.4,
    "defect_rate": 0.0,
}


def percentile(value: float, population: list[float]) -> float:
    """The mid-p percentile of a value inside a population."""
    if not population:
        return float("nan")
    below = sum(1 for other in population if other < value)
    equal = sum(1 for other in population if other == value)
    return (below + 0.5 * equal + 0.5) / (len(population) + 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="the sample report JSON")
    parser.add_argument("--glb-dir", required=True, help="where the GLBs are")
    parser.add_argument("--out", required=True, help="where to write the measurement")
    args = parser.parse_args()

    sys.path.insert(0, str(BUILDER_IDE))
    from core.genbatch.glb import read_glb
    from core.genbatch.mesh import measure_mesh
    from core.genbatch.plausibility import (
        FEATURE_NAMES,
        PropFeatures,
        ReferencePrior,
        features_from_report,
    )
    from tests.genbatch import test_plausibility as critic_test

    report_rows = json.loads(Path(args.report).read_text())
    glb_dir = Path(args.glb_dir)

    # -- the SimReady reference set, measured by the critic's own pipeline ---
    simready: dict[str, dict] = {}
    for row in report_rows:
        asset = row["asset"]
        path = glb_dir / f"{asset}.glb"
        if not path.exists():
            continue
        glb = read_glb(path)
        mesh_report = measure_mesh(glb.mesh)
        features = features_from_report(mesh_report)
        simready[asset] = {
            "features": features,
            "vector": features.as_vector(),
            "watertight": bool(mesh_report.watertight),
            "volume": float(mesh_report.volume),
            "area": float(mesh_report.area),
            "extent": [float(v) for v in mesh_report.extent],
        }

    reference = [row["features"] for row in simready.values()]
    populations = {
        name: [float(row["vector"][index]) for row in simready.values()]
        for index, name in enumerate(FEATURE_NAMES)
    }
    watertight_reference = [
        row["features"] for row in simready.values() if row["watertight"]
    ]

    # -- the critic's own toy world -------------------------------------------
    toy_reference, toy_labels = critic_test._reference_set()
    toy_prior = ReferencePrior(toy_reference, clusters=2, seed=critic_test.SEED)
    ghost = PropFeatures(**GHOST)
    toy_ghost = toy_prior.score(ghost)

    rng = np.random.default_rng(critic_test.SEED + 3)
    toy_mug = [critic_test._features(rng, "mug") for _ in range(60)]
    toy_plank = [critic_test._features(rng, "plank") for _ in range(60)]
    real_mug = critic_test._features(np.random.default_rng(critic_test.SEED + 3), "mug")

    out: dict = {
        "simready_reference": {
            "assets": len(reference),
            "watertight": len(watertight_reference),
            "features": list(FEATURE_NAMES),
        },
        "baseline_the_critics_own_prior": {
            "reference": "the toy approved set (180 mugs, 20 planks)",
            "ghost_score": toy_ghost.score,
            "ghost_distance": toy_ghost.distance,
            "ghost_flagged": bool(toy_ghost.score < 0.05),
            "mug_median_score": float(
                np.median([toy_prior.score(f).score for f in toy_mug])
            ),
            "plank_median_score": float(
                np.median([toy_prior.score(f).score for f in toy_plank])
            ),
        },
        "simready_prior": {},
        "per_feature_percentiles_in_the_simready_set": {},
        "simready_assets_scored_against_the_toy_prior": {},
    }

    # -- the same prior, refitted on SimReady ---------------------------------
    for clusters in (2, 3):
        prior = ReferencePrior(reference, clusters=clusters, seed=0)
        score = prior.score(ghost)
        simready_scores = [prior.score(f).score for f in reference]
        out["simready_prior"][str(clusters)] = {
            "group_sizes": list(prior.group_sizes),
            "ghost_score": score.score,
            "ghost_distance": score.distance,
            "ghost_cluster": score.cluster,
            "ghost_flagged_below_005": bool(score.score < 0.05),
            "ghost_distance_beyond_3": bool(score.distance > 3.0),
            "ghost_per_feature_tails": list(score.percentiles),
            "mug_median_score": float(
                np.median([prior.score(f).score for f in toy_mug])
            ),
            "plank_median_score": float(
                np.median([prior.score(f).score for f in toy_plank])
            ),
            "simready_own_median_score": float(np.median(simready_scores)),
            "simready_own_min_score": float(np.min(simready_scores)),
            "separates_ghost_from_mug": bool(
                prior.score(ghost).score < np.median([prior.score(f).score for f in toy_mug])
            ),
        }

    # -- where the ghost sits, per feature ------------------------------------
    out["per_feature_percentiles_in_the_simready_set"]["ghost"] = {
        name: percentile(GHOST[name], populations[name]) for name in FEATURE_NAMES
    }
    out["per_feature_percentiles_in_the_simready_set"]["toy_mug_median"] = {
        name: percentile(float(np.median([getattr(f, name) for f in toy_mug])), populations[name])
        for name in FEATURE_NAMES
    }
    out["per_feature_percentiles_in_the_simready_set"]["toy_plank_median"] = {
        name: percentile(float(np.median([getattr(f, name) for f in toy_plank])), populations[name])
        for name in FEATURE_NAMES
    }
    out["per_feature_percentiles_in_the_simready_set"]["ranges"] = {
        name: {
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "median": float(np.median(values)),
        }
        for name, values in populations.items()
    }

    # -- the other direction: does the SimReady set survive the toy prior? ---
    toy_scores = [toy_prior.score(f).score for f in reference]
    out["simready_assets_scored_against_the_toy_prior"] = {
        "median_score": float(np.median(toy_scores)),
        "min_score": float(np.min(toy_scores)),
        "max_score": float(np.max(toy_scores)),
        "share_below_005": float(
            sum(1 for s in toy_scores if s < 0.05) / max(len(toy_scores), 1)
        ),
        "share_below_020": float(
            sum(1 for s in toy_scores if s < 0.20) / max(len(toy_scores), 1)
        ),
    }

    # -- the shell finding ----------------------------------------------------
    watertight_population = {
        name: [
            float(row["vector"][index])
            for row in simready.values()
            if row["watertight"]
        ]
        for index, name in enumerate(FEATURE_NAMES)
    }
    out["solid_versus_shell"] = {
        "note": (
            "the critic's features are computed from the signed volume of a "
            "closed mesh; a hollow object encloses only its wall material, so "
            "its fill ratio is small"
        ),
        "fill_ratio_all_assets": {
            "min": float(np.min(populations["fill_ratio"])),
            "median": float(np.median(populations["fill_ratio"])),
            "max": float(np.max(populations["fill_ratio"])),
        },
        "fill_ratio_watertight_only": {
            "min": float(np.min(watertight_population["fill_ratio"])),
            "median": float(np.median(watertight_population["fill_ratio"])),
            "max": float(np.max(watertight_population["fill_ratio"])),
        },
        "toy_mug_fill_ratio": 0.68,
        "toy_plank_fill_ratio": 0.27,
        "ghost_fill_ratio": GHOST["fill_ratio"],
    }

    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
