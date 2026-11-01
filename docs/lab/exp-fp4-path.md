# EXP — FP4 on the Thor, for real: the NVFP4 tensor-core path on sm_110

**Date:** 2026-10-31 (started by the previous seat after the 13:22 OOM reboot;
finished in this session). **Seat:** `~/lm-wt/lab-fp4`.
**What the hardware does, and what this lab found.** The Thor's Blackwell tensor cores (sm_110) accept **NVFP4** directly: 4-bit e2m1 values with one UE4M3 scale per 16 elements, packed in the tcgen05 128×4-tile block layout. Round 1 measured FP4 through torchao at 13.69 TFLOPS, *slower* than BF16, and recorded the dtype as unusable. torchao dequantised the weights to BF16 and multiplied in BF16, so the FP4 units were never used.

cuBLASLt 13.4.1's block-scaled path feeds the packed e2m1 values and their scales straight to the tensor cores. Measured here:
- **371–456 TFLOPS dense:** 1.6–2.2× FP8 and 2.5–4.3× BF16 when the inner dimension K ≥ ~2048, at roughly half FP8's joules per GEMM.
- **Shape-dependent:** at UNet-sized K (320–1280), today's library kernels are *slower* than BF16, because the per-tile scale handling and fixed tile shapes cost more than the narrower arithmetic saves.
- **Mixed operands through CUTLASS 4.4.1 on sm_110a:** MXFP8 activations × MXFP4 weights, a combination cuBLASLt refuses, run and validate numerically at 96 TFLOPS untuned.

Everything here is `FP4 = NVFP4` (e2m1 codes, one UE4M3 scale per 16 elements,
packed in the tcgen05 128×4-tile block layout) unless stated otherwise.

---

## 1. The idea (BRIEF lab-fp4)

Round 1 (`exp-fp8-tensorcores.md` C4) killed FP4 *through torchao at 13.69
TFLOPS* and IDEAS Part B froze "sizing work against 2,070 TFLOPS FP4" as a
killed claim. The brief: find out how much of the Thor's FP4 hardware is
actually reachable, by building the path ourselves — cuBLASLt first, CUTLASS
second, our own kernel third — then convert our own models if a fast path
exists. Part 2 (models) ran and is in `exp-fp4-models.md`.

## 2. Hypothesis

The FP4 tensor cores exist (datasheet, and torch exposes the dtype); what was
missing in round 1 was a caller that speaks the library's block-scaled
protocol on sm_110. Direct cuBLASLt/CUTLASS calls with a correct scale-tensor
layout should unlock them.

## 3. Setup and the box's state

| | |
|---|---|
| Date of runs | 2026-10-31, 13:33–15:20 local |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores / MemTotal | 14 / 122.80 GiB (unified, no swap) |
| Power mode | MAXN |
| Driver / toolkit | 595.78 / CUDA 13.2.86 (`nvcc` from `/usr/local/cuda-13.2`) |
| cuBLASLt (driver side) | 13.4.1 (`cublasLtGetVersion() = 130401`) |
| Device | `NVIDIA Thor`, cc (11,0) = **sm_110**, 20 SMs, max clock 1,575 MHz (315 idle) |
| nvcc targets | `compute_100`, `compute_110` listed; `-arch=sm_110` and `sm_110a` both compile and run |
| Box sharing | other seats active, load 5–18 beside every table; the 13:22 crash's lock rule (`flock ~/lm-wt/heavy.lock`, ≥25 GB kept free) was followed: sweep peak ≈6 GB host+device; each CUTLASS build ≈4–6 GB, run under the lock; model experiments <3 GB, no lock |

Scripts: `scripts/lt_heuristic_probe.cu` (previous seat), `lt_fp4_bench.cu`
(previous seat, **fixed here**: scale *and* packed buffers must be padded to
128-row tiles), `lt_fp4_scaleprobe*.cu`/`lt_fp4_scalemap.cu` (previous seat —
the one-hot probes that recovered the scale layout), `cutlass_sm110_nvfp4.cu`
(previous seat; comparison fixed here), `cutlass_sm110_mxfp8xfp4.cu` (this
session). Raw outputs in `results/`.

