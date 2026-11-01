# 05 — NIC, DMA rings and the zero-copy network path

**Source:** `googl1.md` lines 21–27 ("3. GPUDirect DMA Ring Buffers"), lines
1062–1066 (the ingress → work queue → DOORBELL path), lines 1642–1700 (Stage 14,
`egress_fabric.c` and the TX_RING), lines 1700–1760 (Stage 15, the register
map), lines 3366–3470 (Stage 29, `cluster_map.c` and NVLink).

## What it says

> "We cannot let network traffic cause CPU page faults or software interrupts,
> which waste thousands of clock cycles."

The mechanism: the NIC DMAs frames directly into a pre-allocated ring in memory.
A core polls the ring's tail register, sees a new frame, and turns it into a
command. On the egress side, `egress_fabric.c` fills a `TX_RING` and advances a
physical `TX_TAIL_REG`, and "the network interface picks up this change at the
silicon level." Stage 29 then scales this across blades with "raw NVLink Address
Translation Tables".

## What it means

Three sub-claims:

1. **DMA into a pinned ring, no per-packet interrupt.** This is ordinary
   high-performance networking. It is exactly what a `SO_ZEROCOPY` socket or a
   DPDK-style poll loop does, and what NVIDIA's GPUDirect RDMA does across
   machines. Standard and achievable.
2. **The ring is in unified memory, so the GPU reads the frame without a copy.**
   This is the interesting part and it depends on the coherence fact established
   in part 02. If the NIC DMAs into a coherent region that the GPU can also
   address, then the frame is available to tensor cores with no copy.
3. **NVLink between Thor blades.** This is where the document is wrong, and
   importantly wrong in a way that matters for planning.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor has real Ethernet controllers with MMIO windows | **confirmed** | `/proc/device-tree/bus@0` on the Thor lists `ethernet@A808910000` and four more `ethernet@...` nodes |
| A NIC can DMA into system memory without per-packet interrupts | **confirmed** | Standard PCIe DMA; NVIDIA documents GPUDirect RDMA for Jetson Thor (the AGX Thor Developer Kit ships an optional ConnectX-7 NIC for this) |
| GPUDirect RDMA is supported on Jetson AGX Thor | **confirmed** | NVIDIA's "GPUDirect RDMA on Jetson Thor" documentation covers the AGX Thor Developer Kit with the ConnectX-7 adapter, requiring the `nvidia-peermem` module |
| A frame DMA'd by the NIC can be read by the GPU with no copy, because memory is unified and coherent | **confirmed (mechanism) / plausible (specific path)** | Coherence is confirmed (part 02; both-direction host↔device visibility measured today). Whether the *NIC's* DMA writes land in a region the GPU addresses is a driver and IOMMU question not tested here — mark it plausible but unverified |
| Polling a ring beats interrupt-driven processing | **confirmed** | Standard result; and our own measurement shows the same shape on the GPU side: the persistent ring reached 313 k jobs/s at p50 3.03 µs against 69.27 µs for per-job launches, and the plain per-job path *stalled at job 1* under contention |
| The register map in `linker.ld` / `register_miter.c` gives the real Thor TX ring addresses | **contradicted** | The document's addresses (`0x40001000`, `0x40002000`, `TX_TAIL_REG`, `RX_HEAD_REG`) are its own invention. The real Thor NIC registers are described in the Jetson Linux *Device Tree* and the *Ethernet Controller* documentation, under `nvidia,tegra264-ethernet` |
| Thor blades have **NVLink** between them | **contradicted** | NVIDIA's published AGX Thor spec lists no NVLink. The interconnect listed is the **QSFP28** networking (4× 25 GbE) plus PCIe Gen5 x16. The live device tree contains no NVLink or C2C node. Thor blades scale over *Ethernet*, not NVLink — which changes the entire design of `cluster_map.c` |
| `cluster_map.c`'s "NVLink Address Translation Tables" can map a remote blade's memory | **contradicted** | Follows from the above: there is no NVLink address space to translate. Remote memory would be RDMA over Ethernet, with a different programming model entirely |
| The "multi-blade chassis" is a single memory space | **contradicted** | The Thor's 128 GB is a *per-module* pool. There is no fabric making several modules into one address space; multi-node work is explicitly networked (RDMA), which is exactly the latency the document hoped to remove |

**The honest summary.** The NIC→GPU zero-copy idea is real and is the single
most valuable *unexploited* property of this machine: a coherent, unified
address space means a frame that lands in memory is addressable by the GPU with
no copy. But the document's multi-blade story is built on NVLink, and Thor
blades do not have NVLink — they have 4×25 GbE Ethernet. Any design that assumes
a shared memory space across blades is dead on arrival, and that is a large part
of the document's later architecture.

## Judgement

**The network→tensor zero-copy path is worth pursuing — and it is the paper in
part 12. The NVLink multi-blade fabric is not worth pursuing, because the
hardware it needs does not exist on this machine.**

Stock JetPack, today:

- **Build the NIC→GPU zero-copy path.** The property is there: one coherent
  memory pool that both the NIC's DMA engine and the GPU's SMs address. This is
  the natural fit for builder-ide's night agent ingesting an event stream and
  running it through a model without staging copies.
- **Budget the Ethernet bandwidth honestly.** 4×25 GbE is ~100 GbE aggregate
  (~12.5 GB/s) before overheads. Compare the memory system: we measured 239.7
  GB/s of DRAM bandwidth. The network is the bottleneck by more than an order of
  magnitude, so the design should minimise *bytes crossing the wire*, not
  optimise copies inside the box.
- **Do not build `cluster_map.c` / the NVLink translation layer.** Replace it
  with an explicit RDMA or even TCP-based multi-node path that respects the
  actual topology.

Needs OS/firmware changes, which nothing does without Casey:

- Nothing for the zero-copy path, provided `nvidia-peermem` is available for
  GPUDirect RDMA on the box. That is a module and a NIC; it is a purchase and a
  configuration decision, not an engineering cliff.
- True NVLink between Thor blades would need different hardware.

**What we would measure.** The experiment is in part 12's paper: a NIC→tensor
path with zero intermediate copies, measured as (a) end-to-end per-frame latency
from wire to tensor consumption, (b) sustained throughput against the wire's
~12.5 GB/s ceiling rather than the DRAM's 240 GB/s, and (c) a control that
counts the copies the naive path performs. We have none of these today; we have
the CPU-side doorbell number (3.03 µs p50) and the memory bandwidth ceiling.

**Cost:** moderate to high — a NIC, `nvidia-peermem`, and a real pipeline. But
the ceiling is known and the property is confirmed, which makes it a tractable
project rather than a speculative one.
