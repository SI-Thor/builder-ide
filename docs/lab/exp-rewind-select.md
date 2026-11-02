# exp-rewind-select — "rewind to here, keep these", measured

**What was asked.** Build #5 of `docs/design/vibecode-in-world.md`: the
**selection** step the cherry-pick was missing. A selection expression over
the world ledger (by actor, time range, event kind, tile/skill id, verdict)
that, given a rewind point, replays the kept events onto a fork of that
point through the existing three-way merge, parking conflicts rather than
guessing. Prove it on the Bevy world ledger, where byte-identical replay
holds. Measure the cost per hour of world (time, bytes).

**What was built.** `core/rewind/` (the selection language, the ledger
readers, fork-at-point, replay-kept, the report) and 33 tests under
`tests/rewind/`. Two small additions to the Bevy world's CLI, in the
`last-mile` repository on its own branch: `lm dump` (a round log's
decisions, readable from outside Rust) and `lm branch --drop` (stop
applying a source's decisions from the branch tick on — the library and the
simulation already had both halves; only the flag was missing).

**The short version.** The selection is a small parsed language with seven
fields, and every event it does not keep carries the reason it was
dropped. On the Bevy world the rewind is proved: the fork (`lm branch
--at 150 --drop agent:3`) and the reference (`lm run --inject` with the
decisions the selection kept, replayed by the Python side) are **the same
world, tick for tick** — `lm diff` says `IDENTICAL` — and the two are built
by code that shares nothing but the ledger they read. The cost per hour of
world is **0.081 s** to read the world's ledger and **0.024 s** to run a
selection over it; one cherry-pick writes **5 events and 772 bytes** and
takes **23 ms**; the ledger's own growth is **5.23 MB per hour of world**,
so the rewind's own writes are three orders of magnitude below the ledger
they read.

---

## 1. The mechanism

### 1.1 The fact the build stands on

The ledger is append-only and every row has a gapless `seq`
(`core/recipe/ledger.py`, `core/events.py`). A rewind therefore cannot mean
"delete the bad events"; it means *cut a branch at an earlier point and
replay forward* (`docs/design/vibecode-in-world.md` §2.4). The Bevy world
already had that machinery — `lm branch` replays the parent to a tick with
every hash verified and plays on — and the recipe store already had its
own (`create_branch`, `move_head`, heads that never move backwards). What
neither had was the **selection**: the step where a human, looking at a
timeline, says *these nine events are the ones I want*.

### 1.2 Why the old way could not do it

The merge exists (`core/recipe/merge.py`: three-way at entry granularity,
conflicts park a question). But the merge takes two *documents* and a base;
it has no way to say which of a hundred events are the ones to bring
across. The Bevy world has the same gap from the other side: `lm branch`
could change a reflex script or a parameter, and `Change::DropDecisions`
existed in the library and in the simulation, but there was no flag to reach
it — so a fork could retune the round but could not drop an actor.

### 1.3 What changed

**The selection language** (`core/rewind/selection.py`) is one expression
over a ledger's rows:

```
actor = Kite and kind in (tile.played, tile.authored)
at >= 2026-11-01T05:00:00Z and at < 2026-11-01T07:00:00Z
not (kind = judge.verdict) or verdict = accept
id = skill_14fd7774a036
```

Seven fields — `actor` (who wrote the row), `agent` (who the row is
*about*, which is not the same thing), `kind`, `id` (the tile or skill id),
`verdict`, `at` (the time), `seq` — eight operators, and `and`/`or`/`not`.
Two rules make it safe to hand to a human:

* **A dropped row says why.** `actor ('Pebble') is not 'Kite'` — the report
  prints the reason, not a count.
* **A comparison that cannot mean anything is refused.** A number
  comparison on a text field is a parse error naming the field; a
  timestamp against a ledger whose time is ticks is a refusal, not a
  silent comparison of two different kinds of number.

**Fork-at-point** (`core/rewind/fork.py`) cuts a branch at a version. The
canon's own branch does not move and no version is removed: a rewind is a
fork, never a deletion. The point carries the ledger's `seq`, so "the
events after this point" is exact rather than approximate.

**Replay-kept** (`core/rewind/replay.py`) applies the kept events' ops to
the fork's document and merges it with the canon through the existing
`three_way_merge`: base = the point, ours = the canon now, theirs = the
replayed fork. A conflict **parks**: the question goes into the ledger as
a `question.parked` event, the merge does not happen, and the canon does
not move. The cherry-pick lands on the *fork*; moving `main` is the
owner's separate step (`store.apply_branch`).

### 1.4 The one thing it deliberately does not do

