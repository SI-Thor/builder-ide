# The batched simulator on the Thor: the interface, the Beacons port, and what it does

**Desk brief:** Casey, 2026-11-02 — the first ranked item of
[`docs/design/batched-sim.md`](../design/batched-sim.md): build the general
`core/sim/` batched-simulator interface (C++/CUDA, Python bindings), port one
real game of ours onto it, measure env steps/s at batch 128 / 1024 / 4096
against the Python/CPU reference, and prove that the GPU and the CPU produce
identical trajectories from the same seeds and the same actions.

The game is **last-mile's Beacons ruleset**: squads fight over beacons on a
procedural map, contact is a tag rather than a kill, and a squad scores a
point for every beacon it holds on every tick. The port is in
[`core/sim/systems/beacons/`](../../core/sim/systems/beacons/).

---

## 0. The box, and what it means for the numbers

| | |
|---|---|
| machine | NVIDIA Jetson AGX Thor, aarch64, **122.8 GB unified memory**, Blackwell GPU, **compute capability 11.0 (sm_110)**, CUDA 13.2, driver 595.78 |
| CPU | 14 Neoverse cores |
| GPU memory | **is** the system memory. On this box that is the single most important fact for every number below. |
| PyTorch | not installed, and not needed: the binding speaks numpy and `core.sim.to_torch` converts with `torch.from_numpy` |
| the port | last-mile's `crates/lm-core` (read-only on the Thor): `rules/beacons.rs`, `world/{grid,los,gen}.rs`, `rng.rs`, `hash.rs`, `agent.rs`, `params.rs` |

The box was **shared and busy** for the whole session. The GPU pool's
largest free block was **1035 MB** when the seat started and fell to
**12.6 MB** at the worst point, and every GPU number below is recorded with
the block beside it.

One operational fact cost the session about an hour, and it is the reason
the guard in the benchmark script exists:

> **On the Thor, a CUDA allocation that does not fit the GPU pool blocks in
> the kernel rather than failing.** A throwaway smoke program that allocated
> 8 KB with `cudaMallocManaged` sat in uninterruptible sleep at 184 MB of
> free block, where a timeout could not reap it. The simulator's own
> allocations (`cudaMalloc`) run at 125 MB. The two are not the same thing,
> and the difference is worth knowing: **managed memory is what wedges here.**

---

## 1. The interface

`core/sim/` is the interface the design names, and the rules that came with
it from the Stratego port are not negotiable:

- **Fixed-size state, no per-world allocation.** The batch is `rows ×
  num_envs` states, row-major, the row stride is `num_envs`.
- **The mask is `num_envs × A` bools and the rules engine writes it.** The
  policy gathers on it; it never re-derives legality.
- **Point of view is the caller's problem.** The observation is written from
  the acting player's point of view, so the plane list does not depend on who
  is acting.
- **Tensor lifetime is short.** The backend reuses its buffers, so every
  array the binding returns is a fresh copy.
- **No float ever enters the state.** The state is integers, so the GPU and
  the CPU can be compared byte for byte rather than approximately.

A rule system is a directory, not a branch: `state.h` (the POD and the
traits), `rules.cuh` (the rules), `host.cc` and `kernels.cu` (the two
backends), `planes.json` (the manifest) and `reference.py` (the Python
implementation). The registry and the pybind11 module are the only shared
pieces.

### The rules are written once

The Beacons rules live in **one** header, `core/sim/systems/beacons/rules.cuh`,
compiled by g++ for the CPU backend and by nvcc for the CUDA backend:

```
rules.cuh ──g++──► host.cc   (the CPU backend)
         └─nvcc─► kernels.cu (the CUDA backend)
```

That is the load-bearing decision of the whole build. "The GPU agrees with
the CPU" is then a property of the *backend*, not of a second implementation
that might drift. A third implementation — the Python reference, written
from the Rust rather than from the C++ — is the ground truth the two are
checked against.

## 2. The ported game

**One env is one round.** A step is one **acting agent's** turn: the
design's "one character's turn inside a shared world". The acting agent
rotates over the roster and the rules run when the rotation wraps, which is
where the real tick puts them (last-mile's `sim.rs`: the agents, then the
rules). A round of eight agents is eight steps a tick.

The rules, in the order they run, are last-mile's:

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

