# vibecode-in-world: humans and agents editing a live world, under supervision, with rewind

> **Priority (Casey, 2026-11-01):** "the rewind thing doesn't have to be perfect all things considered. it's a
> minor feature. the main thing is to be able to leave and have the community developing while you are gone."
> So the order is: (1) a community of agents (and humans who drop in) that keeps developing the world unattended,
> (2) supervision that keeps it on track without the human (validator + precedents, drift auto-pause), (3) a good
> return (letter, timeline). Rewind is a safety net: snapshot-based, good enough, not byte-perfect.

**Date:** 2026-11-01 · **Where:** `~/lm-wt/vibecode-design/` · **Branch:** the repo's current branch · **Push:** never

Casey's goal, verbatim: *"not just human players could vibecode ingame, but the agents could as well
under the correct supervision. and a human can come and go from the game world and check in on the
work and even rewind if somewhere when they were gone got off track."*

This note turns that into an architecture **over what we already have**. It is a design note, not a
build: nothing here was installed, and every number below was read off a file on the Thor on
2026-11-01/02.

---

## 0. The short version

One sentence:

> **The world is a ledger of intents; the world's state is a fold over that ledger; an edit is an
> event that must survive a pre-flight before it becomes state; and a rewind is a branch, never a
> deletion.**

Everything else in this note is that sentence plus its consequences:

- The **loop** (§1) is `intent → proposal → pre-flight in a forked canon → commit → live world`.
  Pre-flight is three checks — a scripted constraint check, a geometric critic, and a resource
  lease — and all three run against a **branch**, never against `main`.
- The **permission ladder** (§1.4) has three rungs. An unsupervised agent's commit is *a proposal*;
  the owner confirms it. That rule already exists in the code (`core/recipe/store.py`: a kid
  actor's apply becomes `branch.proposed`), which is why this is a design and not a wish.
- The **rewind** (§2) is a branch head pointing at an earlier sequence number, replayed forward.
  The ledger costs **≈5.1 MB per hour of world** and a Minecraft world snapshot is **20 MB**; both
  are cheap enough to keep every hour.
- The **drift detector** (§3.4) is a **rate** gate over the ledger, because that is what was
  measured to work: at matched recall, a rate gate cuts false alarms on cuts from 19.4 % to
  6.9 % to 0 % (`docs/lab/exp-syzygy-keyframes.md` §5.9).
- The **return** (§4) is a Biographer letter, a five-beat arc, a Director's cut and a scrubber —
  all four are views over the same ledger, so the human's "rewind to here, keep these" is one
  click on a timeline mark.
- **agent-world runs it first** (§5), because that is where the human actually is. The Bevy world
  (`last-mile`) runs it second, because that is where byte-identical replay is already proved.

The one thing this note asks for that we do not have: **a fork of a live world**, not a fork of a
recipe. §2.5 and §6 say exactly how small that is.

---

## 1. The loop: intent → proposal → pre-flight → commit → live world

### 1.1 The five steps, and where each one lives

| # | step | the existing mechanism | what it refuses |
|---|---|---|---|
| 1 | **Intent** | a work order (`wo.filed`) in the spine; a tile decision in the world (`tile.played`, `judge.verdict` in `agent-world/reflex/agent_world_reflex/ledger.py`) | an intent with no author — the ledger's `actor` field is mandatory (`core/records.py`) |
| 2 | **Proposal** | `edit.proposed` (`core/recipe/events.py`); `branch.proposed` for a kid's apply | a proposal is not an edit. It carries no effect on `main` |
| 3 | **Pre-flight in a forked canon** | constraint check (`core/recipe/constraints.py`), critic (`core/critic/`), resource lease (`tools/thor-admit`) | a change that fails any of the three never reaches `main` |
| 4 | **Commit** | `version.committed`, `branch.head.moved`; one SQLite transaction per state change, WAL + `synchronous=FULL`, side effects only after commit (`docs/design/core-spec.md` §5.1) | a stale transition: the compare-and-swap raises `StaleTransition` and the whole append transaction rolls back — **a stale transition fails closed** (`core/fold.py`) |
| 5 | **Live world** | the world's own doors: the mineflayer bot executes the tile, Paper writes the region files, the ledger appends the outcome | nothing commits before its justifying event is on disk (`core-spec` §5.1, the `prediction.sealed` → `job.enqueued` ordering) |

Two of these are worth stating precisely because they are the load-bearing parts.

**The pre-flight is pre-flight.** The constraint checks run *before* renders and before the critic,
as scripted analytic computations over the recipe's own parameters, on the CPU lane, and they are
deterministic — there is no physics engine and no "sim" in this system (`core/recipe/constraints.py`).
The five analytic kinds are `load_floor`, `keep_clear`, `reachability`, `scale_bounds`,
`budget_custom`; `watertight` is a geometry kind and is **deferred** to the merge gate. A deferred
check is not a failure — and, read the other way, it is not a pass either. It is an open item that
the critic must close before the commit.

**The commit is one transaction.** `core-spec` §5.1: *"append the `audit` row and update projections
atomically. Side effects happen only after commit — a job is enqueued, a seat started, a render
dispatched strictly after the event that justifies it exists on disk."* The world ledger in
agent-world writes through the same door: `WorldLedger.append` is *"the ledger protocol the judge
writes through: the judge records its own `judge.verdict` rows, and it does not know about this
world's own event types. So the door is the same door: one log, one append, whatever the seat."*

That last sentence is the hinge of the whole design. The judge's verdict and the bot's block
placement are the same kind of thing: **a row in one log**. Supervision is therefore not a separate
subsystem that watches the world; supervision is *reading the same log the world writes*.

### 1.2 The three pre-flight checks

**(a) The validator — scripted, analytic, deterministic.** `core/recipe/constraints.py`. One
analytic reading per constraint kind; the spec fixes the kinds, not the arithmetic, and the recipe
side's reading is documented so the engine can re-implement it identically. This is the check that
can run in milliseconds, on every proposed edit, with no model in the loop.

**(b) The critic — measured, not asserted.** `core/critic/CALIBRATION.md` publishes the table.
On the 30-member reference set (6 clean controls, 24 with a seeded defect):

| critic | TP | FP | FN | TN | in band | median ms/verdict |
|---|---|---|---|---|---|---|
| `scripted` (the fallback) | 23 | 0 | 1 | 39 | **no** | 1,059 |
| `hybrid` (chosen) | 24 | 0 | 0 | 39 | **yes** | 696 |

The band (`core-spec` §1.9): catch the seeded defects — **no false negatives** — and reject no
more than one in ten of the clean ones. The scripted critic does not hold the band on its own: it
misses `floating_object` (check `floating_blob`) at an FN rate of 50 %. The `hybrid` critic holds
it, at 696 ms per verdict. Every verdict wears the critic's name on its face (`verdict@hybrid`,
`verdict@scripted`), so a verdict always says which critic made it.

