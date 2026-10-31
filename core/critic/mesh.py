"""The mesh probe: a scene's geometry, measured, and seeded defects in it.

Two of the reference set's defect classes live in the **geometry**, not in the
pixels: a prop at the wrong scale, a shell with a hole in it, geometry cut by
the frame's edge. A check cannot see those in a PNG — they are facts about
meshes — so this module measures them.

The seam is deliberately narrow. The core **never imports bpy**: the probe is
a separate script run by the engine's own interpreter (the one that has
``bpy==4.2.0``), which writes a JSON file that this module reads back. That
keeps the core installable on a box with no Blender, and it keeps the numbers
provenance-checkable — the probe's own output *is* the record, and it is
re-readable without the scene.

What the probe measures per object:

* its world-space bounding box (so scale and size are comparable across
  objects, and a prop's size relative to the scene's floor is meaningful);
* whether its shell is **watertight** — a closed solid has every edge shared
  by exactly two faces, so a hole is an edge with fewer;
* the **camera**, so "is this object cut by the frame's edge?" is a
  projection rather than a guess.

The camera's frame is the render's frame: the same width and height the
sweep rendered at, so an object that leaves the picture here leaves the
picture in the PNG too.

Seeding a mesh defect is a **mutation of the measured geometry**, applied to
the probe's own numbers and never to the scene on disk: the sweep's scenes
are read-only, and a member is a recipe plus the numbers it produces.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .models import CameraInfo, MeshObject, MeshStats

__all__ = [
    "DEFAULT_PROBE_SCRIPT",
    "MeshProbeError",
    "probe_scene",
    "probe_script_path",
    "apply_mesh_defect",
    "scale_object",
    "hollow_object",
    "cut_object",
]

#: The probe script, shipped beside this module. It runs under bpy.
DEFAULT_PROBE_SCRIPT = Path(__file__).with_name("probe_scene.py")

#: How long the probe may take before it is treated as a failure. Blender's
#: start-up alone is a couple of seconds; a big scene's statistics pass is
#: the slow part.
PROBE_TIMEOUT_SECONDS = 300


class MeshProbeError(RuntimeError):
    """The probe could not measure the scene — or measured nothing."""


def probe_script_path() -> Path:
    """The path of the probe script the subprocess runs."""
    return DEFAULT_PROBE_SCRIPT


def probe_scene(
    blend_path: str | Path,
    *,
    python: str | None = None,
    script: str | Path | None = None,
    timeout: int = PROBE_TIMEOUT_SECONDS,
) -> MeshStats:
    """Measure a scene's geometry with the engine's own interpreter.

    ``python`` must be an interpreter that can ``import bpy`` — on the Thor
    that is the Infinigen checkout's virtualenv. The probe writes a JSON file
    and this function reads it back, so the numbers cross the seam as data
    rather than as a live object graph.
    """
    if python is None:
        python = os.environ.get("CRITIC_BLENDER_PYTHON")
    if not python:
        raise MeshProbeError(
            "no bpy-capable interpreter: pass python=... or set CRITIC_BLENDER_PYTHON"
        )

    script_path = Path(script) if script is not None else probe_script_path()
    if not script_path.is_file():
        raise MeshProbeError(f"probe script not found: {script_path}")

    with tempfile.TemporaryDirectory(prefix="critic-probe-") as tmp:
        out_path = Path(tmp) / "probe.json"
        cmd = [
            str(python),
            str(script_path),
            "--blend",
            str(blend_path),
            "--out",
            str(out_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing
            raise MeshProbeError(f"probe timed out after {timeout}s") from exc
        if proc.returncode != 0 or not out_path.is_file():
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else "no output"
            raise MeshProbeError(f"probe failed (rc={proc.returncode}): {tail}")
        payload = json.loads(out_path.read_text())

    return stats_from_payload(payload)


def stats_from_payload(payload: dict[str, Any]) -> MeshStats:
    """Rebuild a :class:`MeshStats` from the probe's JSON."""
    objects = tuple(
        MeshObject(
            name=str(o["name"]),
            x0=float(o["x0"]),
            y0=float(o["y0"]),
            z0=float(o["z0"]),
            x1=float(o["x1"]),
            y1=float(o["y1"]),
            z1=float(o["z1"]),
            watertight=bool(o.get("watertight", True)),
            vertices=int(o.get("vertices", 0)),
            faces=int(o.get("faces", 0)),
            inward=float(o.get("inward", 0.0)),
            volume=float(o.get("volume", 0.0)),
        )
        for o in payload.get("objects", ())
    )
    camera: CameraInfo | None = None
    cam = payload.get("camera")
    if cam:
        camera = CameraInfo(
            location=tuple(float(v) for v in cam["location"]),  # type: ignore[arg-type]
            forward=tuple(float(v) for v in cam["forward"]),  # type: ignore[arg-type]
            up=tuple(float(v) for v in cam["up"]),  # type: ignore[arg-type]
            right=tuple(float(v) for v in cam["right"]),  # type: ignore[arg-type]
            half_width=float(cam["half_width"]),
            half_height=float(cam["half_height"]),
            depth=float(cam["depth"]),
        )
    return MeshStats(
        objects=objects,
        camera=camera,
        frame_width=int(payload.get("frame_width", 0)),
        frame_height=int(payload.get("frame_height", 0)),
    )


