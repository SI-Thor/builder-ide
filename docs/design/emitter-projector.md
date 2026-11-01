# The emitter and the projectors: send what each view needs, let each view render itself (2026-10-31)

**From Casey's observation about Syzygy, and the architecture of the original Spasim.** ASCII renderings work best for a person who is *moving*: parallax reveals depth. When still, things that move pop out. The information is in the **deltas of relative perspective**, not in static detail. The original Spasim's central machine never rendered anyone's view: it sent each terminal only the facts it needed, and every terminal projected them into its own perspective. The centre stayed viewpoint-agnostic and scaled with what changed, not with the number of viewers. (The architecture is the reference; we are not recreating the game.)

## The principle

1. **The Thor is the emitter,** and it is viewpoint-agnostic. It emits a compact, ordered stream of **world deltas**:
   - object poses and velocities in world coordinates;
   - recipe changes;
   - events (a builder placed a crate, the critic rejected a lamp).

   Each delta carries its `since_version`, so a late joiner asks for the gap, or for a full world (the keyframe).
2. **Interest management:** each subscriber receives only the deltas that can affect *its* view (in or near its frustum, relevant to its task, or addressed to it). The emitter knows each subscriber's *interest*, not its camera.
3. **Every view is a projector:**

   | View | What it does with the deltas |
   |---|---|
   | The **human viewer** (three.js, `thor-world`) | Renders its own camera at its own frame rate |
   | A **Syzygy text view** | Projects, then runs the integer kernel locally. The kernel is deterministic, so any client produces identical bytes from the same state; no frames are sent |
   | A **builder character's perception** | Gets its own projection of only what it needs to know: privacy and scale for many agents |
   | **Magnus's flight sim** (OpenSkyFlight / Sitka Skies) | Another projector of the same stream |

4. **The motion channel.** Because every projector knows its own camera and the objects' motion exactly, it can compute **per-cell optical flow in its own frame** at no cost:
   - when moving, it is a parallax depth cue;
   - when still, it is a "what moved" mask.

   For an AI reader this is the signal humans get from watching ASCII in motion, made explicit. It is also the motion vector a video codec would estimate, here known exactly.
5. **Where the resolution cost goes:**
   - **Emitter side:** state changes, kilobytes, no rendering.
   - **Projector side:** each client spends its live budget on motion and its idle time on sharpening the static scene (keyframes, held in its cache).

   Detail is bought locally, when there is time for it.

## What already exists

- **world-stream (thor-world):** recipe deltas over SSE with `since_version`, a full world as the keyframe, byte-identical compiles, and a browser that projects locally.
- **The ledger and the event log:** the ordered history the emitter reads from.
- **Per-agent tokens (core-doors):** a subscriber's identity, on which interest management can key.

## What to build

1. **Pose and velocity deltas** in world-stream, alongside the recipe deltas: the continuous part of the world.
2. **Interest management:** subscriptions declare an interest region and a task, and the emitter filters.
3. **A Syzygy projector** that subscribes to the stream, renders text locally and emits the motion channel. It is being tested in `~/lm-wt/syzygy-keyframes`, arms (g) and (h).
4. **Characters as projectors:** each builder's perception becomes a subscription, not a render.

## The test that decides it

The syzygy-keyframes experiment measures:
- bytes per frame for emitting state against sending frames;
- whether an explicit motion channel raises a reader's accuracy on depth order, approaching objects and moving objects, with the camera moving and still.

That turns Casey's observation into a number.

## Temporal stereoscopy: perception as listening (Casey, 2026-10-31)

Casey: low-resolution ASCII looks strongly 3D to a person because the frames over a short span of visual memory act like two eyes separated in time. The characters' flicker where structure moves carries the depth, and "it's like listening: you don't see the 3D space unless you carry it around and you get used to the rhythm of the changes, like finding the sound of a song as a guest soloist." (SuperInstance/chiaroscuro makes those aspects pop for a person on purpose.)

What it implies for any projector that feeds a model rather than a person:
- **Memory:** the reader must integrate over a window, so a stateful model (Liquid's recurrent and state-space family) or a short frame window is needed. A single frame is the wrong unit.
- **Events, not frames:** per-cell change events (as an event camera emits) are the sparse, informative part.
- **Rhythm:** each region's temporal spectrum, so the reader can notice a broken rhythm.
- **Active parallax:** when unsure, move a little and look again, as a pigeon bobs its head. In builder-ide, a character that is unsure of a spatial judgment can take a small epistemic move before escalating to a bigger model.

These are arms (i) to (l) of the syzygy-keyframes experiment.

## Time-first, not only state-first (Casey, 2026-10-31)

"I'm, at the core, time-first, and you are state-first. Time-first only perceives change … a rate of change as a sense." Our gates so far are state-first: escalate when confidence is *below* τ; hold a *level* with hysteresis. A time-first design also gates on **rates of change**:
- the derivative of confidence;
- the rate of cell events;
- a region's rhythm breaking.

It feeds readers timestamped changes with Δt, and prefers time-native models (Liquid's liquid time-constant lineage) for perception over time. The rate gate is being tested against the level gate in syzygy-keyframes and in lab-cascade (on the recorded d1 traces).
