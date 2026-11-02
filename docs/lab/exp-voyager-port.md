# Voyager's loop as a system-agnostic core, measured on Minecraft

Status: round 2 finished (2026-11-02): the two named levers pulled, four Minecraft runs, the crafter run with 3 skills admitted; round 1 stands with its blindness reading superseded (§Round 2).
Written per `~/lm-wt/DOC-RULES.md` (mechanism first, numbers with the
box state beside them, suspected/confirmed labelled, what was *not*
verified named). Every number on this page is read out of the runs'
own payload files by `docs/lab/voyager-port-scripts/summarize_run.py`,
so the page cannot drift from what was measured.

## Mechanism

**What was asked.** The brief: re-engineer
[MineDojo/Voyager](https://github.com/MineDojo/Voyager) (MIT; its notice
is kept in `core/voyager/__init__.py` and the bridge header) as a
*system-agnostic* core in builder-ide — automatic curriculum → skill
written as code by a model → execute → environment feedback and
self-verification → skill library — with models from DeepInfra in three
roles, the skill library on our tiles with one ledger event per skill,
autopilot's harness rules borrowed, and a measurement on Minecraft for
N hours of world: unique items, tech-tree milestones
(wood→stone→iron), skills admitted, token cost per milestone.

**The loop (`core/voyager/`, one step).**

1. **Curriculum** (`curriculum.py`) picks the next goal: a milestone
   whose dependencies are reached, weighted by novelty — the less
   recently a goal was tried, the more eager it is. The tech tree is
   the floor: no iron before a stone pickaxe exists.
2. **Planner** (`XiaomiMiMo/MiMo-V2.6-Pro`) reads the facts and offers
   **2–8 options, each a whole meaningful step, facts in the player's
   terms** — autopilot's field-tested harness rules
   (`docs/research/autopilot.md` §borrow), not Voyager's bare prompt.
3. **Coder** (`Qwen/Qwen3.8-27B`) writes one skill: a program against
   the world's **closed vocabulary** of primitives (`vocab.py` — a name
   outside the vocabulary is a refusal, not a repair; the sandbox is
   the second door), plus a one-line self-verification expression.
4. **Execute**: the adapter runs the program in the world with a wall
   clock; execution errors and the program's own log come back.
5. **Verifier** (`Qwen/Qwen3.8-Max`, a different model from the coder —
   a model grading its own code measures nothing) sees the world
   before and after, the log, the self-check and the world's own
   record, and answers **CONFIRMED / DENIED / INCONCLUSIVE**.
6. **Library** (`skills.py`): a confirmed skill becomes a **tile**
   (content-addressed body on disk, one ledger event —
   `admitted`/`rejected`/`superseded`), so skills are rewindable and
   the drift detector (`core/drift`) sees them like any other edit.
   The next planner prompt lists the library; a failed attempt's code,
   error and critique are fed into the next coder prompt — Voyager's
   iterative prompting, kept whole.

