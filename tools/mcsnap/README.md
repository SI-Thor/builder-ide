# `tools/mcsnap` — snapshot and restore a live Paper world, with a manifest

Build #1 of [`docs/design/vibecode-in-world.md`](../../docs/design/vibecode-in-world.md)
(§6.1 row 6): the **world snapshot / restore** primitive. Everything in §2 that
does not run on the Bevy world depends on it — the rewind, the scrubber's
world view, the cherry-pick's preview, the auto-pause's undo.

The measurement is [`docs/lab/exp-world-snapshot.md`](../../docs/lab/exp-world-snapshot.md).

## What it does

| command | what it does |
|---|---|
| `snapshot` | stop the world's writing, flush it to disk, copy it, and write a manifest that says what the moment was |
| `restore` | put a snapshot back **by swap** — the world it replaces is moved aside, never deleted — and check every restored file by its hash |
| `verify` | check a snapshot against its own manifest |
| `list` | the snapshots in a store, with the ledger row each one sits behind |
| `server start\|stop\|status` | the private server this build runs against |
| `rewind` | the join to the world's story: a rewind point on the ledger, the nearest snapshot at or before it, and the work that can be put back |

## The snapshot

The order of operations, and why each is where it is:

1. `save-off` — the server stops writing the world on its own schedule;
2. `save-all flush` — every chunk is written to disk **now**, and the server
   waits for it: this is the moment the world's state stops moving;
3. the copy — the world's files, hashed as they sit in the snapshot;
4. `save-on` — the writing goes back on, **even when the copy failed**.

The copy is a plain file copy, not a hard link: a hard link would let the
restored world's writes reach back into the snapshot and change it.

## What is copied, and what is left behind

A Paper world directory is not just the region files. The manifest lists
every file with its size and its sha256, and it lists the files that were
left behind with the reason:

| section | what it holds |
|---|---|
| `level` | `level.dat` — the world's time, seed, spawn and data version |
| `region` | the blocks, as `r.*.mca` region files |
| `entities` | the entities, as region files |
| `poi` | the points of interest, as region files |
| `dimension-data` | each dimension's own data (maps, raids) |
| `world-data` | the world's own data: the scoreboard, the stopwatches, the boss events, the random sequences |
| `datapacks` | the datapacks the server ships |
| `players` | the players' data, advancements and statistics |
| `config` | the dimension's Paper settings (`paper-world.yml`) |
| `unclassified` | a file this tool did not recognise — **copied anyway**, and listed |

Left behind on purpose: `session.lock` (the server's own lock on the world
while it runs — it holds the server's pid) and `level.dat_old` (the previous
`level.dat`, already superseded).

## The manifest

The fields, and why each is there:

* `snapshot_id`, `taken_at` — what it is and when it was taken;
* `server` — the Paper and Minecraft versions it was taken under;
* `world` — the seed, the tick (`level.dat`'s `Time`), the time of day
  (`DayTime`), the data version and the spawn: the world's own clock is
  what makes a snapshot *a moment* rather than a directory of bytes;
* `ledger` — the world ledger and the highest `seq` it held: the join
  between the world's **state** and the world's **story**;
* `files` — every file with its size, its sha256 and its mtime;
* `skipped` — every file left behind, with the reason;
* `sections`, `totals` — how much of the snapshot is blocks and how much is
  players;
* `timing` — how long each step took.

The verification checks a restored tree **by content**: a file of the right
size and the wrong bytes fails.

## The private server

The live world is a Paper server on 25565 with a human in it. This build
never touches it. What it runs instead is a **copy**: the same Paper jar and
the same JDK — read from the live server's own `version_history.json`, never
downloaded — on port 25610, bound to 127.0.0.1, in offline mode, with its
own world directory grown from the same seed (`agent-world`).

Geyser and Floodgate are moved out of the copy's `plugins/`: the live server
already owns the Bedrock port, and two servers cannot both own it.

Every run goes through `thor-admit run` with an honest peak.

## The bots

`bots/builder.js` places blocks and records two things: the **placement
journal** (the coordinates, one JSON line per placement) and the **world
ledger** (a row per placement in the live world's own `audit` schema, written
live with `node:sqlite`). `bots/replay.js` puts the kept placements back.

```bash
NODE_PATH=~/lm-wt/agent-world/bots/node_modules \
  ~/lm-wt/agent-world/runtime/node/bin/node tools/mcsnap/bots/builder.js \
  --name Builder1 --journal mc-snap/placements.jsonl \
  --ledger mc-snap/ledger.sqlite3 --count 6 --block stone --offset 0
```

## The join to the world's story

`core/rewind/snapshot.py` (the core's vocabulary, not this tool's) maps a
rewind point on the world ledger to the nearest snapshot at or before it,
and says which of the kept work can be put back:

* **re-appliable** — a block placement, which mineflayer can make again;
* **recorded** — a row the ledger already keeps and the world does not hold
  (a judge's verdict): nothing to replay;
* **lost** — a mined block, a killed mob, the time of day moving on: the
  restore takes these away and nothing puts them back.

The coordinates come from the **placement journal**, because the ledger's
rows do not carry them: a `tile.played` row says which skill ran on which
bot, not what it did to the world. A row with no journal entry is lost, and
the plan says so rather than guessing.

## Running it

```bash
cd ~/lm-wt/world-snapshot
.venv/bin/python -m mcsnap snapshot --server-dir mc-snap --out mc-snap/snapshots \
    --ledger mc-snap/ledger.sqlite3
.venv/bin/python -m mcsnap list --out mc-snap/snapshots
.venv/bin/python -m mcsnap verify --snapshot mc-snap/snapshots/<id>
```

The environment is `uv venv` + `uv pip install -e ".[dev]"`; the package
itself needs **only the standard library**.
