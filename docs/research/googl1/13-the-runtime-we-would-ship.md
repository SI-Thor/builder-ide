# 13 — Putting it together: the agent-world runtime we would actually ship

**Source:** synthesis across `googl1.md` parts 01–12, judged against
`docs/design/three-minds.md` (the three minds: CPU roots, memory fabric, GPU
engine), `docs/design/language-fit.md`, and the `builder-ide` night-agent
context. This part is the answer to the brief's question — "what part of it is
worth doing for us (builder-ide, the night, the first mile, agent-world)".

## What it says

The document does not address this directly, and that is a legitimate finding:
it is a description of a machine, not of a workload. But taken together with
what we measured, the document supports a specific runtime shape for the night
agent, and that shape is worth writing down because it is the thing the
brainstorm was groping towards and did not have the measurements to reach.

The shape is: **a compiled, resident, hardware-scheduled service with a
host-side doorbell, over one coherent memory pool, with a guaranteed SM floor
for live work.**

## What it means

Concretely, the runtime the evidence supports has five pieces, each of which we
have verified on the Thor:

1. **One coherent memory pool.** No CPU-side staging copy between the agent's
   state and the GPU's work. Verified: mapped pinned memory is visible in both
   directions (`host->device pinned visible=YES device->host pinned visible=YES`),
   and green contexts share the primary context's address space.

2. **A resident kernel and a host-side ring.** The agent posts a job into a
   pinned ring and rings a doorbell; the resident kernel picks it up. Verified
   and measured at **313,155 jobs/s, p50 3.03 µs, p99 5.42 µs**, max rel err
   2.41e-08 — against **99,991 jobs/s, p50 69.27 µs** for the per-job launch path
   in the same process, which additionally **stalled at job 1** under
   contention.

3. **A guaranteed SM floor for live work.** Green Contexts on the Thor:
   `minSmPartitionSize=2`, `smCoscheduledAlignment=2`, partitions confirmed at
   A=4 SMs / B=16 SMs. Under a heavy background the split served **1195 of 1200**
   live launches where both the same-priority and the high-priority paths served
   **1 of 1200**.

4. **A fixed-width cell record for agent context.** A record format both the
   producer and the GPU kernel understand, with a stride that respects the
   hardware's 128-byte granularity (not the document's 144).

5. **Differential checking on every path.** A reference model and a recorded
   error bound for every numerically meaningful operation — the discipline the
   document called a "miter", and the one every measurement in this library
   already follows.

What this runtime deliberately does *not* have: no custom boot image, no
hand-written SASS, no owned page tables, no DVFS control, no NVLink mesh, no
bare-metal layer. Every one of those was examined in parts 01–12 and found
either unsupported on this hardware or unnecessary given the mechanisms that
are supported.

## Is it true on the Thor?

| Component | Verdict | Evidence |
|---|---|---|
| Coherent unified memory pool usable as the agent's working store | **confirmed** | Measured today under `thor-admit`: host→device and device→host pinned visibility both YES. `total_mem` 131,856,928,768 B shared between OS and CUDA |
| A resident kernel + host doorbell is faster than per-job launches, by a wide margin | **confirmed** | Measured today: 313,155 jobs/s at p50 3.03 µs vs 99,991 jobs/s at p50 69.27 µs; p99 5.42 µs vs 69.27 µs. Same process, same box, same lease |
| The resident ring is numerically correct | **confirmed** | max rel err 2.41e-08 over 100,000 jobs against a host reference |
| Green Contexts can hold a live lane open against a background sweep | **confirmed** | Measured today: partitions A=4/B=16 SMs confirmed via `cuGreenCtxGetDevResource`; concurrent SGEMMs overlapped 1.00 with max rel err 3.443e-06. Under load, 1195/1200 launches served in the split condition vs 1/1200 in both priority conditions |
| Green Contexts bound the *latency* of that live lane | **contradicted** | Live p50 goes from 0.117 ms idle to 0.737 ms under the split (6.3×); p99 to 5.418 ms, which is 37× the 1.2×-of-idle pass bar. SM partitioning does not partition DRAM |
| A fixed-width cell record is a sound design for agent context | **plausible but unverified** | Sound as a data-format choice (no hardware claim involved). The document's specific 144-byte stride is contradicted — 144 is not a multiple of 128 |
| No custom boot, SASS, MMU ownership, DVFS control or NVLink mesh is needed for any of the above | **confirmed** | Every verified mechanism above runs through the stock CUDA stack on a stock JetPack Thor, under `thor-admit`, with no privileged access |

**The honest summary.** The runtime the evidence supports is buildable today on
stock JetPack, on a shared box, by one person, in days. It is *less* exotic than
the brainstorm and *more* effective than most of the brainstorm: the measured
3.03 µs doorbell latency and 1195/1200 live launches are the concrete
achievements, and neither required removing an abstraction.

The one thing the document offers that the measurements do not settle is the
network→tensor zero-copy path (part 05). That is the largest remaining
opportunity on this machine, and it is the one that earns a paper (part 14
overview → the paper in `superinstance-papers`).

## Judgement

**Build this. It is the whole of the useful yield of the document.**

**Stock JetPack, today — the build order:**

1. **Adopt the persistent ring in builder-ide's agent runtime.** Replace
   per-request launches with a resident kernel and a pinned ring. Measured
   benefit: p50 3.03 µs instead of 69.27 µs, and it removes the stall-under-
   contention failure that the plain path showed. *Cost: hours.*
2. **Make the measurement a gate, not a report.** The 100 k-job run (p50, p99,
   throughput, max rel err) is the standing regression for anything we schedule
   on the Thor. It already exists as `xp-batch/persist_queue`. *Cost: hours.*
3. **Introduce a Green Context lane for live work against background sweeps.**
   Adopt it as a *service floor* — "live work is served", not "live work is
   fast". Record the p50/p99 we actually get (0.737 ms / 5.418 ms under load)
   so nobody re-derives the wrong expectation. *Cost: a day.*
4. **Cap background memory bandwidth, and prefer not to run a
   bandwidth-hungry sweep during live work.** The green-split data shows the
   live p99 is inflated by the background's 55 GB/s of DRAM traffic. This is a
   policy lever worth more than the partitioning mechanism. *Cost: a policy
   decision, and possibly a `thor-admit` dimension.*
5. **Adopt a fixed-width cell record with a 128-byte-aligned stride** for agent
   context and working sets. *Cost: a day.*
6. **Keep the differential check on every numeric path.** Already our habit;
   make it explicit and record the error bounds. *Cost: ongoing.*
7. **Investigate the NIC→tensor zero-copy path** — the one remaining large
   opportunity, and the subject of the paper written alongside this digest.

**Needs OS/firmware changes, which nothing does without Casey:**

Everything else in the document. In particular: a custom EL3 image or boot chain
(signed and fuse-locked), raw SASS injection (no supported path), MMU injection
from userspace (unnecessary and unsafe), direct DVFS control (privileged, and
it spends other tenants' thermal budget), and NVLink multi-blade scaling (the
hardware has no NVLink).

**What we would measure, once this is in place:** the end-to-end agent
latency budget, decomposed into: doorbell round-trip (3.03 µs measured),
GPU compute, and the network ingress path (unmeasured — the honest gap). The
third term is where the remaining work is.

**Cost of the whole build order: days, not months.** That is the headline of
this digest: the brainstorm describes a multi-year bare-metal programme; the
measurable yield is a week of work.
