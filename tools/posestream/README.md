# The pose stream: an emitter that sends each view only what its view needs

Mission B, team `mcode`. A world of 10,000 moving objects, 64 subscribers with moving interest
regions, and an emitter that streams each subscriber the pose deltas its region needs, so that
every subscriber can rebuild the poses of everything it can see — exactly, at every tick, for a
few kilobytes per second.

```
./bench.sh          # builds, runs the tests, writes RESULT.json, checks determinism
```

Rust, standard library only (no crates, no network, no system installs). One binary,
`posestream`.

## The architecture this implements

`builder-ide/docs/design/emitter-projector.md` says the emitter is viewpoint-agnostic: it emits
world deltas, it filters by *interest*, and every view is a projector that renders from what it
was told. Three consequences shape this implementation:

* **The emitter never learns about cameras.** It knows a subscriber's interest region (a sphere
  or a perspective frustum), not its viewpoint. That is also why the motion channel carries
  velocities in *world* coordinates: the projector rotates them into its own frame locally.
  Shipping camera-frame velocities would make the emitter viewpoint-dependent and would make
  every packet churn whenever the camera turns.
* **The projector must be told the region membership**, not just the positions: an object that
  enters the region arrives with an absolute pose, an object that leaves is named and dropped.
* **`since_version` is in every packet**, so a gap is detectable by the receiver and repairable
  from a keyframe.

`three-minds.md` puts the emitter in the "canon" role: one committed history, many simple
viewers. The projector never writes history; when it disagrees with the canon it resynchronises
from a keyframe, never the other way round. That is exactly what the resync path below does.

## The world

An arena of 200 m × 200 m × 120 m holds 10,000 objects, seeded (so the world is a pure function
of the seed and the benchmark can replay it exactly):

| kind | share | motion |
|---|---|---|
| walker | 70 % | random walk, 0.4–2.4 m/s, heading re-sampled every 6 ticks with a bounded turn |
| orbiter | 25 % | circle of radius 5–40 m in a random plane, speed 0.5–4 m/s |
| fast mover | 5 % | random walk, 10–40 m/s, heading re-sampled every 3 ticks |

The motion is deliberately *predictable between turns*: a walker's velocity is constant for its
epoch, an orbiter's velocity turns smoothly. That is what makes the motion channel worth
carrying, and it is why the fast movers (5 % of the objects) dominate the byte count — they
turn twice as often as anybody else.

## Interest management

A uniform spatial hash with 10 m cells (20 × 20 × 12 = 4800 cells) is maintained incrementally:
an object is re-hashed only when it crosses a cell boundary. A delivery does:

1. the region's bounding box → the cells that can contain it;
2. the exact membership test on those candidates (sphere: distance; frustum: five planes in the
   camera basis);
3. a merge of the new set with the subscriber's previous set (both sorted) → entered, left, and
   the common part.

Objects outside the region are never mentioned to that subscriber. The 64 subscribers are a mix
of spheres and frusta, moving (circle, drift) and idle (static), at 2–60 Hz, eight of them
deliberately sharing one camera so that regions overlap. Their first deliveries are staggered by
`id % interval`, so the emitter's per-tick load is even rather than bursty.

## What goes on the wire

One packet per subscriber per delivery:

```
0xA1 | flags | tick | since_version | n_region | n_enter | n_leave | n_change | n_prev | n_escape
     | pos_abs_bits | vel_abs_bits | pos_delta_bits[3] | vel_delta_bits[3]
```

* **enter** — delta-coded ids, then the absolute quantised pose (u16 per axis) and the absolute
  quantised velocity (u16 biased, 1/64 quantum per tick).
* **leave** — delta-coded ids.
* **change** — the changed set as a bitmap over the subscriber's previous set (one bit per
  previous object) when that is cheaper than the id list, otherwise delta-coded ids; then, per
  changed object, a 2-bit mask (position present / velocity present) and the delta fields.

Delta fields are *biased* fixed-width bit fields: a value `v` is stored as `v + 2^(w-1)` in `w`
bits, so the all-ones pattern is free to be an escape marker. The width per axis is chosen to
minimise the total cost — `w` bits for every object plus a varint for each object that does not
fit — so a handful of fast movers cannot widen the field for everybody else. Outliers that do
not fit escape into a varint list at the end of the packet. Each record's fields are packed
into one 64-bit word and written in a single operation.

## Two delta modes

Both modes deliver exactly the same information; they differ in what the delta is measured
against.

**Direct** (`--mode direct`): the delta is measured from the last position this subscriber was
told. Simple, and the projector accumulates deltas to the truth.

**Predictive** (`--mode predictive`, the default): the delta is measured against what the
projector can *predict* from the motion channel it already holds. The prediction is a
snapshot — `position + velocity × (t − t_anchor)` — where the snapshot is the position, the
velocity and the time of the last correction. A smoothly moving object therefore costs
**nothing at all**: the projector already knows where it is, so the emitter has nothing to say.
The projector applies the identical prediction, so the two sides agree to the integer.

This is the mechanism behind the byte count: the motion channel carries the motion, and the
position channel only has to correct what the motion did not explain.

| | bytes/s per subscriber (mean) | p95 | emitter ms/tick (p50) | reconstruction errors |
|---|---|---|---|---|
| direct | 8,579 | 26,130 | 0.74 | 0 |
| predictive | 5,796 | 16,643 | 0.79 | 0 |

