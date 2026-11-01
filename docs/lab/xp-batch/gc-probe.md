# gc-probe: Green Contexts on sm_110 (idea3 E3)

Run: 2026-11-01 06:55 under `thor-admit` (lease xp-batch.chain). Box: NVIDIA
Thor, sm_110 (cc 11.0), CUDA 13.2 driver 13020, 20 SMs, L2 32 MB,
`smCoscheduledAlignment = 2`, `minSmPartitionSize = 2`.

## Question

Can the CUDA driver split the Thor's SMs into hardware-partitioned green
contexts, and do two partitions run concurrent work correctly?

## Result: SUPPORTED and verified

- `cuDeviceGetDevResource(0, CU_DEV_RESOURCE_TYPE_SM)` returns smCount=20.
- `cuDevSmResourceSplit` into a 4-SM group (coscheduled 2) plus a 16-SM
  backfill group succeeded; `cuGreenCtxCreate` for both succeeded;
  `cuGreenCtxGetDevResource` confirms **A = 4 SMs, B = 16 SMs**.
- One 512x512 SGEMM launched in each partition concurrently: device spans
  overlapped **1.00** (A span 2.384 ms on 4 SMs, B span 0.612 ms on 16 SMs —
  the 4:16 time ratio 3.9 is what a compute-bound kernel predicts for a 4x
  smaller partition), and both partitions computed the same A@B: max sampled
  rel err **3.4e-06** vs a host double-precision reference.
- Device memory allocated in the primary context was read/written by kernels
  launched inside the green contexts with no copies and no errors: green
  contexts share the primary context's address space.

## Unsupported paths (recorded verbatim)

- `cuGreenCtxStreamCreate(..., flags=0, ...)` fails with
  **CUDA_ERROR_INVALID_VALUE**; the header requires `CU_STREAM_NON_BLOCKING`,
  which succeeds.
- Modules are per-context: a module loaded in the primary context is not
  usable from a green context; `cuModuleLoadData` must be called again with
  each green context current.

## Caveats

- `nvidia-smi` on Thor does not report per-process GPU memory reliably
  (queries intermittently hang for minutes under load; bounded with
  `timeout 10`), so partition occupancy was verified by overlap spans
  (`%globaltimer` in-kernel) rather than utilization counters.
- No clock locking (clocks [N/A] to nvidia-smi; jetson_clocks needs sudo).
