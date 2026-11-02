"""Run Vibe3DScene's execute_code transaction path against headless Blender.

Runs *inside* Blender:

    /usr/bin/blender --background --factory-startup --python run_vibe_transactions.py -- \
        --addon <dir containing blender_mcpv_addon> --out records.json

What it exercises, per the addon (blender-mcp-vision at the submodule commit
Vibe3DScene pins, eda20a63): `execute_code(code, safe_mode, rollback_on_guard_fail,
validate_scene)` from `blender_mcpv_addon/server_scene_tools_mixin.py` —

  - safe_mode takes a .blend snapshot of the scene before the code runs
  - validate_scene builds a scene-guard snapshot before and after and reports
    violations (coord outliers, dimension outliers, NaNs, scene-bbox growth,
    object-count delta)
  - a guard violation with rollback_on_guard_fail=true reloads the snapshot
  - an exception inside the code also reloads the snapshot
  - raw object deletion in execute_code is refused before anything runs

The script needs three things from the server side, which the TCP server normally
gets from its environment: SESSION_ID, SESSION_BLEND_PATH, SESSION_SNAPSHOT_DIR and
SESSION_PERSISTENCE_ENABLED=1. It sets them before constructing the server object.
"""
import argparse
import json
import os
import sys
import time
import traceback

import bpy  # noqa: E402  (Blender injects this)


def scene_state():
    out = {}
    for obj in bpy.context.scene.objects:
        out[obj.name] = {
            "location": [round(float(v), 4) for v in obj.location],
            "dimensions": [round(float(v), 4) for v in obj.dimensions],
        }
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--addon", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    args = ap.parse_args(argv)

    os.makedirs(args.workdir, exist_ok=True)
    snap_dir = os.path.join(args.workdir, "snapshots")
    os.environ.setdefault("SESSION_ID", "ingame-phase2")
    os.environ.setdefault("SESSION_BLEND_PATH", os.path.join(args.workdir, "session.blend"))
    os.environ.setdefault("SESSION_SNAPSHOT_DIR", snap_dir)
    os.environ.setdefault("SESSION_STORAGE_DIR", args.workdir)
    os.environ.setdefault("SESSION_PERSISTENCE_ENABLED", "1")

    sys.path.insert(0, args.addon)
    from blender_mcpv_addon.server import BlenderMCPVisionServer

    srv = BlenderMCPVisionServer()
    records = {
        "blender": bpy.app.version_string,
        "argv": argv,
        "persistence_enabled": bool(srv.persistence_enabled),
        "edits": [],
    }

    def call(label, code, **options):
        entry = {
            "label": label,
            "code": code,
            "options": options,
            "state_before": scene_state(),
        }
        t0 = time.time()
        try:
            result = srv.execute_code(code, **options)
            entry["outcome"] = "ok"
            entry["transaction"] = result
        except Exception as exc:  # the tool's error path: message carries the
            entry["outcome"] = "error"  # rollback text
            entry["error"] = str(exc)
        entry["seconds"] = round(time.time() - t0, 3)
        entry["state_after"] = scene_state()
        entry["state_restored"] = entry["state_before"] == entry["state_after"]
        records["edits"].append(entry)
        print(label, "->", entry["outcome"], "restored:", entry["state_restored"])

    defaults = dict(safe_mode=True, rollback_on_guard_fail=True, validate_scene=True)

    # Edit 1: a clean edit. Must commit.
    call("clean-edit",
         "import bpy\n"
         "bpy.ops.mesh.primitive_cube_add(size=1, location=(1.5, 0.0, 0.5))\n"
         "bpy.context.active_object.name = 'crate'\n"
         "print('crate placed')\n",
         **defaults)

    # Edit 2: must roll back - the guard flags a coord outlier (|coord| > 5000).
    call("guard-violation-rollback",
         "import bpy\n"
         "bpy.data.objects['crate'].location.x = 9999.0\n"
         "print('crate teleported')\n",
         **defaults)

    # Edit 3: must roll back - the code raises after mutating the scene.
    call("exec-error-rollback",
         "import bpy\n"
         "bpy.data.objects['crate'].location.x = 42.0\n"
         "raise RuntimeError('mid-edit failure')\n",
         **defaults)

    # Edit 4: the raw-delete guard, refused before any execution.
    call("raw-delete-refused",
         "import bpy\n"
         "bpy.data.objects.remove(bpy.data.objects['crate'])\n",
         **defaults)

    # Edit 5: same violation as edit 2 but with rollback switched off -
    # records the failure without restoring the scene (the contrast case).
    call("guard-violation-no-rollback",
         "import bpy\n"
         "bpy.data.objects['crate'].location.x = 9999.0\n",
         safe_mode=True, rollback_on_guard_fail=False, validate_scene=True)

    # Edit 6: safe_mode off - no snapshot, no guard, code side effects stand even
    # though the same coordinates would have failed the guard.
    call("safe-mode-off",
         "import bpy\n"
         "bpy.data.objects['crate'].location.x = 8888.0\n",
         safe_mode=False, rollback_on_guard_fail=True, validate_scene=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(records, fh, indent=1)
    print("wrote", args.out)


main()