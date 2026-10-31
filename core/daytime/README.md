# The daytime world

The core's **daytime lane**: the part of the product that is awake while you
are not. Between sessions the world keeps living under the same recipe — the
light moves through the day, a builder tidies the props, the plants grow by a
step — and in the morning there is one line in the report that says what
changed while nobody was watching.

This package is the seat that runs it. It is deliberately small and
deliberately honest:

* **the ledger is the world's only state** — there is no file the room lives
  in. The room is what you get when you fold the audit log, so it survives a
  `kill -9` and it can be rebuilt at any time (§1.0);
* **the world is reproducible** — the same recipe and the same tick count
  reconstruct the same world *exactly*. That is arithmetic, not a promise:
  `world_at(recipe, version_id, tick)` is a pure function;
* **the daytime yields to the night** — the night is the work. When the night
  lane is busy the daytime stands down, and the stand-down is in the log,
  because the edges are the story;
* **it is cheap** — a tick is a few small events and a few microseconds of
  CPU. It has a budget, and admission is before spend (§5.5).

It is built against **core-spec v2** (`docs/design/core-spec.md`) and plan
item 19 (`docs/plan.md`). B3 — *the always-on daytime world* — is **not
decided**: the whole lane is behind one setting and is **off by default**
(`Settings.daytime_enabled`).

## What it does, in one day

1. **Stand down if the night is working.** The night lane's state is read out
   of the log (a `night.started` with no `night.stopped` yet), so the daytime
   never competes with the work.
2. **Open the room** on the recipe version — one room, one clock, at tick
   zero — and write that to the log.
3. **Tick.** The clock advances one tick; the light moves; the things in the
   room move on their own schedules. Each small change is one `day.change`
   event.
4. **Stop at the bar.** The budget is folded out of the log (ticks run, wall
   minutes spent) and admission happens before the spend: a tick the budget
   cannot cover is not run and cut afterwards — it is not run at all, and a
   `day.yielded` says why. The defaults are **24 ticks** (one day of the
   clock) and **1 wall-minute** a day; see *What it costs* below.
5. **Say so in the morning.** The report's "while you were away" section is
   the daytime ticks between one night stopping and the next one starting:

   ```
   12 daytime ticks while you were away · the light went night → day ·
   terrain.harbor grew 4× · harbor.crates was tidied 3×
   ```

## What moves, and how often

The recipe decides. No behaviour is invented for an entry that does not ask
for it:

| Recipe entry kind | Behaviour in the room | How often |
|---|---|---|
| `prop_set` | a builder tidies it | every 2–4 ticks |
| `terrain` | its plants grow by a step | every 2–4 ticks |
| `light` | says what hour the room wakes at | — |
| anything else | it sits still | — |

The period and the phase come from the entry's **seed** (its own, else the
recipe's), so two entries never fall into lockstep and the schedule is
reproducible from the recipe alone. The light is an integer triangle over a
24-tick day — the same number on every machine, or the world would not be
reproducible.

## What it costs

Measured on the box, with the box's state beside the number (CLAUDE.md):
`thor`, aarch64, NVIDIA Jetson AGX Thor Developer Kit, 14 Neoverse cores,
load average 25.36 / 20.59 / 21.16 (the box was busy with other work).

| What | Number |
|---|---|
| one full day of the clock (24 ticks) | **0.245 ms** median of 20 runs (min 0.240, max 1.845) |
| one tick | 0.0102 ms |
| rows written to the shared ledger in a day | 63 (1 open, 24 ticks, 38 changes) |

Reproduce it:

```bash
.venv/bin/python - <<'PY'
import time, statistics
from core.daytime import DayRunner
from core.daytime.ledger import InMemoryLedger
# ... a recipe with a prop_set and a terrain entry ...
runs = []
for _ in range(20):
    ledger, runner = InMemoryLedger(), None
    runner = DayRunner(ledger, recipe, "ver_0192")
    t0 = time.perf_counter()
    for _ in range(24):
        runner.tick()
    runs.append((time.perf_counter() - t0) / 60.0)
print(statistics.median(runs) * 1000, "ms for 24 ticks")
PY
```

So the **tick ceiling binds first**: the budget's 24 ticks a day is the real
limit, and its one wall-minute ceiling is a backstop four orders of magnitude
above the measured cost. The daytime is cheap because it is arithmetic — it
renders nothing and holds no model.

## Running the tests

Everything runs from the worktree's own venv:

```bash
cd ~/lm-wt/daytime-world

.venv/bin/python -m pytest -q                     # the whole suite
.venv/bin/python -m pytest -q tests/daytime/      # this seat alone
```

