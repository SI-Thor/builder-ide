"""The stage cache and partial regeneration — on the **real v2 venv**.

Opt-in, like the M1 real-engine run:

    .venv/bin/python -m pytest tests/engine/test_stagecache_real.py -m engine -q

The default engine home is the round-2 venv (`~/lm-wt/v2-next` — the
working code and patches of `docs/research/engine-round2.md`, used
read-only); `BUILDER_V2_HOME` points elsewhere (the unpatched
`~/lm-wt/v2-thor` runs the same object generators). Skips, never fails,
when the venv is not on the box — the named missing piece is printed.

What this run proves that the doubles cannot: the cache's hits are real
byte-identical traced graphs, the misses really charge the engine, and the
dirty-set contract holds on engine bytes an upstream CLI produced — a seed
edit re-traces exactly the one entry (the sibling's generator chain is
asked for **once**, counted at the subprocess boundary), and re-editing
back to a previous seed is a **hit**, because the content key remembers it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from core.engine.infinigen1 import CommandResult, SubprocessRunner
from core.engine.infinigen2 import Infinigen2Engine
from core.engine.regen import Regenerator
from core.engine.stagecache import StageCache
from core.engine.graph import GraphStore
from core.records import Actor, GeneratorRef, Op, Recipe, RecipeEntry
from core.recipe.ledger import InMemoryLedger
from core.recipe.store import RecipeStore
from core.engine.venv2 import Venv2Runtime

pytestmark = pytest.mark.engine

ACTOR = Actor(kind="owner", id="casey")

#: The box's own generator resolution (the same table the M1 real run
#: used; each chain traces clean at RANDOM_CONTROL).
GENERATORS = {
    "crates": "storage_cabinet_with_door_rand",
    "racks": "storage_cell_shelf_rand",
}


def _box_state() -> str:
    parts = []
    for argv in (["uptime"],):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                parts.append(out.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return " | ".join(parts) or "state unavailable"


class CountingRunner(SubprocessRunner):
    """The real subprocesses, counted — the proof a hit never runs one."""

    def __init__(self) -> None:
        super().__init__()
        self.argvs: list[list[str]] = []

    def run(self, argv, *, cwd=None) -> CommandResult:
        argv = [str(a) for a in argv]
        self.argvs.append(argv)
        return super().run(argv, cwd=cwd)

    def traces_of(self, chain_word: str) -> int:
        return sum(
            1
            for argv in self.argvs
            if "--trace" in argv and chain_word in argv
        )


@pytest.fixture(scope="module")
def venv_home() -> Path:
    home = Path(os.environ.get(
        "BUILDER_V2_HOME", str(Path("~/lm-wt/v2-next").expanduser())
    )).expanduser()
    if not (home / ".venv" / "bin" / "python").is_file():
        pytest.skip(
            f"the v2 venv is not at {home} (set BUILDER_V2_HOME to point "
            "elsewhere); without it there is no engine to regenerate with"
        )
    return home


@pytest.fixture(scope="module")
def world(tmp_path_factory, venv_home: Path):
    runner = CountingRunner()
    runtime = Venv2Runtime(
        python=venv_home / ".venv" / "bin" / "python",
        generators=GENERATORS,
        output_dir=tmp_path_factory.mktemp("sc-engine"),
        repo=venv_home / "src" / "infinigen-upstream",
        repo_name="princeton-vl/infinigen",
        runner=runner,
    )
    pin = runtime.engine_pin()
    engine = Infinigen2Engine(pin=pin, runtime=runtime)

    store = RecipeStore(ledger=InMemoryLedger(), require_schema=False)
    store.create_recipe(
        Recipe(
            id="rcp_fjellvik", name="Fjellvik", engine_pin=pin,
            entries={
                "harbor.crates": RecipeEntry(
                    path="harbor.crates", kind="prop_set", seed=42,
                    generator=GeneratorRef(
                        module="infinigen_thor.structures", func="crates",
                        variant=None, rev=pin.commit),
                    params={"count": 8}),
                "harbor.racks": RecipeEntry(
                    path="harbor.racks", kind="prop_set", seed=43,
                    generator=GeneratorRef(
                        module="infinigen_thor.structures", func="racks",
                        variant=None, rev=pin.commit),
                    params={"count": 3}),
            },
        ),
        ACTOR,
    )
    root = tmp_path_factory.mktemp("sc-world")
    regen = Regenerator(
        engine=engine, store=store,
        cache=StageCache(root / "cache", max_bytes=512 * 1024 * 1024),
        graphs=GraphStore(root / "graphs"),
    )
    return {"regen": regen, "store": store, "runner": runner,
            "engine": engine, "pin": pin}


def _edit(world, base: str, *ops: Op, message: str) -> str:
    return world["store"].apply_edit(
        base, list(ops), author=ACTOR, message=message).id


def test_the_real_flow_full_then_partial_then_a_hit_again(world):
    regen, runner = world["regen"], world["runner"]

    # 1. the first regeneration generates both entries for real
    first = regen.regenerate("ver_0001", "ver_0001")
    assert first.verdicts() == {"hit": 0, "miss": 2, "partial": 0}
    graphs = [o.graph for o in first.entries if o.graph]
    assert graphs and all(row["nodes"] > 10 for row in graphs), \
        "the recorded stages are not real traced graphs"

    # 2. a seed edit re-traces exactly the touched entry: the sibling's
    #    generator chain is asked for once in this whole session
    regen.cache.reset_stats()
    reseeded = _edit(world, "ver_0001",
                     Op(op="set", path="harbor.crates.seed", value=52),
                     message="reseed crates")
    second = regen.regenerate("ver_0001", reseeded)
    verdicts = {o.entry: o.verdict for o in second.entries}
    assert verdicts == {"harbor.crates": "miss", "harbor.racks": "hit"}
    assert runner.traces_of("storage_cabinet_with_door_rand") == 2
    assert runner.traces_of("storage_cell_shelf_rand") == 1
    crates_now = next(o for o in second.entries if o.entry == "harbor.crates")
    crates_before = next(o for o in first.entries if o.entry == "harbor.crates")
    assert crates_now.key != crates_before.key       # the key moved honestly
    assert crates_now.produced_bytes != crates_before.produced_bytes

    # 3. editing back to the previous seed is a HIT — the content key
    #    remembers the earlier stage, byte for byte
    regen.cache.reset_stats()
    back = _edit(world, reseeded,
                 Op(op="set", path="harbor.crates.seed", value=42),
                 message="and back again")
    third = regen.regenerate(reseeded, back)
    verdicts = {o.entry: o.verdict for o in third.entries}
    assert verdicts == {"harbor.crates": "hit", "harbor.racks": "hit"}
    assert runner.traces_of("storage_cabinet_with_door_rand") == 2  # unchanged
    assert third.cache["hit_rate"] == 1.0

    # the hit serves the very bytes the first run generated
    hit = next(o for o in third.entries if o.entry == "harbor.crates")
    served = regen.cache.peek(hit.key)
    first_run = next(
        o for o in first.entries if o.entry == "harbor.crates")
    assert served.data == regen.cache.peek(first_run.key).data
    assert served.mechanism  # provenance kept: what produced these bytes


def test_the_real_stages_are_procfunc_graphs_the_diff_can_read(world):
    regen = world["regen"]
    head = world["store"].list_versions("rcp_fjellvik")[-1].id
    root = world["store"].list_versions("rcp_fjellvik")[0].id
    report = regen.regenerate(root, head)  # all hits; no engine work
    assert report.verdicts()["hit"] == 2
    for outcome in report.entries:
        assert outcome.graph is not None
        assert outcome.graph["nodes"] > 10


def test_the_report_records_the_box_state_and_the_engine(world):
    """The standing rule: a number is recorded with the box's state beside
    it. The report names the engine and its pin; the printout carries the
    state for the run's log."""
    report = world["regen"].regenerate("ver_0001", "ver_0001")
    assert report.pin == (
        f"{world['pin'].repo}@{world['pin'].commit}")
    assert "venv-subprocess" in report.engine
    print(f"\n[stage-cache real] box state: {_box_state()}")
    print(f"[stage-cache real] engine: {report.engine}")
    for outcome in report.entries:
        print(
            f"[stage-cache real] {outcome.entry}: {outcome.verdict} · "
            f"{outcome.produced_bytes or outcome.reused_bytes} bytes · "
            f"{(outcome.graph or {}).get('nodes', '?')} nodes"
        )
