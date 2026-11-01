# 06 — Partitioning: MIG, Green Contexts, and what admission actually costs

**Source:** `googl1.md` line 164 (MIG/partitioning as a design dimension), and
the brief's own framing of "Green Contexts" as one of the mechanisms. The
document's Green Contexts content is sparse — most of the substance comes from
the measurements in `docs/lab/exp-mig.md` and the `xp-batch` runs on the Thor.

## What it says

The document treats partitioning as a given: it repeatedly assumes the machine
can be divided into "16 compute + 4 memory" style partitions (MIG terminology)
and that this division is available to the runtime for scheduling live work
against a background sweep.

The interesting question the document does not ask: **if you divide the machine,
what does the division cost the latency of the part you care about?**

## What it means

On a shared Thor box, there is a background workload (a sweep, a model server,
another agent) and there is live work (an interactive or agent-driven query).
Two ways to give live work a guaranteed share:

- **MIG** — hardware isolation into fixed instances with their own memory.
  Strong isolation, but fixed partition geometry and a reboot to change it.
- **Green Contexts** — CUDA 13's in-process SM partitioning. The driver splits
  the SMs into groups; a green context is bound to one group; streams created
  in it can only be scheduled on those SMs. No reboot, no separate memory, and
  the primary context's address space stays shared, so buffers are not duplicated.

The question the document leaves open is the cost: if the live work is given
6 of 20 SMs, it gets 30% of the compute, and it also loses whatever memory
bandwidth the background is using — because Green Contexts partition *SMs*, not
DRAM. That last point is the crux and it is where the measurements are decisive.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor supports MIG | **confirmed, with a catch** | NVIDIA's "What's New in CUDA Toolkit 13.0 for Jetson Thor" documents MIG with 10 TPCs on AGX Thor. Measured on the box: MIG mode is present, `mig.mode` is `Disabled` by default and can be enabled |
| MIG instances on Thor are **compute-only** — no memory isolation | **confirmed** | `exp-mig.md`: `nvidia-smi mig -lgip` on this Thor reports `Memory: 0 MiB` for every profile (1g.6c, 2g.12c, 3g.20c, 4g.20c, 7g.20c) — `Enabled` for compute, `Disabled` for memory. Consistent with unified memory: there is no separate VRAM to partition. NVIDIA's own Thor MIG documentation says MIG on Thor provides compute partitioning |
| A MIG instance can be created on this box right now | **contradicted** | `exp-mig.md`: MIG mode enable fails with "in use" because the desktop session holds the GPU; instance creation fails with `Unknown Error`. Also note the profile list is coarse (6, 12, or all 20 SMs) — a 3g.20c profile is the whole device |
| MIG can be used as an admission primitive for live work on this box | **contradicted** | Same as above: it requires disabling the desktop and a reboot to change geometry. This is the concrete reason the `xp-batch` work went to Green Contexts instead |
| The Thor supports **Green Contexts** (`cuDevSmResourceSplitByCount`, `cuGreenCtxCreate`) | **confirmed** | Measured first-hand today under `thor-admit`: `SM resource: smCount=20 minSmPartitionSize=2 smCoscheduledAlignment=2`; a 4-SM group and a 16-SM backfill group were created; `cuGreenCtxGetDevResource` confirms **A = 4 SMs, B = 16 SMs**; concurrent 512×512 SGEMMs in both partitions overlapped **1.00** and computed the same A@B to max rel err **3.443e-06**. Independently, `xp-batch/gc_probe` recorded the same result at 06:55 today |
| Green Contexts share the primary context's address space | **confirmed** | `xp-batch/gc_probe.md`: "Device memory allocated in the primary context was read/written by kernels launched inside the green contexts with no copies and no errors." This is what makes them usable as an admission primitive rather than just an isolation toy |
| `cuGreenCtxStreamCreate` requires `CU_STREAM_NON_BLOCKING` | **confirmed** | `xp-batch/gc_probe.md` records `CUDA_ERROR_INVALID_VALUE` with `flags=0`; `CU_STREAM_NON_BLOCKING` succeeds |
| Modules are per-context for green contexts | **confirmed** | `xp-batch/gc_probe.md`: a module loaded in the primary context is not usable from a green context; `cuModuleLoadData` must be called again with each green context current |
| **A Green Context gives live work a latency win under load** | **contradicted** | This is the finding. From `sp_gc_half.json` (5 repeats × 4 conditions × 12 s windows, 1200 launches/window, medians): idle live GEMV p50 **0.117 ms**; under load with no split, **1** launch served in 1200 at 0.323 ms; under load with stream priorities, **1** launch served in 1200 at 0.210 ms; under load with the green split, **1195** served at p50 **0.737 ms**, p99 **5.418 ms**, dev p50 **562.3 µs** (vs 112.6 µs idle) |
| So: green split restores *service*, not *latency* | **confirmed** | The split is the only condition where live work is served at all (1195/1200 vs 1/1200). But the cost is real: p50 goes from 0.117 ms idle to 0.737 ms (6.3×), and p99 to 5.418 ms. Background bandwidth drops from 104 to 55 GB/s and copy traffic *rises* from 2.5 to 25 GB/s |
| Stream priority keeps live work responsive under load | **contradicted (structurally)** | `xp-batch/stream-priority.md` verdict: "fail — and the failure is structural". Both the same-priority and high-priority conditions served **1 launch out of 1200**. The priority range on this device is `[0 .. -5]` |
| The 1.2× p99 pass bar was met | **contradicted** | The stated bar was "high-priority p99 under load ≤ 1.2× idle p99" (idle p99 = 0.145 ms → bar 0.174 ms). Under the green split, p99 = 5.418 ms, i.e. **37× the bar**. The stream-priority path did not serve a single launch, so its p99 is not merely above the bar, it is undefined |

