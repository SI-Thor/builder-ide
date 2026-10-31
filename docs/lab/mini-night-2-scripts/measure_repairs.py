"""Measure the repair on every prop the night made, after the fact.

The night's own report carries the repair for the three winners; this walks
the night's *whole* slate — nine props — and measures each one the same way
the pipeline measured it: read the GLB, measure the mesh as the generator
left it, run the repair, and measure the mesh again.

That gives the before/after the night needs to answer: how many props were
watertight before the repair, how many after, and what the repair did to
each one's outline (the silhouette IoU).

    python measure_repairs.py --requests examples/mini_night_requests.json \\
        --out artifacts/mini-night-2/repairs.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.genbatch.glb import GlbError, read_glb  # noqa: E402
from core.genbatch.mesh import measure_mesh  # noqa: E402
from core.genbatch.models import PropRequest  # noqa: E402
from core.genbatch.repair import repair_mesh  # noqa: E402
from core.genbatch.schedule import NightPlan  # noqa: E402

DEFAULT_TRELLIS = Path.home() / "lm-wt" / "trellis"


def _newest_glb(out_dir: Path, request_id: str, seed: int) -> Path | None:
    """The most recent GLB the night wrote for one (request, seed)."""
    pattern = f"{request_id}_s{seed}_*.glb"
    found = sorted(out_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _measure(path: Path, request: PropRequest) -> dict:
    """One prop: as the generator left it, and as the repair left it."""
    mesh = read_glb(path).mesh
    before = measure_mesh(mesh)
    result = repair_mesh(mesh, request.repair)
    after = result.report.after or measure_mesh(result.mesh)
    report = result.report
    return {
        "glb": str(path),
        "bytes": path.stat().st_size,
        "before": {
            "watertight": before.watertight,
            "consistent_winding": before.consistent_winding,
            "boundary_edges": before.boundary_edges,
            "nonmanifold_edges": before.nonmanifold_edges,
            "triangles": before.triangles,
            "vertices": before.vertices,
            "volume": before.volume,
            "area": before.area,
            "extent": list(before.extent),
        },
        "after": {
            "watertight": after.watertight,
            "consistent_winding": after.consistent_winding,
            "boundary_edges": after.boundary_edges,
            "nonmanifold_edges": after.nonmanifold_edges,
            "triangles": after.triangles,
            "vertices": after.vertices,
            "volume": after.volume,
            "area": after.area,
            "extent": list(after.extent),
        },
        "repair": {
            "ok": report.ok,
            "reason": report.reason,
            "seconds": report.seconds,
            "method": report.method,
            "welded_vertices": report.welded_vertices,
            "boundary_edges_closed": report.boundary_edges_closed,
            "nonmanifold_edges_split": report.nonmanifold_edges_split,
            "pinched_vertices_split": report.pinched_vertices_split,
            "degenerate_faces_collapsed": report.degenerate_faces_collapsed,
            "fidelity": report.fidelity,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure_repairs.py")
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_TRELLIS / "out" / "genbatch",
        help="where the night's GLBs are",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    body = json.loads(args.requests.read_text())
    requests = [PropRequest.model_validate(row) for row in body]
    plan = NightPlan(requests)

    rows: list[dict] = []
    for request in requests:
        for index, seed in enumerate(plan.seeds(request.id), start=1):
            path = _newest_glb(args.out_dir, request.id, seed)
            if path is None:
                rows.append(
                    {
                        "request": request.id,
                        "seed": seed,
                        "variant": f"{request.id}_r1_v{index}",
                        "glb": None,
                        "error": "no GLB for this seed",
                    }
                )
                continue
            try:
                row = _measure(path, request)
            except GlbError as exc:
                row = {"glb": str(path), "error": str(exc)}
            row["request"] = request.id
            row["seed"] = seed
            row["variant"] = f"{request.id}_r1_v{index}"
            rows.append(row)
            print(
                f"{row['variant']:>22}  "
                f"before watertight={row['before']['watertight']} "
                f"({row['before']['boundary_edges']:,} boundary)  "
                f"after watertight={row['after']['watertight']} "
                f"({row['after']['boundary_edges']:,} boundary)  "
                f"fidelity={row['repair']['fidelity']:.6f}  "
                f"{row['repair']['seconds']:.1f}s"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
