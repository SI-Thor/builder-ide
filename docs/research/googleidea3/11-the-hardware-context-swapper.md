# 11 — The hardware context swapper (Stage 39)

**Source:** `googleidea3.md` lines 1298–1377 (`context_swapper.c`, "The
Tensor Virtualization Matrix Is Sealed"); the concurrency claims repeat at
lines 1521–1525 (part 13).

**Relation to the corpus:** googl1's parts 04/06 were the scheduling and
partitioning parts (persistent kernels; Green Contexts and MIG);
googleidea3 answers the same need — "multitasking without a software
scheduler" — with invented GPU registers. googleidea2 promised the same
property via "Warp 0 Management Core" doorbells.

## What it says

> "Saves raw registers (R0-R31) and predicate flags (P0-P7) straight to
> hardwired physical RAM buffer spaces … cutting traditional software
> context-switch latencies down to raw silicon speed."

Three registers at 0x50002000/08/10: a control slot with SAVE/RESTORE
command bits and a BUSY flag, a save-area pointer, an active-context id.
`switch_active_tensor_context` polls BUSY, points the save area at one of
four 64-byte-aligned context buffers, fires SAVE, polls BUSY, retargets,
fires RESTORE. Four "isolated execution context tracks"; competing tasks
swap "in picoseconds", "without a context-switch stall".

## What it means

The claim is that the GPU exposes a user-programmable
snapshot/restore-engine for execution contexts, so "processes" can be
multiplexed by writing three registers instead of by software scheduling.
This is the hardware fantasy version of a real problem we have measured
(this box serves a night agent *and* tenants): how do competing GPU
workloads share the machine without starving each other?

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| GPU context-save/restore registers exist at 0x50002000 | **contradicted (invented; address self-collides)** | No such interface is published; and 0x50002000 lies *inside* the document's own GPU command ring extent (0x50001000 + 1024×24 B — part 03). The "context registers" would sit on top of ring slot #64 |
| A GPU context is "R0–R31 + P0–P7" | **contradicted** | That is a *CPU* register file pasted onto a GPU. An SM thread's architectural state is per-thread registers in packs (R0–R255 per thread on modern SMs), predicates, plus per-warp/CTA state; a *channel's* context in the host interface is queues, pushbuffers, and runlist state — nothing like a 64-byte CPU frame |
| Context switches take "picoseconds" | **contradicted as to scale** | Nothing on this machine switches contexts in picoseconds; the *measured* relevant numbers: ring doorbell-to-result 3.03–3.21 µs p50; a whole GPU work-context switch (preemption between channels) is µs-to-ms class. The claim is ~6 orders off the fastest real number we have |
| Real hardware multiplexes GPU work without our software scheduler | **confirmed (differently)** | The host interface schedules channels via runlists (NVIDIA open-gpu-kernel-modules documentation); CUDA exposes the controllable subset: streams, MPS, and — on this box, measured — **Green Contexts** (partitions A=4/B=16 SMs; 1195/1200 live launches served under a heavy background where both stream-priority conditions served 1/1200 — googl1 part 06) |
| "Warp-level concurrency isolation … without cache-eviction delays" | **contradicted by our measurement** | Partitioning does *not* partition DRAM: live p50 6.3× idle and p99 37× the bar under the split — the memory system is shared (googl1 part 06; MIG likewise compute-only, `exp-mig.md`) |

**The honest summary.** The problem is real and already solved to the
extent this machine allows: the supported mechanisms are the resident ring
(no per-job context at all — that *is* "no context switch", measured at
3 µs) and Green Contexts as a service floor. The snapshot registers are
invention, the register file is a CPU's, and the isolation promise
collides with the measured fact that DRAM bandwidth is the shared
resource no partition protects.

## Judgement

Stock JetPack, today — this is googl1 part 13's runtime again, and it is
already the answer: resident ring for dispatch (no context to swap), a
Green Context lane as the *service floor* for live work (with the recorded
latency price: p50 0.737 ms / p99 5.418 ms under load, so nobody expects
magic), and the background-bandwidth policy as the actual lever.

Needs Casey: a published preemption/context API — nothing needs it; the
mechanisms above are supported and measured.

**Cost:** zero beyond what googl1 part 13 already listed. **What we would
measure:** nothing new — the service-floor numbers are the standing
record.
