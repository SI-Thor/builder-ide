# 09 — The QUF cell format, FP4 packing and the tensor-core path

**Source:** `googl1.md` lines 828–843 (QUF, the 144-byte cell, the hardware
register map), lines 844–887 (the FP4 tensor layout, the hardware semaphores),
lines 1554–1560 (the Hebbian update loop), lines 3445–3510 (Stage 30,
`silicon_signoff.ld`).

## What it says

The document defines **QUF (Quilt Unified Format)**: a byte-exact record layout
for a "cell" — the unit of both storage and computation.

> "Every agent session, context block, or logical thread is represented as a
> single, 144-byte padded QUF_Hardware_Cell."

> "To allow the Blackwell Tensor Cores to process data with zero conversion
> latency, the cell's memory structure is packed into a strict, byte-aligned
> format using FP4 (4-bit Floating Point) quantization for the weights. Each
> cell is padded to exactly 144 bytes to maintain strict hardware alignment
> lines across memory blocks."

The learning rule is Hebbian accumulation — `execute_hebbian_update` — with
"hyperbolic decay" applied to drop dead cells and "cell refractory states" to
prevent firing storms. Stage 23 supplies the matching SASS.

## What it means

This part is where the document becomes an actual data-format design, and it
contains one genuinely good idea and one number that will not survive.

**The good idea: a fixed-width cell record as the unit of both memory and
compute.** If the record's layout is known to the producer, the consumer and the
kernel, then a "context block" can be handed between components without
serialisation, without a schema, and without a parser. That is the shape of a
good wire format, and it is the shape that makes an agent's working set
addressable at cell granularity. The document calls it a "quilt"; it is a
record format.

**The number that will not survive: 144 bytes.** The constraint being satisfied
is alignment to a hardware access granularity — a 128-byte cache line, with
padding to keep the next cell on a fresh line. That works out to 128 bytes of
payload plus 16 bytes of header, or 96 plus 48, depending on the header layout.
144 bytes is divisible by 16 but *not* by 128, so a cell array would straddle
cache lines unless the stride were a multiple of 128. Either the document
means 128-byte stride and has mis-stated the number, or it means 144 and has
not checked the alignment.

**FP4 with zero conversion latency** is the claim that needs the most care. The
Thor does have a native NVFP4 tensor-core path, and `thor-fp4/BENCHMARKS.md`
records it working at scale. But the cell format and the tensor-core input
format are different things: the tensor cores want a specific blocked,
scale-per-block layout, not a 144-byte record. "Zero conversion latency" is
achievable only if the *cell layout is the tensor layout* — which is a
real design goal and a real constraint, and it is not free.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor's Blackwell tensor cores support native FP4 (NVFP4) | **confirmed** | `thor-fp4/BENCHMARKS.md` documents working NVFP4 paths on this Thor via CUTLASS for `sm_110a`, with the `tcgen05` block-scaled MMA kinds, and records measured throughput |
| NVFP4 uses a per-16-element block scale (E4M3) alongside E2M1 values | **confirmed** | `thor-fp4/BENCHMARKS.md` records the `e2m1 + UE4M3 per-16 block scales` format directly, matching NVIDIA's published NVFP4 spec |
| The record size of **144 bytes** is the right stride for hardware alignment | **contradicted** | 144 is not a multiple of 128, so a packed array of 144-byte cells straddles 128-byte cache lines; the last field of each cell would live in the next line. For a format whose stated purpose is "strict hardware alignment", 144 fails its own requirement. The document never shows the QUF_Hardware_Cell layout, so the intended stride cannot be recovered |
| FP4 weights can be consumed by the tensor cores with zero conversion latency | **contradicted as stated** | The tensor cores' FP4 input format is a specific blocked layout with per-block scale factors, not a general-purpose record. `thor-fp4/BENCHMARKS.md` shows the format conversion and scale handling is a real, non-trivial part of the pipeline (`lt_fp4_scalemap.cu`, `lt_fp4_scaleprobe.cu` exist to study exactly this). "Zero conversion latency" holds only in the special case where the cell layout is *already* the tensor layout |
| The Thor's L2 is 32 MB | **confirmed** | `xp-batch/sp_gc` records `l2_bytes: 33554432` (32 MiB) from the live device |
| Tensor Core "5th generation" and ~84 KiB shared memory per CTA | **plausible but unverified here** | NVIDIA's published Thor specs list 5th-gen Tensor Cores; the 84 KiB shared-memory figure was not independently confirmed on this box in this pass (`xp-batch` recorded `maxt_per_sm = 1536`) |
| Hardware semaphores (mbarrier) can synchronise CPU and GPU without software messaging | **partially confirmed, and the CPU-side claim is wrong** | `mbarrier` is a *GPU-side* CTA/cluster-scoped mechanism (PTX ISA §9.7.15). It cannot be used to signal from the CPU. The document's line 888–889 claims the CPU verifier loop and the GPU scheduler sync "without losing clock cycles to software messaging" via "Silicon Hardware Semaphores"; there is no such CPU-side mechanism. The real answer is host-mapped memory, which *is* what our measurement used |
| Hebbian accumulation with decay is implementable as written | **plausible but unverified** | Numerically it is ordinary arithmetic on FP4-quantised weights. The subtlety the document does not address: accumulating into an FP4-quantised weight in place is lossy at every step, and the accumulation needs a higher-precision shadow or the result drifts. Nothing in the document addresses this |
| "Hyperbolic decay" drops dead cells safely | **plausible but unverified** | Decay is fine. "Refractory states to protect the hardware matrix from infinite firing storms" is a rate-limiting idea; the document gives no parameters and no mechanism for a cell that fires while refractory |