## The error bound

Positions are quantised to a 1 cm grid, round-to-nearest, so the quantised truth is at most
**5 mm per axis** away from the float truth (Euclidean at most 8.7 mm). The projector reproduces
the quantised truth *exactly* — integer arithmetic, no accumulated drift, because every delta is
measured against the quantised truth and never against an accumulated estimate.

So the guarantee is: **at every tick a subscriber is delivered, the projector's pose for every
object in its region equals the emitter's quantised ground truth exactly**, and therefore lies
within 5 mm per axis of the true float position. The benchmark checks exactly that, for all
9,471,363 delivered states of the scored run: **0 mismatches**, with the observed maximum error
equal to the bound (5.000 mm).

Between deliveries the projector holds its last corrected pose and interpolates with the motion
channel. That extrapolation is a bonus, not part of the guarantee, and it is measured too: over
the run, the prediction error is 0 mm at the median, 30 mm at p95, 130 mm at p99, with a tail of
32 m where a fast mover turns and the constant-velocity guess is simply wrong. The emitter
corrects that at the next delivery.

## Resynchronisation

Every packet says which version its deltas are relative to. A subscriber that joins late, or
that lost a packet, sees a version that does not match what it holds, refuses the packet, and
asks for a keyframe; the emitter answers with the whole region in absolute poses and the
projector resets to it. A lost packet is detected either by the version check or by the
changed-set bitmap being about a set the projector does not hold.

The scored run exercises both: four subscribers join late (ticks 900, 1800, 2700, 3000) and six
packets are dropped on purpose. Both paths recover, and the reconstruction stays exact
afterwards. `late_join_resync_ms` in `RESULT.json` is the worst service time for a
first delivery — the emitter's work (interest query, delta computation, encoding) plus the
projector's decode, apply and verification, for the region in question.

## What the numbers mean

`bench.sh` writes `RESULT.json` (exactly the keys the brief asks for) and `bench_log.txt`
(everything else: the per-subscriber table, the byte breakdown, the phase timings, the
prediction-error distribution, the gap events, the stream digest).

* **bytes_per_s_per_subscriber** — bytes handed to that subscriber over the run ÷ 60 s,
  keyframes included; then the mean and the p95 (nearest-rank) over the 64 subscribers. The
  number is deterministic: the same seed produces the same bytes, and `bench.sh` checks that by
  hashing every delivered byte.
* **emitter_cpu_ms_per_tick** — the whole emitter tick: the world advance (the canon writing
  history) plus interest management, delta computation and serialisation. Measured with
  `Instant`; single threaded, so it is also the CPU time. The subscriber's decode and apply are
  *not* in this number; they are in the latency figure and in the log.
* **delivery_latency_ms_p95** — from the world's committed tick to the subscriber's applied
  state, in the in-process loopback: it includes the emitter's serial service of the other
  subscribers in the same tick, so it is an upper bound (a deployment would serve the 64 links
  in parallel; the per-subscriber state is disjoint, so that is a one-line change).
* **late_join_resync_ms** — the worst first-delivery service time, as described above.

## Where the bytes go

From `bench_log.txt` (predictive mode, scored run):

```
header 8.1%   enter 5.1%   leave 0.4%   changed-set 5.5%
pos deltas 29.6%   vel deltas 30.5%   masks 8.1%   escapes 20.4%
```

The motion channel and the position corrections cost about the same, and the escapes are the
fast movers refusing to fit in the delta field.

The motion channel, expressed in the subscriber's own frame (the emitter sends world velocities;
the projector rotates them locally, which is also the optical flow a renderer would use): mean
apparent speed 4.8 m/s, max 51.5 m/s, and every object in view is in motion — the "what moved"
mask is all ones in this world, because everything moves.

## The code

| file | what it holds |
|---|---|
| `src/world.rs` | the seeded world: RNG, walkers, orbiters, fast movers, quantisation |
| `src/space.rs` | the spatial hash, the two region shapes, the 64 subscribers and their paths |
| `src/wire.rs` | the packet format: bit writer/reader, biased delta fields, escapes |
| `src/stream.rs` | the emitter (interest management, deltas) and the projector (reconstruction) |
| `src/bench.rs` | the harness: the referee, the statistics, `RESULT.json` |
| `src/main.rs` | the command line |

`cargo test` runs the wire round-trip fuzz, the world's determinism, the quantisation bound,
and two end-to-end tests: the projector reproduces the ground truth in both modes, and a lost
packet is detected and repaired by a keyframe.

## Deliberate non-choices

* **The projector does not re-simulate the world.** It could — the world is deterministic, so a
  projector holding the seed could regenerate everything and the emitter would have nothing to
  send. That would make interest management theatre and the emitter pointless. The stream
  carries the state, as the architecture requires; the only thing a projector derives locally
  is the *view* of that state (its own frame, its optical flow).
* **The emitter sends world velocities, not camera velocities** (see the architecture above).
* **The emitter is single threaded.** The per-subscriber state is disjoint, so serving the
  subscribers in parallel is easy, but one thread keeps the CPU number unambiguous.
* **The interest regions are modest**: spheres of 14–30 m and frusta reaching 25–50 m, which
  hold 13–313 objects each (82 on average) in a 200 m arena with 10,000 objects. The byte
  numbers are only meaningful together with that; `bench_log.txt` prints the region size of
  every subscriber.
