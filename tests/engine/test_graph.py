"""The procfunc graph layer — the diff, the extraction, the store.

The doubles here are shaped like the real traced graphs (round 2's
`graph.json`: nodes with ids, ``$ref`` edges nested in args/kwargs,
``chosen_idx`` on choice nodes, a join point where a subtree's results
enter the scene's lists), so the assertions read against round 2's §4.1
table — the measurement this contract is grounded on. The real
18,725/21,423-node graphs are exercised by the Thor measurement
(`examples/stage_cache_thor.py`), not shipped as fixtures.
"""

from __future__ import annotations

import json

import pytest

from core.canon import content_hash
from core.engine.graph import (
    GraphStore,
    StageGraphs,
    diff_graphs,
    graph_hash,
    graphs_of_stage,
)
from core.recipe.errors import IntegrityError


# ------------------------------------------------------------------ builders


def constant(node_id: str, value) -> dict:
    return {"id": node_id, "type": "Constant", "value": value}


def draw(node_id: str, low: float, high: float, *refs: str) -> dict:
    return {
        "id": node_id,
        "type": "FunctionCall",
        "func": "procfunc.random.uniform",
        "args": [],
        "kwargs": {
            "rng": {"$ref": refs[0]} if refs else None,
            "low": low,
            "high": high,
        },
    }


def choice(node_id: str, rng_ref: str, chosen_idx: int) -> dict:
    return {
        "id": node_id,
        "type": "FunctionCall",
        "func": "procfunc.control.choice",
        "args": [],
        "kwargs": {
            "choice_rng": {"$ref": rng_ref},
            "choice_options": [[0, 2.0], [1, 1.0]],
            "chosen_idx": chosen_idx,
        },
    }


def join(node_id: str, left: str, right) -> dict:
    """The `_operator.add` shape: a list literal that may contain refs."""
    return {
        "id": node_id,
        "type": "FunctionCall",
        "func": "_operator.add",
        "args": [{"$ref": left}, right],
        "kwargs": {},
    }


def graph(nodes: list[dict], outputs: dict | None = None) -> dict:
    return {"name": "execute_generators", "nodes": nodes, "outputs": outputs or {}}


def room(desk: bool) -> dict:
    """A room in the round-2 shape: walls either side of one desk choice.

    The shapes are the ones the real graphs taught us (round 2 §4.1): the
    desk's objects ride **inline** inside the join node as embedded node
    trees (``$type`` dicts, no ids of their own), the choice node itself
    records the branch taken, and the positional tail node past the shared
    region gets its id re-bound to a different call.
    """
    desk_tree = (
        [{"$type": "Proxy", "node": {"$type": "FunctionCallNode",
                                     "args": [{"$ref": "n40"}, {"$ref": "n41"}],
                                     "kwargs": {"kind": "desk"}}}]
        if desk
        else []
    )
    nodes = [
        constant("n0", {"$type": "rng"}),
        draw("n1", 0.0, 1.0),
        choice("n2", "n0", 1 if desk else 0),
        join("n3", "n1", desk_tree),
        {
            "id": "n4",
            "type": "MethodCall",
            "method": "__getitem__",
            "args": [{"$ref": "n3"}, 0],
            "kwargs": {},
        },
    ]
    if desk:
        nodes += [draw("n40", 0.6, 0.9, "n0"), draw("n41", 1.2, 1.6, "n0")]
        # the tail: an id that existed in the base graph bound to another call
        nodes.append(
            {"id": "n5", "type": "MethodCall", "method": "__getitem__",
             "args": [{"$ref": "n0"}, 4], "kwargs": {}}
        )
    else:
        nodes.append(
            {"id": "n5", "type": "FunctionCall", "func": "builtins.Vector",
             "args": [[{"$ref": "n1"}, {"$ref": "n1"}, {"$ref": "n1"}]],
             "kwargs": {}}
        )
    return graph(nodes, outputs={"objects": {"$ref": "n3"}})


# ------------------------------------------------------------------ the diff


def test_identical_graphs_diff_to_nothing():
    a = room(desk=False)
    diff = diff_graphs(a, room(desk=False))
    assert diff.identical
    assert diff.added == [] and diff.removed == [] and diff.changed == []
    assert diff.closure == []
    assert not diff.outputs_touched
    assert diff.wall_ms is not None


def test_the_desk_shaped_edit_diffs_like_round_2():
    """Additive at graph level: the desk subtree appears, nothing shrinks;
    the join point grew by embedding the desk's inline tree, the choice is
    an edited node, and one positional tail id re-binds — the honest reason
    this diff is not splice-safe even though it is additive."""
    diff = diff_graphs(room(desk=False), room(desk=True))
    assert diff.added == ["n40", "n41"]          # the desk subtree's draws
    assert diff.removed == []                    # nothing shrinks
    assert diff.changed == ["n2", "n3", "n5"]
    assert diff.join_points == ["n3"]            # grew: the inline desk tree
    assert diff.edited == ["n2"]                 # the branch taken moved
    assert diff.rebound == ["n5"]                # the positional tail artifact
    assert diff.additive and not diff.splice_safe
    # the closure: seeds plus everyone downstream — the join feeds the
    # room's list and the outputs, so the outputs are touched
    assert set(diff.closure) == {"n2", "n3", "n4", "n5", "n40", "n41"}
    assert diff.outputs_touched
    assert diff.added_kinds == {"procfunc.random.uniform": 2}
    assert diff.changed_kinds["_operator.add"] == 1


