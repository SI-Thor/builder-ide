# 04 — Warp scheduling, persistent kernels and the live I-cache

**Source:** `googl1.md` lines 115–133 (SM orchestration), lines 134–144 (live
SASS surgery and DVFS), lines 146–164 ("The Absolute Silicon Layer"), lines
720–818 (the Persistent Tile Scheduler PTX), lines 3084–3167 (Stage 26,
`register_miter.c`).

## What it says

The document proposes four layers of SM-level control:

1. **DSMEM cluster routing** — "we bypass this entirely by binding SMs into
   physical clusters", so data moves SM-to-SM through the distributed shared
   memory mesh rather than through global LPDDR5X.
2. **mbarrier** — "we handle synchronization entirely through dedicated hardware
   registers called mbarrier blocks", instead of software locks or spin loops.
3. **Live SASS surgery** — "the system must perform live surgery on its own
   active binary machine code inside the GPU's Instruction Cache (I-Cache)", so
   the AI "can adapt its logic in real-time without crashing the chip".
4. **DVFS at the register level** — "an autonomous, un-killable system cannot
   rely on a slow operating system power daemon", so it must manage its own
   thermodynamics "directly at the register level".

The Persistent Tile Scheduler PTX (line 722 onward) is the document's own
attempt at the software side of this: a warp-specialized resident kernel using
`clusterlaunchcontrol` to load-balance across SMs, with 84 KiB of shared memory.

## What it means

Layers 1 and 2 are the standard modern GPU programming model, and the document
describes them correctly. The specific claim about DSMEM is worth checking
carefully, because "DSMEM routing mesh" is often overstated: distributed shared
memory lets one CTA in a cluster address another CTA's shared memory over the
cluster interconnect, but that is a much narrower facility than a general
"fabric" — it is scoped to clusters, and it is not a substitute for global
memory traffic in general.

Layer 3 is the one that separates this document from real engineering. "Live
surgery on the I-cache" is not a documented NVIDIA capability. The GPU's
instruction memory is managed by the driver and the hardware instruction cache;
there is no supported path to rewrite the instruction stream of a running kernel
from userspace. What *is* possible is to compile a different kernel and launch
it — which is ordinary CUDA, and which the document treats as an intolerable
abstraction.

