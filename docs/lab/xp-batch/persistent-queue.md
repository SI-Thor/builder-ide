# persistent-queue: resident kernel polling a ring vs per-job CUDA Graph launches

Run: 2026-11-01 07:56-07:58 under `thor-admit` (lease xp-batch.chain, peak 1G,
actual RSS ~150 MB). Box: NVIDIA Thor sm_110, CUDA 13.2 driver 13020, 20 SMs,
clock monotonic resolution 1 ns. Job = 64-float dot product; 100,000 jobs per
variant; latency = host clock from the moment the CPU hands the job over
(slot write / async copy issue) to the moment the result is observed on the
host. Clocks not lockable (nvidia-smi [N/A] on Thor).

## Question

A resident CUDA kernel polling a lock-free ring that the CPU fills with tiny
jobs — measured against launching each job as a captured CUDA Graph (a prior
measurement on this Thor: ~4.7 us). Report both, plus throughput.

## First: a hardware/driver fact the design depends on

Mapped pinned memory is coherent in *both* directions on this box when
polled politely — a bounded probe (one thread, 200 ms) saw host->device
writes and device->host writes (both YES). The earlier stream-priority
experiment's hang is therefore specific to a 20,480-thread kernel hammering
one mapped line, not to the mechanism. Design accordingly: doorbells work;
do not spin a whole grid on one mapped word.

## Numbers (100k jobs each)

| variant | rel err | p50 | p99 | throughput |
|---|---|---|---|---|
| **persistent kernel + ring in pinned memory (direct host writes)** | 2.4e-08 | **3.01 us** | **5.41 us** | **314 k jobs/s** |
| torch-captured CUDA Graph per job (copy_ + replay + item) | 6.0e-08 | 34.9 us | 4657 us | 9.8 k jobs/s |
| plain per-job kernel launch (memcpyAsync + launch) | 2.4e-08 | 53.1 us (job 0) | — | stalled at job 1 (see below) |

The spec's remembered ~4.7 us per graph launch is not reproducible through
torch's graph path (35 us p50 — that includes a pinned->device `copy_`, the
replay, and `.item()` per job); the persistent ring is ~12x faster at p50
and ~860x at p99.

## Verdict

**The persistent ring wins decisively and is verified correct** (rel err
2.4e-08 over 100k jobs, results read back and compared to a host reference).
p50 3.0 us, p99 5.4 us at 314 k jobs/s — CPU enqueue to GPU result, on a
shared box.

## Unsupported / anomalous paths (recorded verbatim)

- **Driver-API CUDA Graphs hang.** `cudaGraphInstantiate` + the first
  `cudaGraphLaunch` of a kernel that writes mapped host memory blocks
  indefinitely (0% CPU, observed twice, 10-minute timeout kills). Torch's
  graph path works, so the graph baseline above goes through torch.
- **Plain per-job launches: result visibility stalls.** Job 0's mapped
  result write became visible in 53 us; job 1's did not become visible
  within 1 s (bounded wait tripped), although the kernel's device result
  was correct when later synchronized. The same mapped write from the
  *persistent* kernel was visible every ~3 us for 100k jobs. Mechanism
  unknown — worth a follow-up if per-launch latency matters anywhere.
- Two measurement bugs found and fixed on the way, worth remembering:
  a non-volatile empty spin (`while (*hseq != want);`) is deleted by the
  compiler (forward-progress UB) — atomic acquire loads are required; and
  a reduction that only sums warp 0's lanes silently returns half a dot.

## Notes

- The ring is the spec's literal design: slots in mapped pinned memory, CPU
  writes data then bumps the slot sequence with a release store; the kernel
  polls the sequence. A doorbell variant (ring in device memory, one
  copy-engine push per job) was built as a fallback and is not needed here.
- 314 k jobs/s of 64-float dots is ring-polling bound; jobs 8x bigger would
  scale proportionally until the copy path saturates.
