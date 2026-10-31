#!/usr/bin/env python3
"""EXP 5a -- CUDA Graphs: the launch overhead that hides the FP8 gain.

EXP 2 found this: the FP8 stack's *GPU* work is ~1.94x faster than BF16's
(profiler: 6.62 ms vs 12.84 ms of CUDA busy time per step) yet the wall clock
was the same, because the Python-side cost of issuing the FP8 path's extra
casts and _scaled_mm calls is ~10.2 ms per step -- more than the GPU needs.
The step was launch-bound, not compute-bound.

Kimi's note says "CUDA Graphs to kill launch overhead in a hot loop". This
measures whether that is true here, and what it is worth:

  A. a hot loop of many tiny kernels -- eager vs a captured CUDA Graph
  B. the EXP 2 stack, BF16 and FP8, eager vs graphed, across N
"""

from __future__ import annotations

import json
import os
import sys
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp2_batched as E  # noqa: E402
from boxstate import (PowerMeter, format_box_state, box_state,  # noqa: E402
                      gpu_clock_mhz, warm_gpu)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")


def bench(fn, warmup: int = 5, reps: int = 20) -> dict:
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    ts = []
    for _ in range(reps):
        s, e = torch.cuda.Event(True), torch.cuda.Event(True)
        s.record()
        fn()
        e.record()
        torch.cuda.synchronize()
        ts.append(s.elapsed_time(e))
    ts.sort()
    return {"median_ms": ts[len(ts) // 2], "min_ms": ts[0], "max_ms": ts[-1]}


def bench_pair(fn_a, fn_b, warmup: int = 5, reps: int = 12) -> tuple[dict, dict]:
    """Time two functions in *interleaved rounds*.

    On a shared box the absolute time of anything drifts by 2-3x with the other
    seats' load. Timing the two variants in the same rounds means the drift
    affects both equally, so the *ratio* -- which is the claim -- stays
    trustworthy even when the absolutes do not.
    """
    for _ in range(warmup):
        fn_a(); fn_b()
    torch.cuda.synchronize()
    ta, tb = [], []
    for _ in range(reps):
        for fn, acc in ((fn_a, ta), (fn_b, tb)):
            s, e = torch.cuda.Event(True), torch.cuda.Event(True)
            s.record()
            fn()
            e.record()
            torch.cuda.synchronize()
            acc.append(s.elapsed_time(e))
    ta.sort(); tb.sort()
    return ({"median_ms": ta[len(ta) // 2], "min_ms": ta[0], "max_ms": ta[-1]},
            {"median_ms": tb[len(tb) // 2], "min_ms": tb[0], "max_ms": tb[-1]})


# ------------------------------------------------------------------ part A

def hot_loop(n_kernels: int = 256, size: int = 4096) -> dict:
    """A hot loop of many small kernels: the classic launch-overhead case."""
    x = torch.randn(size, device="cuda")
    w = torch.randn(size, device="cuda")

    def eager():
        y = x
        for _ in range(n_kernels):
            y = torch.add(y, w).relu()
        return y

    # capture
    s = torch.cuda.Stream()
    s.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(s):
        for _ in range(3):
            eager()
    torch.cuda.current_stream().wait_stream(s)
    torch.cuda.synchronize()

    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        out = eager()
    torch.cuda.synchronize()

    t_eager, t_graph = bench_pair(eager, g.replay)

    # the pure CPU-side cost of issuing the work
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(10):
        eager()
    enq_eager = (time.perf_counter() - t0) / 10 * 1000
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(10):
        g.replay()
    enq_graph = (time.perf_counter() - t0) / 10 * 1000
    torch.cuda.synchronize()

    return {
        "n_kernels": n_kernels,
        "tensor_size": size,
        "eager": t_eager,
        "graph": t_graph,
        "speedup": t_eager["median_ms"] / t_graph["median_ms"],
        "cpu_enqueue_eager_ms": enq_eager,
        "cpu_enqueue_graph_ms": enq_graph,
        "per_kernel_eager_us": t_eager["median_ms"] * 1000 / n_kernels,
        "per_kernel_graph_us": t_graph["median_ms"] * 1000 / n_kernels,
    }


# ------------------------------------------------------------------ part B

def graphed_stack(stack, N: int, S: int, policy: str) -> dict:
    """Capture one decode step as a CUDA Graph and replay it."""
    cfg = stack.cfg
    kv_cache = torch.zeros(cfg.n_layers, 2, N, cfg.n_kv_heads, S, cfg.head_dim,
                           device="cuda", dtype=torch.bfloat16)
    x = torch.randn(N, cfg.d_model, device="cuda", dtype=torch.bfloat16)

    def step():
        return E.forward(stack, x, kv_cache, pos=S - 1, policy=policy)

    s = torch.cuda.Stream()
    s.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(s):
        for _ in range(3):
            step()
    torch.cuda.current_stream().wait_stream(s)
    torch.cuda.synchronize()

    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        out = step()
    torch.cuda.synchronize()
    # interleaved: the box's load drifts, and the ratio is the claim
    t_eager, t_graph = bench_pair(step, g.replay)

    # joules for the graphed loop
    with PowerMeter() as pm:
        torch.cuda.synchronize()
        t0 = pm.mark()
        reps = 0
        deadline = time.perf_counter() + 1.0
        while time.perf_counter() < deadline:
            g.replay()
            reps += 1
        torch.cuda.synchronize()
        t1 = pm.mark()
        j_total = pm.joules_between("VIN_total", t0, t1)
        j_gpu = pm.joules_between("VDD_GPU", t0, t1)
        w_total = pm.watts_between("VIN_total", t0, t1)

    return {
        "N": N, "S": S,
        "precision": "fp8_e4m3" if stack.is_fp8 else "bf16",
        "policy": policy,
        "eager": t_eager,
        "graph": t_graph,
        "speedup": t_eager["median_ms"] / t_graph["median_ms"],
        "joules_per_item_total": j_total / (reps * N),
        "joules_per_item_gpu": j_gpu / (reps * N),
        "mean_w_total": w_total,
        "items_per_s": reps * N / (t1 - t0),
        "gpu_clock_mhz": gpu_clock_mhz(),
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    torch.backends.cuda.matmul.allow_tf32 = False
    results = {}

    print("=" * 78)
    print("EXP 5a -- CUDA Graphs: launch overhead")
    print("=" * 78)
    st = box_state()
    print(format_box_state(st))
    # the GPU idles at 315 MHz and ramps to 1575 MHz over ~1.4 s of sustained
    # load; without this, the first timed block measures the governor.
    w = warm_gpu(seconds=2.5)
    print(f"  gpu clock warmed: {w['clock_before_mhz']:.0f} -> {w['clock_after_mhz']:.0f} MHz")
    results["gpu_warmup"] = w

    print("\n--- A. a hot loop of small kernels ---")
    hl = hot_loop()
    results["hot_loop"] = hl
    print(f"    {hl['n_kernels']} kernels on a {hl['tensor_size']}-element tensor")
    print(f"    eager : {hl['eager']['median_ms']:8.3f} ms  ({hl['per_kernel_eager_us']:6.1f} us/kernel)")
    print(f"    graph : {hl['graph']['median_ms']:8.3f} ms  ({hl['per_kernel_graph_us']:6.1f} us/kernel)")
    print(f"    speedup {hl['speedup']:.2f}x   | CPU enqueue "
          f"{hl['cpu_enqueue_eager_ms']:.3f} ms -> {hl['cpu_enqueue_graph_ms']:.3f} ms")

    print("\n--- B. the EXP 2 stack, eager vs graphed ---")
    cfg = E.Cfg()
    stacks = {"bf16": E.Stack(cfg, torch.bfloat16), "fp8_e4m3": E.Stack(cfg, E.FP8)}
    rows = []
    for prec, policy in (("bf16", "bf16"), ("fp8_e4m3", "naive"), ("fp8_e4m3", "fused")):
        for N in (1, 4, 16, 64):
            try:
                r = graphed_stack(stacks[prec], N, 1, policy)
            except Exception as e:
                print(f"    {prec} N={N}: FAILED {type(e).__name__}: {str(e)[:120]}")
                continue
            rows.append(r)
            print(f"    {prec:9s} [{policy:6s}] N={N:3d}  clk {r['gpu_clock_mhz']:.0f}  eager {r['eager']['median_ms']:7.2f} ms  "
                  f"graph {r['graph']['median_ms']:7.2f} ms  -> {r['speedup']:5.2f}x  "
                  f"| graphed {r['items_per_s']:9.1f} items/s  "
                  f"{r['joules_per_item_total']:6.3f} J/item  {r['mean_w_total']:5.1f} W")
    results["stack"] = rows

    # the headline: does the FP8 gain become visible once the launches are gone?
    print("\n--- the FP8 gain, eager vs graphed (S=1) ---")
    for N in (1, 4, 16, 64):
        g16 = [r for r in rows if r["precision"] == "bf16" and r["N"] == N]
        g8 = [r for r in rows if r["precision"] == "fp8_e4m3" and r["policy"] == "fused"
              and r["N"] == N]
        if not (g16 and g8):
            continue
        b, f = g16[0], g8[0]
        print(f"    N={N:3d}: eager bf16 {b['eager']['median_ms']:6.2f} ms vs fp8 "
              f"{f['eager']['median_ms']:6.2f} ms -> {b['eager']['median_ms']/f['eager']['median_ms']:.2f}x"
              f" | graphed bf16 {b['graph']['median_ms']:6.2f} ms vs fp8 "
              f"{f['graph']['median_ms']:6.2f} ms -> {b['graph']['median_ms']/f['graph']['median_ms']:.2f}x")

    with open(os.path.join(OUT, "exp5a_cudagraphs.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nwrote {OUT}/exp5a_cudagraphs.json")


if __name__ == "__main__":
    with torch.no_grad():
        main()