Layer 4 conflates two different things. DVFS is real: the Thor's power
management is controlled by a power daemon, and `jetson_clocks` exists (it
needs root). But an *unattended agent* managing its own clocks is the opposite
of what a shared, multi-tenant box wants. It is also unnecessary: the failure
mode DVFS protection addresses — thermal throttling under sustained load — is
handled by the existing daemon.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| Thread block clusters are supported on cc 11.0 | **confirmed** | CUDA Programming Guide Table 29: "Thread Block Cluster — Yes" for 11.0. Live device: `CU_DEVICE_ATTRIBUTE_CLUSTER_LAUNCH = 1` on the Thor |
| Distributed shared memory is supported on cc 11.0 | **confirmed** | CUDA Programming Guide Table 29: "Distributed Shared Memory — Yes" for 11.0 |
| `mbarrier` asynchronous barriers are available | **confirmed** | PTX ISA §9.7.15; verified today — `mbarrier.init.shared.b64`, `mbarrier.arrive.shared.b64`, `mbarrier.try_wait.parity.shared.b64` all assemble clean for `sm_110a` under `ptxas` |
| `clusterlaunchcontrol` is available on cc 11.0 | **confirmed** | PTX ISA §9.7.15.18–19: "Requires sm_100 or higher"; verified today — `clusterlaunchcontrol.try_cancel.async.shared::cta.mbarrier::complete_tx::bytes.b128` assembles clean for `sm_110a` |
| DSMEM is a general substitute for global memory traffic | **contradicted** | DSMEM is scoped to a thread block *cluster* and addresses peer CTAs' shared memory. It is not a general routing fabric and does not remove the need for global memory for any data that does not fit the cluster's scope. The document's phrasing ("we bypass this entirely") overstates it |
| "Sub-nanosecond latency" for mbarrier wakeups (line 3558) | **contradicted** | A same-cluster shared-memory barrier is on the order of tens of nanoseconds at best; mbarrier operations are asynchronous and their *latency* is not sub-nanosecond by any published figure. The document's own Stage 25 code, by contrast, polls in a loop, which is the opposite of the claim |
| We can rewrite the GPU's instruction cache while a kernel runs | **contradicted** | No documented NVIDIA mechanism. `cudaGraphExecUpdate` replaces a *graph*, not running code; there is no supported instruction-cache write path from userspace |
| A persistent, warp-specialized tile scheduler is the right way to keep SMs busy | **confirmed, and measured** | Measured first-hand today: the persistent ring reached 313,155 jobs/s at p50 3.03 µs versus 99,991 jobs/s at p50 69.27 µs for per-job launches. The document's instinct — a resident scheduler beats repeated launches — is the one part of this section that survived contact with the hardware |
| 84 KiB of shared memory per CTA | **plausible but unverified** | `sp_gc` recorded `maxt_per_sm = 1536` threads/SM and the CUTLASS `sm_110a` kernels in `thor-fp4` use large shared allocations, but the exact 84 KiB figure for cc 11.0 was not independently confirmed here |
| We should write our own DVFS control to manage thermals | **contradicted** | The Thor's power daemon already does this. `nvidia-smi` on Thor reports clock and power as `N/A` (cannot be locked; `jetson_clocks` needs root) — the platform deliberately centralises this. A userspace agent fighting the daemon would be a bug source, not a feature |
| A shadow "miter" CPU model can detect a divergent GPU path and hot-patch it | **plausible but unverified** | The idea (a cheap reference model checking a fast path) is sound engineering and is used in practice. The specific claims — "un-patchable, formally proven", "healing the system mid-stride" — are not achievable as stated: you cannot hot-patch GPU code (see above), so the miter can only *detect and signal*, not heal |
| The `register_miter.c` (Stage 26) check-gate is worth having | **plausible but unverified** | A descriptor/register auditor is a reasonable defensive measure for a bare-metal system. It is untested and, for a userspace builder-ide agent, largely redundant with CUDA's own error checking |

**The honest summary.** Clusters, DSMEM, mbarrier and CLC are all real on the
Thor and all assemble for `sm_110a` — I checked the encodings directly. The
document's *use* of them (persistent scheduling) is right and is measured. Its
*extensions* (live I-cache surgery, register-level DVFS, mid-stride hot-patching)
are not available and are not needed.

## Judgement

**Take the persistent-scheduler half. Leave the rest.**

Stock JetPack, today:

- **Use a persistent, warp-specialized resident kernel** where the work is
  fine-grained and frequent. This is the measured win (3.03 µs vs 69.27 µs p50)
  and it uses only documented CUDA.
- **Use `mbarrier` and clusters when the dataflow is genuinely producer/consumer
  across CTAs.** Both are available on the Thor; both are ordinary CUDA
  (`cuda::barrier`, cooperative groups). Do not hand-write PTX for them —
  `ptxas` handles it, and I verified the encodings assemble.
- **Do not attempt live I-cache modification.** Not supported, not needed, and
  it is the point where the document stops being engineering.
- **Leave DVFS to the platform.** `jetson_clocks` needs root and the daemon
  already exists; the box is multi-tenant and its other tenants' thermal budget
  is not ours to spend.
- **Keep the miter idea as a testing practice, not a runtime mechanism.** A
  cheap reference model cross-checking a fast path is good practice; it is
  *detection*, not *self-healing*.

Needs OS/firmware changes, which nothing does without Casey:

- Writing the GPU instruction cache from outside the driver. No public path.
  Out of scope.

**What we would measure.** For a producer/consumer pipeline on the Thor: whether
an mbarrier-based consumer keeps its p99 within a stated factor of the idle p99
while a producer runs at full rate — i.e. the same shape as the `sp_gc` harness
already built (`sp_host.cpp` measures device-side duration with `%globaltimer`,
correctness against a host reference, and a background load). That harness is
reusable; the question is only what to point it at.

**Cost:** low to moderate. The persistent scheduler is hours. The miter as a
runtime self-healer is unbounded and out of scope.
