"""Summarise the fp8 arms' artifacts into the numbers the lab note quotes.

Reads one round's run JSONs (the wall times, the lanes) and probe JSONs
(the per-step GPU spans, the memory, the fp8 counters) from the
experiment's artifacts directory and prints, per arm:

* the whole prop's wall time, per seed, image + mesh;
* the per-step GPU span, per stage, split by the step's input shape —
  the picture stage's SDXL steps and the mesh stage's structure /
  shape / texture steps have different shapes, so the shape is what
  tells them apart;
* the peak memory the probe saw (torch's allocator high-water marks and
  the process's RSS, where the weights live);
* the fused path's counters: calls, taken, declined — the number that
  says whether the fp8 arm actually ran fp8.

Everything is printed beside the arm's fp8 counters on purpose: a
per-step time from an arm whose fused path declined is a bf16 number
wearing an fp8 label.

    python summarize_arms.py --artifacts artifacts/fp8-real --suffix -r1

With ``--json`` the same numbers come out as a JSON document, so the lab
note's tables can be regenerated rather than retyped.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

#: The arms, in the order they are compared.
ARMS = ("bf16", "fp8-declined", "fp8-fixed")

#: The input shapes that name the stages, as (channels, height, width) for
#: the picture UNet and the mesh stage's tokens. The SDXL latent is 128×128
#: (1024² / 8); the mesh stage's dense structure tokens are 32³ = 32768 long.
#: Rather than hardcode a table, steps are grouped by their exact input
#: shape string and the groups are named by the seed's known step counts.
def _stage_buckets(records: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Group the steps by input shape and name the big groups.

    A seed runs 74 steps: 30 SDXL (the picture) and 44 TRELLIS.2
    (structure 12, shape 20, texture 12). The shape string separates the
    models; within the mesh stage the three samplers' shapes differ in
    the token count and the channel width, and the order of the records
    separates the samplers when two of them share a shape.
    """
    buckets: dict[str, list[float]] = {}
    for record in records:
        shape = str(record.get("input_shape"))
        buckets.setdefault(shape, []).append(float(record["gpu_ms"]))
    return buckets