# -- the seeded mesh defects -------------------------------------------------


def apply_mesh_defect(
    stats: MeshStats, defect: str, *, seed: int = 0
) -> tuple[MeshStats, dict[str, Any]]:
    """Seed a mesh defect into measured geometry and return the new stats.

    The mutation is applied to the *numbers*, never to the scene: the sweep's
    scenes are read-only, and the member is the recipe plus the measurement
    it produces — the same rule the image half follows.
    """
    if defect == "wrong_scale":
        return scale_object(stats, seed=seed)
    if defect == "hollow_mesh":
        return hollow_object(stats, seed=seed)
    if defect == "clipped_geometry":
        return cut_object(stats, seed=seed)
    raise ValueError(f"cannot seed {defect!r} into a mesh")


def _pick_object(stats: MeshStats, seed: int) -> MeshObject:
    """The object a mesh defect is seeded into.

    The choice is deterministic in ``seed`` and skips the emptiest objects,
    so the defect lands on something with real geometry.
    """
    candidates = [o for o in stats.objects if o.faces > 0]
    if not candidates:
        raise MeshProbeError("the scene has no measurable objects")
    candidates.sort(key=lambda o: (-o.faces, o.name))
    pool = [o for o in candidates if o.faces >= 8] or candidates
    index = abs(seed) % len(pool)
    return pool[index]


def _replace(stats: MeshStats, obj: MeshObject) -> MeshStats:
    objects = tuple(obj if o.name == obj.name else o for o in stats.objects)
    return MeshStats(
        objects=objects,
        camera=stats.camera,
        frame_width=stats.frame_width,
        frame_height=stats.frame_height,
    )


def scale_object(
    stats: MeshStats, *, seed: int = 0, factor: float = 1.45
) -> tuple[MeshStats, dict[str, Any]]:
    """A prop at the wrong scale.

    The object is scaled about its own centre, so it stays where it was and
    only its size is wrong — a prop that is 1.45× too big, standing on the
    ground among props of its own kind at the right size.

    The object is chosen from a **family** of more than one, because "the
    wrong scale" is a claim about a prop compared with the other props of
    its kind. A family of one has nothing to compare against.
    """
    families: dict[str, list[MeshObject]] = {}
    for obj in stats.objects:
        if obj.faces <= 0:
            continue
        families.setdefault(_family(obj.name), []).append(obj)
    pools = [members for members in families.values() if len(members) > 1]
    if not pools:
        pools = [[o for o in stats.objects if o.faces > 0]]
    if not pools or not pools[0]:
        raise MeshProbeError("the scene has no measurable objects")
    pool = sorted(pools, key=lambda m: (-len(m), m[0].name))[abs(seed) % len(pools)]
    members = sorted(pool, key=lambda o: (-o.faces, o.name))
    obj = members[abs(seed) % len(members)]

    cx, cy, cz = obj.centre
    sx, sy, sz = obj.size
    new = MeshObject(
        name=obj.name,
        x0=cx - sx * factor / 2.0,
        y0=cy - sy * factor / 2.0,
        z0=cz - sz * factor / 2.0,
        x1=cx + sx * factor / 2.0,
        y1=cy + sy * factor / 2.0,
        z1=cz + sz * factor / 2.0,
        watertight=obj.watertight,
        vertices=obj.vertices,
        faces=obj.faces,
        inward=obj.inward,
        volume=obj.volume,
    )
    return _replace(stats, new), {
        "object": obj.name,
        "family": _family(obj.name),
        "factor": factor,
        "before": [obj.x0, obj.y0, obj.z0, obj.x1, obj.y1, obj.z1],
        "after": [new.x0, new.y0, new.z0, new.x1, new.y1, new.z1],
    }


