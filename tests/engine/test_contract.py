"""The seam's contract — the rules every engine keeps, whichever flavour.

The five rules of `core/engine/contract.py` are asserted here against the
fake and (where the rule crosses the subprocess/procfunc boundary) the two
adapter skeletons. The suite's own headline is the last test: **the engine
swap** — the plan's standing gate (§6) and this branch's pass/fail (plan §3
week-1 item 3): *a recipe written under one engine still replays under the
next, because our schema sits above the engine.*
"""

from __future__ import annotations

import json

import pytest

from core.engine import (
    EnginePinMismatch,
    FakeEngine,
    Infinigen2Engine,
    check_pin,
    expected_stage_key,
)
from core.engine.contract import Engine, StageRequest
from core.recipe.stagecache import stage_cache_key
from core.records import Recipe

from .conftest import PIN_V1, PIN_V2, RecordingRuntime, fjellvik, param_ops


def _stage(engine, recipe: Recipe, version_hash: str, stage: str = "coarse"):
    return engine.generate_stage(
        StageRequest(recipe=recipe, version_hash=version_hash, stage=stage)
    )


def test_the_seam_is_a_protocol_any_engine_satisfies():
    fake = FakeEngine(PIN_V1)
    v2 = Infinigen2Engine(pin=PIN_V2, runtime=RecordingRuntime())  # noqa: F841
    assert isinstance(fake, Engine)
    assert isinstance(v2, Engine)


# --------------------------------------------------------------------- rule 1–2


def test_the_pin_reported_drops_straight_into_a_recipe():
    """Rule 1: the pin is §1.1's EnginePin verbatim — the descriptor's pin
    IS a valid recipe pin, so reporting and pinning cannot drift apart."""
    engine = FakeEngine(PIN_V1)
    pin = engine.describe().pin
    recipe = fjellvik(pin)
    assert recipe.engine_pin == pin


def test_an_engine_refuses_a_recipe_pinned_elsewhere():
    """Rule 2: a mismatch is a refusal, never a silent reinterpretation
    (X R9) — and the refusal names both pins."""
    engine = FakeEngine(PIN_V1)
    with pytest.raises(EnginePinMismatch) as caught:
        _stage(engine, fjellvik(PIN_V2), "sha256:" + "a" * 64)
    message = str(caught.value)
    assert PIN_V2.commit in message and PIN_V1.commit in message
    assert "silent" in message


def test_the_pin_check_compares_the_whole_pin():
    """The config hash is load-bearing (RV patch 13): an engine with the
    same commit but a different config bundle is still a different engine."""
    drifted = PIN_V1.model_copy(update={"config": "sha256:deadbeef00"})
    with pytest.raises(EnginePinMismatch):
        check_pin(FakeEngine(PIN_V1).describe(), fjellvik(drifted))


# --------------------------------------------------------------------- rule 3


def test_same_request_same_bytes():
    """Rule 3: determinism is the stage-hit invariant (§1.9) and what job
    dedup converges on (§5.3)."""
    engine = FakeEngine(PIN_V1)
    recipe = fjellvik(PIN_V1)
    a = _stage(engine, recipe, "sha256:" + "a" * 64)
    b = _stage(engine, recipe, "sha256:" + "a" * 64)
    assert a.data == b.data
    assert a.stage_key == b.stage_key
    assert a.artifact["sha256"] == b.artifact["sha256"]


def test_different_content_changes_the_bytes_and_only_the_hash_does_not():
    """Content determines the bytes; the version hash determines the key.
    Two versions of identical content produce identical stage bytes (what
    job dedup converges on, §5.3) but different keys (the spec's key is a
    function of the version, §1.9) — both facts are the contract."""
    engine = FakeEngine(PIN_V1)
    recipe = fjellvik(PIN_V1)
    other = fjellvik(PIN_V1, crates=9)
    a = _stage(engine, recipe, "sha256:" + "a" * 64)
    b = _stage(engine, other, "sha256:" + "a" * 64)
    assert a.data != b.data

    same_content = _stage(engine, recipe, "sha256:" + "b" * 64)
    assert same_content.data == a.data
    assert same_content.stage_key != a.stage_key


# --------------------------------------------------------------------- rule 4


