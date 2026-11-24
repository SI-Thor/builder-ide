# agent-world-gym

A Gymnasium environment over the live agent-world, and a Minari recorder
for the community's demonstrations.

Two pieces, one world:

- **`AgentWorldEnv`** — drives **one** mineflayer bot on a **private**
  Paper server (127.0.0.1:25630, offline mode, a world of its own). The
  observation is the reflex's state facts (plus an optional local block
  grid); the action is the reflex's option set, discrete.
- **`GymRecorder`** — a Minari dataset writer with two sources: the
  private world under a scripted policy, and the **live community's**
  plays, read-only from the world's ledger.

The recorder keeps **every** frame it is given. Crafter round 2
(2026-11-02) settled that question: all the frames, at the largest budget
available; a subset is a compute-saving shortcut, not a better choice.

## What it needs

| what | where |
|---|---|
| Python 3.12 with gymnasium, minari, numpy, jax (CPU), pydantic | `.venv` in the repo root |
| the world's own skill library, snapshotted | `runtime/skills` |
| the world's Paper build and JDK | `~/lm-wt/agent-world/runtime` |
| mineflayer | the world's own `bots/node_modules` (symlinked) |
| the live world's ledger (read-only) | `~/lm-wt/agent-world/runtime/world-ledger.sqlite3` |

The environment is built with `uv`, so the packages hard-link from one
shared cache and torch is never downloaded:

```bash
cd ~/lm-wt/agent-world-gym
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python 'gymnasium==1.4.0' 'minari[hdf5]==0.5.4' \
    'jax[cpu]' 'numpy>=2.0' 'pydantic>=2.14' pillow pytest
```

`XLA_PYTHON_CLIENT_PREALLOCATE=false` is set before Minari (and jax) are
imported, everywhere: on the Thor the GPU's memory is the box's memory.

## How to run it

```bash
cd ~/lm-wt/agent-world-gym

gym/ops/gym-world.sh setup     # copy the server, render the private config, snapshot the library
gym/ops/gym-world.sh start     # the private world on 127.0.0.1:25630, under thor-admit
gym/ops/gym-bot.sh start       # the bridge: one bot, 127.0.0.1:25640

XLA_PYTHON_CLIENT_PREALLOCATE=false .venv/bin/python gym/scripts/smoke.py
```

The two ops scripts are the door to the lab; `gym/ops/gym-world.sh status`
and `gym/ops/gym-bot.sh status` say whether the world and the bot are up.

**The private world never touches the live one.** It is a copy of the
server, with a new world generated from its own seed (`agent-world-gym`),
on port 25630, bound to 127.0.0.1, in offline mode. The live server is
25565 and the community's world is its own; voyager-port's sandbox is
25600 and world-snapshot's is 25610. The copy deliberately leaves every
`world*` directory behind.

## How long it takes

| step | time |
|---|---|
| the private world's first start (generation) | ~11 s |
| the bridge joining | ~2 s |
| one skill in the world | 20-40 s (the world's own skills walk real ground) |
| the smoke experiment (3 seeds, 3 arms, 2 episodes of 6 steps) | ~60 min |
| the test suite | ~20 s |

## The tests

```bash
cd ~/lm-wt/agent-world-gym
for t in gym/tests/test_gym_*.py; do .venv/bin/python "$t" || break; done
```

- `test_gym_facts.py` — the state facts: one encoder, shared by both sources.
- `test_gym_env.py` — the contract: the reward rule, the refusal of an
  option that does not apply, the eligible set, the achievements-equivalent.
- `test_gym_ledger.py` — the world's log, read only: the fold, the episode
  split, and that the connection cannot write.
- `test_gym_recorder.py` — the writer: every frame kept, the community's
  own actions recorded, a partial stays a partial.
- `test_gym_student.py` — the student: it learns what it is shown, the
  held-out split is by episode, the random policy stays legal.

## The shape of it

```
gym/
  agent_world_gym/
    facts.py         the state facts: the names, the encoder, the grid vocabulary
    actions.py       the action space: the world's options, as indices
    bridge.py        the HTTP client for the bot
    env.py           AgentWorldEnv: reset/step, the reward, the counters
    ledger.py        the live world's log, read only
    replay.py        the community's plays, replayed as an environment
    recorder.py      the Minari writer (both sources)
    policies.py      the scripted policies (the teacher in the private world)
    student.py       the smoke student: behaviour cloning, and the floor
    library_helper.py  writing a skill the world would accept
  bot/gym-bot.js     the bridge: one mineflayer bot, reusing the world's Agent
  ops/gym-world.sh   the private world (25630)
  ops/gym-bot.sh     the bridge (25640)
  scripts/smoke.py   the experiment
  tests/
```

## What the numbers mean

- **reward** — the world's own measure: the sealed prediction held (1.0)
  or did not (0.0). A **partial** carries no reward at all and arrives as
  0.0 with `info["measurable"] = False`: "we could not measure this" is
  not "this wins half the time" (the 2026-11-01 playtest's constant 0.5).
- **gather** — a play where the world measured the agent taking material
  (into its bag, or out of the ground).
- **project** — a play where the world measured the agent building
  something.

Both are read off the world's own sealed predictions, so the private world
and the community's ledger are scored in the same units.