def test_a_param_change_closes_over_consumers_only():
    """One draw's bounds move: the dirty subtree is that node and its
    consumers — the sibling choice is untouched (RNG scoping made visible:
    a node nobody downstream of the change re-executes)."""
    base = room(desk=True)
    head = room(desk=True)
    head["nodes"][1] = draw("n1", 0.0, 2.0)
    diff = diff_graphs(base, head)
    assert diff.changed == ["n1"]
    assert diff.edited == ["n1"]
    assert diff.closure == ["n1", "n3", "n4"]    # n1 → join n3 → __getitem__ n4
    assert diff.additive and diff.splice_safe
    assert diff.outputs_touched


def test_a_dead_change_does_not_reach_the_outputs():
    base = room(desk=True)
    head = room(desk=True)
    head["nodes"].append(draw("n99", 0.0, 1.0))  # referenced by nothing
    diff = diff_graphs(base, head)
    assert diff.added == ["n99"]
    assert diff.closure == ["n99"]
    assert not diff.outputs_touched


def test_a_removal_is_not_additive_and_dirties_its_consumer():
    base = room(desk=True)
    head = room(desk=True)
    head["nodes"] = [n for n in head["nodes"] if n["id"] != "n40"]
    head["nodes"][3] = join("n3", "n1", [])
    diff = diff_graphs(base, head)
    assert diff.removed == ["n40"]
    assert not diff.additive and not diff.splice_safe
    assert "n3" in diff.changed and "n3" in diff.closure


def test_diff_as_dict_carries_the_report_shape():
    diff = diff_graphs(room(desk=False), room(desk=True))
    report = diff.as_dict()
    assert report["added"] == 2 and report["removed"] == 0
    assert report["changed"] == 3
    assert report["closure_nodes"] == 6
    assert report["closure_share"] == round(6 / 8, 4)
    assert report["additive"] is True and report["splice_safe"] is False


# ------------------------------------------------------------------ extraction


def _envelope(graph_payload: dict) -> bytes:
    doc = {"engine": "infinigen-2-procfunc", "pin": {}, "stage": "objects",
           "graph": graph_payload}
    return json.dumps(doc).encode("utf-8")


def test_extraction_reads_the_venv_bundle_per_entry():
    bundle = {"engine": "venv-cli", "trace_level": "RANDOM_CONTROL",
              "entries": {"harbor.crates": room(False), "harbor.racks": room(True)}}
    graphs = graphs_of_stage(_envelope(bundle))
    assert set(graphs.entries) == {"harbor.crates", "harbor.racks"}
    assert graphs.for_entry("harbor.crates") == room(False)
    assert graphs.for_entry("elsewhere") is None  # no single graph to fall back to


def test_extraction_reads_a_bare_graph_as_single():
    graphs = graphs_of_stage(_envelope(room(False)))
    assert graphs.single == room(False)
    assert graphs.for_entry("any.entry") == room(False)


def test_extraction_refuses_what_it_does_not_recognize():
    """Contract rule 5: the lower layer belongs to the engine — an envelope
    this module does not know is 'no graph', never a guess."""
    assert graphs_of_stage(b"not json").empty
    assert graphs_of_stage(json.dumps({"engine": "fake-engine",
                                       "entries": {}}).encode()).empty
    assert graphs_of_stage(json.dumps({"nodes": "nope"}).encode()).empty


# ------------------------------------------------------------------ the store


def test_the_store_records_and_reads_back_by_stage_key(tmp_path):
    store = GraphStore(tmp_path)
    ref = store.record("sha256:" + "a" * 64, room(False))
    assert ref.nodes == 6
    assert store.get("sha256:" + "a" * 64) == room(False)
    assert "sha256:" + "a" * 64 in store
    assert len(store) == 1


def test_the_store_dedupes_identical_graphs(tmp_path):
    """Two versions share most of a graph; the same graph under two keys is
    one blob, not two (graphs are megabytes)."""
    store = GraphStore(tmp_path)
    first = store.record("sha256:" + "a" * 64, room(True))
    second = store.record("sha256:" + "b" * 64, room(True))
    assert first.graph == second.graph == graph_hash(room(True))
    assert len(store) == 2
    assert store.total_bytes() == first.size_bytes  # counted once


def test_the_store_survives_reopen_and_verifies_its_blobs(tmp_path):
    key = "sha256:" + "c" * 64
    GraphStore(tmp_path).record(key, room(False))
    reopened = GraphStore(tmp_path)
    assert reopened.get(key) == room(False)

    blob = reopened.ref_for(key)
    path = tmp_path / "artifacts" / blob.graph.split(":")[1][:2] / blob.graph.split(":")[1]
    path.write_bytes(path.read_bytes() + b"corrupted")
    with pytest.raises(IntegrityError):
        reopened.get(key)


def test_the_store_refuses_a_non_graph(tmp_path):
    store = GraphStore(tmp_path)
    with pytest.raises(ValueError, match="procfunc graph"):
        store.record("sha256:" + "d" * 64, {"nodes": [{"no": "id"}]})


def test_a_missing_key_is_none_never_an_error(tmp_path):
    assert GraphStore(tmp_path).get("sha256:" + "e" * 64) is None


def test_graph_hash_is_content_hash_of_the_document():
    assert graph_hash(room(False)) == content_hash(room(False))
