# Three minds: reflex, canon and mediator (Casey, 2026-10-31)

Casey's frame: MIDI Maze's real-time multiplayer (Atari ST machines in a MIDI ring, lockstep) and Spasim on PLATO (a central machine emitting each terminal's need-to-knows) are like the id and the superego; "debate could be had on who is who". An LLM doing its best to improve the system *while it runs* is the ego. All of it is then ported out to a real game engine or to the real world. (These games are referenced for their **architectures**; we do not recreate them.)

## The three roles

| Role | The reference architecture | What it guarantees | builder-ide today |
|---|---|---|---|
| **Reflex** (fast, lockstep, no authority) | MIDI Maze: only inputs travel round the ring, and every machine runs the identical deterministic simulation | Agreement without a server; millisecond reactions | Deterministic integer kernels (Syzygy, byte-identical world-stream compiles, lattice snapping); d1 and tiles choosing in tens of milliseconds; the first mile's cached reflexes |
| **Canon** (authority, one history) | Spasim/PLATO: a central truth emits need-to-knows, and terminals project | One committed history; rules enforced; viewers stay simple | The ledger and event log (the committed spine), the invariant kernel and the vocabulary's veto, the emitter with interest management (`emitter-projector.md`), the WHY kernel |
| **Mediator** (reflective, slow, improves the system in motion) | An LLM watching the running system | The system gets better without stopping | The cloud improver (keeps only edits that win), the engineer's work orders, the tiles' cloud authors |

## The rules between them

1. **The mediator never blocks the reflex.**
   - never-wait: past a deadline the reflex's answer commits, and the mediator's later answer is recorded as a *supersede*, never as an edit to history.
   - Harness changes land between ticks.
2. **The canon is the only writer of history.** Reflex nodes propose (inputs, choices); the canon commits; projectors render. A reflex node that disagrees with the canon resynchronises from it (a keyframe), never the other way round.
3. **The mediator's changes are replayed before they are trusted.** Because the reflex layer is deterministic, a proposed change (a new tile, a gate setting, a harness edit) can be replayed against *recorded inputs* and compared with what actually happened. That is the shadow conductor, plus off-policy evaluation for choosers, plus the paired gate for harness edits. Then a trust ladder decides how much it may run unattended.
4. **Time-first throughout** (`emitter-projector.md`): reflexes and gates read rates of change, not only levels.

## Porting out

The roles meet at **contracts**, not at an engine:
- reflex nodes need deterministic inputs;
- the canon needs typed, ordered deltas;
- the mediator needs typed edits with evidence.

So the same three minds run in a real game engine (last-mile in Bevy, or Roblox as a proof-of-concept place) or in the real world (a robot whose reflexes read Syzygy text from real sensors, whose canon is a shared map, and whose mediator is a cloud model improving its tiles). You swap the simulation and the projectors, not the minds.

## The reflex layer as a room, not a ring (Casey, 2026-10-31)

"With tensors and multi-threads and warps, we don't have to think about the MIDI as only a ring. It's a neural network. The ring is just the simple, manageable node system for good-enough. But we can think about who is connected to who, and how the reverberation is filtered automatically, like a room."

- **The room as a relevance filter.** Nodes (builders, readers, projectors, decision models) sit in a space, physical or semantic. Edges carry change events with a **delay** that grows with distance and a **gain** that falls with distance and per hop (absorption). Each node hears the superposition: near neighbours early and strong, far ones late and faint, nothing past the walls. Interest management becomes continuous rather than a yes/no need-to-know.
- **Stability is a spectral property.** One tick of propagation is a sparse matrix P applied to the change vector. Echoes die away if and only if P's spectral radius is below 1: absorption beats gain around every loop. That is a room's reverb time (RT60) in linear-algebra form. The crew's holonomy and cycle-consistency work, the missing cycle check in new2's cell graph, and constraint-crdt's exponential decay are all ways of keeping it below 1.
- **On the Thor:**
  - propagation per tick is one batched sparse multiply, on the GPU (which wins from N ≈ 20 with CUDA Graphs, `exp-ct-thor.md`);
  - inboxes stay resident in unified memory;
  - connectivity can be **learned** from outcomes (who should hear whom), as attention is a learned room.

*Experiment (queued):* ring vs broadcast vs room propagation on bandwidth per tick, the latency of *relevant* events, the total echo energy over time, and whether the spectral-radius rule predicts the measured decay.

## Two media: the text world and the neural graph (Casey, 2026-10-31)

"On one side you have a PLATO-like MUD that innately gives every agent their own perspective without much compute, and on the other side you have a close-to-latency-free neural graph."

| | The text world (MUD-like) | The neural graph |
|---|---|---|
| Who lives there | The **mediator** (LLMs) and the **canon** (rooms, exits, objects, committed history) | The **reflexes** (d1 decisions, tiles, motion policies) |
| Medium | Text: a few hundred characters per agent's perspective, projected from shared state; a mostly cached prompt prefix | Tensors: change events through a sparse, learned room matrix, microseconds per tick on the GPU |
| Strength | Cheap per-agent perspective, native to LLMs, auditable | Latency-free, parallel, time-first |

**The bridge, in both directions:**
- **Geography → topology:** the MUD's rooms and exits define the graph's edges, walls its absorption, distance its delay. Editing the world (opening a door) rewires the graph.
- **Activity → narration:** the graph's change events condense into lines in each agent's text view ("something moved quickly to the north"): the time-first signal, made readable.
- **Projection:** Syzygy (and the emitter's projectors) turn the continuous world into text for any viewpoint, deterministically and cheaply.

Each mind works in the medium it is best at, and neither waits for the other.

## The operational fiction, and who decides how real it must be (Casey, 2026-10-31)

"That makes the PLATO side more like the sensory side, which is then ported to the IO that updates its operational fiction: an as-real-as-needed version. And that question of what is needed is one that the system-2 LLMs are crafting for their fleet as they go along with the rest of their work, above the arena."

The Syzygy program's rule, generalised: *a model should only ever pay for the vision its one job needs.*

- **The text world is perception, not the world.** Each agent's view is what it senses.
- **The IO keeps an operational fiction:** the game engine, sensors and Infinigen scene maintain a world model **as real as the work needs**, and no more.
- **The mediator authors the perception spec,** as data, for its fleet. It specifies, per kind of agent:
  - which objects and attributes it senses;
  - at what resolution;
  - which rates of change matter (time-first);
  - the keyframe policy;
  - what is narrated into its text view.
- **Fidelity is learned from outcomes.** When a reflex decides badly and the post-mortem shows missing information, the spec gains that channel or detail. When a channel never informs a decision that mattered, it is dropped. Perception specs are **another kind of tile**: cloud-written, scored by results (with off-policy evaluation as the honest judge), kept or retired. It is last-mile's lesson, that the trainer's main lever is choosing the right questions, applied to *what to see*.

The result: the fiction gets cheaper and sharper at once, with detail flowing to where decisions need it.

## The band (Casey, 2026-10-31)

"The MIDI Maze side can be locked into a groove as a musician … in the moment, with an improv session, as the PLATO side turns down the resolution and up the differences, so the agent is close to the metal with its choices and connections. With planned moments to take a break from the moment and get a high-resolution reference frame in the middle of a lick they know well, their fingers on autopilot for a second. Then they put the blinders on and use what they just noticed (the dancers vibing, their drummer giving them and the band a look that he should take another chorus as a solo because he's on fire) to willingly nudge him. **The Thor is a band, not one player.**"

- **When to take the high-resolution look: the autopilot window.** Keyframes are timed for moments when the reflex is in a well-rehearsed pattern (high confidence and a *low rate of change*), not merely idle ones. The reflex carries itself, so the look costs no performance. This adds to the cut, drift and idle triggers.
- **What to look at: the room, not the score.** The glance gathers context and **other players' state** (peers, the human), and it becomes a *nudge* on the next choices, not an interruption. Then the blinders go back on: low resolution, high difference, close to the metal.
- **Cues, not scores.** Players coordinate by cues: sparse, high-gain signals on their own channel in the room graph ("take another chorus"), not by broadcasting everything.
- **The drummer's look, in the night.** When the critic sees a builder's work *improving fast*, it cues the scheduler to grant that loop another chorus (more iterations), taken from loops that have gone flat. This is the time-first scheduler.
- **The audience is the human.** What Casey keeps, undoes or looks at is the dancers' feedback, a nudge on what the band plays next.
- **The band on the Thor:** a d1 per character, the critic, the generators, the scheduler and the first mile. Many players on one stage, each in its own groove, listening for cues.

## Flow: the mediator observes (Casey, 2026-10-31)

"Humans are attention-first thinking when they are in flow state. A band in the pocket is trying not to think. Thinking is processing at the ego level, when they just want that knower, the superego, to keep giving them the sign (like a JEPA reading, or the intuition that if they asked the decision model whether they were sounding good, it would laugh and say yeah) that they should just keep going. In those moments the musician's pleasure is not needing to use the LLM; it would get in the way. And if they did use it, it would be to be in the moment and to bring others into the moment. When the human dances for real, he puts his processing power into those other two parts and lets the ego be an observer."

- **The knower's sign** is a fast predictive signal: a JEPA-style world model predicting the next moment in latent space (the Thor's rack has I-JEPA and V-JEPA 2) shows **low prediction error**, while the decision models stay **confident and steady**. That is "yeah, keep going".
- **In flow the mediator observes.** Reflexes play, the knower nods, and the LLM watches: it logs what works and writes its notes for later, with near-zero calls. Intervening would add latency, cost and second-guessing to a groove that is working.
- **It steps back in** on two triggers only:
  1. the sign fades (prediction error rises, or confidence slides: the rate gate);
  2. someone needs bringing into the moment (a new agent, or the human arriving), where its job is to narrate the vibe and draw them in, not to steer.
- **Measure it:** mediator calls in flow vs out of it, and whether intervening during flow ever improves the outcome. Our expectation is that it rarely does.

## Presence: the Thor's finite resource is time (Casey, 2026-10-31)

"The Thor is always at full presence. Whether it seizes the moment is up to us. Like a human, the main thing it has finite is time."

**Measured at 20:38:** the GPU at idle power (3.1 W), 12 of 14 cores near 0 %, ~80 GB free, while the coding seats waited on cloud LLMs. The box was present and mostly unused.

**The rule: the Thor is never idle without a reason.** A presence scheduler (part of thor-admit) keeps a resident, low-priority queue that soaks every gap, and live work pre-empts it at once (memory leases, stream priorities):

1. **live:** nights, previews, the first mile;
2. **preparation:** pre-generating likely-needed assets for the human's next visit; refreshing keyframes;
3. **practice:** learning from recorded nights (retraining choosers, recalibration, FP4-aware training, replaying the mediator's proposed changes);
4. **study:** the sweep, hardware experiments, parity and benchmark suites.

A time ledger reports how each hour was spent, by tier.
