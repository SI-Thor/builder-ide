"""The v2 + procfunc adapter skeleton — trace graph out, recipe diff in.

The recording runtime answers the five procfunc operations, so what is
tested is the adapter's own half: the translation from our entries to
generator calls (the ``_rand_from_params`` convention), the translation
from our edit ops to graph edits, the envelope that names the lower layer,
and the honest refusal when neither procfunc nor another flavour's stage
is there to use.
"""

from __future__ import annotations

import json

import pytest

from core.engine import EngineUnavailable, Infinigen2Engine
from core.engine.contract import (
    ExportRequest,
    PreviewRequest,
    ReexecuteRequest,
    StageRequest,
)
from core.engine.infinigen2 import (
    ImportedProcfuncRuntime,
    generator_calls,
    graph_edits,
)

from .conftest import PIN_V1, PIN_V2, RecordingRuntime, fjellvik, param_ops


def _engine(rt: RecordingRuntime) -> Infinigen2Engine:
    return Infinigen2Engine(pin=PIN_V2, runtime=rt)


def _stage(recipe=None):
    return StageRequest(
        recipe=recipe or fjellvik(PIN_V2),
        version_hash="sha256:" + "a" * 64, stage="coarse",
    )


# ------------------------------------------------------------------ translation


def test_entries_become_generator_calls():
    """Our schema → v2's surface: a generator ref is a *name*; params ride
    explicitly (the ``_rand_from_params`` twin, E §2)."""
    calls = generator_calls(fjellvik(PIN_V2))
    by_entry = {c.entry_path: c for c in calls}
    assert by_entry["harbor.crates"].name == "crates"
    assert by_entry["harbor.crates"].params == {"count": 8, "style": "weathered"}
    assert by_entry["harbor.crates"].module == "infinigen_thor.structures"
    assert by_entry["harbor.racks"].seed == 43


def test_entries_without_a_generator_are_not_calls():
    """asset_ref and its kind carry no generator; the translation skips
    them rather than inventing a call."""
    recipe = fjellvik(PIN_V2)
    entries = dict(recipe.entries)
    entries["harbor.marker"] = recipe.entries["harbor.racks"].model_copy(
        update={"path": "harbor.marker", "generator": None})
    recipe = recipe.model_copy(update={"entries": entries})
    assert {c.entry_path for c in generator_calls(recipe)} == {
        "harbor.crates", "harbor.racks"}


def test_param_ops_become_graph_edits():
    edits = graph_edits(param_ops("harbor.crates", count=12))
    assert len(edits) == 1
    assert edits[0].entry_path == "harbor.crates"
    assert edits[0].param == "count"
    assert edits[0].value == 12


def test_non_param_ops_are_refused_not_passed_through():
    """An op the translation does not know is a schema change, not a silent
    pass-through (structure edits are a re-trace, not a graph edit)."""
    from core.records import Op

    with pytest.raises(ValueError, match="params"):
        graph_edits([Op(op="set", path="harbor.crates", value={"a": 1})])


# ------------------------------------------------------------------ the seam


def test_the_traced_graph_is_the_stages_lower_layer(runtime):
    """E §2: the instance-level graph is the recipe's lower layer — the
    stage's data carries it, marked with the flavour that traced it."""
    rt = runtime
    result = _engine(rt).generate_stage(_stage())
    doc = json.loads(result.data)
    assert doc["engine"] == "infinigen-2-procfunc"
    assert doc["stage"] == "coarse"
    assert doc["graph"]["traced"] is True
    assert doc["pin"]["commit"] == PIN_V2.commit
    assert rt.ops[0][0] == "trace"


