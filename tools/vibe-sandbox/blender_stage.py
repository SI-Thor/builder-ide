"""Assemble, decimate-if-over-budget, and export — inside the Thor's system
Blender 4.0.2 (``blender --background --python blender_stage.py -- ...``).

Reads the generator's scene.json, imports each named STL (already in world
coordinates), decimates any object over the triangle budget (quadric LOD is
the open3d-critic lane's rule: decimate on budget, not blindly), adds one
overview camera (the critic's edge-cut check needs one), saves a .blend for
the critic's probe, and exports the GLB the viewer hot-loads.
"""

import json
import sys
import time
from pathlib import Path

import bpy

MAX_TRIS = 20000


def parse_args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    out = {}
    i = 0
    while i < len(argv):
        out[argv[i].lstrip("-")] = argv[i + 1]
        i += 2
    return out


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()
    scene = json.loads(Path(args["spec"]).read_text())
    parts_dir = Path(args["parts"])
    out_glb = Path(args["out"])
    out_blend = Path(args["blend"])

    bpy.ops.wm.read_factory_settings(use_empty=True)

    objects = []
    names = list(scene["shell"]) + [p["name"] for p in scene["props"]]
    for name in names:
        stl = parts_dir / f"{name}.stl"
        before = set(bpy.context.scene.objects)
        bpy.ops.wm.stl_import(filepath=str(stl), global_scale=1.0)
        new = [o for o in bpy.context.scene.objects if o not in before]
        for obj in new:
            obj.name = name
            obj.data.name = name
            objects.append(obj)

    # one overview camera, framed on the whole room (the critic's edge-cut
    # check projects objects against the render frame; a whole-room frame
    # cuts nothing)
    room = scene["room"]
    import math

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 18.0  # wide enough that no prop is cut by the frame
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (room["width"] / 2, room["depth"] / 2 + 0.75 * room["depth"], 0.9 * room["height"])
    cam.rotation_euler = (
        math.radians(55.0),
        0.0,
        math.radians(-90.0),
    )
    bpy.context.scene.camera = cam
    bpy.context.scene.render.resolution_x = 1280
    bpy.context.scene.render.resolution_y = 720

    report = {"objects": [], "decimated": []}
    t_import = time.perf_counter() - t0

    for obj in objects:
        faces = len(obj.data.polygons)
        entry = {"name": obj.name, "faces": faces}
        if faces > MAX_TRIS:
            ratio = MAX_TRIS / faces
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("budget", "DECIMATE")
            mod.ratio = ratio
            bpy.ops.object.modifier_apply(modifier="budget")
            entry["decimated_to"] = len(obj.data.polygons)
            report["decimated"].append(obj.name)
        report["objects"].append(entry)

    bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
    bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format="GLB")
    report["timings"] = {
        "import_s": round(t_import, 3),
        "total_s": round(time.perf_counter() - t0, 3),
    }
    report["glb_bytes"] = out_glb.stat().st_size
    Path(args["report"]).write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report))


main()
