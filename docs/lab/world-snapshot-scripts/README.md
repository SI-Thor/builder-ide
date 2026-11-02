# The world snapshot experiment

The script behind [`../../exp-world-snapshot.md`](../../exp-world-snapshot.md).
It runs the whole loop on the **private** world — the copy of the Paper
server on 127.0.0.1:25610 with its own world directory — and writes every
number it measures into a JSON file.

## What it needs

* the private server running (`.venv/bin/python -m mcsnap server start
  --server-dir mc-snap --peak 3G`), which needs a `thor-admit` lease;
* `node` and `mineflayer` from the live world's bots
  (`~/lm-wt/agent-world/runtime/node/bin/node`, with
  `NODE_PATH=~/lm-wt/agent-world/bots/node_modules`);
* the world ledger the bots write (`mc-snap/ledger.sqlite3`) and the
  placement journal (`mc-snap/placements.jsonl`).

## What it does

1. op the builders, the replayer and the prober;
2. **build A** — the builders place blocks; the world's ledger gets its
   first rows;
3. **snapshot, idle** — timed and measured;
4. **build B** — the builders place blocks again, and the snapshot is taken
   while they are building (the script waits for the placement journal to
   grow rather than sleeping a fixed time);
5. **the plan** — the rewind point (the ledger's head) is matched to the
   nearest snapshot at or before it, and the kept work is classified;
6. **restore** — the snapshot is put back by swap, every file is verified by
   hash, and the world is read again: the entities, the players'
   inventories and the time of day;
7. **probe** — a bot stands next to every journalled block and asks the
   server what is there, before the restore and after it;
8. **replay** — the kept placements are put back by mineflayer and read
   back.

## How long it takes

About four minutes, of which 11 s is the restore (the server starting
again) and the rest is the builders' placement loops. The private server
has to be up before it starts.

## Running it

```bash
cd ~/lm-wt/world-snapshot
.venv/bin/python docs/lab/world-snapshot-scripts/exp_world_snapshot.py \
    --server-dir mc-snap \
    --results docs/lab/world-snapshot-scripts/results/world-snapshot.json
```

Useful flags: `--bots` (how many builders), `--blocks` (how many blocks
each builder places), `--block` (which block), `--interval-ms` (how long a
builder waits between two placements).

The run writes its results **as it goes**, so a run that is interrupted
still leaves the numbers it had reached.

## Reading the results

* `snapshot_idle`, `snapshot_building` — the two snapshots: files, bytes,
  the ledger's seq, the tick, the time of day, and the timing of each step;
* `restore` — the timings, and `verified` / `problems`;
* `block_table` — every journalled block, with what the probe read before
  the restore, after the restore and after the replay;
* `block_table_summary` — the counts;
* `plan_keep_everything`, `plan_keep_one_bot` — the rewind plans;
* `state_before_restore`, `state_after_restore` — the world's own state;
* `box_at_start` … `box_at_end` — the box's load and free memory beside
  the numbers.
