# EXP 7 — one Infinigen terrain element ported to Warp: bit-identical output, 44–56× the CPU path

**Date:** 2026-10-30 23:57 local (Alaska Daylight Time)
**Verdict: BREAKTHROUGH** — the Warp port of `mountains` produces **bit-identical**
output to Infinigen's own CPU *and* CUDA libraries (max |diff| = 0.0 over 16 million
points) while running **44–56× faster than the CPU path** and **6× faster than
Infinigen's own hand-written CUDA kernel**.

---

## 1. The idea

`IDEAS.md` idea #2 / Part C item #7: "Port one Infinigen terrain element to Warp",
with the kill condition *"Kill it if the outputs differ, or if the existing CPU path
is already under 1 s."*

The element is `mountains` — the terrain SDF element Infinigen uses to cut
mountain ranges (a max-blended Perlin fBm with a coverage mask and a slope term),
from `src/infinigen/terrain/source/common/elements/mountains.h`.

Two things make this the right element to port first:

1. It is *pure numeric* — a kernel over a grid of positions, with no Blender
   dependency — so it can be ported to Warp without touching anything else.
2. The Infinigen spike **already builds** it twice: a C++/OpenMP library and a
   hand-written CUDA library. So the port has a real oracle to be measured
   against, not a straw man.

## 2. Hypothesis

A Warp port of `mountains` can be **bit-identical** to Infinigen's own
implementations (the element is deterministic integer-hash + float math, and Warp
compiles to native sm_110 SASS), and it will be much faster than the CPU path.
It will also beat Infinigen's own CUDA library, because **that library
`cudaMalloc`s and copies the position buffer on every call** — on a unified-memory
box that copy is pure overhead.

## 3. Setup

- Venv: `/home/caseydigennaro/lm-wt/lab2/.venv` (Python 3.12.3), with
  `warp-lang 1.18.0`, `numpy 2.5.4`.
- Device: `NVIDIA Thor`, compute capability `(11, 0)` = sm_110.
- Script: `scripts/exp_warp_terrain_port.py`; raw output:
  `results/exp-warp-terrain-port.txt`.
- Bisect tool: `scripts/exp7_port_debug.py` + `vendor/infinigen-terrain/oracle.cpp`.
- **Nothing in `~/src/infinigen-thor` was edited.** The sources and the two *built*
  libraries were **copied** into `vendor/infinigen-terrain/` so the experiment is
  self-contained and does not depend on the other seat's tree:
  `mountains.h`, `FastNoiseLite.h`, `elements_util.h`, `blender_noise.h`,
  `nodes_util.h`, `vectors.h`, `mountains_cpu.so`, `mountains_cuda.so`.

### The three implementations compared

| | what it is |
|---|---|
| **Infinigen CPU** | the spike's own C++ build (`mountains_cpu.so`), OpenMP over 14 cores |
| **Infinigen CUDA** | the spike's own hand-written `.cu` kernel (`mountains_cuda.so`) |
| **Warp (this port)** | `scripts/exp_warp_terrain_port.py`, one thread per point |

