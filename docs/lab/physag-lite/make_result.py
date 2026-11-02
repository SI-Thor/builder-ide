"""Build docs/lab/physag-lite/RESULT.json from the three arm summaries.

Run on the Thor:

    python docs/lab/physag-lite/make_result.py

It reads the committed summary.json of each arm (plus the per-prop
deliveries for the wall times) and writes RESULT.json beside the
experiment doc. Re-running it after any arm re-run keeps the numbers
in one place, one fact per place.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ART = REPO / "artifacts" / "physag-lite"
OUT = Path(__file__).resolve().parent / "RESULT.json"

BASELINE = {
    "source": "PhysAg3D",
    "completion_rate_in_the_wild": 0.913,
    "note": "PhysAg3D's reported action-completion rate on in-the-wild objects; the arms below are measured on the same question",
}


def per_prop(arm_dir: Path) -> dict:
    out = {}
    for p in sorted(arm_dir.iterdir()):
        d = p / "delivery.json"
        if not d.exists():
            err = (p / "error.txt").read_text().strip() if (p / "error.txt").exists() else None
            out[p.name] = {"error": err}
            continue
        r = json.load(open(d))
        t = r.get("timings") or {}
        comp = (r.get("check") or {}).get("completion") or {}
        out[p.name] = {
            "interaction_status": r.get("interaction_status"),
            "physics_status": r.get("physics_status"),
            "counted": r.get("counted"),
            "completed": comp.get("completed"),
            "reached": comp.get("reached"),
            "target": comp.get("target"),
            "repair_used": (r.get("repair") or {}).get("used"),
            "wall_s": t.get("wall_s"),
            "gpu_busy_s": t.get("gpu_busy_s"),
        }
    return out


def arm(name: str, arm_dir: Path, extra: dict) -> dict:
    s = json.load(open(arm_dir / "summary.json"))
    out = {k: s[k] for k in (
        "props", "counted", "completed", "completion_rate",
        "stable", "stable_of_counted", "wall_s_total",
    ) if k in s}
    out["per_prop"] = per_prop(arm_dir)
    out.update(extra)
    return out


trellis = arm("trellis", ART / "run-trellis", {})
s = json.load(open(ART / "run-trellis" / "summary.json"))
trellis["repairs_used"] = s["repairs_used"]
trellis["repaired_props"] = s["repaired_props"]
trellis["not_counted"] = s["not_counted"]
trellis["gpu_busy_s_total"] = 0.0
trellis["gpu_note"] = (
    "the meshes are pre-generated (exp doc section 3, 955.9 s GPU-busy "
    "for the batch); the arm itself is CPU-only, so its GPU column is 0 by construction"
)
trellis["superseded_run"] = "artifacts/physag-lite/run-trellis-buggyseg/ (before the box-cut fix; its four box-cut props could not build)"

cad = arm("cad", ART / "run-cad", {
    "not_built": ["cart", "ladder", "lantern"],
    "not_built_reason": "the recorded SolidCraft scripts have kernel errors; the designs were not edited to make them build",
    "gpu_busy_s_total": 0.0,
    "reverified": "artifacts/physag-lite/run-cad-1133/ agrees field for field on the final code",
})

seed = arm("seed", ART / "run-seed", {
    "repairs_used": 0,
    "repair_note": "no repair round by design: the arm compares whose priors ran",
    "priors_scoring": json.load(open(ART / "run-seed" / "summary.json"))["priors_scoring"],
    "gpu_busy_s_total": 0.0,
})

result = {
    "experiment": "physag-lite",
    "date": "2026-11-01",
    "doc": "docs/lab/exp-physag-lite.md",
    "question": "can our own loop — plan in the cloud, generate on the Thor, segment, build MJCF, check in MuJoCo on CPU, repair once, record — deliver props whose action runs, and what does each stage cost?",
    "baseline": BASELINE,
    "arms": {
        "trellis": trellis,
        "cad": cad,
        "seed": seed,
    },
    "generation": {
        "doc_section": "exp-physag-lite.md section 3",
        "mesh_step_wall_s_total": "about 24 min for the ten",
        "gpu_busy_s_total": 955.9,
        "gpu_util_mean_pct": 66.6,
        "meshes": "ten TRELLIS.2 GLBs, ~700k triangles each, ~1 m across",
    },
    "notes": [
        "completion rates count only props whose part-to-spec mapping verified (guard 1)",
        "every generated-arm stability score is void, not failed: the convex colliders stray 110-635 mm from the organic material and the guard refuses to score on them (guard 2)",
        "the only stable physics scores in the experiment are the two exact-solid CAD props (door, drawer_unit)",
        "drawer_unit and gate do not build on the generated arm because their meshes are featureless solid blocks: 0 of ~699k triangle centres inside the plan's moving-part box",
        "the seed arm's mass deviations (planner vs volume-scaled SimReady midpoint) run from -16% to +2743%; the single-observation ranges are tight by construction and worth exactly one asset",
    ],
}

OUT.write_text(json.dumps(result, indent=2) + "\n")
print(f"wrote {OUT}")
