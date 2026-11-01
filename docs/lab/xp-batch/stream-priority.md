# stream-priority: does stream priority keep a UX kernel responsive under load? (idea4 E2)

Run: 2026-11-01 06:49-07:23 and 07:39-07:45 (final dataset `sp_gc_half.json`:
5 repeats x 4 conditions x 12 s windows, live launch every 10 ms = 1200
launches/window, medians across repeats). Box: NVIDIA Thor sm_110, CUDA 13.2
(driver 13020), 20 SMs, max 1536 threads/SM, L2 32 MB, MemAvailable 76.5 GB,
co-tenant night-v3.heavy active throughout (GPU util dipped in and out; power
47-66 W, 63-66 C). Clocks: `nvidia-smi` reports [N/A] on Thor (cannot lock;
jetson_clocks needs sudo) — DVFS warmed by a 3 s full-GPU spin + per-window
1 s background warm before measurement. Priority range
`cuCtxGetStreamPriorityRange` = [0 (default) .. -5 (highest)].

## Question

Does a small live kernel (a d1-sized GEMV: 2048x2048 fp32 weights, warp-per-row,
4 passes = 67 MB read, ~113 us idle on 20 SMs) keep its p50/p95/p99 while a
long background loop runs, when the live kernel runs on a high-priority stream
and the background on a low-priority one? Pass bar: high-priority p99 under
load <= 1.2x idle p99.

## Method and guards

Background = persistent grid-stride streaming kernel (2 GiB working set = 64x
L2, self-terminating by device timer, no inter-kernel gaps) launched on a
lowest-priority stream; live GEMV on the highest-priority stream; both sizes
chosen so the live grid fits in the slots the background leaves free. Device
duration per launch from `%globaltimer` in-kernel (floor: empty-launch event
pair 2.5 us; live idle 45x the floor). Idle / load-at-default / load-at-high
priority measured side by side with the green-context split (see
green-contexts.md).

## Numbers (medians across 5 repeats)

| condition | launches served per 1200 | ev p50 | ev p99 | dev p50 | dev p99 | bg GB/s |
|---|---|---|---|---|---|---|
| idle (no load)            | ~1198 | 0.117 ms | 0.145 ms | 112.6 us | 139.2 us | 0 |
| load, same priority       | **1** | 0.323 ms | 0.323 ms | 179.5 us | 179.5 us | 104 |
| load, live=-5 / bg=0      | **1** | 0.210 ms | 0.210 ms | 196.1 us | 196.1 us | 109 |

## Verdict: fail — and the failure is structural

**Stream priorities do not keep a live kernel responsive under a persistent
loop on this box.** Per-launch service collapses to a single completion per
12 s window in the loaded conditions: the first live launch co-runs fine
(its device duration, 180-196 us, is only 1.6x idle), and after that the
second and all later launches never complete until the background kernel
ends. The mechanism is not queueing (which priorities address) — it is
**co-scheduling**: CUDA stream priorities "do not preempt already-running
work" (documented in cuda.h), and on sm_110 the work distributor does not
admit later same-context kernels into the slots a persistent kernel leaves
free, at any occupancy we tested (100%, 50%, 33% of 1536 threads/SM), with
or without a concurrent copy-engine load, for live grids of 20-80 blocks
(kernels of 22 us and of 113 us idle duration alike).

A minimal independent repro (20-block live kernel, 5 launches at 10 ms
cadence on a second stream) *does* interleave — first launch 0.6-5.9 ms,
later ones 1-4 ms — so same-context co-scheduling is not categorically
broken; it fails exactly for the persistent-background + periodic-live
pattern this spec asks about.

Consequences for the design question behind the spec:
- Priority-only isolation is unusable against a *persistent* background loop
  on this box. It can only reorder queued work.
- A live path that must survive a background loop needs either a different
  context (Green Contexts — see green-contexts.md: sustained 1195/1200
  launches) or a background that yields (bounded kernels, not persistent).

## Caveats

- The one sample per loaded window is survivorship bias: it is the launch
  that got in before the door closed. p50/p95/p99 "under load" are not
  measurable in that regime — which is itself the finding.
- ncu is not installed (`command -v ncu` empty), so lts/dram counters are
  not available; background saturation is evidenced by achieved read
  bandwidth (104-109 GB/s under the co-tenant's competing traffic;
  247 GB/s measured quiet) and by the collapse of the concurrent copy
  stream to ~2.5 GB/s during loaded windows.
- Clock state unrecordable (see above); temperatures 63-66 C, power 47-66 W
  during loaded windows (in-kernel `%globaltimer` spans, `nvidia-smi` samples).
