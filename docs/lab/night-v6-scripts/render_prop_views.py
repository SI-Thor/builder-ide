#!/usr/bin/env python3
"""render_prop_views.py — a prop's mesh, rendered from three views.

The ghost's second look needs to see the *prop* — the mesh the plausibility
prior judged — not the picture the mesh was made from. Night-v5's ghost
(lantern_r2_v3, occupied volume 1.004) came from a perfectly good lantern
picture; the degeneracy was in the mesh, and a second look at the picture
would have praised it. So the prop's GLB is rendered here, from three
turntable views, and the renders are what the cloud model is shown.

Runs under the v2 venv's bpy (the same Blender export_scene.py uses), in
the background, on the CPU — Cycles at 16 samples, 640 px, an orthographic
camera that frames the whole object, a neutral grey world and one sun. The
question the second look asks is about shape (a solid block against a real
object), not material, so the renders are deliberately plain.

    ~/lm-wt/v2-thor/.venv/bin/python render_prop_views.py \
        --glb /path/to/prop.glb --outdir /tmp/views

Writes view_1.png .. view_3.png and render_stats.json (triangles, wall).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--views", type=int, default=3)
    parser.add_argument("--size", type=int, default=640)
    args = parser.parse_args()

    started = time.perf_counter()
    out = args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    import bpy  # noqa: PLC0415  (only importable under the v2 venv)
    from mathutils import Vector  # noqa: PLC0415

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.glb.resolve()))

    corners = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            corners.extend(obj.matrix_world @ Vector(c) for c in obj.bound_box)
    if not corners:
        print(json.dumps({"error": "the GLB holds no mesh objects"}))
        return 1
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners),
                 min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners),
                 max(c.z for c in corners)))
    center = (lo + hi) / 2.0
    radius = max((hi - lo).x, (hi - lo).y, (hi - lo).z) / 2.0 or 0.5

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = args.size
    scene.render.resolution_y = args.size

    world = bpy.data.worlds.new("neutral")
    world.use_nodes = False
    world.color = (0.65, 0.65, 0.68)
    scene.world = world

    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(35), 0.0, math.radians(40))
    scene.collection.objects.link(sun)

    camera = bpy.data.cameras.new("cam")
    camera.type = "ORTHO"
    camera.ortho_scale = radius * 2.0 * 1.25
    cam_obj = bpy.data.objects.new("cam", camera)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    # A quarter turn between views: front-quarter, profile, back-quarter —
    # an object that is a solid block reads as one from all three, and an
    # object with openings shows them from at least one.
    azimuths = [25.0, 90.0 + 180.0 / max(args.views, 1), 155.0][: args.views]
    while len(azimuths) < args.views:
        azimuths.append(azimuths[-1] + 45.0)
    elevation = math.radians(22.0)
    distance = radius * 2.6
    written = []
    for index, azimuth in enumerate(azimuths, start=1):
        angle = math.radians(azimuth)
        cam_obj.location = (
            center.x + distance * math.cos(elevation) * math.cos(angle),
            center.y + distance * math.cos(elevation) * math.sin(angle),
            center.z + distance * math.sin(elevation),
        )
        look = center - cam_obj.location
        cam_obj.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
        target = out / f"view_{index}.png"
        scene.render.filepath = str(target)
        bpy.ops.render.render(write_still=True)
        written.append(target.name)

    triangles = sum(len(polygon.vertices) - 2
                    for mesh in bpy.data.meshes
                    for polygon in mesh.polygons)
    stats = {
        "glb": str(args.glb),
        "views": written,
        "triangles": triangles,
        "orthographic": True,
        "wall_s": round(time.perf_counter() - started, 2),
        "python": sys.version.split()[0],
    }
    (out / "render_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))
    sys.stdout.flush()
    sys.stderr.flush()
    # This box's bpy segfaults during interpreter teardown after a Cycles
    # render (rc -11, after every file is written — measured 2026-11-02).
    # The work is done; skip the crashing teardown.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