## 4. Part 1, step 0 — the addendum's probes

- **nvcc targets:** `sm_110` and `sm_110a` both accepted by nvcc 13.2.86
  (there is no `sm_110f` in `--list-gpu-arch` output; `sm_110a` works —
  the CUTLASS builds prove it at runtime).
- **`cublasLtMatmulAlgoGetHeuristic` with FP4 block-scaled types**
  (`results/lt-heuristic-8192.txt`, M=N=K=8192, 8 algorithms requested):

| config | result |
|---|---|
| **NVFP4 FP4×FP4 → FP16/BF16/FP32, `VEC16_UE4M3`, TN** | **3 algorithms — the path exists** |
| NVFP4 NN / TT | rejected (status 15 = INVALID_VALUE) |
| MXFP4 `VEC32_UE8M0` (all layouts, all outputs) | rejected (status 7) |
| mixed FP8×FP4, FP4×FP8, BF16×FP4, FP4×BF16 (all scale modes tried) | rejected |
| FP8 block-scaled (vec16/vec32) | rejected |
| FP8 scalar32F / BF16 (controls) | 8 algorithms each |

So on sm_110 today: **NVFP4 in TN layout only; no MXFP4, no mixed operands**
from cuBLASLt. (CUTLASS fills the mixed gap — §6.)

## 5. The numbers

### 5.1 The interleaved sweep (`results/sweep-main.txt`)

3 rounds × {bf16, fp8, nvfp4, nvfp4dq} back to back, median-of-3-rounds
ranges below (clock warmed 1.6 s per timing; VDD_GPU rail sampled at 10 ms;
GPU at 1,575 MHz throughout; load 5–18). `nvfp4dq` = dequantize-both-operands-
to-BF16-then-BF16-GEMM, the round-1 "fallback" path, measured end to end.

| M×N×K | BF16 | FP8 | **NVFP4** | NVFP4/FP8 | NVFP4/BF16 | nvfp4dq |
|---|---|---|---|---|---|---|
| 2048³ | 157–171 | 192–195 | **401–413** | 2.1× | 2.5× | 34–35 |
| 4096³ | 108–112 | 190–241 | **422–456** | 1.9–2.2× | 3.9× | 47 |
| 8192³ (round-1 anchor) | 104–109 | 201–214 | **365–388** | 1.7–1.9× | 3.5× | 63–68 |
| 16384³ | 100–101 | 178–185 | **366–372** | 2.0× | 3.7× | 77 |
| 4096×5120×5120 (SDXL ff-ish) | 104–114 | 185–215 | **317–332** | 1.6× | 3.0× | 49–50 |
| 1024×8192×8192 (decision-model-ish) | 45–82 | 214–220 | **343–417** | 1.7× | 5–9× | 24–27 |

Energy per GEMM (VDD_GPU rail, J/iter, 8192³): BF16 1.55, FP8 0.77,
**NVFP4 0.41** — the FP4 path is ~1.9× cheaper than FP8 and ~3.8× cheaper than
BF16 per GEMM while also being fastest. Peak measured **456 TFLOPS = 22 % of
the 2,070 sparse-FP4 datasheet figure (≈44 % of the implied 1,035 dense)**.

Correctness: NVFP4 vs an FP32 reference computed from the *same quantized
codes*: errRMS 2.2e-3 at 1024³, 4.5e-3 at 4096³ (pure FP16-output rounding)
— after the buffer-padding fix below. Without it, any M not a multiple of 128
produced garbage (§5.3).

### 5.2 Where FP4 pays: the (N,K) landscape (`results/fp4-landscape.txt`)

M=4096, bare GEMM (no quant/transpose), TFLOPS:

| K \ N | 320 | 1280 | 5120 | 8192 |
|---|---|---|---|---|
| 320 | 78 | 127 | 73 | 68 |
| 768 | 174 | 321 | 154 | 163 |
| 1280 | 232 | **475** | 253 | 253 |
| 2048 | 267 | 343 | **374** | 358 |
| 4096 | 287 | 369 | **416** | **424** |
| 8192 | 322 | 394 | 352 | **418** |

