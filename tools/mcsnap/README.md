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

## What the measurement found

The measurement is [`docs/lab/exp-world-snapshot.md`](../../docs/lab/exp-world-snapshot.md).
These are the things that cost the most to find, and that the next person
would otherwise have to find again:

**Paper's RCON answers carry a packet type.** The protocol description of
the RCON packet does not mention it, and a client that reads the payload
from `body[4:]` gets an **empty string** for every command. The payload
starts at `body[8:]`: length, request id, packet type, payload.

**The jar is not the newest one.** The runtime holds two Paper jars, and
the newest by mtime is *not* the one the live world was written by. The
build is read from the live server's own `runtime/paper/version_history.json`
(`26.1.2-74-e4e17fc` → `paper-26.1.2-74.jar`). Starting the private server
with the wrong one crashes on the dimension migration.

**`level.dat` holds its fields one level down.** The root compound has a
single key, `Data`, and everything else is inside it. Read one level too
high and the tick, the spawn and the data version all come back zero.

**Two facts are the server's, not the world's.** In this Paper version
`level.dat` carries no `DayTime` and no seed: the day is a **timeline**
(`time query day` answers *"Timeline minecraft:day is at 5039 tick(s)"*)
and the seed is asked of the server (`seed`). The manifest records both,
and says where they came from.

**The restore has to move the sibling worlds aside.** `world_nether` and
`world_the_end` left next to the restored world make Paper try to migrate
them into it at startup, and it dies with *"Refusing to overwrite existing
migrated file"*. The restore reports what it moved.

**A bot has to be an operator, and it has to be one *after* the restore.**
A bot that is not an operator cannot `/tp`, so it stands where it spawned
and its placements are out of reach — and the server refuses an
out-of-reach placement **without answering**, so the placement times out
after five seconds with *"Server did not answer the placement"*. A restore
restarts the server, and a server that starts reads its operators from
`ops.json`, so an operator given at runtime is gone with the old server.

**Three rules the bots follow, each of them a message from the server:**

* the item to equip is the one **in the inventory**, not the one in the
  registry — the registry item has no slot, and mineflayer's equip uses the
  slot to decide what to click;
* the bot aims before it places: mineflayer's own `placeBlock` does a
  *smooth* look first, and the rotation packets that come with it are what
  the server refuses (*"Invalid move player packet received"*) — the bot is
  dropped for it. `forceLook: true` is the instant look;
* a bot that is teleported **once** falls most of the way to the ground
  while the chunk arrives, and a block eight metres up is then out of
  reach. It is teleported twice: once to load the chunk, once to be back at
  the target's height.

**A block the client has not been told about is not an empty block.** A
probe that reads a block before its chunk has arrived reads *unknown*, and
calling that "air" says a block is missing when the client has simply not
seen it yet. The probe waits for the block to become known.

**The journal carries the ledger's `seq`.** A placement journal entry that
records the ledger row it wrote makes the join to the ledger **exact**;
without it the join is by time, and a ledger row with second resolution
can land on the wrong placement. See `core/rewind/snapshot.py`.
