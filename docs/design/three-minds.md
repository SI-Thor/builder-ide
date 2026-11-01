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