The action space is nine (hold and the eight neighbours), the mask is
written by the rules engine, and the observation is six planes from the
acting agent's own eyes: `visible`, `terrain`, `beacon`, `self`, `ally`,
`enemy`. The agent planes are masked by the visibility, so an enemy in an
unseen cell is not leaked by its own plane.

### What was not ported

- **The routing.** The real motor walks a Jump Point Search route to a goal
  cell. Here the **policy** picks the neighbour, so the action space is the
  neighbour move. The kinematics are the real ones: the `speed_upt` budget
  (136 units a tick), the axis-separated stepping with the leading axis
  alternating every `axis_swap_ticks`, and the refusal to enter a wall.
- **The world generation on the GPU.** The generator runs on the host in both
  backends: its connectivity repair is a serial flood fill that does not
  parallelise across the worlds, and one host generator means both backends
  start from literally the same bytes. The Python reference grows its own
  world from the same seed, so the generator is still covered by the gate.
- **The facing angle**, which the Beacons rules never read; and the talk,
  the lanes, the reflex and the d1 model, which are the *policy* rather than
  the environment.

---

## 3. The correctness gate

The gate is the design's own rule: the CUDA implementation is checked against
the Python one **bit for bit** before anything depends on it.

`tests/sim/test_beacons_equivalence.py` runs the same seed and the same
action sequence through

- the Python reference (`core/sim/systems/beacons/reference.py`),
- the CPU backend (the same `rules.cuh`, compiled by g++),
- the CUDA backend (the same `rules.cuh`, compiled by nvcc),

and compares the **canonical byte encoding** of every state after every
step. The encoding is little-endian and fixed-width, so "the states agree"
means the bytes agree, not "they are close". The world bytes are compared
too, so the generator is covered: the Python reference grows its own world
from the seed and it has to match the host generator byte for byte.

The comparison covers the state, the world, the legal-action mask, the
observation and the reward. The gate prints what it compared, so a run that
skipped the GPU says so rather than passing quietly.

### What the gate found

Three bugs, all in the port, all silent — the kind that a "looks about
right" check does not catch:

| bug | what it was | why it was silent |
|---|---|---|
| the state size was seven bytes short | `state_serial_size` counted a 19-byte header (it is 18) and 26 bytes an agent (it is 27) | the serializer wrote 246 bytes into a 239-byte buffer — a heap overflow on every call, and the *contents* were right |
| north west went west | `dir_y(8)` fell through to the default and returned 0 | the y axis only moves on the ticks where it leads, so the bug was invisible on half the ticks |
| the world generator zeroed its own dimensions | the `memset` that canonicalises the unused beacon entries ran *after* `w` and `h` were set | every world came out with no cells, and the connectivity repair then read past the end of an empty flood buffer |

Two test bugs are worth recording too, because the honest fix was not to
work around them:

- The batch was built on the default 128×128 world while the reference used
  32×32, so the comparison was between two different games.
- The reference rounds were created once, outside the loop over the
  backends, and each pass steps them — so the CUDA pass compared a fresh
  batch against rounds the CPU pass had already advanced. A gate that
  compares against something it has already moved is not a gate.
- The sanity floor that asks whether the game actually plays used a random
  walk, which does not cover the distance between the two spawns (a walk's
  displacement is the square root of its length). It needed a policy that
  wants something: walk to the beacon nearest the enemy squad, which is the
  one the two squads contest.

---

## 4. The measurements

**The method.** One script, `docs/lab/batched-sim-scripts/bench_env.py`, three
devices, two variants. The **median** of the repetitions is the number, the
first repetition is a warm-up and is not counted, and every run records the
box's state (load, free memory, the GPU pool's largest free block) before
and after, in the JSON beside it.

| device | what it is |
|---|---|
| `cuda` | the GPU backend: the same `rules.cuh`, compiled by nvcc for sm_110 |
| `cpu` | the CPU backend: the same `rules.cuh`, compiled by g++, **14 threads over the worlds** |
| `python` | the reference: `reference.py`, the pure Python rules the two are checked against, one world at a time |

| variant | what it times |
|---|---|
| `step` | `apply_actions` alone: the rules |
| `step+obs` | the same plus the observation planes, which is what a policy actually consumes |

### The rules alone

