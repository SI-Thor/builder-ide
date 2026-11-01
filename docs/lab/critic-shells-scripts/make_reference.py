"""Measure the SimReady sample and write the reference set the prior uses.

**What this writes.** ``core/genbatch/simready-reference.json`` — the six
plausibility features of every sampled real asset, measured by the critic's
own pipeline (``read_glb`` → ``measure_mesh`` → ``features_from_report``)
with the **occupied** volume rather than the shell's signed volume, plus
the provenance a reader needs to trust the numbers: the dataset and its
licence, the fill measure and its parameters, the prior's cluster count and
seed, and the state of the box the measurement ran on.

The file is the *recipe*, not the meshes: 38 rows of six numbers each,
where the GLBs are 113.9 MiB. The critic's approved set and this sample
are the union the prior is fitted on, and the union has to be reproducible
without the dataset on the disk.

Usage::

    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/make_reference.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.glb import read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.occupancy import DEFAULT_FILL_METHOD, DEFAULT_RESOLUTION
from core.genbatch.plausibility import FEATURE_NAMES, features_from_report

DEFAULT_GLB_DIR = Path("/home/caseydigennaro/lm-wt/simready-survey/data/glb")
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "core" / "genbatch" / "simready-reference.json"

#: The prior's fit, as measured (docs/lab/exp-critic-shells.md).
REFERENCE_CLUSTERS = 22
REFERENCE_SEED = 20261031


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


def measure_asset(path: Path, method: str, resolution: int) -> dict:
    """One asset's features, and what the measurement saw."""
    mesh = read_glb(path).asset
    report = measure_mesh(mesh, fill_method=method, fill_resolution=resolution)
    features = features_from_report(report)
    extent = np.asarray(report.extent, dtype=np.float64)
    box_volume = float(extent[0] * extent[1] * extent[2])
    return {
        "name": path.stem,
        "triangles": int(report.triangles),
        "vertices": int(report.vertices),
        "watertight": bool(report.watertight),
        "defect_rate": float(features.defect_rate),
        "signed_volume": float(report.volume),
        "occupied_volume": float(report.occupied_volume or 0.0),
        "box_volume": box_volume,
        # Twelve decimals, not six: the prior's score is a *rank*, and the
        # ranks of the borderline assets move when the numbers are rounded
        # coarsely enough. A recipe has to reproduce.
        "features": {
            name: float(f"{float(value):.12g}")
            for name, value in zip(FEATURE_NAMES, features.as_vector())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb-dir", type=Path, default=DEFAULT_GLB_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--method", default=DEFAULT_FILL_METHOD)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RESOLUTION)
    args = parser.parse_args()

    paths = sorted(args.glb_dir.glob("*.glb"))
    if not paths:
        print(f"no GLBs under {args.glb_dir}")
        return 1

    assets = [measure_asset(path, args.method, args.resolution) for path in paths]

    document = {
        "version": 1,
        "source": {
            "dataset": "nvidia/simready-assets",
            "licence": "CC-BY-4.0",
            "credit": "NVIDIA SimReady Assets",
            "sample": f"{len(assets)} packages, 37 categories",
            "survey": "docs/research/simready.md",
            "read_back_with": "core.genbatch.glb.read_glb",
            "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "box": box_state(),
        },
        "measure": {
            "method": args.method,
            "resolution": args.resolution,
            "note": (
                "the volume the object occupies (its envelope), not the "
                "volume of the material in its wall"
            ),
        },
        "prior": {
            "clusters": REFERENCE_CLUSTERS,
            "seed": REFERENCE_SEED,
            "note": (
                "the prior is fitted on the union of the approved set and "
                "this sample; the cluster count and the seed are the ones "
                "the measurement chose (docs/lab/exp-critic-shells.md)"
            ),
        },
        "assets": assets,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"wrote {args.out} — {len(assets)} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
