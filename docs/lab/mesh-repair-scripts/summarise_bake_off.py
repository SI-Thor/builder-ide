"""Turn the bake-off's raw results into the table the lab record carries.

Reads ``artifacts/mesh-repair/bake_off.json`` and prints, for each method,
the four numbers the brief asks for — watertightness, triangles, the
silhouette IoU against the original, and the CPU time — aggregated over the
nine meshes, with the load average the measurements were taken at.

Run: .venv/bin/python docs/lab/mesh-repair-scripts/summarise_bake_off.py
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path("artifacts/mesh-repair/bake_off.json")

ORDER = [
    "none",
    "weld",
    "trimesh_fill_holes",
    "pymeshfix",
    "manifold3d",
    "voxel_128",
]


def main() -> None:
    if not RESULTS.exists():
        raise SystemExit(f"no results at {RESULTS}")
    rows = json.loads(RESULTS.read_text())
    by_method: dict[str, list[dict]] = {}
    for row in rows:
        by_method.setdefault(row["method"], []).append(row)

    print(
        "| method | meshes | watertight | triangles | silhouette IoU | CPU (s) | load |"
    )
    print("|---|---:|---|---:|---|---:|---:|")
    for method in ORDER + [m for m in by_method if m not in ORDER]:
        entries = by_method.get(method)
        if not entries:
            continue
        good = [e for e in entries if not e.get("error")]
        if not good:
            errors = sorted({e.get("error", "") for e in entries})
            print(f"| `{method}` | {len(entries)} | **failed** | — | — | — | — |")
            for error in errors:
                print(f"| | | | | | | {error} |")
            continue
        watertight = sum(1 for e in good if e.get("watertight"))
        triangles = [e["triangles"] for e in good]
        ious = [e.get("fidelity", 0.0) for e in good]
        seconds = [e["seconds"] for e in good]
        loads = [e.get("load", 0.0) for e in good]
        print(
            f"| `{method}` | {len(good)} | {watertight}/{len(good)} | "
            f"{min(triangles):,}–{max(triangles):,} | "
            f"{min(ious):.4f}–{max(ious):.4f} | "
            f"{min(seconds):.2f}–{max(seconds):.2f} | "
            f"{min(loads):.0f}–{max(loads):.0f} |"
        )


if __name__ == "__main__":
    main()
