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
