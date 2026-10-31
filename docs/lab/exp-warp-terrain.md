# EXP B — NVIDIA Warp on aarch64 + sm_110, and a terrain-style SDF/noise kernel against the 14 Neoverse cores

**Date:** 2026-10-30 23:02 local (Alaska Daylight Time)
**Verdict: USEFUL — and not for the reason the idea assumed** (the GPU wins against an
optimised CPU on identical work, but a *restructured* CPU beat the GPU outright)

---

## 1. The idea

Infinigen's heaviest procedural stages — terrain, scattering, geometry-node evaluation —
rewritten as GPU kernels, e.g. with **NVIDIA Warp** (Python → CUDA kernels; check aarch64
support), kept resident in unified memory (`IDEAS.md` ideas #1, #11).

## 2. Hypothesis

NVIDIA Warp installs and runs on aarch64 against this Thor's sm_110 Blackwell GPU, and a
terrain-style SDF/noise kernel runs far faster there than the same math on the 14
Neoverse cores — fast enough that procedural stages move off the CPU lane entirely.

## 3. Setup

- Venv `/home/caseydigennaro/lm-wt/lab1/.venv` (Python 3.12.3). Added for this experiment:
  `warp-lang 1.18.0` (147.3 MB aarch64 wheel), `numba 0.68.1` + `llvmlite 0.50.0` (for a
  *fair* optimised CPU baseline — without it the NumPy-Python comparison is a straw man).
- Device: `NVIDIA Thor`, cc `(11, 0)` = sm_110.
- Script: `scripts/exp_warp_terrain.py`; raw output: `results/exp-warp-terrain.txt`.
- Kernel cache: `WARP_CACHE_PATH=.warp-cache` **inside the lab directory** (nothing written
  outside it).

### The kernel

A faithful mini-Infinigen: a value-noise fBm heightfield and a displaced-sphere SDF (the
shape of Infinigen's terrain "mountain" element). The noise uses a 16-bit integer hash
whose every intermediate stays below 2³¹, so **Warp's int32 and NumPy's int64 produce
bit-identical results** — the comparison is verifiable, not hand-waved.

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-30T23:02:19-0800 |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / 115.30 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` at start | 0 % util, 2.76 W, 30 °C, 315 MHz |
| `tegrastats` RAM | 46,706 / 125,749 MB |
| `tegrastats` VIN | 23.67 W peak / 14.34 W avg |
| loadavg (1/5/15) | 4.23 / 5.25 / 5.70 |
| Warp's own view | `CUDA Toolkit 13.4, Driver 13.2`; `"cuda:0": "NVIDIA Thor" (123 GiB, sm_110, mempool enabled)`; `device arch = 110` |

The box was **not** idle — another seat's `cmake` build held load ≈ 4–5 throughout. The
load was sampled *during* every individual measurement and is printed with each number
below; it was stable at 4.1–5.2 across all of them.

## 4. The numbers

### B1 — does Warp work at all on aarch64/sm_110?

**Yes.** Warp 1.18.0 initialises, enumerates the Thor as an sm_110 device, and compiles
kernels for it natively.

```
Module __main__ load on device 'cuda:0' took 654.53 ms  (compiled)   # cold
Module __main__ load on device 'cuda:0' took 1.16 ms  (cached)      # warm, .warp-cache/
```

**Cold compile ≈ 0.65 s per module; warm load 1.16 ms.** This is a one-off cost that
disappears once the kernel cache is populated — worth knowing for a service that must
start fast, and worth caching in the repo.

**And it is native sm_110 SASS, not a PTX-JIT binary.** The cache holds
`wp___main___*.sm110.cubin`; inspecting it:

```
$ cuobjdump --list-elf  wp___main___52091ce.sm110.cubin
ELF file    1: wp___main___52091ce.sm110.sm_110.cubin

$ cuobjdump --list-ptx  wp___main___52091ce.sm110.cubin
cuobjdump info : No PTX file found to extract from ...
```

This matters because rev-tech §C6 flags that **this box's `nvcc` defaults to sm_75** —
meaning hand-written CUDA extensions run on the driver PTX JIT and a SASS-only build
fails outright with *"no kernel image is available for execution on the device"*. Warp
compiles straight to sm_110 with no PTX embedded, so **Warp sidesteps the arch trap that
every from-source CUDA extension on this box has to work around.** That alone is an
argument for Warp over a hand-written extension for the procedural-stage rewrite.

### B2 — 2D fBm heightfield, 4096 × 4096, 5 octaves

| Implementation | Time | Written | vs Warp |
|---|---|---|---|
| **Warp (GPU)** | **4.6 ms** | 13.53 GB/s | — |
| NumPy, 1 thread | 2,999.3 ms | 0.02 GB/s | **647× slower** |
| NumPy, 14 threads | 656.3 ms | 0.10 GB/s | **142× slower** |
| **numba, 14 threads (optimised)** | **65.7 ms** | 0.95 GB/s | **14.2× slower** |

Across **four runs** on 2026-10-30 the GPU/kernel timings move around (the box is
shared): Warp **4.6 / 7.4 / 8.1 ms**, numba-14 **65.7 / 75.1 / 338 ms** (the 338 ms is
the run whose JIT compile landed inside the timed region, see §8). Taking the runs where
the compile was excluded, **Warp beats the optimised 14-core CPU by 10.2×–14.2×** on
identical work. The "647× vs NumPy" number is real but would not survive a review.

Correctness: `max |warp − numpy| = 4.768e-07` (relative 2.74e-07); `max |numba − numpy|
= 1.073e-06`. The three implementations agree to float32 rounding.

Note: NumPy on 14 threads is only **4.6×** faster than on 1 thread, not 14×. The fBm is
allocation-heavy and memory-bandwidth-bound, so threading it scales poorly.

### B3 — 3D displaced-sphere SDF, 256³ (16.7 M voxels)

| Implementation | Time | Noise evaluations |
|---|---|---|
| **Warp (GPU)** | **9.1 ms** | 16.7 M (per voxel) |
| NumPy, 1 thread | 45.5 ms | 16.7 M |
| NumPy, 14 threads | 48.5 ms | 16.7 M |
| numba, 14 threads, **per-voxel** | 71.8 ms | 16.7 M — *identical work to Warp* |
| numba, 14 threads, **separable** | **6.0 ms** | **65 K** (noise computed once per (x,y)) |

- **Warp vs the CPU doing identical work: 7.9× faster** (run 1) / **10.46×** (clean
  re-run). Apples-to-apples.
- **The restructured CPU versus the per-voxel GPU kernel is a photo finish, and which
  one wins depends on the run:** CPU wins by **1.53×** in run 1 (6.0 ms vs 9.1 ms), the
  GPU wins by **1.10×** in the clean re-run (7.1 ms vs 7.9 ms). Reported as a range:
  **0.91×–1.53×** — i.e. **a well-written CPU implementation matches the GPU on this
  workload.**

This correction matters, so it is worth stating plainly. The first run suggested
"restructuring the CPU beats the GPU by 1.53×". The re-run says that conclusion does not
survive: the two are the same speed within measurement noise. The robust finding is
narrower and still useful:

> **The GPU does not automatically win. It wins by 7.9–10.5× against a *faithful port*
> of the current CPU code — and by nothing at all against a *better* CPU implementation.**
> So a GPU rewrite must ship alongside the algorithmic work, or it ships a regression.

A 256³ SDF is also a modest workload (16.7 M voxels, 67 MB of output) — small enough
that the CPU's cache behaviour competes well with the GPU's bandwidth. A larger terrain
tile set would favour the GPU more; that is worth measuring rather than assuming.

### B4 — launch overhead (the interactive-clock tax)

| | Launch |
|---|---|
| CuPy `RawKernel` | 6.5 µs |
| PyTorch CUDA elementwise | 7.1 µs |
| **Warp** | **17.1 µs** |

Warp costs ~2.6× CuPy's launch overhead. Irrelevant for a 4 ms terrain kernel; it matters
if a builder's edit fans out into thousands of tiny kernel launches.

### B5 — does a Warp kernel mutate a NumPy buffer in place?

**Yes, but not the way you would guess — and the obvious API gets it wrong.**

| API | Pointer | Shares NumPy's buffer? |
|---|---|---|
| `wp.from_numpy(arr)` | `0x348000600` vs NumPy's `0x1f9fca80` | **no — it copies to the device** |
| `wp.array(ptr=..., dtype=..., shape=..., copy=False)` | `0x1f9fca80` | **yes — identical pointer** |

```
numpy after warp wrote       = [0.  1.5 3.  4.5 6. ] (expected [0.  1.5 3.  4.5 6. ])
MATCH (numpy sees GPU write) = True
via wp.from_numpy (copying)  = numpy unchanged? True -> proves from_numpy does NOT share
```

`wp.from_numpy` silently gives you a **device copy** — a classic silent-copy trap, the
same species as the `.cpu()` trap in EXP A. The zero-copy route is
`wp.array(ptr=host_ptr, dtype=..., shape=..., copy=False)`, which is the Warp equivalent
of CuPy's `UnownedMemory` wrapper from EXP A.

## 5. How to reproduce

```bash
cd ~/lm-wt/lab1
.venv/bin/pip install "warp-lang==1.18.0" "numba==0.68.1"
.venv/bin/python scripts/exp_warp_terrain.py      # ~3 min
```

Delete `.warp-cache/` to see the cold-compile number (654 ms) instead of the warm load
(1.16 ms). Raw output: `results/exp-warp-terrain.txt`.

## 6. Verdict

**USEFUL — with a sharp edge.** Warp on aarch64/sm_110 is real, supported, and fast:
it installs from a plain PyPI aarch64 wheel, compiles natively for sm_110, and beats an
optimised 14-core CPU by **7.9×–10.5×** on the 3D SDF and **10.2×–14.2×** on the 2D
fBm — the exact same work. The Python→CUDA workflow is exactly the shape the port needs:
Infinigen's Python stages can be rewritten as kernels without leaving Python.

But the experiment also produced two findings that change the plan:

1. **Optimise the algorithm before you move it to the GPU.** Against the *current* CPU
   code, the GPU is 7.9–10.5× faster; against a *restructured* CPU implementation
   (exploiting the separability of the SDF's displacement field) the two are level
   (0.91×–1.53× depending on the run). The GPU's advantage is over a faithful port, not
   over a better algorithm. The port must do both: restructure *and* port.
2. **Warp's `from_numpy` copies.** Any shared-buffer design must use
   `wp.array(ptr=..., copy=False)`; otherwise every "shared" buffer is silently
   duplicated.

### What this changes for the plan

- Warp is a viable candidate for the terrain/scatter rewrite. The aarch64 question is
  answered **yes**, and the sm_110 question is answered **yes** (no PTX-JIT tax, unlike
  the `nvcc` default of sm_75 that rev-tech §C6 flags for hand-written CUDA).
- Warp's ~0.65 s cold module compile should be paid once and cached; a service that
  compiles kernels on demand will feel it.
- The Infinigen port should pair "rewrite as a Warp kernel" with "look for separability
  and reuse" — the 3D SDF case is the concrete example of a stage that is better served
  by restructuring.

## 7. Licence note

`warp-lang` (Apache-2.0), `numba` (BSD-2-Clause), `llvmlite` (Apache-2.0). Code only, no
weights, no shipped-asset implications.

## 8. Failures that stayed

- **`numba` `parallel=True` was silent about layout.** Warming the JIT with a
  non-contiguous slice (`arr[:4, :4]`) compiles an `A`-layout specialisation; the timed
  call with a C-contiguous array then compiled *a second* specialisation **inside the
  timed region**, reporting 513 ms for work that actually takes 3.8 ms. Warm the JIT with
  a C-contiguous array of the same rank.
- **`numba` `prange` over a 3-axis array can be far slower than NumPy** if the inner
  loop recomputes a separable field. My first 3D numba kernel recomputed the fBm per
  voxel and looked 11× slower than NumPy — NumPy was winning because it broadcast a
  2D field across the third axis. Measuring against a straw man in *either* direction is
  the failure mode to watch for.
- **`wp.array()` in Warp 1.18 has no `owner=` argument** (it has `copy=` and `deleter=`).
  Passing `owner=False` raises `TypeError`.
- **`wp.from_numpy` does not share memory** (see B5) — the name suggests it does.
- Numba `prange` over 14 cores on this box gave 4.4× on a simple sqrt kernel
  (10.5 ms → 2.4 ms), not 14×, with another seat's build competing for cores.
