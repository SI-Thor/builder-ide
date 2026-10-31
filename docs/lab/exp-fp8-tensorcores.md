# EXP C — FP8 on the Thor's Blackwell tensor cores vs FP16/BF16, as the upper bound for quantized generators

**Date:** 2026-10-30 23:07 local (Alaska Daylight Time)
**Verdict: USEFUL — FP8 works and is 1.6–1.7× faster with half the weight memory.
FP4 is a measured *no* on this stack.**

---

## 1. The idea

FP8/FP4-quantized generators (TRELLIS.2, image models) so several stay resident at once
instead of swapping (`IDEAS.md` idea #3). The Thor is marketed with 2,070 TFLOPS of
sparse-FP4 inference, and rev-tech §4 (idea 10) warns that this figure is a *dataclass
NN-inference* number, not something the procedural pipeline can be sized against. So:
measure the actual FP8 (and FP4) matmul throughput of the tensor cores, and treat it as
the upper bound for quantized generators.

## 2. Hypothesis

The sm_110 Blackwell tensor cores do FP8 (e4m3) matmul at materially higher throughput
than FP16/BF16, and FP8 halves the resident size of every weight matrix — so several
quantized generators stay resident in unified memory at once.

## 3. Setup

- Venv `/home/caseydigennaro/lm-wt/lab1/.venv` (Python 3.12.3).
- `torch 2.15.0+cu132` (PyPI aarch64 CUDA 13.2 build; `torch.cuda.get_arch_list()` →
  `['sm_80', 'sm_90', 'sm_100', 'sm_110', 'sm_120']` — **sm_110 is in the shipped
  arch list**, confirmed at runtime).
- FP8 via `torch._scaled_mm` with rowwise scales; FP16/BF16 via `torch.mm`; FP32 as the
  non-tensor-core reference.
- Script: `scripts/exp_fp8_tensorcores.py`; raw output: `results/exp-fp8-tensorcores.txt`.
- Added for the FP4 attempt: `torchao 0.18.0` (the only route on this stack that packs
  NVFP4).

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-30 (final run, 23:0x local) |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` | 122.80 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| Device | `NVIDIA Thor`, cc `(11, 0)` = sm_110 |
| torch arch list | `sm_80, sm_90, sm_100, sm_110, sm_120` |
| `tf32 allowed` | False (so FP32 below is genuine FP32, not TF32) |
| FP8 dtypes present | `float8_e4m3fn`, `float8_e4m3fnuz`, `float8_e5m2`, `float8_e5m2fnuz`, `float8_e8m0fnu` |
| FP4 dtype present | `float4_e2m1fn_x2` (the *dtype* exists; see C4) |

## 4. The numbers

### C2/C3 — matmul throughput

8192 × 8192 × 8192 (median of 10 after 5 warmups). The right-hand column is the range
across **four runs** on 2026-10-30, because the box is shared and the GPU timings move:

| dtype | Time | TFLOPS | TFLOPS (4 runs) | vs FP16 |
|---|---|---|---|---|
| FP32 | 172.71 ms | 6.37 | 6.36–6.37 | 0.06× |
| FP16 | 9.75 ms | 112.79 | 106.10–113.77 | 1.00× |
| BF16 | 10.06 ms | 109.32 | 109.32–110.77 | 0.97× |
| **FP8 e4m3** | **6.21 ms** | **176.96** | **176.96–185.95** | **1.57–1.75×** |

4096 × 4096 × 4096:

| dtype | Time | TFLOPS | TFLOPS (4 runs) |
|---|---|---|---|
| FP32 | 22.68 ms | 6.06 | 6.06–6.07 |
| FP16 | 1.43 ms | 96.00 | 96.00–113.77 |
| BF16 | 1.10 ms | 125.34 | 117.83–125.34 |
| **FP8 e4m3** | **0.80 ms** | **171.21** | **140.06–172.29** |

**FP8 ≈ 1.57–1.75× FP16 at 8192³**, consistently across runs. The 4096³ FP8 figure is
the noisiest number in this file (140–172 TFLOPS) — smaller GEMMs are short enough that
scheduling jitter on a shared box shows up; the 8192³ number is the one to quote.

**Accuracy.** FP8 against the BF16 reference: max abs error 18.75 with reference max |v|
536.00 → **relative error 3.50e-02** at 8192, 3.78e-02 at 4096. That is the expected
e4m3 mantissa error (3-bit mantissa) and it is *not* a bug — but it is also **not** a
drop-in replacement for FP16 in an exactness-sensitive path. Diffusion models tolerate it
because they run many steps; a single-GEMM numerical pipeline may not.

### C4 — FP4 (nvfp4): measured NO

Torch 2.15 exposes the `float4_e2m1fn_x2` dtype but **no conversion op** — `a.to(torch.float4_e2m1fn_x2)` raises
*"copy_() does not support casting Float4_e2m1fn_x2 to different types"*. The only route
that packs on this stack is `torchao` 0.18's `NVFP4Tensor.to_nvfp4`, which works:

| | Time | TFLOPS |
|---|---|---|
| NVFP4 matmul (8192³) | 80.31 ms | **13.69** |
| — dequantize one matrix | 35.27 ms | — |
| — BF16 matmul of the dequantized matrix | 10.66 ms | 103.16 |
| — **dequantize + BF16 matmul** | **45.92 ms** | — |

**Ratio NVFP4 / (dequantize + BF16 mm) = 1.75.** If FP4 tensor cores were engaged, this
ratio would be well below 1.0 (you would pay a fraction of the dequantize cost and get a
tensor-core matmul). At 1.75, the NVFP4 path is **slower than simply decompressing to
BF16 and multiplying** — it is a fallback, not a tensor-core path. NVFP4 relative error vs
the BF16 reference: 0.1359 (i.e. 13.6 %, the expected e2m1 error).

**Conclusion: FP4 tensor cores are not reachable on sm_110 through torch 2.15 + torchao
0.18.** The 2,070 TFLOPS FP4 figure in NVIDIA's Thor marketing is not available to this
stack. FP8 is.

### C4b — a diffusion-step-shaped GEMM chain, measured end to end

Eight representative transformer/UNet linear shapes (320/640/1280 → 5120, etc.) at 4096
tokens, timed end to end:

| | Time |
|---|---|
| FP16 chain | 3.46 ms |
| FP8 chain | 3.64 ms |
| **speedup** | **0.95×** |

**FP8 was *slower* here**, and the reason is instructive: the chain pays a
fp32→fp8 cast of every activation plus a scale allocation per GEMM, and at these GEMM
sizes that overhead exceeds the 1.6× compute saving. This chain **understates** the FP8
benefit for a real generator, which keeps activations in FP8 between layers and would not
re-cast — but it is the honest measurement of the naive port, and it says: **quantizing
the weights alone is not enough; the activations must be quantized too, or FP8 buys
nothing.**

### C5 — bytes per parameter and the residency consequence

| Precision | GB per 4 B-parameter model | Fit in 122.8 GB (weights only) |
|---|---|---|
| FP32 | 14.90 | 8 |
| FP16 / BF16 | 7.45 | 16 |
| **FP8 e4m3** | **3.73** | **32** |
| FP4 nvfp4 | 1.86 | 65 — *measured NOT usable on this stack* |
| INT8 | 3.73 | 32 |

## 5. How to reproduce

```bash
cd ~/lm-wt/lab1
.venv/bin/pip install "torch==2.15.0" "numpy<2.6" torchao
.venv/bin/python scripts/exp_fp8_tensorcores.py     # ~3 min
```

Raw output: `results/exp-fp8-tensorcores.txt`. The script was re-run from scratch after
this file was written and reproduced every figure within the ranges quoted above.

## 6. Verdict

**USEFUL.**

- **FP8 works on this box and is 1.6–1.7× FP16** on large GEMMs (≈ 177–183 TFLOPS vs
  ≈ 106–113 TFLOPS). The FP8 tensor cores are real and are in torch's shipped sm_110
  kernels.
- **FP8 halves the resident size of every weight matrix** (3.73 GB for a 4 B-parameter
  model vs 7.45 GB in FP16). With 122.8 GB of unified memory, that is 32 weight-only
  copies instead of 16 — the difference between a scheduler that thrashes and one that
  doesn't.
- **FP4 is a measured no on this stack.** 13.69 TFLOPS, and 1.75× the cost of just
  dequantizing to BF16 and multiplying. Do not schedule against NVIDIA's 2,070 TFLOPS
  FP4 figure.

### What this changes for the plan

- The model's hot/warm/cold tiers can be sized in **FP8**, which doubles the number of
  warm models that fit. Since the real constraint on this box is *weight-swap thrash*
  (rev-tech §C4), not raw capacity, halving the weight footprint is the single highest-
  leverage change available to the scheduler.
- **The activation cast is the thing to solve.** C4b shows weights-only FP8 quantization
  yields 0.95× on a realistic GEMM chain. A generator that keeps activations in FP8
  (fused QKV/attention/MLP in FP8, as ComfyUI's `--fp8_e4m3fn-unet` intends) would see
  the 1.6×. **That flag is now worth testing for real** — it was previously an untested
  option (rev-tech R9).
- FP8's 3.5 % relative error means **the critic and the asset-licence/provenance path
  should stay in BF16/FP16** while the bulk generation runs in FP8.

## 7. Licence note

`torchao` (BSD-3-Clause), `torch` (BSD-3-Clause). Code only — no model weights were
downloaded, so no weights-licence implications. The FP8 path itself is licence-neutral:
it is a numeric format, not a redistribution.

## 8. Failures that stayed

- `a.to(torch.float4_e2m1fn_x2)` raises `RuntimeError: copy_() does not support casting
  Float4_e2m1fn_x2 to different types`. Torch 2.15 has the FP4 *dtype* but no *casting
  op* for it — the presence of `float4_e2m1fn_x2` in `dir(torch)` is not evidence that
  FP4 is usable.
- `torch._scaled_mm` rowwise scaling requires `scale_b` to be `(1, N)` where **N is the
  output width of that particular GEMM**; reusing one `(1, 4096)` scale across a chain of
  differing shapes fails with *"Invalid scaling configuration"*.
- `torch._scaled_mm_v2` exists but has no docstring and no FP4 path that works here.
- cuBLASLt is not exposed by CuPy 14.2 (`cupy.cuda` has no `cublasLt` attribute), so the
  raw cuBLASLt FP8/NVFP4 route could not be tested from Python as a cross-check.
