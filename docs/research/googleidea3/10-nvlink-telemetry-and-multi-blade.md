# 10 — The NVLink telemetry monitor and the multi-blade fabric (Stage 38)

**Source:** `googleidea3.md` lines 1209–1295 (`nvlink_perf.c`, "The
Multi-Blade Transport Profiler Is Embedded"); the register block at
0x70003000 with flit counters and a link-throttle config at 0x70000004.

**Relation to the corpus:** the third appearance of the NVLink belief —
googl1's Stage 29 (`cluster_map.c`, "raw NVLink Address Translation
Tables", contradicted in its part 05), googleidea2's "Peer-to-Peer NVLink
(200 GB/s)" and its `parse_nvlink_hardware_counters` telemetry node (with
**mock** counters and a hardcoded 200 GB/s ceiling), and now Stage 38's
performance-counter block. Each document invents its own register numbers
for the same non-existent hardware; googleidea3 adds the self-throttling
behaviour.

## What it says

> "Interrogates Blackwell NVLink Network Profiling Registers. Tracks raw
> packet counts, retransmission exceptions, and link lane bandwidth."

Reset-and-arm the counter block, sample TX/RX flit counters and retry
counts into a 256-entry telemetry ring, compute `link_efficiency_pct =
(tx − retries) × 100 / tx` (defined as 100 at zero load), and if retries
exceed 0xFFFF, set a config bit to "force line link throttle to stabilize
signal drops".

## What it means

A fabric health monitor: counters → a rolling log → a control action on
degradation. As a *pattern* (telemetry ring + threshold policy) this is
ordinary and fine. Every concrete element — the counters, the throttle
bit, the fabric itself — assumes NVLink between Thor blades.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| Thor blades interconnect over NVLink | **contradicted (standing verdict)** | AGX Thor's published interconnect: 4× 25 GbE (QSFP28) + PCIe Gen5; no NVLink listed, no NVLink/C2C-to-fabric node in the live device tree (googl1 part 05, checked there). Multi-blade scaling is Ethernet — RDMA at best — with a different programming model entirely |
| NVLink performance counters sit at 0x70003000 | **contradicted (invented)** | Follows from the above; also the third distinct invented address set for this same fiction across the corpus |
| The throttle bit at 0x70000004 controls link speed | **contradicted (invented)** | Same. Writing invented config bits on a shared machine is the exact behaviour the brief's safety rules forbid |
| The efficiency metric and zero-load baseline are sane | **partly** | Retries/TX as a health ratio is fine; "100% at zero load" is a convention, and retry-spikes-throttle is a policy — but neither is attached to hardware that exists |
| Cross-node telemetry is desirable for a cluster | **confirmed (as a need)** | Real clusters do exactly this — via per-node standard counters exported over the *actual* interconnect (ethtool statistics, /proc/net, RDMA counters) — which every Thor can do today on stock JetPack |

**The honest summary.** The telemetry pattern is generic and portable; the
fabric it monitors is not on this machine. The corpus's multi-blade story
(NVLink shared memory across blades) was already dead in googl1 part 05 —
repeating it with performance counters added does not revive it. The
supported version of "know your link health" is reading the real Ethernet
counters, which costs one command.

## Judgement

Stock JetPack, today: if multi-box work ever matters to builder-ide,
design against **Ethernet/RDMA** (the honest ceiling is the wire:
~12.5 GB/s aggregate vs 239.7 GB/s DRAM — googl1 part 05's budget note),
and read link health from `ethtool -S`/`/proc/net/dev`. Nothing to build
now; single-box is the current world.

Needs Casey/hardware: NVLink between Thor blades — different hardware,
not a project on this machine.

**Cost:** zero. **What we would measure:** nothing here; the multi-node
path is out of scope until a second box exists.