**The honest summary.** Green Contexts work on the Thor, and they are the only
one of the three mechanisms that keeps live work running at all under load.
But they are a *service* guarantee, not a *latency* guarantee: partitioning SMs
does not partition DRAM, so the live kernel still contends for memory bandwidth,
and the 6.3× p50 / 37×-of-bar p99 is the price. Stream priority does not work
at all on this device.

This is the correction the first-pass research note
(`docs/research/googl1.md`) was reaching for when it marked Green Contexts
"Untested — we have not called the API". It is now tested.

## Judgement

**Green Contexts are worth adopting as a *floor*, not as a *latency* mechanism.**
This is the most useful single result in the digest.

Stock JetPack, today:

- **Adopt Green Contexts as the admission primitive for live work against a
  background sweep.** The alternative is stream priority, which serves 1 launch
  in 1200. That is not a tuning problem; it is a dead end on this driver.
- **Set expectations from the measurement, not from the hope.** If the live path
  has a latency budget, a green split under a heavy background will not meet a
  1.2×-of-idle bar. If the requirement is "live work is served at all, with a
  bounded tail", a green split delivers that and priority does not.
- **Prefer not to run a memory-bandwidth-hungry background at all.** The
  background's 55 GB/s under the green split is what inflates the live p99. If
  the background were bandwidth-light, the split would look far better. This
  is a *policy* lever (what runs on the box, and how much bandwidth it takes)
  and it is worth more than the partitioning mechanism itself.
- **Do not use MIG for this.** It is compute-only on this machine, it needs the
  desktop off, and instance creation fails today.

Needs OS/firmware changes, which nothing does without Casey:

- Nothing for Green Contexts — all of this is stock CUDA 13.2, verified on the
  box today with driver 595.78 / CUDA 13.2.
- Enabling MIG on this shared box does need the desktop off and a reboot, which
  is an operational decision about the box, not a firmware change.

**What we would measure.** For any live/background split we adopt, measure and
record: live p50/p99 and device-side duration, launches served out of N, background
bandwidth, and copy bandwidth — the same five columns `sp_gc_half.json` already
records. That harness exists and should become the standing regression test for
anything we schedule on the Thor.

**Cost:** low. The mechanism is a dozen lines of driver API. The discipline of
running the measurement is the real cost, and it is the same discipline that
would have caught the priority failure before we depended on it.