**The honest summary.** The Thor has the tensor-core capability the document
needs — native NVFP4 is real and measured on this box. The specific cell
geometry (144 bytes) fails the document's own alignment rationale, and the
"zero conversion latency" claim holds only under a constraint the document does
not state: the cell layout must already be the tensor-core layout.

## Judgement

**The fixed-width cell record is worth taking. The specific 144-byte number and
the FP4-in-cell layout are not, as stated.**

Stock JetPack, today:

- **Adopt a fixed-width, byte-exact cell record for agent context.** This is
  the part of the document with a durable payoff. If builder-ide's agent
  sessions, context blocks and working sets each have a fixed-width record
  format, then components can exchange them without a schema negotiation and
  the GPU can address them directly. That is a real simplification and it costs
  nothing.
- **Fix the stride to the hardware's, not the document's.** Use a 128-byte
  stride (or 256) so a cell never straddles a cache line. This is a five-minute
  decision with a measurable consequence, and it should be made from the
  hardware's granularity rather than inherited from a brainstorm.
- **Do not design the cell to be the tensor layout.** Two formats with two
  consumers will diverge, and `thor-fp4` already has working NVFP4 paths. Keep
  the cell format a *record* format, and let the tensor path convert — the
  conversion is what `thor-fp4` already does and it is fast enough that
  optimising it away is a later problem, not a first one.
- **If you do want an FP4 cell, keep the accumulation in higher precision.**
  A shadow weight in fp16/fp32 with FP4 as the storage format is the
  conventional arrangement, and it is what `thor-fp4`'s scale-map work is
  already studying. In-place FP4 accumulation is a correctness bug waiting.

Needs OS/firmware changes, which nothing does without Casey:

- Nothing. All of this is userspace data structures and CUDA kernels.

**What we would measure.** A round-trip benchmark on the real cell format:
build cells in the producer, consume them in a tensor-core kernel, check
fidelity against an fp32 reference, and record the conversion cost as a
fraction of end-to-end latency. We have the reference machinery
(`exp-ct-thor.md` checks against host references; `thor-fp4` has the NVFP4
kernels), so the experiment is mostly assembly.

**Cost:** low for the record format, moderate for an FP4 cell with a faithful
accumulation model.
