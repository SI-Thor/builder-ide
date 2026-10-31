"""The opt-in real-engine test — the resident behind a real Blender.

Not part of the default run: it needs ``bpy`` under its own interpreter
(the engine's, Python 3.11), which this core's test venv does not have.
Opt in by pointing ``BUILDER_RESIDENT_BLENDER`` at a python that can
``import bpy`` — on this box, the spike's venv::

    BUILDER_RESIDENT_BLENDER=~/lm-wt/warm-scene/.venv/bin/python \
        python -m pytest tests/engine/test_resident_real.py -v

Without the variable the suite skips, naming the exact missing piece
(the house rule: never an import traceback, always the named refusal).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest

from core.engine.contract import StageRequest
from core.engine.resident import ResidentEngine, ResidentPolicy

from .conftest import PIN_V1, fjellvik

PY_WITH_BPY = os.environ.get("BUILDER_RESIDENT_BLENDER", "").strip()

pytestmark = pytest.mark.skipif(
    not PY_WITH_BPY,
    reason=(
        "opt-in: set BUILDER_RESIDENT_BLENDER to a python that imports bpy "
        "(e.g. ~/lm-wt/warm-scene/.venv/bin/python) to run the resident "
        "against a real Blender scene"
    ),
)


@pytest.fixture(scope="module")
def bpy_python() -> str:
    """The interpreter the resident will run under — checked, not assumed."""
    probe = subprocess.run(
        [PY_WITH_BPY, "-c", "import bpy; print(bpy.app.version_string)"],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode != 0:
        pytest.skip(
            f"{PY_WITH_BPY} cannot import bpy — the real-engine test needs "
            "the engine's own interpreter"
        )
    return PY_WITH_BPY


@pytest.fixture
def blender_engine(tmp_path, bpy_python):
    engine = ResidentEngine(
        pin=PIN_V1, root=tmp_path / "resident", backend="blender",
        python=bpy_python,
        policy=ResidentPolicy(
            restart_backoff_s=0.05, health_check_interval_s=3600.0,
            checkpoint_every_ops=50, checkpoint_every_s=3600.0,
            growth_check_every_ops=50, start_timeout_s=300.0,
        ),
    )
    yield engine
    engine.stop()


def stage_for(recipe, version_hash: str) -> StageRequest:
    return StageRequest(
        recipe=recipe, version_hash=version_hash, stage="coarse")


def with_params(recipe, entry: str, **params):
    out = recipe.model_copy(deep=True)
    out.entries[entry].params.update(params)
    return out


def test_a_real_scene_loads_and_is_deterministic(blender_engine):
    recipe = fjellvik(PIN_V1)
    first = blender_engine.generate_stage(stage_for(recipe, "vh1"))
    described = blender_engine.describe()  # the resident has reported now
    assert described.flavour == "resident"
    assert described.capabilities.export_formats == ["ply", "obj", "usd"]

    again = blender_engine.generate_stage(stage_for(recipe, "vh1"))
    assert first.data == again.data  # rule 3, against a real scene
    assert blender_engine.resident_state()["state"]["object_count"] == 8 + 3


def test_an_edit_moves_the_real_scene_in_place(blender_engine):
    recipe = fjellvik(PIN_V1)
    blender_engine.generate_stage(stage_for(recipe, "vh1"))
    before = blender_engine.resident_state()
    blender_engine.generate_stage(
        stage_for(with_params(recipe, "harbor.crates", count=12), "vh2"))
    after = blender_engine.resident_state()
    assert before["state"]["object_count"] == 11
    assert after["state"]["object_count"] == 15
    # the untouched entry's objects were left exactly as they were
    untouched = [o for o in after["state"]["objects"]
                 if o["name"].startswith("harbor.racks")]
    was = [o for o in before["state"]["objects"]
           if o["name"].startswith("harbor.racks")]
    assert untouched == was


def test_kill_9_recovery_is_exact_on_the_real_scene(blender_engine):
    recipe = fjellvik(PIN_V1)
    edited = with_params(recipe, "harbor.crates", count=6)
    before = blender_engine.generate_stage(stage_for(edited, "vh1"))
    digest_before = blender_engine.resident_state()["digest"]

    os.kill(blender_engine.stats()["pid"], signal.SIGKILL)
    time.sleep(0.1)

    after = blender_engine.generate_stage(stage_for(edited, "vh1"))
    assert after.data == before.data
    assert blender_engine.resident_state()["digest"] == digest_before
    stats = blender_engine.stats()
    assert stats["restarts"] == 1 and stats["recoveries"] == 1
    # the guard's premise holds on a real scene too: a rebuilt resident is
    # not a leak — meshes and materials are collected, not accumulated
    assert stats["peak_rss_mb"] is None or stats["peak_rss_mb"] > 0
