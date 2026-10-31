#!/usr/bin/env python
"""stage_cache_thor.py — measure the stage cache and partial regeneration.

Plan §3 week-2 item 9's pass/fail, made a script: *"edit one room"
end-to-end vs full regeneration, with per-stage timings; cache hit rate
per night reported; cache keys ⊆ (recipe hash, engine pin, stage)* — plus
the round-2 desk edit re-measured through the new graph diff. Three
scenarios, all against the real v2 venv (read-only):

A. **edit one room** (stage granularity) — a 3-entry recipe (room +
   terrain + crates). The same room edit runs twice: once against a cold
   cache (full regeneration: every entry re-traces) and once against a
   warm one (partial: the room re-traces, the siblings are hits the
   engine is never asked for).
B. **add a desk** (subtree granularity) — round 2's one-`chosen_idx` edit
   (`room.py:661`, forced with the experiment's own `choice_tool.py`,
   read-only): two fresh traces, the graph diff between them, and the
   un-traced generation runs whose wall delta is the desk's marginal
   cost (the render is held at 320×180 / 4 spp so generation dominates).
C. **a 10-edit session** (hit rates) — ten scripted edits over the
   3-entry recipe through the stage cache, each one a full regenerate()
   of every entry; the hit rate is the cache's own counters, and the
   no-cache cost is computed from the session's measured per-stage walls
   (each stage's re-trace wall, summed over the asks a cache would have
   missed) — said so in the row, never measured twice by pretending.

Every number is recorded with the box's state beside it (the standing
rule). Usage:

    .venv/bin/python examples/stage_cache_thor.py [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.engine.graph import GraphStore, diff_graphs
from core.engine.infinigen1 import SubprocessRunner
from core.engine.infinigen2 import Infinigen2Engine
from core.engine.regen import Regenerator
from core.engine.stagecache import StageCache
from core.engine.venv2 import Venv2Runtime
from core.records import Actor, GeneratorRef, Op, Recipe, RecipeEntry
from core.recipe.ledger import InMemoryLedger
from core.recipe.store import RecipeStore

ACTOR = Actor(kind="owner", id="casey")

GENERATORS = {
    "room": "room_livingroom_rand",
    "terrain": "terrain_scene_rand",
    "crates": "storage_cabinet_with_door_rand",
}

SEEDS = {"room": 0, "terrain": 0, "crates": 42}


def box_state() -> str:
    parts = []
    for argv in (["uptime"], ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
                              "--format=csv,noheader"]):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                parts.append(out.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return " | ".join(parts) or "state unavailable"


def run_timed(argv: list[str], *, cwd: Path | None = None,
              tmp: Path | None = None) -> dict:
    """One subprocess, wall time, and peak RSS via /usr/bin/time -v when
    it exists (the round-2 convention for the big runs). The timing file
    lands in our scratch, never in the engine's read-only tree."""
    time_bin = shutil.which("time")
    if time_bin:
        out_path = (tmp or Path("/tmp")) / ".time-v"
        wrapped = [time_bin, "-v", "-o", str(out_path), *argv]
    else:
        out_path, wrapped = None, argv
    started = time.monotonic()
    result = subprocess.run(wrapped, cwd=cwd, capture_output=True, text=True)
    wall = time.monotonic() - started
    rss_kb = None
    if out_path is not None and out_path.is_file():
        match = re.search(r"Maximum resident set size \(kbytes\): (\d+)",
                          out_path.read_text())
        if match:
            rss_kb = int(match.group(1))
        out_path.unlink(missing_ok=True)
    return {
        "argv": [Path(a).name for a in argv[:3]],
        "returncode": result.returncode,
        "wall_s": round(wall, 3),
        "peak_rss_mb": round(rss_kb / 1024, 1) if rss_kb else None,
        "tail": (result.stderr or result.stdout).strip().splitlines()[-1][:200]
        if (result.stderr or result.stdout).strip() else "",
    }


# --------------------------------------------------------------------- world


def build_stack(home: Path, scratch: Path, *, cache_root: Path):
    runtime = Venv2Runtime(
        python=home / ".venv" / "bin" / "python",
        generators=GENERATORS,
        output_dir=scratch / "engine",
        repo=home / "src" / "infinigen-upstream",
        repo_name="princeton-vl/infinigen",
        runner=SubprocessRunner(),
    )
    pin = runtime.engine_pin()
    engine = Infinigen2Engine(pin=pin, runtime=runtime)

    store = RecipeStore(ledger=InMemoryLedger(), require_schema=False)
    store.create_recipe(recipe_document(pin), ACTOR)
    regen = Regenerator(
        engine=engine, store=store,
        cache=StageCache(cache_root, max_bytes=8 * 1024 * 1024 * 1024),
        graphs=GraphStore(cache_root.parent / "graphs"),
    )
    return regen, store, pin


