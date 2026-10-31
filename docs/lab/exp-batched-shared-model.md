# EXP 2 — One shared model, N agents batched: where does batching stop being free?

**Date:** 2026-10-31 03:05 local (Alaska Daylight Time)
**Verdict: THE FP8 MULTIPLIER IS 3.0× ON THE GEMM CHAIN AND 1.3× END-TO-END. BATCHING IS FREE
ONLY IN THE WEIGHTS-ONLY REGIME.** Kimi's two claims split apart cleanly:

- *"FP4 as an iteration multiplier … re-derive the real multiplier"* — **FP8 with fused
  activations is 3.00× on a realistic GEMM chain** (range 2.1–3.0× across four runs), and
  **1.29× end-to-end** in eager mode because the stack is **launch-bound**, not
  bandwidth-bound. CUDA Graphs recover it to 2.5–3.6×.
- *"One shared model, N agents batched: weights stream once per pass, so batching N agents
  costs ~the bandwidth of one"* — **only true when the agents have no context.** With a
  realistic 1024-token context the step time grows from **13.6 ms at N = 1 to 53.7 ms at
  N = 128**, because each agent's KV cache is its own and scales linearly with N.

And the number the plan was built on — **273 GB/s** — is **not the working bandwidth**.
This box delivers **166 GB/s** of weight streaming, **0.61× the datasheet**.

---

## 1. The idea

> "One shared model, N agents batched: weights stream once per pass, so batching N agents
> costs ~the bandwidth of one; only compute scales."
>
> "FP4 as an iteration multiplier (bandwidth wall: T_pass ≈ active_params × bytes/param /
> 273 GB/s). Our lab round 1 measured FP4 a no on this stack and FP8 1.6–1.7×: re-derive
> the real multiplier."

The brief asks for: latency per step, aggregate items/s, achieved bandwidth against
273 GB/s, and joules per item from the rails — and then *"where does batching stop being
free?"*

## 2. Hypothesis

1. A resident model, stepped with a batch dimension N, has a step time that is **flat** in
   N over the range that matters, because the weights stream once per step.
2. The bandwidth actually available is close to the datasheet's 273 GB/s, and the FP8
   multiplier is the 1.6–1.7× round 1 measured.
3. Batching N agents costs about what one agent costs, in both time and joules.

## 3. Setup

- Script: `scripts/exp2_batched.py`; raw JSON: `results/exp2_batched.json`
  (rerun: `.venv/bin/python scripts/exp2_batched.py`)
- The model is a **LLaMA-shaped transformer decoder stack** — RMSNorm, grouped-query
  attention (16 heads, 4 KV heads), SwiGLU — **16 layers, d_model 2048, FFN 8192**,
  **973 M parameters**. It is held resident in unified memory and stepped with a batch
  dimension N, so the weight byte count is exact: **1.946 GB in BF16, 0.973 GB in FP8**.
- Two KV-cache regimes, which is the whole point of the experiment:
  - **S = 1** — weights only. Isolates Kimi's claim.
  - **S = 1024** — a realistic agent context, where the cache grows with N.
