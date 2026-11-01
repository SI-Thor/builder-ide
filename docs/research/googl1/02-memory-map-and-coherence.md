# 02 — Memory map, BAR pinning and coherence

**Source:** `googl1.md` lines 14–20 ("2. Unified MMU Mapping & Zero-Copy BAR"),
lines 75–81 (AMBA CHI coherence), lines 82–86 (stage-2 translation fencing),
lines 459–478 (`linker.ld`), lines 3170–3273 (Stage 27, `mmu_fabric.c`).

## What it says

> "In a normal computer, the CPU and GPU have separate memory spaces, and copying
> data between them kills performance. On the Thor, we exploit the unified memory
> architecture at the silicon level."

The proposed mechanism: the machine has one flat physical address space. A linker
script pins regions to fixed physical addresses so that "memory addresses
0x10000000 and 0x20000000 are hardwired directly via PCIe BAR to your physical
network interface and RAM pool" (line 365). Stage 27's `mmu_fabric.c` then writes
page tables directly into the ARMv9 MMU. The coherence argument is that on the
Thor the CPU's caches do not need explicit flushing when the NIC writes RAM and
the GPU reads it, because the interconnect is coherent.

The document also proposes a "stage-2 translation" (EL2) layer: an outer
translation that the GPU's MMU walks in hardware, so a page-table change does not
require a TLB shootdown round-trip.

## What it means

Three claims are being compressed here, and they need separating:

1. **Unified physical memory.** One DRAM, one address space, CPU and GPU both see
   it. On the Thor this is true and is the most valuable single fact about the
   machine. NVIDIA's own docs call the Thor a "unified memory" architecture where
   CPU and GPU share LPDDR5X.
2. **PCIe BAR pinning.** The document wants fixed physical addresses so the NIC
   can DMA into them with no translation. On the Thor the device tree shows
   `ethernet@A808910000` and four more `ethernet@...` nodes — real devices with
   real MMIO windows. Whether the NIC can DMA *into arbitrary chosen physical
   addresses* is a different question from "the NIC can DMA somewhere".
3. **Hardware cache coherence between NIC, CPU and GPU.** This is the load-bearing
   claim. If the interconnect were not coherent, every NIC→GPU handoff would need
   explicit cache maintenance, which is exactly the "thousands of clock cycles"
   the document says it is avoiding.