def recipe_document(pin, *, room_seed=SEEDS["room"],
                    terrain_seed=SEEDS["terrain"],
                    crates_seed=SEEDS["crates"]) -> Recipe:
    def ref(func: str) -> GeneratorRef:
        return GeneratorRef(module="infinigen_thor.scenes", func=func,
                            variant=None, rev=pin.commit)

    return Recipe(
        id="rcp_fjellvik", name="Fjellvik", engine_pin=pin,
        entries={
            "fjellvik.room": RecipeEntry(
                path="fjellvik.room", kind="structure", seed=room_seed,
                generator=ref("room"), params={}),
            "fjellvik.terrain": RecipeEntry(
                path="fjellvik.terrain", kind="terrain", seed=terrain_seed,
                generator=ref("terrain"), params={}),
            "fjellvik.crates": RecipeEntry(
                path="fjellvik.crates", kind="prop_set", seed=crates_seed,
                generator=ref("crates"), params={"count": 8}),
        },
    )


def entry_walls(report) -> dict[str, float]:
    return {
        outcome.entry: round((outcome.wall_ms or 0) / 1000.0, 3)
        for outcome in report.entries
    }


# ----------------------------------------------------------------- scenario A


def scenario_edit_one_room(home: Path, scratch: Path) -> dict:
    """The same room edit, cold cache vs warm: full vs partial, measured."""
    cold_root = scratch / "a-cold"
    warm_root = scratch / "a-warm"
    cold, cold_store, pin = build_stack(home, scratch, cache_root=cold_root / "cache")
    warm, warm_store, _ = build_stack(home, scratch, cache_root=warm_root / "cache")

    # prime the warm cache: the project's first full generation
    prime = warm.regenerate("ver_0001", "ver_0001")

    edit = [Op(op="set", path="fjellvik.room.seed", value=1)]

    warm_head = warm_store.apply_edit("ver_0001", edit, author=ACTOR,
                                      message="reseed the room").id
    started = time.monotonic()
    warm_report = warm.regenerate("ver_0001", warm_head)
    warm_wall = time.monotonic() - started

    cold_head = cold_store.apply_edit("ver_0001", edit, author=ACTOR,
                                      message="reseed the room").id
    started = time.monotonic()
    cold_report = cold.regenerate("ver_0001", cold_head)
    cold_wall = time.monotonic() - started

    return {
        "box_state": box_state(),
        "recipe_entries": sorted(GENERATORS),
        "prime_walls": entry_walls(prime),
        "full_regeneration": {  # cold cache: every entry re-traces
            "wall_s": round(cold_wall, 3),
            "verdicts": cold_report.verdicts(),
            "per_entry": entry_walls(cold_report),
        },
        "partial_regeneration": {  # warm cache: the room misses, siblings hit
            "wall_s": round(warm_wall, 3),
            "verdicts": warm_report.verdicts(),
            "per_entry": entry_walls(warm_report),
        },
        "saved": round(cold_wall - warm_wall, 3),
        "speedup": round(cold_wall / warm_wall, 2) if warm_wall else None,
    }


# ----------------------------------------------------------------- scenario B


def scenario_add_a_desk(home: Path, scratch: Path) -> dict:
    """Round 2's choice edit, fresh: two traces, the graph diff, and the
    un-traced generation runs whose wall delta is the desk's cost."""
    venv_python = home / ".venv" / "bin" / "python"
    choice_tool = home / "choice_tool.py"
    site = (home / "src" / "infinigen-upstream" / "src" / "infinigen2" /
            "scenes" / "room" / "room.py:661")
    out = scratch / "b"
    out.mkdir(parents=True, exist_ok=True)

    base_trace = run_timed(
        [str(venv_python), str(choice_tool), "trace", "room_livingroom_rand",
         "--seed", "0", "--out", str(out / "base")], cwd=home, tmp=out)
    desk_trace = run_timed(
        [str(venv_python), str(choice_tool), "force-trace",
         "room_livingroom_rand", "--seed", "0", "--site", str(site),
         "--occurrence", "0", "--index", "1", "--out", str(out / "desk")],
        cwd=home, tmp=out)

    base_graph = json.loads((out / "base" / "graph.json").read_text())
    desk_graph = json.loads((out / "desk" / "graph.json").read_text())
    diff = diff_graphs(base_graph, desk_graph).as_dict()

    # un-traced generation at the floor of the render ladder: the wall
    # delta between baseline and forced is the desk's marginal cost
    base_run = run_timed(
        [str(venv_python), str(choice_tool), "run", "room_livingroom_rand",
         "--seed", "0", "--samples", "4", "-r", "320", "180",
         "--out", str(out / "run-base")], cwd=home, tmp=out)
    desk_run = run_timed(
        [str(venv_python), str(choice_tool), "run", "room_livingroom_rand",
         "--seed", "0", "--site", str(site), "--occurrence", "0",
         "--index", "1", "--samples", "4", "-r", "320", "180",
         "--out", str(out / "run-desk")], cwd=home, tmp=out)

    def choices(path: Path) -> int:
        return len(json.loads((path / "choices.json").read_text()))

    return {
        "box_state": box_state(),
        "edit": "room.py:661 chosen_idx 0 -> 1 (the desk), seed 0",
        "full_regeneration": {
            "trace_wall_s": desk_trace["wall_s"],
            "generation_wall_s": desk_run["wall_s"],
            "peak_rss_mb": desk_run["peak_rss_mb"] or desk_trace["peak_rss_mb"],
            "choices": choices(out / "desk"),
        },
        "partial_regeneration": {  # what the dirty closure says executes
            "marginal_generation_s": round(
                desk_run["wall_s"] - base_run["wall_s"], 3),
            "baseline_generation_wall_s": base_run["wall_s"],
            "graph_diff_ms": diff["wall_ms"],
        },
        "graph_diff": diff,
        "baseline_choices": choices(out / "base"),
    }


