# Playtest: the constant reward, and what was under it (2026-11-01)

The desk brief asked why the scout's main skill showed **reward exactly
0.5 on all 18,066 plays**, day and night, and asked for the fix at the
source, an audit of every skill family for the same pattern, an hour of
re-run, and the THREE.js NaN console errors fixed. This note is the
record. `NOTES.md` in the repo root is the step-by-step log, dead ends
included.

## The finding, and the chain under it

Three separate defects were wearing one costume. The box they ran on:
the Thor (aarch64, 122 GB, shared), **rebooted at ~20:00 UTC today**;
the world came back at 20:06; through everything below two other seats
ran a generation sweep and two agent sessions, and free memory stayed
between 45 and 86 GB.

### 1. The reward arithmetic: a partial was worth half a win

`PlayRecord.reward` (`reflex/agent_world_reflex/models.py`) mapped
outcomes `{win: 1.0, partial: 0.5, lose: 0.0}`. A partial is the record
for "the skill ran, but no sealed prediction could be checked" — the
scout's survey skill (`skill_4c16c6547b52`, scout.sight, "survey the
ground around") predicts `kind: "none"` by design, because looking
around changes nothing the measures can see. So every one of its plays
scored exactly 0.5. The bandit read that as a 0.5 win rate: a constant,
and a high one — higher than any working gatherer's true rate
(0.28–0.33) — which is why the survey held the scout's role while
teaching nothing. `ops/reward-audit.py --windows 2,all` shows it: 18,066
plays, one distinct reward value.

**The fix**: a partial is not half a win; it is no measurement.
`reward` returns `None` for a partial, and the chooser's `update` and
`fit` skip `None`-reward records — so an unscorable skill keeps the
judge's prior (the designed cold-start rule) until real evidence
arrives. `tests/test_reward.py` fails against the old code on six
checks ("partial carries no reward: got 0.5, want None"; the old
arithmetic also blended one real win with five phantom partials into
4/7 ≈ 0.571 where the answer from one scorable play is 0.75) and all
11 checks pass against the new.

### 2. The bodies: the builders could not walk

The audit's second finding was bigger than the first: **in the two
hours before the fix, 1,855 plays and zero wins, every family constant
at 0.0**. The last ledger win was 17:22Z. That was not the reward
arithmetic — the bots could not move:

- Pebble stood in water in a cave at (3, 27, −2), 48 blocks under the
  depot, since ~16:00Z; Kite had not moved a block all day (238 walk
  plays, all "the walk took too long", zero displacement);
- a fresh probe bot could not walk either: raw controls covered 0.02
  blocks in 3 s. The world border was fine (59999968 blocks), no mob
  stood on anyone, chunks were loaded, health and food were 20;
- a **server-side teleport of the same client** freed it instantly —
  the freeze is spot-local: the bots stand wedged against cobble
  faces, much of it the lines the community itself laid while building
  the wall;
- the mechanism (`bots/probe-wedge.js`): pressed against a face,
  mineflayer's physics reports the bot off the ground, and a jump needs
  `onGround` — so it can never step or jump out; the planner finds a
  path, its follower cannot make the first move, and `goto` hangs with
  no error (58 s measured, zero movement). The old `gotoNear` then
  ground through its whole 20 s deadline every play and started the
  same doomed walk next tick.

