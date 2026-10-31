"""The fake engine — the seam's test double, on its own terms."""

from __future__ import annotations

from core.engine import FakeEngine
from core.engine.contract import (
    ExportRequest,
    PreviewRequest,
    StageRequest,
)
from core.engine.fake import FAKE_PIN, entry_digest

from .conftest import PIN_V1, fjellvik


def _preview(engine, *, subject="harbor.crates", rung=2, seed=42,
             resolution="480p", recipe=None, version="sha256:" + "a" * 64):
    return engine.render_preview(PreviewRequest(
        recipe=recipe or fjellvik(PIN_V1), version_hash=version,
        subject=subject, rung=rung, seed=seed, resolution=resolution,
    ))


def _stage(engine, recipe=None):
    return engine.generate_stage(StageRequest(
        recipe=recipe or fjellvik(PIN_V1),
        version_hash="sha256:" + "a" * 64, stage="coarse",
    ))


def test_every_byte_says_what_it_is():
    """A fake that could pass for a render is a fabrication (D §2 02:07) —
    every artifact the fake produces names itself inside its own bytes."""
    engine = FakeEngine(PIN_V1)
    assert b"fake-engine" in engine.render_preview(PreviewRequest(
        recipe=fjellvik(PIN_V1), version_hash="sha256:" + "a" * 64,
        subject="harbor.crates", rung=2, seed=42)).data
    assert b"fake-engine" in engine.export(ExportRequest(
        recipe=fjellvik(PIN_V1), version_hash="sha256:" + "a" * 64,
        format="usda")).data


def test_the_fake_measures_nothing_and_says_so():
    """wall_ms stays None: the fake invents no timing (no plausible zeros)."""
    engine = FakeEngine(PIN_V1)
    preview = _preview(engine)
    stage = _stage(engine)
    assert preview.wall_ms is None
    assert stage.wall_ms is None


def test_previews_are_deterministic_in_the_whole_request():
    engine = FakeEngine(PIN_V1)
    assert _preview(engine).data == _preview(engine).data
    assert _preview(engine, seed=43).data != _preview(engine).data
    assert _preview(engine, rung=1).data != _preview(engine).data
    assert _preview(engine, subject="harbor.racks").data != _preview(engine).data


def test_the_pin_is_in_the_bytes_a_repin_changes_the_output():
    """Re-pinning a project is real work: the fake's outputs change with
    the pin, so a swapped pin can never serve yesterday's bytes."""
    same_recipe_other_pin = fjellvik(PIN_V1).model_copy(
        update={"engine_pin": FAKE_PIN})
    a = _preview(FakeEngine(PIN_V1), recipe=fjellvik(PIN_V1))
    b = _preview(FakeEngine(FAKE_PIN), recipe=same_recipe_other_pin)
    assert a.data != b.data


def test_calls_are_recorded_for_the_seams_own_assertions():
    engine = FakeEngine(PIN_V1)
    _preview(engine, subject="harbor.crates", rung=2, seed=42)
    engine.export(ExportRequest(
        recipe=fjellvik(PIN_V1), version_hash="sha256:" + "a" * 64,
        format="glb"))
    ops = [(c.op, c.subject, c.format) for c in engine.calls]
    assert ("render_preview", "harbor.crates", None) in ops
    assert ("export", None, "glb") in ops


def test_the_entry_digest_helper_reads_the_same_bytes_the_seam_does():
    import json

    engine = FakeEngine(PIN_V1)
    recipe = fjellvik(PIN_V1)
    result = _stage(engine, recipe)
    entries = json.loads(result.data)["entries"]
    assert entries["harbor.crates"] == entry_digest(recipe.entries["harbor.crates"])


def test_the_default_pin_names_no_real_checkout():
    assert "fake" in FAKE_PIN.repo