Claim 1 is confirmed. Claim 2 is a standard PCIe capability (BMCs must be able to
address memory) but *pinning* specific addresses needs driver cooperation.
Claim 3 is the interesting one, and it is partially checkable on the box.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor has unified memory: CPU and GPU share one LPDDR5X | **confirmed** | NVIDIA AGX Thor spec: 128 GB LPDDR5X, unified memory architecture. Measured: `total_mem` 131,856,928,768 B (122.8 GiB) visible to CUDA *and* to the OS — one pool, no separate VRAM (`nvidia-smi` reports memory as `N/A` on Thor, because there is no separate device memory) |
| The Thor's DRAM is LPDDR5X | **confirmed** | NVIDIA published spec: 128 GB LPDDR5X with 256-bit bus, 273 GB/s |
| A "128 GB" pool is fully usable | **contradicted (as stated)** | NVIDIA's 128 GB is the marketing figure; the box reports `MemTotal: 128,766,532 kB` (122.8 GiB) — roughly 5 GiB is reserved by the boot chain and the desktop. The document's "90 GB weights + 10 GB network + 28 GB context = 128 GB" partition does not fit in the addressable pool |
| The measured bandwidth is the published 273 GB/s | **contradicted** | `thor-fp4/BENCHMARKS.md` measures ~239.7 GB/s triad; `sp_gc` calibration measures 117.97 GB/s peak read and 438.24 GB/s device-to-device. The published 273 GB/s is a theoretical peak. A sustained 240 GB/s is ~88% of it — normal for a real memory system, but the document's numbers should be quoted as peak, not achievable |
| The interconnect is coherent between CPU and GPU | **confirmed** | CUDA green contexts share the primary context's address space (`gc_probe`: memory allocated in the primary context is read/written by kernels in green contexts with no copies); `exp-ct-thor.md` confirmed pointer identity for `cudaMallocManaged` |
| Mapped pinned host memory is coherent in **both** directions | **confirmed** | Measured first-hand on the Thor today under `thor-admit`: `probe: host->device pinned visible=YES device->host pinned visible=YES`. This is the single most load-bearing fact for the paper in part 11 |
| PCIe BARs can be pinned to chosen physical addresses | **plausible but unverified** | The device tree exposes real MMIO windows; whether arbitrary BAR programming is permitted under stock JetPack is untested here. It is also irrelevant if the socket is used as a normal network interface — see the judgement |
| The interconnect is **AMBA CHI** specifically | **unknowable without NVIDIA's private docs** | CHI is Arm's coherent protocol for its own fabrics. NVIDIA's Thor TRM does not publish the CPU↔GPU interconnect protocol publicly. The *effect* (coherence) is confirmed; the *name* is not checkable from outside |
| Stage-2 (EL2) translation can fence GPU pages without shootdowns | **plausible but unverified** | ARMv9 has stage-2 for EL2 guests. Whether the Thor's GPU MMU walks an outer table in hardware is NVIDIA-internal. Note the document then contradicts itself: it proposes both a flat physical map (no MMU) and a stage-2 MMU (a hierarchy) |
| A hand-written `linker.ld` pinning 0x10000000/0x20000000 can be linked against the physical Thor | **contradicted** | The proposed addresses are the document's invention. NVIDIA's real Thor memory layout is defined by the device tree and the signed BCT partition table, and `nvidia-smi`/CUDA allocate from it. A bare-metal image at invented addresses will not describe the running SoC |

**The honest summary.** Unified memory is real and it is the machine's best
property. Coherence is real and we measured it in both directions. The rest —
BAR pinning at invented addresses, the exact interconnect protocol, an outer
translation table — is either NVIDIA-internal or a design that contradicts the
silicon it claims to describe.

## Judgement

**The unified-memory fact is worth a lot to us and is already banked. The BAR and
MMU work is not worth doing.**

Stock JetPack, today:

- **Use unified memory as a first-class design element.** The Thor has one memory
  pool and coherent host/device access. For builder-ide's night agent — which
  reads and writes across CPU and GPU — this is the single biggest structural
  advantage the hardware offers. The measured doorbell round-trip of 3.03 µs p50
  (part 11) is only possible because of it.
- **Do not touch the MMU, the BCT, or the flash layout.** The document's Stage 27
  (`mmu_fabric.c`) writes page tables from userspace. On a stock JetPack box with a
  running desktop, that is at best a no-op and at worst a brick. It is also
  unnecessary: we get the benefit (one address space, coherent access) without
  owning the page tables.
- **Do not build a NIC DMA path on PCIe BAR programming.** The Thor's network
  path is a normal network interface. Even if BAR pinning were possible, the
  socket-based path is what actually carries traffic, and the zero-copy story we
  need is about *GPU memory to CPU memory*, not about programming BARs.

Needs OS/firmware changes, which nothing does without Casey:

- Replacing or bypassing the signed boot chain to load a custom flat physical
  map. Out of scope; treat as a boundary, not a project.

**What we would measure.** If a zero-copy network→tensor path ever becomes worth
building, the measurement is: (a) can the NIC's DMA target be placed in the same
page-table region the GPU reads, (b) what is the per-frame latency from NIC
arrival to tensor consumption, and (c) does the 240 GB/s achieved bandwidth
saturate before the tensor path does. We have (b) and (c) today for the
CPU→GPU path and not at all for the NIC→GPU path — which is the honest gap.

**Cost:** near zero for the "use unified memory" part; weeks and a signed-chain
break for the rest.
