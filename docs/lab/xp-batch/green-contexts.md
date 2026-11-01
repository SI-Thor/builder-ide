# green-contexts: SM partitions inside a process on the Thor (seed 164)

Run: 2026-11-01 07:39-07:45 (final dataset `sp_gc_half.json`), measured side
by side with stream-priority (same harness, same windows; see
stream-priority.md for box state: sm_110, CUDA 13.2 driver 13020, 20 SMs,
max 1536 threads/SM, MemAvailable 76.5 GB, co-tenant active, clocks [N/A]).

## Question

Does a CUDA 13.2 Green Context split (`cuDevSmResourceSplit`,
`cuGreenCtxCreate`) give live work an isolated SM share on the Thor with the
desktop up — i.e., sustained per-launch service under a persistent background
loop — and at what latency cost?

## Setup

- Split: 6 live SMs + 14 background SMs (`smCoscheduledAlignment = 2`,
  `minSmPartitionSize = 2`; live group 6 = 3x2, background group 14 with the
  BACKFILL flag). `cuGreenCtxGetDevResource` confirms 6 and 14.
- Live GEMV (d1-sized, 67 MB read/launch, 113 us idle on 20 SMs) launched
  every 10 ms into the 6-SM context; persistent streaming background (2 GiB
  working set, half the SMs' thread slots) in the 14-SM context; continuous
  pinned H2D/D2H copy traffic (22-35 GB/s) alongside, in every loaded
  condition (the copy engines cannot be partitioned — that is the point of
  the test).
- Background working set 64x L2 (shared-L2 guard); background bandwidth
  measured in-kernel; live kernel duration measured on-device
  (`%globaltimer`); correctness checked against a host reference in every
  window (max rel err 2.25e-06, identical for primary and green launches —
  green contexts share the primary context's address space).

## Numbers (medians across 5 repeats, 1200 launches per window)

| condition | launches served | ev p50 | ev p99 | dev p50 | dev p99 | overlap | bg GB/s | copy GB/s |
|---|---|---|---|---|---|---|---|---|
| idle                | ~1198 | 0.117 ms | 0.145 ms | 112.6 us | 139.2 us | —    | 0     | 0    |
| load, no split      | **1** | 0.323 ms | 0.323 ms | 179.5 us | 179.5 us | 0.00 | 104   | 2.5  |
| load, priorities    | **1** | 0.210 ms | 0.210 ms | 196.1 us | 196.1 us | 0.00 | 109   | 2.6  |
| load, green split   | **1195** | 0.737 ms | 5.418 ms | 562.3 us | (see below) | **1.00** | 55 | 25 |

(`dev` p95/p99 in the split window are bimodal: 673 us in three repeats,
~3.2-5.3 ms in two — the DRAM is shared with the copy stream and the
co-tenant; GPU utilization sampled 97-98% during split windows.)

## Verdict

**Isolation: yes, unambiguously. The strict pass bar: no.**

- The split is the only mechanism of the three that sustains per-launch
  service under a persistent background loop: 1195 of 1200 launches served
  at the 10 ms cadence, device-side overlap 1.00, for the whole 12 s window,
  every repeat — while the same-context conditions collapse to 1 launch
  (stream-priority.md).
- The spec's bar — split p99 <= 1.2x idle p99 — **fails**: the live
  partition's p50 is ~6x idle (0.74 ms vs 0.117 ms event; 562 us vs 113 us
  device). Two causes, both measured: (a) the live context has 6 of 20 SMs,
  and the GEMV is not bandwidth-bound enough to hide the partition (the
  isolated 6-SM GEMV alone is already ~148 us vs 55 us on 20 SMs, ~2.7x);
  (b) L2 and DRAM are unpartitioned — the background streams 55-76 GB/s and
  the copy engines 22-35 GB/s through the same memory system as the live
  kernel.
- With the desktop compositor up (Xorg + gnome-shell hold the display), the
  split creates and runs normally; MIG remains disabled (not attempted, per
  the box rules).

## Reading for the design decision

Green contexts convert "live work under a background loop" from
unpredictable (one completion per window) to bounded and predictable
(p50 0.74 ms, p99 ~5 ms, every launch served). Whether that trade is worth
it depends on the live path's budget: if 0.74 ms p50 is acceptable, the 6/14
split is the only working isolation on this box; if the budget is the idle
latency itself, no SM partition of 6/20 can deliver it for a
compute-latency kernel — the budget must buy more SMs in the live partition
(at the background's expense) or accept the bandwidth-sharing cost.

## Unsupported paths (verbatim)

- `cuGreenCtxStreamCreate(..., flags=0, ...)`: CUDA_ERROR_INVALID_VALUE —
  `CU_STREAM_NON_BLOCKING` is required.
- Modules are per-context; each green context needs its own
  `cuModuleLoadData`.
- `nvidia-smi` per-process memory / clock queries: "Not Supported" or
  minutes-long hangs under load (bounded with `timeout 10`).
- `ncu`: not installed.
