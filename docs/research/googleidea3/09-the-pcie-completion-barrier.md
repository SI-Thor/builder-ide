# 09 — The PCIe completion barrier and write ordering (Stage 37)

**Source:** `googleidea3.md` lines 1130–1206 (`pcie_barrier.c`, "The
Peripheral Interconnect Layer Is Fixed").

**Relation to the corpus:** this is the write-ordering question that
googl1's part 03/05 doorbell paths never asked and that paper 61's ring
answers by construction; googleidea2 shared the unexamined "doorbell write"
belief (its `0x50004000` submission with "0.00 ms host overhead"). It is
the one place googleidea3 identifies a *real hazard* — and then reaches for
the wrong register.

## What it says

> "Solves the classic microarchitectural hazard where the CPU rings the
> GPU's hardware doorbell before the accompanying data payload has finished
> traveling across the physical PCIe lanes."

`enforce_pcie_split_barrier`: `dmb ishst`, then poll a status register
(bit 5, "Transactions Pending") with a `yield` backoff and a ~16M-iteration
panic bound, then `isb`. `submit_synchronized_hardware_flit`: emit the
command, run the barrier, ring the doorbell.

## What it means

The hazard is real in general DMA programming: a consumer that sees the
"ready" flag must also see the payload the flag describes — otherwise it
executes on torn or empty data. The document's proposed guarantee is to
poll a PCIe device-status bit until "the write buffers have completely
emptied". Two questions: does that bit mean that, and is any of it needed
on this machine?

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The payload-before-doorbell hazard is real | **confirmed** | The producer/consumer ordering problem is the classic DMA ring hazard; every serious ring protocol addresses it |
| The "Transactions Pending" bit (Device Status Register, bit 5) reports *your posted writes* landing | **contradicted — wrong semantics** | Per the PCI Express Base Specification, the Device Status Register's Transactions Pending bit indicates the *function's own outstanding non-posted requests* (its owed completions) and exists mainly to detect FLR completion. It says nothing about the arrival of posted writes a host issued *to* the device. Polling it here is a status bit repurposed as a fence |
| Without such a barrier, a doorbell can overtake the payload | **contradicted on this fabric** | PCIe posted writes do not pass posted writes issued earlier (base-spec transaction-ordering rules; same ordering the C2C path preserves). The window the document fears is closed by write ordering *plus* the release discipline on the flag — no device-status polling required |
| The supported way to guarantee payload-before-flag is a device-status poll | **contradicted** | The standard primitives: a release store of the flag after the payload writes (the C11/Armv8 memory model's `stlr`/`dmb ishst` — which `emit_graph_node` itself already issues), and/or a readback of the flag (a completion forces the posted writes ahead of it). The measured ring does exactly this |
| The measured ring needs any of Stage 37 | **contradicted — measured** | Paper 61: 100,000-job ring runs bit-exact (rel err 2.4e-08, twice independently), and the ingress arm — an actual payload-then-flag-then-consume pipeline per frame, 70,000 frames — recorded **mismatch = 0** with no barrier register anywhere. The observed shutdown `dma_fence_default_wait` stall (attempt 3a) is starvation, not ordering: the data was correct; the *kernel* was merely unscheduled |
| The panic bound (`0x00FFFFFF` polls → reboot) makes it safe | **plausible but unverified** | Rebooting the box because a status bit never clears is exactly the over-reaction the brief's safety rules exist to prevent on a shared machine |

**The honest summary.** The concern is legitimate and the proposed
mechanism is a misread of a real register. On this machine the correct
answer is already deployed and measured: release ordering of the flag
after the payload (plus acquire on the consumer side), which PCIe/C2C
posted-write ordering makes sufficient — proven by 170,000 bit-exact
jobs/frames through paper 61's rings. Stage 37 would add a config-space
poll, a panic path, and no additional guarantee.

## Judgement

Stock JetPack, today: **nothing to build — one thing to write down.** The
ordering rule our runtime relies on deserves a sentence in the runtime's
design doc so nobody re-derives Stage 37: *payload writes, then
release-store the tail/flag; consumer acquire-loads the flag; no device
status polling.* That rule is what the probes implement; the bit-exact
records are the evidence.

Needs Casey: nothing. If a real NIC-DMA path is ever built (paper 61 §7),
the *same* question returns for the NIC's descriptors — and the answer
will again be ordering + readback, measured, not a status-bit poll.

**Cost:** zero (it is a paragraph). **What we would measure** if anyone
doubts it: deliberately weak ordering (plain stores, no release) on the
ring until a mismatch appears, then the release form — a negative-control
experiment paper 61's harness could host in minutes; not run here because
the positive evidence is already twice-measured.
