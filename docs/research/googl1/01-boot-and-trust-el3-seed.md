# 01 — Boot and trust: the EL3 BootROM seed

**Source:** `googl1.md` lines 1–13 ("1. The EL3 BootROM Seed"), and the recurring
"un-erasable EL3 BootROM Seed" motif at lines 82–86, 166, 187, 3552.

## What it says

> "When the Thor SoC receives power, the 14-core ARM Neoverse V3AE cluster doesn't
> know what an AI is. It executes blind silicon instructions."

The proposed mechanism is a *seed*: an immutable cell burned at manufacture (or at
first boot) into the EL3 BootROM, which on every power-on reset re-establishes the
whole execution graph. Later the document sharpens the ask:

> "The system constantly mutates its own SASS binary machine code … We enforce this
> not via software permissions, but through the ARM processor's physical hardware
> virtualization states." (lines 82–86)

and

> "What foundational survival directive or loss metric will you hardcode into its
> permanent, un-erasable EL3 BootROM Seed?" (line 166)

Stage 0 of the code cascade (`main_entry.c`) and Stage 29/30 (`boot_signoff.c`,
`silicon_signoff.ld`) are the concrete expressions of this: clear memory, build the
baseline cell matrix, engage the global tick, never return.

## What it means

The claim rests on three separable assertions:

1. **The CPU begins execution at EL3.** The EL3 BootROM is the first code to run
   after reset, before any OS, and it hands off to the next stage.
2. **EL3 memory can be made immutable** (TrustZone / secure memory, SCR_EL3.NS bit,
   TZASC secure memory regions), so a seed cell cannot be overwritten by the running
   system.
3. **The seed is the root of trust** — if it is immutable and it decides what runs,
   then everything above it is derivable from it, and the system can "heal" itself
   to a known-good baseline.

Assertion 1 and 2 are well-established Arm architecture. Assertion 3 is where the
document does its real work: it is proposing that the *seed* (not the kernel, not
the GPU) is the thing that makes the machine trustworthy.

Note what this is not: it is not a proposal for an ordinary bootloader. The
document's own later sections (lines 941–968) explicitly reverse course and argue
that "over-engineering a custom bare-metal loop" is a mistake, because throwing
away the driver stack isolates you from NVLink routing and hardware graph
schedulers. The EL3 seed idea survives that reversal as *trust*, not as *execution*.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor CPU cluster is 14-core Arm Neoverse-V3AE | **confirmed** | NVIDIA's published AGX Thor spec lists a 14-core Neoverse-V3AE CPU; `exp-ct-thor.md` measured 14 online cores, and the live box reports 14 `ete_cpu_*` nodes in `/proc/device-tree` |
| The SoC is `tegra264` (Thor), part `p4071-0000` | **confirmed** | `/proc/device-tree/compatible` on the Thor reads `nvidia,p4071-0000+p3834-0008 nvidia,p3834-0008 nvidia,tegra264` |
| EL3 exists and is the reset entry point | **confirmed** | Arm architecture; Jetson Linux boots through BPMP → MB1 → MB2 → XBP (UEFI), with MB1 running at EL3 |
| Memory can be made immutable via Arm hardware virtualization | **confirmed** | Arm ARM: TrustZone secure memory regions (TZASC), SCR_EL3.NS |
| We can write our own EL3-level boot code on the Thor | **contradicted** | Jetson Linux's boot chain is signed and fuses are locked in production. NVIDIA provides the `flash_layout`/MB1 BCT mechanism; a third party cannot substitute an arbitrary EL3 image. NVIDIA's *Jetson Linux Developer Guide*, "Boot Configuration" — the BR-BCT is signed by NVIDIA |
| The seed can be made "un-erasable" | **plausible but unverified** | The fuses and the signed chain make it *very* likely, but the exact granularity (per-sector OTP vs whole-chain signature) is NVIDIA-internal |
| The "un-erasable seed" can encode a *loss metric* or a *Free Energy Principle* directive | **contradicted** | Not a hardware question but a category error: a boot ROM stores bits, not an objective function. The document's own framing ("hardcode into the BootROM") asks for a number, not a law. See part 12 |

**The honest summary.** The Arm mechanics are real and confirmed. The Thor has a
secure boot chain with an EL3 stage. What we cannot do is *write* it: NVIDIA's
signing and fuse model makes a custom EL3 image impossible on a stock module, and
that is a deliberate supply-chain property, not an obstacle to be engineered around.

## Judgement

**Worth doing for us, cheaply, in a different form.**

The instinct behind the seed idea is right — builder-ide's night agent runs
unattended on hardware we do not physically attend to, and the question "what
establishes that the thing that came back up is the thing I left running?" is a
real one. But the answer is not a custom EL3 image; it is **attestation at the
user-space level**: a measured, signed, monotonic record of what the running
process believes it is, checked against something the process cannot rewrite.

What we could measure, on stock JetPack, today:

- Whether the Thor's boot chain surfaces a measurable, verifiable boot state
  (e.g. the OEM fuse/boot-chain attestation NVIDIA exposes for Thor) that a
  user-space process can read.
- Whether a signed, append-only journal of "what I launched and what I observed"
  survives a reboot, and whether verifying it is cheaper than re-deriving state.

What needs OS/firmware changes, which nothing does without Casey:

- Any modification of the EL3 stage, the BR-BCT, or the flash layout. This is a
  signed-chain break. It would require NVIDIA to sign, or a module with unlocked
  fuses and an accepted risk posture. **Not a project; a boundary.**

**Cost:** low for the attestation form (a day or two of measurement, no kernel
changes); categorically high and out of scope for the seed form.

**Register note.** The document's phrasing here — "the system is entirely
self-contained, self-governing" — is rhetoric about the architecture, not a
claim about what any of us can deploy. The digest should not inherit it.