The cherry-pick brings work across; it does not remove work the canon
already has. The merge is *with* main, so where main already holds a
change the merge keeps main's copy. Removing main's own history is not a
fork's business — and the canon's heads are not allowed to move backwards
in any case.

---

## 2. The proof on the Bevy world

The Bevy world is where byte-identical replay holds (§2.6), so it is where
the rewind is proved rather than asserted.

**The round.** Two actors, each with work before and after the rewind
point, injected into a headless round of 300 ticks (seed 5, eight reflex
agents, the beacons ruleset):

| tick | actor 0 | actor 3 |
|---|---|---|
| 100 | `GoTo(12, 9)` | `GoTo(30, 30)` |
| 200 | `GoTo(40, 12)` | `GoTo(18, 44)` |

The round records **10 state hashes** and `lm replay` checks every one of
them: `OK 10 hashes`.

**The rewind.** The point is tick 150. The selection is
`actor = agent:0`: keep one actor's later work, drop another's.

**Two mechanisms, one world.**

* the **fork** — `lm branch parent.lml --at 150 --drop agent:3 --out fork.lml`:
  the round's own machinery. The sim stops applying agent 3's decisions
  from the tick on.
* the **reference** — `lm run --seed 5 --ticks 300 --inject <the kept
  decisions> --out reference.lml`: the decisions the selection kept, read
  out of the parent's log by `lm dump` and replayed into a fresh round by
  this package.

They share nothing but the ledger they read: the fork is Rust, the
reference is Python. `lm diff fork.lml reference.lml` says:

```
IDENTICAL
```

**That is the claim the design note asks for** — the fork's state equals a
world in which only the kept actor acted after the rewind point — and it
holds tick for tick, because the two worlds apply the same decisions to the
same deterministic simulation.

Two numbers that come with it:

* the fork parts company with its parent at **tick 209** — the first state
  hash after the dropped decision's tick (200), the hashes being taken at
  ticks 29, 59, … 299;
* the fork's header carries the drop: `{"lineage":{"at":150,"changes":1}}`.

### 2.1 A finding about the fork's log

**The fork's log is not a record of what was applied.** `lm dump fork.lml`
prints all four decisions, including agent 3's decision at tick 200 — the
one the drop was meant to stop applying. The recorder writes every decision
it hands to the simulation; the simulation drops the ones the lineage says
to drop, and it drops them again on every replay, so `lm replay fork.lml`
still checks out.

This matters for the design: the fork's log cannot be used to ask "what did
this fork do" by reading its decisions. The header's lineage is what says
it, and the state hashes are what prove it. It is also why the reference
run is built from the **parent's** dump and not the fork's: feeding the
fork's own decisions back in would reintroduce the dropped ones.

### 2.2 Where the fork's machinery cannot express the selection

The fork can only drop a **whole source**. A selection that keeps some of
a source's decisions and drops others — "keep agent 0's `Intent`s, drop its
`Roll`s" — is finer than `lm branch --drop` can say. The package names
those sources in `partial_sources` and says so in the report; the reference
run is the only world that can show such a selection, because it filters
per decision. This is the limit the design note means by *"where replay
allows"*.

---

## 3. The cost per hour of world

The world's ledger is live, so these numbers are as at the reading, not as
at any later moment. Box state at the reading: the **Thor** (Jetson AGX
Thor, aarch64, 14 CPUs), load average **28.35 / 22.94 / 17.91** — other
seats were running on the same box — and **92,844,048 kB** (≈88.5 GiB)
available. The timings below are therefore pessimistic: they were taken on a
loaded box.

### 3.1 The world's ledger

`agent-world/runtime/world-ledger.sqlite3`, read read-only:

| quantity | measured |
|---|---|
| rows | **91,487** |
| span of world | **24.508 h** (2026-11-01T05:20:38Z → 2026-11-02T05:51:06Z) |
| rows per hour of world | **3,733** |
| ledger file | **123,977,728 B** |
| WAL | **4,148,872 B** |
| **bytes per hour of world** | **5,227,962 B** (5.23 MB/h) |
| time to read the whole ledger | **1.983 s** |
| **read time per hour of world** | **0.081 s** |
| time to run a selection over every row | **0.578 s** |
| **selection time per hour of world** | **0.024 s** |
| rows kept by `actor = Kite or agent = Pebble` | **37,610** (300,880 B of `seq`s) |

The rate is the design note's, re-measured: §2.2 measured ≈5.1 MB/h over
22.07 h and 82,952 events; the same ledger reads 5.23 MB/h over 24.51 h and
91,487 rows — the same rate, two and a half hours later.

### 3.2 One cherry-pick over a canon

