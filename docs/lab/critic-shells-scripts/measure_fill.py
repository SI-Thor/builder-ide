"""Measure the fill of the SimReady sample under every candidate measure.

**What this measures.** The critic's ``fill_ratio`` divides a mesh's
*signed* volume by its bounding box. A real object is a shell, so the
number it reads is the volume of the material in the wall, not the space
the object takes up: a real mug reads 0.052 against a solid toy mug's
0.68, and the prior fitted on the toy set calls all 38 sampled real
assets ghosts.

This script measures the candidates on the same 38 meshes:

``signed``
    the measure the critic has — the shell's own signed volume;
``visual``
    the silhouette hull (:mod:`core.genbatch.occupancy`), numpy only;
``convex``
    the convex hull of the vertices (scipy).

It reports, per asset: the triangles, the box, the signed volume, each
candidate's occupied volume, the fill ratio each one gives, and the wall
clock each one cost. The box's state is in the results file beside them.

Usage::

    ~/lm-wt/mesh-repair/.venv/bin/python docs/lab/critic-shells-scripts/measure_fill.py

The GLBs are the survey's own conversions, verified against their USD
sources and read back with builder-ide's reader
(docs/research/simready.md §4.3). They live outside the repository — the
sample is 113.9 MiB — so the path is a parameter.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.genbatch.glb import read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.plausibility import features_from_report

DEFAULT_GLB_DIR = Path("/home/caseydigennaro/lm-wt/simready-survey/data/glb")


def box_state() -> dict:
    """The box's state, beside the numbers."""
    load = os_loadavg()
    memory = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    memory[key] = int(rest.split()[0]) * 1024
    except OSError:
        pass
    return {
        "machine": "NVIDIA Jetson AGX Thor, aarch64, 14 Neoverse cores",
        "kernel": platform.release(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "load_average": load,
        "mem_total_gb": round(memory.get("MemTotal", 0) / 1024**3, 1),
        "mem_available_gb": round(memory.get("MemAvailable", 0) / 1024**3, 1),
    }


def os_loadavg() -> list[float]:
    try:
        return [round(value, 2) for value in os.getloadavg()]
    except OSError:
        return []


def measure_asset(path: Path, resolutions: list[int]) -> dict:
    """Every candidate's fill for one asset."""
    glb = read_glb(path)
    # The whole object, not its first part: a forklift is 32 parts and its
    # first primitive is 0.2% of the geometry.
    mesh = glb.asset

    started = time.perf_counter()
    plain = measure_mesh(mesh)
    plain_seconds = time.perf_counter() - started

    extent = np.asarray(plain.extent, dtype=np.float64)
    box_volume = float(extent[0] * extent[1] * extent[2])

    row: dict = {
        "asset": path.stem,
        "triangles": plain.triangles,
        "triangles_first_primitive": int(glb.mesh.triangles),
        "primitives": len(glb.gltf.get("meshes") or []),
        "vertices": plain.vertices,
        "extent": [round(float(value), 6) for value in extent],
        "box_volume": box_volume,
        "watertight": plain.watertight,
        "consistent_winding": plain.consistent_winding,
        "boundary_edges": plain.boundary_edges,
        "signed_volume": plain.volume,
        "signed_fill": plain.volume / box_volume if box_volume else float("nan"),
        "signed_seconds": round(plain_seconds, 4),
        "defect_rate": (
            (plain.boundary_edges + plain.nonmanifold_edges + plain.degenerate_triangles)
            / max(plain.triangles, 1)
        ),
        "candidates": {},
    }

    for method, resolution in (
        [("visual", r) for r in resolutions]
        + [("convex", 64)]
    ):
        started = time.perf_counter()
        try:
            report = measure_mesh(mesh, fill_method=method, fill_resolution=resolution)
        except Exception as exc:  # noqa: BLE001
            row["candidates"][f"{method}_{resolution}"] = {"error": str(exc)}
            continue
        seconds = time.perf_counter() - started
        features = features_from_report(report)
        volume = float(report.occupied_volume or 0.0)
        row["candidates"][f"{method}_{resolution}"] = {
            "occupied_volume": volume,
            "fill": volume / box_volume if box_volume else float("nan"),
            "seconds": round(seconds, 4),
            "log_volume": features.log_volume,
            "sphericity": features.sphericity,
            "elongation": features.elongation,
            "fill_ratio": features.fill_ratio,
            "offcentre": features.offcentre,
            "defect_rate": features.defect_rate,
        }

    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb-dir", type=Path, default=DEFAULT_GLB_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--resolutions",
        type=int,
        nargs="+",
        default=[32, 64, 128],
        help="the occupancy grids to measure, in cells along the longest axis",
    )
    args = parser.parse_args()

    paths = sorted(args.glb_dir.glob("*.glb"))
    if not paths:
        print(f"no GLBs under {args.glb_dir}")
        return 1

    rows = []
    for path in paths:
        row = measure_asset(path, list(args.resolutions))
        rows.append(row)
        signed = row["signed_fill"]
        visual = row["candidates"].get("visual_64", {}).get("fill", float("nan"))
        print(
            f"{row['asset']:42s} tri {row['triangles']:>9,}  "
            f"signed {signed:>9.4f}  visual64 {visual:>8.4f}  "
            f"{row['candidates'].get('visual_64', {}).get('seconds', 0):>6.2f}s"
        )

    result = {
        "box": box_state(),
        "glb_dir": str(args.glb_dir),
        "resolutions": list(args.resolutions),
        "assets": rows,
    }
    out = args.out or Path(__file__).with_name("results") / "fill.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
