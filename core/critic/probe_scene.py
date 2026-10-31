"""The mesh probe — the script that runs inside Blender.

Run by the engine's own interpreter (the one with ``bpy==4.2.0``), against a
``scene.blend``, writing a JSON file the core reads back. The core never
imports bpy; this is the seam.

    python probe_scene.py --blend <scene.blend> --out <probe.json>

What it measures, and why:

* **Per object**, its world-space bounding box. Scale and size are only
  comparable across objects in world space, and a prop's height above the
  floor is the floating-object oracle.
* **Per object**, whether its shell is *watertight*: a closed solid has every
  edge shared by exactly two faces. A hole is an edge with fewer, so the
  check is a count, not a guess.
* **The camera**, as a frame in the world: its position, its axes, and the
  picture's half-width and half-height at the scene's depth. That makes "is
  this object cut by the frame?" a projection.

The frame's size is taken from the render settings, so it is the picture the
sweep actually rendered — an object outside this frame is outside the PNG.

Only meshes that carry geometry are measured: the terrain, the props, the
things the scene is made of. Lights and empties are skipped.
"""

from __future__ import annotations

import argparse
import json
import math
import sys


def _axis_vectors(camera) -> dict[str, tuple[float, float, float]]:
    """The camera's world axes, from its matrix.

    Blender's camera looks down its **local -Z**; local +Y is up and local
    +X is right. Those are the axes the frame is built from.
    """
    matrix = camera.matrix_world
    right = (matrix[0][0], matrix[1][0], matrix[2][0])
    up = (matrix[0][1], matrix[1][1], matrix[2][1])
    back = (matrix[0][2], matrix[1][2], matrix[2][2])
    forward = (-back[0], -back[1], -back[2])
    return {"right": right, "up": up, "forward": forward}


def _scene_depth(objects, camera) -> float:
    """How far the scene's content is from the camera.

    The frame's half-width is quoted at this depth, so the picture's size
    follows the render's own field of view. The median object depth is used
    rather than the nearest one, so a single prop in the foreground does not
    shrink the frame.
    """
    depths = []
    for obj in objects:
        centre = obj.matrix_world.translation
        relative = camera.matrix_world.inverted() @ centre
        depth = -relative.z
        if depth > 1e-6:
            depths.append(depth)
    if not depths:
        return 1.0
    depths.sort()
    return depths[len(depths) // 2]


def _is_watertight(mesh) -> bool:
    """Is this mesh's shell closed?

    Every edge of a closed solid is shared by exactly two faces. A shell with
    a hole has boundary edges (one face) and non-manifold edges (three or
    more). Both mean "not a solid".

    The count is done with bmesh, which is Blender's own mesh library, so it
    is the engine's own answer rather than a re-implementation.
    """
    import bmesh

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        for edge in bm.edges:
            if len(edge.link_faces) != 2:
                return False
        return True
    finally:
        bm.free()


def _shell_facts(mesh) -> dict[str, float]:
    """How the shell faces, and whether it turns inward anywhere.

    A **hollow** shell is not the same thing as an **open** one. An open
    surface (Infinigen's terrain and its eroded rock shells are open) has
    every face pointing outward. A hollow shell has faces pointing *inward* —
    you can see the inside of the prop.

    Two numbers tell them apart:

    * ``inward`` — the fraction of faces whose normal points towards the
      object's own centre. Zero for a correctly-wound surface; large for a
      shell that folds back on itself.
    * ``volume`` — the mesh's signed volume, by the divergence theorem. An
      open surface's volume is meaningless (it is the volume under the
      surface, not of the solid), while a solid's is its real volume and its
    sign says which way it faces.
    """
    import bmesh

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        if not bm.faces:
            return {"inward": 0.0, "volume": 0.0}
        centre = bm.verts[0].co.copy()
        for vert in bm.verts:
            centre += vert.co
        centre /= max(1, len(bm.verts))

        inward = 0
        for face in bm.faces:
            if face.normal.dot(face.calc_center_median() - centre) < 0.0:
                inward += 1
        volume = bm.calc_volume(signed=True)
        return {
            "inward": inward / float(len(bm.faces)),
            "volume": float(volume),
        }
    finally:
        bm.free()


def measure(blend_path: str, out_path: str) -> None:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=blend_path)

    scene = bpy.context.scene
    frame_width = int(scene.render.resolution_x)
    frame_height = int(scene.render.resolution_y)
    percentage = int(scene.render.resolution_percentage)
    if percentage > 0:
        frame_width = max(1, frame_width * percentage // 100)
        frame_height = max(1, frame_height * percentage // 100)

    from mathutils import Vector

    objects = []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        # A world-space bounding box: the corners of the object's local box,
        # pushed through the object's own matrix.
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        xs = [float(c[0]) for c in corners]
        ys = [float(c[1]) for c in corners]
        zs = [float(c[2]) for c in corners]
        mesh = obj.data
        facts = _shell_facts(mesh)
        objects.append(
            {
                "name": obj.name,
                "x0": min(xs),
                "y0": min(ys),
                "z0": min(zs),
                "x1": max(xs),
                "y1": max(ys),
                "z1": max(zs),
                "watertight": _is_watertight(mesh),
                "inward": facts["inward"],
                "volume": facts["volume"],
                "vertices": len(mesh.vertices),
                "faces": len(mesh.polygons),
            }
        )

    camera_payload = None
    camera = scene.camera
    if camera is not None:
        axes = _axis_vectors(camera)
        location = tuple(float(v) for v in camera.matrix_world.translation)
        depth = _scene_depth(
            [o for o in scene.objects if o.type == "MESH"], camera
        )
        # The picture's half-width at that depth. Blender has already
        # resolved the sensor fit into these angles, so they are the camera's
        # own field of view rather than a re-derivation of it:
        # half_width = depth * tan(angle_x / 2).
        camera_data = camera.data
        angle_x = float(getattr(camera_data, "angle_x", 0.0))
        angle_y = float(getattr(camera_data, "angle_y", 0.0))
        if angle_x > 0.0:
            half_width = depth * math.tan(angle_x / 2.0)
        else:  # pragma: no cover - Blender always has an angle
            sensor_width = float(getattr(camera_data, "sensor_width", 36.0)) or 36.0
            lens = float(getattr(camera_data, "lens", 50.0)) or 50.0
            half_width = depth * sensor_width / (2.0 * lens)
        if angle_y > 0.0:
            half_height = depth * math.tan(angle_y / 2.0)
        else:  # pragma: no cover
            half_height = half_width * (frame_height / float(frame_width or 1))
        camera_payload = {
            "location": list(location),
            "forward": list(axes["forward"]),
            "up": list(axes["up"]),
            "right": list(axes["right"]),
            "half_width": half_width,
            "half_height": half_height,
            "depth": depth,
            # The distance at which the renderer starts cutting geometry.
            # Nothing in a clean scene straddles it; a prop that does is
            # sliced by the camera itself.
            "clip_start": float(getattr(camera_data, "clip_start", 0.1) or 0.1),
        }

    payload = {
        "blend": blend_path,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "objects": objects,
        "camera": camera_payload,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure a scene's geometry.")
    parser.add_argument("--blend", required=True, help="the scene.blend to open")
    parser.add_argument("--out", required=True, help="where to write the JSON")
    args = parser.parse_args(argv)
    try:
        measure(args.blend, args.out)
    except Exception as exc:  # noqa: BLE001 - the failure must reach the core
        print(f"probe failed: {exc}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