A canon of two entries, a branch with two edits by two actors, a selection
that keeps one actor's work, on a SQLite ledger of record:

| quantity | measured |
|---|---|
| events written | **5** (`branch.created`, `edit.proposed`, `edit.validated`, `version.committed`, `branch.head.moved`) |
| payload of those events | **772 B** |
| ledger file + WAL growth | **115,360 B** (SQLite's WAL page allocation, not payload) |
| wall time | **23.1 ms** |
| kept / dropped / parked | **4 / 6 / 0** |
| merged cleanly | yes |
| the canon's head moved | **no** |

One human action costs five events and 772 bytes of payload. Against the
ledger's own 5.23 MB per hour of world, that is 0.0001 % of an hour's
ledger.

### 3.3 The Bevy fork

| quantity | measured |
|---|---|
| the round (300 ticks, 10 hashes) | **0.114 s** to play, **0.090 s** to replay |
| the whole keep — fork, reference, diff | **0.285 s** |
| parent log | **5,206 B** |
| fork log | **5,234 B** (+28 B: the lineage in the header) |
| reference log | **5,191 B** |

---

## 4. What is not verified

* **The Minecraft world does not replay byte-identically** and this build
  does not change that (§2.6). The world's ledger is *read* and *selected*
  over here; the world's *state* cannot be rewound by replaying decisions,
  because the world is a live Paper server with a human in it. What the
  package proves on the Bevy world is the selection and the fork; the
  world's own rewind still needs the snapshot/restore that §6.1 row 6 calls
  missing.
* **The measurements were taken on a loaded box** (load average 28 on 14
  CPUs). The times are upper bounds; the ratios between them are not
  affected in any way that matters at this scale.
* **A Bevy round is not an hour of world.** No tick-to-hour mapping was
  established, so §3.3's numbers are per round and are not folded into the
  per-hour figures.
* **The selection was not run against the live world's *events* in a
  cherry-pick.** The world's ledger rows and the recipe canon's events are
  two different ledgers; the world's rows were selected over and measured,
  but a cherry-pick over the world's own events (the `tile.played` rows as
  work to replay) is not built, because the world's events do not carry
  recipe ops.
* **The world's ledger attribution is a convention, not a schema.** Which
  agent a `judge.verdict` row is *about* is read from
  `payload.judgments[].qid`, and a play's from `payload.context.bot` — the
  same convention the drift detector uses. A row that carries neither falls
  back to its actor.
* **One source of the fork's dropped decisions was not re-checked at
  scale.** The Bevy proof runs on a 300-tick round with four injected
  decisions; the mechanism is the simulation's own, but the number of
  actors and the length of the round are small.

---

## 5. Reproducing it

```bash
cd ~/lm-wt/rewind-select
export PATH=$HOME/last-mile/target/release:$PATH

# 1. the measurement (about a minute; no GPU, no model)
.venv/bin/python docs/lab/rewind-select-scripts/exp_rewind_select.py \
    --ledger ~/lm-wt/agent-world/runtime/world-ledger.sqlite3 \
    --lm ~/last-mile/target/release/lm \
    --out docs/lab/rewind-select-scripts/results/rewind-select.json

# 2. the tests (33; the four Bevy ones need the lm tool on the PATH)
.venv/bin/python -m pytest tests/rewind -q

# 3. the Bevy CLI's own suite (15 cases, in the last-mile repository)
cd ~/last-mile && cargo test --release -p lm-tools --test cli
```

The script needs the world's ledger (read read-only — it is live and is
never locked) and the `lm` binary; the Bevy part plays and replays three
headless rounds, which takes about a second of CPU. The results are written
as JSON next to the script and are committed.

---

## 6. Files

| path | what it is |
|---|---|
| `core/rewind/selection.py` | the language: the parser, the evaluator, the reasons |
| `core/rewind/ledger.py` | the readers: the world's ledger, the core's ledger, a round log |
| `core/rewind/fork.py` | fork-at-point: the rewind point, the branch it cuts |
| `core/rewind/replay.py` | replay-kept: the ops, the merge, the parked questions |
| `core/rewind/report.py` | kept / dropped / parked, with the reasons |
| `core/rewind/bevy.py` | the `lm` adapter, and the keep/drop proof |
| `core/rewind/README.md` | the package's own README |
| `tests/rewind/` | 33 tests |
| `docs/lab/rewind-select-scripts/exp_rewind_select.py` | the measurement script |
| `docs/lab/rewind-select-scripts/results/rewind-select.json` | the numbers as the script wrote them |
| `last-mile`: `crates/lm-tools/src/main.rs` | `lm dump`, `lm branch --drop` (branch `rewind-select/dump-and-drop`, local, not pushed) |
