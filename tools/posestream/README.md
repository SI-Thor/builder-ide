# The pose stream: an emitter that sends each view only what its view needs

Mission B, team `mcode`. A world of 10,000 moving objects, 64 subscribers with moving interest
regions, and an emitter that streams each subscriber the pose deltas its region needs, so that
every subscriber can rebuild the poses of everything it can see — exactly, at every tick, for a
few kilobytes per second.

```
./bench.sh          # builds, runs the tests, writes RESULT.json, checks determinism
./netbench.sh       # round 2: the same world over a simulated network, each idea measured
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

Round 2 turns that measurement into a **bound**: *the drift budget* below states how far the
extrapolation can be from the truth, from the world's own motion parameters, and the harness
checks every interpolation against it.

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

**With a network, the request has to travel too.** The projector that finds a gap sends a resync
request *up* the link; it arrives after the same delay the downlink packets do; the emitter marks
that subscriber and answers with a keyframe at its next delivery, which then crosses the link
again. So a resync costs one round trip of delay plus up to one delivery interval, and the
harness measures it (`resync_recovery_ms_p95`: the median is 32 ms, the p95 108 ms, the worst
509 ms — the 2 Hz subscriber's interval). The request's bytes are not counted in the bytes
metric, the way the other entry also excluded them.

## Round 2: the network

The first measurement had no network: the emitter handed the packet to the projector in the same
process, in the same tick. The other entry's harness had one — a fixed one-way delay of 2–12 ms —
and the verdict asked for the winner to be measured again with a network in the way. This is that
measurement, plus the four ideas the other entry contributed, each measured on its own.

### The link

One link per subscriber, in `src/net.rs`:

* the one-way delay is drawn per packet, uniformly from **[2, 12] ms**, plus a zero-mean uniform
  jitter of **±1.5 ms** (so 0.5–13.5 ms in practice);
* a packet is **lost with probability 0.5 % or 2 %**, independently of everything else;
* the delay stays below one tick (16.667 ms), so a subscriber's packets never overtake each other
  and the link is FIFO. The harness counts the reorderings rather than assuming them: the measured
  number is **0**;
* the resync request travels back over the same link, with the same delay.

The clock is in **microticks** (1e6 per tick) because the receiver has to know *when* a packet
arrived to better than a tick — that is what back-dating needs.

**What is simulated and what is not.** The world, the emitter and the projectors are real code and
real CPU time. The *link* is a model: delay and loss are drawn from a distribution, not measured
from a socket. There is no real network, no socket and no second machine; the emitter and the
projectors exchange bytes through the model's queue, which is the same exchange a deployment would
make over a real link.

### What the network costs

The same seed, the same 64 subscribers, the same 60 s at 60 Hz.

| run | bytes/s per subscriber (delivered) | bytes/s on the wire | delivery latency p95 | reconstruction errors | resyncs | keyframes |
|---|---:|---:|---:|---:|---:|---:|
| the loopback (round 1's conditions) | 5,796 | 5,796 | 0.54 ms | 0 | 3 | 67 |
| the network, no loss | 5,796 | 5,796 | 13.09 ms | 0 | 3 | 67 |
| the network, 0.5 % loss | 5,911 | 5,940 | 13.09 ms | 0 | 380 | 492 |
| the network, 2 % loss | 6,244 | 6,374 | 13.09 ms | 0 | 1,560 | 1,783 |

**The delay alone costs nothing.** The bytes are identical to the byte — the stream digest is the
same — and the reconstruction is exact at every delivery. The delay costs latency: the p95 goes
from 0.54 ms to 13.09 ms, which is the link's own 13.5 ms worst case plus the receiver's service
and the emitter's wait for that subscriber.

**Loss costs bytes, and the cost is the resync.** At 0.5 % the delivered bytes rise 2.0 %; at 2 %
they rise 7.7 %. The reason is the keyframe: a lost packet leaves the projector one version
behind, the version check fires, the projector asks for a keyframe, and the keyframe is the whole
region in absolute poses (about 1 kB for an average region of 82 objects). 380 lost packets became
380 keyframes at 0.5 %, and 1,560 at 2 %. A gap-fill repair — sending the missed corrections instead
of the whole region — would cut that; it is not implemented here.

The recovery is quick: from the gap to the keyframe's arrival the median is 32 ms and the p95 is
108 ms; the worst is 509 ms, which is the 2 Hz subscriber's delivery interval (a keyframe can only
be sent at a delivery, and that subscriber has one every 30 ticks).

### (a) The back-dating: kept, and it is load-bearing

The other entry's receiver *back-dates* a correction: a record tagged with tick T is applied as if
it had been computed at T, so the delay never moves the state. The winner's receiver holds a
snapshot (position, velocity, anchor time) rather than dead-reckoning every tick, so the same idea
becomes: **the anchor time of a correction is the tick the correction was computed for**, not the
tick it arrived at.

The harness measures both. `--backdate off` makes the receiver anchor at the arrival instead — the
natural thing to do if you do not think about it, because that is when the data turned up.

| | reconstruction errors | mirror mismatches | worst error |
|---|---:|---:|---:|
| back-dating on, 0.5 % loss | **0** | **0** | 0 mm |
| back-dating off, 0.5 % loss | 9,169,158 | 9,384,114 | 2,140 mm |
| back-dating on, 2 % loss | **0** | **0** | 0 mm |
| back-dating off, 2 % loss | 8,673,717 | 9,109,745 | 900 mm |

Without it, essentially every delivery is wrong: 9.17 million of the 9.47 million delivered
states, with errors of up to 2.14 m. With it, the reconstruction is exact at every delivery
whatever the link did, and the receiver's held state is **bit-identical to the emitter's mirror** —
the invariant the resync path depends on.

The mechanism: a receiver that anchors at the arrival adds the motion between the correction's
tick and the arrival to the correction's base, and then adds it again when it extrapolates.
Anchoring at the correction's tick makes the base and the anchor agree with the emitter's, so the
receiver's state *is* the emitter's truth at that tick, exactly.

**Kept.** It costs nothing on the wire (the packets are the same bytes) and it is what makes the
guarantee hold.

### (b) The exit hysteresis: measured, and not kept

The other entry keeps an object in the subscriber's region until it is 8 m outside it, so that an
object on the boundary does not churn in and out. `--hysteresis M` does the same here (for a
frustum: M metres of extra range and M metres of extra width at the far plane).

| margin | enters | leaves | change records | delivered states | bytes/s | emitter work p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 0 m | 86,786 | 79,353 | 7,346,143 | 9,471,363 | 5,796 | 0.56 ms |
| 2 m | 85,215 | 77,014 | 8,127,481 | 10,467,187 | 6,328 | 0.67 ms |
| 8 m | 82,654 | 72,251 | 10,144,140 | 13,037,976 | 7,697 | 0.86 ms |
| 16 m | 79,891 | 66,716 | 12,556,607 | 16,110,606 | 9,345 | 1.13 ms |

The hysteresis does what it says: at 8 m it removes 9 % of the leaves. But it costs 33 % more
bytes, because every object it holds outside the region still costs a change record per delivery,
and it costs the emitter 54 % more CPU (the membership test runs twice, and the candidate box grows
by the margin).

**Not kept.** On this world the regions are small (14–30 m) against a dense world (10,000 objects
in 200 m × 200 m × 120 m), so an 8 m margin holds about a third more objects. The idea would pay
off where the regions are large relative to the object density — zcode's were 80–180 m in a
1200 m arena.

### (c) The 2-byte evicts: measured, and not kept

The other entry's evict is two bytes: a fixed 16-bit object id. Here the leave list is delta-coded
varints, which is one byte when the ids are close and two when they are not. `--evict2 on` switches
the leave list to fixed 16-bit ids.

| | bytes/s per subscriber |
|---|---:|
| delta-coded leave ids | 5,796 |
| absolute 16-bit evicts | 5,798 |

The delta-coded list is already at or below two bytes per object, so the fixed-size evict costs
2 B/s per subscriber (0.04 %). **Not kept**: there is nothing to gain, and the delta-coded list is
cheaper exactly when the evictions cluster.

### (d) A provable drift budget: kept, as a stated bound

Between two corrections the projector holds the last corrected pose and extrapolates it with the
motion channel. That extrapolation is only as good as the world's motion is smooth, and "it stayed
within the bound" is not a guarantee. The budget makes it one.

The derivation (also in `src/budget.rs`; the table below is computed by it, not typed in): the
projector's pose for an object is `p(t0) + vh · (t - t0)` — the position of its last correction
extrapolated with the velocity of that correction. The error against the truth is

```
error(t) = (v(t0) - vh) · (t - t0)
         + the sum, over every velocity change in the interval, of that change times the time
           it persists
