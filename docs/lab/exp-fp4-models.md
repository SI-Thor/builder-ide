# EXP — our own FP4 models on the Thor: quantizer, QAT, and where FP4 serving actually pays

**Date:** 2026-10-31. **Seat:** `~/lm-wt/lab-fp4`. **Prerequisite:** Part 1
(`exp-fp4-path.md`) found the fast path — cuBLASLt NVFP4 at 371–456 TFLOPS —
so the brief's Part 2 ran.

**Verdict: USEFUL, with a sharp boundary. Our NVFP4 quantizer + real
tensor-core serving works end to end (real-vs-fake-quant relRMS 2e-4, weights
3.5× smaller, capture-safe in CUDA graphs), and QAT is the difference between
"degraded" and "held": it recovers most of PTQ's quality loss on both a
decision MLP and a motion policy. But at *decision/policy model scale the FP4
path is latency-bound below BF16* (0.065 vs 0.022 ms graphed at B=1), and on
an SDXL-shaped UNet workload it is 2.5× *slower* than BF16 end to end — the
current kernels only win on large-K GEMMs. FP4 today is a residency +
large-K tier, not a universal serving tier.**

## 1. The idea (BRIEF Part 2)

Convert the models the Thor actually runs — small decision models (with QAT,
since we control training), a motion-policy stand-in, and the dense
UNet/flow blocks — to NVFP4 with our own quantizer (e2m1, per-16 UE4M3 block
scales), measuring speed, memory, joules and quality held or lost.

## 2. Setup

- `.venv/` in this directory: Python 3.12.3, `torch 2.15.0+cu132` (wheel
  cache; no system installs). No model weights downloaded.
- **The quantizer + real path:** `scripts/fp4ops.cu` → `build/libfp4ops.so`
  (device-side quantize kernels + the cuBLASLt NVFP4 GEMM, col-major D +
  transpose, per-shape resolved-descriptor cache so calls are CUDA-graph
  capture-safe), bound into torch by `scripts/fp4torch.py` (ctypes). The
  fake-quantizer for QAT (`nvfp4_fake_quant`, STE) mirrors the .so's
  arithmetic exactly.
- Experiment driver: `scripts/exp_fp4_models.py` → `results/fp4-models.txt`;
  per-GEMM decomposition → `results/fp4-sdxl-decomp.txt`.
- Box: as in `exp-fp4-path.md` §3 (same day, load 6–18, 1,575 MHz warmed
  before every timed section, variants interleaved inside each round). Peak
  memory of every section < 3 GB (no lock needed; `free -g` checked).

**Correctness spine.** Every "REAL fp4" number below went through the tensor
cores; the real path is validated against the fake quantizer at relRMS
2.07e-4 (= FP16 output rounding) for every M ∈ {1,5,8,16,17,32,48,64,96,128,256}
and every K ∈ {320,640,768,960,1280,2048,5120} used here (after padding
batches to multiples of 8 per the library's constraints — `exp-fp4-path.md` §5.3).

## 3. Quality: decision MLP and motion policy (B, C)

Models: decision MLP "tile scorer" 512→1024→1024→64 (Q over 64 candidate
tiles; 1.7 M params) and motion policy 768→2048→2048→256 (6.3 M params),
GELU. Task: distill a fixed seeded teacher (the honest framing for "quality
held": deltas are measured against each model's *own* BF16 output, since a
random-teacher task has an irreducible student error — ~49 % top-1 here).
Training: 2,500 steps AdamW+cosine, batch 2,048 (~40 s per model on the
Thor). PTQ = the BF16-trained model quantized at inference (weights **and**
activations, as the hardware requires); QAT = trained from scratch with
fake-quantized weights and activations (STE), then served through the real
tensor cores.

**Decision MLP** (teacher agreement ceiling 49.3 % for the BF16 student):

| variant | Q-MSE vs teacher | top-1 agree | relRMS vs own BF16 | top-1 kept vs own BF16 |
|---|---|---|---|---|
| BF16 baseline | 0.0296 | 49.3 % | — | 100 % |
| PTQ (real FP4) | 0.0375 | 44.1 % | 0.2407 | 71.3 % |
| **QAT (real FP4)** | **0.0333** | **47.1 %** | 0.3045 | 62.9 % |

**Motion policy** (continuous 256-dim action; argmax is not a "decision"
here — read MSE/relRMS):

| variant | MSE vs teacher | relRMS vs teacher | relRMS vs own BF16 |
|---|---|---|---|
| BF16 baseline | 0.0524 | 0.5742 | — |
| PTQ (real FP4) | 0.0668 | 0.6482 | 0.3966 |
| **QAT (real FP4)** | **0.0538** | 0.5821 | 0.2661 |

Readings:

- **PTQ costs real decision quality** — 5.3 points of top-1 agreement on the
  scorer (29 % of choices flip), +27 % MSE on the policy.
- **QAT recovers most of it**: scorer 47.1 % vs PTQ's 44.1 % (baseline
  49.3 %); policy 0.0538 vs 0.0668 (baseline 0.0524). On the policy the QAT
  model is nearly indistinguishable from the BF16 baseline (relRMS 0.582 vs
  0.574 vs teacher).
