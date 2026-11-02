# Mission B, the pose stream: the verdict (2026-11-01)

Two teams solved the same mission independently: implement the emitter/projector design (`docs/design/emitter-projector.md`) for 10,000 seeded moving objects at 60 ticks/s for 60 s, with 64 subscribers on their own interest regions and rates.

The score was **pre-registered**:
- **the bar:** zero reconstruction errors within the stated bound, and a late joiner resyncs;
- **the ranking:** bytes per subscriber, then emitter CPU p95.

## The result
| | **mcode** (Rust, std-only) | zcode (C, single file) |
|---|---:|---:|
| Bar: reconstruction errors | **0** (9.47 M states checked) | **0** |
| Quantisation bound | **5 mm per axis** (1 cm grid) | 100 mm per axis (measured max 61.9 mm) |
| Late-join resync | **0.07 ms** | 12.5 ms |
| **Bytes/s per subscriber, mean** | **5,796** | 7,196 |
| Bytes/s per subscriber, p95 | **16,643** | 17,507 |
| Emitter CPU p50 / **p95** | **0.79 / 1.43 ms** | 1.20 / 3.27 ms |
| Delivery latency p95 | 0.67 ms (no simulated network) | 11.8 ms (includes a simulated 2–12 ms network) |

**mcode wins on the ranking** (fewer bytes, then less CPU), and it holds a twentyfold tighter error bound while doing so. Its code is merged as `tools/posestream/` (a standalone crate; `bench.sh` reproduces `RESULT.json` byte-identically from the seed).

## Why the winner sends less
The **predictive delta**: each pose delta is measured against what the projector can already *predict* from the motion channel it holds (position + velocity + time, extrapolated in integers), so a smoothly moving object costs nothing. Both sides apply the identical integer prediction, so they agree exactly. The rest is careful coding:
- biased fixed-width bit fields, one 64-bit word per object, with the width per axis chosen to minimise total cost;
- an escape list so a few fast movers cannot widen the field for everyone;
- the changed set as a bitmap when that beats an id list.

Plain (non-predictive) deltas would cost 8,579 B/s, so prediction is worth 33%.

## What the other entry contributes
The zcode entry reached the same idea from another side: a per-subscriber integer **dead-reckoning mirror**, sending nothing until the mirror drifts past 50 mm. Four of its ideas are worth carrying into the winner:
1. **A provable drift budget from bounded acceleration** (world acceleration ≤ 1.8 m/s²), which turns "it stayed within the bound" into a guarantee.
2. **Tick-tagged corrections, back-dated by the receiver in integer arithmetic,** so network delay never corrupts state. The winner was measured without a simulated network; it should be re-measured with one.
3. **Exit hysteresis** on interest regions (8 m), which avoids enter/exit churn at region edges.
4. **2-byte evicts.**


## Round 2: the network

The winner was measured without a network: the emitter handed the packet to the projector in
the same process, in the same tick. Round 2 re-measures it with one — 2–12 ms of one-way delay
with jitter, and 0.5 % or 2 % packet loss — and measures each of the four ideas the other entry
contributed, on its own. Same seed, same 64 subscribers, same 60 s at 60 Hz. The harness, the
model of the link, and the full numbers are in `tools/posestream/README.md`; the runs are in
`tools/posestream/runs/` and the matrix is `tools/posestream/netbench.sh`.

