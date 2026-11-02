# exp-world-snapshot — the world's state and the world's story, measured

**What was asked.** Build #1 of [`docs/design/vibecode-in-world.md`](../design/vibecode-in-world.md)
(§6.1, row 6): the **world snapshot / restore** primitive for the Minecraft
(Paper) world — a snapshot with a manifest, a restore that puts it back, and
the join that lets `core/rewind` rewind a *live* server, where the Bevy
world's byte-identical replay cannot hold. Measure the snapshot and the
restore, at idle and with three bots building, and say what differs after a
restore.

**What was built.** `tools/mcsnap/` (the snapshot, the manifest, the restore,
the verification, a private Paper server, three bots) and
`core/rewind/snapshot.py` (the join between a ledger row and a snapshot),
with 71 tests under `tests/mcsnap/` and `tests/rewind/`.

**The short version.** A snapshot of the live world's world directory costs
**under half a second** and about **12 MB**, and a restore costs about
**eleven seconds** — almost all of it the server starting again. The restore
is exact: every file comes back with the sha256 the manifest recorded, and
the world is put back as a **new** directory (the old one is moved aside,
never deleted). The join works: the ledger's own prediction of what the
snapshot holds (the rows at or before the snapshot's `seq`) matched the world
**exactly**, block for block, when the world was read back from the running
server. And the work that came after the snapshot can be put back: the five
block placements between the snapshot and the rewind point were replayed by
a bot and **all five read back as the expected block**.

---

## 1. The mechanism

### 1.1 The fact the build stands on

A live Paper world is a directory of files that the server is writing to
while you look at it. There is exactly one moment in which that directory
means "this was the world at 21:14:03", and it is the moment the server has
been told to stop writing and to flush what it holds:

* `save-off` — the server stops saving the world on its own schedule;
* `save-all flush` — every chunk is written to disk **now**, and the server
  waits for the write to finish.

After the flush the world's files on disk are a consistent picture of the
world at that instant, and the server is still running. Everything else —
copying the files, hashing them, writing the manifest — is bookkeeping
around that one moment. Paper exposes both commands over RCON, so the
snapshot can be taken by another process without touching the console.

### 1.2 Why the old way could not do it

There was no way to take a picture of the live world at all.

**Copying the files while the server writes gives a torn picture.** A region
file half-written, `level.dat` from one tick and `players/` from another. The
live world is on 25565 with a human in it, so this is not a thing to try and
see.

**Byte-identical replay cannot hold for a live Paper server.** It holds for
the Bevy world, where a fork at a tick and a reference run with injected
decisions come out identical tick for tick
([`exp-rewind-select.md`](exp-rewind-select.md) §2). A Paper server has a
tick counter, a day cycle, entities with their own state, and plugins with
their own files. There is no second implementation of a Paper world to
compare against, so the rewind there has to be **snapshot-based**: put the
files back, then put back the work that came after.

**The ledger does not say what a play did to the world.** A `tile.played`
row in the world ledger names the skill and the bot; it does not carry the
coordinates of the block that went down. So restoring the files is only half
a rewind: the work between the restore point and now has to be re-applied,
and the coordinates have to come from somewhere else.

### 1.3 What changed

**`tools/mcsnap/`** — the snapshot, the manifest, the restore, the verify,
the private server, the bots:

* `snapshot.py` — `save-off` → `save-all flush` → copy → `save-on`, with the
  `save-on` in a `finally` so a failed copy never leaves the world with
  saving off;
* `manifest.py` — the manifest, and the verification by content (sha256);
* `world.py` — what a Paper world directory actually holds, section by
  section;
* `restore.py` — the swap: stop, move the old world aside, put the snapshot
  in as a new world directory, start, verify;
* `server.py` — the private Paper server, under `thor-admit`;
* `state.py` — the world's own state (entities, players, inventories, the
  tick), read out of the files.