The seat's own tests are in `tests/daytime/`:

| File | What it holds |
|---|---|
| `test_events.py` | the closed event set carries the daytime group, and every seat's mirror agrees |
| `test_world.py` | the world's arithmetic: the room, the light, the schedules, reproducibility |
| `test_projection.py` | the fold of the log reproduces the arithmetic, and the lane reads the night's state out of the log |
| `test_runner.py` | the tick, the budget, and the yield to the night |
| `test_report.py` | the "while you were away" line |
| `test_spine.py` | the spine's own doors: the setting, the one ledger, the morning report |

A room, folded from nothing, in five lines:

```python
from core.daytime import DayRunner, world_at

world = world_at(recipe, "ver_0192", 12)   # the room, from arithmetic
runner = DayRunner(ledger, recipe, "ver_0192")
runner.tick()                              # one tick, into the log
runner.world()                             # the room, from the log — the same room
```

## The seams it stubs

| Seam | What it answers | Stand-in |
|---|---|---|
| **the ledger** (`ledger.py`) | append an event; read it back | `InMemoryLedger`, `SQLiteLedger` — the spine's own store replaces it as a constructor argument (`core/svc/daytime.py::SpineDayLedger`) |
| **the recipe** | what the room contains and what moves in it | a `core.records.Recipe` handed in — the daytime never writes to the recipe store |
| **the lane** (`runner.py`) | is the night working right now? | read out of the log; a `lane_busy` callable overrides it for a live lane |
| **the clock** | what time is it? | the ledger's own clock; the daytime's *world* clock is a tick count, not a timestamp |

## How it connects to the core

* **The log is the contract.** The daytime writes four audit event types and
  nothing else. §1.8's set is closed, so this was a schema change: the four
  types live in `core.records.EVENT_TYPES` (the one copy) and are mirrored
  in `core/night/events.py` and `core/recipe/events.py`, with a pin in
  `tests/daytime/test_events.py` holding all three in step.

  | Type | What it says |
  |---|---|
  | `day.world.opened` | the room opens on a recipe version, at tick zero |
  | `day.tick` | the clock advances one tick, and what it cost |
  | `day.change` | one small change in the room (light, tidy, grow) |
  | `day.yielded` | the daytime stood down — for the night, or for its budget |

* **The spine owns the one ledger.** `core/svc/daytime.py` is the spine's own
  door: `SpineDayLedger` satisfies the seat's small `Ledger` protocol with
  the spine's SQLite store, the way `SpineRecipeLedger` does for the recipe
  store. Every `day.*` row lands in the same audit log as the night's, and
  folds into the same projections.

* **The morning report is a fold.** The "while you were away" section is read
  out of the same log as the status line and the tally — never narrated by
  whoever is awake to write it (§3.4).

* **The night keeps the priority.** The night is the work; the daytime is the
  room that breathes between sessions. The lane's first act is to stand down
  when the night lane is busy, and its budget is a ceiling on the rest.

* **One setting.** `Settings.daytime_enabled`, default **False**. Nothing
  about the daytime happens — not one row is written — while it is off, and
  the report reads the same log either way.

## The files

| Module | What it owns |
|---|---|
| `events.py` | the closed event set (re-exported) and the daytime group; the change vocabulary and the entry-kind → behaviour map |
| `models.py` | the records: `DayWorld`, `DayRoom`, `DayObject`, `DayChange`, `PlannedEvent` |
| `world.py` | the world's arithmetic: `world_at`, the light's arc, the schedules, `apply_change` |
| `plan.py` | the plan for a tick: the changes it makes, in order |
| `projection.py` | the fold: the world, the day's counters, and the day that came before each night |
| `runner.py` | the tick, the yield, the budget |
| `budget.py` | the cheap budget: ticks and wall minutes |
| `ledger.py` | the ledger seam: `append` / `events` / `last_seq` |
| `report.py` | the "while you were away" line, and the closed vocabulary of verbs it uses |

## What it does not do yet

* **It does not render.** The daytime writes state, not meshes. A render is
  the night's job, and the daytime's budget says so.
* **It does not decide anything.** The daytime is not an agent: it applies the
  recipe's own schedule. Who *is* the builder that tidies the crates is not
  settled — the counts are there, the actor is the core.
* **It does not run on a schedule yet.** The tick is something a caller asks
  for (`DaytimeService.tick`); nothing yet calls it on a timer.
* **B3 is undecided.** The lane is off by default, and the plan item's own
  wording — "one room, one clock" — is deliberately the whole of the scope.
