# XP-SUMMARY — xp-batch on the Thor, morning of 2026-11-01

Box for all runs: NVIDIA Thor sm_110 (cc 11.0), CUDA 13.2 driver/runtime 13020
(595.78), 20 SMs (max 1536 threads/SM), L2 32 MB, 122 GB unified DRAM
(~250 GB/s streaming reads, 433-451 GB/s D2D), 14 Neoverse-V3AE cores. Clocks
not lockable from this seat (nvidia-smi reports [N/A]; jetson_clocks needs
sudo). All runs under `thor-admit` (study tier, labels xp-batch.*). Box was
co-tenanted throughout (night-v3.heavy 40G lease, llama-servers, coldshelf
chain); the first half of the morning the admission queue was closed behind a
56-58G `serve.glide` promise (runs went when its seat switched glide to CPU and
the lease died — details in results/*.md context). ncusight/ncu not installed;
per-process GPU memory queries hang intermittently (bounded with `timeout 10`).

| spec | verdict (one line) | key numbers |
|---|---|---|
| stream-priority | **Fail — structural**: under a persistent background loop, per-launch live service collapses to ~1 completion/12 s window; priorities cannot help (they do not preempt resident work) | idle dev p99 139 us; loaded: 1/1200 launches served, both at default and at -5/0 priorities; independent repro shows small-grid pairs interleave (1-6 ms) |
| green-contexts | **Isolation works, strict bar fails**: 6+14 SM split sustains 1195/1200 launches at 10 ms cadence with overlap 1.00, but p50 is ~6x idle (6/20 SMs + shared DRAM with 25 GB/s copies and a streaming bg) | split ev p50 0.74 ms vs idle 0.117 ms; same-context conditions collapse to 1/1200; correctness 2.25e-06; API SUPPORTED (CU_STREAM_NON_BLOCKING required for green streams) |
| l2-persist | **Fail (0.98x vs 1.15x bar)**: persistence window accepted (24 MB limit, 16 MB window) but no effect; hot buffer never L2-resident even idle (319 GB/s = DRAM class) | hot+cold 207.1 GB/s -> 203.8 with window |
| persistent-queue | **Pass, decisive**: resident kernel + pinned ring: p50 3.01 us / p99 5.41 us CPU-enqueue-to-result at 314 k jobs/s (rel err 2.4e-08); torch graph path 35 us p50; driver-API graphs hang (verbatim below) | mapped pinned coherent both ways (single-thread probe); plain-launch mapped writes stall after job 1 (verbatim) |
| d1-batching-proxy | **Fail, narrowly**: batch16 vs batch1 = 2.75x with graphs (bar 3.0x); graphs don't help (no launch bottleneck; SDPA-under-capture suspected at batch 128 where graph is 2.1x slower) | 351.7 items/s at batch 16 (graphs); peak 17.3 GiB < 20; spec's dims give 407 M params, not 2 B |
| gc-probe | **Pass — SUPPORTED**: 4+16 SM partitions created and verified; concurrent matmuls overlap 1.00, identical results (3.4e-06); green contexts share the primary address space | smCount 20, minSmPartitionSize 2, alignment 2 |
| room-propagation | **Pass**: room delivers in-radius events at tick 0-1 (100%) at 6-7% of broadcast bandwidth; decay matches power-iteration rho to <0.15% for 0.85<=rho<=1.05; stability edge at rho=1 confirmed by divergence; room echo finite where broadcast diverges | N=64/512/4096; rho-normalized sweep 0.70-1.40 (raw absorption doesn't reach the stability edge — normalization required) |

Mechanism findings worth carrying forward:

1. **sm_110 same-context co-scheduling**: a persistent kernel starves later
   same-context kernels regardless of stream priority, occupancy (33-100%),
   kernel size (22 us-113 us), or copy load; the first launch co-runs, the
   rest wait for the persistent kernel to end. A minimal repro shows
   small-grid pairs interleave, so the boundary is pattern-specific.
   Green contexts (separate contexts) do not stall.
2. **Green contexts share the primary context's address space** — no copies
   needed; modules must be loaded per context; green streams require
   CU_STREAM_NON_BLOCKING (flags=0 -> CUDA_ERROR_INVALID_VALUE).
3. **Mapped pinned memory is coherent both directions** for polite single-
   thread polling (the doorbell design works); a 20k-thread grid spinning on
   one mapped word never saw host writes. An empty non-volatile spin loop is
   compiled away (UB) — atomic acquire is mandatory.
4. **L2 persistence policy is accepted but inert** on this driver — do not
   budget for it.
5. **Sparse-room operators need spectral-radius normalization** to place
   absorption sweeps at the stability edge; raw absorption sweeps never get
   there (in-degree gain dominates).

Artifacts: `sp_gc/` (harness + repro + analyzer), `l2_persist/`,
`persist_queue/` (+ torch graph baseline), `d1_batch/`, `gc_probe/`,
`room_prop/`; JSONs next to each harness; chain scripts `chain*.sh` with logs
in `logs/`. Raw numbers: sp_gc_half.json (primary, bg occupancy 0.5),
sp_gc.json (higher occupancy), room_prop.json + room_prop_nograph.json,
persist_queue.json + persist_queue_graph.json, l2_persist.json,
d1_batch.json, gc_probe.json.
