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

## Next
Re-run the winner with a simulated 2–12 ms network and lossy links (the zcode harness's conditions), then add items 1–3 where they cut bytes or harden the bound. The stream belongs beside thor-world's world-stream; whether it moves there is a later call.
