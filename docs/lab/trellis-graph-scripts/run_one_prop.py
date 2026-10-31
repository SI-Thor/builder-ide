"""Run one prop through a (possibly probed) ComfyUI, and time it.

The graph-capture experiment needs the *real* generator in the *real*
pipeline — a picture, then a mesh, through ComfyUI's own workflows — and it
needs to be able to choose the workflow, because the fp8 arm runs the
TRELLIS.2 environment's own ``fp8_e4m3fn_fast`` template (which is what
selects ComfyUI's fused fp8 path).

So this driver is deliberately small and deliberately in the lab's scripts
directory rather than in ``core.genbatch``: it is experiment scaffolding,
not a product path.  It reuses the seat's own workflow builders and client,
so the workflows it sends are the same ones the night sends.

    python run_one_prop.py --comfy-url http://127.0.0.1:8189 \\
        --template trellis2_512.api.json --out artifacts/trg/run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.genbatch.comfy import ComfyClient  # noqa: E402
from core.genbatch.workflow import (  # noqa: E402
    build_image_workflow,
    build_trellis_workflow,
    load_template,
    nodes_of_type,
    trellis_seeds,
)

DEFAULT_TRELLIS = Path.home() / "lm-wt" / "trellis"

PROMPT = (
    "a weathered wooden crate with iron banding, studio product photo, "
    "single object, plain light grey background"
)
NEGATIVE = (
    "blurry, low quality, watermark, text, deformed, disfigured, "
    "multiple objects, cropped"
)


def _run(client: ComfyClient, workflow: dict, client_id: str):
    class_types = {
        node_id: str(node.get("class_type", ""))
        for node_id, node in workflow.items()
        if isinstance(node, dict)
    }
    return asyncio.run(
        client.run_prompt(workflow, client_id=client_id, class_types=class_types)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_one_prop.py")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--trellis-root", type=Path, default=DEFAULT_TRELLIS)
    parser.add_argument(
        "--template",
        default="trellis2_512.api.json",
        help="the TRELLIS.2 workflow template, read from the environment",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--prefix", default="trg")
    args = parser.parse_args(argv)

    workflows = args.trellis_root / "workflows"
    image_template = load_template(workflows / "text2image.api.json")
    trellis_template = load_template(workflows / args.template)

    client = ComfyClient(args.comfy_url, output_root=args.trellis_root / "out")
    report: dict = {
        "comfy_url": args.comfy_url,
        "template": args.template,
        "template_digest": trellis_template.digest,
        "seed": args.seed,
        "stages": {},
    }

    # -- the image stage --------------------------------------------------
    image_workflow = build_image_workflow(
        image_template,
        prompt=PROMPT,
        negative=NEGATIVE,
        seed=args.seed,
        size=1024,
        steps=30,
        cfg=7.0,
        sampler="dpmpp_2m",
        scheduler="karras",
        filename_prefix=f"{args.prefix}/image_s{args.seed}",
    )
    t0 = time.monotonic()
    image_result = _run(client, image_workflow, f"{args.prefix}-image")
    report["stages"]["image"] = {
        "wall_seconds": image_result.wall_seconds,
        "gpu_seconds": image_result.split.gpu_seconds,
        "cpu_seconds": image_result.split.cpu_seconds,
        "error": image_result.error,
    }
    if not image_result.ok:
        print(f"the image stage failed: {image_result.error}", file=sys.stderr)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))
        return 1

    save_node = nodes_of_type(image_workflow, "SaveImage")[0][0]
    picture = image_result.output(save_node)
    if picture is None:
        print("the image stage wrote no picture", file=sys.stderr)
        return 1
    image_name = asyncio.run(client.upload_image(picture.read_bytes(), picture.name))

    # -- the mesh stage ---------------------------------------------------
    seeds = trellis_seeds(args.seed)
    trellis_workflow = build_trellis_workflow(
        trellis_template,
        image_name=image_name,
        seeds=seeds,
        steps=(12, 20, 12),
        cfg=7.5,
        sampler="euler",
        scheduler="normal",
        filename_prefix=f"{args.prefix}/prop_s{args.seed}",
        resolution=32,
    )
    t0 = time.monotonic()
    mesh_result = _run(client, trellis_workflow, f"{args.prefix}-mesh")
    report["stages"]["mesh"] = {
        "wall_seconds": mesh_result.wall_seconds,
        "gpu_seconds": mesh_result.split.gpu_seconds,
        "cpu_seconds": mesh_result.split.cpu_seconds,
        "error": mesh_result.error,
        "nodes": [
            {
                "node": node.node,
                "class_type": node.class_type,
                "lane": node.lane,
                "seconds": node.seconds,
            }
            for node in mesh_result.split.nodes
        ],
    }
    glb_node = nodes_of_type(trellis_workflow, "SaveGLB")[0][0]
    glb = mesh_result.output(glb_node)
    report["stages"]["mesh"]["glb"] = str(glb) if glb else None

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if mesh_result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