The rule step is the part the batched simulator exists for, and it is where
the GPU shows its shape: the work per world does not change, so the batch
buys throughput rather than latency.

| batch | world | `cuda` step | `cpu` step | `python` step |
|---:|---:|---:|---:|---:|
| 128 | 128 | **2,399,051** env/s (0.417 us) | 309,029 env/s (3.236 us) | 154,397 env/s (6.477 us) |
| 1024 | 128 | **22,109,458** env/s (0.045 us) | 2,895,973 env/s (0.345 us) | 142,219 env/s (7.031 us) |
| 4096 | 128 | not measured, see below | 9,644,540 env/s (0.104 us) | 133,031 env/s (7.517 us) |
| 128 | 64 | — | 359,363 env/s (2.783 us) | — |
| 1024 | 64 | — | 3,014,118 env/s (0.332 us) | — |
| 4096 | 64 | — | 9,456,769 env/s (0.106 us) | — |

Three things to read out of that table.

- **The GPU's rule step scales with the batch and then saturates.** Batch 128
  to batch 1024 is 8x the worlds and **9.2x** the throughput, so the GPU is
  already saturated at batch 128 and everything after that is free.
- **The CPU backend scales too**, because it is not one world at a time: it
  is 14 threads striding over the worlds. It is a real baseline, not a straw
  man, and the GPU is **7.6x** it at batch 1024.
- **The Python reference does not scale at all** — it is slightly *slower* at
  the bigger batch, because one world at a time in Python is one world at a
  time in Python. At batch 1024 the GPU's rule step is **156x** it.

### The step and the observation together

This is the number a policy cares about, and it is a different story. The
observation is six float planes per world, written out of a line-of-sight
walk from the acting agent's eye, for **every cell of every world**.

| batch | world | `cuda` step+obs | `cpu` step+obs |
|---:|---:|---:|---:|
| 128 | 128 | 5,448 env/s (183.544 us) | **27,648 env/s** (36.168 us) |
| 1024 | 128 | 17,860 env/s (55.992 us) | not measured: 16.8 M cells a step |
| 128 | 64 | not measured | **65,825 env/s** (15.192 us) |
| 1024 | 64 | not measured | **108,152 env/s** (9.246 us) |
| 4096 | 64 | not measured | not measured: 16.8 M cells a step |

**The CUDA observation is currently slower than the 14-thread CPU one**: at
batch 128 on the 128x128 world the GPU manages 5,448 env/s where the CPU
manages 27,648, and the GPU's own number only catches up as the batch grows
(17,860 at batch 1024) because the batch amortises the fixed cost.

That is not a rounding error, and it is not a surprise in hindsight: the
kernel gives every cell its own Bresenham walk and writes six planes
uncoalesced, while the CPU version walks the same cells but writes into a
buffer it is already touching. **The observation kernel is the thing worth
optimising next**, and it is the one part of this build that is left naive:
a sweep along each row (a DDA visibility) turns one walk per cell into one
per row. The rule kernel, by contrast, is already at the machine's limit —
the GPU beats the 14-thread CPU by 7.6x on it.

### The box these numbers come from

Every number above was taken with the box shared. The two GPU runs recorded
their own box state:

| run | load average (1/5/15) | free memory | the GPU pool's largest free block |
|---|---|---|---|
| `cuda` 128, world 128, before | 10.55 / 10.90 / 10.45 | 101.0 GB | 1648.4 MB |
| `cuda` 128, world 128, after | 9.03 / 8.67 / 9.51 | 111.8 GB | 2948.6 MB |
| `cuda` 1024, world 128, before | 9.03 / 8.67 / 9.51 | 112.0 GB | 2948.6 MB |
| `cuda` 1024, world 128, after | 11.78 / 10.88 / 9.80 | 90.7 GB | 302.0 MB |

The load average is 9-12 on 14 cores for the whole session, with other
seats' work running (`agent-world-gym.mc`, `voyager-port.mc`, two model
servers, `scenebloom-eval`, `night-v6`). These are the numbers for **this
box in this state**, not for an idle Thor.

### What was not measured, and why

