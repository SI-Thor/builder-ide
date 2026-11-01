# 10 — The "no OS" vision: is eliminating software the goal?

**Source:** `googl1.md` lines 1–3 (the opening thesis), lines 941–968 (the
explicit reversal — "The Macro View" and the Execution Graph paradigm),
lines 3512–3602 (the Quilt Non-OS Multi-Blade Architecture), lines 51
("there is no software to crash"), lines 366–372 and 469–472 ("The software
loop is dead").

## What it says

The document opens with its thesis:

> "To build this on the AGX Thor, you do not write software or an operating
> system; you eliminate the abstraction layers entirely so that hardware
> registers directly drive execution."

and it closes with the same thesis in its most complete form: a three-plane
architecture (Control & Miter on CPU at EL3, Fluid Memory Fabric in unified
memory, Compute Plane as raw SASS in the SMs) in which

> "Software, drivers, operating systems, and human debugging interventions have
> been removed."

But the document contains its own reversal, at lines 941–968, and the reversal
is the most engineering-sound passage in the whole file:

> "Stepping back from the register-level micro-management reveals the fundamental
> architectural flaw of over-engineering a custom bare-metal loop: a truly
> AI-native system does not micro-manage hardware instructions manually; instead,
> it treats the entire computer as a single, compiled, immutable execution graph."

The comparison table that follows makes the point cleanly: code becomes
declarative dataflow; compilation becomes graph compilation (XLA / TensorRT);
execution becomes hardware DMA triggering end-to-end silicon paths; optimization
becomes an automated compiler redefining graph topology.

## What it means

The document has two incompatible theses and does not resolve them:

**Thesis A (the bulk of the file):** software is overhead; the machine should be
a hardwired state machine with a boot seed and no OS.

**Thesis B (lines 941–968 and the closing macro view):** software is the point;
the machine should be a compiled, immutable execution graph managed by
off-the-shelf compilers and hardware schedulers.

Thesis B is the one the document's own analysis supports, and it is also the one
consistent with everything we measured. Our 3.03 µs persistent-ring result is
Thesis B: a resident kernel, a compiled artifact, a hardware-scheduled queue,
zero OS involvement, and 313 k jobs/s. Our Green Contexts result is Thesis B:
the driver partitioning SMs, the hardware scheduling within them. Nothing in
either measurement required removing the driver, and in both cases *removing the
driver would have removed the mechanism*.

The recurring error in the document is a category confusion between **the
system's architecture** and **the system's implementation**. A machine whose
control plane is a compiled graph is still running software. The document
repeatedly slides from "the architecture is a dataflow graph" to "therefore
software must go", and the slide is what generates the 30-stage cascade of
hand-written register pokes.

There is also a cost the document never accounts for: the thing it eliminates —
the operating system, the driver, the compiler — is the thing that provides
*fault isolation, memory safety, observability, and updateability*. "There is no
software to crash" is true in the sense that a hardwired state machine cannot
crash in the way a process can; it is also true that it cannot *report* that it
is stuck, cannot be patched, and cannot be tested. The document's own Stage 25
acknowledges this by implementing a watchdog reset — the OS's job, reimplemented
badly, in a place where a bug is a brick.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor's GPU can run a hardware-managed execution graph without per-job CPU involvement | **confirmed** | CUDA Graphs; and our own persistent-ring measurement (313 k jobs/s, p50 3.03 µs, no per-job launch) is the same property achieved directly |
| The Thor's compiler stack (XLA/TensorRT, CUTLASS) can produce the optimised graphs | **confirmed** | `thor-fp4/BENCHMARKS.md` records working CUTLASS `sm_110a` NVFP4 kernels on this Thor, including the `tcgen05` block-scaled MMA kinds |
| The hardware schedules the graph | **confirmed** | CUDA Graphs; Green Contexts let the driver partition SMs and the hardware schedules within them (measured: partitions A=4, B=16 SMs, concurrent SGEMMs overlapping 1.00) |
| "Hardware registers directly drive execution" with no driver | **contradicted as a practice** | Every mechanism we verified runs *through* the driver: Green Contexts are a driver API; CUDA Graphs are a driver feature; the persistent ring is an ordinary CUDA kernel plus a host-mapped buffer. There is no supported way to remove the driver and keep the hardware scheduling that makes the machine fast |
| A bare-metal image with no OS can run on a stock Thor | **contradicted** | The boot chain is signed and fuse-locked: BPMP → MB1 → MB2 → XBP (UEFI) → kernel. A custom EL3 image requires NVIDIA to sign it or unlocked fuses. `nvidia-smi`/`cuda` allocate against the signed BCT partition table |
| "There is no software to crash" | **contradicted** | A hardwired state machine has strictly worse failure properties than a process: a bug is a brick, not a restart. The document's own answer — a watchdog reset — is the OS's job, done worse |
| Removing the OS would improve throughput | **contradicted** | Our measurements are the counter-evidence: the best result we have (3.03 µs p50) was achieved *with* the full CUDA stack in place, by changing the work decomposition rather than by removing software |
| The three-plane architecture (EL3 control, memory fabric, SASS compute) is a coherent description | **plausible but unverified** | As a *description* it is a reasonable decomposition of concerns. As a *build instruction* it depends on the parts established as contradicted above (custom EL3 image, raw SASS injection, NVLink multi-blade) |
| The document's own reversal (graph-native, not OS-free) is the sound conclusion | **confirmed by our measurements** | The persistent ring and Green Contexts results are both "compiled immutable artifact + hardware scheduling", i.e. Thesis B, without removing anything |

**The honest summary.** The document reaches a correct conclusion by the wrong
route, and then spends 30 stages on the wrong route. The right reading is:
*keep the OS and the driver, remove the per-job launch, and let the hardware
schedule what is left*. That is precisely what the measured results show.

## Judgement

**This part is the framing, and the framing is what we should keep. The
implementation program it generates is what we should drop.**

Stock JetPack, today:

- **Adopt Thesis B as the design principle.** Builder-ide's agent runtime should
  be a compiled, immutable artifact with a hardware-scheduled queue — not a
  Python process issuing launches. This is already what the measurement
  recommends and it needs no kernel work.
- **Do not attempt to remove the OS or the driver.** The measurements are
  decisive on this: the mechanisms that make the Thor fast (Green Contexts,
  CUDA Graphs, the persistent ring) are all driver-mediated. Removing the
  driver removes the mechanism. It also removes the update path, the
  observability and the fault isolation that an unattended night agent needs
  more than a hand-written loop does.
- **Treat "eliminate abstraction" as a cost question, not a virtue.** Every
  abstraction removed must be replaced by something with a test suite, an error
  path, and a failure mode. The document's 30 stages mostly do not.
- **Keep the three-plane decomposition as a way of thinking, not a build plan.**
  "Control plane on CPU, data in unified memory, compute on GPU" is a good way
  to describe where a fault or a latency comes from.

Needs OS/firmware changes, which nothing does without Casey:

- The entire bare-metal program. Signed boot chain, fused OTP, custom EL3.
  Out of scope and, on the evidence, counterproductive.

**What we would measure.** Nothing new here — this part's verdict comes from the
measurements already made. The useful thing to record is the *decision*: the
agent runtime is a compiled artifact with a resident kernel, not a bare-metal
image. Writing that decision down prevents the next brainstorm from re-deriving
it.

**Cost:** zero. This is a decision, not a project.
