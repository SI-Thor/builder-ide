"""Build ``simready_priors.json`` and measure the critic against it.

**What this does, in two parts.**

*Part one — the priors.* For every category in the sample, the measured
mass, size, material and shape features of the assets in it. The shape
features are **the critic's own six features**, computed by running the
critic's pipeline (read the GLB, measure the mesh, take the features) over
the SimReady assets. So the priors are not a description of SimReady assets
in SimReady's terms: they are the same numbers the critic already computes,
measured on real objects instead of generated ones.

*Part two — the measurement.* The critic's test set has known ground truth:
a toy with two kinds of real object (a **mug**, abundant, and a **plank**,
rare), and a **ghost** — a valid solid whose shape is the wrong shape for
anything, which the test file calls out as the control a consistency-only
critic cannot pass. The question the brief asks is whether the SimReady
priors flag the known-bad props. This fits the critic's ``ReferencePrior``
on the SimReady features and scores the test set's props with it.

The reference set is small and the critic's score is a rank within a small
group, so the scores are coarse. That is stated in the output rather than
smoothed over.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BUILDER_IDE = Path("/home/caseydigennaro/src/builder-ide")


def _features_for_assets(report_rows, glb_dir: Path) -> dict[str, dict]:
    """The critic's six features for every asset, through the critic's own code."""
    sys.path.insert(0, str(BUILDER_IDE))
    from core.genbatch.glb import read_glb
    from core.genbatch.mesh import measure_mesh
    from core.genbatch.plausibility import features_from_report

    out: dict[str, dict] = {}
    for row in report_rows:
        asset = row["asset"]
        schema = row.get("schema")
        if not schema:
            continue
        path = glb_dir / f"{asset}.glb"
        if not path.exists():
            continue
        glb = read_glb(path)
        mesh_report = measure_mesh(glb.mesh)
        features = features_from_report(mesh_report)
        out[asset] = {
            "features": features.as_vector().tolist(),
            "log_volume": features.log_volume,
            "sphericity": features.sphericity,
            "elongation": features.elongation,
            "fill_ratio": features.fill_ratio,
            "offcentre": features.offcentre,
            "defect_rate": features.defect_rate,
            "watertight": bool(mesh_report.watertight),
            "measured_volume_m3": float(mesh_report.volume),
            "measured_area_m2": float(mesh_report.area),
            "measured_extent_m": [float(v) for v in mesh_report.extent],
        }
    return out


def _category_of(asset: str) -> str:
    return asset.split("_")[0]


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": int(array.size),
        "min": float(array.min()),
        "max": float(array.max()),
        "median": float(np.median(array)),
        "p10": float(np.percentile(array, 10)),
        "p90": float(np.percentile(array, 90)),
    }


def build_priors(report_rows, features_by_asset: dict[str, dict]) -> dict:
    """Category -> measured ranges."""
    by_category: dict[str, list[str]] = {}
    for row in report_rows:
        asset = row["asset"]
        if asset in features_by_asset:
            by_category.setdefault(_category_of(asset), []).append(asset)

    categories: dict[str, dict] = {}
    for category, assets in sorted(by_category.items()):
        masses, sizes, densities, extents = [], [], [], []
        materials, features, feature_vectors = [], [], []
        for asset in assets:
            schema = next(r["schema"] for r in report_rows if r["asset"] == asset)
            if schema.get("mass_kg_total"):
                masses.append(float(schema["mass_kg_total"]))
            if schema.get("size_m"):
                sizes.append([float(v) for v in schema["size_m"]])
            for value in schema.get("density_kg_m3") or []:
                if value:
                    densities.append(float(value))
            for label in schema.get("semantic_labels") or []:
                cleaned = str(label).strip("[]")
                if cleaned and cleaned not in materials and not cleaned.startswith("Q"):
                    materials.append(cleaned)
            measured = features_by_asset[asset]
            features.append(measured)
            feature_vectors.append(measured["features"])

        # The size band: the largest dimension of each asset, which is the
        # "how big is this thing" number a prior wants.
        largest = [max(size) for size in sizes] if sizes else []
        categories[category] = {
            "assets": sorted(assets),
            "n_sample": len(assets),
            "mass_kg": _quantiles(masses),
            "size_m": {
                "largest_axis": _quantiles(largest),
                "x": _quantiles([s[0] for s in sizes]) if sizes else {"n": 0},
                "y": _quantiles([s[1] for s in sizes]) if sizes else {"n": 0},
                "z": _quantiles([s[2] for s in sizes]) if sizes else {"n": 0},
            },
            "density_kg_m3": _quantiles(densities),
            "materials": sorted(materials),
            "critic_features": {
                "log_volume": _quantiles([f["log_volume"] for f in features]),
                "sphericity": _quantiles([f["sphericity"] for f in features]),
                "elongation": _quantiles([f["elongation"] for f in features]),
                "fill_ratio": _quantiles([f["fill_ratio"] for f in features]),
                "offcentre": _quantiles([f["offcentre"] for f in features]),
                "defect_rate": _quantiles([f["defect_rate"] for f in features]),
            },
            "measured_features": features,
            "feature_vector_mean": [
                float(v) for v in np.mean(np.asarray(feature_vectors), axis=0)
            ],
            "confidence": "one asset per category" if len(assets) == 1 else "small sample",
        }
    return categories


def score_against_critic(features_by_asset: dict[str, dict]) -> dict:
    """Fit the critic's prior on the SimReady features and score its test set."""
    sys.path.insert(0, str(BUILDER_IDE))
    from core.genbatch.plausibility import PropFeatures, ReferencePrior
    from tests.genbatch import test_plausibility as critic_test

    reference = [
        PropFeatures.from_vector(row["features"]) for row in features_by_asset.values()
    ]
    out: dict = {
        "reference_assets": len(reference),
        "reference_source": "SimReady sample, measured by the critic's own pipeline",
        "clusters": {},
    }

    for clusters in (2, 3, 4):
        prior = ReferencePrior(reference, clusters=clusters, seed=0)
        rng = np.random.default_rng(critic_test.SEED)
        mug = [
            critic_test._features(rng, "mug") for _ in range(40)
        ]
        plank = [
            critic_test._features(rng, "plank") for _ in range(40)
        ]
        ghost = PropFeatures(
            log_volume=-2.5,
            sphericity=30.0,
            elongation=12.0,
            fill_ratio=0.02,
            offcentre=0.4,
            defect_rate=0.0,
        )
        ghost_score = prior.score(ghost)
        mug_scores = [prior.score(f).score for f in mug]
        plank_scores = [prior.score(f).score for f in plank]
        simready_scores = [prior.score(PropFeatures.from_vector(row["features"])).score for row in features_by_asset.values()]
        out["clusters"][str(clusters)] = {
            "group_sizes": list(prior.group_sizes),
            "ghost": {
                "score": ghost_score.score,
                "cluster": ghost_score.cluster,
                "distance": ghost_score.distance,
                "percentiles": list(ghost_score.percentiles),
                "flagged_as_implausible": bool(ghost_score.score < 0.05),
                "distance_beyond_three_sigma": bool(ghost_score.distance > 3.0),
            },
            "mug_median_score": float(np.median(mug_scores)),
            "plank_median_score": float(np.median(plank_scores)),
            "simready_median_score": float(np.median(simready_scores)),
            "simready_min_score": float(np.min(simready_scores)),
            "consistency_gap": prior.consistency_gap([0.98 + 0.0004 * i for i in range(50)]),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="the sample report JSON")
    parser.add_argument("--glb-dir", required=True, help="where the GLBs are")
    parser.add_argument("--out", required=True, help="where to write the priors")
    parser.add_argument("--experiment-out", help="where to write the critic measurement")
    parser.add_argument(
        "--dataset",
        help="the dataset-wide physics summary (data/dataset_physics.json)",
    )
    args = parser.parse_args()

    report_rows = json.loads(Path(args.report).read_text())
    features_by_asset = _features_for_assets(report_rows, Path(args.glb_dir))
    categories = build_priors(report_rows, features_by_asset)

    dataset = None
    if args.dataset and Path(args.dataset).exists():
        dataset = json.loads(Path(args.dataset).read_text())
        # The dataset-wide mass distribution for each category: the same
        # category, measured over every asset in it, rather than over the
        # one the sample drew.
        for category, entry in categories.items():
            measured = (dataset.get("categories") or {}).get(category)
            if measured:
                entry["dataset_mass_kg"] = measured["mass_kg"]
                entry["dataset_assets"] = measured["assets"]
                entry["dataset_assets_with_mass"] = measured["assets_with_mass"]
                entry["confidence"] = (
                    "dataset-wide mass over %d assets; size and shape from one "
                    "sampled asset" % measured["assets_with_mass"]
                )

    priors = {
        "version": "1.0",
        "source": {
            "dataset": "nvidia/simready-assets",
            "licence": "CC-BY-4.0",
            "credit": "NVIDIA SimReady Assets (nvidia/simready-assets), CC-BY-4.0",
            "sample": "38 assets across 37 categories",
            "measured_by": "core.genbatch.glb.read_glb -> measure_mesh -> features_from_report",
        },
        "how_to_read": {
            "mass_kg": "the total rigid-body mass of the asset, from the USD physics payload",
            "size_m": "the world-space extent of the asset's geometry, in metres (metersPerUnit is 1, up axis Z)",
            "density_kg_m3": "the authored material density where the asset carries one",
            "materials": "the semantic material labels the asset declares",
            "critic_features": (
                "the critic's own six features, measured on the asset's mesh: "
                "log_volume, sphericity, elongation, fill_ratio, offcentre, defect_rate"
            ),
        },
        "caveats": [
            "One asset per category for most categories: the size and shape "
            "ranges are the measured spread of a single observation, not a "
            "distribution. The mass range per category is measured over every "
            "asset in that category in the dataset, under dataset_mass_kg.",
            "category is the first underscore-delimited token of the asset's "
            "folder name, which is NVIDIA's own grouping.",
            "mass is the sum over the asset's rigid bodies, so a multi-part "
            "asset (a forklift) carries the mass of the whole thing.",
            "the critic's six features are computed from the signed volume of "
            "the asset's mesh, and these meshes are shells: 21 of the 38 "
            "sampled packages are not watertight, and a hollow object "
            "encloses only its wall material. The fill_ratio feature is "
            "therefore small for real objects (a mug measures 0.052 against "
            "the critic's toy mug's 0.68) and the volume-based features "
            "are not comparable with a solid-prop reference set. See "
            "docs/research/simready.md section 2.",
        ],
        "categories": categories,
    }
    if dataset:
        priors["materials"] = {
            "note": (
                "the physics layer's PhysicsMaterialAPI: one block per material "
                "the asset uses, with its density and its friction. Measured over "
                "every package in the dataset."
            ),
            "table": dataset["materials"],
        }
        priors["dataset"] = {
            "packages": dataset["physics_layers_parsed"],
            "materials": dataset["material_count"],
            "asset_types": dataset["asset_types"],
            "profiles": dataset["profiles"],
        }
    Path(args.out).write_text(json.dumps(priors, indent=2) + "\n")
    print(f"wrote {args.out}: {len(categories)} categories")

    experiment = score_against_critic(features_by_asset)
    if args.experiment_out:
        Path(args.experiment_out).write_text(json.dumps(experiment, indent=2) + "\n")
    print(json.dumps(experiment, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