def test_reexecution_edits_the_graph_and_executes_the_reachable_part(runtime):
    """Recipe diff → graph edit → re-execute: the targeted variant (E's
    confirming experiment, step 3)."""
    rt = runtime
    engine = _engine(rt)
    base = engine.generate_stage(_stage())
    edited = fjellvik(PIN_V2, crates=9)
    again = engine.reexecute(ReexecuteRequest(
        recipe=edited, version_hash="sha256:" + "b" * 64, stage="coarse",
        ops=param_ops("harbor.crates", count=9), base=base))
    kinds = [op[0] for op in rt.ops]
    assert kinds == ["trace", "replace", "execute"]
    # the edit landed in the graph the runtime was handed
    replace_graph, replace_edits = rt.ops[1][1], rt.ops[1][2]
    assert replace_edits[0]["entry_path"] == "harbor.crates"
    executed_graph = rt.ops[2][1]
    assert executed_graph["nodes"]["n0"]["params"]["count"] == 9
    # and the executed output is digested into the new stage's envelope
    assert json.loads(again.data)["outputs_sha256"].startswith("sha256:")
    assert again.mechanism == "graph-edit"


def test_a_foreign_base_stage_is_refused(runtime):
    """Rule 5: only this flavour's own lower layer is ours to edit — a v1
    blob (or the fake's) is not a traced graph."""
    rt = runtime
    engine = _engine(rt)
    base = engine.generate_stage(_stage())
    foreign = base.model_copy(update={
        "data": b"not a graph", "mechanism": "full-reeval"})
    with pytest.raises(EngineUnavailable) as caught:
        engine.reexecute(ReexecuteRequest(
            recipe=fjellvik(PIN_V2, crates=9),
            version_hash="sha256:" + "b" * 64, stage="coarse",
            ops=param_ops("harbor.crates", count=9), base=foreign))
    assert "not a traced v2 graph" in str(caught.value)


def test_a_recipe_pinned_elsewhere_is_refused(runtime):
    with pytest.raises(Exception, match="pin"):
        _engine(runtime).generate_stage(
            StageRequest(recipe=fjellvik(PIN_V1),
                         version_hash="sha256:" + "a" * 64, stage="coarse"))


def test_previews_render_the_traced_graph(runtime):
    rt = runtime
    result = _engine(rt).render_preview(PreviewRequest(
        recipe=fjellvik(PIN_V2), version_hash="sha256:" + "a" * 64,
        subject="harbor.crates", rung=2, seed=42))
    kinds = [op[0] for op in rt.ops]
    assert kinds == ["trace", "render"]
    assert rt.ops[1][1:] == ("480p", 16, 42)  # the ladder's rung 2
    assert result.data.startswith(b"v2-render")
    assert result.wall_ms is not None


def test_export_goes_through_the_runtime_ours_to_write(runtime):
    """v2 ships no exporter (E §1) — the runtime's export half is the piece
    this project writes; the seam carries it either way."""
    rt = runtime
    result = _engine(rt).export(ExportRequest(
        recipe=fjellvik(PIN_V2), version_hash="sha256:" + "a" * 64,
        format="glb", profile="lod"))
    assert [op[0] for op in rt.ops] == ["trace", "export"]
    assert rt.ops[1][1:] == ("glb", "lod")
    assert result.data == b"v2-export glb lod"
    with pytest.raises(ValueError, match="glb"):
        _engine(rt).export(ExportRequest(
            recipe=fjellvik(PIN_V2), version_hash="sha256:" + "a" * 64,
            format="fbx"))


def test_without_procfunc_the_missing_piece_is_named():
    """On this core (Python 3.12) procfunc cannot import — the engine
    decision's own fact (E §2: bpy==4.2.0 pins Python ==3.11.*). The
    default runtime says so instead of throwing an import traceback."""
    try:
        import procfunc  # noqa: F401
        pytest.skip("procfunc is importable on this box; the refusal path "
                    "cannot be exercised here")
    except ImportError:
        pass
    engine = Infinigen2Engine(pin=PIN_V2)  # the ImportedProcfuncRuntime
    with pytest.raises(EngineUnavailable) as caught:
        engine.generate_stage(_stage())
    message = str(caught.value)
    assert "procfunc" in message and "3.11" in message
    assert caught.value.detail.get("missing") == "procfunc"