def _per_stage(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Median GPU span per stage, named by what the input shape says.

    A seed runs 74 steps. Thirty are the picture's SDXL UNet. The other
    44 are ``Trellis2``, and their shapes split them: the dense
    structure latent is ``[b, 32, 16, 16, 16]``, and the sparse stages
    (shape and texture samplers alike) are ``[b, 32, n_tokens, 1]``.
    The leading batch dimension is the CFG batching — the workflow's
    ``CFGOverride`` node drops guidance to 1.0 over the last third of
    the sigma range, so the same sampler runs batched for most steps
    and single for the rest. Groups are reported with their counts, not
    pretended into sampler names the shape cannot prove.
    """
    groups: dict[tuple[bool, bool, bool], list[float]] = {}
    for record in records:
        model = str(record.get("model", ""))
        shape = record.get("input_shape")
        trellis = "Trellis2" in model
        dense = isinstance(shape, list) and len(shape) == 5
        batched = isinstance(shape, list) and shape and shape[0] == 2
        key = (trellis, dense, batched)
        groups.setdefault(key, []).append(float(record["gpu_ms"]))

    names = {
        (False, False, True): "image",
        (False, False, False): "image",
        (True, True, True): "structure-batched",
        (True, True, False): "structure-single",
        (True, False, True): "sparse-batched",
        (True, False, False): "sparse-single",
    }
    out: dict[str, dict[str, float]] = {}
    for key, samples in groups.items():
        name = names.get(key, str(key))
        out[name] = {
            "steps": len(samples),
            "median_gpu_ms": statistics.median(samples),
        }
    return out


def summarize(artifacts: Path, suffix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        base = arm + suffix
        run_files = sorted(artifacts.glob(f"{base}-run-s*.json"))
        probe_file = artifacts / f"{base}-probe.json"
        fix_file = artifacts / f"{base}-fp8-real.json"
        arm_out: dict[str, Any] = {"run_files": [p.name for p in run_files]}

        walls: list[float] = []
        per_seed: dict[str, Any] = {}
        records: list[dict[str, Any]] = []
        for run_file in run_files:
            run = json.loads(run_file.read_text())
            seed = str(run.get("seed"))
            wall = (
                run["stages"]["image"]["wall_seconds"]
                + run["stages"]["mesh"]["wall_seconds"]
            )
            walls.append(wall)
            per_seed[seed] = {
                "wall_seconds": round(wall, 1),
                "image_wall_seconds": round(run["stages"]["image"]["wall_seconds"], 1),
                "mesh_wall_seconds": round(run["stages"]["mesh"]["wall_seconds"], 1),
                "mesh_gpu_seconds": round(run["stages"]["mesh"]["gpu_seconds"], 1),
                "weight_dtype": run.get("weight_dtype"),
            }
        arm_out["per_seed"] = per_seed
        if walls:
            arm_out["wall_seconds_median"] = round(statistics.median(walls), 1)

        if probe_file.exists():
            probe = json.loads(probe_file.read_text())
            records = probe.get("records", [])
            arm_out["stages"] = {
                name: {
                    "steps": bucket["steps"],
                    "median_gpu_ms": round(bucket["median_gpu_ms"], 1),
                }
                for name, bucket in _per_stage(records).items()
            }
            if records:
                last = records[-1].get("memory", {})
                arm_out["memory_mb"] = {
                    k: round(v, 0)
                    for k, v in last.items()
                    if isinstance(v, (int, float))
                }
            stats = probe.get("fp8_stats") or {}
            arm_out["fp8"] = {
                key: stats.get(key, {}).get("calls", 0)
                for key in ("fp8_linear", "fp8_linear_used", "fp8_linear_none")
            }
            arm_out["fp8"]["weight_dtype_seen"] = stats.get("weight_dtype")
        if fix_file.exists():
            arm_out["fix"] = json.loads(fix_file.read_text())
        out[arm] = arm_out
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="summarize_arms.py")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/fp8-real"))
    parser.add_argument("--suffix", default="-r1", help="the round suffix: -r1, -r2, ...")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    document = summarize(args.artifacts, args.suffix)
    if args.json:
        print(json.dumps(document, indent=2))
        return 0

    for arm, data in document.items():
        print(f"== {arm}{args.suffix}")
        if data.get("fp8") is not None:
            fp8 = data["fp8"]
            print(
                f"   fused path: {fp8['fp8_linear_used']}/{fp8['fp8_linear']} used,"
                f" {fp8['fp8_linear_none']} declined"
                f" (weights seen as {fp8['weight_dtype_seen']})"
            )
        for seed, row in (data.get("per_seed") or {}).items():
            print(
                f"   seed {seed}: wall {row['wall_seconds']}s"
                f" (image {row['image_wall_seconds']}, mesh {row['mesh_wall_seconds']},"
                f" mesh gpu {row['mesh_gpu_seconds']})"
            )
        for stage, bucket in (data.get("stages") or {}).items():
            print(
                f"   {stage:10s} {bucket['steps']:3d} steps,"
                f" median gpu {bucket['median_gpu_ms']} ms"
            )
        mem = data.get("memory_mb") or {}
        if mem:
            print(
                f"   peak: cuda allocated {mem.get('cuda_max_allocated_mb', 0) / 1000:.1f} GB,"
                f" reserved {mem.get('cuda_max_reserved_mb', 0) / 1000:.1f} GB,"
                f" rss {mem.get('rss_mb', 0) / 1000:.1f} GB"
            )
        fix = data.get("fix") or {}
        if fix:
            print(
                f"   fix: {fix.get('weights_cast')} weights cast"
                f" ({fix.get('elements_cast', 0) / 1e9:.2f} G elements,"
                f" {fix.get('cast_seconds', 0):.1f} s at load)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