**The fix** (`bots/src/api.js`): a stall watcher (no net progress for
3.2 s) buys one nudge — back off, sidestep, stop the planner, retry
from a clean standstill; after two nudges the walk fails fast ("the
walk could not start") and the skill hears a failure it can act on.
The walk budget grows 1.5 s per block beyond twelve, so the scout's
24-block walk gets 38 s. A stop-race rejection ("Path was stopped
before it could be completed", probe7's old artifact) is retried as an
interruption, not obeyed as a verdict. `bots/test/goto-near.test.js`
— three tests with a stub bot that wedges — fails against the old code
(both walks grind 20 s and throw) and passes against the new (the
wedged walk fails in 16.5 s *having moved*; a progressing walk arrives
in 2.4 s; the stop-race is retried).

### 3. The judge: unreachable, twice

After the reboot the reflex asked its configured port 8094 and got
nothing — the box's one d1-2B lease was held elsewhere. When the
reflex then joined a lease whose server answered `/health`, it failed
**480 of 486 asks in 3 ms each**: that server does not speak
`/v1/systemone`. The world ran its afternoon on priors alone.

**The fix** (`reflex/agent_world_reflex/decision.py`): the port is
discovered at startup — configured port first, then any admission
lease serving this model (canonical `serve.d1-2B` before variants),
with the port read from the lease's listening socket, and **a
candidate must answer a real probe on the API the judge speaks**;
green health is not enough. The source travels with the stats
(`port_source`). `tests/test_d1_port.py`: 5 checks including the
health-but-not-API case. `ops/d1.sh start` then brought the world's
own d1-2B up under the admission daemon.

### 4. The viewer's NaN console errors (brief item 3)

Reproduced with the real browser: **12** "computeBoundingSphere():
Computed radius is NaN" errors per load, not the director's ~6 (a
night-time load draws more entities). A temporary patch of the served
bundle (`ops/patch-bundle-diag.py`, diagnosis only, restored after)
printed the geometries: twelve, each 24 positions and 36 indices —
one box — each NaN at position index 1, a NaN y. They fire before any
mob spawns. They are prismarine-viewer's fallback for a **name-less
entity**: the page builds `BoxGeometry(entity.width, entity.height,
entity.width)` from undefined dimensions. 26.1 has entities the
viewer's 1.21.4 tables do not name, and the server's `drawable()`
forwarded them because its first branch read `!entity.name` as "a
departure or a move".

**The fix** (`viewer/src/server.js`): name-less entities are left out,
like model-less mobs; departures still pass so the page forgets what
it once drew. Correction in writing: `ops/check-views.mjs` had been
*excusing* this exact warning as an empty-section artifact of
three.js — wrong twice over (the geometries were not empty; they came
from the viewer's own server) — and the excuse is gone: any console
error now fails the check, which fails against the old viewer and
passes against the new.

## The hour, measured (21:53–22:53 UTC)

After the fixes, with only the changed windows restarted (viewer,
reflex, bots; d1 started; **paper was not stopped**), the four
builders repositioned out of their wedged and barren spots by
world-ops teleport (the tool the docs already record), with the stone
quarry pit, the grass field, the depot edge and an open eastward
corridor graded by probe first:

| skill | family | plays | wins | mean reward | distinct rewards |
|---|---|---|---|---|---|
| skill_e2b1155205c6 | farmer.ground | 271 | 270 (99.6%) | 0.996 | 0.0, 1.0 |
| skill_bd703b1a37bc | gatherer.stone | 165 | 164 (99.4%) | 0.994 | 0.0, 1.0 |
| skill_8d9afce5fc4f | scout.ground | 20 | 1 | 0.05 | **0.0, 1.0 — varies** |
| skill_4c16c6547b52 | scout.sight | 1,564 | — | — | **1,564 unscored, no 0.5 anywhere** |

- The scout's walk **won once at 22:03:26Z: "moved 25.2 blocks
  (wanted 20)"** — the first walk reward the scout's record has ever
  held; the other 19 are honest losses (2.0–5.8 blocks moved, dense
  forest). Its reward now varies, which is the brief's ask; the survey
  plays on as the decision model's own choice, unscored.
- The chooser's choices move with evidence again: farmer.ground's
  night-bucket estimate rose 0.005 → **0.251**, gatherer.stone's
  0.282 → **0.361**, on plays that could actually be scored; the
  scout's survey is chosen on the judge's opinion alone (latest
  distribution: survey 0.761, walk 0.239) — the cold-start rule
  applied honestly, no fabricated number under it.
- The judge: **1,828 calls, 0 failures, mean 58.4 ms** on port 8094.
- The chooser's fold is smaller and truer: 34,157 plays folded before
  the fix, 16,819 after — the 18k phantom partials are out.
- `ops/check-views.sh`: all three pages pass; the 3D view reports
  `ok no console errors`; `probe.mjs` is clean; the screenshot shows
  terrain, a builder and the drawing strip.

Reproduce the audit with `python3 ops/reward-audit.py --windows 1`
(takes about a second on the 37k-event ledger).

## What still does not work

- **builder.wall: 19 plays, 0 wins in the hour** — "the wall could not
  grow": the gatherers stock the depot and Timber collects, but the
  wall's next placement fails. This is a skill problem (the wall's
  next spot needs support or a different strategy), which is the
  mediator's job, not the reward's.
- The scout's walk wins 1 in 20 from the current spot; a smarter scout
  skill (or a better spot policy) is mediator work too.
- farmer.seed and farmer.plant lose their occasional explored plays;
  small numbers, honest zeros.

## What it makes possible

The learning loop closes only when three things hold at once: rewards
that exist, bodies that can act, and a judge that answers. All three
hold again, so: losses mean something (a losing skill can be retired
on evidence); the mediator's sign reads real failures instead of a
wall of fabricated 0.5s; and the next console error in the viewer is
one nobody has seen before, instead of a dozen known ones drowning
it.
