# RESULT — googl1-digest: the parts, the verdicts, the papers, and why

**Seat:** googl1-digest (continuation), 2026-11-01.
**Inputs:** Casey's `googl1.md` (~25,000-word bare-metal Thor brainstorm); our
measurements in `builder-ide` (`docs/lab/`, `docs/lab/xp-batch/`,
`thor-fp4/BENCHMARKS.md`, `docs/design/`); the `superinstance-papers` library.
**Previous state:** the 13 part docs were written by the previous seat (mcode)
and filed in `builder-ide/docs/research/googl1/` with the director's judgement
in its README. This seat finished the overview, the paper decision, the paper,
and this result. The part docs were not rewritten.

## The parts and their verdicts

| Part | Verdict |
|---|---|
| 01 boot and trust (EL3 seed) | Real Arm mechanics; unwritable on a stock module. Do the cheap form: user-space attestation |
| 02 memory map and coherence | Unified memory confirmed (coherent both directions, UVA — already banked). BAR/MMU work: not worth doing |
| 03 command submission and SASS | Mechanism real and driver-reachable; "bypass the driver" contradicted by our own 3 µs measurement |
| 04 warp scheduling, persistent kernels | Take the persistent-scheduler half (measured); I-cache surgery / DVFS: unsupported, unneeded |
| 05 NIC DMA and zero-copy | Network→tensor zero-copy worth pursuing (paper candidate); NVLink fabric dead on this hardware |
| 06 MIG and Green Contexts | Green Contexts = service floor (1195/1200 vs 1/1200), not a latency mechanism; MIG compute-only, blocked |
| 07 safety and the miter | Differential testing: yes (already our practice). Self-healing / formal-proof framing: no |
| 08 power, DVFS, thermodynamics | Nothing as written; keep "thermals are a shared resource" as a thor-admit fact |
| 09 QUF cell format and FP4 | Fixed-width cell record at a 128-byte stride (not 144); NVFP4 real; "zero conversion latency" only if cell layout = tensor layout |
| 10 the no-OS vision | Keep Thesis B (compiled artifact + hardware scheduling); drop the bare-metal programme |
| 11 physics escalation | Nothing to build; the document's failure mode, understood |
| 12 the 30-stage cascade | Mine for three techniques; do not adopt the architecture |
| 13 the runtime to ship | **Build:** resident ring + coherent pool + Green Context floor + 128-byte cells + differential checks — days, not months, stock JetPack |

Overall verdict: the brainstorm describes a multi-year bare-metal programme;
its measurable yield is a week of work on stock JetPack. The director's
judgement (builder-ide README) concurs, including on MIG (compute-only, same
DRAM sharing expected as Green Contexts; one headless test worth running) and
on recommending **none** of the firmware-level ideas.

**Deliverables:** `docs/00-overview.md` (map, verdict, three takeaways, paper
decision) plus the 13 part docs (`docs/01…13`, unchanged from the previous
seat).

## The papers

### Written: `papers/61-doorbell-ring-ingress` on branch `googl1-papers`

**"The Three-Microsecond Doorbell: Resident Kernels and Zero-Copy Ingress on
a Unified-Memory SoC"** — the resident kernel + pinned doorbell ring, which
the CONTINUE flagged as possibly the stronger paper because it was already
measured twice:

