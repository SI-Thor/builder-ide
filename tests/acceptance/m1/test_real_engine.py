"""The M1 session with the **real engine** behind the render rung (opt-in).

The plain suite keeps the fake engine (fast, deterministic, no engine on
the box required — `seats/engine.py::SPEC`). This module is the other run:

    .venv/bin/python -m pytest tests/acceptance/m1 -m engine -q

`BUILDER_ENGINE` is set to `real_engine_spec(home)` — the **v2 venv on
this box** (`~/lm-wt/v2-thor`, read-only; `BUILDER_V2_HOME` overrides) —
so the session's render steps ask Infinigen 2.0 for real: each render is
the subject entry's generator chain through ``render_cycles`` on the
Thor's GPU, at rung 2 of the ladder (854×480, 16 samples — a step is
seconds-to-minutes, not hours). The session performs the **explicit pin
edit** first (X R9); every render lands in the ledger with an artifact
hash, the measured wall, and the engine's provenance and licence row.

What this run asserts, beyond the session's own steps:

* every ``render.completed`` artifact is a real PNG (magic bytes, real
  size) with its measured wall in the event;
* the work order's landed preview and the gate's render rung produced
  real images too;
* the asset carries the venv's own licence row (BSD-3 + dependency terms)
  and provenance naming the resolved generator;
* the recipe's pin is the engine's interrogated pin, and the swap was one
  explicit edit;
* a stage generated twice through the venv is byte-identical (the
  stage-hit invariant, on the real traced graphs).

Skip (not fail) when the venv is not on the box: the named missing piece
is printed, exactly like the engine seam's own refusals.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from driver import build_world, play, teardown_world
from seats.engine import DEFAULT_V2_HOME, real_engine_spec

pytestmark = pytest.mark.engine

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _box_state() -> str:
    """The standing rule: a timing is recorded with the box's state beside
    it (CLAUDE.md). Best effort — a missing tool is not a failure."""
    parts = []
    for argv in (["uptime"],
                 ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
                  "--format=csv,noheader"]):
        try:
            out = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                parts.append(out.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return " | ".join(parts) or "state unavailable"


@pytest.fixture(scope="module")
def engine_world(tmp_path_factory):
    home = tmp_path_factory.mktemp("m1-engine-home") / "builder-ide"
    v2_home = Path(
        os.environ.get("BUILDER_V2_HOME", str(DEFAULT_V2_HOME))).expanduser()
    if not (v2_home / ".venv" / "bin" / "python").is_file():
        pytest.skip(
            f"the v2 venv is not at {v2_home} (set BUILDER_V2_HOME to point "
            "elsewhere); the real-engine run has no engine to render with — "
            "the fake-engine run is the default suite"
        )
    run_dir = Path(__file__).resolve().parent / "run" / "engine"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    os.environ["BUILDER_ENGINE"] = json.dumps(
        real_engine_spec(home, v2_home=v2_home))
    world = None
    try:
        world = build_world(home, run_dir)
        world.artifacts["box_state"] = _box_state()
        yield world
    finally:
        if world is not None:
            teardown_world(world)
        os.environ.pop("BUILDER_ENGINE", None)


def _session(engine_world):
    """The played session, once per module (the script is the fixture)."""
    if "steps" not in engine_world.artifacts:
        ses = play(engine_world)
        engine_world.artifacts["steps"] = ses.steps
        engine_world.artifacts["session"] = ses
        table = (ses.table() + "\n\nbox state at the run: "
                 + engine_world.artifacts["box_state"] + "\n")
        (engine_world.run_dir / "steps.txt").write_text(table, encoding="utf-8")
    return engine_world.artifacts["session"]


def test_the_session_plays_end_to_end_on_the_real_engine(engine_world):
    ses = _session(engine_world)
    failed = [s for s in ses.steps if not s.ok]
    assert not failed, f"{len(failed)} failed steps:\n{ses.table()}"
    # the explicit pin edit is a step of this run, and it held
    repin = next(s for s in ses.steps if s.name == "engine-repin")
    assert repin.ok


def test_every_render_step_served_the_real_engine(engine_world):
    ses = _session(engine_world)
    render_steps = [
        s for s in ses.steps
        if any(b.endswith(("engine(render)", "engine(gate-rungs)"))
               for b in s.backends)
    ]
    assert render_steps, "no engine-labelled steps in the session"
    for step in render_steps:
        assert any(b.startswith("real:engine(") for b in step.backends), \
            f"{step.act}/{step.name} was not served by the real engine"


def test_every_render_produced_a_real_image_with_its_measured_wall(engine_world):
    _session(engine_world)  # the session must have played
    door = engine_world.door
    events = door.raw_events(0, ["render.completed"])
    assert len(events) >= 2, "the two sealed bets rendered nothing"
    for ev in events:
        payload = ev.payload
        assert payload["engine_flavour"] == "infinigen-2-procfunc", payload
        wall = payload.get("wall_ms")
        assert wall is not None and wall > 0, \
            f"render {payload['job_id']} has no measured wall"
        sha = payload["artifact"]["sha256"]
        data = door.store.artifacts.get(sha)  # hash-verified read
        assert data.startswith(PNG_MAGIC), f"{sha} is not a PNG"
        assert payload["artifact"]["bytes"] > 10_000, \
            f"{sha} is {len(data)} bytes — not a real frame"
    # and the work order's landed preview is a real image too (the morning
    # has since kept it — the preview artifact is the one that landed)
    board = {w["id"]: w for w in engine_world.spec.work_orders()}
    wo = board[engine_world.stamps["wo"]]
    preview = door.store.artifacts.get(wo["preview"]["sha256"])
    assert preview.startswith(PNG_MAGIC)
    # the gate's own render rung (the critic acceptance) rendered through
    # the same seam — its verdict carries a real artifact
    landed_events = door.raw_events(0, ["wo.landed"])
    critics = [
        c for e in landed_events
        for c in (e.payload.get("gate", {}) or {}).get("checks", [])
        if c.get("check") == "critic"
    ]
    assert critics, "the gate's render rung did not run"
    verdict = critics[0]["verdict"]
    assert verdict["engine"].startswith("infinigen 2.0 + procfunc")
    assert verdict["artifact"]["bytes"] > 10_000


def test_the_ledger_carries_the_provenance_and_the_licence_row(engine_world):
    _session(engine_world)
    assets = engine_world.spec.assets()["assets"]
    assert assets, "the library is empty"
    row = next(
        a for a in assets
        if ((a.get("provenance") or {}).get("generator") or {})
        .get("method", "").startswith("infinigen")
    )
    generator = row["provenance"]["generator"]
    assert generator["model_id"].startswith("infinigen@")
    assert generator["resolved_generator"], "the name resolution is not recorded"
    assert generator["resolution"] == "480p" and generator["samples"] == 16
    licence = row["licence"]
    assert licence["spdx"] == "BSD-3-Clause", licence
    terms = " ".join(licence["dependency_terms"])
    assert "procfunc 0.37.0" in terms and "bpy 4.2.0" in terms
    assert "GPL-3.0" in terms and "not the images" in terms, \
        "the Blender term must say what it covers"


def test_the_recipe_is_pinned_to_the_engine_that_rendered_it(engine_world):
    _session(engine_world)
    engine_pin = engine_world.engine.engine.describe().pin
    document = engine_world.recipe.recipe_document()
    assert document.engine_pin == engine_pin
    # and the swap was one explicit edit (X R9), diffable in the store:
    # every op touches the pin, nothing else moved
    repin_version = engine_world.stamps["engine_repin_version"]
    ops = engine_world.recipe.diff_ops(
        engine_world.recipe.root_version, repin_version)
    assert ops and all(op["path"].split(".")[0] == "engine_pin" for op in ops), \
        str(ops)


def test_a_stage_generated_twice_through_the_venv_is_byte_identical(engine_world):
    """The stage-hit invariant on the real engine: two generations of the
    same stage produce identical bytes (the normalized traced graphs — the
    two wobbles the CLI leaves in graph.json are removed adapter-side)."""
    from core.engine.contract import StageRequest

    _session(engine_world)
    store = engine_world.recipe.store
    head = engine_world.recipe.head("main")
    request = StageRequest(
        recipe=store.get_document(head),
        version_hash=store.get_version(head).root_hash,
        stage="objects",
    )
    engine = engine_world.engine.engine
    first = engine.generate_stage(request)
    second = engine.generate_stage(request)
    assert first.data == second.data, \
        "the real traced stage is not byte-stable — the gate's rebuild rung would fail"
    assert first.stage_key == second.stage_key
    assert first.artifact["bytes"] > 1000  # a real graph, not a token