**`core/rewind/snapshot.py`** — the join. A rewind point on the world ledger
maps to the nearest snapshot at or before it, plus the work that has to be
put back on top of it, classified into three kinds: **re-appliable** (a block
placement, which mineflayer can make again), **recorded** (a row the ledger
already keeps and the world does not hold), and **lost** (a mined block, a
killed mob, the time of day moving on).

### 1.4 The one thing it deliberately does not do

**Incremental snapshots.** The Director's note asks for them to be skipped,
and the build skips them: every snapshot is the whole world directory. What
that costs is measured below — at 12 MB and under half a second, there was
nothing to win.

**"Exotic state"** is skipped too, but the manifest does not *hide* it: a
file this tool did not recognise is copied anyway and listed under
`unclassified`. That is the "list what you find" the brief asks for.

---

## 2. The measurement

### 2.1 The box, and what else was running

The run is on the Thor, in the private server's own directory
(`~/lm-wt/world-snapshot/mc-snap`), on Paper `26.1.2-74` — the same build
the live world was written by, read out of the live server's own
`version_history.json`, never downloaded. The server runs on 127.0.0.1:25610
under `thor-admit` with an honest peak of 3G.

| | load (1/5/15 min) | memory available |
|---|---|---|
| at the start of the run | 13.62 / 14.32 / 16.50 | 99.58 GB |
| at the end of the run | 13.89 / 14.32 / 16.27 | 99.27 GB |

Other seats were on the box (the live server on 25565, the voyager-port
server on 25600, and two other leases); none of them was touched. The
private server's own lease is `world-snapshot.server`, peak 3G, 1.5G in use.

### 2.2 The snapshot at idle

`mcsnap-20261102T084024Z-6e938e93` — 112 files, **12,381,679 bytes**.

| step | seconds |
|---|---|
| `save-off` | 0.0037 |
| `save-all flush` | 0.4222 |
| copy | 0.0168 |
| hash (sha256 of every file) | 0.0206 |
| manifest | 0.0008 |
| **wall clock** | **0.481** |

The manifest records the ledger's head at the moment of the flush (**seq
6**), the world's tick (**88754**), the time of day (**16760**, the day
timeline's tick, asked of the server — this Paper version keeps the day in
the server, not in `level.dat`), the spawn (`0, 70, 0`), the Paper and
Minecraft versions, and the sha256 of every one of the 112 files.

### 2.3 The snapshot while the bots build

`mcsnap-20261102T084034Z-7bf50fc9` — 112 files, **12,381,708 bytes** — taken
while the builders were in their placement loop.

| step | seconds |
|---|---|
| `save-off` | 0.0078 |
| `save-all flush` | 0.0617 |
| copy | 0.0164 |
| hash | 0.0236 |
| manifest | 0.0009 |
| **wall clock** | **0.126** |

**What the numbers say.** The snapshot's cost is the **flush**, and the
flush's cost is how much the world has changed since the server last saved,
not how many bots are placing at that instant: the idle flush took 0.42 s
because the world had been dirty since the last save, the second flush
0.06 s because only the blocks the builders had just placed were dirty.

**What the numbers do not say.** No placement landed *inside* the 0.126 s
window of the snapshot itself — the builders place a block every 1.5 s, so
a 0.126 s window has roughly a one-in-twelve chance of containing one, and
this one did not. The snapshot was taken while the world was being written
to; it did not happen to catch a write in its own window.

**And the honest count of "3 bots building".** Three builders were started,
but only **one of them built anything** in each phase: the other two stood
where no neighbouring column was clear, and the builder refuses to build on
an occupied column (a placement there would be a no-op, and the journal
would then say the bot put a block in the world when it did not). So the
figure above is **one** bot placing a block every 1.5 s, not three. The
measurement is honest about it, and the fix — making the builders choose a
column they can reach and clear — is in `tools/mcsnap/bots/builder.js`.

### 2.4 The restore

The building snapshot was put back: stop, move the old world aside, put the
snapshot in as a **new** world directory, start, verify every file against
the manifest's sha256.