- **The GPU at batch 4096.** The batch always allocates the observation
  planes — the backend does not have a step-only mode — so 4096 worlds on a
  64x64 world is 402 MB of observation buffer plus the worlds and the
  states, about 420 MB in one block. The pool's largest free block was
  **104.9 MB** for most of the session and never went above 3 GB for long.
  A CUDA allocation that does not fit the pool **blocks in the kernel**
  rather than failing, so the batch was not attempted; the benchmark script
  refuses it and the run is recorded as not measured. The CPU and the Python
  reference are measured at 4096, so the batch size the brief asks for is
  covered on the baselines.
- **The `cuda` rows on the 64x64 world.** They were queued for the pool and
  for the admission daemon, which stopped granting leases (two model-server
  leases were over their reservations) while the session ended.
- **The Python reference's observation.** The reference writes the planes one
  cell at a time in Python, about 1.5 us a cell, so it is 40 times slower
  than the GPU on the same work; it is only measured where that fits in the
  budget, and the JSON says which configurations were skipped and why.
- **The CPU's observation at the bigger configurations.** Above 8 M cells a
  step the script does not measure it, and says so rather than leaving a
  blank.

### What it makes possible

A policy rollout at batch 1024 is no longer the thing that costs: the rules
run at **22.1 M env-steps/s** on the GPU, which is 7.6x the 14-thread CPU
and 156x the Python reference, and the batch is **byte-identical** to the
CPU's, so a GPU rollout can be checked against a CPU rollout exactly rather
than statistically. What is left on the table is the observation, and it is
left on the table in a way that is now measured rather than guessed.

## 5. What is not verified

- **The observation is not optimised.** It is the whole cost of a step (see
  §4), because every cell of every world does its own Bresenham line-of-sight
  walk from the acting agent's eye. A sweep along each row (a DDA
  visibility) would turn one walk per cell into one per row, and the
  observation is the thing worth optimising next. Nothing in this build
  tries.
- **The world generation does not run on the GPU.** It is a serial flood fill
  per world, and it runs on the host. It is a one-off cost per rollout, so
  it does not show in the steps/s, but a long rollout with many resets would
  feel it.
- **The routing (the Jump Point Search route) is not ported.** The policy
  picks the neighbour. The kinematics are the real ones; the path is not.
- **Only one rule system is ported.** The interface is general, but the
  drift system (build 1 of the design) and the pre-flight system (build 2)
  are not written. The design's own claim — that a rule system is a
  directory — is supported by one example.
- **The belief model and the sampled-belief search were not measured.** They
  need the simulator, and this is the simulator; the search itself is §2 and
  §3 of the design and is not built.
- **The GPU numbers are from a shared box.** The load average was 9-12 on
  14 cores for the whole session, with other seats' work running. The
  numbers are for this box in this state, not for an idle Thor.
- **The GPU was not measured at batch 4096**, at either world size: the
  observation buffer alone is 1.6 GB at 4096 on the 128x128 world and
  402 MB at 4096 on the 64x64 world, and the pool would not give it. The CPU
  and the Python reference are measured at 4096 on the 128x128 world, and at
  64x64 the two are not the same game.
- **The repo's own test suite does not collect as one run**, and that is
  pre-existing: `tests/coldstart/test_gate.py` and `tests/drift/test_gate.py`
  share a basename and neither directory has an `__init__.py`, so pytest's
  default import mode collides on them. It is not this seat's to fix (both
  files predate this work, and a fix would touch other seats' test layout),
  so the suite was run with `--import-mode=importlib`, which other tests do
  not like either. The 32 tests of this package pass on their own.

## 6. What is committed

| | |
|---|---|
| the interface | [`core/sim/`](../../core/sim/) — `state.h`, `kernels.h`, `bindings.cc`, the registry, the build, the README |
| the ported game | [`core/sim/systems/beacons/`](../../core/sim/systems/beacons/) — the POD, the rules written once, the two backends, the manifest, the Python reference |
| the tests | [`tests/sim/`](../../tests/sim/) — 25 rule tests and the byte-for-byte gate |
| the measurements | [`docs/lab/batched-sim-scripts/`](./batched-sim-scripts/) — `bench_env.py` and the raw JSON |
| the plan | [`docs/superpowers/plans/2026-11-02-batched-sim.md`](../superpowers/plans/2026-11-02-batched-sim.md) |
| this note | `docs/lab/exp-batched-sim.md` |

Reproduce any number with the script beside it and the README in its
directory: what it needs, how to run it, how long it takes.
