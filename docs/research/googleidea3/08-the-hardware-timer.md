# 08 — The hardware timer and pacing (Stage 36)

**Source:** `googleidea3.md` lines 1036–1128 (`timer_fabric.c`, "The Clock
Domain is Fixed to Silicon Time").

**Relation to the corpus:** googl1 part 12's cascade had a "global tick"
(Stage 18) with no mechanism; this part supplies one — the architectural
generic timer — and it is the most nearly correct stage in the document.

## What it says

Read `CNTFRQ_EL0` for the oscillator frequency, convert a microsecond
interval to cycles, program `CNTHP_CVAL_EL2` with a deadline, enable
`CNTHP_CTL_EL2`, unmask "IRQ line 26" at the GIC. On each interrupt:
check the status bit, mask, run `execute_global_fabric_tick` (the decay
loop), re-arm the compare value, unmask. "Microsecond-Precise Pacing …
forcing connection weight decay and voltage leaks to execute precisely on
interval."

## What it means

Use the Arm generic timer's comparator as a periodic tick source, from
EL3/EL2, with no OS timer subsystem. Pacing is a real need for the kind of
runtime the corpus imagines (decay, sweeps, heartbeats) and a real need
for ours (the night agent's cadences). The question is what the primitive
costs and who can reach it.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| `CNTFRQ_EL0`/`CNTPCT_EL0` read the system counter frequency/count | **confirmed** | Armv8-A generic timer; user space reads the count via `CNTVCT_EL0` (no privilege needed) and the frequency via the vDSO/`clock_gettime` machinery |
| Programming `CNTHP_CVAL_EL2`/`CNTHP_CTL_EL2` from EL3/EL2 | **confirmed (naming muddled)** | Real registers — but `CNTHP_*` is the **EL2 hypervisor** physical timer, not the "EL3 physical timer" the comments claim (that is `CNTPS_*`); the mixed EL3/EL2 naming is wrong in the text and right in the code |
| "IRQ 26" for the EL2 physical timer | **confirmed** | GICv3 INTID 26 = PPI 10, the EL2 physical timer (GIC architecture spec IHI0069, PPI assignment) — a real detail, correctly chosen |
| Enabling INTID 26 via `GICD_ISENABLER0 = 1<<26` | **contradicted** | On GICv3, PPIs are enabled at the **Redistributor** (`GICR_ISENABLER0`), not the Distributor — `GICD_ISENABLER*` banks SPIs from INTID 32 (IHI0069). Same bank error as part 03 |
| The handler compiles | **contradicted** | It tests `CNTHP_CTL_EL2_STATUS`, which is never defined (the file defines `..._ISTATUS`) — a third distinct compile error class after part 03's, in the document's most nearly correct stage |
| Re-arming "now + interval" in the handler gives precise periodic pacing | **partly** | Drifts one interrupt-latency per period (no accumulation, but each deadline inherits the previous handler's delay); the tight form re-arms as `deadline += interval` |
| EL2/EL3 timers are reachable from our software | **contradicted** | Privileged; signed boot (googl1 part 01). User space paces with `clock_gettime(CLOCK_MONOTONIC)` (vDSO, tens of ns), `timerfd`, or CUDA's device-side `clock64()`/`%globaltimer` |

**The honest summary.** Stage 36 is the document at its best: real
registers, the right PPI number, a plausible handler shape — and it still
contains a naming error (EL3 vs EL2), a GICv3 bank error, a
never-defined symbol, and sits behind the privilege wall. Its supported
equivalents are already good enough that nothing is lost.

## Judgement

Stock JetPack, today:

- **Host-side pacing** (the shape paper 61's runtime actually uses): the
  ring's host loop paces itself with `clock_gettime` — sub-microsecond
  reads via vDSO, no privilege, already measured inside the 3 µs p50
  number.
- **Device-side cadence**, if a resident kernel ever needs internal
  epochs: `%globaltimer` (PTX, ns granularity, sm_110) — verified
  assemblable in the same family as the part 03 checks.
- The decay-tick motivation belongs to the cell/learning story (part 04),
  which carries no workload; nothing paces it today.

Needs Casey: the EL2/EL3 timer route — and nothing needs it.

**Cost:** zero; all supported. **What we would measure**: nothing new —
timer resolution on this box is a one-liner if a pacing design ever needs
the number recorded.
