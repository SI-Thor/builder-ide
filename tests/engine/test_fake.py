"""The fake engine — the seam's test double, on its own terms."""

from __future__ import annotations

import json

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


# ------------------------------------------------------------------ the scope


def _scoped(engine, path, recipe):
    from core.engine.contract import StageRequest

    return engine.generate_stage(StageRequest(
        recipe=recipe, version_hash="sha256:" + "a" * 64,
        stage=f"entry:{path}", entries=[path]))


def test_a_scoped_stage_carries_only_its_entry():
    """The per-entry stage's bytes are a function of the entry's effective
    inputs — exactly what entry_stage_key hashes — so the hit-is-byte-
    identical invariant is demonstrable against the fake."""
    from core.recipe.stagecache import entry_stage_key

    engine = FakeEngine(PIN_V1)
    recipe = fjellvik(PIN_V1)
    stage = _scoped(engine, "harbor.crates", recipe)
    doc = json.loads(stage.data)
    assert list(doc["entries"]) == ["harbor.crates"]
    assert entry_stage_key(
        "harbor.crates", recipe.entries["harbor.crates"], PIN_V1,
        seeds=recipe.seeds,
    )  # the key the regenerator will address this stage by


def test_a_siblings_edit_leaves_a_scoped_stage_byte_identical():
    """The dirty-set contract's first promise, on the fake: an edit inside
    harbor.racks changes neither harbor.crates' bytes nor its key."""
    engine = FakeEngine(PIN_V1)
    base = fjellvik(PIN_V1)
    edited = base.model_copy(deep=True)
    edited.entries["harbor.racks"].params["count"] = 30
    assert _scoped(engine, "harbor.crates", base).data == _scoped(
        engine, "harbor.crates", edited).data


def test_a_recipe_seed_edit_reaches_a_fallback_seeded_entrys_stage():
    """crates carries seed 42 of its own, racks falls back to the recipe's
    seeds — so moving the recipe seed changes racks' scoped bytes (and its
    effective key) while crates' stand still."""
    engine = FakeEngine(PIN_V1)
    base = fjellvik(PIN_V1)
    reseeded = base.model_copy(deep=True)
    reseeded.entries["harbor.racks"].seed = None  # the fallback case
    reseeded.seeds["harbor"] = 99
    assert _scoped(engine, "harbor.crates", base).data == _scoped(
        engine, "harbor.crates", reseeded).data
    assert _scoped(engine, "harbor.racks", base).data != _scoped(
        engine, "harbor.racks", reseeded).data
