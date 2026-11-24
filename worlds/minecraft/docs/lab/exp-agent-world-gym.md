# agent-world-gym: the world's game as an environment, and the community's plays as a dataset

**Status:** the pipeline runs end to end. This is the first pass — a smoke
student against a random policy, three seeds, in the world's own units.

**The answer, in one line:** a student cloned from the community's own
ledger gathered **6.00 materials per 6-step episode against a random
policy's 4.00**, and hit the ceiling on every seed (6, 6, 6 against 3,
5, 4). The community's morning, read as a dataset, is worth more than
guessing.

## What was asked

From the desk brief (`BRIEF.md`, 2026-11-02):

1. **env** — `agent_world_gym.AgentWorldEnv(reset/step)` driving **one**
   mineflayer bot on a **private** Paper server copied from `runtime/`
   (new world, port 25630, 127.0.0.1, offline; never the live 25565 server
   or its world; never voyager-port's 25600 or world-snapshot's 25610).
   Observation = the reflex's state facts (+ optional local block grid);
   action = the reflex's skill/option set (discrete) — the same contract
   the d1 reflex uses.
2. **recorder** — a Minari dataset writer recording episodes from (a) the
   env under a scripted policy and (b) the **live community bots,
   read-only**, from the world ledger (state, chosen option, outcome) — no
   writes to the live world.
3. **a smoke student** — behaviour cloning on the recorded data against a
   random policy, a few seeds; report achievements-equivalent
   (projects/gathers per episode).

The rule carried over from crafter round 2: **record ALL of a teacher's
frames** (not a filtered subset); subsample randomly only if storage
forces it.

## The mechanism, in the order DOC-RULES asks for

### The hardware and software fact

The Thor can host a **second** Minecraft world of its own without
disturbing the community's: 122 GB of memory, and a Paper build that
generates a fresh world in **11 seconds** (`Done (11.122s)!`). The world's
own runtime already holds everything a second world needs — the Paper jar,
the JDK, the server libraries — so a private world is a *copy of the
server* with a new seed and a new port, not a new installation.

The community's demonstrations were already recorded, just not in a form a
student could read: the world's ledger holds one row per play, with the
state facts, the option chosen and the outcome. 71,963 plays were in it
when this was written.

### Why the old way could not do this

Before this, the world could be *watched* and *played* by people and by
the crew, but it could not be:

- **played as an environment.** The bots ask the reflex what to do and
  the reflex answers; there was no `reset()`/`step()` to drive, no
  observation space, no action space, and no way to take a step *by
  hand* and see what it cost;
- **read as a dataset.** The ledger is a log of events, not a dataset:
  no episodes, no observations, no actions, no reward, and the frames of
  one bot's play are interleaved with three other bots';
- **learned from.** Nothing read the ledger to build a policy, so the
  community's 70,000-odd plays of hard-won behaviour were only ever
  evidence for a human reading the log.

`docs/design/autoplay-stack.md` (2026-11-01, in the builder-ide family)
queued exactly this as build-out item 1: *"`agent-world-gym`: a Gymnasium
environment over the live agent-world, plus a Minari recorder for every
session (bots, teacher, opt-in human state)"*, with Minari as the format
for **every watched demonstration** and Stable-Baselines3 as the honest
baseline for "does watching a teacher beat learning alone?".

### What changed

Five pieces, all on branch `gym` of `agent-world`:

1. **the private world** (`gym/ops/gym-world.sh`) — the server copied
   from the community's `runtime/paper` with **every `world*` directory
   left behind**, so the private world is generated from its own seed
   (`agent-world-gym`) and the community's terrain is never touched. It
   binds 127.0.0.1:25630 only, runs offline, and runs under the admission
   daemon (`thor-admit run --tier live --peak 3G --label
   agent-world-gym.mc`), so the memory it takes is reserved honestly.
2. **the bridge** (`gym/bot/gym-bot.js`) — one mineflayer bot behind an
   HTTP door on 127.0.0.1:25640. It reuses the world's own `Agent`, its
   api, its sandbox and its measure, so the gym plays the world's game
   rather than a copy of it. The one thing it does **not** reuse is the
   reflex: the gym's reflex is a null one that asks nothing and records
   nothing, so the gym writes nothing to the live world.
3. **the environment** (`gym/agent_world_gym/env.py`) — `reset`/`step`
   over the bridge. The observation is the reflex's own context object,
   encoded once by `facts.py`; the action is the library's live option
   set, discrete, with the ineligible options masked into
   `info["eligible_actions"]`.
4. **the recorder** (`gym/agent_world_gym/recorder.py`) — one Minari
   writer, two sources: the private world under a scripted policy, and
   the community's plays read out of the ledger through a **read-only**
   SQLite connection (`mode=ro` — the file cannot be written even by
   accident). Every frame is kept.
5. **the smoke student** (`gym/agent_world_gym/student.py`) — a softmax
   linear policy over the state facts, trained by maximum likelihood in
   numpy, measured against a random policy in the world's own units.

