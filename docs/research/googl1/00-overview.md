# 00 — Overview: the map, the verdict, the three takeaways

**Source:** `docs/01…13`, each of which digests one part of Casey's `googl1.md`
(a ~25,000-word Google-chat brainstorm about running the Jetson AGX Thor
bare-metal) against our measurements, NVIDIA's public documentation and other
primary sources. This overview adds no new claims; it is the map of the parts,
the overall verdict, the three most valuable takeaways, and the paper decision.
The director's judgement is in
`builder-ide/docs/research/googl1/README.md`; this overview is consistent with
part 13 and with it.

## The map of the parts

The brainstorm divides naturally into thirteen parts. One line each; the part
doc carries the full claim/mechanism/verdict/judgement.

| Part | What it is about | Verdict in one line |
|---|---|---|
| [01](01-boot-and-trust-el3-seed.md) | Boot and trust: the "EL3 BootROM seed" | The Arm mechanics are real; we cannot write EL3 on a stock module. Worth doing cheaply as user-space attestation, not as a boot image |
| [02](02-memory-map-and-coherence.md) | Memory map, BAR pinning, coherence | Unified memory is real and measured coherent both directions — the machine's best property, already banked. The BAR/MMU/page-table work is not worth doing |
| [03](03-gpu-command-submission-and-sass.md) | Command submission, doorbells, raw SASS | Every named capability (clusters, DSMEM, TMA, mbarrier, CLC) is real and reachable through the driver. "Bypass the driver" is contradicted by our own 3 µs measurement through it |
| [04](04-warp-scheduling-and-persistent-kernels.md) | Warp scheduling, persistent kernels, "live I-cache surgery" | Take the persistent-scheduler half (measured). Live SASS rewriting and register-level DVFS are unsupported and unneeded |
| [05](05-nic-dma-and-zero-copy.md) | NIC DMA rings and the zero-copy network path | Network→tensor zero-copy is the largest unexploited property and the paper candidate. The NVLink multi-blade fabric is dead on this hardware (Thor has 4×25 GbE, no NVLink) |
| [06](06-partitioning-mig-and-green-contexts.md) | Partitioning: MIG and Green Contexts | **Green Contexts are a service floor, not a latency mechanism** — the most useful single result of the digest. MIG is compute-only and blocked by the desktop today |
| [07](07-safety-isolation-and-the-miter.md) | Safety, isolation, the "miter" | Take the miter as differential-testing discipline (we already practice it). Self-healing and the formal-proof framing are overreach |
| [08](08-power-dvfs-and-thermodynamics.md) | Power, DVFS, thermodynamics | Nothing to do as written. One fact worth keeping: thermals are a shared, finite resource — a `thor-admit` question, not a runtime one |
| [09](09-quf-cell-format-and-fp4.md) | The QUF cell format and FP4 | A fixed-width cell record: yes, at a 128-byte stride (the document's 144 fails its own alignment rationale). NVFP4 is real and measured; "zero conversion latency" only holds if the cell layout is the tensor layout |
| [10](10-the-no-os-vision.md) | The "no OS" vision | The document's own reversal (lines 941–968) is the sound conclusion: a compiled, immutable, hardware-scheduled execution graph — with the OS and driver kept, not removed. Our measurements are all Thesis B |
| [11](11-physics-escalation-and-terminal-reality.md) | Spintronics, phonons, vacuum channels, the Bekenstein bound | Nothing to build. Worth understanding as the document's failure mode: real physics invoked as if it were a property of this machine |
| [12](12-the-thirty-stage-code-cascade.md) | The 30-stage code cascade | A completeness performance, not a system. Mine it for three techniques (persistent execution, differential checking, bounded formal verification); do not adopt the architecture |
| [13](13-the-runtime-we-would-ship.md) | The runtime we would ship | **Build this:** resident kernel + pinned doorbell ring, one coherent memory pool, a Green Context service floor, a 128-byte cell record, differential checks. Days, not months, all on stock JetPack |

The load-bearing measurements behind those verdicts, all taken on the Thor
under `thor-admit`, most of them twice and independently (the `xp-batch` chain
and the digest seat's own probes):

- **The persistent ring:** p50 **3.03 µs**, p99 **5.42 µs**, **313,155
  jobs/s**, max rel err 2.41e-08 over 100,000 jobs (digest seat);
  independently **3.01 µs / 5.41 µs / 314 k jobs/s**, rel err 2.4e-08
  (`xp-batch/persist_queue`). Baselines in the same processes: torch-captured
  CUDA Graph 34.9 µs p50; plain per-job launch 53–69 µs p50 — and the plain
  path *stalled at job 1* under contention in both runs.
- **Mapped pinned memory is coherent in both directions** (host→device and
  device→host visibility both YES) — politely polled; a 20,480-thread grid
  hammering one mapped word never observed host writes.
- **Green Contexts:** SM partitions A=4/B=16 confirmed; under a heavy
  background the split served **1195 of 1200** live launches where both
  stream-priority conditions served **1 of 1200**; live p50 0.737 ms vs 0.117
  ms idle (6.3×) — a service floor, not a latency mechanism.
- **MIG:** present but compute-only (`0 MiB` memory in every profile) and
  blocked by the desktop session today.
- **The GPU is Blackwell sm_110**, 20 SMs, cc 11.0, CUDA 13.2 driver 13020;
  clusters, DSMEM, TMA, mbarrier and CLC all assemble for `sm_110a`; NVFP4
  tensor-core paths work at scale (thor-fp4).

## The overall verdict

**The brainstorm describes a multi-year bare-metal programme; its measurable
yield is a week of work on stock JetPack.** Of the document's three big moves —
remove the OS, own the memory map, inject raw SASS — every one is either
impossible on this hardware (signed boot chain, fuse-locked; no published
doorbell map or instruction-cache write path) or unnecessary given supported
mechanisms that reach the same ends through the driver. The document's own
mid-course reversal (part 10, lines 941–968) already says the right thing: the
machine becomes fast as a *compiled, immutable, hardware-scheduled execution
graph* — and both of our headline measurements are exactly that shape. The
runtime this implies (part 13) is buildable today, by one person, in days,
with no privileged access: the resident ring at 3 µs, one coherent memory
pool, a Green Context floor for live work, a 128-byte cell record, and a
differential check on every numeric path. The firmware-level ideas (custom EL3
boot, owned page tables, raw SASS, MMIO doorbells, DVFS control, NVLink
fabric) are recommended by the digest **none** of, and the director concurs.

The failure mode worth naming (parts 11–12): the document escalates from
falsifiable engineering claims to unfalsifiable ones (spintronics, the
Bekenstein bound, "sealed" 30-stage completeness) and lets the second category
lend the first an authority it has not earned. Separating them is most of the
value of this digest.

## The three most valuable takeaways

1. **Adopt the resident kernel + pinned doorbell ring as the agent runtime's
   dispatch path.** Measured twice: p50 ≈ 3 µs CPU-enqueue-to-result at
   ~314 k jobs/s, verified correct to 2.4e-08, versus 35–69 µs p50 for every
   per-job path measured — and the per-job paths collapse outright under a
   resident background (1 of 1200 launches served). This is the whole of the
   document's submission story that survives, it needs nothing privileged, and
   it costs hours to adopt. For the reflex layer (`design/three-minds.md`),
   this ring is the right shape for d1 and the tiles: answer from a resident
   kernel, not a launch per decision.
2. **Green Contexts are a service floor, not a latency mechanism — and the
   real lever is background bandwidth.** SM partitioning does not partition
   DRAM: the split restores *service* (1195/1200 vs 1/1200) at a measured
   latency price (6.3× p50, p99 37× the 1.2×-of-idle bar). The data shows the
   live tail is inflated by the background's ~55 GB/s of DRAM traffic, so the
   policy lever — cap or defer bandwidth-hungry background work while live
   work runs — is worth more than the partitioning mechanism, and belongs in
   `thor-admit`.
3. **Keep the framing, drop the programme: Thesis B.** "A compiled, immutable
   artifact with a hardware-scheduled queue" is the correct reading of the
   machine, and every mechanism that made our measurements good (the ring,
   Green Contexts, CUDA Graphs, NVFP4 via CUTLASS) is driver-mediated —
   removing the driver would remove the mechanism. Write the decision down so
   the next brainstorm does not re-derive the bare-metal programme.

## The paper decision (Part 2 of the brief)

The candidate the parts point to is **network→tensor zero-copy on unified
memory** (part 05; parts 02, 04 and 13 support it). Assessed against the
brief's bar — precise statement, mechanism, derived model, related work, an
experiment with a pass bar, and ideally a first measurement:

- The **socket-level zero-copy ingress path** (a frame received directly into
  a mapped pinned ring slot and consumed in place by the resident kernel, no
  staging copy, no per-job launch) is fully pencilable, and its experiment
  ran on 2026-11-01 under `thor-admit`: the **naive arm measured to
  completion** (p50 30.8 µs at 1 KiB / 36.4 µs at 8 KiB, bit-exact over
  70,000 frames — the launch term of the model, measured in the ingress
  setting), while the **zero-copy arm's corrected re-run did not clear the
  box's admission queue within the seat** (head-of-line blocked behind
  24–26 GB leases all morning; the box saturated to the point its ssh timed
  out). Its pass bar is pre-registered in the paper and the corrected run
  sits queued as lease `googl1.ingress4` — when the box opens, the number
  is a retrieval, not a project. The paper, the probe and both attempts'
  raw records are in `superinstance-papers/papers/61-doorbell-ring-ingress/`.
- The **NIC-DMA half** of the idea (GPUDirect RDMA: the NIC's DMA writes
  landing in GPU-addressable memory, bypassing the socket stack) does **not**
  reach the bar on this box: it needs the ConnectX-7-class NIC and
  `nvidia-peermem` module this box does not have, and its central mechanism
  (where the NIC's DMA lands under the IOMMU) is flagged plausible-but-
  unverified in part 05. No measurement of it is possible here. It is recorded
  in the paper as the designed follow-up with its pass bar, not as a result.

The paper that earned its place is **"The Three-Microsecond Doorbell:
resident kernels and zero-copy ingress on a unified-memory SoC"**
(`papers/61-doorbell-ring-ingress/`), on the `googl1-papers` branch of
`superinstance-papers`. It rests on the two independent ring measurements, a
derived dispatch-cost model, the measured naive arm of the ingress
experiment, the service-floor interaction, and a standing regression with a
pass bar. The resident kernel + pinned doorbell ring was already measured
twice before this digest sat down; the ingress experiment added the naive
arm and left the zero-copy arm one queued lease away. Nothing else in the
document came close: the remaining ideas are either contradicted by the
hardware (NVLink fabric, custom EL3, SASS injection), already banked
(unified memory, NVFP4), or practices rather than claims (the miter, the
cell record).
