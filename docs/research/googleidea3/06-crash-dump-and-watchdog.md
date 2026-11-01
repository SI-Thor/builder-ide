# 06 — Crash dump, watchdog and the self-diagnostic loop (Stage 33)

**Source:** `googleidea3.md` lines 388–402 (`terminate_and_reboot`),
lines 738–835 (`crash_dump.c`, "The Microarchitectural Diagnostic Layer Is
Sealed"); the watchdog registers in `main.c`'s map (0x3C000000) and the
`REG_CORE_DUMP_BASE` sector at 0x2FFF0000.

**Relation to the corpus:** extends googl1's part 07 (the miter, safety)
into failure handling — the same instinct builder-ide's night agent
actually needs (googl1 part 01's attestation question: "what establishes
that the thing that came back up is the thing I left running?").

## What it says

On panic: write a fault code to a crash-log address, zero the watchdog
counter, set its control bit, "trigger immediate Power-On Reset". Stage 33
serialises an ASCII trauma log into a reserved memory sector: the vector
id, the failing cell, and the raw exception registers — `ELR_EL3`,
`ESR_EL3`, `FAR_EL3` — read by `mrs` at fault time, plus the cell's
activation and threshold, then `dmb sy`. The promise: an "un-brickable"
record that survives the reboot and can be audited "directly from hardware
memory on restart".

## What it means

Crash-only design: fail fast, leave the evidence in RAM, reboot into
something that reads it. This is a real and respected pattern — Linux's
`pstore`/`ramoops` does exactly this (registers and kernel log to a
reserved-RAM region, recovered at next boot), and the crash-only
literature (Candea & Fox 2003) argues for it deliberately rather than as
an emergency. The document's version is the pattern with invented
addresses and no reader.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| `ELR_EL3`/`ESR_EL3`/`FAR_EL3` are the right registers to capture at an exception | **confirmed** | Armv8-A exception syndrome: link register, syndrome, faulting address — exactly what a bare-metal handler should save |
| Serialising a small ASCII record to reserved RAM at fault time is fast and sane | **confirmed** | Standard practice; `pstore`/`ramoops` reserve a RAM region for precisely this (Linux kernel documentation, `pstore.rst`) |
| The watchdog registers at 0x3C000000 / `REG_WDT_CONTROL` semantics | **contradicted (invented)** | Addresses invented; the Thor's watchdogs are Tegra TIM/WDT banks managed by firmware and the kernel, exposed to user space as `/dev/watchdog` with the standard Linux watchdog API |
| The dump sector at 0x2FFF0000 is "isolated SRAM" | **contradicted** | 0x2FFF0000 lies between the document's own linker regions (LPDDR5X_MITER ends at 0x28000000) — reserved by nothing, in DRAM that a warm reset may or may not preserve |
| A warm reset preserves RAM so the record "survives the reboot" | **plausible but unverified** | Tegra-class SoCs generally preserve DRAM across a warm reset (this is what makes pstore/ramoops work here at all); on this box the supported form is the kernel's pstore, which we have not exercised |
| A `mrs` of `ELR_EL3` from the fault path works | **confirmed at EL3; moot here** | Real register semantics; unreachable from our software (signed boot, googl1 part 01) |

**The honest summary.** The pattern is right and the implementation is a
sketch: the two things that make crash-first design work — a *reader* for
the record and a *contract* for what state survives — are absent, and the
addresses are invented. The supported stack already ships both halves:
`pstore`/`ramoops` for the record, `systemd`/journald + persistent journal
for the reader.

## Judgement

Stock JetPack, today — this is the one operational habit in googleidea3
worth adopting for the night agent, in its supported form:

- **Verify the box's pstore/ramoops** (one boot-cycle test: does
  `/sys/fs/pstore` receive anything after a crash?) — a thor-admit-free,
  read-only check plus one reboot window. If it works, the night agent's
  crash evidence is free.
- **Keep the agent's own journal append-only and hash-chained** across
  restarts (the googl1 part 01 attestation idea) — the "warm-boot loader
  checks a state hash" impulse, done with CRC32/BLAKE3 instead of FNV-1a
  and a real journal instead of a bare snapshot.
- The watchdog form on this box is `/dev/watchdog` + the existing
  supervision; nothing new.

**Cost:** a day for both checks. **Blocked parts:** nothing that matters —
the EL3 handler version is the only Casey/NVIDIA-shaped piece, and its
function is fully covered by pstore.
