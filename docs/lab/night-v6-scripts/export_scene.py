#!/usr/bin/env python3
"""export_scene.py — generate an Infinigen 2.0 scene and export it as glTF.

Night-v6's copy of the world-stream exporter (~/lm-wt/world-stream-scratch/
export_scene.py is the team's own; this one is committed beside its
measurements, docs/lab/night-v6.md). One resident bpy process:

    generate (procfunc, CPU only — no render)  ->  save .blend  ->  export .glb

The scene-generation call is the exact code path the `infinigen` CLI uses
(`infinigen2.generate._main`), so the export is "a real Infinigen 2.0 run"
rather than a hand-built scene. Everything this script writes goes under
--outdir.

**Decimate first (night-v6).** The glTF export walks the *evaluated*
meshes, and this scene evaluates to millions of triangles — two hours of
Python on one CPU core (115 and 136 min measured 2026-10-31; 240 min at
the 4 h bound on the loaded box of 2026-11-01, killed mid-walk). Two
passes bring it inside a night, and the probe of night-v5's own
scene.blend says both are needed:

* the scene holds 28 Subdivision Surface modifiers (levels up to 6) —
  `--max-subsurf N` caps them at N levels before the export;
* **and** 91 % of the base polygons are three throw pillows at 884,736
  polygons each with *no modifiers at all* (2.65 M of 2.90 M base
  polygons — capping subdivision cannot touch them) — `--decimate-over M`
  adds a collapse Decimate modifier to every mesh object whose base
  polygon count exceeds M, sized to bring it under M.

The cap, the decimations and the counts ride export_stats.json, so a
delta compiled from this source says what it was decimated from. A
pillow at 884 k polygons decimated to 50 k is still a pillow; the
fidelity choice is recorded, not hidden.

`--from-blend PATH` opens a saved scene instead of generating one — the
measurement path: night-v5's own scene.blend, capped and exported, is the
like-for-like comparison against the 115/136 min walks.

Usage (on the Thor, the v2 venv's python):
    ~/lm-wt/v2-thor/.venv/bin/python export_scene.py \
        --generator room_livingroom_rand --seed 42 \
        --max-subsurf 1 --outdir <dir>

    ~/lm-wt/v2-thor/.venv/bin/python export_scene.py \
        --from-blend ~/lm-wt/night-v5/artifacts/night-v5/worldstream/export/scene.blend \
        --max-subsurf 1 --outdir <dir>

Writes: scene.blend (generation path only), source.glb, export_stats.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generator", default="room_livingroom_rand")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--max-subsurf", type=int, default=0,
                    help="cap every Subdivision Surface modifier at this "
                         "many levels before the export (night-v6's "
                         "decimate-first path; -1 keeps the scene's own "
                         "levels). 0: the exporter walks the saved cages")
    ap.add_argument("--materials", choices=("placeholder", "export"),
                    default="placeholder",
                    help="placeholder (the measured cheap path): write a "
                         "default material instead of walking each "
                         "material's node graph. The stack dump of the "
                         "stalled export of 2026-11-02 (py-spy) says the "
                         "node-tree search — gltf2_blender_search_node_tree "
                         "recursing over Infinigen's procedural materials — "
                         "is what made this export cost 115-240 minutes, "
                         "not the triangles")
    ap.add_argument("--decimate-over", type=int, default=5_000,
                    help="add a collapse Decimate modifier to every mesh "
                         "object whose base polygon count exceeds this "
                         "(sized to bring it under); 0 disables. The "
                         "measured cost curve on this box says the "
                         "threshold is load-bearing: one 884,736-polygon "
                         "cushion decimated to 5,000 polygons exports in "
                         "36 s, and the same cushion held at 50,000 ran "
                         "past 6 minutes without finishing (the extractor "
                         "blows up with density, not linearly). The probe "
                         "of night-v5's scene: three such pillows hold "
                         "2.65 M of the 2.90 M base polygons, with no "
                         "modifiers to cap")
    ap.add_argument("--from-blend", type=Path, default=None,
                    help="open this saved scene instead of generating one")
    args = ap.parse_args()

    out = args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    timings: dict[str, float] = {}
    subsurf: dict[str, object] = {}

    t0 = time.perf_counter()
    import bpy  # noqa: F401
    import infinigen2.generate as ig
    timings["import_bpy_infinigen"] = time.perf_counter() - t0

    if args.from_blend is not None:
        t1 = time.perf_counter()
        bpy.ops.wm.open_mainfile(filepath=str(args.from_blend.resolve()))
        timings["open_blend"] = time.perf_counter() - t1
    else:
        # ---- generate the scene exactly as the CLI would (minus any render)
        argv = [
            "infinigen",
            args.generator,
            "--seed", str(args.seed),
            "--output", str(out / "gen"),
            "--save_blend", str(out / "scene.blend"),
            "--cpu_threads", "4",          # stay polite: the box runs other jobs
        ]
        old_argv = sys.argv
        sys.argv = argv
        t1 = time.perf_counter()
        try:
            ig._main()
        finally:
            sys.argv = old_argv
        timings["generate_scene"] = time.perf_counter() - t1

    # ---- decimate first: cap the subdivision, collapse the giants --------
    t2 = time.perf_counter()
    levels_before: Counter[int] = Counter()
    modifier_types: Counter[str] = Counter()
    capped = 0
    decimated: list[dict] = []
    for obj in bpy.data.objects:
        for modifier in obj.modifiers:
            modifier_types[modifier.type] += 1
            if modifier.type == "SUBSURF":
                levels_before[int(modifier.levels)] += 1
                if 0 <= args.max_subsurf < int(modifier.levels):
                    modifier.levels = args.max_subsurf
                    capped += 1
                if 0 <= args.max_subsurf and hasattr(modifier, "render_levels"):
                    try:
                        if int(modifier.render_levels) > args.max_subsurf:
                            modifier.render_levels = args.max_subsurf
                    except (TypeError, ValueError):
                        pass
        if (obj.type == "MESH" and args.decimate_over > 0
                and len(obj.data.polygons) > args.decimate_over):
            polys = len(obj.data.polygons)
            modifier = obj.modifiers.new("night6_decimate", "DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = args.decimate_over / polys
            decimated.append({"object": obj.name[:60], "polygons": polys,
                              "ratio": round(modifier.ratio, 6)})
    timings["decimate_first"] = time.perf_counter() - t2
    subsurf = {
        "max_subsurf": args.max_subsurf,
        "decimate_over": args.decimate_over,
        "materials": args.materials,
        "modifier_types": dict(modifier_types),
        "subsurf_levels_before": {str(k): v for k, v in levels_before.items()},
        "subsurf_modifiers_capped": capped,
        "decimated_objects": len(decimated),
        "decimations": decimated,
    }

    # ---- export glTF from the same resident process (bpy still holds it) --
    t3 = time.perf_counter()
    kwargs = {
        "filepath": str(out / "source.glb"),
        "export_format": "GLB",
        "export_apply": True,            # evaluated meshes (modifiers applied)
        "export_yup": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_colors": False,
        "export_cameras": False,
        "export_lights": False,
        "export_animations": False,
        "export_skins": False,
        "export_extras": False,
        "export_draco_mesh_compression_enabled": False,  # raw source; our compiler compresses
        "export_materials": ("PLACEHOLDER" if args.materials == "placeholder"
                             else "EXPORT"),
    }
    # option names move between Blender releases; keep only what this build knows
    valid = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    dropped = sorted(set(kwargs) - valid)
    if dropped:
        print(f"[export] dropping kwargs unknown to this bpy: {dropped}")
    bpy.ops.export_scene.gltf(**{k: v for k, v in kwargs.items() if k in valid})
    timings["export_gltf"] = time.perf_counter() - t3

    # ---- stats for the measurements doc ------------------------------------
    n_objects = len(bpy.data.objects)
    n_meshes = len(bpy.data.meshes)
    n_materials = len(bpy.data.materials)
    tris = 0
    for m in bpy.data.meshes:
        for p in m.polygons:
            tris += len(p.vertices) - 2

    stats = {
        "generator": args.from_blend and f"from-blend:{args.from_blend.name}"
                    or args.generator,
        "seed": args.seed,
        "objects": n_objects,
        "meshes": n_meshes,
        "materials": n_materials,
        "triangles_base": tris,
        "triangles_approx": tris,
        "subsurf": subsurf,
        "source_glb_bytes": (out / "source.glb").stat().st_size
                            if (out / "source.glb").exists() else 0,
        "scene_blend_bytes": (out / "scene.blend").stat().st_size
                             if (out / "scene.blend").exists() else 0,
        "timings_sec": {k: round(v, 3) for k, v in timings.items()},
        "python": sys.version.split()[0],
    }
    (out / "export_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))
    sys.stdout.flush()
    sys.stderr.flush()
    # This box's bpy hangs (and once segfaulted) during interpreter
    # teardown after a long export/render — after every file is written
    # (render_prop_views.py found the same fact the same day). The work is
    # done; skip the teardown, or the night's bound waits on a corpse.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
