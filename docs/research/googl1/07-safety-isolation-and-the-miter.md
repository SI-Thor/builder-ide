# 07 — Safety, isolation and the shadow miter

**Source:** `googl1.md` lines 51 ("there is no software to crash"), lines
2900–3001 (Stage 24, `cosim_miter.c`), lines 3084–3167 (Stage 26,
`register_miter.c`), lines 3545–3548 ("Layer A: The Control & Miter Plane"),
line 188 (the Free Energy Principle as the safety law).

## What it says

> "By engineering the system this way, there is no software to crash. If a bit
> flips or an operation fails, it manifests as a hardware flag in a status
> register. The system reads that register, alters its next command queue, and
> keeps moving."

The formalisation is the **miter**: a shadow copy of the logic running on the
CPU in parallel with the fast GPU path.

> "While the GPU executes fast, speculative code, a cluster of CPU cores executes
> an un-patchable, formally proven behavioral model of the same logic. If the
> outputs of the two paths diverge by even a single bit, a hardware exception is
> tripped via the GICv4 controller, the corrupted memory space is isolated, and
> the CPU hot-patches the GPU's instruction cache with a stable baseline
> binary—healing the system mid-stride without dropping the incoming API
> connection."

Stage 20 adds a formal property contract (`formal_contracts.sby`) using SMT
solving (boolector) to "mathematically prove that its memory allocations can
never breach their bounds, its internal state variables will never leak energy,
and its global clock tick deadlines can never be starved."

## What it means

The miter idea is genuinely good engineering and predates this document by
decades — it is what a redundant flight-control computer does, what a CPU
shadow in a GPU emulator does, and what differential testing does everywhere.
The document's contribution is to apply it to a self-modifying agent.

Two of the document's specific mechanisms do not survive contact with the
hardware:

1. **"Hot-patches the GPU's instruction cache."** There is no supported path to
   write GPU instruction memory from userspace (part 04). A miter can *detect*
   divergence and *signal*; it cannot heal in place.
2. **"Un-patchable, formally proven behavioural model."** Two separate
   overreaches. "Un-patchable" describes the EL3 secure memory of the CPU side,
   which is real, but it does not make the model *correct* — a formally proven
   model of the wrong specification proves the wrong thing. And "100% stable
   under all conceivable environmental request conditions" (line 2472) is not
   what an SMT solver can deliver: it proves a bounded model, and the document
   never states the bound.

The Free Energy Principle as the safety law (line 187–193) is the document's
weakest technical move dressed as its deepest. Friston FEP is a modelling
framework in theoretical biology — a variational account of self-organising
systems. It is not a specification of memory-safety invariants and cannot be
compiled into a register mask. The document's own framing — "the un-erasable
Seed Cell in the EL3 BootROM must be programmed with a law derived from
biophysics" — asks for a bit pattern, and FEP is not one.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| Errors surface as hardware status flags rather than crashes | **plausible but unverified** | Hardware does report ECC and other error status; the Thor's 128 GB LPDDR5X is ECC-protected in principle. The document's specific "read the flag, alter the next command queue, keep moving" is not a documented flow |
| The Thor has a GICv4 | **contradicted (the name), confirmed (the function)** | Arm's GICv3 with LPIs is what Neoverse-V3AE implements; GICv4 is the Arm GICv4 design used in some Cortex-A/X parts. The *function* — a programmable interrupt controller with CPU affinity, and a way to raise an exception on a specific core — is present, and the document's use of it is sound. The specific version number is wrong |
| The CPU can hot-patch the GPU's instruction cache mid-flight | **contradicted** | No documented NVIDIA mechanism for userspace instruction-cache modification (part 04) |
| A shadow model can detect divergence between a fast path and a reference model | **confirmed** | Standard differential-testing practice, and the same shape `xp-batch/sp_gc` uses: it checks every window's result against a host reference and records max rel err (2.25e-06 for the GEMV, 3.443e-06 for the partition SGEMM) |
| SMT solving can prove memory bounds and clock deadlines | **confirmed as a method, contradicted as stated** | `formal_contracts.sby` is a legitimate SymbiYosys/`boolector` setup. What it proves is bounded: over the modelled bound, not "all conceivable conditions" |
| "Proves state variables will never leak energy" | **contradicted** | Energy leakage is not a property an SMT solver over a C model can prove; it is a physical property. The document conflates the model's energy variable with physical energy |
| A miter can isolate corrupted memory without dropping the connection | **plausible but unverified** | Isolation of a region is possible (we can free or quarantine host memory); dropping the connection is a policy choice, not a hardware fact |
| GICv4's exception mechanism can be used to signal a divergence to a specific core | **plausible but unverified** | The GIC is present; the specific flow is untested here. Note the device tree on this Thor exposes no `interrupt-controller` node we could read directly (the topology is behind BPMP), so the interrupt structure was not verified from the box |

**The honest summary.** The miter is the best idea in the document and it needs
none of the document's own mechanisms to work. Differential checking against a
reference model is ordinary practice and we already do it on every measurement.
What is wrong is the healing half (no instruction-cache write path) and the
formal-proof half (bounded proofs described as universal).

## Judgement

**Take the miter as a testing discipline. Discard the self-healing and the
formal-proof framing.**

Stock JetPack, today:

- **Adopt differential checking as a standing practice for anything we run on
  the Thor.** We already do it: `exp-ct-thor.md` records "max rel err" against
  host references for every kernel; `xp-batch` records it for the GEMV, the
  SGEMM and the persistent-ring dot product. Formalise it: every numerically
  meaningful path we ship gets a reference check and a recorded error bound.
- **Use the miter for detection and gating, not healing.** A divergence should
  raise an alarm, fail the request, and fall back to a known-good path — not
  attempt to rewrite GPU code.
- **Do not put a "loss metric" or FEP into a boot ROM.** Write the invariant you
  actually mean (e.g. "a cell write never changes an unrelated cell") and check
  it. The document's own example — memory bounds and clock deadlines — is
  exactly right and can be checked with a model checker over a bounded horizon,
  which is what the `formal_contracts.sby` file actually does.
- **Do not chase GICv4.** Use whatever the platform gives; the document's version
  number is wrong and the function is available anyway.

Needs OS/firmware changes, which nothing does without Casey:

- None for the testing discipline. The self-healing form would need GPU
  instruction-memory write access, which does not exist publicly.

**What we would measure.** For the agent-world path: the divergence rate between
the fast path and its reference model, per 10^5 operations, under adversarial
input. A non-zero rate in a trusted path is the finding; the number is what
decides whether the fast path is shippable.

**Cost:** low for the discipline, unbounded for the self-healing form.