def test_the_stage_key_is_the_one_canonical_function():
    """Rule 4: the key an engine reports is the key §1.9's function
    computes over (version hash, pin, stage, dep keys) — no engine keeps
    its own arithmetic."""
    engine = FakeEngine(PIN_V1)
    request = StageRequest(
        recipe=fjellvik(PIN_V1),
        version_hash="sha256:" + "a" * 64,
        stage="coarse",
        dep_keys=["sha256:" + "c" * 64],
    )
    result = engine.generate_stage(request)
    assert result.stage_key == stage_cache_key(
        request.version_hash, engine.describe().pin, "coarse", request.dep_keys
    )
    assert result.stage_key == expected_stage_key(request, engine.describe())


def test_the_artifact_descriptor_is_the_cores_shape():
    """The result's artifact is `{sha256, kind, bytes}` — core.artifacts'
    descriptor, so it can ride an audit event unchanged (§1.8)."""
    result = _stage(FakeEngine(PIN_V1), fjellvik(PIN_V1), "sha256:" + "a" * 64)
    assert set(result.artifact) == {"sha256", "kind", "bytes"}
    assert result.artifact["bytes"] == len(result.data)


# --------------------------------------------------------------------- rule 5


def test_reexecution_honours_the_dirty_set_contract():
    """§1.1's contract: an edit re-evaluates only the dirty set. The fake's
    stage data carries one digest per entry, so the untouched entry's bytes
    are *visible* staying identical."""
    engine = FakeEngine(PIN_V1)
    base_recipe = fjellvik(PIN_V1)
    version = "sha256:" + "a" * 64
    base = _stage(engine, base_recipe, version)
    edited_recipe = fjellvik(PIN_V1, crates=9)
    again = engine.reexecute(
        _reexecute_request(edited=edited_recipe, version=version, base=base))
    before = json.loads(base.data)["entries"]
    after = json.loads(again.data)["entries"]
    assert before["harbor.crates"] != after["harbor.crates"]
    assert before["harbor.racks"] == after["harbor.racks"]


def _reexecute_request(*, edited, version, base):
    from core.engine.contract import ReexecuteRequest

    return ReexecuteRequest(
        recipe=edited,
        version_hash=version,
        stage="coarse",
        ops=param_ops("harbor.crates", count=9),
        base=base,
    )


# ------------------------------------------------------------------- the swap


def test_the_engine_swap_a_recipe_written_today_survives():
    """The standing gate (plan §6): a recipe written under one engine still
    replays under the next, because our schema sits above the engine.

    Concretely: the same two entries, written under the v1 pin, replay under
    the v2 adapter after one pin edit — no entry is rewritten, only the pin
    and the adapter change; every stage key changes (the cache invalidates
    honestly); and the new engine refuses to re-execute the old engine's
    recorded stages, so nothing stale can ride through the swap.
    """
    v1 = FakeEngine(PIN_V1)
    v2 = Infinigen2Engine(pin=PIN_V2, runtime=RecordingRuntime())

    written_today = fjellvik(PIN_V1)
    version = "sha256:" + "a" * 64
    under_v1 = v1.generate_stage(
        StageRequest(recipe=written_today, version_hash=version, stage="coarse"))

    # the swap: one explicit pin edit (§1.1's Op list), the entries untouched
    swapped = written_today.model_copy(
        update={"engine_pin": PIN_V2},
        deep=True,  # entries survive byte-for-byte; only the pin moves
    )
    assert set(swapped.entries) == set(written_today.entries)
    assert all(
        swapped.entries[p].model_dump() == written_today.entries[p].model_dump()
        for p in swapped.entries
    )

    under_v2 = v2.generate_stage(
        StageRequest(recipe=swapped, version_hash=version, stage="coarse"))
    assert under_v2.mechanism == "graph-edit"
    # every key changed: a stage built by a different engine is different
    # work, and the cache must not serve the old bytes as a hit
    assert under_v1.stage_key != under_v2.stage_key
    assert under_v2.stage_key == stage_cache_key(
        version, PIN_V2, "coarse", [])

    # and the old engine's recorded stage is not the new engine's to edit
    with pytest.raises(Exception):  # noqa: B017 — the flavour refuses, any of its errors
        v2.reexecute(_reexecute_request(
            edited=swapped, version=version, base=under_v1))