```

The first term is the velocity quantisation (half a velocity quantum). The second is where the
world's parameters come in, per kind:

* an **orbiter** turns uniformly, so its acceleration is exactly `v²/r ≤ 3.2 m/s²`, and the
  integral is the usual half-acceleration term;
* a **walker** holds its velocity for 6 ticks and then changes it by at most
  `42 · (2 sin(0.11) + 0.06) = 11.75 m/s`. The walker's *initial* speed is at most 2.4 m/s, but the
  speed is re-sampled every turn and clamped only at 42 m/s, so the bound uses the clamp;
* a **fast mover** does the same every 3 ticks;
* an object that **reflects** off the arena wall has a velocity component flipped: no
  constant-velocity extrapolation can see that, so an interval containing a reflection gets its
  own bound (2 v per tick from then on, 42 m/s over 30 ticks).

The bound, by delivery interval (the intervals the 64 subscribers actually use):

| every | orbiter | walker | fast mover |
|---:|---:|---:|---:|
| 1 tick | 0.016 m | 0.211 m | 0.211 m |
| 2 ticks | 0.018 m | 0.407 m | 0.407 m |
| 3 ticks | 0.021 m | 0.602 m | 0.602 m |
| 4 ticks | 0.024 m | 0.798 m | 0.994 m |
| 6 ticks | 0.034 m | 1.190 m | 1.777 m |
| 12 ticks | 0.085 m | 3.538 m | 5.887 m |
| 30 ticks | 0.431 m | 17.629 m | 32.306 m |

The verification: the harness measures the projection against the truth at every tick, for every
object every subscriber holds, and checks it against the bound for that object's kind and
staleness. Over the 60 s run at 2 % loss, **24,713,234 checks and not one over the bound**.

The worst interpolation of that run was 87.3 m: a fast mover **89 ticks past its last
correction** — the packets that should have corrected it were lost, so the staleness ran past
the delivery interval — and the bound for an 89-tick interval is 267.1 m. The table above is
therefore the floor of the bound, not its ceiling: a lost packet moves the staleness, and the
staleness is what the bound is a function of.

The bound is a worst case over the world; what actually happened is much tighter — over the same
run the median drift was 0 mm for walkers and orbiters and 10 mm for fast movers, with p95s of
30 mm, 10 mm and 620 mm.

**Kept**, as a statement rather than a mechanism: it costs nothing, and it turns the tail of the
prediction-error distribution from an observation into a number the reader can check.

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
* **emitter_work_ms_per_tick_p50 / _p95** — the emitter's *own* work per tick (the interest
  query, the delta computation and the encoding), without the world advance and without the
  harness's own verification. The `emitter_cpu_ms_per_tick_*` figures above are the whole tick,
  as in round 1, so they include the referee.
* **bytes_per_s_per_subscriber_sent_mean** — the bytes put on the wire, before the link drops
  any. The difference from the delivered figure is what the link lost.
* **packets_sent / packets_lost / packets_delivered** — the link's own counts.
* **keyframes / resyncs** — how many keyframes the emitter sent, and how many gaps the
  projectors found.
* **resync_recovery_ms_p95** — the time from a gap to the keyframe's arrival.
* **mirror_mismatches** — how often the receiver's held state was not bit-identical to the
  emitter's mirror. Zero means the delay never touched the state.
* **max_reconstruction_error_mm** and **max_state_divergence_mm** — the worst of each.
* **drift_over_budget / drift_checks** — the drift budget's verification: how many
  interpolations were checked against the bound, and how many were over it.

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
| `src/net.rs` | the simulated link: the delay, the jitter, the loss, the uplink |
| `src/budget.rs` | the drift budget: the bound, derived from the world's parameters |
| `src/bench.rs` | the harness: the referee, the statistics, `RESULT.json` |
| `src/main.rs` | the command line |

`cargo test` runs the wire round-trip fuzz, the world's determinism, the quantisation bound, and
the end-to-end tests: the projector reproduces the ground truth in both modes; a lost packet is
detected and repaired by a keyframe; the back-dating keeps the delay out of the receiver's state
(and the version without it does not); the exit hysteresis changes the membership without adding
churn; and the absolute evicts round-trip.

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

## What is modelled, and what is not

The numbers above are only worth what the harness's assumptions are worth, so they are written
down:

* **The link is a model, not a socket.** Delay and loss are drawn from a distribution per
  packet. There is no real network, and the emitter and the projectors share a process and a
  clock. A deployment would split them across machines with the same byte stream.
* **The delay is below one tick**, so the link is FIFO and no packet overtakes another. A link
  that reordered packets would make the receiver refuse the later one (the version check) and
  pay a keyframe for it; that path is not exercised here.
* **The loss is independent and memoryless.** A real link's losses come in bursts (a congested
  queue drops a run of packets), which is worse: one burst can cost several keyframes, because
  each lost packet is one gap.
* **The world's motion is not acceleration-bounded in the other entry's sense.** That entry
  built its world with a hard acceleration cap (1.8 m/s² per axis) so its drift budget would
  come out tight. This world has walkers that turn impulsively and objects that reflect off
  the arena wall, so the budget here is derived per kind from the world's actual parameters,
  and the impulsive cases are named rather than smoothed over. The consequence is visible in
  the table: the bound for a fast mover over 30 ticks is 32 m, not the millimetres a smooth
  world would give.
* **The receiver applies a packet when it arrives**, in the same tick it was emitted, because
  the delay is shorter than a tick. The measured latency is therefore the link's delay plus the
  emitter's wait plus the receiver's service, and it is not quantised to a tick.
* **The referee is inside the timed region** for the `emitter_cpu_ms_per_tick_*` figures (as in
  round 1) and outside it for `emitter_work_ms_per_tick_*` and for the delivery latency. The
  delivery latency in round 1 was measured with the verification inside the timed region too,
  so the round-2 figure for the loopback (0.54 ms) is smaller than round 1's (0.67 ms) for
  that reason alone; the bytes and the errors are identical.
