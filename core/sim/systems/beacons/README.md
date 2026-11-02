# Beacons: last-mile's beacon game, ported onto the batched simulator

The ported game is the **Beacons** ruleset of last-mile's `lm-core`
(`crates/lm-core/src/rules/beacons.rs`, read-only on the Thor). Squads fight
over beacons on a procedural map: contact is a tag rather than a kill, and a
squad scores a point for every beacon it holds on every tick.

This directory is the reference implementation of the design's first build
([`docs/design/batched-sim.md`](../../../../docs/design/batched-sim.md) §5,
build 1): one real rule system on the general interface, with the rules
**written once** for the host and the device.

## What it owns

| file | what it owns |
|---|---|
| `state.h` | the POD state, the parameters, the traits |
| `rules.cuh` | the rules: hash, RNG, grid, LOS, motor, tick, mask, obs |
| `worldgen.cuh` | the seed-grown world (host **and** device) |
| `host.cc` | the CPU backend, over the same `rules.cuh` |
| `kernels.cu` | the CUDA backend, over the same `rules.cuh` |
| `planes.json` | the plane manifest: the contract with the network |
| `reference.py` | the Python implementation: the ground truth |

## The rules, in the order they run

1. **Respawn.** An agent whose stun has ended goes back to its squad's spawn.
2. **Tagging.** The agents act in the tick's rotating order. An agent that
   is not stunned tags the *first* enemy that is not stunned, is within
   `tag_range_units` and is in line of sight. The target is stunned for
   `stun_ticks` ticks. A tag never comes back in the same tick, so two
   agents that can see each other cannot trade tags.
3. **Holding.** A beacon is held by the squad that has a living agent inside
   `beacon_radius_units` of it while no enemy is inside that radius. A
   beacon two squads stand in is held by nobody. Every held beacon is worth
   one point per tick.
4. **Ending.** The round ends when a squad reaches `win_score` or the tick
   limit runs out. The higher score wins; a tie is a tie.

## The env

**One env is one round.** A step is one **acting agent's** turn — the
design's "one character's turn inside a shared world". The acting agent
rotates over the roster and the rules run when the rotation wraps, which is
where the real tick puts them (last-mile's `sim.rs`: the agents, then the
rules). So a round of 8 agents takes 8 steps per tick.

- **Actions (A = 9)**: hold, and the eight neighbours.
- **Mask**: written by the rules engine. Hold is always legal; a move is
  legal when the neighbour cell is in bounds and walkable; a stunned agent
  may only hold.
- **Reward**: the points the acting agent's squad scored this step.
- **Observation** (C = 6, from the acting agent's own eyes): `visible`,
  `terrain`, `beacon`, `self`, `ally`, `enemy`. The agent planes are masked
  by the visibility, so an enemy in an unseen cell is not leaked by its own
  plane.

## What was not ported, and why

- **The routing.** The real motor walks a Jump Point Search route to a goal
  cell. Here the **policy** picks the neighbour, so the action space is the
  neighbour move. The kinematics are the real ones: the `speed_upt` budget
  (136 units a tick), the axis-separated stepping with the leading axis
  alternating every `axis_swap_ticks`, and the refusal to enter a wall.
- **The world generation on the GPU.** The generator runs on the host in both
  backends: its connectivity repair is a serial flood fill that does not
  parallelise across the worlds, and one host generator means both backends
  start from literally the same bytes. The Python reference grows its own
  world from the same seed, so the generator is still covered by the
  equality gate.
- **The facing angle.** The Beacons rules never read it.
- **The talk, the lanes, the reflex and the d1 model.** Those are the
  *policy*, not the environment: what the simulator rolls out is the rules,
  and the policy supplies the actions.

## The equality gate

`tests/sim/test_beacons_equivalence.py` runs the same seed and the same
action sequence through the Python reference, the CPU backend and the CUDA
backend, and compares the canonical byte encoding of every state after every
step. The state is all integers, so "the states agree" means the bytes
agree.

The reference is written from the Rust, not from the C++, so it is an
independent implementation and not a transcription of the port.

## Its tests

```bash
.venv/bin/python -m pytest tests/sim -q
```

- `tests/sim/test_beacons_rules.py` — the rules themselves, written from
  last-mile's Rust tests (the tag and the respawn, the contested beacon, the
  tie, the line of sight, the generator's symmetry and determinism, the
  motor's axis order and budget).
- `tests/sim/test_beacons_equivalence.py` — the byte-for-byte gate.
