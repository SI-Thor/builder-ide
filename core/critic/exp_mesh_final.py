"""Experiment: the mesh half's three signals, measured on the rebuilt scenes.

The first measurement of the mesh half said why absolute thresholds cannot
work on real scenes: the clean props' inward-facing fraction reached 0.593
(vegetation is full of inward faces), the props' sizes vary by up to 5.5×
within a family, and most of them reach outside the frame — a landscape is
shot from inside it.

So the three mesh checks need *categorical* signals — ones that nature does
not produce:

* **hollow** — a shell whose faces are turned inside out has a **negative
  signed volume**, while a correctly-wound solid's is positive. A sign, not
  a magnitude: no amount of natural variation produces one.
* **clipped** — geometry the renderer **cuts**: a prop whose box straddles
  the camera's near plane. A prop that merely reaches outside the picture is
  normal (30 of 44 clean props did); a prop the near plane slices is not.
* **wrong scale** — a prop **bigger than every other prop of its kind**.
  Natural scenes have none, which is what the measurement has to show.

The probe is cached, because it costs a Blender start-up per scene and this
script measures many things about the same scenes.

Run:

    CRITIC_BLENDER_PYTHON=... .venv/bin/python core/critic/exp_mesh_final.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/home/caseydigennaro/lm-wt/critic-calib")

from core.critic.checks import prop_family, props_of  # noqa: E402
from core.critic.mesh import probe_scene  # noqa: E402

PYTHON = os.environ.get(
    "CRITIC_BLENDER_PYTHON", "/home/caseydigennaro/src/infinigen-thor/.venv/bin/python"
)
SCENES = Path("/home/caseydigennaro/lm-critic/scenes")
CACHE = Path("/tmp/critic-probe-cache")


def cached_stats(blend: Path):
    """The scene's measurement, cached by the blend's own hash."""
    import hashlib

    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(blend).encode()).hexdigest()[:16]
    path = CACHE / f"{key}.json"
    if path.is_file():
        from core.critic.mesh import stats_from_payload

        return stats_from_payload(json.loads(path.read_text()))
    payload = Path(f"/tmp/probe-{key}.json")
    stats = probe_scene(str(blend), python=PYTHON)
    # The probe's own JSON, kept verbatim so the numbers stay re-readable.
    from core.critic.mesh import probe_script_path
    import subprocess

    subprocess.run(
        [
            PYTHON,
            str(probe_script_path()),
            "--blend",
            str(blend),
            "--out",
            str(payload),
        ],
        capture_output=True,
        check=False,
    )
    if payload.is_file():
        path.write_text(payload.read_text())
    return stats


def main() -> int:
    blends = sorted(SCENES.glob("*/fine/scene.blend"))
    print(f"scenes: {len(blends)}\n")

    negative = 0
    total_props = 0
    straddles = 0
    volumes: list[float] = []
    inward: list[float] = []
    family_ratios: list[float] = []
    per_scene = []

    for blend in blends:
        stats = cached_stats(blend)
        props = props_of(stats)
        camera = stats.camera
        neg = [o for o in props if o.volume < 0]
        cut = 0
        for obj in props:
            if camera is None:
                continue
            forwards = []
            inside = 0
            for cx in (obj.x0, obj.x1):
                for cy in (obj.y0, obj.y1):
                    for cz in (obj.z0, obj.z1):
                        _r, _u, f = camera.projects((cx, cy, cz))
                        forwards.append(f)
            if forwards and min(forwards) < camera.depth and max(forwards) > camera.depth:
                cut += 1
        total_props += len(props)
        negative += len(neg)
        straddles += cut
        volumes.extend(o.volume for o in props)
        inward.extend(o.inward for o in props)

        families: dict[str, list[float]] = {}
        for obj in props:
            families.setdefault(prop_family(obj.name), []).append(obj.diagonal)
        scene_max_ratio = 0.0
        for members in families.values():
            if len(members) < 2:
                continue
            biggest = max(members)
            for m in members:
                scene_max_ratio = max(scene_max_ratio, m / biggest)
        family_ratios.append(scene_max_ratio)
        per_scene.append((blend.parent.parent.name, len(props), len(neg), cut, scene_max_ratio))
        print(
            f"  {blend.parent.parent.name:12s} props={len(props):4d} "
            f"negative-volume={len(neg):3d} near-plane-cut={cut:3d} "
            f"max family ratio to the family's largest={scene_max_ratio:.3f}"
        )

    print(f"\n=== the signed volume ===")
    print(f"  props: {total_props}, with a negative volume: {negative}")
    volumes.sort()
    print(
        f"  min={volumes[0]:.4f} p50={volumes[len(volumes)//2]:.4f} "
        f"max={volumes[-1]:.4f}"
    )
    inward.sort()
    print(
        f"  inward fraction: min={inward[0]:.3f} p50={inward[len(inward)//2]:.3f} "
        f"p95={inward[int(len(inward)*0.95)]:.3f} max={inward[-1]:.3f}"
    )
    print(f"\n=== the near plane ===")
    print(f"  props cut by the camera's near plane, across all scenes: {straddles}")
    print(f"\n=== the family's largest ===")
    print(f"  the largest clean ratio of a prop to its family's largest: {max(family_ratios):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
