# 03 — The invented register map and the GPU command path

**Source:** `googleidea3.md` lines 279–348 (the `#define` register map of
`main.c`), lines 444–473 (`emit_graph_node`, `dispatch_graph_hardware`),
lines 515–576 (`bare_metal_interrupt_handler`,
`initialize_hardware_irq_routing`, `hardware_signoff_kickoff`).
`docs/googleidea3/probes/snippet-as-is.c` is the compile check.

**Relation to the corpus:** the direct descendant of googl1's part 03
(doorbells, work queues) and googleidea2's invented MMIO set
(`0x50004000` doorbell, `0x3F000100` heartbeat) — the addresses change
between documents, which is itself the tell: three documents, three
different "physical silicon" maps.

## What it says

> "REG_GPU_DOORBELL 0x5000F000 — Physical Silicon Doorbell Execution Pin."

A platform map: NIC ingress/egress rings at 0x20000000/0x20001000/0x20002000,
GPU command head/tail at 0x50000000, command ring at 0x50001000, hardware
semaphores at 0x40000000, watchdog at 0x3C000000, GPU error status and a
thermal diode at 0x60000000, "GICv4" distributor/interface at 0x3D000000.
Submission: `emit_graph_node` writes a 24-byte `HardwareCommand` into a
1024-slot ring with head/tail bounds checks and `dmb ishst` ordering, then
`dispatch_graph_hardware` writes the tail to the doorbell register. The
interrupt handler routes "line 32" (network frame) into a ring→cell
dispatch and "line 33" (miter fault) into a reboot.

## What it means

The submission code is a correct-shaped *ring discipline*: check fullness,
write the descriptor, barrier, publish the tail — the same release/acquire
discipline our measured ring uses (paper 61). Everything around it — every
address, the interrupt numbers, the GIC programming — is invented, and the
interrupt code fails to compile, which settles how much of this ran before
being written down.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The ring discipline (fullness check → descriptor → `dmb ishst` → publish tail → doorbell) | **confirmed as a shape, measured through the driver** | Paper 61's ring is exactly this discipline and measured 3.03 µs p50 / 313 k jobs/s, rel err 2.4e-08; the ingress form 3.21 µs p50, bit-exact over 50,000 frames (attempt 3, 2026-11-01) |
| `REG_GPU_*`, `REG_NIC_*`, `0x40000000` semaphores, `0x3C000000` watchdog, `0x60000000` error/thermal | **contradicted** | All invented. The real Thor map is in the device tree (e.g. `ethernet@A808910000`); NVIDIA publishes no user-writable GPU doorbell register (googl1 part 03: "unknowable without NVIDIA's private docs", and the invented `0x40001000` was flagged there too) |
| A GPU command ring sits at 0x50001000 with 1024×24 B slots | **contradicted internally** | 1024 slots × 24 B = 0x6000 bytes from 0x50001000 — the region *contains* the document's own `REG_GPU_CTX_SWITCH_CTRL` at 0x50002000 (Stage 39, part 11). The command ring and the context registers would overlap |
| The NIC registers at 0x20000000 coexist with the linker map | **contradicted** | 0x20000000 is `LPDDR5X_CODE` in the document's own `linker.ld` (part 02) |
| "GICv4" with GICD/GICC at 0x3D000000 | **contradicted** | The live device tree: `interrupt-controller@8146000000`, compatible **`arm,gic-v3`**, with an `its@8146040000` child (an ITS exists only on GICv3+). Wrong version, wrong base — and "GICv4 exception tables" conflates the core's VBAR vectors with the GIC's version |
| Unmasking "lines 32 & 33" via `GICD_ISENABLER0 = (1<<0)|(1<<1)` | **contradicted** | Two errors. (i) On GICv3, SPIs (INTID ≥ 32) live in `GICD_ISENABLER<n≥1>` — INTID 32 is bit 0 of **ISENABLER1**; writing ISENABLER0 bits 0–1 enables **SGIs 0–1**, i.e. self-generated interrupts (Arm GIC architecture spec, IHI0069). (ii) The line is an lvalue-cast assignment and does not compile (below) |
| The interrupt handler / IRQ init compile | **contradicted — measured** | `probes/snippet-as-is.c` (verbatim extract + the document's own types/macros): five `lvalue required as left operand of assignment` errors (`(volatile u32)GICD_CTLR = 0x3;` etc.) plus `u16` used but never typedef'd in `main.c`. The silent sibling bug: `u32 head = (volatile u32)REG_NIC_INGRESS_HEAD;` compiles but loads the **address constant**, not the register contents |
| A physical doorbell register is how work should reach the GPU on this box | **contradicted by our own number** | The driver-mediated doorbell (a resident kernel polling a pinned ring) already delivers 3 µs; there is nothing left for a bare register to save (googl1 part 03's standing point, now with the ingress measurement behind it) |

**The honest summary.** Keep the discipline, discard the map. The
head/tail ring with release ordering is the *one load-bearing pattern* in
this document, and it is already measured on this box through the supported
path — where its correctness is also proven (bit-exact over 170,000 frames
across paper 61's runs). Every specific address, the GIC programming, and
the interrupt handler are invention, in the provable sense that the handler
cannot be compiled by any C compiler.

## Judgement

Stock JetPack, today: nothing new to build — paper 61's §6 regression *is*
the measured version of this part's one good pattern, and it runs without
a single MMIO address.

Needs Casey (and NVIDIA): a published user-mode doorbell/BAR map for the
Thor's GPU and NIC — which does not exist publicly, and which nothing we
do needs, because the 3 µs number already includes everything the bare
register path hoped to win.

**Cost:** zero for the supported form (already built and measured);
unknown-to-impossible for the register form.
