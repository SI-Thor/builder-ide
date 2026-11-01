# 02 — The monolithic image: linker map, EL3 boot and the build pipeline

**Source:** `googleidea3.md` lines 109–266 (`linker.ld`, `boot.s`), lines
578–596 (the cross-compiler "Build Strategy"), and the framing claim at
lines 109–110 ("a fully complete, single-source, copy-pasteable monolithic
codebase … compiled into a unified binary image").

**Relation to the corpus:** this is googl1's Stage 0/`boot_signoff`
material (its parts 01–02) rewritten as three concrete files; the EL3
substrate repeats googl1's EL3 claims and inherits the same verdict. The
`-mcpu=neoverse-v3ae` flag is new and — to its credit — matches the real
CPU.

## What it says

A memory map hardwired "directly into physical silicon rows":
`HARD_RESET` at 0x00000000 (16 KiB, "Secure EL3 Reset Vector"), boot
vectors at 0x00004000, "on-chip SRAM" at 0x3FFF0000, `LPDDR5X_CELLS` at
0x10000000 (256 MiB), `LPDDR5X_CODE` at 0x20000000 (64 MiB),
`LPDDR5X_MITER` at 0x24000000 (64 MiB); a 512 KiB stack in SRAM. `boot.s`
masks interrupts (`msr daifset, #0xf`), parks all cores but core 0
(`mpidr_el1` check + `wfe`), sets `SCR_EL3=0x531` and `SPSR_EL3=0x3c9`,
points `VBAR_EL3` at a vector table, sets the SMP coherency enable bit
(`S3_1_C15_C2_1` bit 6, "CPUECTLR.SMPEN"), and jumps to C. Build:
`aarch64-none-elf-gcc -mcpu=neoverse-v3ae`, link with `-T linker.ld`,
`objcopy -O binary` to `quilt_flash.img`.

## What it means

This is a competent sketch of how a minimal AArch64 bare-metal image *is*
built — memory regions in a linker script, an EL3 entry that sets up
scrubbed state, secondary cores parked, cache coherency enabled before the
MMU. The question is whether any of the addresses or privilege levels are
real on this machine, and whether the resulting image could ever execute.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The CPU is Neoverse V3 AE-class; `-mcpu=neoverse-v3ae` is the right target | **confirmed** | 14 Neoverse V3AE cores measured on this box (`exp-ct-thor.md`; googl1 part 01) |
| `msr daifset, #0xf`, `mpidr_el1` park loop, `wfe` | **confirmed** | Real Armv8-A sequences, correctly written |
| `SCR_EL3 = 0x531`, `SPSR_EL3 = 0x3c9` | **confirmed as values** | 0x531 = NS=1 + arch-reserved ones + HCE + RW; 0x3c9 = EL2h with all DAIF masked — the canonical minimal-boot values for "next state = AArch64 EL2" |
| VBAR_EL3 with a 2 KiB-aligned table (`.align 11`), 128-byte vector slots (`.align 7`) | **confirmed** | Armv8-A vector layout: 16 slots × 16 B, slot alignment 128 B, table alignment 2 KiB |
| Setting SMPEN before enabling caches/MMU is required | **confirmed** | Real bring-up requirement on modern Arm cores; the register is implementation-defined per core TRM |
| The memory map (0x0 reset, SRAM at 0x3FFF0000, DRAM regions at 0x10000000+) is the Thor's | **contradicted** | Invented. The Thor's real map is per its device tree — e.g. the GIC at 0x8146000000, `ethernet@A808910000` (live `/proc/device-tree`), both far outside the document's picture; on Tegra-class SoCs the BootROM region and SysRAM have their own published layout, none of which matches |
| The map is even self-consistent | **contradicted** | `LPDDR5X_CODE` claims 0x20000000–0x24000000; `main.c` (part 03) puts its NIC ring registers at 0x20000000 and its PCIe status at 0x20000040 — the "code" region and the "device" region are the same addresses. The document's two halves were never checked against each other |
| We can build this image and the Thor will execute it | **contradicted** | The boot chain is signed and fuse-locked (googl1 part 01, standing verdict): a third-party EL3 image cannot be substituted. Building the ELF is a `gcc` invocation; running it on this module is not possible without NVIDIA's signing or unlocked fuses |
| The result is a "single-source monolithic codebase" | **contradicted** | `main.c` and `main_final.c` (Stage 40) both define `hardware_signoff_kickoff` and `execute_simulated_linux_command` — linking both objects is a duplicate-definition error; the build script compiles only `boot.o main.o`, so the "final integration" file is not even in the build. And `main.c` itself does not compile (part 03's probe) |

**The honest summary.** The Arm mechanics in `boot.s` are mostly *right* —
canonical register values, correct vector layout, correct park loop. But
the substrate is unreachable (signed boot), the memory map is invented and
internally contradictory, and the "complete, copy-pasteable" claim fails on
its own files. This is the googl1 part-01 verdict, unchanged by being
re-serialized as a linker script.

## Judgement

Nothing to do. The EL3 route is a boundary, not a project (googl1 part 01;
the director concurs). The one transferable habit: **the build recipe
itself** (cross-compile → `-T linker.ld` → `objcopy`) is the standard way
we would ship *any* freestanding artifact, e.g. a tiny initramfs probe —
and that runs under the stock kernel, no signing needed.

**Cost of anything here:** unbounded and blocked for the EL3 image; zero
and unnecessary for everything else. No measurement on the Thor bears on
it beyond what googl1 part 01 already recorded.
