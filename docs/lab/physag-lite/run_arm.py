#!/usr/bin/env python3
"""Run one arm of the experiment and write the numbers.

The arm is a set of props and a place their meshes live. For each prop the
runner:

1. reads the plan (a recorded cloud plan, from ``--specs``);
2. splits the mesh into the plan's parts, geometrically;
3. decomposes each part into convex pieces and writes an MJCF;
4. checks the action in MuJoCo — completion against a relative band,
   stability against penetration, explosion and the rest baseline;
5. repairs once, if the planner recorded a revision and the check failed;
6. writes the delivery record: what was measured, what was estimated, what
   it cost.

The summary at the end is the thing the brief asks for: the completion rate
over the props that count, the stability pass rate, the repairs used, and
the wall time and GPU seconds per prop.

Usage::

    python docs/lab/physag-lite/run_arm.py --arm trellis \\
        --meshes artifacts/physag-lite/meshes \\
        --specs docs/lab/physag-lite/specs \\
        --out artifacts/physag-lite/run-trellis

    python docs/lab/physag-lite/run_arm.py --arm cad \\
        --meshes artifacts/physag-lite/cad-mesh \\
        --specs docs/lab/physag-lite/cad-specs \\
        --out artifacts/physag-lite/run-cad
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.physag.pipeline import delivery_for, run_prop  # noqa: E402
from core.physag.planner import FixturePlanner  # noqa: E402
from core.physag.spec import load_spec  # noqa: E402


def _gpu_seconds(log_path: Path, start: float, end: float) -> dict[str, float]:
    """The GPU-busy seconds over a window, from the sampled utilisation log.

    The wall clock alone would charge the GPU for the time it spent waiting
    for the CPU — the mesh tail of a TRELLIS run is CPU-bound. The
    utilisation is sampled once a second; the busy seconds are the
    integral of the sampled utilisation over the window.
    """
    if not log_path.exists():
        return {"gpu_busy_s": 0.0, "gpu_util_mean_pct": 0.0, "gpu_samples": 0}
    samples: list[float] = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            samples.append(float(line.strip()))
        except ValueError:
            continue
    if not samples:
        return {"gpu_busy_s": 0.0, "gpu_util_mean_pct": 0.0, "gpu_samples": 0}
    busy = sum(samples) / 100.0
    return {
        "gpu_busy_s": round(busy, 1),
        "gpu_util_mean_pct": round(sum(samples) / len(samples), 1),
        "gpu_samples": len(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, help="the arm's name, as it appears in the record")
    parser.add_argument("--meshes", required=True, type=Path, help="where the meshes are")
    parser.add_argument("--specs", required=True, type=Path, help="where the plans are")
    parser.add_argument("--out", required=True, type=Path, help="where to write the records")
    parser.add_argument("--props", default="", help="a space-separated list; default: every spec")
    parser.add_argument("--gpu-log", type=Path, default=None, help="the sampled GPU utilisation")
    parser.add_argument("--no-repair", action="store_true", help="do not repair")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    planner = FixturePlanner(args.specs)

    if args.props:
        props = args.props.split()
    else:
        props = sorted(p.stem for p in args.specs.glob("*.json") if not p.stem.endswith(".repair"))

    records = []
    for prop in props:
        spec_path = args.specs / f"{prop}.json"
        mesh_path = args.meshes / f"{prop}.glb"
        if not spec_path.exists():
            print(f"!! {prop}: no plan at {spec_path}", file=sys.stderr)
            continue
        if not mesh_path.exists():
            print(f"!! {prop}: no mesh at {mesh_path}", file=sys.stderr)
            continue

        spec = load_spec(spec_path)
        prop_dir = args.out / prop
        prop_dir.mkdir(parents=True, exist_ok=True)

        wall_start = time.perf_counter()
        print(f"== {prop} ({args.arm})")
        try:
            run = run_prop(
                spec,
                mesh_path,
                out_dir=prop_dir,
                planner=planner,
                allow_repair=not args.no_repair,
            )
        except Exception as exc:  # a prop that will not build is a result too
            print(f"!! {prop}: {type(exc).__name__}: {exc}", file=sys.stderr)
            (prop_dir / "error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
            records.append(
                {
                    "prop": prop,
                    "arm": args.arm,
                    "interaction_status": "not_run",
                    "physics_status": "invalid",
                    "counted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "notes": ["the prop did not build"],
                }
            )
            continue
        wall = time.perf_counter() - wall_start

        delivery = delivery_for(run, arm=args.arm)
        gpu = _gpu_seconds(
            args.gpu_log,
            0.0,
            0.0,
        ) if args.gpu_log else {"gpu_busy_s": 0.0, "gpu_util_mean_pct": 0.0, "gpu_samples": 0}
        delivery.timings["wall_s"] = round(wall, 3)
        delivery.timings.update(gpu)
        delivery.save(prop_dir / "delivery.json")

        result = run.result
        print(
            f"   interaction={delivery.interaction_status} "
            f"physics={delivery.physics_status} "
            f"completed={result.completion.completed if result else None} "
            f"repair={run.repair.get('used') if run.repair else False} "
            f"wall={wall:.1f}s"
        )
        if result is not None and result.stability.reasons:
            for reason in result.stability.reasons:
                print(f"      ! {reason}")
        if run.notes:
            for note in run.notes:
                print(f"      - {note}")

        records.append(delivery.to_dict())

    counted = [r for r in records if r.get("counted")]
    completed = [r for r in counted if r.get("interaction_status") == "completed"]
    stable = [r for r in counted if r.get("physics_status") == "stable"]
    valid = [r for r in counted if r.get("physics_status") in ("stable", "unstable")]
    repaired = [r for r in records if (r.get("repair") or {}).get("used")]

    summary = {
        "arm": args.arm,
        "props": len(records),
        "counted": len(counted),
        "completed": len(completed),
        "completion_rate": round(len(completed) / len(counted), 4) if counted else None,
        "stable": len(stable),
        "stable_of_counted": round(len(stable) / len(counted), 4) if counted else None,
        "physics_valid_of_counted": round(len(valid) / len(counted), 4) if counted else None,
        "repairs_used": len(repaired),
        "repaired_props": [r["prop"] for r in repaired],
        "not_counted": [r["prop"] for r in records if not r.get("counted")],
        "statuses": {
            r["prop"]: {
                "interaction_status": r.get("interaction_status"),
                "physics_status": r.get("physics_status"),
                "counted": r.get("counted"),
            }
            for r in records
        },
        "wall_s_total": round(sum(r.get("timings", {}).get("wall_s", 0.0) for r in records), 2),
        "wall_s_per_prop": round(
            sum(r.get("timings", {}).get("wall_s", 0.0) for r in records) / len(records), 2
        )
        if records
        else None,
        "gpu_busy_s_total": round(
            sum(r.get("timings", {}).get("gpu_busy_s", 0.0) for r in records), 1
        ),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
