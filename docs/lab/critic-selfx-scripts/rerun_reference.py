"""Re-run the SimReady reference set through the critic's new signals.

The brief for ``critic-selfx``: re-run the reference set and record which
verdicts change and why. This script measures each of the 38 reference
GLBs twice — once with the new signals off (the pre-Open3D measurement,
bit-for-bit) and once with them on (self-intersection under the cap,
ray-parity fallback where the signed volume is unreliable) — judges both
against the same request, and records every check that flipped.

The old verdict is reconstructed exactly, not approximated: turning the
signals off leaves a report whose volume check behaves identically to the
old code (``unchecked'' self-intersection does not change
``volume_reliable''), so dropping the one new check from the new judge's
output and recomputing the weighted mean is the old verdict to the digit.

It also copies out the 12 watertight-flip rows from the open3d-critic
sweep (rows where the critic's edge census says closed and Open3D's
watertight word says not), with each mesh's signed and ray-parity
volumes — the list the brief asks the doc to carry, unchanged code
behind it.

Run (Thor, CPU only, the worktree's venv):

    cd ~/lm-wt/critic-selfx
    .venv/bin/python docs/lab/critic-selfx-scripts/rerun_reference.py [--quick]

``--quick`` measures the first three meshes only (a smoke run, ~1 min).
The full run is a few minutes; the two meshes over the 200k cap are
skipped by the cap itself, which is the point of the cap. Results land
in ``results/rerun.json`` beside this script.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path

from core.genbatch.critic import judge
from core.genbatch.glb import read_glb
from core.genbatch.mesh import measure_mesh
from core.genbatch.models import CheckResult, PropRequest, PropVerdict

#: Where the reference GLBs live on the Thor (never in the repo).
GLB_DIR = Path.home() / "lm-wt/simready-survey/data/glb"

#: The sweep's committed per-mesh rows, for the watertight-flip list.
SWEEP_RESULTS = Path(__file__).parents[1] / "open3d-critic/results/results.json"

RESULTS = Path(__file__).parent / "results/rerun.json"

#: The request every mesh is judged against. The triangle budget is set
#: not to bind: the reference assets run to 1.33 M triangles, and the
#: budget verdict is the same before and after the change — it would only
#: add noise to the score columns.
REQUEST = PropRequest(id="reference", triangle_budget=10**9)


def box_state() -> dict:
    """The box's state, for the record beside every number."""
    load = os.getloadavg()
    with open("/proc/meminfo", encoding="ascii") as handle:
        mem = {
            line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in handle
            if ":" in line
        }
    return {
        "load_average": [round(x, 2) for x in load],
        "mem_available_gb": round(mem["MemAvailable"] / 2**30, 1),
    }


def _reweighted(checks: list[CheckResult]) -> tuple[float, bool, str]:
    """The weighted mean, the degraded flag and the reason of some checks."""
    weight = sum(check.weight for check in checks)
    score = (
        sum(check.weight * check.score for check in checks) / weight
        if weight
        else 0.0
    )
    failed = [check for check in checks if not check.passed]
    reason = (
        "; ".join(f"{check.name}: {check.detail}" for check in failed)
        if failed
        else "every check passed"
    )
    return score, any(check.score < 1.0 for check in checks), reason


def old_verdict(report, request: PropRequest) -> PropVerdict:
    """The verdict the critic gave before the self-intersection signal.

    The report is measured with the signals off, so its volume checks are
    the old code's behaviour already; all that is left is to take the one
    new check out of the judge's output and recompute the weighted mean.
    """
    verdict = judge(report, request)
    checks = [check for check in verdict.checks if check.name != "self_intersection"]
    score, degraded, reason = _reweighted(checks)
    return PropVerdict(score=score, checks=checks, reason=reason, degraded=degraded)


def one_mesh(path: Path) -> dict:
    mesh = read_glb(path).asset
    # The old measurement: the signals off, bit-for-bit what the critic
    # measured before critic-selfx.
    before = measure_mesh(mesh, selfx=False, parity_fallback=False)
    # The new measurement: self-intersection under the cap, the ray-parity
    # fallback where the signed volume is unreliable.
    after = measure_mesh(mesh)

    old = old_verdict(before, REQUEST)
    new = judge(after, REQUEST)

    old_passed = {check.name: check.passed for check in old.checks}
    new_passed = {check.name: check.passed for check in new.checks}
    flips = sorted(
        name
        for name in set(old_passed) | set(new_passed)
        if old_passed.get(name) != new_passed.get(name)
    )
    return {
        "name": path.stem,
        "triangles": after.triangles,
        "watertight": after.watertight,  # unchanged by design; recorded anyway
        "self_intersection": {
            "state": after.self_intersection,
            "pairs": after.self_intersection_pairs,
            "reason": after.self_intersection_reason,
        },
        "signed_volume": after.volume,
        "volume_reliable": after.volume_reliable,
        "parity_volume": after.parity_volume,
        "old_score": round(old.score, 6),
        "new_score": round(new.score, 6),
        "score_delta": round(new.score - old.score, 6),
        "flipped_checks": flips,
        "old_failed": sorted(n for n, ok in old_passed.items() if not ok),
        "new_failed": sorted(n for n, ok in new_passed.items() if not ok),
    }


def watertight_flip_rows() -> list[dict]:
    """The 12 rows a watertight-flag swap would flip, from the sweep."""
    document = json.loads(SWEEP_RESULTS.read_text(encoding="utf-8"))
    rows = []
    for mesh in document["meshes"]:
        ours = mesh["topology"]["ours"]["watertight"]
        theirs = mesh["topology"]["o3d"]["watertight"]
        if ours and not theirs:
            rows.append(
                {
                    "name": mesh["name"],
                    "triangles": mesh["triangles"],
                    "signed_volume": mesh["volume"]["ours_signed"],
                    "parity_volume": mesh["occupancy"]["o3d_raycast_interior"],
                    "self_intersecting": mesh["self_intersection"]["o3d"],
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="first three meshes only")
    args = parser.parse_args()

    paths = sorted(GLB_DIR.glob("*.glb"))
    if args.quick:
        paths = paths[:3]
    if not paths:
        raise SystemExit(f"no reference GLBs under {GLB_DIR}")

    started = time.perf_counter()
    rows = []
    for index, path in enumerate(paths, start=1):
        row = one_mesh(path)
        rows.append(row)
        print(
            f"[{index:>2}/{len(paths)}] {row['name']:<44} "
            f"selfx={row['self_intersection']['state']:<17} "
            f"delta={row['score_delta']:+.3f} flips={','.join(row['flipped_checks']) or '-'}",
            flush=True,
        )

    flipped = [row for row in rows if row["flipped_checks"]]
    document = {
        "meta": {
            "started": box_state(),
            "ended": box_state(),
            "seconds": round(time.perf_counter() - started, 1),
            "peak_rss_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
            ),
            "meshes": len(rows),
            "python": os.sys.version.split()[0],
            "request": REQUEST.model_dump(),
            "verdicts_changed": len(flipped),
        },
        "rows": rows,
        "watertight_flip_rows": watertight_flip_rows(),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")

    states: dict[str, int] = {}
    for row in rows:
        state = row["self_intersection"]["state"]
        states[state] = states.get(state, 0) + 1
    print(
        f"\n{len(rows)} meshes in {document['meta']['seconds']} s, "
        f"peak RSS {document['meta']['peak_rss_mb']} MB; "
        f"self-intersection states {states}; "
        f"{len(flipped)} verdicts changed -> {RESULTS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
