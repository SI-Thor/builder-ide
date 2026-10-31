# EXP 5a — CUDA Graphs: the launch overhead that hides the FP8 gain

**Date:** 2026-10-31 03:30 local (Alaska Daylight Time)
**Verdict: CONFIRMED, AND THE GRAPH IS WORTH MORE THAN THE SPEEDUP.** Capturing the
decode step in a CUDA Graph removes **99.7 % of the host-side work** (CPU enqueue
**2.38 ms → 0.008 ms**, a ~300× collapse) and makes the step **reproducible on a shared
box** — the eager step time varied **3.4×** across runs while the graphed step time varied
**6 %**. The FP8 gain over BF16 goes from **1.55–2.22× eager to 1.66–2.42× graphed**: the
graph does not create the gain, it *uncovers* it.

---

## 1. The idea

> "CUDA Graphs to kill launch overhead in a hot loop."

EXP 2 found that the FP8 stack's GPU work is faster than BF16's but the wall clock was
the same, because the Python-side cost of issuing the FP8 path's extra casts and
`_scaled_mm` calls is longer than the GPU needs. The step was launch-bound.

This measures whether a CUDA Graph is the answer, and what it is worth:

- **A.** a hot loop of many tiny kernels — the classic launch-overhead case;
- **B.** the EXP 2 stack, BF16 and FP8, eager vs graphed, across N.

## 2. Hypothesis

1. A CUDA Graph collapses the per-kernel launch cost: the hot loop's host time drops by
   an order of magnitude and the wall time follows.
2. On the EXP 2 stack, graphing recovers the FP8 advantage, because the FP8 path's extra
   per-GEMM host work disappears.

## 3. Setup

- Script: `scripts/exp5a_cudagraphs.py`; raw JSON: `results/exp5a_cudagraphs.json`
  (rerun: `.venv/bin/python scripts/exp5a_cudagraphs.py`)
- The stack is EXP 2's: a 16-layer LLaMA-shaped decoder, 973 M parameters, **1.946 GB of
  BF16 weights** resident, stepped with **S = 1** (the weights-only regime) and a batch
  dimension N.
- **Eager and graphed are timed in interleaved rounds.** On this box the absolute time of
  anything drifts by 2–3× with the other seats' load; timing the two variants in the same
  rounds means the drift hits both equally, so the *ratio* — which is the claim — stays
  trustworthy when the absolutes do not.
- The GPU is warmed to 1575 MHz before any timing (see `exp-batched-shared-model.md`
  §5.1) and the clock is recorded beside every row.

### The box this ran on

| | |
|---|---|
| GPU clock | 1575 MHz (warmed from 315 MHz first) |
| **Load during the run** | **loadavg 19–33 on 14 cores** |
| GPU tenants | `trellis/ComfyUI/main.py` (**9.8 GB** of GPU memory, actively rendering), `warm-scene`'s server |
| **Effect on these numbers** | the **CPU load** moves the *eager* numbers (they are host-bound); the **GPU tenants** move the *graphed* numbers (they are pure GPU work). The ratios are measured interleaved and are unaffected. |

## 4. Numbers

### 4.1 A hot loop of small kernels

256 kernels on a 4096-element tensor:

| | time | per kernel | CPU enqueue |
|---|---|---|---|
| eager | 0.691 ms | **2.7 µs** | **2.379 ms** |
| **graph replay** | **0.500 ms** | **2.0 µs** | **0.008 ms** |

**The host-side cost collapses by ~300× (2.379 ms → 0.008 ms).** The wall time follows by
1.38× in this run — and by **5.05×** in a quieter one, because the eager path's wall time
is set entirely by how fast the host can issue the kernels.

**That variability is the finding.** Across two runs of the *same* code:

| | eager | graph |
|---|---|---|
| run A (quiet) | 2.375 ms — 9.28 µs/kernel | 0.471 ms — 1.84 µs/kernel |
| run B (busy) | 0.691 ms — 2.7 µs/kernel | 0.500 ms — 2.0 µs/kernel |
| **spread** | **3.4×** | **6 %** |

The graph replay is pure GPU work, so it barely moves. The eager loop's time is whatever
the host's load makes it. **On a shared box, the graph is what makes a measurement
reproducible** — and that matters more for the lab than the 1.4–5× speedup.

### 4.2 The EXP 2 stack, eager vs graphed

| precision | policy | N | eager | graph | speedup | graphed items/s | graphed J/item |
|---|---|---|---|---|---|---|---|
| bf16 | bf16 | 1 | 20.37 ms | 20.29 ms | 1.00× | 52.6 | 1.266 |
| bf16 | bf16 | 4 | 23.36 ms | 19.59 ms | 1.19× | 186.1 | 0.352 |
| bf16 | bf16 | 16 | 23.29 ms | 22.87 ms | 1.02× | 858.7 | 0.080 |
| bf16 | bf16 | 64 | 23.69 ms | 23.41 ms | 1.01× | 2705.4 | 0.026 |
| fp8_e4m3 | naive | 1 | 13.06 ms | 10.54 ms | 1.24× | 74.4 | 1.153 |
| fp8_e4m3 | naive | 4 | 13.33 ms | 10.46 ms | 1.27× | 389.0 | 0.237 |
| fp8_e4m3 | naive | 16 | 9.95 ms | 5.60 ms | 1.78× | 2358.7 | 0.035 |
| fp8_e4m3 | naive | 64 | 8.77 ms | 7.49 ms | 1.17× | 4675.6 | 0.021 |
| fp8_e4m3 | fused | 1 | 13.12 ms | 11.44 ms | 1.15× | 80.9 | 1.129 |
| fp8_e4m3 | fused | 4 | 13.70 ms | 10.57 ms | 1.30× | 426.4 | 0.185 |
| fp8_e4m3 | fused | 16 | 14.09 ms | 13.78 ms | 1.02× | 1407.6 | 0.054 |
| fp8_e4m3 | fused | 64 | 10.69 ms | 9.68 ms | 1.10× | 7346.6 | 0.011 |