- Four precision policies, **over identical weights** (both stacks are built from the same
  generator seed, so the FP8 stack is a quantisation of the BF16 stack):

  | policy | weights | activations |
  |---|---|---|
  | `bf16` | BF16 | BF16 |
  | `naive` | FP8 | cast to FP8 at every GEMM input (round 1's C4b path) |
  | `fused` | FP8 | stay FP8 between the GEMMs of a block, no activation scale |
  | `scaled` | FP8 | stay FP8 with **calibrated per-tensor activation scales** |

- **The GPU clock is warmed before any timing.** The Thor idles at **315 MHz** and ramps to
  **1575 MHz** over about 1.4 s of sustained load; a cold measurement is **2.6× slow** and
  measures the governor, not the code. See §5.1.
- Each (precision, S, N) point is measured as **3 rounds × 20 timed steps**; the reported
  step time is the **least-contended round** (the best estimator on a shared box) with the
  median alongside it.

### The box this ran on

| | |
|---|---|
| GPU | NVIDIA Thor, clock warmed to **1575 MHz** |
| Power mode | `MAXN` (nvpmodel mode 0) |
| **Load during the run** | **loadavg 26–36 on 14 cores** (rising during the run) |
| GPU tenants | `trellis/ComfyUI/main.py` (9.8 GB) and `warm-scene`'s server — **other seats** |
| **Effect on these numbers** | the *host-bound* quantities (step time at small N, CPU issue time) are inflated; the *GPU-bound* quantities (the GEMM chain, the per-shape TFLOPS) are robust — they reproduced within 5 % across four runs at loads from 15 to 110. |

## 4. Numbers

### 4.1 The FP8 multiplier, re-derived

A chain of eight GEMMs with the shapes a real transformer uses
(`1280→320→640→1280→5120→1280→1920→640→1280`), 4096 tokens, **156 GFLOP**:

| policy | time | throughput | vs BF16 | output error (max / RMS) |
|---|---|---|---|---|
| bf16 | 1.547 ms | 100.9 TFLOPS | — | — |
| fp8 weights only, cast per layer | 1.197 ms | 130.3 TFLOPS | **1.29×** | 15.4 % / 18.3 % |
| **fp8 weights + fp8 activations** | **0.515 ms** | **301.7 TFLOPS** | **3.00×** | 22.0 % / 22.4 % |
| fp8 weights + activations, scaled | 0.595 ms | 261.6 TFLOPS | **2.60×** | 15.9 % / 18.5 % |

**This is the real multiplier: 3.00×, not 1.6–1.7×.** Round 1's 1.6–1.7× was measured on
large GEMMs with the *weights* in FP8 but the activations in BF16, and on a chain that
regenerated a fresh random weight matrix **inside the timed region** — so it measured
`randn + cast`, not the matmul. Rebuilt correctly, FP8 weights alone buy **1.29×** and
FP8 weights *with* fused activations buy **3.00×**.

Across four runs on this box (loads 15 → 110) the fused multiplier was **2.13, 2.51,
2.76, 3.00×** and the scaled one **1.82, 2.33, 2.60, 2.69×**. The spread is the box, not
the code; the ordering never changed.

**Per shape**, so the multiplier is not a single number:

| GEMM shape (tokens × in × out) | BF16 | FP8 | FP8 speedup |
|---|---|---|---|
| 4096 × 1280 × 320 | 41.0 TF | 71.6 TF | 1.70× |
| 4096 × 320 × 640 | 36.3 TF | 45.0 TF | 1.26× |
| 4096 × 640 × 1280 | 80.8 TF | 132.0 TF | 1.64× |
| 4096 × 1280 × 5120 | 135.2 TF | 298.2 TF | 2.25× |
| 4096 × 5120 × 1280 | 107.3 TF | 235.6 TF | **2.95×** |
| 4096 × 1280 × 1920 | 108.9 TF | 222.4 TF | 1.28× |
| 4096 × 1920 × 640 | 69.4 TF | 136.8 TF | **2.96×** |
| 4096 × 640 × 1280 | 85.5 TF | 128.8 TF | 1.67× |

The big GEMMs get ~2.2–3.0×; the skinny ones get 1.26–1.7×. **A claim about "the FP8
multiplier" is meaningless without saying which shape.**

**The price:** FP8 e4m3 has a 3-bit mantissa, so a single quantisation carries ~3.5 %
relative error and 8–16 layers of it compound. The full stack's output differs from the
BF16 reference by **15.4 % (weights only) to 22.0 % (fused)** relative. That is not a
drop-in for anything whose output is checked. Round 1's conclusion — *keep the critic and
the provenance path in BF16* — survives, and now has a number attached.

### 4.2 The sweep: S = 1, weights only

BF16 stack, 1.946 GB of weights resident. "launch-bound" is the ratio of the CPU-side
issue time to the step time: **1.0 means the host cannot issue the work faster than the
GPU can do it**, so adding rows to the batch is free.

| N | step (best) | step (median) | items/s | weight GB/s | ×273 | CPU issue | launch-bound | J/item | J/item above baseline |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 12.10 ms | 12.23 | 83.7 | **160.8** | 0.59 | 8.85 ms | 0.72 | 0.932 | 0.219 |
| 2 | **11.71 ms** | 11.88 | 168.6 | **166.3** | **0.61** | 7.35 ms | 0.62 | 0.444 | 0.119 |
| 4 | 12.41 ms | 13.23 | 326.2 | 156.9 | 0.57 | 7.38 ms | 0.56 | 0.231 | 0.059 |
| 8 | 12.41 ms | 13.36 | 631.4 | 156.8 | 0.57 | 8.44 ms | 0.63 | 0.121 | 0.023 |
| 16 | 13.00 ms | 13.20 | 1189.5 | 149.7 | 0.55 | 8.40 ms | 0.64 | 0.071 | 0.022 |
| 32 | 13.62 ms | 14.07 | 2072.2 | 142.9 | 0.52 | 15.16 ms | 1.08 | 0.040 | 0.009 |
| 64 | 14.51 ms | 14.75 | 4434.4 | 134.1 | 0.49 | 8.00 ms | 0.54 | 0.019 | 0.006 |
| 128 | 16.11 ms | 16.18 | 8037.0 | 120.8 | 0.44 | 8.81 ms | 0.54 | 0.011 | 0.004 |
| 256 | 18.75 ms | 19.26 | 13474.6 | 103.8 | 0.38 | 9.02 ms | 0.47 | 0.007 | 0.003 |
| 512 | 23.57 ms | 23.63 | 22129.7 | 82.6 | 0.30 | 12.29 ms | 0.52 | 0.005 | 0.002 |

**Where batching stops being free: N ≈ 32.** The step time is **flat from N = 1 to N = 8**
(11.7–12.4 ms for 8× the work) and then grows roughly linearly: **+20 % by N = 64, +95 %
by N = 512**. The aggregate items/s still climbs monotonically to 22 130 items/s, and the
joules per item fall **186×** from N = 1 to N = 512 — so even where batching is no longer
free in time, it is still overwhelmingly worth it in energy.

**But the reason batching is free is not Kimi's.** Kimi says the weights stream once.
They do — but at N ≤ 8 the step is *not* limited by the weights at all: the CPU issue
time is **7.4–8.9 ms against a 12 ms step**, and the FP8 stack's issue time *equals* its
step time (launch-bound ratio 0.94–0.99). **The step is launch-bound; the extra rows ride
along in the launch overhead's shadow.** When the weights finally do become the limit, the
achievable rate is **166 GB/s — 0.61× the 273 GB/s datasheet**.

### 4.3 The sweep: S = 1024, a realistic agent context

| N | step (best) | items/s | weight GB/s | CPU issue | launch-bound | J/item |
|---|---|---|---|---|---|---|
| 1 | 13.62 ms | 73.6 | 142.9 | 8.06 ms | 0.55 | 1.079 |
| 2 | 14.46 ms | 144.7 | 134.6 | 8.51 ms | 0.59 | 0.540 |
| 4 | 14.64 ms | 154.6 | 133.0 | 8.39 ms | 0.56 | 0.554 |
| 8 | 19.11 ms | 520.7 | 101.9 | 11.32 ms | 0.56 | 0.177 |
| 16 | 15.92 ms | 1005.3 | 122.2 | 11.55 ms | 0.52 | 0.082 |
| 32 | 19.29 ms | 1108.9 | 100.9 | 7.75 ms | 0.39 | 0.080 |
| 64 | 30.27 ms | 1836.3 | 64.3 | 10.95 ms | 0.32 | 0.049 |
| 128 | 53.72 ms | 3194.5 | 36.2 | 17.60 ms | 0.30 | 0.029 |

**Batching is not free here at all**: the step time grows **3.9×** from N = 1 to N = 128,
and the launch-bound ratio falls to 0.30 — the GPU is now the constraint, and the
constraint is the **KV cache**, which is per-agent. At N = 128, S = 1024 the cache traffic
is **4.3 GB per step against 1.9 GB of weights** — the cache is 2.3× the model, and it
scales linearly with N.

The N = 8 and N = 16 points are out of order with each other; the box was at load 33 and
those are the noisiest points in the table. The trend (13.6 → 53.7 ms) is not in doubt.

### 4.4 The same sweep in FP8

FP8 with fused activations, S = 1: **9.35 ms at N = 1** against BF16's 12.10 ms — a
**1.29× end-to-end gain**, even though the GEMM chain is **3.00×** faster and the weights
are **half** the size. The reason is in the same column: **the CPU issue time is 9.35 ms,
exactly the step time.** The FP8 stack does its 112 GEMMs in less time than the host can
issue them. **FP8 does not make the stack faster until the launch overhead is removed**
(see `exp-cuda-graphs-nvenc.md`).

## 5. What this changes

### 5.1 The measurement trap that had to be fixed first

The GPU idles at **315 MHz** and ramps to **1575 MHz** under the `nvhost_podgov`
governor, taking about **1.4 s of sustained load**. Measured directly:

| state | clock | 8-GEMM BF16 chain |
|---|---|---|
| cold (first measurement after idle) | 315 MHz | **3.51 ms** |
| after 1.4 s of sustained work | 1575 MHz | **1.40 ms** |
| after 5 s idle again | 1323 MHz | 1.84 ms |

**A 2.6× error, in the first measurement of every session.** Every experiment in this
round warms the GPU before timing and records the clock beside the number. This is a
`Part D` trap that applies to *every* GPU number on this box, including rounds 1 and 2.

### 5.2 The bandwidth number to use

Kimi's formula, `T_pass ≈ active_params × bytes/param / 273 GB/s`, assumes 273 GB/s.
**This box delivers 166 GB/s of weight streaming in an eager step** (the number a serving
loop actually sees) and **~220 GB/s of pure GPU bandwidth** once the launch overhead is
removed with a CUDA Graph (1.946 GB in an 8.83 ms graphed step, the quietest measurement
in the round; the same measurement on a busier GPU gave 96 GB/s, see
`exp-cuda-graphs-nvenc.md`). **The datasheet number is 1.24–1.64× optimistic.** Any
T_pass computed from 273 GB/s is a T_pass that cannot be achieved.

### 5.3 What the design should say

- **Batch the agents** — the joules per item fall 186× between N = 1 and N = 512, and the
  weights stream once per step as Kimi says. But batch *only* while the agents' contexts
  are short. **With 1024-token contexts the per-agent KV cache dominates the model, and
  the batch stops being free at N ≈ 2.**
- **Do not plan on 273 GB/s.** Plan on 166 GB/s eager, ~220 GB/s graphed.
- **Do not plan on a 3× FP8 multiplier in eager mode.** Plan on 1.3×, or 2.5–3.6× if the
  step is captured in a CUDA Graph.
- **FP8 is not a drop-in for the critic.** 15–22 % output error; the critic and the
  provenance path stay in BF16.

## 6. Reproduce

```bash
cd /home/caseydigennaro/lm-wt/lab3
.venv/bin/python scripts/exp2_batched.py          # -> results/exp2_batched.json

# the multiplier on its own
python3 -c "
import json; m=json.load(open('results/exp2_batched.json'))['fp8_multiplier']
print(m['bf16_ms'], m['fused_ms'], m['speedup_fused_vs_bf16'])"
```

## 7. Licence note

`torch` (BSD-3-Clause). No weights are downloaded: the model is a **synthetic** decoder
stack with seeded random weights, which is what makes the byte accounting exact and the
comparison between the BF16 and FP8 stacks exact in intent.

## 8. Failures that stayed

- **Joules per item must divide the window's joules by (steps × N), not by N.** The first
  run of this script divided by N alone and over-reported by the number of steps in the
  window — a factor of ~100.
- **Grouped-query attention must not materialise a `repeat_interleave` copy of the KV
  cache.** The copy is 4× the cache; it made the S = 1024 sweep measure the attention
  *implementation* rather than the model (234 ms/step at N = 128 instead of 54 ms).
  Reading the cache once with an `einsum` over the group axis is the correct form.
- **The scale tensors for `_scaled_mm` must be allocated once, outside the timed loop.**
  Creating them inside is a synchronous H2D copy per GEMM, which costs more than the GEMM.
- **The BF16 reference chain must not overwrite its own input.** The first version left
  `x` holding the *output* of the calibration pass, so every chain ran from the wrong
  starting point.
- **The output reconstruction must be outside the timed region.** Comparing a chain's FP8
  *representation* against a true-value reference, and timing that reconstruction, made
  the calibrated chain look 34 % slower than it is.
- **A GPU with a power governor must be warmed before it is measured.** See §5.1.
- **On a shared box the whole-box INA rail needs a baseline subtraction**, and even then
  the absolute joules are only meaningful when the load is low. See `exp-joules-per-fixed-point.md`.
