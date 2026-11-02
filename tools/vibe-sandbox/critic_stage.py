"""The critic stage: the repo's own mesh critic, plus Open3D self-intersection.

Three sources, one report:

* ``core.critic.mesh.probe_scene`` measures the saved .blend with the
  engine's own bpy interpreter (per-object world bboxes, watertightness,
  inward fraction) — nothing is re-implemented here;
* ``core.critic.checks.run_mesh_checks`` runs the scripted mesh checks
  (scale_bounds within a family, the hollow-shell watertight rule, edge cut)
  on those numbers — the same checks the reference set is scored with;
* Open3D 0.20's ``is_self_intersecting`` on every object of the shipped GLB
  — the check the open3d-critic lane adopted (34 of 38 reference meshes
  self-intersect; invisible to the checks above).

Findings carry the object name so the generator's repair path can use them.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from pathlib import Path

LANE = Path(__file__).resolve().parent
REPO = LANE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(LANE))

from core.critic.checks import run_mesh_checks  # noqa: E402
from core.critic.mesh import probe_scene  # noqa: E402


def _self_intersecting(glb: Path) -> tuple[list[dict], float]:
    import open3d as o3d
    import trimesh

    t0 = time.perf_counter()
    rows = []
    scene = trimesh.load(str(glb), process=False, force="scene")
    for name, geom in scene.geometry.items():
        if geom.faces is None or len(geom.faces) == 0:
            continue
        mesh = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(geom.vertices),
            o3d.utility.Vector3iVector(geom.faces),
        )
        rows.append(
            {
                "name": name,
                "faces": int(len(geom.faces)),
                "self_intersecting": bool(mesh.is_self_intersecting()),
            }
        )
    return rows, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blend", required=True)
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    t0 = time.perf_counter()
    from common import BPY_PYTHON  # noqa: E402

    stats = probe_scene(args.blend, python=str(BPY_PYTHON))
    t_probe = time.perf_counter() - t0

    t1 = time.perf_counter()
    outcomes = [dataclasses.asdict(o) for o in run_mesh_checks(stats)]
    t_checks = time.perf_counter() - t1

    selfx_rows, t_selfx = _self_intersecting(Path(args.glb))

    findings = []
    for o in outcomes:
        if not o.get("fired"):
            continue
        finding = {"kind": o["check"], "source": "critic", "detail": o["detail"]}
        if o["check"] == "scale_bounds":
            # the detail line carries "name@ratio" pairs; lift the first name
            # so the repair path can use it
            m = re.search(r"([A-Za-z_.0-9]+)@", o["detail"])
            if m:
                finding["name"] = m.group(1)
        findings.append(finding)
    for row in selfx_rows:
        if row["self_intersecting"]:
            findings.append(
                {
                    "kind": "self_intersection",
                    "source": "open3d",
                    "name": row["name"],
                    "detail": f"{row['faces']} faces, shells pass through each other",
                }
            )

    report = {
        "objects": [
            dataclasses.asdict(ob) for ob in stats.objects
        ],
        "checks": outcomes,
        "selfx": selfx_rows,
        "findings": findings,
        "verdict": "pass" if not findings else "fail",
        "timings": {
            "probe_s": round(t_probe, 3),
            "checks_s": round(t_checks, 4),
            "selfx_s": round(t_selfx, 3),
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps({"verdict": report["verdict"], "findings": len(findings)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