FP4 beats FP8 (≈180–240 TFLOPS here) essentially everywhere K≥1280 and at
N≥1280 for all K; but at **K=320, N≥5120 it falls to 68–73 TFLOPS** — *below
BF16's 100–130*. The current cuBLASLt sm_110 FP4 kernels are tuned for
compute-bound large-K GEMMs. Practical rule for models (measured further in
`exp-fp4-models.md` §E): **FP4 for the 5120-dim ff/attn-projection blocks and
long-K scorers; BF16 for 320/640-dim blocks.**

### 5.3 The constraints and the library bugs (all measured)

1. **TN layout only** (`A` (K,M) col-major = row-major activations (M,K);
   `B` (K,N) col-major = row-major weights (N,K); NN/TT rejected).
2. **K must be a multiple of 64** (K=48 rejected; 32 works but keep 64 — the
   scale tiles are 4 sf wide).
3. **M must be ≥8 and a multiple of 8**: no algorithm for M=4/12/15/31;
   **M=1 computes garbage** (errRMS ≈1.0) even with padded buffers. Zero-pad
   the batch to 8 and slice — then M=8..∞ all exact (verified relRMS ≈2e-4
   for M ∈ {1,5,8,16,17,32,48,64,96,128,256} through the wrapper).
4. **Scale AND packed-code buffers must be padded to 128-row tiles** (zeroed):
   the kernels read the whole 128-row MMA tile. Unpadded scales → garbage at
   M=64; unpadded packed codes → illegal memory access at M=1. (This was a
   bug in the inherited `lt_fp4_bench.cu`, fixed here; all sweep shapes were
   multiples of 128 so its published numbers were unaffected.)
5. **`CUBLASLT_ORDER_ROW` on the FP4 D layout returns an algorithm that
   computes WRONG values** — a mix of exact and garbage outputs plus NaNs
   (1036/131072 NaN, non-NaN median error 4.5 at M=256 N=512 K=1024). The
   col-major-D + transpose path is exact. (Re-testable via
   `FP4OPS_ALLOW_ROW_D=1` in `scripts/fp4ops.cu`.)
6. The heuristic returns **no algorithm unless the A/B scale pointers are
   non-null** even for a pure query.

### 5.4 The recovered scale layout (the missing piece from round 1)

For a logical scale entry (row r, sf column s) of an (R, S=R·K/16) scale
tensor, with a = r/128, b = (r%128)/32, c = r%32, d = s/4, e = s%4:

```
byte index = (a·(S/4) + d)·512 + 16·c + 4·b + e      (one UE4M3 byte per entry)
```

i.e. 128-row × 4-sf tiles; inside a tile the row-within-32-group has stride
16, the 32-row group stride 4, sf index stride 1. Recovered empirically by
the previous seat's one-hot probes (`lt_fp4_scaleprobe2.cu`: give every row a
distinct scale, one-hot codes, read back which buffer position each output
row used — `results/scalemap-M128.txt`), then validated end-to-end by the
error checks above. This matches CUTLASS's `SfKMajorAtom`
(`cutlass/detail/sm100_blockscaled_layout.hpp`) — confirmed independently by
the mixed-input kernel accepting the same formula with vec-32 scales.

## 6. CUTLASS on sm_110 (Part 1, step 2)

CUTLASS 4.4.1 (vendored in `vendor/cutlass`, BSD-3) has no sm_110 builders,
but `cute/arch/config.hpp` enables the tcgen05 block-scaled MMA kinds
(mxf4nvf4, mxf8f6f4, tf32, f16, s8 — plus TMEM, TMA_SM100, LOAD256) for
**SM110A**. The previous seat patched an `arch::Sm110` tag into the vendor
copy; the harnesses compile the sm_100 block-scaled collectives for
`-arch=sm_110a`.

