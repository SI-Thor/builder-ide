#!/usr/bin/env python3
"""The metric scale: metres per pixel, from the scene's own camera.

The frame's units — pixels and frame heights — are exact and need nothing but
the picture. The **metre** value needs the scene the picture came from: the
geometry probe reads the scene's camera out of the ``.blend``, the camera's
frame at the scene's depth is quoted in metres, and that divided by the
picture's width in pixels is the scale of the picture.

This script measures that scale for every scene the reference set points at,
and then measures what the scale does to a continuation: for each member
whose defect is a floating object and whose scene is on the box, the frame
probe's drop distance in pixels and the same drop in metres.

    python docs/lab/critic-delegate-scripts/scene_scale.py

It writes ``results/scene-scale.json``. The mesh half needs an interpreter
with ``bpy`` — the Infinigen checkout's virtualenv on the Thor:

    export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python

The probe caches its measurements under ``core/critic/.cache/``, so a second
run over the same scenes costs no interpreter at all.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELECT = HERE.parent / "critic-select-scripts"
for path in (str(HERE), str(SELECT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from harness import CACHE, MANIFEST, load_set  # noqa: E402

from core.critic.imaging import load_rgb  # noqa: E402
from core.critic.mesh import blender_python_from_env, probe_scene  # noqa: E402
from core.critic.surface import scene_scale, suggest_edit  # noqa: E402

RESULTS = HERE / "results"


def _box_state() -> dict:
    """The box's state, beside the numbers."""
    import subprocess

    def _read(path: str, pattern: str) -> float | None:
        try:
            text = Path(path).read_text()
        except OSError:
            return None
        match = re.search(pattern, text)
        return float(match.group(1)) if match else None

    mem = _read("/proc/meminfo", r"MemAvailable:\s+(\d+) kB")
    model = None
    try:
        model = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - the box state is best effort
        model = None
    return {
        "kernel": platform.release(),
        "arch": platform.machine(),
        "mem_available_gib": round(mem / 1048576.0, 2) if mem else None,
        "gpu": model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST))
    args = parser.parse_args()

    members, _bases = load_set(args.manifest, CACHE)
    python = blender_python_from_env()
    if not python:
        print(
            "! no bpy-capable interpreter named (CRITIC_BLENDER_PYTHON) — "
            "the scale cannot be measured"
        )
        return 1

    # -- the scale, scene by scene ------------------------------------------------
    scenes: dict[str, dict] = {}
    for member in members:
        blend = member.mesh_path
        if not blend or blend in scenes:
            continue
        if not Path(blend).is_file():
            scenes[blend] = {"blend": blend, "error": "the .blend is not on this box"}
            continue
        try:
            stats = probe_scene(blend, python=python, cache_dir=CACHE)
        except Exception as exc:  # noqa: BLE001 - a scene that cannot be probed
            scenes[blend] = {"blend": blend, "error": str(exc)}
            continue
        scale = scene_scale(stats)
        scenes[blend] = {
            "blend": blend,
            "base_id": member.base_id,
            "camera_half_width_m": stats.camera.half_width,
            "camera_depth_m": stats.camera.depth,
            "frame_width_px": stats.frame_width,
            "frame_height_px": stats.frame_height,
            "metres_per_pixel": scale,
        }
        print(
            f"  {member.base_id:12s} {scale:.6f} m/px "
            f"(half width {stats.camera.half_width:.3f} m at "
            f"{stats.camera.depth:.1f} m, {stats.frame_width} px wide)"
        )

    # -- what the scale does to a continuation -------------------------------------
    continuations = []
    for member in members:
        if member.defect != "floating_object" or not member.derived_path:
            continue
        blend = member.mesh_path
        entry = scenes.get(blend) if blend else None
        scale = (entry or {}).get("metres_per_pixel")
        if not scale:
            # No scene on this box: the edit stays in the frame's units, and
            # says so, rather than carrying a metre value nobody measured.
            continuations.append(
                {
                    "member_id": member.member_id,
                    "base_id": member.base_id,
                    "scene": blend,
                    "metres_per_pixel": None,
                    "drop_m": None,
                    "note": "no scene on this box: the edit carries the frame's units",
                }
            )
            continue
        try:
            image = load_rgb(member.derived_path)
        except OSError as exc:
            continuations.append(
                {
                    "member_id": member.member_id,
                    "base_id": member.base_id,
                    "scene": blend,
                    "metres_per_pixel": scale,
                    "drop_m": None,
                    "note": f"the frame is not here: {exc}",
                }
            )
            continue
        edit = suggest_edit(image, metres_per_pixel=scale)
        row = {
            "member_id": member.member_id,
            "base_id": member.base_id,
            "scene": blend,
            "metres_per_pixel": scale,
            "edit": edit.as_dict() if edit else None,
            "drop_m": edit.drop_m if edit else None,
            "drop_px": edit.drop_px if edit else None,
        }
        continuations.append(row)
        if edit:
            print(
                f"  {member.member_id} ({member.base_id}): drop {edit.drop_px} px "
                f"= {edit.drop_m:.2f} m at {scale:.6f} m/px"
            )

    payload = {
        "scenes": scenes,
        "continuations": continuations,
        "box": _box_state(),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "scene-scale.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    measured = [s for s in scenes.values() if s.get("metres_per_pixel")]
    if measured:
        lo = min(s["metres_per_pixel"] for s in measured)
        hi = max(s["metres_per_pixel"] for s in measured)
        print(f"\n{len(measured)} scenes measured: {lo:.6f} - {hi:.6f} m/px")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