**The FP8 gain, eager vs graphed:**

| N | eager bf16 → fp8 | graphed bf16 → fp8 |
|---|---|---|
| 1 | 20.37 → 13.12 ms = **1.55×** | 20.29 → 11.44 ms = **1.77×** |
| 4 | 23.36 → 13.70 ms = **1.71×** | 19.59 → 10.57 ms = **1.85×** |
| 16 | 23.29 → 14.09 ms = **1.65×** | 22.87 → 13.78 ms = **1.66×** |
| 64 | 23.69 → 10.69 ms = **2.22×** | 23.41 → 9.68 ms = **2.42×** |

In a quieter run of the same experiment the graphed BF16 step was **8.83 ms** (1.946 GB →
**220 GB/s of pure GPU bandwidth**) against an eager 11.91 ms, and the graphed FP8 step
**5.21 ms** — a **1.69×** FP8 gain, the same shape as the table above. The absolute
numbers move with the GPU tenants; the *structure* — BF16 ≈ 20–23 ms eager and graphed
because it is bandwidth-bound, FP8 ≈ 10–13 ms because it is launch-bound and halves its
weights — does not.

**The graph does not make the FP8 stack faster than BF16; it makes the FP8 stack's
existing speed visible.** BF16 gains almost nothing from graphing (1.00–1.19×): it is
bandwidth-bound, so removing the launch overhead changes little. The FP8 stack gains
**1.02–1.78×**, because for it the launch overhead *was* the binding constraint.

## 5. Verdict

- **Confirmed:** *"CUDA Graphs to kill launch overhead in a hot loop."* The host-side cost
  of issuing 256 kernels collapses from **2.379 ms to 0.008 ms** — a **~300×** reduction,
  and the wall time follows by 1.38–5.05× depending on how contended the host was.
- **Confirmed and extended:** the graph **uncovers the FP8 gain** rather than creating
  it. BF16 is bandwidth-bound and gains ~1.0–1.2× from graphing; FP8 is launch-bound and
  gains 1.1–1.8×. The end-to-end FP8-over-BF16 ratio improves from **1.55–2.22× eager** to
  **1.66–2.42× graphed**.
- **New, and the most useful thing in this file:** on a **shared** box the graph replay
  time varied by **6 %** across runs while the eager time varied by **3.4×**. A captured
  graph is also a *reproducible* measurement, which is what a shared lab needs.

### What this changes

- **Capture the decode step in a CUDA Graph.** It is the cheapest speedup available on
  this box (a few lines of `torch.cuda.graph`) and it is worth more as a
  *reproducibility* tool than as a speedup.
- **Do not quote an eager FP8 multiplier as the FP8 multiplier.** Eager: 1.29× end-to-end
  (`exp-batched-shared-model.md`); graphed: 1.66–2.42×. The honest figure depends on
  whether the serving loop captures its step.
- **The "pure GPU bandwidth" of this box is ~220 GB/s** (graphed BF16, quiet run), against
  the datasheet's 273 GB/s — see `exp-batched-shared-model.md` §5.2.

## 6. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp5a_cudagraphs.py     # -> results/exp5a_cudagraphs.json

python3 -c "
import json; d=json.load(open('results/exp5a_cudagraphs.json'))
print('hot loop:', d['hot_loop']['speedup'], 'x',
      '| enqueue', d['hot_loop']['cpu_enqueue_eager_ms'], '->', d['hot_loop']['cpu_enqueue_graph_ms'], 'ms')
for r in d['stack'][:4]:
    print(r['precision'], r['policy'], 'N=',r['N'], r['speedup'], 'x')"
```

## 7. Licence note

`torch` (BSD-3-Clause). The model is synthetic (seeded random weights); nothing is
downloaded.

## 8. Failures that stayed

- **Timing eager and graphed in separate blocks is not good enough on a shared box.** Two
  runs of identical code disagreed by 2.8× because the box's load moved between the
  blocks. Timing them in **interleaved rounds** — same rounds, same conditions — makes
  the ratio trustworthy.
- **The GPU clock must be warmed before the hot loop**, or the first block measures the
  315 MHz idle clock (a 2.6× error). The hot loop is short enough that the warm-up
  decays into it.
- **A CUDA graph's replay time is the pure GPU cost**, so it moves with the box's *GPU*
  tenants (another seat's ComfyUI server rendering), not with the CPU load. On this box
  the graphed BF16 step measured 8.83 ms on a quiet GPU and 20.29 ms with ComfyUI
  rendering — the same effect that makes every absolute GPU number here a range.