- **NVFP4×NVFP4** (`scripts/cutlass_sm110_nvfp4.cu`, MmaTile 128×128×256,
  cluster 1×1×1): **the kernel builds and runs on sm_110a** — 102–103 TFLOPS
  (naive config; cuBLASLt's tuned 371–388 is the bar for tuning work).
  *Open:* its output disagrees with cuBLASLt on identical packed inputs
  (relRMS 1.4) — since the mixed kernel validates with the same tile formula,
  the mismatch is narrowed to the nvf4 element/scale details, not the tile
  layout. Untuned + unvalidated numerics ⇒ cuBLASLt remains the production
  NVFP4 path.
- **MXFP8 × MXFP4 mixed** (`scripts/cutlass_sm110_mxfp8xfp4.cu`, mirror of
  example 72c): **runs and is numerically correct** — relRMS 1.6e-3 vs an
  FP32 host reference computed from the same codes and UE8M0 scales, at
  96.4 TFLOPS (8192³, untuned). This is the addendum's "FP4 weights × FP8
  activations" operand mix, **which cuBLASLt rejects on this box** — the
  hardware supports it; the shipped library does not. Tuning (larger
  clusters, stream-K) is open; 96 ≈ the BF16 rate today.

## 7. Corrections this makes to IDEAS (for the director to lift)

- Part 0 "Serving models" row: replace "FP4 a measured no (13.7 TFLOPS…)" with:
  **FP4 NVFP4 via cuBLASLt 13.4.1 TN: 371–456 TFLOPS at K≥2048 (1.6–2.2× FP8,
  ~half FP8's joules, 3.55× smaller weights than BF16); at K≤1280 the library
  kernels lose to BF16 — shape-gate FP4 to big-K blocks.**
- Part B row "Sizing work against 2,070 TFLOPS FP4": amend, not delete —
  **measured dense ceiling 456 TFLOPS (22 % of the sparse claim); schedule
  against ≤450, and only for K≥2048 GEMMs.**
- Part B "FP8 as a drop-in for the critic": unchanged (BF16 stays), and the
  FP4 quality tables in `exp-fp4-models.md` reinforce it.

## 8. Part 3 — ideas beyond the box (ranked, IDEAS style)

1. **FP4-resident decision-model bank.** 0.5625 B/parameter → a 2 M-param
   tile scorer is 1.1 MB: hundreds resident where dozens of BF16 fit; and the
   decision-model-ish shape already runs at 343–417 TFLOPS. *Smallest
   experiment:* N scorers quantized resident, one CUDA graph scoring a batch
   through all of them; measure bank throughput vs a BF16 bank and the
   residency frontier. *Kill:* if per-model padding (batch → 8) wastes more
   than the compute saves at real request rates.
2. **Mixed MXFP8-act × MXFP4-weight linears, tuned.** Numerically proven
   (§6); halves the activation-quantization error vs FP4 acts (the QAT tables
   show activation quantization is the dominant error). *Smallest
   experiment:* sweep MmaTile/cluster on `cutlass_sm110_mxfp8xfp4` toward
   ≥200 TFLOPS, then one SDXL ff-block quality check vs BF16. *Kill:* if no
   config beats FP8 scalar on real shapes.
3. **Transpose-free FP4 serving.** The col-major-D + transpose convenience
   can cost 5–14× the bare GEMM at small N (measured: 0.011 ms bare GEMM vs
   0.155 ms through the wrapper at 4096×960×320). Keep activations
   column-major between FP4 layers (or fuse the transpose into the next
   layer's quantize kernel). *Smallest experiment:* rewrite the .so chain
   col-major end-to-end; time the SDXL workload. *Kill:* nothing — it's an
   engineering measurement.
4. **2:4 sparsity on top of FP4** — the "sparse" in the 2,070 figure:
   tcgen05 sparse block-scaled (CUTLASS ex. 84/89 territory). *Smallest
   experiment:* build ex. 84-style nvfp4-sparse for sm_110a, one shape,
   correctness vs dense on the pruned weights. *Kill:* if sm_110a lacks the
   sparse tcgen05 atoms (compiler will say so immediately).
5. **FP4 latent/texture store.** SDXL/TRELLIS latents (and Infinigen texture
   atlases) at 4.5× smaller for multi-scene resident state; reads dequantize
   on the fly at ~166 GB/s. *Smallest experiment:* latent round-trip PSNR +
   one image decoded from FP4 latents scored by the DINOv2 critic vs BF16
   latents. *Kill:* if the critic's score drops beyond the round-1 FP8 floor.

## 9. How to reproduce

```bash
cd ~/lm-wt/lab-fp4
export PATH=/usr/local/cuda-13.2/bin:$PATH
nvcc -arch=sm_110 -O2 -std=c++17 -Xcompiler -fopenmp \
    -o build/lt_fp4_bench scripts/lt_fp4_bench.cu -lcublasLt -lcublas
flock ~/lm-wt/heavy.lock stdbuf -oL ./build/lt_fp4_bench sweep | tee results/sweep-main.txt   # ~15 min
./build/lt_fp4_bench limits                      # K/M coverage probe
./build/lt_fp4_bench one nvfp4 4096 5120 5120    # any single shape
# CUTLASS (build under the lock; ~4 min each, ~4-6 GB RAM):
nvcc -arch=sm_110a -O2 -std=c++17 --expt-relaxed-constexpr \
  -Ivendor/cutlass/include -Ivendor/cutlass/tools/util/include \
  -o build/cutlass_sm110_mxfp8xfp4 scripts/cutlass_sm110_mxfp8xfp4.cu && \
  ./build/cutlass_sm110_mxfp8xfp4
```

## 10. Verdict

**A real FP4 tier, gated by shape.** The FP4 tensor cores on the Thor are
reachable today through cuBLASLt NVFP4 (TN, VEC16_UE4M3): 371–456 TFLOPS on
big-K GEMMs, 1.6–2.2× FP8, half FP8's energy, 3.55× smaller weights — and
CUTLASS proves the mixed FP8×FP4 variant exists on this silicon even though
cuBLASLt refuses it. FP4 is now a real tier for the models the Thor runs —
*applied to the right shapes* (K≥2048 dense blocks, long-K scorers) — while
small-K UNet blocks and tiny policy MLPs stay BF16/FP8 for now (library
kernel quality, not hardware; see `exp-fp4-models.md`).

## 11. Licence note

Code only. cuBLASLt/cuBLAS (NVIDIA toolkit, used via the installed toolkit);
CUTLASS 4.4.1 vendored unmodified **except** the `arch::Sm110` tag noted in
`vendor/cutlass/include/cutlass/arch/arch.h` (BSD-3). No model weights were
downloaded.

## 12. Failures that stayed (the record, per house style)

- torchao's 13.69 TFLOPS "NVFP4" (round 1) was a dequantize fallback — right
  measurement, wrong conclusion about the hardware; the direct path fixes it.
- `CUBLASLT_ORDER_ROW` + FP4: silently wrong values (§5.3.5).
- cuBLASLt MXFP4 (`VEC32_UE8M0`) and every mixed FP8/FP4/BF16 operand combo:
  heuristic-rejected on this library (status 7/15) — library, not hardware
  (CUTLASS mixed runs).
- M=1 FP4 GEMM computes garbage; M not ≡0 (mod 8) has no algorithm.
- Unpadded scale/packed buffers at M % 128 ≠ 0: garbage / illegal access.
- CUTLASS nvfp4 (mxf4nvf4 kind) on sm_110a: runs, numerics unresolved vs
  cuBLASLt (relRMS 1.4); the mixed kernel validates with the same tile
  formula, so the nvf4 path needs one more layout detail pinned.
- The heuristic needs non-null scale pointers to return anything.
- A debugging file named `bisect.py` in `/tmp` shadowed Python's stdlib
  `bisect` for anything run from `/tmp` (`random` → `bisect`) and cost ~20
  minutes of confusion. Name scratch files nothing that collides with the
  stdlib, and don't put them on `sys.path` by running from their directory.