def _family(name: str) -> str:
    """The asset family a prop belongs to."""
    import re

    base = name.split(".")[0]
    base = re.sub(r"\(\d+\)$", "", base)
    return base.split("(")[0]


def hollow_object(
    stats: MeshStats, *, seed: int = 0, inward: float = 0.75
) -> tuple[MeshStats, dict[str, Any]]:
    """A shell with a hole in it — a shell you can see the inside of.

    A **hollow** shell is not the same thing as an **open** one. Infinigen's
    terrain and its eroded rock shells are open surfaces: every face points
    outwards. A hollow prop has faces pointing back at its own centre, so
    the picture shows the inside of the object.

    The prop is chosen among the ones whose shell is *closed* — a shell with
    a hole in it must have had something to lose — and its faces are turned
    inwards. Nothing about its size or position moves: a hollow shell is
    exactly the same size as a solid one.
    """
    candidates = [o for o in stats.objects if o.faces > 0 and o.inward < 0.2]
    if not candidates:
        candidates = [o for o in stats.objects if o.faces > 0]
    if not candidates:
        raise MeshProbeError("the scene has no measurable objects")
    candidates.sort(key=lambda o: (-o.faces, o.name))
    obj = candidates[abs(seed) % len(candidates)]
    new = MeshObject(
        name=obj.name,
        x0=obj.x0,
        y0=obj.y0,
        z0=obj.z0,
        x1=obj.x1,
        y1=obj.y1,
        z1=obj.z1,
        watertight=obj.watertight,
        vertices=obj.vertices,
        faces=obj.faces,
        inward=inward,
        volume=-abs(obj.volume) if obj.volume else 0.0,
    )
    return _replace(stats, new), {
        "object": obj.name,
        "was_inward": obj.inward,
        "now_inward": inward,
        "was_watertight": obj.watertight,
    }


def cut_object(
    stats: MeshStats, *, seed: int = 0
) -> tuple[MeshStats, dict[str, Any]]:
    """Geometry cut by the frame's edge.

    The object is moved so far that it crosses the picture's edge — the
    camera decides whether it is cut, exactly as the check does, so the
    mutation and the check share one oracle rather than two guesses.
    """
    camera = stats.camera
    if camera is None:
        raise MeshProbeError("the scene has no camera; cannot seed clipped geometry")
    obj = _pick_object(stats, seed)
    cx, cy, cz = obj.centre
    right, up, _forward = camera.projects((cx, cy, cz))
    # Push it out along the camera's own right axis until it is well past
    # the edge of the picture.
    overshoot = camera.half_width * 1.6
    shift = overshoot - right
    dx = camera.right[0] * shift
    dy = camera.right[1] * shift
    dz = camera.right[2] * shift
    new = MeshObject(
        name=obj.name,
        x0=obj.x0 + dx,
        y0=obj.y0 + dy,
        z0=obj.z0 + dz,
        x1=obj.x1 + dx,
        y1=obj.y1 + dy,
        z1=obj.z1 + dz,
        watertight=obj.watertight,
        vertices=obj.vertices,
        faces=obj.faces,
    )
    return _replace(stats, new), {
        "object": obj.name,
        "shift": [dx, dy, dz],
        "before": [obj.x0, obj.y0, obj.z0, obj.x1, obj.y1, obj.z1],
        "after": [new.x0, new.y0, new.z0, new.x1, new.y1, new.z1],
    }
