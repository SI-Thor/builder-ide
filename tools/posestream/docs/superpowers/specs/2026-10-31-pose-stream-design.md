# Design: the pose stream (emitter / projector)

Date: 2026-10-31. Mission B, team `mcode`.
Source: `BRIEF.md` in this directory + `builder-ide/docs/design/emitter-projector.md` and `three-minds.md`.
Status: as built (the implementation in `src/` follows this document).

## 1. What the mission asks for

A world of 10,000 deterministic moving objects, 60 ticks/s for 60 s (3600 ticks).
64 subscribers, each with an interest region (moving frustum or sphere) and its own rate.
The emitter sends each subscriber only what its region needs: pose deltas with `since_version`,
quantised, with a stated error bound. Each projector reconstructs the poses of everything in
its region and must match the emitter's ground truth exactly (or within the bound) at every tick
it is delivered.
Bonus: the motion channel (per-object velocity) and a keyframe/resync path for late joiners and
dropped packets.

## 2. Architecture (from `emitter-projector.md`)

The emitter owns the canon (the world) and the spatial index. Interest management decides *which*
deltas reach *which* subscriber. Every subscriber is a projector: it holds its own state, applies
the deltas, and projects them into its own view.

Consequences that shape the implementation:

* The emitter must not know about cameras. So the **motion channel carries the object's world
  velocity**; the projector converts it into *its own* frame (and into optical flow) locally. A
  camera-frame velocity on the wire would make the emitter viewpoint-dependent and would churn
  on every camera rotation.
* "Each projector reconstructs the poses of everything in its region" ⇒ the projector must be
  told the region membership (enter/leave), not just the positions.
* `since_version` ⇒ every packet says which version its deltas are relative to; a gap is
  detectable by the receiver, which then asks for a keyframe.

## 3. World

Arena: 200 m × 200 m × 120 m. 10,000 objects, seeded (xorshift64\* per object, so the world is a
pure function of the seed):

| kind | share | motion |
|---|---|---|
| walker | 70 % | random walk, speed 0.4–2.4 m/s, heading re-sampled every 6 ticks with a bounded turn, so motion is piecewise linear between turns |
| orbiter | 25 % | circle of radius 5–40 m in a random plane, ω set from a speed of 0.5–4 m/s; smooth, so constant velocity predicts it well |
| fast mover | 5 % | random walk, speed 10–40 m/s, heading re-sampled every 3 ticks; these dominate the byte cost |

Position is the truth in float metres. The *quantised truth* is `round(p / Q)` with `Q = 0.01 m`
(1 cm), i.e. integers ("quanta"). Positions and velocities live in separate arrays so the
emitter's random per-object lookups stay cache friendly.

## 4. Quantisation and the error bound

The emitter quantises the **true** position each tick and sends the difference from what the
subscriber already holds. The projector applies the difference with integer arithmetic.
Therefore, at any tick on which the projector holds a current packet:

```
projector position == emitter quantised truth     (exactly)
|projector − truth| ≤ Q/2 per axis = 5 mm          (Euclidean ≤ √3 · 5 mm ≈ 8.7 mm)
```

The bound is **5 mm per axis (1 cm quantum, round-to-nearest)**. It does not accumulate: a delta
is always measured against the quantised truth, never against an accumulated estimate.

Between deliveries the projector *predicts* (the motion channel). That extrapolation is a bonus,
not part of the guarantee, and it is measured: over the run the prediction error is 0 mm at the
median, 30 mm at p95, 130 mm at p99, and up to 32 m in the tail where a fast mover turns and a
constant-velocity guess is wrong. The emitter corrects that at the next delivery.

## 5. Interest management

Uniform spatial hash, 10 m cells (20×20×12 = 4800 cells), maintained incrementally: an object is
re-hashed only when it crosses a cell boundary (swap-remove keeps it O(1)).

Region types:

* **sphere** — centre moves with the subscriber, fixed radius.
* **frustum** — perspective; `near`/`far` and a horizontal/vertical tangent give the exact
  five-plane membership test in the camera basis.

Each delivery: query the cells overlapping the region AABB, exact-test the candidates, and merge
with the subscriber's previous set (both sorted) to get entered, left and common. Objects outside
the region are never mentioned to that subscriber. The 64 subscribers are spheres and frusta,
moving (circle, drift) and idle (static), at 2–60 Hz, eight of them sharing one camera so that
regions overlap. First deliveries are staggered by `id % interval` so the emitter's per-tick load
is even.

