"""The confusion table: before and after.

**The finding.** The critic's ``fill_ratio`` divides a mesh's **signed
volume** by its bounding box. A real object is a shell, so the number it
reads is the volume of the material in the wall, not the space the object
takes up: a real mug reads 0.052 where the toy mug reads 0.68, and the
prior fitted on generated solids calls every real object a ghost.

**What this measures.** Two priors over the same 38 sampled real assets:

*before*
    the prior as it was: fitted on the toy approved set alone, the
    features measured on the shell's signed volume;
*after*
    the prior fitted on the **union** of the toy approved set and the
    real objects, the features measured on what the object **occupies**.

And for each: the ghost's score, how many real assets are called ghosts,
and the same numbers with each real asset held out of the fit — the
honest measure, because the prior's job is to judge objects it has never
seen.

Usage::

    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/refit_prior.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "genbatch"))

from core.genbatch.glb import read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.occupancy import DEFAULT_FILL_METHOD
from core.genbatch.plausibility import (
    FEATURE_NAMES,
    PropFeatures,
    ReferencePrior,
    features_from_report,
)
from core.genbatch.reference import (
    GHOST_THRESHOLD,
    REAL_KIND,
    simready_features,
    simready_reference,
    union_prior,
)

import test_plausibility as toy

DEFAULT_GLB_DIR = Path("/home/caseydigennaro/lm-wt/simready-survey/data/glb")

#: The ghost, as the test file writes it: a valid solid whose shape is the
#: wrong shape for anything.
GHOST = PropFeatures(
    log_volume=-2.5,
    sphericity=30.0,
    elongation=12.0,
    fill_ratio=0.02,
    offcentre=0.4,
    defect_rate=0.0,
)


def box_state() -> dict:
    """The box's state, beside the numbers."""
    memory = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    memory[key] = int(rest.split()[0]) * 1024
    except OSError:
        pass
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = []
    return {
        "machine": "NVIDIA Jetson AGX Thor, aarch64, 14 Neoverse cores",
        "kernel": platform.release(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "load_average": load,
        "mem_total_gb": round(memory.get("MemTotal", 0) / 1024**3, 1),
        "mem_available_gb": round(memory.get("MemAvailable", 0) / 1024**3, 1),
    }


def measured(glb_dir: Path, method: str, resolution: int) -> list[PropFeatures]:
    """The real assets' features, measured from the GLBs."""
    out = []
    for path in sorted(glb_dir.glob("*.glb")):
        mesh = read_glb(path).asset
        report = measure_mesh(mesh, fill_method=method, fill_resolution=resolution)
        out.append(features_from_report(report))
    return out


def confusion(
    prior: ReferencePrior, real: list[PropFeatures], names: list[str]
) -> dict:
    """What the prior calls a ghost."""
    scores = [prior.score(features).score for features in real]
    flagged = [name for name, score in zip(names, scores) if score < GHOST_THRESHOLD]
    ghost = prior.score(GHOST)
    return {
        "ghost_score": float(ghost.score),
        "ghost_flagged": bool(ghost.score < GHOST_THRESHOLD),
        "ghost_distance": float(ghost.distance),
        "real_flagged": len(flagged),
        "real_total": len(real),
        "real_rate": len(flagged) / len(real),
        "real_median_score": float(np.median(scores)),
        "real_flagged_names": flagged,
        "real_scores": [round(score, 4) for score in scores],
    }


def leave_one_out(
    approved: list[PropFeatures],
    labels: list[str],
    real: list[PropFeatures],
) -> dict:
    """Each real asset held out of the fit and scored against the rest.

    The in-sample number is a rank among the group's own members, so it
    cannot be read as a false-positive rate. This is the honest one: the
    prior fitted without the asset, judging it.
    """
    flagged = []
    scores = []
    for index in range(len(real)):
        without = list(approved) + [
            features for other, features in enumerate(real) if other != index
        ]
        kinds = list(labels) + [REAL_KIND] * (len(real) - 1)
        prior = ReferencePrior(without, clusters=2, seed=toy.SEED, labels=kinds)
        score = prior.score(real[index]).score
        scores.append(score)
        if score < GHOST_THRESHOLD:
            flagged.append(index)
    return {
        "real_flagged": len(flagged),
        "real_total": len(real),
        "real_rate": len(flagged) / len(real),
        "real_median_score": float(np.median(scores)),
        "real_flagged_indices": flagged,
        "real_scores": [round(score, 4) for score in scores],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb-dir", type=Path, default=DEFAULT_GLB_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--method", default=DEFAULT_FILL_METHOD)
    parser.add_argument("--resolution", type=int, default=64)
    args = parser.parse_args()

    approved, labels = toy._reference_set()
    names = [asset.name for asset in simready_reference()]
    stored = simready_features()

    # -- the fit the critic would use: the stored reference set -----------
    after = confusion(union_prior(approved, labels), stored, names)
    after["leave_one_out"] = leave_one_out(approved, labels, stored)

    # -- the state before: the toy prior, and the shell's signed volume ----
    signed = measured(args.glb_dir, "signed", args.resolution)
    before = confusion(ReferencePrior(approved, clusters=2, seed=toy.SEED), signed, names)
    before["note"] = (
        "the prior as it was: fitted on the toy approved set alone, the "
        "features measured on the shell's signed volume"
    )

    # -- and the toy prior against the occupied features, for the record ---
    occupied = measured(args.glb_dir, args.method, args.resolution)
    toy_prior_occupied = confusion(
        ReferencePrior(approved, clusters=2, seed=toy.SEED), occupied, names
    )

    result = {
        "box": box_state(),
        "threshold": GHOST_THRESHOLD,
        "measure": args.method,
        "resolution": args.resolution,
        "toy_size": len(approved),
        "real_size": len(stored),
        "before": before,
        "toy_prior_on_occupied_features": toy_prior_occupied,
        "after": after,
    }

    print(f"box: {result['box']['machine']}, kernel {result['box']['kernel']}, "
          f"load {result['box']['load_average']}, "
          f"{result['box']['mem_available_gb']} GB available")
    print(f"threshold {GHOST_THRESHOLD}, measure {args.method}\n")
    for label, block in (("before", before), ("after", after)):
        print(f"{label:7s} ghost {block['ghost_score']:.4f} "
              f"({'FLAGGED' if block['ghost_flagged'] else 'passed '})  "
              f"real flagged {block['real_flagged']}/{block['real_total']} "
              f"({block['real_rate']:5.1%})  median {block['real_median_score']:.4f}")
        if "leave_one_out" in block:
            loo = block["leave_one_out"]
            print(f"        leave-one-out: {loo['real_flagged']}/{loo['real_total']} "
                  f"({loo['real_rate']:5.1%})  median {loo['real_median_score']:.4f}  "
                  f"{[names[i] for i in loo['real_flagged_indices']]}")
    print(f"\ntoy prior alone, occupied features: "
          f"{toy_prior_occupied['real_flagged']}/{toy_prior_occupied['real_total']} "
          f"({toy_prior_occupied['real_rate']:.1%}) flagged")

    out = args.out or Path(__file__).with_name("results") / "confusion.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