- **Measured twice, independently** (both 2026-11-01, same box, co-tenant):
  p50 3.01 µs / p99 5.41 µs / 314 k jobs/s (`xp-batch/persist_queue`) and
  p50 3.03 µs / p99 5.42 µs / 313,155 jobs/s (the digest seat's probe), max
  rel err 2.4e-08 over 100 k jobs each. Baselines in the same processes:
  torch-captured CUDA Graph 34.9 µs p50; plain per-job launch 53–69 µs p50
  and a stall-under-contention failure.
- **A derived cost model** (dispatch decomposition, a no-crossover dominance
  proposition with measured constants β_read ≈ 100.9 GB/s vs β_api ≈ 88
  GB/s and c_launch ∈ [35, 69] µs, Little's-law consistency, ingress copies
  accounting), not asserted scalings.
- **Related work with citations**: persistent threads (Aila & Laine HPG 2009;
  Cederman & Tsigas GH 2008; Gupta, Stuart & Owens InPar 2012; Chatterjee et
  al. LCPC 2011), launch-overhead characterizations (Wilt 2013; NVIDIA
  dynamic-parallelism whitepaper), CUDA Graphs, Green Contexts (CUDA 12.4;
  the CUDA 13 Jetson-Thor note), Tegra zero-copy/UVA, GPU networking
  (PacketShader SIGCOMM 2010; Kalia et al. NSDI 2015; GPUDirect RDMA; DOCA
  GPUNetIO), resident serving loops (Orca OSDI 2022; vLLM SOSP 2023), Little
  1961.
- **An experiment with a pass bar** (the standing regression of §6) and **a
  first measurement run for the ingress claim** — see below.
- **A first measurement on the Thor**, under `thor-admit`, user-space only:
  the zero-copy ingress probe (`thor-probe/wire_ingress.cu` + `sender.c`,
  committed as aux files) — `recv()` directly into a mapped pinned ring slot
  consumed in place by one resident warp, vs the naive recv→heap→H2D
  copy→per-job-launch path, at 1 KiB and 8 KiB frames. Result: **the naive
  arm ran to completion, twice, bit-exact over 70,000 frames (p50 30.8 µs
  at 1 KiB, 36.4 µs at 8 KiB, rare multi-second stalls recorded verbatim) —
  the model's launch term measured in the ingress setting. The zero-copy
  arm's corrected re-run never cleared the box's admission queue within the
  seat** (the queue spent the session head-of-line blocked behind 24–26 GB
  render and model-server leases; by ~10:30 the box's ssh was timing out
  under load). The first attempt also caught and fixed a probe bug (a clock
  helper multiplying nanoseconds, ×1000 inflation) — the correction is
  quantified in the paper and the corrected probe is what is committed. The
  zero arm's pass bar (zero p50 < naive p50, zero mismatches) stands
  pre-registered, and the corrected run sits queued as lease
  `googl1.ingress4` (~10 s of bounded, 512 MB work): when the box opens it
  executes unattended and lands in `~/googl1-ingress/results/` on the Thor.

Filed in the library's structure: `papers/61-doorbell-ring-ingress/` (the
next number after `papers/60`), plus its `LEDGER.md` (new "November 2026"
section), `TOPICS.md` (Infrastructure and tooling) and `papers-index.json`
records, with the library's headline counts updated (355 → 356 papers, 339 →
340 dated). Committed as `c23825e` on branch `googl1-papers` with a full
message; **not pushed** — the director opens the PR. The words "breakthrough",
"groundbreaking" and "ah-ha" do not appear in the library text (checked).

### Declined: a standalone NIC-DMA zero-copy paper (part 05's full form)

The network→tensor candidate as written in part 05 has two halves. The
socket-level half (frame received into coherent pinned memory, consumed in
place) is real, measured, and became §5.3 of paper 61 rather than a paper of
its own — it is the *same* coherence fact and the *same* ring; a separate
paper would have split one mechanism in two. The NIC-DMA half (GPUDirect
RDMA: the NIC's DMA writes landing in GPU-addressable memory) does not reach
the brief's bar on this box: it requires a ConnectX-7-class NIC and the
`nvidia-peermem` module that this box does not carry, its central mechanism
(where NIC DMA lands under the IOMMU on this platform) is untested and marked
plausible-but-unverified in part 05, and no honest measurement of it is
possible here. Writing it as a paper would have been an unmeasured design
document. It is recorded in paper 61 §7 as the designed follow-up with an
unchanged pass bar.

### Examined and not paper-worthy

- **Green Contexts as an admission primitive** — a measured, useful result
  (1195/1200 service restoration) and the most useful single finding of the
  digest, but a mechanism adoption with a clear scope limit (service floor,
  not latency; DRAM not partitioned), not an idea needing a paper's machinery.
  It is §4.5 of paper 61.
- **The bare-metal mechanisms** (EL3 seed, owned page tables, raw SASS, MMIO
  doorbells, register-level DVFS, NVLink fabric) — each is contradicted by
  the hardware (signed boot, no published doorbell map, no instruction-cache
  write path, no NVLink) or unnecessary; there is nothing to pencil out.
- **The cell record / FP4** — a data-format decision (128-byte stride) and
  banked NVFP4 measurements (`thor-fp4`); no open claim to test.
- **The miter** — our existing differential-testing practice; no new claim.

## What was run on the Thor

All measurements were user-space CUDA under `~/lm-tools/thor-admit run`
(study tier, labels `googl1.ingress*`), via `ssh thor-lan`. Nothing wrote to
`/dev/mem`, firmware, or boot configuration; nothing ran outside a lease.
One operational note, recorded honestly: the box's admission queue was
head-of-line blocked for part of the morning behind a 24 GB render lease,
and two of my queued lease requests were killed and resubmitted (only my own
PIDs were touched; no other tenant's lease was affected — verified before and
after).
