# Does the gym fit `core/sim`?

**Verdict: no.** The gym is not a `core/sim` rule system, and an adapter
between them would have to be a second implementation of Minecraft rather
than a translation. This note says why, against the four rules
`core/sim` states as non-negotiable, and then says what the gym *is* a
good fit for — because it is a good fit for something, and saying that
is more useful than saying "no".

The question was: can `gym/agent_world_gym` be made to fit `core/sim`'s
interface? The brief allows either answer; this is the "no" answer, with
the reasons.

---

## 1. What `core/sim` is

`core/sim` is a **batched simulator**: one rule system, many independent
worlds, stepped together on the GPU. Its README
(`core/sim/README.md`) states four rules it does not negotiate:

| rule | what it means |
|---|---|
| fixed-size state, no per-world allocation | `sizeof(State)` is known at compile time; the batch is `rows × num_envs` states |
| the mask is `num_envs × A` bools, written by the rules engine | the policy gathers on it; it never re-derives legality |
| point of view is the caller's problem | the observation is written from the acting player's point of view |
| no float ever enters the state | the state is integers, so the GPU and the CPU can be compared byte for byte |

And the shape of a rule system (`core/sim/systems/<name>/`) is a
**directory**: `state.h`, `rules.cuh`, `kernels.cu`, `host.cc`,
`backend.h`, `planes.json` and a Python `reference.py`. The registry that
knows the systems is C++ (`core/sim/systems/register.cc`), and the
Python side only calls `_pysim.make_batch(...)` — a compiled pybind11
module. The CPU and CUDA backends are two implementations of the **same
rules header**, which is what makes "the GPU agrees with the CPU" a
property of the backend instead of a coincidence.

## 2. What the gym is

`gym/agent_world_gym` is a **Gymnasium environment over a live
Minecraft server**. One mineflayer bot, one private Paper server
(127.0.0.1:25630, offline mode, its own world), driven over HTTP by a
bridge (`gym/agent_world_gym/bridge.py`). Its observation is the reflex's
state facts, encoded as a flat vector (`facts.py`), plus an optional
local block grid. Its action is the reflex's option set: `Discrete(n)`
over the skill ids the library holds.

## 3. The four rules, against the gym

### 3.1 Fixed-size POD state — **cannot hold**

A Minecraft world is not a fixed-size record. The state that decides a
step is the chunk palette of every chunk within the bot's view, the
entity list, the block-entity data, the world's tick counter, the
player's inventory, the scoreboard and whatever the server holds. It
grows with the world and it is not a POD.

There is no honest way to make this fixed-size without writing a
different game. The gym's own observation encoding already shows the
tension: the block grid is **off by default**, and the reason is written
in `gym/agent_world_gym/env.py` — the community's ledger holds no grids,
so a grid-capable student could not be cloned from it. A `core/sim`
system is *all* grid, by construction.

### 3.2 The mask is written by the rules engine — **cannot hold**

`core/sim` requires the legality mask to be produced by the compiled
rules, on the device, as part of the step. The gym's eligibility rule is
the world's own: `SkillLibrary.eligible(context)` filters the library by
the skills' preconditions, and a context with no eligible skill is a
**refusal with a named reason** — never a fallback to another skill
(`worlds/minecraft/reflex/agent_world_reflex/library.py:164`).

That rule is Python, over a library that changes while the world runs
(the mediator writes new skills). It cannot be compiled into a CUDA
kernel that decides legality, because the set of legal actions is a
function of a mutable on-disk library, not of the batch's state.

### 3.3 Point of view — **fits, and is the one thing that does**

The gym already writes the observation from the acting agent's point of
view: the facts are the bot's own health, food, position, inventory and
the phase of day. This is the same contract `core/sim` states. It is the
one rule the gym meets as it stands.

### 3.4 No float in the state — **cannot hold, and does not need to**

The gym's facts are `float32` (`spaces.Box(low=-1.0, high=1.0,
dtype=np.float32)`), and its student is trained by maximum likelihood
over those vectors (`gym/agent_world_gym/student.py`). That is the
Gymnasium contract, and it is fine for it. It is simply not `core/sim`'s
contract, and `core/sim`'s rule exists for a reason that does not apply
here: its states must be compared **byte for byte** between the CPU
reference and the CUDA backend.

## 4. The decisive objection

The four rules above say an adapter would be hard. One thing says it is
not worth doing:

> **A `core/sim` rule system is a directory of C++/CUDA sources, and the
> Python side cannot add one.**

`core/sim/systems/register.cc` is the registry; `_pysim.make_batch` only
looks up a system it already knows. Writing a "minecraft" system would
mean re-implementing Minecraft's rules in `rules.cuh` — world
generation, block physics, entity AI, the redstone engine — in a
project whose whole point is that a system is a *small* rule set compiled
twice (CPU and CUDA) and compared byte for byte.

And the gym's world is **not stepped by the batch at all**. The batch
would advance a state that is a copy of a copy of a summary of a world
that is actually living in the Paper server. The batch's stepping and
the world's stepping would be two different histories, and the gym's
reward (the sealed prediction checked against the real world) would
belong to the second one. The result would not be faster than the gym;
it would be a second, diverging world.

## 5. What the gym *is* a good fit for

The gym is a **student**: a place where a policy is trained against the
world's own demonstrations and scored in the world's own units
(projects and gathers per episode, `gym/agent_world_gym/student.py`).
That is a different shape of problem from `core/sim`'s, and it has its
own right place in builder-ide:

- the **demonstrations** come from the world's log of record — the same
  log the seam now writes into builder-ide's core store, so the
  student's dataset and builder-ide's log are the same rows;
- the **scoring** is the world's own measure (a sealed prediction that
  held, or did not);
- the **policy** is a softmax linear model over the state's facts — the
  honest floor, and the reason the comparison is about the data rather
  than the model class.

So the gym stays where it is: a world-type package that reads the log
of record and trains a student against it. It is **adapter-free** — no
`core/sim` adapter, and no fake one.

## 6. What would have to be true for the answer to change

Two things, and both are larger than this fold:

1. **The world had to be a rule set small enough to state in C++** — a
   grid world with a handful of block types and no entities, say. The
   gym's world is neither.
2. **The batch would have to be the world** — the state in the batch
   would have to be the state the server holds, which means owning the
   server's simulation. That is a different product.

There is a third, smaller door worth naming: a **`core/sim` system for
the gym's *decision* problem** — not the world, but the choice among
skills given the facts. The world's chooser already answers that with
`core/tiles/chooser.py`'s contextual bandit, which runs in Python on the
Thor and does not need a GPU. A `core/sim` system for it would be a
different problem with the same arithmetic, and it is not what the brief
asked about.

## 7. The check

The gym's own tests still pass from its new home in builder-ide:

```bash
pytest worlds/minecraft/gym/tests -q
```

They were written against a live Paper server and a fake bridge, so they
run offline. What they cannot check — and what the Thor must check at
cut-over — is that the **live** world's episodes still read the same way
after the log moved into the core store. That checklist is in
`FOLD-REPORT.md` at the root of this worktree.
