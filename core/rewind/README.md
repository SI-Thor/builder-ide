# `core/rewind` — "rewind to here, keep these"

Build #5 of [`docs/design/vibecode-in-world.md`](../../docs/design/vibecode-in-world.md)
(§2.5): the **selection** step the cherry-pick was missing. The merge exists
(`core/recipe/merge.py`, three-way at entry granularity, conflicts park a
question); the fork exists (the recipe store's branches, and `lm branch` on
the Bevy side); what was missing was a way for a human to say *which of the
ledger's events are the ones to keep*.

The measurement is [`docs/lab/exp-rewind-select.md`](../../docs/lab/exp-rewind-select.md).

## What it is

```python
from core.rewind import parse, select, read_world_ledger

ledger = read_world_ledger("/home/caseydigennaro/lm-wt/agent-world/runtime/world-ledger.sqlite3")
result = select(ledger, parse("actor = Kite and kind in (tile.played, tile.authored)"))

result.kept_seqs      # the events to keep
result.reason_for(42) # why an event was dropped
```

And the cherry-pick over the canon:

```python
from core.rewind import cherry_pick, parse, point_at_version

pick = cherry_pick(
    store,                                   # a core.recipe.store.RecipeStore
    point=point_at_version(store, "ver_0001"),
    selection=parse("actor = magnus"),
    actor=owner,
)
print(pick.report().render())
```

## The selection language

One expression over a ledger's rows:

```
actor = Kite and kind in (tile.played, tile.authored)
at >= 2026-11-01T05:00:00Z and at < 2026-11-01T07:00:00Z
not (kind = judge.verdict) or verdict = accept
id = skill_14fd7774a036
```

| field | what it reads |
|---|---|
| `actor` | who wrote the row (a seat, a judge, an agent) |
| `agent` | who the row is *about* — not always the actor |
| `kind` | the event kind (`tile.played`, `judge.verdict`, …) |
| `id` | the tile, skill or entity id |
| `verdict` | the row's verdict or outcome |
| `at` | the time — epoch seconds, or the tick of a round log |
| `seq` | the ledger's own row number |

| operator | meaning |
|---|---|
| `=` `!=` | equal, not equal (a list on the right means "one of") |
| `in` | one of a list |
| `contains` | the text contains |
| `>=` `>` `<=` `<` | numeric comparison (`at` and `seq` only) |
| `and` `or` `not` `( )` | combine clauses |

Every row the selection does not keep carries **the reason it was dropped**,
and the report prints it. A parse error names the place; a refused
comparison names the field.

## What it owns

| module | what it owns |
|---|---|
| `selection.py` | the language: the parser, the evaluator, the reasons |
| `ledger.py` | the readers: the world's ledger, the core's ledger, a round log |
| `fork.py` | fork-at-point: the rewind point, the branch it cuts |
| `replay.py` | replay-kept: the ops, the three-way merge, the parked questions |
| `report.py` | what was kept, what was dropped, what was parked, and why |
| `bevy.py` | the `lm` CLI, and the keep/drop proof on a round log |

## How it connects to the rest

* **The recipe store** (`core/recipe/store.py`) — the fork is a branch of its
  canon; the merge is its `three_way_merge`; a parked question is a
  `question.parked` event in its ledger.
* **The recipe edits** (`core/recipe/edits.py`) — `apply_ops` replays the
  kept work onto the fork; `diff_recipes` turns the merged document back
  into ops, so the cherry-pick is a normal edit and earns its pre-flight.
* **The world's ledger** (`agent-world/runtime/world-ledger.sqlite3`) — read
  read-only, never locked.
* **The Bevy world** (`last-mile`) — through the `lm` CLI: `run`, `replay`,
  `diff`, `dump`, `branch --drop`.

## What it does **not** do

* It does not move the canon's head. The cherry-pick lands on a **fork**;
  moving `main` is the owner's separate step (`store.apply_branch`).
* It does not remove work the canon already has. The merge is *with* main:
  the kept work comes across, and what main already holds stays. Removing
  main's own history is not a fork's business.
* It does not delete anything: the ledger keeps every row it had, the canon
  keeps every version, and the fork is a branch beside them.

## Running the tests

```bash
cd ~/lm-wt/rewind-select
.venv/bin/python -m pytest tests/rewind -q
```

33 tests. The four in `test_bevy.py` need the `lm` tool on the `PATH` and
are skipped without it:

```bash
export PATH=$HOME/last-mile/target/release:$PATH
```

The environment is `uv venv` + `uv pip install -e ".[dev]"`; the package
itself needs only `pydantic` (through `core.records`) and the standard
library.

## The world snapshot: a rewind for a world that cannot be forked

The Bevy world is rewound by forking at a tick. A live Paper server cannot
be: there is no second implementation of a Paper world to compare against,
so a rewind there has to be **snapshot-based** — put the world's files
back, then put back the work that came after.

`core/rewind/snapshot.py` is that join. A rewind point on the world ledger
maps to the nearest snapshot at or before it (by the snapshot's recorded
ledger `seq`), and the work between them is classified:

| kind | what it is | what happens to it |
|---|---|---|
| **re-appliable** | a block placement by a bot | put back with mineflayer, given the coordinates and the block name |
| **recorded** | a row the ledger already keeps and the world does not hold (a judge's verdict, a skill authored or retired) | nothing to replay — the ledger *is* the record |
| **lost** | a mined block, a killed mob, an item that despawned, the time of day moving on | the restore takes it away and nothing puts it back |

The coordinates come from a **placement journal** — the world mutations the
bots recorded, with their coordinates — because the ledger's rows do not
carry them: a `tile.played` row says which skill ran on which bot, not
what it did to the world. A journal entry that records the ledger row's
own `seq` is joined **exactly**; a journal without one is joined by time.

The tool that takes and puts back the snapshots is
[`tools/mcsnap/`](../../tools/mcsnap/); the measurement is
[`docs/lab/exp-world-snapshot.md`](../../docs/lab/exp-world-snapshot.md).