The reference `.so`s are driven through `ctypes` with the same ABI Infinigen uses
(`init(...)` then `call(size, float3* positions, float* sdfs)`), so the comparison
is against the real thing, not a re-implementation.

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-30T23:57:09-0800 |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / 113.79 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` at start | 0 % GPU util, 2.36 W, 31 °C, 315 MHz |
| `tegrastats` RAM | 48,201 / 125,749 MB |
| `tegrastats` VIN | 28,380 mW peak / 17,461 mW avg |
| loadavg (1/5/15) | 12.95 / 11.77 / 10.30 |
| CPU busy at sample | cores 0–7 at 13–31 %, cores 8–9 at 100 % / 34 % (another seat's `pytest` + a `./configure`) |
| `jetson_clocks` | present, **not** locked |

**The box was heavily loaded** (load ≈ 13 on 14 cores) — another seat was running
pytest and a Python `./configure`. That loads the *CPU* path and barely touches
the GPU, so it works against the port, not for it. The load is printed beside
every measurement below.

## 4. The numbers

### 7.1 — timing (median of 3 after a warm-up)

| N points | Infinigen CPU | Infinigen CUDA | **Warp (port)** | Warp vs CPU | Warp vs CUDA | max \|diff\| vs CPU |
|---|---|---|---|---|---|---|
| 1,024 | 1.0 ms | 1.0 ms | **0.2 ms** | 4.3× | 4.3× | **0.0** |
| 1,048,576 | 359.0 ms | 38.4 ms | **6.7 ms** | **53.9×** | 5.8× | **0.0** |
| 4,194,304 | 1378.2 ms | 149.8 ms | **24.5 ms** | **56.3×** | 6.1× | **0.0** |
| 16,777,216 | 4272.0 ms | 596.7 ms | **96.2 ms** | **44.4×** | 6.2× | **0.0** |

Load beside each row: 12.95 / 13.04 / 13.83 / 15.38.

### 7.2 — the same run, at 16 M points

| | time | throughput |
|---|---|---|
| Infinigen CPU (C++/OpenMP, 14 cores) | 4854.7 ms | 3.5 Mpoints/s |
| Infinigen CUDA (`malloc` + copy + kernel + copy) | 596.7 ms | 28.1 Mpoints/s |
| **Warp port (resident buffers)** | **96.1 ms** | **174.7 Mpoints/s** |

- **Warp vs Infinigen CPU: 50.5×**
- **Warp vs Infinigen CUDA: 6.2×**
- Infinigen's CUDA library vs Infinigen's own CPU path: **8.1×**

The input traffic is 201 MB of positions per call. The CUDA library `cudaMalloc`s
a position buffer and an sdf buffer and copies both ways **on every call**; on a
unified-memory box that is exactly the copy EXP A says you should not make.

### 7.3 — correctness: bit-identical, not "close enough"

```
max |warp - infinigen CPU| = 0.000000e+00   (sdf range -54.667..50.110)
mean |warp - infinigen CPU| = 0.000000e+00
fraction of points differing by > 1e-3: 0.000000%
fraction of points differing by > 1e-5: 0.000000%
```

Infinigen's own CUDA library agrees with its CPU library to **0.000e+00** as well,
so the reference pair is self-consistent and the Warp port is a third independent
implementation that lands on the same bits.

### 7.4 — the oracle and the bisect

Bit-exactness was not luck. `vendor/infinigen-terrain/oracle.cpp` is compiled from
**Infinigen's own headers** and prints the intermediates (the per-group frequency,
the Perlin value, the mask, the ramp, the slope, and every hash) for eight test
points. `scripts/exp7_port_debug.py` runs the same points through the Warp port
and prints them side by side, so a mismatch is attributed to a *specific step*
instead of "the sdf is different". Final state: **every intermediate matches, and
the worst |sdf difference| is 0.0.**

## 5. How to reproduce

```bash
cd ~/lm-wt/lab2
.venv/bin/pip install "warp-lang==1.18.0" "numpy<2.6"
.venv/bin/python scripts/exp_warp_terrain_port.py        # ~4 min
```

The bisect (needs `g++`):

```bash
cd vendor/infinigen-terrain && g++ -O2 -o oracle oracle.cpp
cd ~/lm-wt/lab2 && .venv/bin/python scripts/exp7_port_debug.py
```

Raw output: `results/exp-warp-terrain-port.txt`.

## 6. Verdict

**BREAKTHROUGH.** Three claims, each measured:

1. **The port is correct.** Bit-identical to Infinigen's own CPU and CUDA
   libraries over 16 M points (max |diff| = 0.0). The kill condition "kill it if
   the outputs differ" is **not** triggered.
2. **The port is fast.** 44–56× the CPU path, 6× Infinigen's own CUDA kernel.
   The kill condition "kill it if the existing CPU path is already under 1 s" is
   **not** triggered — the CPU path needs 4.3 s for 16 M points.
3. **Warp beats the spike's hand-written CUDA** by 6×, for a reason that is
   specific to this box: the hand-written path copies its input and output
   through `cudaMalloc`/`cudaMemcpy` on every call, and on a unified-memory Thor
   that copy is avoidable.

### What this changes for the plan

- **The procedural-stage rewrite is worth it** — and the spike's own CUDA kernel
  is not the endpoint. If the terrain elements are rewritten in Warp, they get
  bit-identical output *and* 6× the speed of the existing CUDA build, with no
  `nvcc`/arch-flag fragility.
- **Round 1's `nvcc` trap does not apply to the spike's current build.** The
  copied `mountains_cuda.so` contains **native sm_110 SASS and no PTX**:
  `cuobjdump --list-elf` → `mountains_cuda.1.sm_110.cubin`; `--list-ptx` → none.
  So the spike's build *does* pass an explicit arch flag, and rev-tech §C6's
  "nvcc defaults to sm_75" is a default, not a wall — worth correcting in the
  notes (see IDEAS.md).
- **A port of this size is a day of work, not a week**: the element is 60 lines
  of C, the port is one Warp kernel, and the oracle (compile Infinigen's own
  headers into a tiny program) turns "does it match?" into a 10-minute question.
  The oracle is the reusable artefact: it works for any element.

### The next step this suggests

Port the *rest* of the terrain elements with the same oracle harness
(`landtiles`, `warped_rocks`, `voronoi_rocks`, `caves`, `upsidedown_mountains`),
then the OcMesher's SDF evaluation (IDEAS.md idea #4), whose question is still
open: is the cost SDF evaluation or octree bookkeeping?

## 7. Failures that stayed

- **Two transcription errors in the hash chain, both invisible until the oracle
  existed.** Blender's `hash_bit_final` ends with `c -= hash_bit_rotate(b, 24)`
  — it rotates **b**, not c — and the middle of the chain is
  `b -= hash_bit_rotate(a, 25)`, not `rot(b, 25)`. Reading the header carefully
  and transcribing it by hand produced both errors; the symptom was a 7 % sdf
  error that looked like "float precision" and was not. **The fix was to stop
  transcribing and start compiling**: build a tiny oracle from Infinigen's own
  headers and diff the intermediates. That harness found both errors in minutes.
- **Warp's mutable variables inside `if` blocks are a trap.** A probe kernel that
  assigned `a` inside an `if/elif` chain returned a corrupted value
  (`0xdeafa148` instead of `0xdeafd03c`) and sent me hunting for a bug in the
  hash that did not exist. The port now uses `wp.where(...)` selects instead of
  branches for the `is_3d` z-zeroing and the spherical-radius choice.
- **FastNoiseLite's `FastFloor` is not `floor`.** It truncates toward zero and
  then subtracts one for negatives, so `FastFloor(-1.0) == -2`. The port
  reproduces that quirk exactly (`fast_floor`), because `floor()` and
  `FastFloor()` differ on every negative integer coordinate.
- The C++ `log_uniform` evaluates `exp(log(low) + …)` in **float** (C++'s float
  overloads), not double; the port had to match that exactly, because the
  frequency feeds a Perlin lattice and a 1-ULP difference in frequency is a
  visible difference in the noise.

## 8. Licence note

Infinigen is BSD-3-Clause (attribution kept in the copied headers, which are in
`vendor/infinigen-terrain/`). `blender_noise.h` is derived from Blender and is
GPL-2.0-or-later AND BSD-3-Clause — it is Infinigen's own copy and is reproduced
here only as an unmodified copy for the experiment. `warp-lang` (Apache-2.0),
`numpy` (BSD-3-Clause). Code only; no model weights, no shipped-asset
implications.