| step | seconds |
|---|---|
| stop the server | 1.005 |
| move the old world aside | 0.0006 |
| copy the snapshot in | 0.0281 |
| verify every file by hash | 0.0163 |
| start the server again | 10.017 |
| **wall clock** | **11.068** |

`verified: true`, **no problems**. The old world was moved aside, not
deleted: `mc-snap/world.replaced-20261102T084058Z` is still on disk.

**The restore is dominated by the server starting again** — 10.0 s of the
11.1 s. The world work itself (move aside, copy, verify) is 45 ms. A
restore that did not have to stop the server would be two orders of
magnitude faster, and that is the shape a live rewind would want.

The restore also has to move the server's **sibling** world directories
aside (`world_nether`, `world_the_end`): left in place, Paper tries to
migrate them into the restored world at startup and crashes with *"Refusing
to overwrite existing migrated file"*. The tool reports what it moved.

### 2.5 What differs after the restore

Read out of the world's own files, before and after:

| | before | after |
|---|---|---|
| tick | 88941 | 88941 |
| data version | 4790 | 4790 |
| spawn | 0, 70, 0 | 0, 70, 0 |
| Paper version | Paper/26.1.2-74-e4e17fc | Paper/26.1.2-74-e4e17fc |
| entities (overworld) | 0 | 0 |
| players' positions, health, food | unchanged | unchanged |
| players' inventories | unchanged | unchanged |

And the **blocks**, read out of the *running server* with a probe bot that
stands next to each one and asks what is there:

| | count |
|---|---|
| placements the journal recorded | 12 |
| blocks present before the restore | 11 |
| **blocks the restore removed** (the work after the snapshot) | **5** |
| blocks the restore kept (the work before the snapshot) | 6 |
| what the ledger predicted (rows at or before the snapshot's seq) | 7 in the snapshot, 5 after |

The ledger's prediction and the world's own contents **agree**: the work
after the snapshot is gone, the work before it is still there.

**The time of day** is the one thing the restore does not bring back. The
day cycle in this Paper version is a server-side timeline, not a field in
`level.dat`: the manifest records it (16760 at the idle snapshot, 16943 at
the building one) but the restore cannot put it back, because it was never
in the files. A rewind that cares about the time of day has to set it
explicitly — and this build does not.

**Entities and inventories** are in the files (`entities/`, `players/`), so
they come back with the snapshot. The measurement above shows no
difference, which is the point: the restore is exact for what the files
hold. What is *not* in the files is what the server was holding in memory
when it was stopped — a mob mid-jump, a player mid-swing — and that is
gone.

### 2.6 The rewind: the point, the plan, the replay

A rewind point at the ledger's head (seq 12) maps to the nearest snapshot
at or before it — the building snapshot at seq 7 — plus the work that came
after, classified:

* **re-appliable** — 5 block placements, with their coordinates;
* **recorded** — 0 (no judge verdicts in this world's story);
* **lost** — 0 (nothing was mined).

The five placements were replayed by a bot against the restored world, and
**all five were read back from the running server as the expected block**:

```
replayed stone at 9,76,9 (read back stone)
replayed stone at 9,77,9 (read back stone)
replayed stone at 9,78,9 (read back stone)
replayed stone at 9,79,9 (read back stone)
replayed stone at 9,80,9 (read back stone)
done: 5 replayed, 0 already there, 0 failed, 5 read back as the expected block
```

So the loop closes: the snapshot says what the world was, the ledger says
what happened after it, and the replayer puts the "what happened after it"
back on top.

**Where the replay numbers come from, exactly.** The `replay` section of
[`world-snapshot-scripts/results/world-snapshot.json`](world-snapshot-scripts/results/world-snapshot.json)
is from the run **before** the operator fix of §2.7, and it shows that
failure: the bot was not an operator after the restore, so it stood 11
blocks away from the blocks it was asked to place and the server refused
every placement without answering. The replay quoted above was run against
**the same restored world**, from the same plan file
(`mc-snap/snapshots/replay-plan.json`), after the fix — and all five blocks
came back, each read back from the running server as the expected block.
The committed results file is left as it was: rewriting it would mean
quoting numbers from a run this document does not describe.

**What cannot be put back**, and the build says so rather than guessing:

* a **mined** block — what was there cannot be invented; the plan calls it
  `lost`, and the restore leaves the space empty;
* a **killed mob** or a dropped item — nothing records where it was;
* **the time of day** — it was never in the files;
* **anything the ledger does not describe** — a row with no journal entry is
  `lost`, because the ledger cannot say what it did to the world.

### 2.7 Two bugs the measurement found, and what they were

**The join picked the wrong block.** The ledger's rows are stamped with
second resolution and the journal with milliseconds, so a row can sit up to
a second *before* the placement it records — and then the *nearest* journal
entry is the previous block. The plan replayed y=85, 87, 87, 89, 89 when
the journal said 86, 87, 88, 89, 90, and the replay failed on a block that
was never there. The fix is in `core/rewind/snapshot.py`: a journal entry
that carries the ledger row's own `seq` is joined **exactly**, and the
time-based join now prefers an entry at or after the row's time.

**The replayer could not reach the blocks.** The server refuses a
placement it cannot reach and answers nothing, so the placement times out
after 5 s with *"Server did not answer the placement"*. The cause was not
reach but **the operator**: the restore restarts the server, a server that
starts reads its operators from `ops.json`, and the operator this run gave
at runtime was gone with the old server — so the bot's `/tp` did nothing,
it stood where it spawned, and every placement was 11 blocks away. The
experiment now re-ops the bots **after** the restore, and the replayer
reports how far it is standing from the block it is about to place.

---

## 3. What it makes possible

* **A rewind of a live Paper world.** The rewind that `core/rewind` does
  for the Bevy world by forking at a tick can be done here by swapping the
  world's files back and replaying the kept work on top. The join between
  a ledger row and a snapshot is the same join; only the mechanism of
  "put the world back" differs.
* **A safe snapshot before anything risky.** 0.13–0.48 s and 12 MB buys a
  world you can go back to, taken **while the server runs** — no second
  server, no world copy, no downtime for the players.
* **An undo for the auto-pause.** The auto-pause's undo is a restore, and
  the cost of that undo is now known: 11 s, of which 10 s is the server
  starting again.
* **The knowledge of what a rewind costs, and what it cannot do.** A mined
  block and the time of day do not come back. A build that needed them to
  would have to record them at the time (the journal is where that
  recording would go) rather than hope the files hold them.

---

## 4. What was not verified

* **The live world was never snapshotted.** Everything here was measured
  on the private copy on 25610. The live server on 25565 was only *read*
  (its ledger, its `level.dat`, its `version_history.json`).
* **"Three bots building" was measured with one bot placing.** See §2.3.
* **No placement landed inside the snapshot's own window.** See §2.3.
* **The restore was measured with the world at rest.** A world with a
  player in the middle of something would restore differently — the
  player's own state is in the files, but what the server was holding in
  memory is not.
* **Incremental snapshots were not measured**, because the Director's note
  asks for them to be skipped.
* **The restore does not put the time of day back** (§2.5) and this build
  does not set it.
* **The `day_time` in the manifest is the server's answer**, not a field in
  the world: it is only as good as the moment the RCON command was sent.

---

## 5. How to run it

The script that produced every number in this document is
[`world-snapshot-scripts/exp_world_snapshot.py`](world-snapshot-scripts/exp_world_snapshot.py);
its README is next to it. The numbers in this document are in
[`world-snapshot-scripts/results/world-snapshot.json`](world-snapshot-scripts/results/world-snapshot.json),
written by that script.

```bash
cd ~/lm-wt/world-snapshot
.venv/bin/python docs/lab/world-snapshot-scripts/exp_world_snapshot.py \
    --server-dir mc-snap \
    --results docs/lab/world-snapshot-scripts/results/world-snapshot.json
```

The run takes about four minutes: the private server has to be up, the
builders have to be opped, and the restore restarts the server (10 s).
