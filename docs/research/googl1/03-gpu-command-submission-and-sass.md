# 03 — GPU command submission: doorbells, work queues and raw SASS injection

**Source:** `googl1.md` lines 28–32 ("4. Raw SASS Injection"), lines 55–74 (the
self-directed graph), lines 1062–1066 ("The Completed Architecture" — the
`DOORBELL` register and `WorkSubmissionQueue`), lines 2794–2897 (Stage 23,
`tma_tensor_core.sass`).

## What it says

> "We bypass the entire CUDA driver stack (nvcc, libcuda.so, runtime layers).
> They are too heavy and slow."

The mechanism proposed: instead of the CUDA driver, the machine writes
`HardwareCommand` descriptors into a memory-mapped work queue and then writes to
a physical `DOORBELL` register; the Blackwell Host Command Processor picks it up
and dispatches to the SMs. The GPU side runs "raw SASS machine code instructions
injected straight into the Blackwell Streaming Multiprocessor (SM) warp
schedulers", with a "Persistent Tile Scheduler" that "runs continuously,
bypassing CPU kernel launches entirely."

The document's own Stage 23 supplies hand-written SASS for a tensor-core loop,
and the `linker.ld` maps a "hot-swappable instruction stream" region so the GPU's
code can be rewritten while running.

## What it means

This is the most technically serious part of the document, and it is also where
the document is most nearly right and most nearly wrong at the same time.

**What is right.** The Blackwell GPU does have a doorbell-style submission path.
A host writes a command into a channel's push buffer and rings a doorbell; the
GPU's host interface fetches and dispatches it. The idea of a persistent GPU-side
scheduler that pulls work from a queue rather than being launched per job is
exactly how modern GPU inference engines work. The document has the right
*shape*.

**What is wrong.** "Bypass libcuda.so" is not a design goal; it is a description
of a different, much worse engineering approach. The driver is not "heavy and
slow" in the hot path — the *launch* is expensive, and the document correctly
identifies that, but the fix for an expensive launch is a resident kernel and a
queue, not a reimplementation of the driver. Writing SASS directly buys nothing
that a resident kernel does not already buy, and costs you ptxas, the profiler,
the correctness tooling, and every future ISA.