# ----------------------------------------------------------------- scenario C


SESSION = [
    ("room", 1), ("crates", 43), ("terrain", 1), ("crates", 44),
    ("room", 2), ("crates", 45), ("terrain", 2),
    ("crates", 42), ("room", 0), ("terrain", 0),  # back to seeds already seen
]


def scenario_session(home: Path, scratch: Path) -> dict:
    regen, store, pin = build_stack(home, scratch, cache_root=scratch / "c-cache")
    regen.regenerate("ver_0001", "ver_0001")  # the evening's first full build
    regen.cache.reset_stats()  # the session's own denominator

    edits = []
    base = "ver_0001"
    measured_walls: dict[str, float] = {}
    for i, (entry, seed) in enumerate(SESSION, start=1):
        head = store.apply_edit(
            base, [Op(op="set", path=f"fjellvik.{entry}.seed", value=seed)],
            author=ACTOR, message=f"session edit {i}: {entry} seed {seed}").id
        report = regen.regenerate(base, head)
        for outcome in report.entries:
            if outcome.wall_ms:
                measured_walls[outcome.entry] = max(
                    measured_walls.get(outcome.entry, 0.0),
                    outcome.wall_ms / 1000.0)
        edits.append({
            "edit": f"{entry}.seed -> {seed}",
            "verdicts": report.verdicts(),
            "wall_s": round((report.wall_ms or 0) / 1000.0, 3),
        })
        base = head

    stats = regen.cache.stats()
    # the no-cache cost of the same session, computed from the session's own
    # measured per-entry walls (one re-trace per ask, which is what no cache
    # means) — computed, and said so
    no_cache_s = sum(
        measured_walls.get(f"fjellvik.{name}", 0.0)
        for _ in SESSION
        for name in GENERATORS
    )
    cached_s = sum(edit["wall_s"] for edit in edits)
    return {
        "box_state": box_state(),
        "edits": edits,
        "stage_asks": stats["hits"] + stats["misses"],
        "hits": stats["hits"],
        "misses": stats["misses"],
        "hit_rate": stats["hit_rate"],
        "cached_wall_s": round(cached_s, 3),
        "no_cache_wall_s_computed": round(no_cache_s, 3),
        "per_entry_walls_measured": {k: round(v, 3)
                                     for k, v in sorted(measured_walls.items())},
        "cache_stats": stats,
    }


# ---------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/research/stage-cache-thor.json")
    parser.add_argument("--home", default=os.environ.get(
        "BUILDER_V2_HOME", str(Path("~/lm-wt/v2-next").expanduser())))
    args = parser.parse_args()

    home = Path(args.home).expanduser()
    if not (home / ".venv" / "bin" / "python").is_file():
        print(f"no v2 venv at {home} (set --home or BUILDER_V2_HOME)",
              file=sys.stderr)
        return 2

    scratch = Path(os.environ.get("BUILDER_STAGE_SCRATCH", "/tmp/stage-cache-thor"))
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    results = {
        "date": time.strftime("%Y-%m-%d"),
        "engine_home": str(home),
        "scenarios": {},
    }
    for name, scenario in (
        ("edit_one_room", scenario_edit_one_room),
        ("add_a_desk", scenario_add_a_desk),
        ("session_10_edits", scenario_session),
    ):
        print(f"[stage-cache-thor] running {name} ...", flush=True)
        started = time.monotonic()
        results["scenarios"][name] = scenario(home, scratch)
        print(f"[stage-cache-thor] {name} done in "
              f"{time.monotonic() - started:.1f} s", flush=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=1, sort_keys=True))
    print(json.dumps(results["scenarios"]["session_10_edits"], indent=1)[:800])
    print(f"[stage-cache-thor] results -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
