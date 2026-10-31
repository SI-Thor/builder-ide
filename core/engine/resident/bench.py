"""The benchmark the brief asks for — builder wait, batch vs warm, and
crash-recovery time (plan item 15's own measures).

    python -m core.engine.resident.bench                     # fake backend
    python -m core.engine.resident.bench --backend blender \
        --python ~/lm-wt/warm-scene/.venv/bin/python         # the real tax

Three measurements, one scripted sequence of builder edits (the same
script the tests use — alternate the two entries, bump the count):

* **warm** — one resident holds the scene; every edit is a request to a
  process that is already there. Builder wait = the request's wall time.
* **batch** — a fresh resident per edit, the way a batch pipeline pays a
  fresh process per task: launch, load the whole recipe, do the edit,
  go away. The two modes run **interleaved** (batch 1, warm 1, batch 2,
  …) so whatever the box is doing while the benchmark runs falls on both
  sides (the spike's discipline, WS §1).
* **crash recovery** — SIGKILL the resident mid-sequence and time the
  next request: the rebuild, the journal's replay, the digest check and
  the stage, in one number the waiting builder actually experiences.

The box's state is recorded beside the numbers (CLAUDE.md): load average
and available memory when each phase started. The result is printed and
written, as JSON, to ``--out``.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

from core.engine.contract import StageRequest
from core.records import EnginePin, GeneratorRef, Recipe, RecipeEntry
from core.engine.resident import ResidentEngine, ResidentPolicy

__all__ = ["main"]

#: The pin a benchmark run reports — a synthetic one; the recipe is thrown
#: away with the benchmark's root directory.
BENCH_PIN = EnginePin(
    repo="SI-Thor/infinigen-thor",
    commit="bench-resident",
    config="sha256:" + "0" * 16,
    blender="4.2",
    python="3.11",
)


def bench_recipe(crates: int = 8, racks: int = 3) -> Recipe:
    return Recipe(
        id="rcp_bench", name="ResidentBench", engine_pin=BENCH_PIN,
        seeds={"terrain": 771, "props": 42},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates", kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="crates",
                    variant=None, rev=BENCH_PIN.commit),
                params={"count": crates, "style": "weathered"}, seed=42),
            "harbor.racks": RecipeEntry(
                path="harbor.racks", kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="racks",
                    variant=None, rev=BENCH_PIN.commit),
                params={"count": racks}, seed=43),
        },
    )


def scripted_edits(base: Recipe, count: int) -> list[Recipe]:
    """The 20 builder edits: alternate the entries, bump the count."""
    edits: list[Recipe] = []
    current = base
    for i in range(count):
        entry = "harbor.crates" if i % 2 == 0 else "harbor.racks"
        nxt = current.model_copy(deep=True)
        nxt.entries[entry].params["count"] = 4 + i
        edits.append(nxt)
        current = nxt
    return edits


def request_for(recipe: Recipe, index: int) -> StageRequest:
    return StageRequest(
        recipe=recipe, version_hash=f"bench-v{index}", stage="coarse")


def box_state() -> dict:
    state: dict = {}
    try:
        state["loadavg"] = open("/proc/loadavg").read().split()[:3]
    except OSError:
        pass
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                state["mem_available_mb"] = round(
                    int(line.split()[1]) / 1024)
    except OSError:
        pass
    return state


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * q), len(ordered) - 1)]


def summarize(waits_ms: list[float]) -> dict:
    return {
        "n": len(waits_ms),
        "p50": round(statistics.median(waits_ms), 2),
        "p95": round(pct(waits_ms, 0.95), 2),
        "max": round(max(waits_ms), 2),
        "mean": round(statistics.fmean(waits_ms), 2),
    }


def make_engine(root: Path, backend: str, python: str | None,
                **policy) -> ResidentEngine:
    return ResidentEngine(
        pin=BENCH_PIN, root=root, backend=backend, python=python,
        policy=ResidentPolicy(restart_backoff_s=0.5, **policy),
    )


def run_warm(root: Path, edits: list[Recipe], *, backend: str,
             python: str | None) -> dict:
    engine = make_engine(root, backend, python)
    try:
        cold = engine.generate_stage(
            request_for(edits[0], -1))  # the base load, timed apart
        waits = []
        for i, edited in enumerate(edits):
            waits.append(
                engine.generate_stage(request_for(edited, i)).wall_ms)
        return {
            "starts": engine.stats()["restarts"] + 1,
            "cold_request_ms": round(cold.wall_ms, 2),
            "builder_wait": summarize(waits),
            "state": engine.resident_state()["state"]["object_count"],
        }
    finally:
        engine.stop()


def run_batch(root: Path, edits: list[Recipe], *, backend: str,
              python: str | None) -> dict:
    waits = []
    for i, edited in enumerate(edits):
        engine = make_engine(root / f"task-{i:02d}", backend, python)
        try:
            waits.append(
                engine.generate_stage(request_for(edited, i)).wall_ms)
        finally:
            engine.stop()
    return {"starts": len(edits), "builder_wait": summarize(waits)}


def run_crash_recovery(root: Path, edits: list[Recipe], *, backend: str,
                       python: str | None) -> dict:
    engine = make_engine(root, backend, python)
    try:
        for i, edited in enumerate(edits):
            last = engine.generate_stage(request_for(edited, i))
        digest_before = engine.resident_state()["digest"]
        pid = engine.stats()["pid"]

        os.kill(pid, signal.SIGKILL)
        time.sleep(0.05)

        started = time.monotonic()
        after = engine.generate_stage(request_for(edits[-1], len(edits) - 1))
        recovery_ms = (time.monotonic() - started) * 1000.0
        return {
            "edits_before_kill": len(edits),
            "recovery_ms": round(recovery_ms, 2),
            "bytes_identical": after.data == last.data,
            "digest_identical":
                engine.resident_state()["digest"] == digest_before,
            "restarts": engine.stats()["restarts"],
        }
    finally:
        engine.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default="fake",
                        choices=["fake", "blender"])
    parser.add_argument("--python", default=None,
                        help="the engine's own interpreter (bpy; "
                             "implies --backend blender in real use)")
    parser.add_argument("--edits", type=int, default=20)
    parser.add_argument("--root", default=None,
                        help="where the engines keep their journals "
                             "(a temp dir by default)")
    parser.add_argument("--out", default=None,
                        help="write the results here as JSON")
    args = parser.parse_args(argv)

    if args.backend == "blender" and not args.python:
        print("the blender backend needs --python (a python that imports "
              "bpy); refusing to guess one", file=sys.stderr)
        return 2

    import tempfile

    tmp = None
    if args.root:
        root = Path(args.root)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="resident-bench-")
        root = Path(tmp.name)
    root.mkdir(parents=True, exist_ok=True)

    base = bench_recipe()
    edits = scripted_edits(base, args.edits)

    result = {
        "backend": args.backend,
        "python": args.python or sys.executable,
        "edits": args.edits,
        "box_at_start": box_state(),
    }

    # interleaved: batch i, warm i — contention falls on both sides
    warm_engine = make_engine(root / "warm", args.backend, args.python)
    batch_waits = []
    try:
        warm_engine.generate_stage(request_for(base, -1))  # the load, once
        warm_waits = []
        for i, edited in enumerate(edits):
            batch_engine = make_engine(
                root / "batch" / f"task-{i:02d}", args.backend, args.python)
            try:
                batch_waits.append(
                    batch_engine.generate_stage(
                        request_for(edited, i)).wall_ms)
            finally:
                batch_engine.stop()
            warm_waits.append(
                warm_engine.generate_stage(request_for(edited, i)).wall_ms)
        warm = {
            "starts": warm_engine.stats()["restarts"] + 1,
            "builder_wait": summarize(warm_waits),
        }
    finally:
        warm_engine.stop()
    batch = {"starts": args.edits, "builder_wait": summarize(batch_waits)}

    crash = run_crash_recovery(
        root / "crash", edits, backend=args.backend, python=args.python)

    result.update({
        "warm": warm,
        "batch": batch,
        "crash_recovery": crash,
        "box_at_end": box_state(),
    })

    warm_p50 = warm["builder_wait"]["p50"]
    batch_p50 = batch["builder_wait"]["p50"]
    print(f"backend={args.backend} edits={args.edits} "
          f"load={result['box_at_start'].get('loadavg')}")
    print(f"{'':14}{'p50 ms':>10}{'p95 ms':>10}{'max ms':>10}{' starts':>9}")
    print(f"{'batch':14}"
          f"{batch['builder_wait']['p50']:>10}"
          f"{batch['builder_wait']['p95']:>10}"
          f"{batch['builder_wait']['max']:>10}{batch['starts']:>9}")
    print(f"{'warm':14}"
          f"{warm['builder_wait']['p50']:>10}"
          f"{warm['builder_wait']['p95']:>10}"
          f"{warm['builder_wait']['max']:>10}{warm['starts']:>9}")
    print(f"builder wait p50, batch vs warm: {batch_p50} -> {warm_p50} ms "
          f"({batch_p50 / warm_p50:.1f}x)")
    print(f"crash recovery: kill -9 after {crash['edits_before_kill']} "
          f"edits -> next result in {crash['recovery_ms']} ms "
          f"(bytes identical: {crash['bytes_identical']}, "
          f"digest identical: {crash['digest_identical']})")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"results: {out}")

    if tmp is not None:
        tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