**(c) The resource lease.** `tools/thor-admit`. The edit must be booked to a tier with a peak, and
the tiers are the permission to pre-empt: only **live** work may take the box back from the
presence queue. And `thor-admit exec` *"refuses to start a framework that takes the box's memory by
surprise (JAX/XLA, TensorFlow)"* — it finds the framework by what the script imports and refuses
a JAX/XLA process without a safe allocator; the three safe ways are
`XLA_PYTHON_CLIENT_PREALLOCATE=false`, the platform allocator, or a memory fraction of at most
0.15, *"or run it under a lease, which is the rule for heavy work"*. The guard stops the biggest
**unleased** process when the box is in trouble. The rule that matters here: an agent's world edits
are background work by default, so they are charged like a lease and they yield.

### 1.3 Why the pre-flight must run on a fork, and what "forked canon" means

A pre-flight that runs against `main` is a pre-flight that can fail *after* it has already touched
the live world, because the world keeps moving while the check runs. The branch is what makes the
check sound:

- `core/recipe/store.py` creates branches with a `base`, a `head`, a `purpose` and a `protected`
  flag; `main` is protected, and `move_head` enforces that **heads never move backwards**
  (`_is_descendant`).
- The spine's fold keeps the branch head as a projection row (`core/fold.py`:
  `_h_branch_created`, `_h_branch_head_moved`).

So a forked canon is: **a named recipe version, a set of validated edits, a head that only moves
forward, and a base you can always go back to.** The pre-flight validates the head. The commit
moves the head. Nothing ever mutates `main` in place.

### 1.4 The permission ladder

| rung | who | token class | may propose | may pre-flight | may commit | may rewind | may widen its own scope |
|---|---|---|---|---|---|---|---|
| **P3** | **owner** (Casey) | `owner` (`core/auth.py`) | yes | yes | yes, to `main` | yes | yes |
| **P2** | **supervised agent** (a seat with a live lease, watched) | `panel` / `character` | yes | yes | yes, **inside a ratified scope**: a branch whose base is a named version and whose head is bounded by a constraint set | only its own branch | no |
| **P1** | **unsupervised agent** (running while the human is away) | `character` | yes | yes, on the Thor, against a fork | **no** — its commit becomes `branch.proposed` | no | no |

The ladder is not a proposal. It is already implemented in two places that were built for a
different reason:

1. **Token classes.** `core/auth.py` resolves a bearer token to a `Principal` with a class
   (`owner`, `panel`, `character`) and `check_class` refuses a class that may not use an endpoint.
   The API already gates on it: `GET/POST /v1/branches` requires `OWNER, PANEL`.
2. **The kid rule.** `core/recipe/store.py`, `apply_branch`: *"A kid actor's apply is a proposal: a
   branch apply is a real edit, so Magnus's becomes `branch.proposed` until the owner confirms
   it."* The event type exists in the closed set (`core/records.py`: `branch.proposed`, marked ▲
   "kid apply pending owner confirm").

That second one is the whole of Casey's sentence, in one method. An unsupervised agent is a kid
actor. It may build; it may not land. When the human comes back, the human lands it.

**What P1 gets, and why it is not a demotion.** P1 can still pre-flight (it can prove its edit is
good, on a fork, on the Thor, in a lease), so the human's check on return is *"this is validated,
this is budgeted, this is what it would have done"* rather than *"something happened, sorry."*
The difference is the difference between a proposal and an apology.

**What it costs.** The human's attention on return, which is why §4 is the part that has to be
good, and why the letter and the five beats come before the Director's cut.

---

## 2. Rewind: the ledger, the cost, the fork, the cherry-pick, the replay

### 2.1 What the ledger stores — three things, and only three

1. **Events.** One append-only row per decision, with a gapless per-project `seq` that is the
   resume cursor (`core-spec` §1.8). The payload is capped at **4 KiB**; anything larger spills to
   an artifact store and is hash-referenced (`core/events.py`, `spill_payload`: the slim payload
   keeps `{_spilled: {sha256, kind, bytes}, type}`).
2. **Keyframes.** What the human *saw*, at the moments the human looked. The mechanism is measured
   (§2.3) but the world does not use it yet.
3. **Seeds.** The world's own determinism: the round seed, the RNG stream, and the bot decision
   stream's inputs. On the Bevy world these are already explicit (`lm run --seed`, `lm replay`); in
   Minecraft they are not.

