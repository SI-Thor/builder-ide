#!/usr/bin/env python3
"""Per-kernel profile of the forward pass.

The stub-based attribution says "the rope is worth 434 ms", but it does
not say which kernel that is. This uses the PyTorch profiler on one real
batch of the workload and prints the kernels by their CUDA time, so the
optimisation is aimed at the right ones.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch  # noqa: E402
from torch.profiler import ProfilerActivity, profile  # noqa: E402

from d1dec.gguf import GGUFFile  # noqa: E402
from d1dec.model import D1Model  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", default="/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf")
    ap.add_argument("--seqs", type=int, default=64)
    ap.add_argument("--tokens", type=int, default=219)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    gguf = GGUFFile(args.gguf)
    model = D1Model(gguf=gguf)
    gguf.release()
    torch.cuda.synchronize()

    seqs = [list(range(1, args.tokens + 1)) for _ in range(args.seqs)]
    for _ in range(2):
        model.forward_last(seqs)
    torch.cuda.synchronize()

    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        for _ in range(3):
            model.forward_last(seqs)
        torch.cuda.synchronize()

    # the CUDA time of every kernel, grouped by its name
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for evt in prof.key_averages():
        if evt.device_type.name != "CUDA" and evt.self_device_time_total <= 0:
            continue
        t = evt.self_device_time_total
        if t <= 0:
            continue
        totals[evt.key] += t
        counts[evt.key] += 1

    total = sum(totals.values())
    print(f"\n=== CUDA time per kernel, 3 forwards of {args.seqs}x{args.tokens} ===")
    print(f"total {total / 3000:.0f} ms per forward\n")
    rows = sorted(totals.items(), key=lambda kv: -kv[1])
    for name, t in rows[:28]:
        if t / 3000 < 1.0:
            continue
        print(f"  {t / 3000:8.1f} ms  {100 * t / total:5.1f}%  n={counts[name]:5d}  {name[:70]}")

    # a grouped view: the interesting families
    families = {
        "gemm (cublas)": ("gemm", "cutlass", "sm90", "sm100", "ampere", "tensorop"),
        "elementwise": ("elementwise", "vectorized_elementwise", "copy", "CatArrayBatched", "fill"),
        "rope-ish (mul/add)": ("mul", "add", "sub", "neg"),
        "conv": ("conv", "implicit", "depthwise"),
        "attention": ("flash", "attention", "fmha", "scaled_dot"),
        "reduce/norm": ("reduce", "rms", "norm", "sum"),
        "index/gather": ("index", "gather", "embedding"),
    }
    print("\n=== the families ===")
    for fam, keys in families.items():
        s = sum(t for k, t in totals.items() if any(x in k.lower() for x in keys))
        print(f"  {fam:22s} {s / 3000:8.1f} ms  {100 * s / total:5.1f}%")

    out = {
        "forward_ms": total / 3000,
        "kernels_ms": {k: v / 3000 for k, v in rows},
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