**The closing probe budget** (autopilot's): probes are free until the
first execution of a step, then closed — the loop may take at most
`max_probes` world reads before it executes, so it cannot hide in
research forever (`budget.py`).

**The adapters, in the brief's order.** (1) Minecraft via mineflayer
against a **private Paper sandbox** (`mc-sandbox/`, port 25600,
127.0.0.1, offline mode, its own `spigot.yml`), never the live
agent-world server on 25565 and never its world. (2) Crafter 1.8.3 —
crafter-lab's own env, so the numbers can sit beside
`docs/lab/exp-crafter-lab.md`. (3) vibe-sandbox and (4) Bevy: the
interface and a stub each, as the brief asks — no measurement claims.

**Tokens.** Every model call's prompt and completion tokens are counted
by role (`llm.py`'s CostBook), logged per step, and summed per
milestone in the run payload — the number the brief asks for. A reply
the token cap cut, or a reply with empty content, is asked again with
the budget doubled, and *every* call's tokens are booked.

## Why the port was hard: the repairs, each found by measuring

The bridge and the loop between them needed three rounds of repair
after the code was written; each round is a commit whose message holds
the measurements (`1669e7d`, `fe1f0ff`, `00bb0e5`). In short:

- **The installed mineflayer differs from its README** in a dozen
  places; the bridge was rewritten against the API that is actually
  there (`1669e7d`).
- **Four things kept the world empty** (`fe1f0ff`): the registry hands
  out objects where ids belong (887 recipes invisible to the recipe
  book); `findBlock`'s radius is an octahedron of chunk sections, not
  the sphere the caller names; a 26-name scan read the loaded world 26
  times over (63 s at radius 96 — past spigot's 60 s keep-alive
  timeout, so the bot was *kicked* mid-program; the sandbox's own
  `timeout-time` is now 0 — it is our server; the live one on 25565
  keeps its own setting); and the client holds no chunks at the moment
  of spawn, so the first scan answered `{}` and read as "empty world".
- **Three reply shapes lost turns** (`00bb0e5`): the planner's JSON was
  cut at its 1200-token cap (completion sat at exactly 1200 on 6 of the
  pilot's 23 steps); the verifier twice returned nothing readable on
  steps that had *worked*; and the coder was never told what a
  primitive *returns*, so `if (!mc.has(item))` over the `{has: bool}`
  it actually returns was a check that could never fire — sixteen steps
  went to one goal while a vacuous check reported success. The coder
  prompt now carries `-> {shape}` for every primitive, read off the
  bridge's own `return` statements.

The Crafter adapter had never executed until this seat ran it: its
vocabulary could not be built (the door refused parameterless words),
`mc` was a dict where the coder's `mc.act(...)` needed an object,
`observe()` tripped numpy's ambiguous truth on `player.pos`, and its
self-check reader wanted `result = x` where the shared prompt asks for
a one-line expression. All four are fixed and round-tripped by a probe
that costs no tokens (`probe_crafter_adapter.py`); `3067572` holds it.

## Environment and box state

The Thor, the shared box: the runs shared it with other seats' work
(the pilot: load average 26 falling to 5.5, ~100 GB available of
122.8 GB; the measured runs: load 7–14, ~100 GB available). The
sandbox runs under a thor-admit lease (peak 3 GB — Paper's heap is
capped at 2 GB and the observed peak of an earlier 8 GB lease was
1.5 GB, so the reservation was four times the use); the measured run
itself under `thor-admit exec` (no lease: its own memory is a few
hundred MB — the models are in the cloud and metered, which is the
house rule).

Models, three roles, DeepInfra: planner `XiaomiMiMo/MiMo-V2.6-Pro`,
coder `Qwen/Qwen3.8-27B`, verifier `Qwen/Qwen3.8-Max` (different from
the coder, per the brief). Seed 7 for the curriculum. The Minecraft
worlds: fresh per run (same seed, same spawn, empty hands —
`reset_mc_world.sh` moves the old world aside, kept, not deleted).

## Numbers

### The pilot (0.5 h, 23 steps) — the run that found the defects

| milestone | reached at | tokens to that point |
|---|---|---|
| wood | 154.1 s | 13,189 |
| planks | 323.9 s | 27,410 |
| crafting_table | 533.1 s | 42,243 |
| wooden_pickaxe | 1811.9 s | 124,865 |

5 unique items (oak_log, oak_planks, stick, crafting_table,
wooden_pickaxe); 1 skill admitted of 17 executions; 6 steps lost to the
planner's capped replies, ~21 minutes to one goal behind a vacuous
self-check. Payload: `results/pilot-0.5h/` on the Thor, committed at
`bd8539e` as `minecraft-run.json` / `minecraft-steps.jsonl`.

### The measured run (2 h, Minecraft, after the fixes)

| | |
|---|---|
| wall | 7365.8 s (2.05 h), stopped by the wall clock |
| steps | 51 of 200; 0 skills admitted, 51 rejected |
| tokens | 369,468 — coder 244,153 / planner 53,584 / verifier 71,731 |
| items / milestones | **0 unique items, 0 milestones** |
| box beside it | load 7–14 (other seats' work), ~100 GB available of 122.8 GB, sandbox under its 3 GB lease |

Every step's program failed to find wood, and the reason is measured,
not guessed. At the bot's spawn the **nearest — and only — tree in the
loaded area is 111 blocks away** (`probe_trees.py`, run against the
sandbox at the end: scan 48 = `{}`, scan 96 = `{}`, scan 160 =
`{oak_log: distance 111, at (-3, 66, 103)}`), while the facts the
planner sees reach 96 blocks and the wood-searching primitives reach
64–128 with coder-chosen distances that mostly sat below 111. No
step's `nearby` ever held a log — checked across all 51 step records —
so the planner was *correctly* blind for two hours; the bot's walks
(120 s program wall) moved it around (it ended at (41, 66, 1), still
111 from the tree) without ever closing the gap. Two walks hit the
bridge's own script timeout, one the walk timeout; the other 48
programs scanned, found nothing, and said so honestly.

Read together, the two runs split the loop's difficulty in two: the
pilot — whose bot an earlier session had **placed at the tree** —
measured crafting (four milestones, 124,865 tokens); this run measured
exploration and found the bottleneck: **the loop cannot cross a
distance it cannot see.** The lever is named and cheap to check — the
bridge's own scan reaches 160 blocks and the adapter's facts stop at
96 — but it is deliberately not changed here: the measurement stands
as taken, and the change belongs to the next run.

### Crafter (the second world, 0.25 h smokes)

Crafter 1.8.3 — the same env crafter-lab's teacher–student experiments
use — is the second adapter, so the loop's own numbers can be separated
from the Minecraft world's difficulty. The adapter had never executed
before this seat; four smoke runs (each 0.25 h, 20 steps, payloads kept
under `results/crafter-smoke-N/`) taught the harness one thing each:

| smoke | steps | what failed | what it taught |
|---|---|---|---|
| 1 | 12 | every step a Python `SyntaxError` at line 1 | the coder prompt took a `language` parameter and never rendered it; the coder was told JavaScript by CODER_SYSTEM (`console.log`) regardless |
| 2 | 1 (+hang) | `while True:` held the run 12 min | `run_code`'s `exec` ignored `timeout_s`; an alarm fires `TimeoutError` inside the exec now |
| 3 | 5 | still JS 4/5 steps | naming the language once is not enough — the *execution error* now says "this world runs python" |
| 4 | 5 | still JS 3/5; guessed actions ('eat_food', 'west') | the seventeen action *names* were never in the prompt — "one of 17 values" invites guessing; the hints name them now |
| 5 | 6 | **first executed program, first item**; still JS 4/6 | with the names in the prompt the coder ran `act`-based programs; the JavaScript habit is the model's, the blindness is the world's |

**The honest state of the second world:** the loop runs end-to-end in
Crafter (steps, verdicts, ledger events, token counts all land), but no
skill has been admitted there yet. The named obstacle is observability,
not the loop: the facts the planner and coder see (position, health,
energy, food, inventory, achievements) carry **no spatial view** —
nothing says where a tree is or what is in front of the player, and
collecting wood in Crafter means facing a tree and pressing `do`.
crafter-lab's scripted teacher reads the grid directly
(`exp-crafter-lab.md`: 9.625 achievements per episode); the LLM loop
plays blind. Against the students in that report (PPO 1.125, BC on all
frames 0.875, teaching-moment BC 1.375), the blind loop's honest number
so far is 0 — the comparison says the next lever is a spatial fact in
`observe()`, not a bigger model.

## Verdict on the claim

**What the brief asked to be shown** — that Voyager's loop can be
re-engineered as a system-agnostic core, with skills as rewindable
tiles the drift detector can see, and measured on Minecraft — is
**shown, with the numbers below and the caveats named**. The core
(5,750 lines, 31 tests with no world and no model) runs the same loop
over two worlds and two stubs; every skill is a tile with one ledger
event per disposition (`tile.played`/`tile.retired` rows in the run's
own ledger, format `core.night.ledger`'s — the drift detector's own
input); every model call's tokens are counted by role and per
milestone.

**What the runs say about the loop itself** is more modest than the
paper's numbers, and the difference is mostly named:

- The pilot (bot placed near the tree by an earlier session) reached
  four milestones in 0.5 h — wood at 154 s, planks 324 s,
  crafting_table 533 s, wooden_pickaxe 1812 s — for 124,865 tokens.
- The measured run (same seed, **fresh world, bot at world spawn**)
  shows what the loop does from an honest start: **zero milestones in
  2 hours**, because the only tree sits 111 blocks out against a
  96-block facts scan — the loop cannot cross a distance it cannot
  see. The start position is the largest single factor in "how fast is
  Voyager", and neither run hides it.
- The three reply defects the pilot exposed (the planner's capped
  JSON, the verifier's silent episodes, the coder's unseen return
  shapes) were each pinned by a probe and fixed; the measured run had
  **zero unreadable replies** (the pilot lost 6 of 23 steps to them),
  and its step records carry `finish_reason` so the distinction
  survives.

## Limits of what these runs establish (explicitly NOT verified)

- **One seed, one world, one spawn each.** The pilot and the measured
  run share a seed but not a start; no run has been repeated, so
  nothing here is a mean, and the milestone times are single
  observations.
- **The verifier's two silent episodes are defended against, not
  explained.** `probe_verifier_reply.py` got 8/8 readable replies at
  ~150 tokens; the empty-content theory fits but was not reproduced.
  The next run's `finish_reason` fields are the instrument that will
  settle it.
- **Crafter is a smoke, not a measurement.** No skill admitted, no
  milestone; the loop's mechanics are exercised, its game-playing is
  not. The spatial-observability gap is named as the cause; adding the
  fact is future work.
- **The drift detector was not run over the run's ledger.** The events
  are in its format by construction (`SQLiteLedger`); that the
  detector *reads* them is asserted from the shared format, not
  demonstrated by running it.
- **vibe-sandbox and Bevy are interfaces with stubs** — the brief asks
  for exactly that, and no more is claimed.
- **Token costs are DeepInfra's reported usage**, not a bill;
  `cost_cents` is `None` throughout because no price table was wired.

## Reproducibility

`docs/lab/voyager-port-scripts/README.md` is the runbook: make the
sandbox, start it, empty the hands (or reset the world), measure
(`run_measurement.sh`, detached), read the numbers
(`summarize_run.py <results>/<world>-run.json`). The pilot is
reproduced with `VOYAGER_HOURS=0.5 VOYAGER_STEPS=60`; the measured run
with `VOYAGER_HOURS=2 VOYAGER_STEPS=200`. Costs: the pilot was 124,865
tokens for 0.5 h; the per-hour rate of the measured run is in its
payload. The tests (`tests/voyager/`, 28) need no world and no model;
the crafter round-trip test skips itself where crafter is not
installed.

## Round 2 (2026-11-02): the two named levers, and what the runs found under them

The director's round-2 note: widen the planner's facts scan 96 → 160
and re-run the 2 h fresh-world run from spawn, then two more seeds so
milestone times have repeats; give Crafter's `observe()` a spatial
fact and run until skills are admitted; compare with the teacher
(9.625 achievements/episode) and the round-1 students; release the
sandbox lease at the end. Both levers were pulled — and the Minecraft
runs found two harness defects stacked under the lever before it could
be measured, each pinned by a probe and repaired mid-round (the
commits carry the detail: `006432e`, `5ca45a7`, `bc7a85b`, `6d59947`).

### Superseded: the round-1 blindness diagnosis

> *"the planner was correctly blind for two hours … the facts reach 96
> blocks"* — round 1's measured-run paragraph, **superseded**.

The tree at 111 blocks from spawn is still measured fact
(`probe_trees.py`), and a working 96-scan would still have missed that
tree. But the planner never saw *any* block at *any* radius: the
bridge's run op dropped the program's completion value, so every
facts scan ever taken returned `{}` (all 51 steps of round 1's run,
re-checked; all 91 of round 2's first run). Radius was never the
binding constraint. The correction chain, in full: (1) the dropped
scan value (`bc7a85b`); (2) the coder's self-wrapped programs running
as fire-and-forget (`6d59947`). The round-1 numbers above stand as
measured; their *mechanism* reading is what changed.

### Minecraft: four runs, one lever, two defects, and where the bottleneck actually sits

| run | seed | steps | tokens | items | milestones | what it measured |
|---|---|---|---|---|---|---|
| mc160-a (control) | voyager-port | 91 | 730,335 | 0 | 0 | the lever pulled but inert: scan value still dropped (24 of 91 programs already self-wrapped) |
| mc160-a2 | voyager-port | 59 | 775,031 | 0 | 0 | eyes fixed, legs gone: oak_log visible 58/59 steps, but all 59 programs self-wrapped and vacuous |
| mc160-b | voyager-port-r2b | 64 | 949,367 | 1 (oak_sapling ×2) | 0 | executor fixed: all 60 programs ran for real, tree visible 64/64 — the coder is the bottleneck |
| mc160-c | voyager-port-r2c | 22 | 536,914 | 0 | 0 | executor fixed; half the steps lost to unreadable coder replies (11 of 22, the same plague that ate run b's tail); oak_log visible at 43–48 blocks while the walks carried the bot away from it |

All four: fresh world from spawn, empty hands, 2 h wall, models
planner MiMo-V2.6-Pro / coder Qwen3.8-27B / verifier Qwen3.8-Max,
curriculum seed 7; the sandbox under its 3 GB thor-admit lease; the
box shared with other seats (48–98 GB free across the day).

**The mechanism, in order of discovery.** (1) `probe_scan_cost.py`:
the widened scan is free (0.02 s at 160 against 0.03 s at 16) — the
lever was safe to pull. (2) Run a came back identical to round 1 and
its payload said why: `nearby` empty on all 91 steps while the same
scan through `run_code` sees 19 block types — `probe_facts_value.py`
found the run op discarding the completion value; fixed, and failed
scans now log instead of vanishing into an empty dict. (3) Run a2 had
eyes (oak_log in 58 of 59 steps' facts) and still zero: replaying its
own step-4 program completed "ok" in 0.02 s with an empty log — the
coder had drifted into wrapping whole programs in their own async
IIFE (0/51 in round 1, 24/91 in the control run, 59/59 in a2; it
spreads through the coder's `previous_code`), and the sandbox's own
wrapper made the inner program fire-and-forget. The bridge unwraps
one redundant IIFE and awaits thenable completion values now.
(4) Run b, on the fixed stack: every program executed for real — 33
logged fast failures, 21 honest throws, 3 long runs, 1 syntax error —
with the tree visible at every step and (per the hand-driven
sequence, `probe_wood_sequence.py`: move, mine, collect in 19 s) fully
reachable. **The residual bottleneck is the coder's fact-binding:
21 of 60 programs hunted `jungle_log`, a tree this world does not
hold, in a prompt whose facts named `oak_log`.** That is the named
lever for round 3 — block names from the facts as the only legal
targets in the coder prompt — not a bridge defect: the primitives
chop wood end-to-end when driven by hand.

### Crafter: the spatial fact, and the loop's first admitted skills

The lever: `observe()` now carries `spatial` — the nearest of each
resource and creature **in the window the pixels already render**
(the engine's own LocalView window, 9 × 8 with the player at its
centre), as direction and distance in the move primitives' own words
(left/right/up/down, |dx|+|dy| = the number of `mc.move` calls), plus
the facing and the faced tile (the tile `do` acts on). crafter-lab's
teacher reads the whole grid (privileged); the loop reads only what
its pixels already show — the comparison stays honest. Deaths no
longer stall the run (episodes end, score, reset; achievements
max-accumulate so milestones survive).

The run (4 h wall, 152 steps, 1,230,853 tokens — coder 631,780 /
planner 293,111 / verifier 305,962):

| | |
|---|---|
| achievements / episode | **4.176 over 17 finished episodes** |
| teacher (privileged grid) | 9.625 |
| students (round-1 lab: PPO / BC / teaching-moment BC) | 1.125 / 0.875 / 1.375 |
| skills admitted | **3** — collect_wood (step 5, 228.0 s, 25,927 tokens), make_wood_pickaxe (step 99, 7556.7 s, 734,728 tokens), collect_stone (step 103, 7873.0 s, 763,975 tokens) |
| achievements reached | 10 of 22, incl. defeat_zombie ×151, collect_drink ×4765, eat_cow, wake_up, place_table |

The loop sits between the students and the teacher: **3.0× the best
student at reading the same local view the students read as pixels**,
43 % of the privileged teacher. The first skill was cheap (25,927
tokens); the second cost 28× more — 93 rejected steps between the
first and second admission, all spent on the pickaxe's table-near
crafting chain. Not verified: the loop never slept on purpose
(wake_up ×2 came from energy hitting zero, not planning), and
episodes 2+ start from scratch like any episode — no cross-episode
skill *replay* was measured (the library admits; whether replaying an
admitted skill in a fresh episode works is round 3's question).

### What round 2 did not establish (named)

- **Minecraft milestones remain unmeasured** — all four round-2 runs
  reached none. What IS established: observation works (the tree is
  in the facts), execution works (programs run to their wall, logs
  and errors honest), the primitives work (a hand-driven sequence
  chops a tree in 19 s). The gap is the coder's program-writing
  (wrong block names, collect-chains that miss) — a prompt lever,
  measured next round.
- **The scan's 160 reach was never the difference between milestones
  and none** — in three of four runs the tree was within 6 blocks of
  spawn. The lever stands as pulled (it costs nothing and round 1's
  spawn measured a tree at 111), but no run isolated its effect.
- **Crafter's 4.176 is one 4 h run**, not a mean over runs; the
  teacher's 9.625 is crafter-lab's own number, measured on its own
  episode budget.
- The **drift detector still has not been run** over any run's ledger
  (round 1's limit, unchanged).
