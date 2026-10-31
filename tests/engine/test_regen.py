"""Partial regeneration — the dirty-set contract, end to end, on doubles.

The regenerator is the contract's driver: ``DIRTY.md`` §1 decides which
entries re-evaluate, §2 decides what a hit may skip (the engine is never
called for one), §3 decides the mechanism per entry (re-execute under the
entry's ops when the engine splices, regenerate the one entry when it
does not), and the graph store reports what re-executed inside the stage.

The doubles: :class:`GraphRuntime` (a procfunc-shaped engine behind
:class:`Infinigen2Engine`) earns the partial path for real — trace, then
replace-in-place; the fake engine is the honest full-reeval engine; the
resident engine is the scene server, warm behind the same seam.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.engine import FakeEngine, Infinigen2Engine, ResidentEngine
from core.engine.contract import StageRequest
from core.engine.graph import GraphStore
from core.engine.regen import Regenerator
from core.engine.stagecache import StageCache
from core.records import Actor, EnginePin, GeneratorRef, Op, Recipe, RecipeEntry
from core.recipe.ledger import InMemoryLedger
from core.recipe.store import RecipeStore

from .conftest import PIN_V2, GraphRuntime

ACTOR = Actor(kind="owner", id="casey")


def _recipe(pin: EnginePin, *, racks_seedless: bool = False) -> Recipe:
    return Recipe(
        id="rcp_fjellvik", name="Fjellvik", engine_pin=pin,
        seeds={"harbor": 42},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates", kind="prop_set", seed=7,
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="crates",
                    variant=None, rev=pin.commit),
                params={"count": 8},
            ),
            "harbor.racks": RecipeEntry(
                path="harbor.racks", kind="prop_set",
                seed=None if racks_seedless else 9,
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="racks",
                    variant=None, rev=pin.commit),
                params={"count": 3},
            ),
        },
    )


def _store(recipe: Recipe) -> RecipeStore:
    store = RecipeStore(ledger=InMemoryLedger(), require_schema=False)
    store.create_recipe(recipe, ACTOR)
    return store


def _regenerator(tmp_path: Path, *, pin: EnginePin = PIN_V2,
                 runtime=None, engine=None):
    runtime = runtime or GraphRuntime()
    engine = engine or Infinigen2Engine(pin=pin, runtime=runtime)
    store = _store(_recipe(pin))
    return (
        Regenerator(
            engine=engine, store=store,
            cache=StageCache(tmp_path / "cache"),
            graphs=GraphStore(tmp_path / "graphs"),
        ),
        engine,
        runtime,
        store,
    )


def _edit(store: RecipeStore, base: str, *ops: Op, message: str) -> str:
    return store.apply_edit(base, list(ops), author=ACTOR, message=message).id


def _by_entry(report):
    return {outcome.entry: outcome for outcome in report.entries}


# ------------------------------------------------------------------ the flow


def test_the_first_regeneration_generates_and_caches_every_entry(tmp_path):
    regen, engine, runtime, store = _regenerator(tmp_path)
    report = regen.regenerate("ver_0001", "ver_0001")
    assert report.verdicts() == {"hit": 0, "miss": 2, "partial": 0}
    assert len(runtime.ops) == 2  # one scoped trace per entry
    assert [op[0] for op in runtime.ops] == ["trace", "trace"]
    assert report.entries[0].graph is not None  # the graphs are stored


def test_an_edit_reexecutes_the_touched_entry_and_hits_its_sibling(tmp_path):
    """The contract's whole point: one param edit, one re-execution under
    the ops (the graph-edit path), one cache hit that never reaches the
    engine, and a graph diff that says what moved inside the stage."""
    regen, engine, runtime, store = _regenerator(tmp_path)
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")

    report = regen.regenerate("ver_0001", head)
    by_entry = _by_entry(report)
    assert report.verdicts() == {"hit": 1, "miss": 0, "partial": 1}

    crates = by_entry["harbor.crates"]
    assert crates.verdict == "partial"
    assert crates.request_key  # the engine-reported key, kept as provenance
    assert crates.graph_diff is not None
    diff = crates.graph_diff
    assert diff["changed"] == 1 and diff["added"] == 0
    assert diff["closure_nodes"] == 2      # the edited draw and its join
    assert diff["splice_safe"] is True

    racks = by_entry["harbor.racks"]
    assert racks.verdict == "hit" and racks.reused_bytes > 0

    # the engine saw exactly one replacement — and no second trace
    assert ("replace", ["harbor.crates"], [("count", 20)]) in [
        (op[0], op[1], op[2]) for op in runtime.ops if op[0] == "replace"
    ]
    assert [op[0] for op in runtime.ops].count("trace") == 2  # only the first run


def test_a_hit_is_byte_identical_to_a_fresh_generation(tmp_path):
    """§1.9's invariant, demonstrated: the hit's bytes are exactly what the
    engine would produce again for that entry at this version."""
    regen, engine, runtime, store = _regenerator(tmp_path)
    regen.regenerate("ver_0001", "ver_0001")
    regen.cache.reset_stats()  # a clean denominator for the measured run
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    report = regen.regenerate("ver_0001", head)
    cached = report.cache

    fresh = engine.generate_stage(StageRequest(
        recipe=store.get_document(head),
        version_hash=store.get_version(head).root_hash,
        stage="entry:harbor.racks", entries=["harbor.racks"]))
    hit = _by_entry(report)["harbor.racks"]
    outcome_key = hit.key
    from core.engine.stagecache import StageCache as _SC
    assert _SC(tmp_path / "cache").peek(outcome_key).data == fresh.data
    assert cached["hit_rate"] == 0.5  # 1 hit of 2 asks, this run


def test_a_seed_edit_retraces_the_entry_the_ops_are_not_spliceable(tmp_path):
    regen, engine, runtime, store = _regenerator(tmp_path)
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.seed", value=8),
                 message="reseed crates")
    report = regen.regenerate("ver_0001", head)
    by_entry = _by_entry(report)
    assert by_entry["harbor.crates"].verdict == "miss"
    assert any("not param-shaped" in r for r in by_entry["harbor.crates"].reasons)
    assert by_entry["harbor.racks"].verdict == "hit"


def test_a_recipe_seed_edit_dirties_a_fallback_seeded_entry_by_key_drift(tmp_path):
    """No op addressed racks, but racks runs on the recipe's seed — the
    effective key moved, so racks re-generates while crates (own seed) is a
    hit. Content decides, not op shape (DIRTY.md §1)."""
    runtime = GraphRuntime()
    engine = Infinigen2Engine(pin=PIN_V2, runtime=runtime)
    store = _store(_recipe(PIN_V2, racks_seedless=True))
    regen = Regenerator(
        engine=engine, store=store,
        cache=StageCache(tmp_path / "cache"),
        graphs=GraphStore(tmp_path / "graphs"))
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="seeds.harbor", value=43),
                 message="reseed the harbor")
    report = regen.regenerate("ver_0001", head)
    by_entry = _by_entry(report)
    assert by_entry["harbor.racks"].verdict == "miss"
    assert by_entry["harbor.crates"].verdict == "hit"


def test_a_new_entry_misses_and_a_removed_entry_leaves_the_report(tmp_path):
    regen, *_ = _regenerator(tmp_path)
    regen.regenerate("ver_0001", "ver_0001")
    store: RecipeStore = regen._store
    head = store.apply_edit("ver_0001", [
        Op(op="remove", path="harbor.racks"),
        Op(op="add", path="harbor.desk", value={
            "path": "harbor.desk", "kind": "prop_set", "seed": 5,
            "generator": {"module": "infinigen_thor.structures",
                          "func": "crates", "variant": None,
                          "rev": PIN_V2.commit},
            "params": {"count": 1}}),
    ], author=ACTOR, message="swap the racks for a desk").id
    report = regen.regenerate("ver_0001", head)
    by_entry = _by_entry(report)
    assert set(by_entry) == {"harbor.crates", "harbor.desk"}
    assert by_entry["harbor.desk"].verdict == "miss"
    assert by_entry["harbor.crates"].verdict == "hit"


# ------------------------------------------------------------------ the engines


def test_the_fake_engine_regenerates_in_full_and_says_why(tmp_path):
    """The fake has no graph-edit mechanism (its capability says so), so a
    touched entry regenerates through the scoped request — the honest v1
    shape — and the reason is in the outcome."""
    from core.engine.fake import FAKE_PIN

    engine = FakeEngine(PIN_V2)
    store = _store(_recipe(PIN_V2))
    regen = Regenerator(engine=engine, store=store,
                        cache=StageCache(tmp_path / "cache"))
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    report = regen.regenerate("ver_0001", head)
    crates = _by_entry(report)["harbor.crates"]
    assert crates.verdict == "miss"
    assert any("mechanism" in r for r in crates.reasons)
    assert _by_entry(report)["harbor.racks"].verdict == "hit"
    # no graph store → no graph rows, and the report says so by omission
    assert crates.graph is None and crates.graph_diff is None


def test_the_venv_boundary_falls_back_to_a_scoped_retrace(tmp_path):
    """The real venv runtime refuses replace/execute, naming its missing
    piece; the regenerator records the refusal and re-traces the one entry
    — the honest mechanism at that boundary today (DIRTY.md §3)."""
    from core.engine.venv2 import Venv2Runtime
    from .test_venv2 import CliDouble, GENERATORS

    venv_home = tmp_path / "venv"
    bin_ = venv_home / ".venv" / "bin"
    bin_.mkdir(parents=True)
    (bin_ / "python").touch()
    (bin_ / "infinigen").touch()
    runtime = Venv2Runtime(
        python=bin_ / "python", generators=GENERATORS,
        output_dir=venv_home / "engine",
        runner=CliDouble(),
    )
    engine = Infinigen2Engine(pin=runtime.engine_pin(), runtime=runtime)
    store = _store(_recipe(engine.describe().pin))
    regen = Regenerator(engine=engine, store=store,
                        cache=StageCache(tmp_path / "cache"),
                        graphs=GraphStore(tmp_path / "graphs"))
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    report = regen.regenerate("ver_0001", head)
    crates = _by_entry(report)["harbor.crates"]
    assert crates.verdict == "miss"
    assert any("reexecute refused" in r and "re-execution" in r
               for r in crates.reasons)
    assert _by_entry(report)["harbor.racks"].verdict == "hit"


def test_the_resident_scene_server_serves_the_misses_warm(tmp_path):
    """Where the scene server helps (DIRTY.md §6): through the same seam,
    the re-execution reaches a process that already holds the scene."""
    engine = ResidentEngine(pin=PIN_V2, root=tmp_path / "resident",
                            backend="fake")
    store = _store(_recipe(PIN_V2))
    regen = Regenerator(engine=engine, store=store,
                        cache=StageCache(tmp_path / "cache"))
    first = regen.regenerate("ver_0001", "ver_0001")
    assert first.verdicts() == {"hit": 0, "miss": 2, "partial": 0}
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    report = regen.regenerate("ver_0001", head)
    by_entry = _by_entry(report)
    assert by_entry["harbor.crates"].verdict == "partial"
    assert by_entry["harbor.racks"].verdict == "hit"


def test_a_pin_edit_changes_every_key_and_the_old_engine_refuses(tmp_path):
    """The engine-swap gate: one pin edit and every content key moves (the
    cache invalidates honestly); the old engine refuses the re-pinned
    recipe rather than reinterpreting it."""
    regen, engine, runtime, store = _regenerator(tmp_path)
    first = regen.regenerate("ver_0001", "ver_0001")
    old_keys = {outcome.key for outcome in first.entries}

    head = store.apply_edit("ver_0001", [
        Op(op="set", path="engine_pin.commit", value="v2-0002"),
    ], author=ACTOR, message="the explicit pin edit").id

    with pytest.raises(Exception, match="pinned"):
        regen.regenerate("ver_0001", head)

    new_pin = PIN_V2.model_copy(update={"commit": "v2-0002"})
    new_engine = Infinigen2Engine(pin=new_pin, runtime=GraphRuntime())
    new_regen = Regenerator(
        engine=new_engine, store=store,
        cache=StageCache(tmp_path / "cache"),
        graphs=GraphStore(tmp_path / "graphs"))
    report = new_regen.regenerate("ver_0001", head)
    assert report.verdicts() == {"hit": 0, "miss": 2, "partial": 0}
    assert {outcome.key for outcome in report.entries}.isdisjoint(old_keys)


def test_the_engine_may_not_invent_its_own_stage_keys(tmp_path):
    """Contract rule 4, enforced by the caller: an engine reporting a key
    the canonical arithmetic does not produce is refused, because the cache
    would then be keyed by the engine's mood."""

    class WrongKeyEngine(Infinigen2Engine):
        def reexecute(self, request):
            result = super().reexecute(request)
            return result.model_copy(
                update={"stage_key": "sha256:" + "0" * 64})

    runtime = GraphRuntime()
    engine = WrongKeyEngine(pin=PIN_V2, runtime=runtime)
    store = _store(_recipe(PIN_V2))
    regen = Regenerator(engine=engine, store=store,
                        cache=StageCache(tmp_path / "cache"))
    regen.regenerate("ver_0001", "ver_0001")
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    from core.recipe.errors import IntegrityError
    with pytest.raises(IntegrityError, match="rule 4"):
        regen.regenerate("ver_0001", head)


def test_the_report_carries_the_cache_counters_for_the_nightly_measure(tmp_path):
    regen, *_ = _regenerator(tmp_path)
    regen.regenerate("ver_0001", "ver_0001")
    regen.cache.reset_stats()
    store = regen._store
    head = _edit(store, "ver_0001",
                 Op(op="set", path="harbor.crates.params.count", value=20),
                 message="more crates")
    report = regen.regenerate("ver_0001", head)
    assert report.cache["hits"] == 1 and report.cache["misses"] == 1
    assert report.cache["hit_rate"] == 0.5
    assert report.pin == f"{PIN_V2.repo}@{PIN_V2.commit}"
