#!/usr/bin/env python3
"""The world snapshot, measured.

This is the script behind ``docs/lab/exp-world-snapshot.md``. It runs the
whole loop on the **private** world — the copy of the Paper server on
127.0.0.1:25610 with its own world directory — and writes every number it
measures into a JSON file next to itself.

The phases, in order:

1. **prepare** — the private server is started, the builders are opped;
2. **build A** — three builders place blocks; the world changes and the
   private world's ledger gets its first rows;
3. **snapshot, idle** — the world is quiet; the snapshot is timed and
   measured;
4. **build B** — three builders place blocks again, and the snapshot is
   taken **while they are building**;
5. **the plan** — the rewind point (the ledger's head) is matched to the
   nearest snapshot at or before it, and the kept work is classified;
6. **restore** — the snapshot is put back by swap, every file is verified
   by hash, and the world is read again: the entities, the players'
   inventories and the time of day;
7. **replay** — the kept placements are put back by mineflayer, and the
   region files are compared with the snapshot's.

The live world is never touched: it is read (the ledger, read-only) and
nothing else.

Usage:

    .venv/bin/python docs/lab/world-snapshot-scripts/exp_world_snapshot.py \\
        --server-dir mc-snap --results docs/lab/world-snapshot-scripts/results/world-snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "mcsnap" / "python"))
sys.path.insert(0, str(REPO))

from mcsnap.manifest import read_manifest, sha256_file, verify_directory  # noqa: E402
from mcsnap.server import PrivateServer  # noqa: E402
from mcsnap.state import world_state  # noqa: E402
from mcsnap.world import plan_tree  # noqa: E402

from core.rewind.snapshot import rewind_plan_from_store  # noqa: E402
from core.rewind.ledger import read_world_ledger  # noqa: E402

NODE = Path.home() / "lm-wt" / "agent-world" / "runtime" / "node" / "bin" / "node"
BOT_MODULES = Path.home() / "lm-wt" / "agent-world" / "bots" / "node_modules"


def box_state() -> dict[str, Any]:
    """The box's state beside the numbers: load and free memory."""
    state: dict[str, Any] = {}
    try:
        for line in Path("/proc/loadavg").read_text().split()[:3]:
            pass
        state["load_average"] = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except OSError:
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                state["mem_available_kb"] = int(line.split()[1])
                break
    except OSError:
        pass
    return state


def op_bots(server: PrivateServer, names: list[str]) -> None:
    """Write the server's own ops file, so the builders can be creative."""
    server.server_dir.mkdir(parents=True, exist_ok=True)
    ops = [{"name": name, "level": 4, "bypassesPlayerLimit": True} for name in names]
    (server.server_dir / "ops.json").write_text(json.dumps(ops, indent=2), encoding="utf-8")


def run_builders(
    server: PrivateServer,
    names: list[str],
    *,
    journal: Path,
    ledger: Path,
    count: int,
    block: str,
    offset_base: int,
    interval_ms: int = 1500,
    wait: bool = True,
) -> dict[str, Any]:
    """Run the builders, and say how long they took and what they placed."""
    environment = dict(os.environ)
    environment["NODE_PATH"] = str(BOT_MODULES)
    processes: list[subprocess.Popen[str]] = []
    started = time.perf_counter()
    for index, name in enumerate(names):
        command = [
            str(NODE),
            str(REPO / "tools" / "mcsnap" / "bots" / "builder.js"),
            "--name", name,
            "--host", "127.0.0.1",
            "--port", "25610",
            "--journal", str(journal),
            "--ledger", str(ledger),
            "--count", str(count),
            "--block", block,
            "--offset", str(offset_base + index),
            "--intervalMs", str(interval_ms),
        ]
        processes.append(
            subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        )
    # The builders need to be opped before they can place a block. They
    # are opped while they are connected, so the experiment never has to
    # restart the server to pick up an ops file.
    time.sleep(3.0)
    for name in names:
        try:
            server.command(f"op {name}")
        except Exception as error:
            print(f"could not op {name}: {error}")
    if not wait:
        return {"started": True, "processes": processes, "seconds": 0.0}
    outputs = []
    for process in processes:
        try:
            outputs.append(process.communicate(timeout=300)[0])
        except subprocess.TimeoutExpired:
            process.kill()
            outputs.append("timeout")
    seconds = time.perf_counter() - started
    placed = 0
    for output in outputs:
        for line in (output or "").splitlines():
            if line.startswith("placed "):
                placed += 1
    return {
        "started": True,
        "seconds": round(seconds, 3),
        "placed": placed,
        "output": outputs,
    }