## 6. Wire format (v1)

Per subscriber, per delivery. Header (varints, LEB128):

```
0xA1 | flags | tick | since_version | n_region | n_enter | n_leave | n_change | n_prev | n_escape
     | pos_abs_bits | vel_abs_bits | pos_delta_bits[3] | vel_delta_bits[3]
```

`flags`: `KEYFRAME` (full state, no deltas), `CHANGE_BITMAP` (the changed set as a bitmap over
the subscriber's previous set, otherwise delta-coded ids), `VELOCITY` (motion channel on).

* **enter** — delta-coded ids, then the absolute quantised position (u16 per axis) and, with the
  motion channel, the absolute quantised velocity (u16 biased, 1/64 quantum per tick).
* **leave** — delta-coded ids.
* **change** — bitmap or id list, then per changed object a 2-bit mask (position present /
  velocity present) and the delta fields.

Delta fields are *biased* fixed-width bit fields: `v` is stored as `v + 2^(w-1)` in `w` bits, so
the all-ones pattern is free to be an escape marker. The width per axis is chosen to minimise the
total cost (`w` bits for every object, plus a varint for each object that does not fit), so a
handful of fast movers cannot widen the field for everybody else; the values that do not fit
escape into a varint list at the end of the packet. Each record's fields are packed into one
64-bit word and written in a single operation.

## 7. The two delta modes

**Direct.** The delta is measured from the last position this subscriber was told.

**Predictive** (the default). The delta is measured against what the projector can predict from
the motion channel it already holds. The prediction is a *snapshot*: `position + velocity ×
(t − t_anchor)`, where the snapshot is the position, the velocity and the time of the last
correction. A smoothly moving object therefore costs nothing: the projector already knows where
it is. The projector applies the identical prediction, so the two sides agree to the integer.

Both sides must agree on the snapshot, which is why the snapshot velocity is stored separately
from the current velocity: the projector applies a position correction with the velocity it held
*before* the packet, and only then takes the new velocity and re-anchors.

Measured: direct 8,579 B/s per subscriber, predictive 5,796 B/s (mean over the 64 subscribers);
0 reconstruction errors in both.

## 8. Emitter and projector

The emitter keeps, per subscriber, the previous object set and one state record per object (last
sent position, last sent velocity, the anchor snapshot), stored *parallel to the set* so the
per-delivery work is sequential in memory. The projector keeps the mirror image.

The projector checks `since_version` against its own version: a mismatch means a dropped packet
(or a stale changed-set bitmap) → it refuses the packet and asks for a keyframe, the emitter
answers with the full region in absolute poses, and the projector resets to it.

## 9. Verification (the harness is the referee)

For every delivery the harness compares the projector's reconstructed state with the emitter's
ground truth at that tick: the object sets must be identical, and every object's pose must be
identical (the projector holds the quantised truth exactly). Mismatches are counted into
`reconstruction_errors`. The harness also:

* measures the float error vs. the true position (must stay ≤ Q/2 per axis),
* measures the inter-delivery prediction error (bonus),
* makes 4 subscribers join late (ticks 900/1800/2700/3000) → keyframe resync, timed,
* drops 6 packets on purpose → gap detection → keyframe resync, timed,
* hashes every delivered byte, so two runs of the same seed must produce the same digest.

`cargo test` additionally fuzzes the packet round trip and runs two end-to-end tests: the
projector reproduces the ground truth in both modes, and a lost packet is detected and repaired.

## 10. Measurement

* `emitter_cpu_ms_per_tick`: the whole emitter tick — world advance + grid maintenance + interest
  management + delta computation + serialisation — measured with `Instant`. The subscriber-side
  decode/apply is measured separately and is *not* in this number.
* `delivery_latency_ms`: from the world's committed tick to the subscriber's applied state,
  measured in-process (loopback): it includes the emitter's serial service of the other
  subscribers in the same tick, so it is an upper bound.
* `bytes_per_s_per_subscriber`: bytes handed to that subscriber (keyframes included) ÷ 60 s, then
  mean and p95 (nearest-rank) across the 64 subscribers.

## 11. Deliberate non-choices

* The projector does **not** re-simulate the world from the seed. It could (the world is
  deterministic), but then the emitter would have nothing to send and interest management would
  be theatre. The protocol carries the state, as the architecture requires.
* The emitter does not send camera-frame velocity (see §2).
* Single-threaded emitter. The per-subscriber state is disjoint, so it parallelises trivially,
  but a single thread keeps the CPU number unambiguous.
