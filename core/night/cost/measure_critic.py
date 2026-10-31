"""Measure the critic's verdict: what one judgement costs on the CPU lane.

The cost model needs a *measured* number for the critic's verdict — the last
step of every prop's path, and the step that decides which variant wins. This
script measures it on the assets the mini-night actually produced
(``artifacts/mini-night/report.json`` names the winners), on the Thor.

**What it measures**, per asset, with the wall clock:

1. ``read_glb`` — the GLB parse (the bytes off the disk).
2. ``measure_mesh`` — the topology and solid measurements (the heavy part:
   edges, winding, volume, area, centre of mass over ~700k triangles).
3. ``judge`` — the verdict itself: the seven analytic checks, the weighted
   score and the reason.

Steps 1 and 2 are the *mesh layer*; step 3 is the **critic verdict**. The
model charges the mesh layer to the CPU lane of the prop's own job and the
verdict to the verdict's own job, so the verdict's number here is step 3
alone.

**How to reproduce it** (from the repo root, with the repo's venv):

    ~/lm-wt/integrate-core/.venv/bin/python -m core.night.cost.measure_critic \\
        --assets ~/lm-wt/trellis/out/genbatch \\
        --requests examples/mini_night_requests.json \\
        --repeats 5

It prints a JSON document — the shape ``core/night/cost/data/recorded.json``
carries for the ``critic.verdict`` job kind.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.genbatch.critic import judge
from core.genbatch.glb import read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.models import PropRequest


def _load_requests(path: Path) -> dict[str, PropRequest]:
    payloads: list[dict[str, Any]] = json.loads(path.read_text())
    return {str(payload["id"]): PropRequest(**payload) for payload in payloads}


def _winners(report_path: Path) -> list[tuple[str, str]]:
    """The (request id, glb path) pairs the mini-night kept."""
    payload = json.loads(report_path.read_text())
    winners = payload.get("winners") or []
    return [(str(w["request_id"]), str(w["glb_path"])) for w in winners]


def _bench(fn, repeats: int) -> list[float]:
    """The wall seconds of ``fn()``, ``repeats`` times."""
    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        timings.append(time.perf_counter() - started)
    return timings


def _measure(request: PropRequest, glb_path: Path, repeats: int) -> dict[str, Any]:
    mesh = read_glb(glb_path).mesh
    report = measure_mesh(mesh)
    verdict = judge(report, request)
    parse = _bench(lambda: read_glb(glb_path), repeats)
    measure = _bench(lambda: measure_mesh(mesh), repeats)
    judge_times = _bench(lambda: judge(report, request), repeats)
    return {
        "request_id": request.id,
        "asset": glb_path.name,
        "triangles": report.triangles,
        "vertices": report.vertices,
        "watertight": report.watertight,
        "score": verdict.score,
        "parse_seconds": parse,
        "measure_seconds": measure,
        "judge_seconds": judge_times,
    }


def _box_state() -> dict[str, Any]:
    """The box's state beside the number: load, cores and free memory.

    A number without the box's state beside it is a number nobody can read
    later (``docs/lab/README.md``'s rule).
    """
    state: dict[str, Any] = {"loadavg_1_5_15": os.getloadavg()}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(("MemTotal:", "MemAvailable:")):
                key, value = line.split(":", 1)
                state[key] = value.strip()
    except OSError:  # pragma: no cover - not Linux
        pass
    try:
        state["cpu_count"] = len(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - not Linux
        state["cpu_count"] = os.cpu_count()
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path("/home/caseydigennaro/lm-wt/trellis/out/genbatch"),
        help="the directory the mini-night wrote its GLBs to",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "/home/caseydigennaro/lm-wt/propmaker-batch/artifacts/mini-night/report.json"
        ),
        help="the mini-night's report.json (it names the winners)",
    )
    parser.add_argument(
        "--requests",
        type=Path,
        default=Path("examples/mini_night_requests.json"),
        help="the requests the mini-night ran",
    )
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    requests = _load_requests(args.requests)
    state = _box_state()
    rows: list[dict[str, Any]] = []
    for request_id, glb_path in _winners(args.report):
        path = Path(glb_path)
        if not path.exists():
            # The report names an absolute path from the run; fall back to the
            # assets directory when the file has moved.
            matches = sorted(args.assets.glob(f"{request_id}_*.glb"))
            if not matches:
                print(f"skipping {request_id}: no asset at {path}")
                continue
            path = matches[0]
        rows.append(_measure(requests[request_id], path, args.repeats))

    judge_times = [value for row in rows for value in row["judge_seconds"]]
    document = {
        "box": {
            "host": platform.node(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            **state,
        },
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "assets": rows,
        "judge_seconds_p50": statistics.median(judge_times) if judge_times else None,
        "judge_seconds_max": max(judge_times) if judge_times else None,
    }
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - a measurement script
    raise SystemExit(main())
