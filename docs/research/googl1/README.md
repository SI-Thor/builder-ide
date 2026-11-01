# googl1.md, digested part by part (2026-11-01)

The source is Casey's `googl1.md`: a ~25,000-word Google-chat brainstorm about running the Jetson AGX Thor bare-metal. Casey asked for every part to be digested into its own doc, with research and judgement, and for any idea that can be fully penciled out to become a paper in `SuperInstance/superinstance-papers`.

The `googl1-digest` seat wrote the 13 part docs. mcode's quota stopped it at ~08:30, before the overview and the paper. Those resume at the next reset. Each doc says what the part claims, what it means, whether it is true on the Thor (with sources and our measurements), and a judgement.

| Part | Verdict, in one line |
|---|---|
| [00, first pass](00-first-pass.md) | The 20-claim triage against our measurements (Groq + DeepSeek), which turned up Green Contexts |
| [01, boot and trust (EL3)](01-boot-and-trust-el3-seed.md) | Worth doing cheaply, in a different form |
| [02, memory map and coherence](02-memory-map-and-coherence.md) | The unified-memory fact is worth a lot and already banked; the BAR/MMU work is not |
| [03, GPU command submission and SASS](03-gpu-command-submission-and-sass.md) | Take the mechanism; discard the framing |
| [04, warp scheduling and persistent kernels](04-warp-scheduling-and-persistent-kernels.md) | Take the persistent-scheduler half |
| [05, NIC DMA and zero-copy](05-nic-dma-and-zero-copy.md) | Network → tensor zero-copy is worth pursuing (the paper candidate); the NVLink fabric is not (no NVLink here) |
| [06, partitioning: MIG and Green Contexts](06-partitioning-mig-and-green-contexts.md) | **Green Contexts as a service floor, not a latency mechanism.** The most useful single result |
| [07, safety, isolation and the "miter"](07-safety-isolation-and-the-miter.md) | Take the miter as a testing discipline; discard self-healing and the formal-proof framing |
| [08, power, DVFS and thermodynamics](08-power-dvfs-and-thermodynamics.md) | Nothing to do as written; one fact worth keeping |
| [09, the QUF cell format and FP4](09-quf-cell-format-and-fp4.md) | A fixed-width cell record, yes, at a 128-byte stride (not the document's 144) |
| [10, the no-OS vision](10-the-no-os-vision.md) | Keep the framing; drop the implementation programme |
| [11, physics escalation and "terminal reality"](11-physics-escalation-and-terminal-reality.md) | Nothing to build; worth understanding as the document's failure mode |
| [12, the thirty-stage code cascade](12-the-thirty-stage-code-cascade.md) | Mine it for techniques; don't adopt it as an architecture |
| [13, the runtime we would ship](13-the-runtime-we-would-ship.md) | **Build this:** a resident kernel + pinned doorbell ring (3.03 µs p50 vs 69 µs per-job launches), one coherent memory pool, a Green Context floor for live work, a 128-byte cell record, differential checks. Days, not months, all on stock JetPack |

`probes/` holds the seat's Green Contexts probe (C).

## The director's judgement

**I agree with part 13's verdict.** The useful yield of a vision of removing the software stack turns out to be a handful of supported mechanisms that run on stock JetPack, and two of them are now measured twice, independently (here and in `docs/lab/xp-batch/`):
- the persistent ring, at 3 µs;
- the Green Context floor, at 1,195 of 1,200 live launches.

**For the reflex layer** (`design/three-minds.md`) that ring is the right shape: d1 and the tiles answering from a resident kernel fed by a doorbell, not a launch per decision.

**On MIG (Casey's decision 1):** MIG on the Thor showed **0 GiB per slice** (`docs/lab/exp-mig.md`), so it partitions compute but not memory bandwidth. Green Contexts' latency cost (live p50 6.3× idle, p99 37× the bar) comes from the background's DRAM traffic, which a MIG slice would share in the same way. **I expect MIG to give the same floor and the same latency penalty, at the cost of the desktop.** The headless test is still worth running once, to settle it. The lever that would actually cut live latency is part 13's item 4: cap background bandwidth while live work runs. That becomes a thor-admit dimension (round 11's Green-Context design note will take it up).

**The firmware-level ideas** (custom EL3 boot, owned MMU, raw SASS, MMIO doorbells, DVFS): the digest found each either unsupported on this hardware or unnecessary given supported mechanisms. **I recommend none of them.**

**Pending:** `00-overview.md` and the papers decision (the network → tensor zero-copy candidate), when mcode is back.
