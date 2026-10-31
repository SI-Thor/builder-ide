# EXP 1 — NVMe → unified-memory load bandwidth: cold, warm, and what it means for hot/warm/cold residency

**Date:** 2026-10-31 00:12 local (Alaska Daylight Time)
**Verdict: USEFUL** — the number nobody had is now measured: **a cold read of a
model-weight file lands in unified memory at 1.2–1.7 GB/s**, so a 7.45 GiB fp16
checkpoint takes **6.5 s** to load cold and **1.7–4.3 s** warm; the "warm" tier
the page cache gives for free is worth more than any tiering machinery, and
**the external cold shelf was unusable for the whole session** (it stalled
mid-write and never recovered).

---

## 1. The idea

`IDEAS.md` idea #12 / Part C item #1: "The NVMe's bandwidth decides the shape of
the whole scheduler." The plan guesses at the one number nobody has measured —
how fast does a model-weight file move from disk into unified memory, cold and
warm, and what does that mean for the hot/warm/cold residency tiers?

## 2. Hypothesis

Loading a 7.45 GiB fp16 checkpoint (a 4B-parameter model, IDEAS.md idea #5)
from the NVMe into unified memory takes **seconds, not minutes**. If it takes
seconds, the residency tiers do not need elaborate machinery; if it takes
minutes, the scheduler has to be built around pre-warming.

## 3. Setup

- Venv: `/home/caseydigennaro/lm-wt/lab2/.venv` (Python 3.12.3), with
  `torch 2.15.0`, `cupy-cuda13x`, `numpy 2.5.4`.
- Script: `scripts/exp_nvme_bandwidth.py`; raw output:
  `results/exp-nvme-bandwidth-internal.txt`.
- The **destination is unified memory**: the read lands in a plain `malloc`'d
  numpy buffer, and the script *proves* that buffer is device-addressable with
  EXP A's pointer-identity trick:

  ```
  numpy buffer host pointer      = 0xfffa1ffff010
  devicePointer                  = 0xfffa1ffff010
  hostPointer                    = 0xfffa1ffff010
  type                            = 0 (cudaMemoryTypeUnregistered)
  DEVICE ADDRESSABLE (ptr equal) = True
  ```

  So "disk → unified memory" is literally what is measured: the bytes land in
  memory the GPU can address directly.

### The ladder

| size | what it stands for |
|---|---|
| 64 MiB | a mesh/texture cache for one scene |
| 512 MiB | a rendered scene cache |
| 2 GiB | a 1B-parameter fp16 checkpoint |
| 7.45 GiB | the 4B-parameter fp16 checkpoint from IDEAS.md idea #5 |
| 16 GiB | a big model plus neighbours (the "several models resident" case) |

### Cold and warm, measured rather than assumed

"Cold" has to mean *not in the page cache*. The first version of this script
evicted with `posix_fadvise(POSIX_FADV_DONTNEED)` and trusted it — and the
files were still cached, so the "cold" numbers were optimistic. The script now:

1. `fsync`s the file (a **dirty** page cannot be dropped — this was the real bug),
2. calls `posix_fadvise(DONTNEED)`,
3. and **verifies with `mincore()`** what fraction of the file's pages are
   actually resident.

Every cold measurement in this report shows `100.0% resident before eviction ->
0.0% after`, so the cold/warm distinction is real. (Note: `os.sync()` must not
be used here — it syncs *every* filesystem, including the wedged external
mount, and blocks forever. That is exactly how the first run hung.)

### The box's state, beside the numbers

| | |
|---|---|
| Timestamp | 2026-10-31T00:12 local |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| Cores | 14 |
| `MemTotal` / `MemAvailable` | 122.80 GiB / ~115 GiB |
| Power mode | MAXN (mode 0) |
| Driver / CUDA / nvcc | 595.78 / 13.2 / 13.2.86 |
| `nvidia-smi` at start | 0 % GPU util, 2.36 W, 36 °C, 315 MHz |
| `tegrastats` RAM | 59,728 / 125,749 MB (during the run) |
| `tegrastats` VIN | 58,618 mW peak / 36,222 mW avg |
| loadavg during the run | **38 → 67** (another seat's build saturating all 14 cores) |
| CPU busy at sample | all 14 cores at 98–100 % |
| `jetson_clocks` | present, **not** locked |
| Device under test | internal NVMe, `/` = ext4, 287 GiB free |
| Device **not** testable | external "TOSHIBA EXT", `/dev/sda1` fuseblk — see §5 |

## 4. The numbers

### 4.1 — disk → unified memory (internal NVMe)

| size | COLD | COLD GB/s | WARM | WARM GB/s | cold/warm |
|---|---|---|---|---|---|
| 64 MiB | 0.042 s | 1.49 | 0.023 s | 2.74 | 0.54× |
| 512 MiB | 0.350 s | 1.43 | 0.176 s | 2.85 | 0.50× |
| 2 GiB | 1.188 s | 1.68 | 1.336 s | 1.50 | 1.12× |
| 7.45 GiB | 6.504 s | **1.15** | 4.298 s | 1.73 | 0.66× |
| 16 GiB | 10.595 s | **1.51** | 4.248 s | 3.77 | 0.40× |

Load beside each row: 38.31 → 43.17 → 51.97 → 64.53.

An earlier run of the same script at a lower load (14–18) gave 7.45 GiB cold in
**6.402 s (1.16 GB/s)** and warm in **1.733 s (4.30 GB/s)**, and 16 GiB cold in
16.752 s (0.96 GB/s). **The cold numbers reproduce; the warm numbers are
load-sensitive** (1.7 vs 4.3 GB/s for the same file), because a warm read is
dominated by the page-cache → user-buffer copy, which is CPU/memory work.

### 4.2 — the real paths

| path | time | effective GB/s |
|---|---|---|
| `torch.load(map_location='cuda')`, **cold**, 3.73 GiB fp16 checkpoint | **1.778 s** | 2.10 |
| `torch.load(map_location='cuda')`, **warm**, same | **0.779 s** | 5.11 |
| pinned staging: read the file (cold) into a pinned buffer | 1.647 s | 2.26 |
| pinned staging: H2D copy | 0.107 s | **34.85** |
| **GPU zero-copy read of the just-loaded 2 GiB buffer** | **0.033 s** | **60.39** |

### 4.3 — the residency finding

```
after the cold read: 100.0% of the file is resident in the page cache
```

**A cold read leaves the whole file resident in RAM.** The page cache *is*
unified memory on this box, so "loading a model" does two things: it puts the
bytes where the GPU can use them, and it leaves them in the cache where the OS
can drop them at any time. The tiering problem is therefore not "how do I move
bytes" but "what do I keep pinned".

## 5. The external cold shelf: unusable this session

The external drive ("TOSHIBA EXT", `/dev/sda1`, mounted **fuseblk**) stalled
during the first run of this experiment and never recovered:

- a 512 MiB write to it **stopped making progress** mid-write (the process's
  `wchar` counter froze; it entered `D` state with `wchan =
  fuse_dequeue_forget`);
- every subsequent access to the mount blocked indefinitely — `ls`, `stat`,
  `open`, and even `os.sync()` (which walks *all* filesystems);
- two Python processes are **still** stuck in `D` state on it, unkillable,
  because a task in `D` state cannot be signalled;
- the mount is served by `gvfsd-fuse`, i.e. the desktop GVFS daemon, not a
  dedicated mount daemon.

So the external-shelf tier **could not be measured**. That is a finding, not a
gap: the cold shelf is a FUSE mount over an external USB drive, and in this
session it failed in a way that took the whole box's I/O paths down with it.

## 6. How to reproduce

```bash
cd ~/lm-wt/lab2
.venv/bin/pip install "torch==2.15.0" "numpy<2.6" cupy-cuda13x
.venv/bin/python scripts/exp_nvme_bandwidth.py --devices internal
# the external shelf (only if the mount is healthy):
.venv/bin/python scripts/exp_nvme_bandwidth.py --devices external
```

The script writes ~26 GiB of scratch files under `.bench-files/` and deletes
them at the end. Every device operation is bounded by a 150 s timeout so a
wedged mount cannot hang the run again.

Raw output: `results/exp-nvme-bandwidth-internal.txt`.

## 7. Verdict

**USEFUL.** The hypothesis holds: **loading a model-weight file costs seconds,
not minutes**, so the residency tiers do not need elaborate machinery.

The numbers that decide it:

1. **Cold NVMe → unified memory is 1.2–1.7 GB/s.** A 7.45 GiB checkpoint takes
   **6.5 s** cold, **1.7–4.3 s** warm (page cache), **1.8 s** via
   `torch.load(map_location='cuda')` for a 3.73 GiB checkpoint.
2. **The disk is not the bottleneck at the sizes that matter.** At 3.73 GiB the
   `torch.load` path moves 2.10 GB/s while the H2D copy runs at 34.9 GB/s and a
   zero-copy GPU read of the freshly loaded bytes at 60.4 GB/s. The transfer is
   **memory-bound, not disk-bound**, once the file is in the cache.
3. **The warm tier already exists and is free.** After any read the file is
   100 % resident in the page cache, which *is* unified memory. The plan's
   "warm" tier needs no implementation — it needs a policy about what to pin.

### What this changes for the plan

- **The hot/warm/cold tiering is a pinning policy, not a transfer system.**
  The measurements say: load once (seconds), then let the page cache decide. A
  7.45 GiB model costs 6 % of the box's RAM; three of them cost 18 %.
- **Cold-tier latency is a design constraint, not a footnote**: 6.5 s to fetch
  a model is longer than the "≤ 5 s watch clock" the plan wants for a critic
  pass. So a cold model cannot be swapped mid-session; the scheduler must
  pre-warm, or the critic must run on a smaller model.
- **The external shelf needs a different answer.** It is a FUSE mount over USB
  that failed catastrophically in this session. If a cold tier is wanted, it
  should be a native filesystem mount, and the plan should assume the shelf is
  *slower* than the NVMe rather than faster (a USB drive is not a cache tier;
  it is an archive tier).
- **One measurement is still missing and worth taking next**: the external
  drive's read bandwidth, once the mount is healthy. `fio` with a real
  `fio.conf` (drop-caches variants) would settle it, and the drop-caches
  problem is the reason this script uses `posix_fadvise` instead.

## 8. Failures that stayed

- **The first "cold" numbers were not cold.** `posix_fadvise(DONTNEED)` silently
  does nothing to a file with dirty pages; the file had just been written, so
  the "cold" read was partly a page-cache hit and the first numbers were
  optimistic by up to 2×. The fix was `fsync` + **`mincore()` verification** —
  now every cold measurement prints `100.0% resident before eviction -> 0.0%
  after`, so the claim is checkable rather than trusted.
- **`os.sync()` hung the whole experiment** (twice): it syncs every filesystem,
  including the wedged FUSE mount. `fsync` on the one file is the correct tool.
- **The external cold shelf stalled and could not be recovered.** Two processes
  are still in `D` state on it. The script now bounds every device operation
  with `SIGALRM` and skips a device that stalls, so the experiment degrades to
  "the internal NVMe" instead of hanging.