| | bytes/s per subscriber | on the wire | delivery latency p95 | reconstruction errors | resyncs |
|---|---:|---:|---:|---:|---:|
| the loopback (round 1's conditions) | 5,796 | 5,796 | 0.54 ms | 0 | 3 |
| 2–12 ms, no loss | 5,796 | 5,796 | 13.09 ms | 0 | 3 |
| 2–12 ms, 0.5 % loss | 5,911 | 5,940 | 13.09 ms | 0 | 380 |
| 2–12 ms, 2 % loss | 6,244 | 6,374 | 13.09 ms | 0 | 1,560 |

**The delay costs latency and nothing else.** The bytes are identical to the byte — the stream
digest is unchanged from round 1 — and the reconstruction is exact at every delivery. **Loss
costs bytes**: 2.0 % at 0.5 % loss, 7.7 % at 2 %, and the cost is the resync. Every lost packet
is one gap, and every gap is one keyframe of the whole region in absolute poses (~1 kB for an
average region of 82 objects). The recovery from a gap to the keyframe's arrival is 32 ms at the
median and 108 ms at p95; the worst is 509 ms, which is the 2 Hz subscriber's delivery interval,
because a keyframe can only be sent at a delivery.

**The four ideas, each measured on its own:**

1. **Tick-tagged corrections, back-dated by the receiver — kept, and load-bearing.** The
   receiver anchors each correction at the tick the correction was *computed for*, not the tick
   it arrived at. With the back-dating: 0 reconstruction errors, and the receiver's held state is
   bit-identical to the emitter's mirror. Without it (the receiver anchors at the arrival):
   **9,169,158 reconstruction errors** out of 9,471,363 delivered states, with errors up to
   2,140 mm — essentially every delivery is wrong. The mechanism: anchoring at the arrival adds
   the motion between the correction's tick and the arrival to the correction's base, and then
   adds it again when it extrapolates. Anchoring at the correction's tick makes the base and the
   anchor agree with the emitter's, so the receiver's state *is* the emitter's truth at that tick.
2. **Exit hysteresis (8 m) — measured, and not kept.** It removes 9 % of the leaves (79,353 →
   72,251 over the run), but it holds objects outside the region and those cost a change record
   each: **+33 % bytes** (5,796 → 7,697) and +57 % emitter CPU. The margin was swept (0, 2, 4, 8,
   16 m) and the cost rises with it. On this world the regions are small (14–30 m) against a
   dense world (10,000 objects in 200 m × 200 m × 120 m); zcode's were 80–180 m in a 1200 m arena,
   which is the regime where the idea pays.
3. **2-byte evicts — measured, and not kept.** The leave list is delta-coded varints, already at
   or below 2 bytes per object; the fixed 16-bit id costs 2 B/s per subscriber more (5,796 →
   5,798, 0.04 %).
4. **A provable drift budget — kept, as a stated bound.** Between corrections the projector
   extrapolates with the motion channel, and how far that can be from the truth follows from the
   world's own motion parameters, per kind of object. The bound and its derivation are in the
   README; the harness checks every interpolation against it: over the 60 s run at 2 % loss,
   24,713,234 checks and **not one over the bound** (the worst, 87.3 m, was a fast mover that
   turned, inside the 90.5 m its interval allows).

**What this world does not give the other entry's argument.** That entry built its world with a
hard acceleration cap (1.8 m/s² per axis), and that is what makes its drift budget tight. This
world has walkers that turn impulsively and objects that reflect off the arena wall, so the
budget here is derived per kind from the world's actual parameters and the impulsive cases are
named rather than smoothed over. The consequence is visible: the bound for a fast mover over 30
ticks is 32 m here, not the millimetres a smooth world would give.

## Next
Round 2 is done: the winner has been re-measured over the network the other entry used, and
the four ideas have each been measured on their own — one kept and load-bearing (the
back-dating), two measured and not kept (the exit hysteresis and the 2-byte evicts), one kept
as a stated bound (the drift budget).

What is left, in the order it would pay:

* **gap-fill resync.** At 2 % loss the keyframes are 7.7 % of the bytes. A repair that sends
  the missed corrections instead of the whole region would cut that, and the drift budget is
  what says how far a missed correction can be.
* **a real link.** The delay and the loss are drawn from a distribution; a deployment would
  measure them. The protocol's assumptions (FIFO, no reordering, independent loss) are
  written down in the README and are the first things to check against a real one.
* **bursty loss.** The simulated loss is memoryless. A real congested link drops runs of
  packets, and each one is a gap.
* The stream belongs beside thor-world's world-stream; whether it moves there is a later call.
