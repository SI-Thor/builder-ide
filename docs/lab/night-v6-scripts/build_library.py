#!/usr/bin/env python3
"""Build the library's approved set: ten measured crates, one kind.

**Why ten.** The plausibility prior's score is a rank inside a group, and
a group of *n* members cannot score below 0.5/(n+1) — so the ghost gate
(0.05) needs a group of **ten** before a member of it can be called a
ghost at all. night-v4's fit had no approved set, so its largest group
held seven and the gate was inert; its letter asked whether the library
may approve ten objects of one kind, and Casey approved it tonight
(2026-11-01). This script is the approval made real: **ten crate meshes,
reconstructed from one of the night's own crate pictures at ten seeds,
each repaired and measured exactly the way the night's executor measures
its own meshes** — same workflow template, same repair recipe, same
convex-hull occupancy — so the prior's approved group is measured in the
same units as the props it will judge.

The ten are written to ``approved-crate-library.json`` beside this script,
and ``run_night.py`` reads that file (it does not run this one): a
library is a thing that is built once and approved, not a per-night fit.

Run on the Thor, from the night-v5 worktree, in the propmaker-batch venv:

  cd ~/lm-wt/night-v5 && PYTHONPATH=. \\
      ~/lm-wt/propmaker-batch/.venv/bin/python \\
      docs/lab/night-v5-scripts/build_library.py

It takes about 25-40 minutes (ten TRELLIS mesh prompts, each with its
repair and measurement), holds one thor-admit lease for the whole build,
waits for the GPU-pool bar before every prompt (the same bar the night
uses — this build is exactly the stage that killed night-v4's run F), and
stops its own ComfyUI afterwards. The GLBs stay in the TRELLIS
environment's output directory and the JSON names them, so every member
is reproducible from its receipt.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("night_runner", HERE / "run_night.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
sys.path.insert(0, str(runner.REPO))

from core.genbatch.comfy import ComfyClient  # noqa: E402
from core.genbatch.glb import read_glb  # noqa: E402
from core.genbatch.mesh import measure_mesh  # noqa: E402
from core.genbatch.models import PropRequest  # noqa: E402
from core.genbatch.occupancy import occupied  # noqa: E402
from core.genbatch.plausibility import features_from_report  # noqa: E402
from core.genbatch.repair import repair_mesh  # noqa: E402
from core.genbatch.workflow import (  # noqa: E402
    build_trellis_workflow,
    load_template,
    nodes_of_type,
    trellis_seeds,
)

#: How many members the library approves of one kind. Ten is not a round
#: number: it is the smallest group whose floor (0.5/(n+1) = 0.0455) sits
#: below the ghost gate (0.05).
MEMBERS = 10

#: The base seeds the ten reconstructions derive from. Distinct from the
#: night's own request seeds (101-103 for the crate), so the library's
#: members and the night's variants never share a reconstruction by
#: accident.
LIBRARY_BASE_SEED = 9000

#: The picture the ten are reconstructed from: one of run F's own crate
#: pictures (night-v4's ledger), already in ComfyUI's input directory.
PICTURE = "crate_s102_00004_.png"

#: Where the members' facts land. run_night.py reads this file.
LIBRARY_FILE = HERE / "approved-crate-library.json"


def build() -> int:
    requests = [PropRequest.model_validate(row) for row in json.loads(
        (HERE / "courtyard_requests.json").read_text())]
    crate = next(r for r in requests if r.id == "crate")
    if not (runner.TRELLIS_INPUT / PICTURE).exists():
        raise SystemExit(
            f"{runner.TRELLIS_INPUT / PICTURE} is not there; the picture "
            f"run F used is the one the library should be built from")

    heavy = runner.Heavy(None, enabled=True)
    client = ComfyClient(runner.COMFY_URL, output_root=runner.TRELLIS_ROOT / "out")
    template = load_template(runner.TRELLIS_ROOT / "workflows" / "trellis2_512.api.json")
    comfy: dict = {}
    members: list[dict] = []
    started = time.monotonic()
    try:
        with heavy.hold("build the crate library: ten TRELLIS meshes"):
            comfy = runner.serve_comfy(heavy)
            if not comfy.get("started"):
                raise SystemExit("this build must own its ComfyUI, not share one")
            for index in range(MEMBERS):
                seed = LIBRARY_BASE_SEED + index
                bar = runner.wait_for_gpu_pool(
                    f"the library's mesh prompt {index + 1}/{MEMBERS}")
                workflow = build_trellis_workflow(
                    template,
                    image_name=PICTURE,
                    seeds=trellis_seeds(seed),
                    steps=crate.trellis_steps,
                    cfg=crate.trellis_cfg,
                    sampler=crate.trellis_sampler,
                    scheduler=crate.trellis_scheduler,
                    filename_prefix=f"genbatch/libcrate_s{seed}",
                    resolution=32 if crate.resolution <= 512 else 64,
                    weight_dtype=crate.weight_dtype,
                )
                class_types = {
                    node_id: str(node.get("class_type", ""))
                    for node_id, node in workflow.items()
                    if isinstance(node, dict)
                }
                prompt_started = time.monotonic()
                result = asyncio.run(client.run_prompt(
                    workflow,
                    client_id=f"library-crate-{seed}",
                    class_types=class_types,
                ))
                node_id = nodes_of_type(workflow, "SaveGLB")
                glb = result.output(node_id[0][0]) if node_id else None
                if glb is None:
                    raise SystemExit(f"seed {seed}: the mesh stage wrote no GLB")
                # the same pipeline the executor runs: read, repair,
                # measure, occupy — the features in the night's own units
                repair = repair_mesh(read_glb(glb).mesh, crate.repair)
                report = repair.report.after or measure_mesh(repair.mesh)
                if report.occupied_volume is None:
                    occ = occupied(repair.mesh, "convex")
                    report.occupied_volume = occ.volume
                    report.occupied_centre = occ.centre
                    report.occupied_method = occ.method
                features = features_from_report(report)
                members.append({
                    "name": f"crate_lib_s{seed}",
                    "kind": "crate",
                    "seed": seed,
                    "picture": PICTURE,
                    "glb": str(glb),
                    "features": asdict(features),
                    "watertight": report.watertight,
                    "triangles": report.triangles,
                    "fidelity": repair.report.fidelity,
                    "wall_s": round(time.monotonic() - prompt_started, 1),
                })
                runner.log(f"the library holds {len(members)}/{MEMBERS}: "
                           f"seed {seed}, {report.triangles:,} tris, "
                           f"watertight {report.watertight}")
    finally:
        runner.stop_comfy(comfy)

    document = {
        "kind": "crate",
        "member_count": len(members),
        "policy": "the library may approve ten objects of one kind "
                  "(Casey, 2026-11-01, answering night-v4's letter)",
        "built_by": {
            "script": "docs/lab/night-v5-scripts/build_library.py",
            "picture": PICTURE,
            "base_seed": LIBRARY_BASE_SEED,
            "template": "trellis2_512.api.json",
            "repair": (crate.repair.model_dump()
                       if hasattr(crate.repair, "model_dump")
                       else asdict(crate.repair)),
            "built_at": runner.now_utc(),
            "wall_minutes": round((time.monotonic() - started) / 60.0, 1),
            "prompt_seconds": [m["wall_s"] for m in members],
        },
        "members_detail": members,
    }
    LIBRARY_FILE.write_text(json.dumps(document, indent=2))
    runner.log(f"the library is approved: {len(members)} crates of one kind "
               f"in {LIBRARY_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