- "top-1 kept vs own BF16" is *lower* for QAT than PTQ **and that is the
  point**: QAT moves the model to a solution adapted to FP4 arithmetic
  rather than tracking its BF16 self — judged against the teacher it wins.
- Real tensor-core outputs match the fake-quantizer arithmetic the QAT
  trained against to relRMS 2e-4 per layer (1.9e-2 end-to-end through 3
  layers — the residual is the real path's FP16 inter-layer rounding; an
  FP32-out variant of the GEMM exists in cuBLASLt if a model ever needs it).
- **Memory: weights+bias 3.54× smaller** (e.g. policy 12.59 → 3.55 MB;
  0.5625 B/parameter including block scales, biases kept FP32).

What is *not* here: the two-level global tensor scale of NVIDIA's full NVFP4
recipe (we use block scales only); calibration on real tile/rollout data
(the teacher is synthetic). Neither changed any conclusion at this scale —
block-scale amax already uses the e4m3 range well for these layers — but
both belong in the production quantizer.

## 4. Latency: eager vs CUDA-graphed, BF16 vs real FP4 (D)

Motion policy forward (3 layers), median of 5×20, GPU ms / host-enqueue ms:

| batch | bf16 eager | bf16 graph | fp4 eager | fp4 graph |
|---|---|---|---|---|
| 1 | 0.158 / 0.159 | **0.022 / 0.008** | 0.976 / 0.977 | 0.065 / 0.009 |
| 64 | 0.165 / 0.166 | **0.029 / 0.008** | 0.511 / 0.512 | 0.072 / 0.008 |
| 256 | 0.161 / 0.162 | **0.060 / 0.013** | 0.492 / 0.493 | 0.142 / 0.009 |

- Round 3's launch-bound lesson repeats exactly: eager FP4 through ctypes is
  100 % host-bound (enq = gpu time); the CUDA graph removes it (0.013 ms to
  replay the whole FP4 chain) — and FP4 chains **do capture cleanly** with
  the .so's resolved-descriptor cache.
- But even graphed, **FP4 is 2.4–3× slower than graphed BF16 at this model
  scale**: per layer the FP4 path runs quantize + GEMM + transpose while the
  GEMMs are too small for the FP4 kernels' strengths (K=768/2048; the
  (N,K) landscape in `exp-fp4-path.md` §5.2 shows the crossover at K≈2048).
- **For tiny decision/policy models, BF16 + CUDA graphs is the right serving
  tier today; FP4's win there is memory (3.5× more models resident), not
  latency.**

## 5. The SDXL-shaped workload (E) and where the time goes

Eight representative UNet linears (qkv/proj/ff at dims 320/640/1280) at
4,096 tokens, 146 GFLOP total, same fp32 weights both sides, interleaved:

| path | gpu ms | enq ms | TFLOPS |
|---|---|---|---|
| bf16 eager | 3.17 | 0.210 | 46.0 |
| bf16 graph | **3.16** | 0.008 | 46.1 |
| fp4 eager | 7.53 | 0.346 | 19.4 |
| fp4 graph | **8.00** | 0.008 | 18.2 |

FP4 output vs BF16 from the same weights: relRMS ≈ 0.15 (single-layer e2m1
noise on weights+activations — the per-model gate the brief asks for must
run the real SDXL and the critic, which needs the ComfyUI wiring; this is
the honest block-level proxy). Weights 3.51× smaller (35.6 → 10.2 MB).

