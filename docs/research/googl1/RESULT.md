# RESULT — googl1-digest: the parts, the verdicts, the papers, and why

**Seat:** googl1-digest (continuation), 2026-11-01. **This file now covers
two digests:** the googl1 digest (below) and the googleidea3 digest
(end). The seat's running log is `NOTES.md`.
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
  pre-registered.

  > **Superseded (11:30, the googleidea3 seat — see the end of this file).**
  > The queued lease `googl1.ingress4` did **not** survive the queue (at
  > 11:15 the queue was empty, no ledger entry, no results dir). The next
  > seat resubmitted the run as `googl1.ingress5`, fixed one more probe
  > defect found on execution (the shutdown `cudaDeviceSynchronize()`
  > hanging behind co-tenant GPU starvation with the JSON unprinted), and
  > **the zero-copy arm then measured and PASSED its pre-registered bar**:
  > zero p50 **3.21 µs** (1 KiB, 50,000 frames) and **4.84 µs** (8 KiB,
  > 20,000 frames) vs naive 29.32/44.35 µs — 9.1×/9.2×, `mismatch = 0`
  everywhere, **zero** frames over 1 ms in the zero arm (naive: 22 and 1).
  Paper 61's experiment is complete; commit `2d0ccb6` on `googl1-papers`,
  not pushed. The correction is recorded in the paper's `measurement.md`
  (attempt 2 superseded, attempt 3 added) with the old text kept visible.

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

---

# googleidea3 — the parts, the verdicts, the paper decision

**Seat:** googl1-digest (googleidea3 continuation), 2026-11-01, per the
11:30 CONTINUE. **Inputs:** `googleidea3.md` (86 KB: the "Cellular POSIX
Simulator", Stages 31–40, a closing self-review); googleidea1 and
googleidea2 (`~/lm-ops/aider-desk/lib-googleidea{1,2}.md`, identical copies
in the seedbank) for the extends/repeats/contradicts relation; everything
the googl1 digest banked. **Deliverables:** `docs/googleidea3/00-overview.md`
+ 13 part docs + a compile probe (`docs/googleidea3/probes/`).

## The parts and their verdicts

| Part | Verdict |
|---|---|
| 01 the Cellular POSIX Simulator | Right shape (a thin compiler into the 3 µs ring), broken costume: paths collide at ~300 names, `ls` can't list, "exploit immunity" inverts the truth; contradicts googleidea1's Linux pipeline |
| 02 the monolith (linker.ld, boot.s) | Real Arm boot mechanics, canonical values — invented self-contradictory map behind signed boot; doesn't assemble |
| 03 the register map + command path | The ring discipline = paper 61's measured ring; every address invented; GIC wrong in version (device tree: `arm,gic-v3` at 0x8146000000) and bank; **the handler does not compile** (probe: 5 lvalue errors + missing typedef + silent read-the-address bugs) |
| 04 cells, "FP4", Hebbian, RNDR | Cell drifted to 112 B (fails googl1's own 128-rule); "FP4" = 4-bit ints ≠ NVFP4; RNDR is real Arm but **FEAT_RNG absent on this box's V3AE (checked live)** — the `mrs` would fault; `getrandom()` suffices |
| 05 the JTAG route | Textbook TAP on a Raspberry Pi GPIO map; can't write flash; signed chain rejects the payload; USB recovery flash is the supported route |
| 06 crash dump + watchdog | The right pattern (crash-only); adopt the supported form: verify pstore/ramoops once, hash-chain the agent journal |
| 07 cache maintenance | Real `dc ivac/cvac` idiom, wrong premise: CPU↔GPU is coherent — 170 k bit-exact jobs/frames ran with zero maintenance |
| 08 the hardware timer | Most nearly correct stage (right regs, right PPI 26); still an EL2/EL3 naming error, a bank error, an undefined symbol; clock_gettime/vDSO is enough |
| 09 the PCIe barrier | Real hazard, wrong fix (Transactions-Pending ≠ your writes' arrival) and unnecessary: posted-write ordering + release/acquire, proven bit-exact by paper 61 |
| 10 NVLink telemetry | Third appearance of the NVLink fiction; Thor has no NVLink (4×25 GbE); ethtool counters are the real form |
| 11 the context swapper | Invented registers sitting on its own command ring; CPU register file pasted onto a GPU; real answers are measured (ring = no context to swap; Green Context floor 1195/1200) |
| 12 the Stage 40 loop | Right skeleton, invented organs; calls symbols that exist nowhere; not in its own build script |
| 13 the expert review | TMA + mbarrier real (assembler-verified sm_110a) beside ps-claims, Apple-ecosystem API names, invented registers; its one true sentence — zero-copy on one coherent pool — is now measured (paper 61, PASS) |

**Overall verdict.** googleidea3 adds no mechanism googl1 didn't already
adjudicate, and its new specifics fail first contact with the machine —
three of them falsified this seat in minutes each (compile probe; live
FEAT_RNG check; device-tree GIC). What stands is what stood after googl1
(Thesis B, the ring, the floor, the differential discipline) plus one
honest addition: crash-first evidence handling (part 06).

## The paper decision

**No paper; no `googleidea3-papers` branch.** The mechanism-shaped
candidates are subsumed by paper 61 (zero-copy pipeline = its subject, now
measured PASS; doorbell ordering = its bit-exact runs + write-ordering
rules; shell-as-ring-client = an application note of its §6 regression);
the genuinely new candidates are not pencilable (RNG mutation rests on a
feature the CPU lacks and is a toy rule without a model; the POSIX
simulator doesn't close semantically; the NVLink monitor and context
registers monitor/command hardware that doesn't exist). The digest's own
findings are evidence about a document, not mechanisms about a machine.
Reasons are stated in `docs/googleidea3/00-overview.md` §"The paper
decision" — a valid outcome per the brief.

**Library work this seat did instead:** completed paper 61's dangling
pre-registered measurement — resubmitted the lost `googl1.ingress4` lease
as `googl1.ingress5`, diagnosed and fixed a shutdown-hang defect (the
receiver printed its JSON only after a `cudaDeviceSynchronize()` that waits
out co-tenant starvation; now print-then-exit), re-ran all five configs:
**zero-copy arm PASS** (3.21/4.84 µs p50 vs 29.32/44.35 µs naive, 9.1×/
9.2×, mismatch 0, zero >1 ms events, 70,000 frames). Committed as
`2d0ccb6` on `googl1-papers` (paper.md + measurement.md + raw JSON +
corrected probe); **not pushed** — the director handles the PR. The words
"breakthrough"/"groundbreaking"/"ah-ha" do not appear in the library text
(checked, `grep -c` = 0).

## What was run on the Thor (this continuation)

Read-only fact checks over `ssh thor-lan` (`/proc/cpuinfo` Features — no
`rng`; `/proc/device-tree/interrupt-controller@8146000000/compatible` =
`arm,gic-v3`). CUDA work only under `thor-admit run` (study tier, label
`googl1.ingress5`, peak 2G, co-tenant render + two model servers
throughout). One correction of the record: the previous seat's queued lease
`googl1.ingress4` had vanished without running — recorded here and in the
paper's `measurement.md` with the old text kept visible. Two stuck
processes killed mid-diagnosis were the lease's own (PIDs verified before
the kill); no other tenant's lease was touched. Nothing wrote to
`/dev/mem`, firmware, or boot configuration. The compile probe ran on the
ProArt host, not the Thor.