**What is unknowable.** The specific `DOORBELL` register addresses in the
document (`0x40001000`, `0x40002000`) are the document's invention. NVIDIA's
actual doorbell addresses are not public.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor's GPU is Blackwell, sm_110 (cc 11.0) | **confirmed** | Live device query on the Thor: `COMPUTE_CAPABILITY_MAJOR=11`, `MINOR=0`, `MULTIPROCESSOR_COUNT=20`. `nvidia-smi` reports "NVIDIA Thor", driver 595.78, CUDA 13.2 |
| The GPU can run a persistent resident kernel that pulls work from a queue, without per-job launches | **confirmed** | Measured first-hand on the Thor today under `thor-admit`: the persistent-ring probe reached **313,155 jobs/s**, p50 **3.03 µs**, p99 **5.42 µs**, rel err 2.41e-08. The per-job launch path in the same probe managed 99,991 jobs/s at p50 **69.27 µs** and *stalled at job 1* under contention |
| Blackwell has Cluster Launch Control (CLC) for dynamic cluster scheduling | **confirmed** | PTX ISA §9.7.15.18–19 defines `clusterlaunchcontrol.try_cancel` / `.query_cancel`, "Requires sm_100 or higher". Assembled and verified for `sm_110a` with `ptxas` today: `clusterlaunchcontrol.try_cancel.async.shared::cta.mbarrier::complete_tx::bytes.b128` compiles clean for `sm_110a` |
| The Thor supports thread block clusters and distributed shared memory | **confirmed** | CUDA Programming Guide Table 29 (Feature Support per Compute Capability): Thread Block Cluster, Distributed Shared Memory and the TMA unit are all "Yes" for cc 11.0; live `CU_DEVICE_ATTRIBUTE_CLUSTER_LAUNCH = 1` on the Thor |
| The Thor supports the TMA (`cp.async.bulk.tensor`) | **confirmed** | PTX ISA §9.7.10.28.4: "Requires sm_90 or higher", with `sm_110a` listed among the family-specific architectures. Verified today: `cp.async.bulk.tensor.1d.shared::cluster.global.mbarrier::complete_tx::bytes.tile` assembles clean for `sm_110a` |
| `mbarrier` asynchronous barriers are available | **confirmed** | PTX ISA §9.7.15; verified today: `mbarrier.init` / `arrive` / `try_wait.parity` assemble clean for `sm_110a` |
| The specific DOORBELL register addresses in the document are the real Thor ones | **unknowable without NVIDIA's private docs** | NVIDIA does not publish the Blackwell host-interface doorbell map. The document's `0x40001000` / `0x40002000` are its own invention and must not be trusted |
| We can inject raw SASS into the SMs of a stock JetPack Thor | **contradicted** | No public mechanism. `ptxas` produces cubins loaded through the driver; there is no documented path to write the SM instruction cache from userspace. The document's own "live surgery on the I-cache" (line 134) has no supported implementation on this box |
| Bypassing libcuda.so would be faster | **contradicted** | The measurement says the opposite: the persistent kernel *through* the driver stack achieves 3.03 µs p50. The driver is not the cost; the per-job launch is |
| A hand-written `tma_tensor_core.sass` tensor-core loop is necessary | **contradicted** | `thor-fp4/BENCHMARKS.md` records working NVFP4 tensor-core paths on this same Thor, at scale, using CUTLASS and `tcgen05`. Hand-written SASS is a large cost for no measured gain |

**The honest summary.** Every hardware capability the document names for the GPU —
clusters, DSMEM, TMA, mbarrier, CLC — is real and present on the Thor, and I
verified the instruction-level encoding of three of them today. What does not
follow is the document's conclusion that you must therefore bypass the driver.
The capabilities are reachable *through* the driver. The expensive thing is the
per-job launch, and the fix is a resident kernel — which we measured, and which
needs no SASS, no doorbell addresses, and no MMU ownership.

## Judgement

**The mechanism is worth taking; the framing is worth discarding.**

Stock JetPack, today:

- **Adopt a persistent resident kernel fed by a host-side queue.** This is the
  single highest-value technique we found, and it is measured (part 11). It
  requires nothing privileged: a `cudaMallocHost` ring, one resident kernel, and
  a doorbell write. `CUDA_NON_BLOCKING` streams are required for green-context
  streams, but the persistent ring itself needs no green context.
- **Do not write SASS.** Use `ptxas` via `nvcc`, or CUTLASS as `thor-fp4` already
  does. Hand-written SASS would cost us the assembler, the disassembler, and the
  ability to move to the next architecture.
- **Do not chase the doorbell register.** If we want the driver's own doorbell
  path, we get it by using the driver. If we want to avoid the launch cost, we
  avoid the launch.
- **Keep CLC in mind for later, not now.** CLC is about cancelling clusters that
  have not started — it is a scheduling-latency tool, valuable once we have
  long-running persistent work whose latency matters and whose cancellation
  must be prompt. That is a real future item, not a current one.

Needs OS/firmware changes, which nothing does without Casey:

- Injecting SASS into SM instruction memory at runtime. No public mechanism on
  this box. Out of scope.

**What we would measure.** Already measured: 313 k jobs/s at 3.03 µs p50 through
the persistent ring, versus 99,991 jobs/s at 69.27 µs p50 per-job launch, in the
same process on the same box, with correctness checked against a host reference
(rel err 2.41e-08).

**Cost:** hours to a day to adopt the persistent pattern in builder-ide; the
SASS-injection path is unbounded and out of scope.