Per-GEMM decomposition (`results/fp4-sdxl-decomp.txt`, M=4096):

- Bare FP4 GEMM+transpose vs BF16 `mm`: at the K=320/640 shapes the .so path
  is **1.5–6.5× slower** than BF16 (e.g. 0.561 vs 0.088 ms at N=2560, K=320);
  at K=5120 it flips — **~2× faster** (0.288 vs 0.581 ms at N=1280, K=5120),
  the first shape where the tensor cores' FP4 rate shows through the
  wrapper overheads.
- The **transpose tax**: cuBLASLt gives col-major D (row-major D computes
  wrong values on this library), so every FP4 GEMM pays a fp16 transpose
  that can cost more than the GEMM itself at small N (0.011 ms GEMM vs
  ~0.15 ms through the wrapper at 4096×960×320). A col-major-inter-layer
  design (or a fused transpose-in-quantize) removes it — idea #3 in
  `exp-fp4-path.md` §8.
- The **quantize kernels** cost 0.04–0.4 ms per layer at 4,096 tokens
  (fp32 read + amax + encode ≈ 100–160 GB/s). Dynamic per-call activation
  quantization is what we measured; a calibrated static-activation scheme
  would trade quality for time.

**Conclusion for SDXL/TRELLIS blocks: do not port the 320/640-dim blocks to
FP4 today.** The 5120-dim ff/projection blocks are where FP4's 317–456
TFLOPS lives (`exp-fp4-path.md` §5.2); a mixed-shape port (FP4 for the big
blocks, BF16 elsewhere) is the follow-up experiment, and the full generator
gate (critic score, silhouette IoU vs BF16) needs the real pipeline.

## 6. DINOv2 (the critic)

Not quantized — per the brief, it stays BF16: round 3 measured 15–22 %
output error for FP8 on this class of work, and §3 above shows plain FP4
PTQ is worse still. Nothing to measure until a QAT-able critic exists.

## 7. How to reproduce

```bash
cd ~/lm-wt/lab-fp4
export PATH=/usr/local/cuda-13.2/bin:$PATH
nvcc -arch=sm_110 -O2 -std=c++17 -Xcompiler -fPIC -shared \
    -o build/libfp4ops.so scripts/fp4ops.cu -lcublasLt
.venv/bin/python scripts/exp_fp4_models.py 2>&1 | tee results/fp4-models.txt   # ~7 min
```

## 8. Verdict

- **The toolchain exists and is validated**: our NVFP4 quantizer, real
  tensor-core GEMMs from torch via ctypes, CUDA-graph capture, QAT with a
  fake quantizer that matches the hardware to 2e-4.
- **QAT is mandatory** for FP4 decision/policy models: PTQ flips ~29 % of
  tile choices; QAT holds quality at 3.5× smaller weights.
- **Speed is shape-gated**: FP4 is not a win at policy/UNet-small-block
  scale on current library kernels (bf16-graphed beats fp4-graphed 2–3×);
  it *is* the win for K≥2048 GEMMs and for residency. Schedule accordingly.

## 9. Licence note

Code only: torch (BSD-3), our own scripts (MIT, house style). No model
weights downloaded; teachers are seeded synthetic networks.

## 10. Failures that stayed

- Random-teacher distillation has a hard student ceiling (~49 % top-1);
  quality deltas are therefore reported against each model's own BF16
  output as well as the teacher. An analytic-rule task was tried and was
  *harder* to fit (68 % ceiling) — the teacher framing is the cleaner one.
- The .so's first transpose kernel (one thread per element with int64
  div/mod) ran at ~14 GB/s and made FP4 look 10–35× slower than the bare
  GEMM; per-call `cudaMallocAsync`/descriptor rebuilds added more. The
  fixed kernels + resolved-descriptor cache recovered ~2.5× — the remaining
  transpose tax is real and architectural (col-major D), not a bug.
- My reblock-kernel rewrite truncated partial 16-sf groups (S%16≠0 —
  exactly the UNet K values) and silently zeroed the tail scale columns:
  E's relRMS read 0.47 until caught. Correctness checks must cover *every*
  K a workload uses, not one representative K.
- `torch.randn(..., generator=g)` with a positional size + generator is
  rejected — and a mis-ordered function signature fed the note string into
  `n_test`, which presented as exactly that error. Print your args.