def journal_entries(journal: Path) -> list[dict[str, Any]]:
    """Every placement the journal holds, in the order they happened."""
    if not journal.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in journal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def run_probe(
    server: PrivateServer,
    points: list[dict[str, Any]],
    out_path: Path,
) -> list[dict[str, Any]]:
    """Ask the server what block is at each point, and write the answer out.

    This is the eye of the measurement. The files say what was copied;
    only the server can say what the world looks like afterwards. The
    probe stands next to each point and reads the block there.
    """
    if not points:
        return []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    points_path = out_path.with_name(f"{out_path.stem}-points.json")
    points_path.write_text(json.dumps(points), encoding="utf-8")
    environment = dict(os.environ)
    environment["NODE_PATH"] = str(BOT_MODULES)
    completed = subprocess.run(
        [
            str(NODE),
            str(REPO / "tools" / "mcsnap" / "bots" / "probe.js"),
            "--name", "Prober",
            "--host", "127.0.0.1",
            "--port", "25610",
            "--points", str(points_path),
            "--out", str(out_path),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if not out_path.is_file():
        return [{"error": (completed.stderr or completed.stdout or "the probe wrote nothing")[-500:]}]
    return json.loads(out_path.read_text(encoding="utf-8"))


def snapshot_now(
    server: PrivateServer, store: Path, ledger_path: Path | None, label: str
) -> dict[str, Any]:
    """Take a snapshot through the tool, and time it."""
    from mcsnap.snapshot import take_snapshot

    started = time.perf_counter()
    result = take_snapshot(
        server.world_dir,
        store,
        ledger_path=ledger_path,
        command=server.command,
    )
    seconds = time.perf_counter() - started
    summary = result.summary()
    summary["label"] = label
    summary["wall_seconds"] = round(seconds, 3)
    summary["directory"] = str(result.directory)
    return summary


def _journal_lines(journal: Path) -> int:
    """How many placements the journal holds."""
    if not journal.is_file():
        return 0
    return sum(1 for line in journal.read_text(encoding="utf-8").splitlines() if line.strip())


def region_hashes(world_dir: Path) -> dict[str, str]:
    """The sha256 of every region file in a world, by its relative path."""
    hashes: dict[str, str] = {}
    root = world_dir / "dimensions"
    if not root.is_dir():
        return hashes
    for region in sorted(root.glob("*/*/region/r.*.mca")):
        hashes[str(region.relative_to(world_dir))] = sha256_file(region)
    return hashes


def save(results: dict[str, Any], out: Path) -> None:
    """Write the results out, now, and keep writing them as they come."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-dir", default="mc-snap")
    parser.add_argument("--store", default=None, help="the snapshot store")
    parser.add_argument("--ledger", default=None, help="the private world's ledger")
    parser.add_argument("--journal", default=None, help="the placement journal")
    parser.add_argument("--results", required=True)
    parser.add_argument("--bots", type=int, default=3)
    parser.add_argument("--blocks", type=int, default=6)
    parser.add_argument("--block", default="stone")
    parser.add_argument(
        "--interval-ms", type=int, default=1500,
        help="how long a builder waits between two placements",
    )
    args = parser.parse_args(argv)

    server_dir = Path(args.server_dir).resolve()
    store = Path(args.store).resolve() if args.store else server_dir / "snapshots"
    ledger_path = Path(args.ledger).resolve() if args.ledger else server_dir / "ledger.sqlite3"
    journal = Path(args.journal).resolve() if args.journal else server_dir / "placements.jsonl"

    server = PrivateServer(server_dir, peak="3G")
    names = [f"Builder{index + 1}" for index in range(args.bots)]
    results: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "server": {"dir": str(server_dir), "port": 25610, "rcon": 25611},
        "box_at_start": box_state(),
    }

    # -- 1. prepare ----------------------------------------------------------
    op_bots(server, names + ["Rewinder"])
    status = server.status()
    if not status["running"]:
        results["server_start"] = server.start(wait_seconds=900.0).to_dict()
    results["server_version"] = server.status()["version"]
    results["server_before"] = status
    # The bots that move themselves around the world — the replayer and
    # the prober — need to be opped as well. The server may already have
    # been running when the experiment starts, and then the ops file on
    # disk is not read: the op has to be given at runtime.
    for name in names + ["Rewinder", "Prober"]:
        try:
            server.command(f"op {name}")
        except Exception as error:
            print(f"could not op {name}: {error}")

    # -- 2. build A ----------------------------------------------------------
    results["build_a"] = run_builders(
        server, names, journal=journal, ledger=ledger_path,
        count=args.blocks, block=args.block, offset_base=0,
        interval_ms=args.interval_ms,
    )
    results["box_after_build_a"] = box_state()
    save(results, Path(args.results))

    # -- 3. snapshot, idle ---------------------------------------------------
    journal_before_idle = _journal_lines(journal)
    idle = snapshot_now(server, store, ledger_path, "idle")
    journal_after_idle = _journal_lines(journal)
    results["snapshot_idle"] = idle
    results["placements_during_the_idle_snapshot"] = journal_after_idle - journal_before_idle
    results["box_after_idle_snapshot"] = box_state()
    save(results, Path(args.results))

    # -- 4. build B, and the snapshot while they build -----------------------
    builders = run_builders(
        server, names, journal=journal, ledger=ledger_path,
        count=args.blocks, block=args.block, offset_base=args.bots + 1,
        interval_ms=args.interval_ms, wait=False,
    )
    # The snapshot has to be taken while the bots are *building*, so the
    # experiment waits for the placement journal to grow rather than
    # sleeping a fixed time and hoping.
    before = _journal_lines(journal)
    deadline = time.time() + 120
    while time.time() < deadline:
        if _journal_lines(journal) > before:
            break
        time.sleep(0.5)
    journal_before_building = _journal_lines(journal)
    building = snapshot_now(server, store, ledger_path, "building")
    journal_after_building = _journal_lines(journal)
    results["journal_lines_at_building_snapshot"] = journal_after_building
    results["placements_during_the_building_snapshot"] = (
        journal_after_building - journal_before_building
    )
    results["snapshot_building"] = building
    save(results, Path(args.results))
    for process in builders["processes"]:
        try:
            process.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            process.kill()
    results["box_after_building_snapshot"] = box_state()

    # -- 4b. the eye: what does the world look like? -------------------------
    probe_dir = Path(args.results).parent / "probes"
    entries = journal_entries(journal)
    points = [
        {
            "x": entry["x"], "y": entry["y"], "z": entry["z"],
            "expect": entry.get("block"),
        }
        for entry in entries
    ]
    results["probe_before_restore"] = run_probe(
        server, points, probe_dir / "probe-before-restore.json"
    )
    save(results, Path(args.results))

    # -- 5. the plan ---------------------------------------------------------
    ledger = read_world_ledger(ledger_path)
    head = ledger.rows[-1].seq if ledger.rows else 0
    results["ledger"] = {
        "path": str(ledger_path),
        "rows": len(ledger.rows),
        "head_seq": head,
    }
    plan_all = rewind_plan_from_store(
        store, ledger_path, point_seq=head, placements_path=journal,
    )
    results["plan_keep_everything"] = plan_all.to_dict()
    one = names[0]
    plan_one = rewind_plan_from_store(
        store, ledger_path, point_seq=head,
        selection_text=f"actor = {one}",
        placements_path=journal,
    )
    results["plan_keep_one_bot"] = plan_one.to_dict()
    save(results, Path(args.results))

    # -- 6. the restore ------------------------------------------------------
    before_state = world_state(server.world_dir)
    before_hashes = region_hashes(server.world_dir)
    results["state_before_restore"] = before_state

    from mcsnap.restore import restore

    restore_started = time.perf_counter()
    restored = restore(
        server_dir,
        Path(results["snapshot_building"]["directory"]),
        stop=server.stop,
        start=lambda: server.start(wait_seconds=900.0),
    )
    results["restore"] = {
        **restored.summary(),
        "wall_seconds": round(time.perf_counter() - restore_started, 3),
    }
    after_state = world_state(server.world_dir)
    results["state_after_restore"] = after_state
    results["region_hashes_after_restore"] = region_hashes(server.world_dir)
    # The eye again: the same points, read out of the restored world.
    results["probe_after_restore"] = run_probe(
        server, points, probe_dir / "probe-after-restore.json"
    )
    results["box_after_restore"] = box_state()
    save(results, Path(args.results))

    # -- 7. the replay -------------------------------------------------------
    # The restore restarted the server, and a server that starts reads
    # its operators from ops.json. The operators this experiment gave
    # at runtime are gone with the old server, so the bots that need to
    # move themselves around the world have to be opped **again** — and
    # a bot that is not an operator cannot /tp, so it would stand where
    # it spawned and its placements would be out of reach.
    for name in names + ["Rewinder", "Prober"]:
        try:
            server.command(f"op {name}")
        except Exception as error:
            print(f"could not op {name} after the restore: {error}")
    replay_plan = Path(results["snapshot_building"]["directory"]).parent / "replay-plan.json"
    replay_plan.write_text(json.dumps(plan_all.to_dict(), indent=2), encoding="utf-8")
    environment = dict(os.environ)
    environment["NODE_PATH"] = str(BOT_MODULES)
    replay_started = time.perf_counter()
    replay = subprocess.run(
        [
            str(NODE),
            str(REPO / "tools" / "mcsnap" / "bots" / "replay.js"),
            "--name", "Rewinder",
            "--host", "127.0.0.1",
            "--port", "25610",
            "--plan", str(replay_plan),
            "--journal", str(journal.with_name("replayed.jsonl")),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    results["replay"] = {
        "seconds": round(time.perf_counter() - replay_started, 3),
        "returncode": replay.returncode,
        "output": (replay.stdout or "")[-2000:],
    }
    try:
        after_replay = snapshot_now(server, store, ledger_path, "after-replay")
        results["snapshot_after_replay"] = after_replay
    except Exception as error:
        results["snapshot_after_replay"] = {"error": str(error)}
    after_replay_hashes = region_hashes(server.world_dir)
    snapshot_hashes = region_hashes(
        Path(results["snapshot_building"]["directory"]) / "world"
    )
    same = [
        path for path, digest in snapshot_hashes.items()
        if after_replay_hashes.get(path) == digest
    ]
    different = [
        path for path, digest in snapshot_hashes.items()
        if after_replay_hashes.get(path) != digest
    ]
    missing = [
        path for path in snapshot_hashes
        if path not in after_replay_hashes
    ]
    results["region_comparison_after_replay"] = {
        "same_as_snapshot": sorted(same),
        "different_from_snapshot": sorted(different),
        "missing_after_replay": sorted(missing),
        "note": (
            "a region file hashes the same only if every block in it came "
            "back exactly; the ones that differ are the chunks the replay "
            "did not restore"
        ),
    }
    # The eye a third time: the same points, read out of the world the
    # replay put back. The table below is the answer to "what differs
    # after a restore", one block at a time.
    results["probe_after_replay"] = run_probe(
        server, points, probe_dir / "probe-after-replay.json"
    )

    def blocks_at(probe: list[dict[str, Any]]) -> dict[tuple[int, int, int], str]:
        index: dict[tuple[int, int, int], str] = {}
        for row in probe:
            if not isinstance(row, dict) or "x" not in row:
                continue
            index[(int(row["x"]), int(row["y"]), int(row["z"]))] = str(row.get("block"))
        return index

    before_blocks = blocks_at(results.get("probe_before_restore", []))
    after_blocks = blocks_at(results.get("probe_after_restore", []))
    replay_blocks = blocks_at(results.get("probe_after_replay", []))
    snapshot_seq = int(results["snapshot_building"].get("ledger_seq") or 0)
    table: list[dict[str, Any]] = []
    for entry in entries:
        key = (int(entry["x"]), int(entry["y"]), int(entry["z"]))
        in_snapshot = int(entry.get("seq") or 0) <= snapshot_seq
        table.append({
            "x": key[0], "y": key[1], "z": key[2],
            "block": entry.get("block"),
            "seq": entry.get("seq"),
            "in_snapshot": in_snapshot,
            "before_restore": before_blocks.get(key),
            "after_restore": after_blocks.get(key),
            "after_replay": replay_blocks.get(key),
        })
    results["block_table"] = table
    results["block_table_summary"] = {
        "placements_journalled": len(table),
        "blocks_present_before_the_restore": sum(
            1 for row in table if row["before_restore"] == row["block"]
        ),
        "blocks_removed_by_the_restore": sum(
            1 for row in table
            if row["before_restore"] == row["block"] and row["after_restore"] == "air"
        ),
        "blocks_kept_by_the_restore": sum(
            1 for row in table
            if row["before_restore"] == row["block"] and row["after_restore"] == row["block"]
        ),
        "blocks_put_back_by_the_replay": sum(
            1 for row in table
            if row["after_restore"] == "air" and row["after_replay"] == row["block"]
        ),
        "still_missing_after_the_replay": sum(
            1 for row in table
            if row["after_restore"] == "air" and row["after_replay"] != row["block"]
        ),
        "predicted_by_the_ledger": {
            "in_the_snapshot": sum(1 for row in table if row["in_snapshot"]),
            "after_the_snapshot": sum(1 for row in table if not row["in_snapshot"]),
        },
        "note": (
            "the counts are read out of the running world with the probe "
            "bot; the ledger's own prediction is in 'predicted_by_the_ledger'"
        ),
    }
    results["box_at_end"] = box_state()
    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = Path(args.results)
    save(results, out)
    print(f"results written to {out}")
    print(json.dumps({
        "snapshot_idle": results["snapshot_idle"],
        "snapshot_building": results["snapshot_building"],
        "restore": results["restore"],
        "replay": results["replay"]["returncode"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