### The numbers

The run: 2026-11-02 16:36:09Z → 18:28:35Z (1 h 52 m), role **gatherer**,
6-step episodes, 3 seeds × 2 episodes per arm. Report:
`runtime/reports/smoke-20261102-073610.json`. Script:
`gym/scripts/smoke.py` (run it with `gym/ops/run-smoke.sh`).

**The datasets** (every frame kept, nothing filtered):

| dataset | episodes | frames |
|---|---:|---:|
| `gym/gatherer-community-20261102-073610-v0` — the live community, read-only from the ledger | 20 | **72,388** |
| `gym/gatherer-private-20261102-073610-v0` — the private world, scripted | 3 | 18 |

The action space is **41** options: the library's 13 live skills plus every
option the community has ever chosen (retired versions and project steps
included), so a student cloned from the community can be played in the
private world with no translation table.

**The students** (a linear softmax policy over the state facts, maximum
likelihood in numpy; the held-out split is by **episode**, never by frame):

| student | training frames | held-out frames | train agreement | held-out agreement |
|---|---:|---:|---:|---:|
| `bc-community` | 48,163 | 24,225 | 0.733 | **0.951** |
| `bc-private` | 12 | 6 | 0.500 | 0.167 |

**The rollouts** — the world's own achievements-equivalent, projects and
gathers per 6-step episode:

| arm | seed 0 | seed 1 | seed 2 | **gathers/episode** | projects/episode | reward/episode | refused/episode |
|---|---:|---:|---:|---:|---:|---:|---:|
| **`bc-community`** (cloned from the community) | 6 | 6 | 6 | **6.00** | 0.00 | 6.00 | 0.00 |
| `bc-private` (cloned from 18 scripted frames) | 0 | 0 | 6 | 2.00 | 0.00 | 2.00 | 0.00 |
| `random` (uniform over the eligible options) | 3 | 5 | 4 | 4.00 | 0.00 | 4.00 | 0.00 |

**The reading.** The student that watched the community gathered **6.00
per episode against the random policy's 4.00** — a 50 % relative gain,
and it hit the ceiling (6 of 6 steps won) on *every* seed, where the
random policy's three seeds were 3, 5 and 4. The mechanism is visible in
the world's own log: the community's gatherer had spent the morning
evolving its wood skill (g15: "go home, find a tree at any level, chop a
log, leave the bag at the depot" — it searches 96 blocks at any level and
walks on when it misses), and the student cloned from 72,388 frames plays
*that* skill every time. The random policy picks the same skill about a
third of the time and the skill that mines surface stone the rest, and
stone is the one that misses.

Two honest limits on that reading:

- **no interval is quoted.** Six rollouts of six steps is not a sample
  that carries an interval; the per-seed rows are given instead.
- **the gatherer never builds**, so the projects column is empty for
  every arm by construction. The other half of the achievements-equivalent
  needs the builder's role to be rolled out.

**The community's own rate**, in the same units, for scale: **140.5
gathers and 0.6 projects per episode**, from 146.9 wins in 3,598 plays
per episode. A community episode is a bot's whole run and a gym episode
is six steps, so the two per-episode numbers are **not** comparable —
what is comparable is the per-play rate: the community gathers 3.9 % of
its plays, the cloned student gathers 100 % of its steps, the random
policy 66.7 %.

