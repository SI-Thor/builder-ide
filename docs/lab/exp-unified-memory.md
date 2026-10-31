# EXP A — unified memory: a 4 GB buffer moves between NumPy, PyTorch-CUDA and a CUDA kernel with no copies

**Date:** 2026-10-30 22:56 local (Alaska Daylight Time)
**Verdict: BREAKTHROUGH** (with one trap that will bite the port — see A4)

---

## 1. The idea

One shared scene in unified memory: Blender/bpy, the generators (PyTorch) and the critic
read and write the *same* buffers, with no copies and no file round-trips
(`IDEAS.md` idea #2). The Thor's claim is that its 122 GB is one pool shared by CPU and GPU.
The question this experiment answers is not "is there unified memory" but:

> can a buffer that **NumPy owns** be handed to a **CUDA kernel** and to **PyTorch** with
> zero copies, and what does that actually buy in bandwidth and in memory?

## 2. Hypothesis

On the Thor, memory returned by the host's `malloc` (what NumPy uses) is *device-addressable*
under CUDA's unified virtual addressing: `devicePointer == hostPointer`. Therefore a NumPy
array can be wrapped — not copied — as a device array, a kernel can read **and write** the
exact pages NumPy owns, and the "zero-copy" path should cost no extra bandwidth versus a
device-resident buffer, while eliminating the copy and the second allocation entirely.

## 3. Setup

- Venv: `/home/caseydigennaro/lm-wt/lab1/.venv` (Python 3.12.3). Nothing outside this
  directory was touched: no system packages, no other venv, no `~/src/infinigen-thor`, no
  services.
- `torch 2.15.0+cu132` (PyPI aarch64 wheel, 483.7 MB — the CUDA 13.2 aarch64 build rev-tech
  predicted), `cupy-cuda13x 14.2.0`, `numpy 2.5.4`.
- Device: `NVIDIA Thor`, compute capability `(11, 0)` = sm_110.
- Script: `scripts/exp_unified_memory.py`; raw output: `results/exp-unified-memory.txt`.
- Buffer: 1,073,741,824 float32 = **4.0 GB**.

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-30T22:56:10-0800 |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / 113.88 GiB |
| Power mode | `nvpmodel`: **MAXN** (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` at start | 0 % GPU util, 2.36 W, 31 °C, 315 MHz |
| `tegrastats` RAM | 48,661 / 125,749 MB |
| `tegrastats` VIN | 30.28 W peak / 16.38 W avg |
| loadavg (1/5/15) | 5.26 / 6.43 / 6.12 |
| CPU busy at sample | cores 4 and 5 at 58 % / 43 % (another seat's `cmake` build) |
| `jetson_clocks` | present, **not** locked |

The box was not idle: another seat's build was using ~2 of the 14 cores for the whole run.
Every number below is from the GPU path, which was idle (0 % util) throughout.

## 4. The numbers

### A1 — pointer identity

| Step | Pointer | Shares storage? |
|---|---|---|
| NumPy array | `0xfffb88fbf010` | — |
| `torch.from_numpy(arr)` | `0xfffb88fbf010` | **yes — same pages** |
| `.cuda()` | `0xfffa60000000` | no — **copied** to device memory |
| `cupy.from_dlpack(torch_cuda_tensor)` | `0xfffa60000000` | **yes — same pages** |
| `torch.from_dlpack(cupy_array)` | `0xfffa60000000` | **yes — same pages** |

`cudaPointerGetAttributes` on the NumPy buffer:

```
type = 0 (cudaMemoryTypeUnregistered)
devicePointer = 0xfffb88fbf010
hostPointer   = 0xfffb88fbf010      <- device pointer == host pointer
device        = -1
```

**The host's plain `malloc` memory is already a valid device address on this Thor.**

### A2 — the decisive test: a CUDA kernel mutates NumPy's memory in place

The NumPy buffer was wrapped with `cupy.cuda.UnownedMemory` + `MemoryPointer` (no
allocation, no copy), and a kernel wrote `(i % 1000) * 1.5` into it.

```
numpy after kernel wrote      = [ 0.   1.5  3.   4.5  6.   7.5  9.  10.5 12.  13.5]
expected                      = [ 0.   1.5  3.   4.5  6.   7.5  9.  10.5 12.  13.5]
probe indices checked         = [0, 1, 2, 998, 999, 1000, 1001] ... [1073741823]
MATCH (numpy sees GPU writes) = True
```

Probe indices cover the pattern's wrap at 1000 and the very last element of the 4 GB
buffer, so this is not a head-of-buffer coincidence. Separately, a CUDA buffer obtained
from PyTorch via DLPack was written through CuPy and read back through PyTorch — **True**.
One buffer, three libraries, no copy in either direction.

### A3 — effective bandwidth vs a copy (4 GB)

| Path | Time | Effective |
|---|---|---|
| (a) explicit H2D copy into a device buffer | 45.57 ms | 87.79 GB/s |
| (a) read the device copy in a kernel | 39.63 ms | 100.93 GB/s |
| **(b) zero-copy read of NumPy's buffer** | **39.66 ms** | **100.87 GB/s** |
| (b) zero-copy **write** into NumPy's buffer | 54.55 ms | 73.33 GB/s |
| copy + read (a), total | 85.20 ms | — |
| **zero-copy (b), total** | **39.66 ms** | — |

- **Speedup of "copy then read" over zero-copy: 2.15×.**
- Checksums identical between the two paths: `3221225472.0` vs `3221225472.0` — the
  zero-copy kernel really read all 4 GB.
- Copy reps: `[45.0, 45.6, 46.0] ms` (stable; an earlier variant that also *allocated*
  a fresh 4 GB device buffer each call showed the allocator's cost separately:
  `[2767.4, 296.5, 297.8] ms`).

**The important reading: the zero-copy path is not faster per byte — it is the same
100 GB/s read.** There is no "unified memory bandwidth penalty" to engineer around. What
the zero-copy path removes is the *copy* and the *second 4 GB allocation*, which is why
copy+read costs 2.15× more.

### A4 — PyTorch's own copy cost (the trap)

| Path | Time | Effective |
|---|---|---|
| `torch.from_numpy(arr).cuda()` (pageable) | 46.26 ms | 86.46 GB/s |
| **`t_gpu.cpu()` (pageable destination)** | **11,900.59 ms** | **0.34 GB/s** |
| `pinned.copy_(t_gpu)` (pinned destination) | 45.55 ms | 87.82 GB/s |
| `t_gpu.copy_(pinned)` (pinned source) | 45.63 ms | 87.66 GB/s |

**`.cpu()` into pageable memory ran at 0.34 GB/s — 258× slower than the pinned path, and
11.9 seconds for 4 GB.** The cause is not the interconnect: it is that every `.cpu()`
allocates a fresh 4 GB host tensor, so the destination pages are faulted in and zeroed on
every call. The pinned path moves the same 4 GB in 45.55 ms.

This is a trap the port must avoid: a naive "pull the render back to the CPU" loop looks
like a working system that is 258× slower than it should be, and it never fails — it just
takes eleven seconds.

### A5 — the whole chain

```
numpy -> torch -> cupy -> GPU write -> numpy : True
pointers identical along the chain: numpy=0xfff69ffff010 torch=0xfff69ffff010 cupy=0xfff69ffff010
-> torch CPU tensor sees the GPU's write too: True
```

## 5. How to reproduce

```bash
cd ~/lm-wt/lab1
.venv/bin/python scripts/exp_unified_memory.py          # ~2 min, needs ~13 GB RAM
```

Rebuild the venv from scratch with:

```bash
python3 -m venv .venv
.venv/bin/pip install "torch==2.15.0" "numpy<2.6" cupy-cuda13x warp-lang
```

Raw output: `results/exp-unified-memory.txt`. The script was re-run from scratch after
this file was written: the zero-copy match and the full chain both reproduced `True`,
the copy+read speedup re-measured at 2.13× (vs 2.15×), zero-copy read at 100.13 GB/s
(vs 100.87) and the copy at 88.51 GB/s (vs 87.79) — i.e. the bandwidth relationship is
stable, the absolute numbers move by ~1 %.

## 6. Verdict

**BREAKTHROUGH.** The Thor's unified memory is not a marketing claim on this box — it is a
directly usable property:

1. A NumPy buffer is a valid device address. A kernel can read and write NumPy's pages
   in place, and NumPy sees the result. Verified, not inferred.
2. PyTorch ↔ CuPy share one buffer through DLPack with identical pointers, in both
   directions. The "one shared scene" idea needs no copy engine at all.
3. Zero-copy costs nothing in bandwidth (100.87 vs 100.93 GB/s) — so there is no reason
   to copy "for speed". It costs nothing because it *is* the same memory.
4. The win is 2.15× on the measured copy+read path, and — larger than the time saving —
   **the second 4 GB allocation disappears**. A 4 GB scene and a 4 GB model can now be
   resident at once, which is what the scheduler's residency model needs.

### What this changes for the plan

- The "one shared scene in unified memory" idea moves from *speculative* to *demonstrated*.
  The mechanism is DLPack between PyTorch and CuPy, plus wrapping a host pointer with
  `cupy.cuda.UnownedMemory` / `wp.array(ptr=..., copy=False)` (see EXP B) for the NumPy leg.
- **Rule for the port: never call `.cpu()` on a large tensor into pageable memory.**
  Use a pinned staging buffer, or — better — don't copy at all: hand the device pointer
  to the consumer.
- The memory-scheduler consequence needs care: because the pool is unified, a GPU buffer
  and a CPU buffer are the *same* bytes. `nvidia-smi` cannot report either (rev-tech C9),
  so residency accounting must come from `/proc/meminfo` and `tegrastats`.

## 7. Licence note

Everything installed here is code only, no model weights: torch (BSD-3-Clause), cupy
(MIT), numpy (BSD-3-Clause), warp-lang (Apache-2.0). No shipped-asset licence implications.

## 8. Failures that stayed

- `cupy.cuda.runtime.pointerGetAttributes` rejects a `ctypes.c_void_p`; it wants a plain
  `int`. The CuPy attribute names are `devicePointer` / `hostPointer` / `type` / `device`
  (not the CUDA C names).
- `torch.utils.dlpack.to_dlpack(cpu_tensor)` cannot be consumed by CuPy:
  *"CuPy is built against CUDA, different from the backend that backs the incoming DLPack
  tensor."* CPU→GPU sharing must go through the raw-pointer route, not DLPack.
- `cupy.ndarray` has no `.zero_()`; it is `.fill(0)`.
- The first "MATCH = False" was **my** bug, not the hardware's: I compared the tail of the
  4 GB buffer against the head pattern, but the kernel's pattern wraps every 1000
  elements. The data was correct; the assertion was wrong.
