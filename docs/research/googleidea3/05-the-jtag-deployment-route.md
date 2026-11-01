# 05 — The JTAG deployment route (Stage 32)

**Source:** `googleidea3.md` lines 599–736 (`jtag_flash_tool.c` and "The
Production Target Loop Is Closed").

**Relation to the corpus:** new in googleidea3 — neither googl1 nor
googleidea1/2 addressed *how the image would get onto the machine*. It is
the honest question to ask of parts 02–04, and the answer given is the
clearest demonstration in the corpus of code generated without a target.

## What it says

> "Pipes the exact 128MB compiled quilt_flash.img snapshot straight into the
> hardware's onboard non-volatile memory arrays."

A host program bit-bangs a JTAG TAP controller through GPIO: five TMS-high
pulses to Test-Logic-Reset, Run-Test/Idle, Select-DR/Capture-DR/Shift-DR,
clock the image out TDI bit-by-bit with a settle delay of ~200 NOPs per
transition, Exit/Update-DR, back to Idle. "Upon the next physical power-on
loop, the processor automatically grabs the Stage 0 boot.s vector."

## What it means

Two mechanisms are stacked: (a) IEEE 1149.1 boundary-scan TAP driving,
described recognisably (the state names and the 5×TMS reset are right);
(b) "flashing" — the belief that streaming bits into a TAP writes them
into the SoC's boot flash. (a) is real technology; (b) is not what a TAP
does, and even if it were, the numbers and the boot chain both fail.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The TAP state-machine traversal (TLR via 5×TMS, Shift-DR streaming, exit on last bit) | **confirmed as IEEE 1149.1** | Standard boundary-scan state flow (IEEE Std 1149.1) |
| The host GPIO register map (`0x3F200000` + GPSET/GPCLR offsets) | **contradicted — it is a Raspberry Pi** | 0x3F200000 is the BCM2836/2837 (Pi 2/3) GPIO block: peripheral base 0x3F000000 + 0x200000 (BCM2835 ARM Peripherals datasheet, rev 3, §1.2 note on 2836/2837). The "host" is silently a different computer than any mentioned |
| Bit-banged JTAG at ~200-NOP settle delays streams a 128 MB image in deployable time | **contradicted** | 1.07e9 bit-transitions × ≥3 settle loops × ~hundreds of ns ≈ **tens of minutes to hours**, best case, per image — for a route that does not write flash anyway (below) |
| A TAP write path "pipes the image straight into the hardware's non-volatile memory arrays" | **contradicted** | A TAP moves scan-chain bits through test logic; it is not a flash-memory write interface. Writing Thor boot storage is done by the boot ROM's recovery path over USB (Jetson Linux `tegraflash`/`flash` scripts, "Flashing Support" in the developer guide) — that is the supported mechanism, and it enforces the same signed chain |
| A flashed custom image would be grabbed at next power-on | **contradicted** | The chain is BootROM → (QSPI) bootloader → signed images, with production fuses locked (googl1 part 01, standing verdict). An unsigned `quilt_flash.img` is not a boot image on this module, however it arrives |
| The tool streams what it loaded | **contradicted (minor, telling)** | `main()` reads `loaded_bytes` from the file, then streams the full static `expected_allocation_bytes` (128 MiB) regardless — padding garbage after the image. The variable exists and is ignored |

**The honest summary.** The state machine is textbook-recognisable and
everything around it is not about this machine: the host map is a
Raspberry Pi's, the write mechanism is not how TAP or the Thor's flash
works, the throughput is off by orders, and the signed boot chain rejects
the payload at the end of it. For our own devkit, flashing is a solved,
supported, USB-recovery-mode operation — this part's problem does not
exist.

## Judgement

Nothing to build; nothing to decide. If we ever need to reflash this
module, the route is the documented recovery-mode USB flash, which any
seat can run and which does not require JTAG, GPIO, or Casey — only the
same care about what image is being written that the signed chain already
enforces.

**Cost:** zero. **Risk of the alternative:** touching boot storage outside
the supported flow is exactly the class of write the brief forbids; the
supported flow exists and is enough.