**Box state beside the numbers.** The Thor, aarch64, 122 GB, 15 h uptime.
MemAvailable **69 GB at the start of the run, 45 GB at the end** (the
run's own footprint is small; another seat's 40 GB lease came and went
alongside it); load 11.6 → 14.3 over the run. The private world held
lease `agent-world-gym.mc` (peak 3.0 G, 1.4 G resident). jax is CPU-only
(`jax[cpu]`: "a CUDA-enabled jaxlib is not installed, falling back to
cpu") and `XLA_PYTHON_CLIENT_PREALLOCATE=false` is set in every entry
point. The community's world (25565), its bots, the reflex and d1 were
running the whole time and were not touched: **0 plays by the gym's bot
in the community's ledger**.

**The cost of a step.** A skill in the world costs **36–85 seconds** of
real walking, so a 6-step episode is 4–8 minutes and the whole matrix
(3 arms × 3 seeds × 2 episodes + 18 recorded steps) is 1 h 52 m. This is
the real cost of rolling out in a Minecraft world, and it is why the
number of seeds is three and not thirty.

## What it makes possible

- **The world's game is now an environment.** Any RL library that speaks
  Gymnasium can be pointed at it: the observation is the reflex's own
  contract, so a student trained on the community's demonstrations and a
  student trained on scratch are learning the same game.
- **The community's days are a dataset.** Every play the four builders
  made is now in a Minari dataset with its state, its option and its
  outcome — 72,388 frames from one morning, with nothing filtered out.
  That is the first time the community's behaviour is available to a
  learner rather than to a reader.
- **Watching and guessing can be compared in the world's own units.**
  The smoke student is deliberately a floor (a linear softmax policy in
  numpy), so a number that moves is evidence about the data and the
  contract, not about the model class. Stable-Baselines3 is the next
  step on the same datasets.
- **A private lab world, cheaply.** A second world costs 11 seconds of
  generation and 1.4 GB resident, under the same admission rule as any
  other seat. That makes "try it in the real world" an ordinary move
  rather than an expedition.

## What was not verified

- **One student, one architecture, one role.** The smoke student is a
  linear softmax policy over the state facts, trained for 600 full-batch
  gradient steps. No PPO, no recurrent state, no DAgger, no
  hyper-parameter search.
- **Three seeds, two episodes each.** Six rollouts per arm. The
  intervals are not quoted because six rollouts of a 36–85-second skill
  are not enough to quote an interval from; the means are given with the
  per-seed rows beside them.
- **One role.** The gatherer. The builder and the farmer are the same
  machinery with a different option set, but they were not rolled out.
- **The local block grid does not work, and is off by default.** The grid
  is implemented, the vocabulary and the encoder are unit-tested, and the
  bridge sends the right 75 cells — but **every cell reads "unknown"** in
  the live private world, so the grid carries no information. The
  community's ledger holds no grids either, so a grid-capable student
  could not be cloned from the community at all. Two reasons to leave it
  off: it does not work, and there is nothing to teach it from. The cause
  was not pinned down: `bot.blockAt` returns null for every position in
  this mineflayer build, and the world it reads (`prismarine-world`'s
  `getBlock`) is `async`, so the sync path mineflayer's `blockAt` takes
  may not be the one the installed build uses. That is a lead, not a
  finding.
- **The community's episodes are not comparable to the gym's episodes.**
  A community episode is a bot's whole run (3,598 plays on average); a
  gym episode is 6 steps. The per-episode numbers are therefore not
  comparable between the two, and the doc says so where it matters.
- **The episode split is a reading, not a fact.** "One bot's run with no
  silence longer than 600 s in it" is a rule this work chose; the ledger
  does not state where an episode begins.

## Corrections in writing (DOC-RULES 5)

1. **The episode split was wrong the first time.** The first fold
   treated every change of bot in the log as a new episode. The four
   builders interleave, so that reading produced **43,466 episodes of one
   or two plays** from 71,577 plays — a demonstration cut to confetti.
   The rule is now: each bot has its own stream, and the stream is split
   on the silence (10 minutes). The same ledger now folds into **20
   episodes**, one per bot per run of continuous play. The regression
   test is `gym/tests/test_gym_ledger.py`
   (`test_interleaved_bots_are_not_fragmented`).
2. **The achievements-equivalent was too narrow the first time.** A
   gather was first counted only when the sealed prediction was
   `inventory_delta`. But the world's own gatherers predict
   `block_broken` — they *chop* and *mine* — so the counter read zero
   for every real gather. A gather is now a play where the world
   measured the agent taking material (into its bag **or** out of the
   ground); a project is a play where the world measured it building
   something.
3. **The episode boundary hung, and it was my bug, not the world's.**
   The first bridge emptied the agent's bag with
   `bot.toss(type, null, count, callback)`. mineflayer's `toss` takes
   three arguments and returns a promise; it never calls a callback, so
   the promise the bridge was waiting on could never resolve, and every
   reset after the first mined log hung until the client timed out. The
   bag is now emptied with the promise API, and every step of the episode
   boundary (toss, walk home, respawn) is capped, so a wedged agent
   cannot hold the run open.
4. **The block grid read "unknown" everywhere — and still does.**
   `bot.blockAt` takes a position, not three numbers; the bridge was
   passing bare numbers, so every cell of the grid came back empty. It
   reads the way the world's own api reads now (`new Vec3(x, y, z)`),
   and the bridge loads Vec3 from the world's shared `node_modules`
   because the gym's checkout has none of its own (Node only looks in the
   directories above the one that asks). **That was not the whole
   cause**: with the fix in, the grid still reads "unknown" in all 75
   cells of the live world. The grid stays off, the claim above stands,
   and the cause is an open lead (`prismarine-world`'s `getBlock` is
   `async`; mineflayer's `blockAt` takes the sync path).

## How to reproduce

```bash
cd ~/lm-wt/agent-world-gym

# the private world (127.0.0.1:25630, its own world, under thor-admit)
gym/ops/gym-world.sh setup
gym/ops/gym-world.sh start

# the bridge: one bot, 127.0.0.1:25640
gym/ops/gym-bot.sh start

# the experiment (about an hour; the world's skills walk real ground)
gym/ops/run-smoke.sh --env-episodes 3 --eval-episodes 2 --seeds 3 --max-steps 6 --tag smoke

# the tests
for t in gym/tests/test_gym_*.py; do .venv/bin/python "$t" || break; done
```

The report of the run is written to `runtime/reports/smoke-<stamp>.json`,
the datasets to `runtime/datasets/gym/`, and the world's own log of the
gym's plays to `runtime/logs/gym-bot.jsonl`.