Everything else — the working state, the projections, the tiles — is a **fold** over the events
(`core/fold.py`: *"every projection row derives from audit events, in seq order, and nothing
else"*), so it can be thrown away and rebuilt.

### 2.2 Cost per hour of world — measured

Measured on the **Thor**, 2026-11-01T05:20:38Z → 2026-11-02T03:24:34Z (**22.07 h** of world), from
the live world ledger `agent-world/runtime/world-ledger.sqlite3`. These are the counts **as at the
end of that window**; the ledger keeps growing afterwards (§9).

| quantity | measured |
|---|---|
| events in the ledger | **82,952** |
| event rate | **3,760 events / hour** |
| ledger file | **112,517,120 B** (+ a 4,148,872 B WAL) |
| ledger growth | **≈5.1 MB / hour** (≈1,356 B per event) |
| `tile.played` | 42,567 |
| `judge.verdict` | 40,061 — every one from `judge@d1:d1-2B` |
| `tile.authored` | 285 (actor `seed`, via `cloud_author`) |
| `tile.retired` | 39 (actor `mediator`) |
| actors | Kite 24,375 · Sprout 8,509 · Pebble 7,270 · Timber 2,413 |

And the world state itself, from Paper's region files under
`agent-world/runtime/paper/world/dimensions/`:

| quantity | measured |
|---|---|
| the four overworld region files (`r.*.mca`) | **14,619,324 B** |
| the whole dimensions tree | **20 MB** |
| `level.dat` | 467 B |

**The rewind budget for one absent night (8 h):** ≈41 MB of ledger + 8 × 20 MB = 160 MB of
snapshots. Both numbers are small enough that the design does not need a retention policy to
begin: keep everything, decide later.

### 2.3 Keyframes: what they would add

The keyframe mechanism is not a guess; it was measured end to end
(`docs/lab/exp-syzygy-keyframes.md`):

- A reader holding a keyframe in its cached prefix and reading only the delta is **11.7× faster**
  on the Thor: 1.712 s → 0.146 s on a 14,012-token prefix.
- **But under motion the delta is the more expensive thing.** On a real walk at 148×80, 63.5 % of
  the glyph cells change per frame; the delta costs **50,004 tokens/frame** against the full
  frame's **6,523**. The best delta policy (budget-triggered) still costs 27,539 tokens/frame —
  **4.2×** the frame it replaces.
- **So the cost moves into idle time only while the world is still.** On an idle scene, one
  refresh per 30 frames costs **230 tokens/frame at the base grid** and **388 at the fine grid** —
  the fine grid is 1.7× the resolution and still **17× cheaper** than reading the base-resolution
  frame every frame.

The consequence for the ledger: **a keyframe is worth storing at the moments the world is still,
and the keyframe resolution is not the thing to economise on.** For the Biographer's return (§4)
and the Director's cut, that means: keyframe on the human's own stops, not on a fixed interval.

One correction to a tempting reading, made here in writing: the delta stream is *not* a cheap
world-state representation under motion. The measured winner for carrying motion is a separate,
cheap **motion channel** — 228 B per frame against the text frame's 35,828 B (**157×**), a 5 ms
local kernel run — and it is what lifts the reader's accuracy on "which way is the scene moving"
from **0.431** (below the 0.486 guessing floor) to **0.889**, +40.3 points, *p* < 0.00001
(same file, §5.6 and §5.10). A rewind log that stores only positions will not reconstruct motion.

### 2.4 A rewind is a fork, never a deletion

The ledger is append-only, so "rewind" cannot mean "delete the bad events". It means:

> **Move a branch head back to an earlier sequence number, then replay forward.**

Two implementations exist, and the second is a direct copy of the first's semantics:

- **The Bevy world.** `lm branch <parent> --at <tick> --reflex NAME=FILE --param FIELD=VALUE --out <log>`
  — *"rewinds a round to a tick, changes one thing and re-runs"*. The child log is a new file; the
  parent log is never rewritten (`last-mile/crates/lm-tools/src/main.rs`, `cmd_branch`; the CLI's own
  header: *"`lm branch` rewinds a round to a tick, changes one thing and re-runs"*).
- **The spine.** `branch.created` / `branch.head.moved`, `main` protected, heads never moving
  backwards (`core/recipe/store.py`).

For **agent-world** the fork target is a **world snapshot**: the region tree + `level.dat` + the
ledger's `seq`. That is the missing piece, and §6 sizes it.

### 2.5 Cherry-picking the good work after the bad point

This is the operation the human actually wants: *"something went wrong around 14:00, but the thing
they built at 16:00 is good — keep that."*

The machinery is nearly all here:

- **Three-way merge at entry granularity** (`core/recipe/merge.py`): merge into `main` is a
  fast-forward, or, when `main` moved meanwhile, a three-way merge at *entry* granularity —
  *"Two edits to the same entry conflict and park a question rather than auto-merging — ambiguity
  is resolved by asking, never by guessing."*
- **The branch apply** (`core/recipe/store.py`): owner-only, moves `main.head` to the branch head.
- **`lm diff` and `lm replay`** in the Bevy world: hash-verified comparison between two logs.

What is missing is the *selection* step — the part where a human, looking at a timeline, says
"these nine events are the ones I want". The merge does not need new machinery; it needs a
**selection expression** over the ledger: *everything on branch B after seq S, minus the events
the human struck out.* The strikethroughs are a UI affordance over the scrubber (§4.4), and the
selected set is fed to the existing three-way merge, which will park a question for any event that
conflicts with `main`.

Two rules make this safe:

1. **A cherry-pick is a new edit and earns its commit the same way.** It goes back through
   pre-flight (§1.2) on the fork. It does not get a discount for having been validated once.
2. **The human sees the result before it goes live.** The merge produces a branch, the branch is
   previewed in the Director's cut, and only then does `main` move.

### 2.6 Byte-identical replay — what is proved and what is not

**Proved, on the Bevy world.** `lm-core` is a deterministic fixed-point simulation — *no floats, no
unordered containers, no clock, no network* — and cross-architecture determinism is **proven on
hardware**: the trunk built natively on the Thor's aarch64 reproduces the pinned golden hashes,
`lm golden` **OK 3/3**, identical to the ProArt's x86-64, with the fairness guard passing 2/2
(`last-mile/docs/design/decisions.md`, **D69**, 2026-10-29). `lm replay` re-reads a round log and
prints `OK <n> hashes`; `lm-archive` runs a headless verifier that replays a round and checks
every state hash.

**Not proved, on the Minecraft world, and it cannot be.** The world is a live Paper server with a
human in it, four bots moving, and Geyser/Floodgate bridging Bedrock clients. Re-deciding it is not
reproducible. So the honest formulation is two-layered:

- **The ledger replays byte-identically.** It is append-only SQLite with a gapless `seq`; re-reading
  it gives the same rows.
- **The world state replays to an *equivalent* state, not an identical one** — unless the replay
  is *driven* rather than *re-decided*.

The way to make it driven is the same three things the Bevy world already has:

1. **the snapshot** — region files + `level.dat` (20 MB, measured in §2.2);
2. **the seed** — Paper's world seed and each bot's RNG stream;
3. **the decision stream as input** — replay the recorded `tile.played` decisions *into* the
   restored world instead of asking the bots to make them again.

This is labelled a design target, not a result. §8 says what would falsify it.

---

## 3. Supervision while away

### 3.1 The validator's hard rules

These never bend, and every one of them is already implemented somewhere:

1. **Pre-flight runs on a fork, never on `main`.** (§1.3)
2. **A deferred constraint is not a pass.** `watertight` defers to the merge gate's geometry check
   (`core/recipe/constraints.py`); the critic must close it before the commit.
3. **The critic's band holds or the verdict does not land.** No false negatives on seeded defects,
   and no more than one in ten clean controls rejected (`core-spec` §1.9;
   `core/critic/CALIBRATION.md`). The scripted critic misses one class; the `hybrid` critic holds
   the band at 696 ms.
4. **A stale transition fails closed.** Compare-and-swap on `from_state`; a mismatch raises
   `StaleTransition` and the whole append transaction rolls back (`core/fold.py`).
5. **Nothing is claimed durable before it is on disk.** WAL + `synchronous=FULL`; side effects only
   after commit (`core-spec` §5.1).
6. **No unleased work.** `thor-admit exec` refuses to start a framework that takes the box's memory
   by surprise without a safe allocator, and a lease is one of the ways to be safe; the guard stops
   the biggest unleased process when the box is in trouble.
7. **No human pixels, audio or transcripts are stored.** The watcher keeps derived events only —
   *what changed, and the decision* (`docs/design/screen-watcher.md`, the privacy rule). The world
   keeps the same promise: *"Your chat is never recorded anywhere — only the agents' own words and
   decisions are logged"* (`agent-world/PLAY.md`).

### 3.2 The screen watcher's "when to speak"

StreamVibe's question is *given only the past, stay silent or speak?*, asked every second, and
scored on **timing** as much as content (`docs/design/screen-watcher.md`). A screen is a better
stream than a camera because the state comes with it: the Minecraft server's events and
mineflayer's view; the night's ledger; the seats' panes; the builder IDE; the spectator's deltas.
So the watcher reads a **change stream**, time-first — rates of change, events with Δt — and never
frames.

The three minds map onto it exactly (`docs/design/three-minds.md`):

- the **reflex** decides *whether* to speak, every second, on a change stream, d1-class, local,
  milliseconds — a small **rate** gate, not a level threshold;
- the **mediator** decides *what* to say, asynchronously, only after the gate fires, and never on
  the per-second path;
- the **canon** holds the intents, each one a ledger object with a lifecycle (stated, implied,
  revised, satisfied, abandoned) — the same object type as dsmc's gaps.

**Why the gate must be a rate gate.** This is measured, and it is the single most reusable number
in this note. At matched recall on true cuts, the rate gate cuts false alarms from **19.4 %** to
**6.9 %** to **0 %**; on the reader's own confidence over the complete run it catches **93.6 %** of
the losses in **25 fires** where the level gate needs **36** for the same catch rate — and it
reaches that recall at a threshold where the level gate does not fire at all
(`docs/lab/exp-syzygy-keyframes.md` §5.9). *The level gate is a state; the rate gate is a change
of state, and only one of them is a trigger.*

So the world's drift detector must be a **rate** gate over the ledger, with **hysteresis** — the
same reason: on real d1 traces a 120 ms window on the confidence took state flickers from 66 to
about 0 (`agent-world/COACHING-IDEAS.md`, idea 13).

### 3.3 Budgets

**Box time is budgeted by tier** (`tools/thor-admit/README.md`). Every lease says what kind of work
it is; the tier is the accounting band the ledger books the seconds to, and the permission to
pre-empt — **only `live` work may take the box back from the presence queue.**

| tier | what it is | who it is for here |
|---|---|---|
| `live` | nights, previews, first-mile requests | the human's own request while they are present |
| `preparation` | pre-generating likely-needed assets, refreshing keyframes | the overnight world work: baking, refreshing keyframes |
| `practice` | retraining choosers, recalibrating confidence, **replaying proposed changes** | the pre-flight rehearsal of tomorrow's edits |
| `study` | the Infinigen sweep, hardware experiment batches, parity suites | measurement, never the live world |

A presence job runs **only when no live request is waiting**, and its memory is charged like any
lease, so a job that promised 30 GiB is held to it. `thor-admit ledger` books the hours by tier
**and by label** — the players, not just the bands — plus the GPU's power and busy share, the
per-core CPU busy share, the flow signal, and idle time broken into causes.

**Token budget** is already an event type: `budget.spend` and `budget.threshold` are in the closed
set. And the supply is measured: the Thor serves about **9 decisions/s** on d1-2B, which is why
the think rate is **1 Hz** per agent with 16 % headroom, and why a think costs a median 164 ms and
a p95 of 262 ms on the move pack (`last-mile/README.md`; `last-mile/docs/design/decisions.md`,
**D68** and **D74**). The
mediator is the expensive tier and it is never on the reflex path: **mediator calls per hour** is
the cost metric, and it should fall as the system learns — *"silence is the measure of trust"*
(`docs/design/watching-teachers.md`).

### 3.4 The drift detector: what "off track" means, measurably

The human's words are *"if somewhere when they were gone got off track"*. That has to become
numbers. Six signals, all computable from the world ledger, all **rates**:

| signal | computed from | fires when |
|---|---|---|
| **stall time rising** | the gap between consecutive `tile.played` events, per agent | the agent's trailing-window p99 gap exceeds its own 24 h median by a factor |
| **success rate falling** | `judge.verdict` rows with a good outcome, per agent | the rate over a window falls below the agent's own baseline |
| **error bursts** | `constraint.failed`, `wo.failed`, and events whose payload is flagged `refused: true` — a domain refusal commits as an event rather than vanishing (`core/fold.py`) — counted per tick-window | the *rate* of failures rises, not the count |
| **rule violations** | the bot's own actions against the human's promises | **any** occurrence — see below |
| **spend per productive decision** | thor-admit ledger by label ÷ `tile.played` | the ratio rises |
| **build drift** | the branch's head vs. its constraint set | a head that no longer satisfies its ratified scope |

**Rule violations are the one hard signal, and they get zero tolerance.** `PLAY.md` promises the
human things that are not rates: *"They never touch your stuff. Blocks you place are yours: they
won't mine them, they won't build within a few blocks of them, they won't open a chest you placed,
and they never attack a player."* Those are promises to a person, and the agent-world code already
has them as tests (`bots/src/humanity.js`, `bots/test/no-grief.test.js`). A drift detector that
averages them into a score would be worse than useless. One violation → escalate immediately.

### 3.5 Auto-pause, in three levels

1. **Soft — the agent waits.** The suspect agent is handed its own safe branch and told to hold.
   This is the "never wait" fallback the Bevy world already runs: late thinking falls back to each
   plan's own safe branch, then to reflexes. The agent is not killed; it stops committing.
2. **Tier — the world's work yields.** The world's job is demoted from `live` to `preparation`, so
   the human's next live request takes the box back. The tier system already supports this
   exactly; "the world runs at low priority on the Thor; if the box gets busy the agents pause
   politely and resume" (`PLAY.md`) is the same mechanism with a different trigger.
3. **Hard — the doors close.** The branch stops advancing; nothing commits to `main`. This is a
   write-side gate, not a kill.

Auto-pause has to be cheap to undo, and because a pause is a fork, it is: resume by moving the
branch head forward, and the paused branch's events are still in the ledger, because the ledger is
append-only and a pause is not a deletion.

---

## 4. The return

The return is the part the design put last and the part that decides whether the whole thing is
used. dsmc.md's line is the reason it is here at all: **absence, and the return, is the main
design surface.**

### 4.1 The Biographer letter

A **Biographer** writes the human a short letter between visits: **≤ 150 words, one open
question** (`docs/research/dsmc.md`). The letter is a *view* over the ledger — not a summary of a
summary. What the ledger already holds, measured over the 22 h in §2.2: 42,567 `tile.played`
decisions, 40,061 `judge.verdict` rows, 285 `tile.authored` tiles, 39 `tile.retired` tiles, and
the per-actor split (Kite 24,375 · Sprout 8,509 · Pebble 7,270 · Timber 2,413).

dsmc.md is explicit about the order, and this note follows it: **a Biographer letter written from
the existing ledger and play log — no gaps needed — shown to Casey. It is cheap, and his reaction
calibrates the rest.** That is the thinnest slice of the whole design and it should be built
first.

### 4.2 The five-beat return

The return is a **five-beat arc the human advances** (`docs/research/dsmc.md`): **threshold,
recognition, digest, thread, quiet moment**. Each beat is a screen, and each maps onto a question
the ledger can answer:

| beat | the question | the ledger's answer |
|---|---|---|
| **threshold** | *is there anything here for me?* | how much changed since my last visit, in decisions and in world state |
| **recognition** | *what is this place / this agent?* | the authored tiles and the retired ones; who did what |
| **digest** | *what happened?* | the branch heads moved, the critic's verdicts, the pauses |
| **thread** | *what is still open?* | the open gaps, the parked questions, the proposals awaiting confirmation |
| **quiet moment** | *nothing to do* | silence — and silence is an action that is logged and scored |

The fifth beat matters most and is the easiest to get wrong. A return that always ends with a
request is a nag. A return that can end with *nothing happened, and that was fine* is what makes
the next absence safe.

### 4.3 The Director's cut

dsmc.md notes the spectator is a window and the conversations want a **program**. The tool is
Theatre.js (`docs/research/theatre-open3d.md`):

- **`@theatre/core` (Apache-2.0)** — the runtime that plays sequences. Usable freely, including in
  pages we serve to others.
- **`@theatre/r3f` (Apache-2.0)** — the react-three-fiber bindings.
- **`@theatre/studio` (AGPL-3.0-only)** — the visual editor. Fine as a **local authoring tool**:
  Casey or a seat edits a sequence on the LAN and exports the JSON. **Not** bundled into any page
  we publish. The runtime reads the exported JSON, so studio never ships. This is a licence
  boundary, not a preference, and it decides the whole authoring model: *sequences are authored
  locally and exported as data.*

Three uses:

1. **The Director's cut** — keyframed camera moves over the live agent-world and thor-world 3D
   views: an establishing shot, follow a builder, cut to the depot. Authored once in studio, played
   by core, **triggered by events** (a build finished, a coach cue, a pause).
2. **The Biographer's return** — the five beats as a Theatre sequence the human advances, each beat
   a keyframed camera plus captions.
3. **Keyframe interchange** — Theatre's sequences are the same idea as Syzygy's precision
   keyframes (a few authored states with interpolation between), and its JSON is a usable
   interchange for the camera and motion keyframes our tools produce.

The camera path can be authored in Theatre and then rendered offscreen by Open3D (MIT) for the
morning report's flythroughs — the same paths, two consumers.

### 4.4 The timeline scrubber, and the one click

A scrubber over the ledger's `seq`, with the **decision points marked**:

- a branch created or a head moved;
- a constraint failed (`constraint.failed`);
- a critic verdict (`critic.verdict`);
- a rewind;
- an auto-pause;
- a gap opened (once gaps exist).

Scrubbing to a point shows the world as it was at that sequence number. Clicking a mark shows the
decision.

**"Rewind to here, keep these"** is one click on the scrubber, and it is exactly §2.5 plus §1.2:

1. the human picks a point and a set of events (strikethroughs to exclude);
2. the selection is merged onto `main` with the existing three-way merge — conflicts **park a
   question** rather than auto-merging (`core/recipe/merge.py`);
3. the result is a **branch**, so the human can preview it in the Director's cut before it lands;
4. it goes through pre-flight again, because it is a new edit;
5. `main` moves — the owner-only step.

---

## 5. Where it runs first

### 5.1 agent-world (Minecraft) — first, because the human is there

Every piece of §1–§4, mapped onto the concrete thing that already exists:

| piece | in agent-world, concretely |
|---|---|
| the world | Minecraft Java **26.1** on the Thor, LAN-only, Paper 26.1.2 (`agent-world/PLAY.md`) |
| the agents | four **mineflayer** bots — **Pebble** (gatherer), **Timber** (builder), **Kite** (scout), **Sprout** (farmer) — `agent-world/bots/src/*.js`; they keep working whether you are there or not |
| the reflex | `agent_world_reflex serve` on the Thor; the canon lives on the ProArt |
| the ledger | `agent-world/runtime/world-ledger.sqlite3` — one SQLite file, the closed event set plus the tile events; **82,952 events over 22.07 h** (§2.2) |
| the decisions | 40,061 `judge.verdict` rows, every one from `judge@d1:d1-2B`; 42,567 `tile.played` rows |
| the world state | Paper's region files: `runtime/paper/world/dimensions/minecraft/overworld/region/r.*.mca` — four files, **14,619,324 B**; the dimensions tree **20 MB**; `level.dat` 467 B |
| the human | Java clients at `192.168.0.78:25565`; Bedrock at `:19132` through Geyser + Floodgate (signed-in Xbox/Microsoft account required); watchers at `http://192.168.0.78:8080/`, `/ascii`, `/voices` |
| the promises | *"They never touch your stuff"*: no mining a player's blocks, no building within a few blocks of them, no opening a player's chest, no attacking a player (`bots/src/humanity.js`, `bots/test/no-grief.test.js`) |
| the privacy | *"Your chat is never recorded anywhere — only the agents' own words and decisions are logged"* |
| the world state, in text | `/ascii` is the same world in text; `/voices` speaks the agents' lines — the three minds already have three projectors |

**What agent-world gives us that the spine does not:** a real world with a real human in it; region
files that can be snapshotted; a public promise set in `PLAY.md` that the validator can enforce; and
three projectors already (3D, ascii, voice) so a "Director's cut" has somewhere to play.

**What agent-world lacks: determinism.** The world is a live server with a human in it. So rewind
there is **snapshot-based, not replay-based**: restore the region tree and `level.dat`, then replay
the recorded `tile.played` decisions *as inputs* against the restored world (§2.6). The Bevy world
is where the deterministic version of this is proved.

### 5.2 The Bevy world (`last-mile`) — second, because replay is already proved there

`last-mile` has the thing agent-world does not have, and it has it **measured**:

| need | in `last-mile` |
|---|---|
| deterministic simulation | `lm-core`: fixed-point, **no floats, no unordered containers, no clock, no network**; rounds replay **bit-exact** |
| cross-architecture replay | built natively on the Thor's aarch64, `lm golden` **OK 3/3**, identical to the ProArt's x86-64; fairness guard 2/2 (**D69**) |
| rewind-and-change-one-thing | `lm branch <parent> --at <tick> --reflex NAME=FILE --param FIELD=VALUE --out <log>`; the parent log is never rewritten |
| hash-verified replay | `lm replay` prints `OK <n> hashes`; `lm diff` compares two logs |
| an archive | `lm-archive` on the Orin: flat store, framed `lm_proto::Msg` ingest, a headless verifier that replays a round and checks every state hash, yielding to the desktop |
| a learning loop over seeds | `lm learn --seed N --harness ...`, evaluated on held-out seeds before it is adopted |
| the human's seat | the Bevy map, piano roll, HUD and replay on the ProArt (`lm-host`); the ProArt is the sequencer and authoritative simulation, the Thor is the agent host |
| the decision supply | the Thor serves ~9 decisions/s on d1-2B; 1 Hz think rate, 16 % headroom (**D68**) |

What `last-mile` does **not** have is the *product* half: the permission ladder, the drift
detector's auto-pause, the Biographer's letter, the Director's cut. Those are the same work in
both worlds, and the world's differences are only in how the state is snapshotted.

**So the ordering is not a preference.** The supervision work (§3, §4) goes where the human is:
agent-world. The rewind work (§2) goes where replay is provably byte-identical: the Bevy world.
They share the ledger vocabulary (`AuditEvent`), the gate vocabulary (d1-class reflex, rate-first)
and the tier vocabulary (thor-admit).

---

## 6. Gaps table, and the five next builds

### 6.1 The table

`e` = exists, `p` = partial, `m` = missing.

| # | piece | state | where it lives | smallest next build |
|---|---|---|---|---|
| 1 | one append-only ledger of record | **e** | `core/records.py`, `core/fold.py`, `core/store.py`; `agent-world/reflex/agent_world_reflex/ledger.py` | — |
| 2 | durable commits, gapless `seq`, payload spill | **e** | `core/recipe/ledger.py`, `core/events.py`; `core-spec` §1.8, §5.1 | — |
| 3 | branch / fork of the canon | **e** | `core/recipe/store.py` (`branch.created`, `branch.head.moved`, protected `main`) | — |
| 4 | deterministic rewind-and-rerun, byte-identical | **e** *(Bevy only)* | `last-mile`: `lm branch`, `lm replay`, D69 | port the *shape* to the world ledger |
| 5 | three-way merge with parked conflicts | **e** *(recipe level)* | `core/recipe/merge.py` | lift "parked question" from recipes to world events |
| 6 | world snapshot / restore | **m** | Paper writes `.mca` region files + `level.dat`; nothing snapshots or restores them | a snapshot/restore script: copy the dimensions tree + `level.dat`, restore by swap, with a manifest |
| 7 | constraint validator | **e** | `core/recipe/constraints.py` | add the world's own constraint kinds |
| 8 | geometric critic | **e** | `core/critic/`, `core/critic/CALIBRATION.md` (hybrid: 24/0/0/39, 696 ms) | a world-scale defect class (a bot building inside the human's protected area) |
| 9 | resource lease + tiers | **e** | `tools/thor-admit/` | a `world` label so the hours are booked per agent |
| 10 | permission ladder | **p** | `core/auth.py` token classes; the kid-actor rule in `core/recipe/store.py` | one function that maps a token class to a rung, and one guard on the commit door |
| 11 | screen watcher's "when to speak" | **p** *(design only)* | `docs/design/screen-watcher.md` | the seat-watcher experiment: replay a day's board states and logs as a one-second change stream, label the director's interventions as help points, measure rate gate vs level gate |
| 12 | drift detector | **m** | the rate-gate mechanism is measured (`exp-syzygy-keyframes` §5.9); nothing is wired to a world | a rate gate over the world ledger with hysteresis, per agent, with the six signals of §3.4 |
| 13 | auto-pause | **p** | thor-admit's tier pre-emption; the world's "pause politely when the box is busy" | a drift-triggered tier demotion + a write-side door |
| 14 | Biographer letter | **m** | `dsmc.md` §"design for absence" | a ≤150-word letter with one open question, written from the existing ledger |
| 15 | five-beat return | **m** | `dsmc.md` | five screens over the ledger, ending in a beat that can be silent |
| 16 | Director's cut | **m** | `docs/research/theatre-open3d.md` (Apache-2.0 core; AGPL studio stays local) | one authored Theatre sequence (establishing → follow a builder → depot) triggered from the world's events |
| 17 | timeline scrubber with marked decision points | **m** | the ledger has `seq`; the world viewer has no timeline | a seq scrubber over the world ledger, marking branches, constraint failures, critic verdicts, pauses |
| 18 | one-click "rewind to here, keep these" | **m** | §2.5: selection is missing; merge and apply exist | a selection expression over the ledger, fed to `three_way_merge` |
| 19 | gaps as first-class canon objects → precedent store → validator → BoardManifest | **m** | `dsmc.md` §"the order" | the gaps object (stated → proposed → adjudicated → closed, receipted) |
| 20 | keyframes of what the human saw | **p** *(measured, not adopted)* | `docs/lab/exp-syzygy-keyframes.md` | keyframe on the human's stops; use the motion channel, not the cell delta, under motion |
| 21 | the bots' own code | **e** | `agent-world/bots/src/` — mineflayer, `humanity.js`, `no-grief.test.js` | — |

### 6.2 The five next builds, ranked

Ranked by *unlocks the most of the design per unit of work*, and each is sized to be a day or two,
not a phase.

**1 — Snapshot and restore for the world, with a manifest.**
The single missing primitive (§6.1 row 6). Everything in §2 that is not in the Bevy world depends
on it: rewind, the scrubber's world view, the cherry-pick preview, and the auto-pause's undo.
Measured cost: the dimensions tree is 20 MB and `level.dat` is 467 B, so an hourly snapshot for
8 h is 160 MB. The build is a script that copies the tree plus `level.dat`, writes a manifest
(region file list + sizes + sha256 + the ledger `seq` + Paper's world seed), and restores by swap.
**This is the smallest next build with the largest unlock.**

**2 — The drift detector and auto-pause, measured on the ledger that already exists.**
Rows 12 and 13. The data is already there: 82,952 events with per-actor attribution and
`judge.verdict` outcomes. The build is a rate gate over the ledger with hysteresis and a
five-minute window, the six signals of §3.4, the hard signal separated from the scored ones, and
a tier demotion wired to `thor-admit`. The measure is the syzygy one, reused directly: at matched
recall the rate gate beats the level gate (19.4 % → 6.9 % → 0 % false alarms). We can be held to
that bar because it is the same experiment on a different stream.

**3 — The seat-watcher experiment (the "when to speak" gate).**
Row 11. The labelled dataset already exists and needs no new collection: the director's own
interventions, with timestamps, from `~/lm-ops/TEAM.md` and `BOARD.md` history and the seats' `.out`
mtimes — every one of those interventions was a help point (a hung seat, quota exhaustion, the JAX
runaway, the lock starvation, the Wi-Fi saturation). Replay a day's board states and logs as a
one-second change stream, label the interventions, and measure a rate gate against a level gate on
help-point precision/recall and false-positive rate, plus the minutes of stall each would have
saved. **No privacy question, our own data, and it pays off at once.**

**4 — The Biographer letter from the existing ledger.**
Row 14. dsmc.md calls it *"a thin slice now… It is cheap, and his reaction calibrates the rest."*
The build is a ≤150-word letter with one open question, generated from the world's own ledger
(`tile.played`, `judge.verdict`, `tile.authored`, `tile.retired`, the branch heads, the pauses) and
shown to Casey. It is the smallest slice of the return and it is what the rest of §4 is designed
around.

**5 — "Rewind to here, keep these": the cherry-pick.**
Rows 5 and 18. The merge exists (`core/recipe/merge.py`, three-way at entry granularity, conflicts
park a question); `lm branch` exists; what is missing is the selection. The build is a selection
expression over the ledger (a set of `seq`s), a preview that renders the cherry-picked result on a
branch, and the pre-flight re-run on that branch before `main` moves. It is the click the human
actually wants, and it is the last thing needed before the return is complete.

**Not in the five, and why:** the gaps → precedent store → BoardManifest track (row 19) is the
foundation for the spectator and for dsmc's governance of the mediator, but the Biographer letter
does not need it and the four beats that matter can be built without it; it is the sixth build.
The Theatre.js Director's cut (row 16) needs Casey's OK before `@theatre/studio` is installed
anywhere, and it is presentation over a substrate that build 5 completes.

---

## 7. Where the phase-2 tools slot

The phase-2 shortlist and its one-day test plans are in `docs/research/ingame-building.md`
(shortlists 1–3) and `docs/research/ingame-building/RESULT.md`. Phase 2 needs Casey's OK before
anything is installed. Here is where each one lands **in this architecture**.

### 7.1 `topview-3d-builder` → the Director's cut's authoring path

*What it is:* an agent plugin that builds a 3D scene from an idea, places cameras, plans a camera
move in its "Studio", and renders an animated video. Apache-2.0. **Evaluate in an isolated
worktree** — its README asks agents to install it as a plugin into themselves, which we do not do
without Casey's explicit OK.

*Where it slots:* it is our **B2 pattern** — the agent writes the scene, local tools render — with
a camera planner attached. That makes it the natural producer of the Director's cut's camera work,
and the counterpart to Theatre.js's local studio authoring:

- **The agent authors the cut.** Casey's rule is that the agent writes the scene and the local
  tools render it. A cut is a scene with a camera and a plan; topview is exactly that shape, so an
  agent can propose a cut (not just play one), and Theatre's exported JSON can be the canonical
  form that topview's fcurves are converted to and from.
- **The fcurve interchange test is already written down** (`ingame-building.md`, shortlist 1):
  convert one Theatre.js sequence into topview fcurves and back, and record whether the compact
  format can carry a Theatre sequence without loss. That is the §4.3 interchange, measured.
- **The comparison that matters** is topview's grounding and framing vocabulary against the
  critic's own checks on the same asset: where the two disagree, which is right. That is the
  pre-flight of §1.2, extended from "is this asset sound" to "is this cut sound".
- **Cost note:** it is the only shortlisted tool driveable end to end with no account, no cloud
  and no GPU. Needs Python 3.11+, Node 20.6+, `uv` or `pipx`, then `topview-3d-cli doctor` and
  `topview-3d-cli browser ensure --with-deps` (≈500 MB).

### 7.2 `build-world`'s three.js kit → the pre-flight's visual gate, and the cut's shot list

*What it is:* a capture harness over a three.js scene. Apache-2.0 for the parts we port.

*Where it slots,* in two places:

- **The visual half of pre-flight.** Our two viewers are three.js — agent-world's
  prismarine-viewer and thor-world's three.js viewer — and neither currently asserts that the same
  scene renders the same way twice. The kit's capture harness renders a fixed set of named shots
  twice and diffs the frames. **If the diff is usable rather than noise, it becomes a critic
  check** (a baseline-diff gate), and then it becomes the cheapest way to answer the question the
  Director's cut asks: *did the build change what the human will see?* The build-world day in
  `ingame-building.md` (shortlist 2) is exactly this experiment, already specified.
- **The shot list.** A fixed set of named shots is what a Director's cut needs to reference
  ("establishing", "follow the builder", "depot"), and it is what makes a diff comparable between
  two moments in the ledger — the "the world changed at seq 41,203" marker on the scrubber becomes
  a frame difference rather than a claim.

Needs Node 20.6+ and Chromium (`npx playwright install chromium`); nothing else, no account, no
cloud. **It is the cheapest item in either phase** and it touches our actual viewers.

### 7.3 Vibe3DScene's transactional tool calls → the write path's transaction shape

*What it is:* a Blender-hosted MCP server. We are **not** adopting the tool — it is a poor fit
(Blender as the runtime, Docker, Redis, provider keys, one author, seven months stale). We are
taking **one mechanism**: transactional tool execution — `safe_mode`, `rollback_on_guard_fail`,
`validate_scene`.

*Where it slots:* this is the **transactional shape for the write path**, which is precisely what
§1.2 and §2.5 need. The rule it encodes is: **run it, validate the result, roll back on failure,
and only then commit.** That is the pre-flight, expressed as a property of the tool rather than as
a stage in a pipeline. Concretely:

- The **agent's world edit** becomes a transaction: it runs against the forked canon, the
  constraint check and the critic run inside the transaction, and a failure rolls the branch back
  to its base instead of leaving a half-applied edit.
- The **cherry-pick** becomes a transaction too: the merge produces a branch, the pre-flight runs,
  and a failed pre-flight rolls the branch back rather than parking a question for a conflict the
  critic has already settled.
- The **auto-pause** is the transaction's abort path, which is why undoing a pause is free.

The one-day plan (`ingame-building.md`, shortlist 3): run the MCP server locally against our own
**aarch64 Blender 4.2** on the Thor — which its own download script does not know how to fetch —
exercise ten tools, and then port the transactional shape into one of our own write-path tools.
**The deliverable we want is the pattern, not the tool.** The day still returns the pattern even
if the answer on Blender-as-runtime is no, which is why it is worth a day and not a week.

### 7.4 The one that is not in the shortlist but belongs here

`docs/research/theatre-open3d.md` records **Open3D** (MIT) for the critic's geometry — voxel
occupancy, watertightness, normals, mesh simplification — and for **offscreen flythroughs** of
generated props and scenes **on a camera path possibly authored in Theatre.js and exported**. That
is §4.3's Director's cut rendered for the morning report, and it is the same camera path as
topview's. The evaluation queued there — occupancy, watertightness and simplification against what
critic-shells and mesh-repair use, for speed and agreement — is a prerequisite for trusting
Open3D as the pre-flight's geometry layer.

---

## 8. What is not verified

Stated plainly, per the documentation rules.

1. **The Minecraft rewind has not been built or measured.** The 20 MB snapshot and 14,619,324 B of
   region files are measurements; "restore the region tree and replay the decisions against it"
   is a design. **It could fail**: Paper's world may hold state outside the region files (player
   data, plugin state in `runtime/paper/plugins/`, the `session.lock`), and the four bots' actions
   are not the only things that change the world. The smallest way to find out is build 1 and try
   one restore.
2. **Byte-identical replay is proved for the Bevy world only** (D69, `lm golden` OK 3/3 on
   aarch64). It is **not** proved for agent-world, and §2.6 argues it cannot be, which is why the
   world rewind is snapshot-based rather than replay-based. If Casey's expectation for the
   Minecraft world is bit-identical replay, this design does not deliver it and says so.
3. **The drift thresholds in §3.4 are not yet calibrated.** They are named as quantities (stall
   time, success rate, error bursts, spend ratio) with the *shape* of the test fixed — rate, not
   level, with hysteresis — but the multipliers ("exceeds its own 24 h median by a factor") are
   placeholders. The 82,952 events are a labelled starting corpus, not a calibrated detector.
4. **No drift detector has been run against a world.** The rate-gate result (19.4 % → 6.9 % → 0 %)
   is from the syzygy cuts corpus, not from the world ledger. Transferring it is a hypothesis.
5. **The Biographer letter has not been written once.** The ≤150-word shape and the one open
   question come from dsmc.md. Whether it reads as a letter rather than as a report is exactly what
   dsmc.md says Casey's reaction will tell us.
6. **The permission ladder is mapped onto existing primitives, not implemented as one.** The token
   classes exist (`core/auth.py`) and the kid-actor rule exists (`core/recipe/store.py`), but there
   is no single rung function and no guard on the world's commit door. The mapping is my reading of
   two code paths; the *policy* (which rung an unsupervised Minecraft bot sits on) is a decision
   Casey has not made.
7. **The keyframe policy for the world is unmeasured.** §2.3 reports the syzygy numbers on a
   148×80 walk; the world's own resolution and motion profile are different, so "keyframes on the
   human's stops" is a starting hypothesis, and the motion-channel result (0.431 → 0.889) was
   measured on synthetic scenes with planted motion.
8. **Theatre.js and Open3D are not installed.** Both licences are checked (Apache-2.0 core and
   r3f; AGPL-3.0 studio, local-only; MIT for Open3D), but the studio boundary has not been
   exercised, and Open3D's aarch64 wheel availability was flagged as needing a check.
9. **The topview and build-world claims come from the phase-1 survey**, which was explicitly
   read-only: 21 repositories read, nothing installed, built or executed. Their behaviour on our
   viewers is untested, and the survey's own unverified list (Prowl's linux-arm64 natives, Torque3D's
   ARM64 build, Playwright Chromium on aarch64, the Vibe3DScene Blender submodule) still stands.
10. **The box was not idle during the measurements.** The Thor was carrying 21 users, load average
    21.18 / 25.76 / 31.28, 122 GB total memory with 13 GB used and 90 GB free, with the reflex
    server and other work resident. The ledger numbers in §2.2 are the world's own counts and are
    not affected by the load; the *timings* quoted elsewhere (the critic's 696 ms, the syzygy
    reader's 1.712 s → 0.146 s) were measured on this box under its own conditions and should be
    re-measured on an idle box before they are treated as budgets.
11. **The Bevy world has not been run with an agent in it.** `last-mile`'s phases are marked done,
    but phase 2's status is *"Done (Casey's hands-on acceptance pending)"*. The supervision half of
    this design would be the first thing to run against it.

---

## 9. Reproducing the numbers

Every figure in §2.2 comes from the live world ledger on the Thor. The commands (read-only; the
ledger is queried with `mode=ro` so nothing is written):

```bash
ssh thor-lan
cd ~/lm-wt/agent-world
python3 - <<'PY'
import sqlite3
c = sqlite3.connect("file:runtime/world-ledger.sqlite3?mode=ro", uri=True)
print("total:", c.execute("select count(*) from audit").fetchone()[0])
print("span:",  c.execute("select min(at), max(at) from audit").fetchone())
for t, n in c.execute("select type, count(*) from audit group by type order by 2 desc"):
    print(f"{n:>8}  {t}")
for a, n in c.execute("select actor, count(*) from audit group by actor order by 2 desc"):
    print(f"{n:>8}  {a}")
PY
ls -la runtime/world-ledger.sqlite3*
find runtime/paper/world/dimensions -name "*.mca" -printf "%p %s\n"
du -sh runtime/paper/world/dimensions
```

The event rate (3,760/h) and the growth rate (≈5.1 MB/h) are the two quotients of the totals above
by the 22.07 h span; the ≈1,356 B/event is the file size over the event count.

**These are a snapshot, not a live reading.** The world keeps running and the ledger keeps growing,
so re-running the script now returns larger counts. The figures in §2.2 are the counts **as at
2026-11-02T03:24:34Z**, the end of the stated window, and the rates are over that window. To
reproduce them as written, bound the query with `where at <= '2026-11-02T03:24:34Z'` and take the
file size at that moment.

The critic's table is regenerated by the script beside it: `.venv/bin/python -m core.critic --grow --publish`
(`core/critic/CALIBRATION.md` says so at the top; the file is generated by `core/critic/publish.py`).

The syzygy numbers are in `docs/lab/exp-syzygy-keyframes.md` §4.10 (the keyframe policy sweep) and
§5.9 (the rate gate), with the reproduction steps in that file's §8.

The Bevy numbers are `last-mile/docs/design/decisions.md` **D69** (cross-architecture determinism)
and **D68** (the decision supply), and `last-mile/README.md` for the crate table.

---

## 10. One paragraph, for the person who asked

The world we already have — a Minecraft server with four bots that keep working while you are
away, a ledger that records every decision, a critic with a measured table, a recipe store that
already refuses to let an unsupervised actor land an edit, and a Bevy world whose rounds replay
bit-exact on the Thor's own processor — is most of Casey's sentence. What it does not have is the
one thing that connects them: **a fork of a live world.** That is 20 MB of region files, a
manifest, and a script, and it is the first build. The second is a rate gate over the ledger that
knows when the agents have drifted, because the same gate was already measured to beat a level
threshold by a factor of three on false alarms. The third is a letter, because a return that is not
a letter is a bill. The fourth is a click — *rewind to here, keep these* — which is a selection
over the ledger fed into a merge that already exists and refuses to guess.
