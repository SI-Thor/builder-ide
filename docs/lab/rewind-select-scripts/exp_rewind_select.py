#!/usr/bin/env python3
"""Measure the rewind machinery: the cost per hour of world (time, bytes).

Three measurements, in the order the rewind meets them:

1. **The world's ledger.** A selection over the whole of the world's ledger:
   how long the read takes, how long the selection takes, and how many bytes
   the ledger itself holds. Divided by the hours of world the ledger
   records, that is the cost per hour of world.
2. **One cherry-pick over the canon.** The marginal cost of the fork: the
   events it writes, the bytes they add to the ledger, and the time they
   take. This is what a human's "rewind to here, keep these" costs the
   ledger of record.
3. **The Bevy fork.** The cost of the round's own machinery on the Bevy
   world: the branch, the replay, and the reference run that proves the two
   agree.

Run it from the repository root:

    ~/lm-wt/rewind-select/.venv/bin/python docs/lab/rewind-select-scripts/exp_rewind_select.py \
        --ledger ~/lm-wt/agent-world/runtime/world-ledger.sqlite3 \
        --lm ~/last-mile/target/release/lm \
        --out docs/lab/rewind-select-scripts/results/rewind-select.json

It takes about a minute: the world ledger is 90k rows and a few hundred
megabytes, and the Bevy part plays and replays three rounds. It needs no
GPU and no model: the Bevy world is a fixed-point simulation.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.recipe.blobs import FileBlobStore  # noqa: E402
from core.recipe.edits import apply_ops  # noqa: E402
from core.recipe.ledger import SQLiteLedger  # noqa: E402
from core.recipe.models import (  # noqa: E402
    Actor,
    Constraint,
    EnginePin,
    GeneratorRef,
    Op,
    Recipe,
    RecipeEntry,
)
from core.recipe.store import RecipeStore  # noqa: E402
from core.rewind import (  # noqa: E402
    BevyWorld,
    cherry_pick,
    keep_from_round,
    parse,
    point_at_version,
    read_world_ledger,
    select,
)

HOUR = 3600.0


def _median_time(callable_, repeats: int = 3) -> float:
    """The median of a few runs, in seconds."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        callable_()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def _file_bytes(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


# ==================================================================== 1. world


def measure_world_ledger(path: Path) -> dict:
    """A selection over the whole world's ledger."""
    started = time.perf_counter()
    ledger = read_world_ledger(path)
    read_seconds = time.perf_counter() - started

    selection = parse("actor = Kite or agent = Pebble")
    started = time.perf_counter()
    result = select(ledger, selection)
    select_seconds = time.perf_counter() - started

    rows = len(ledger.rows)
    if rows == 0:
        raise SystemExit(f"the ledger at {path} holds no rows")
    span = ledger.rows[-1].at - ledger.rows[0].at
    hours = span / HOUR

    wal = path.with_name(path.name + "-wal")
    file_bytes = _file_bytes(path)
    wal_bytes = _file_bytes(wal)

    # The bytes of the answer: the seqs the human would act on.
    kept_bytes = len(result.kept_seqs) * 8

    return {
        "ledger": str(path),
        "rows": rows,
        "first_at": ledger.rows[0].at,
        "last_at": ledger.rows[-1].at,
        "hours_of_world": hours,
        "ledger_bytes": file_bytes,
        "wal_bytes": wal_bytes,
        "bytes_per_hour": (file_bytes + wal_bytes) / hours,
        "rows_per_hour": rows / hours,
        "read_seconds": read_seconds,
        "select_seconds": select_seconds,
        "read_seconds_per_hour": read_seconds / hours,
        "select_seconds_per_hour": select_seconds / hours,
        "kept_rows": len(result.kept_seqs),
        "kept_bytes": kept_bytes,
        "selection": selection.text,
    }


# ==================================================================== 2. canon


def _canon() -> Recipe:
    pin = EnginePin(
        repo="SI-Thor/infinigen-thor",
        commit="9f31c0e",
        config="sha256:" + "0" * 64,
        blender="4.2.0",
        python="3.12",
    )
    return Recipe(
        id="rcp_harbor",
        name="Harbor",
        engine_pin=pin,
        seeds={"terrain": 4471},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates",
                kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.props",
                    func="crates",
                    variant="harbor",
                    rev="9f31c0e",
                ),
                params={"count": 12},
                seed=4472,
            ),
            "terrain.harbor": RecipeEntry(
                path="terrain.harbor",
                kind="terrain",
                params={"slope": 0.08},
                seed=4471,
            ),
        },
        constraints=[Constraint(name="dripline", kind="keep_clear", ref="oak_0117", value=0.35)],
    )


