# 07 — Cache maintenance and the coherence story (Stage 34)

**Source:** `googleidea3.md` lines 838–918 (`cache_fabric.c`, "The
Microarchitectural Cache Interface Is Locked"); the coherence checklist
reappears at lines 1536–1538 (part 13).

**Relation to the corpus:** googl1 part 02 established the coherence fact
by measurement; this part is the first place the corpus tries to *manage*
caches manually around it, motivated by "GPUDirect DMA memory injections".

## What it says

> "Prevents stale data reads during high-frequency GPUDirect DMA memory
> injections."

`invalidate_cache_line_range` aligns to 64-byte lines, `dmb sy`, issues
`dc ivac` per line ("drops the state … down to Invalid"), then `dsb sy` +
`isb`. `clean_cache_line_range` mirrors it with `dc cvac` ("Unique Dirty
to Unique Clean"). The use case: before touching a cell the NIC wrote,
invalidate; after the CPU modifies it, clean — "makes the calculation
visible to the Blackwell GPU warp controllers in picoseconds".

## What it means

These are real Arm cache-maintenance instructions with their real
semantics — by VA to the point of coherency, which is the correct form for
DMA staging (set/way forms are for power management). The *premise* is the
part to check: this machinery exists for **non-coherent** DMA agents. The
document assumes the Thor's CPU caches sit on a non-coherent path from the
GPU (and a NIC's DMA), so software must scrub lines by hand — on every
ingress cell, per frame.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| `dc ivac`/`dc cvac` by VA to PoC, 64-byte lines, barriered before and after | **confirmed** | Arm ARM: correct instructions, correct ordering idiom (`dmb`→`dc`→`dsb`+`isb`); 64 B is the line size on this class of core |
| Invalidate-before-DMA-read / clean-after-CPU-write is the right protocol *for a non-coherent agent* | **confirmed** | The standard non-coherent DMA contract (same shape as Linux's `dma_sync_*` for non-coherent devices) |
| The CPU↔GPU path on the Thor needs this | **contradicted — measured** | Mapped pinned memory is coherent in both directions on this box (host→device and device→host visibility both YES, googl1 part 02; `hostNativeAtomicSupported = 1`, `exp-ct-thor.md`). The measured ring and the measured ingress path (paper 61: 3.03/3.21 µs p50, bit-exact over 170 k jobs/frames) run with **zero** cache maintenance — no stale read was ever observed, including a 20,480-thread grid politely polling a mapped word |
| Results become visible to the GPU "in picoseconds" after a clean | **contradicted as to scale** | A `dc cvac` to PoC on this SoC lands in the coherence domain in tens-of-nanoseconds-class time, then the GPU's *poll interval* (the ring polls with `__nanosleep(200)` backoff) dominates. The measured doorbell-to-result p50 is 3.03–3.21 µs — the number the machine actually gives |
| A NIC's DMA would land incoherently, needing the Stage 34 scrub | **plausible but unverified** | On-SoC peripherals on Tegra-class parts are I/O coherent; the socket-level ingress path (our measurement) involves no device DMA at all. The GPUDirect-RDMA form remains untested here — no such NIC on this box (googl1 part 05, paper 61 §7) |
| Per-cell invalidate+clean on the ingress path is affordable | **contradicted** | It is per-frame, per-line Python-level thinking in a 3 µs budget: a 112-byte cell is 2–3 lines, two barriers per frame — the barriers alone (`dsb sy`) are of the same order as the entire measured job. On a coherent machine it is pure cost with no benefit |

**The honest summary.** The instructions and their sequencing are real and
correctly described — the author knew the idiom. The premise is false on
this machine for the case that matters to us: the CPU↔GPU path is
coherent, which our own measurements demonstrate by *never needing* the
machinery, bit-exactly, at 3 µs. Where the idiom genuinely applies
(non-coherent DMA agents, if a real NIC DMA path ever lands), the right
owner is the kernel DMA API, not per-cell hand-scrubbing in user code.

## Judgement

Stock JetPack, today: **do nothing of this.** The correct user-space tools
for cross-device visibility are the ones already in the measured path —
release/acquire atomics on mapped memory (`__atomic_store_n` /
`__atomic_load_n`, or `cuda::atomic_ref`), which is what paper 61's ring
and probe use. If a NIC-DMA path is ever built, its cache story is decided
by whether the agent is coherent (then: nothing) or not (then: kernel DMA
API), and that determination is a *measurement* (the paper 61 §7
follow-up), not a default to scrubbing.

Needs Casey: nothing.

**What we would measure**, if ever relevant: with a coherent DMA source,
poll a flag with plain acquire loads vs inserting Stage 34's
invalidate+clean — expectation from the measured numbers: the maintenance
adds latency and changes nothing in correctness. Not worth running while
no non-coherent agent exists on the box.