def measure_cherry_pick(work: Path) -> dict:
    """One cherry-pick over a canon, on a ledger of record on disk."""
    ledger_path = work / "canon-ledger.sqlite3"
    ledger = SQLiteLedger(ledger_path)
    store = RecipeStore(
        ledger=ledger,
        blobs=FileBlobStore(work / "blobs"),
        require_schema=False,
    )
    owner = Actor(kind="owner", id="casey")
    magnus = Actor(kind="owner", id="magnus")

    store.create_recipe(_canon(), owner)
    branch = store.create_branch(
        name="night", recipe="rcp_harbor", head="ver_0001", purpose="night", actor=owner
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="more crates",
        branch=branch.id,
    )
    store.apply_edit(
        branch.head,
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=owner,
        message="a steeper slope",
        branch=branch.id,
    )

    def ledger_bytes() -> int:
        # SQLite writes into the WAL first: the file alone does not show
        # the growth until a checkpoint moves it.
        return _file_bytes(ledger_path) + _file_bytes(
            ledger_path.with_name(ledger_path.name + "-wal")
        )

    before_bytes = ledger_bytes()
    before_events = len(ledger.events())

    started = time.perf_counter()
    pick = cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=owner,
    )
    seconds = time.perf_counter() - started

    after_bytes = ledger_bytes()
    events = ledger.events()
    written = events[before_events:]
    kinds: dict[str, int] = {}
    for event in written:
        kinds[event.type] = kinds.get(event.type, 0) + 1

    payload_bytes = sum(len(json.dumps(event.payload, sort_keys=True)) for event in written)
    ledger.close()
    return {
        "seconds": seconds,
        "ledger_bytes_before": before_bytes,
        "ledger_bytes_after": after_bytes,
        "marginal_bytes": after_bytes - before_bytes,
        "marginal_bytes_note": "the ledger file plus its WAL",
        "events_written": len(written),
        "events_by_type": kinds,
        "payload_bytes": payload_bytes,
        "kept": len(pick.kept),
        "dropped": len(pick.dropped),
        "parked": len(pick.parked),
        "merged_cleanly": pick.merged_cleanly,
        "canon_head_moved": False,
    }


# ==================================================================== 3. bevy


def _decision(agent: int, tick: int, seq: int, x: int, y: int) -> str:
    return json.dumps(
        {
            "arrived": tick,
            "decision": {
                "apply_tick": tick,
                "source": {"Agent": agent},
                "seq": seq,
                "kind": {"ActionOn": {"GoTo": {"x": x, "y": y}}},
                "provenance": "Test",
            },
        }
    )


def measure_bevy(lm: str, work: Path) -> dict:
    """The Bevy fork: the branch, the replay, and the reference run."""
    world = BevyWorld(lm)
    ledger = work / "decisions.jsonl"
    ledger.write_text(
        "\n".join(
            [
                _decision(0, 100, 1, 12, 9),
                _decision(3, 100, 1, 30, 30),
                _decision(0, 200, 2, 40, 12),
                _decision(3, 200, 2, 18, 44),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parent = work / "parent.lml"

    started = time.perf_counter()
    world.run(seed=5, ticks=300, out=parent, inject=ledger)
    run_seconds = time.perf_counter() - started

    started = time.perf_counter()
    replay = world.replay(parent)
    replay_seconds = time.perf_counter() - started

    started = time.perf_counter()
    keep = keep_from_round(
        world,
        parent=parent,
        at=150,
        selection=parse("actor = agent:0"),
        out_dir=work / "out",
    )
    keep_seconds = time.perf_counter() - started

    return {
        "run_seconds": run_seconds,
        "replay_seconds": replay_seconds,
        "replay_hashes": replay.hashes,
        "replay_ok": replay.ok,
        "keep_seconds": keep_seconds,
        "parent_bytes": _file_bytes(parent),
        "fork_bytes": _file_bytes(Path(keep.fork)),
        "reference_bytes": _file_bytes(Path(keep.reference)),
        "dropped_sources": list(keep.dropped_sources),
        "identical": keep.identical,
        "diff": keep.diff.output if keep.diff else "",
    }


# ==================================================================== main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path.home() / "lm-wt/agent-world/runtime/world-ledger.sqlite3",
        help="the world's ledger (read read-only)",
    )
    parser.add_argument(
        "--lm",
        default=os.environ.get("LM", str(Path.home() / "last-mile/target/release/lm")),
        help="the lm binary",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "docs/lab/rewind-select-scripts/results/rewind-select.json",
        help="where the numbers are written",
    )
    parser.add_argument("--skip-world", action="store_true")
    args = parser.parse_args()

    box = {
        "load_average": os.getloadavg(),
        "cpus": os.cpu_count(),
    }
    with open("/proc/meminfo") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                box["mem_available_kb"] = int(line.split()[1])
                break

    results: dict = {"box": box}

    with tempfile.TemporaryDirectory(prefix="rewind-select-") as tmp:
        work = Path(tmp)

        if not args.skip_world:
            results["world"] = measure_world_ledger(args.ledger)
        results["cherry_pick"] = measure_cherry_pick(work)
        if Path(args.lm).exists():
            results["bevy"] = measure_bevy(args.lm, work)
        else:
            results["bevy"] = {"skipped": f"no lm binary at {args.lm}"}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
