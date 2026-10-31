"""Typed edits: applying ops and diffing two recipe documents.

The diff *is* the op list (§1.1): a recipe never mutates in place, change is
a list of typed operations against a parent version.
"""

from __future__ import annotations

import pytest

from core.recipe.edits import apply_ops, diff_recipes, touched_entries
from core.recipe.errors import EditRejected
from core.recipe.models import Op, Recipe


def test_set_changes_an_entry_param(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="set", path="harbor.crates.params.count", value=20)])
    assert result.entries["harbor.crates"].params["count"] == 20


def test_apply_never_mutates_the_base(fjellvik: Recipe):
    apply_ops(fjellvik, [Op(op="set", path="harbor.crates.params.count", value=20)])
    assert fjellvik.entries["harbor.crates"].params["count"] == 12


def test_set_changes_a_document_seed(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="set", path="seeds.terrain", value=99)])
    assert result.seeds["terrain"] == 99


def test_set_changes_the_engine_pin(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="set", path="engine_pin.commit", value="abc1234")])
    assert result.engine_pin.commit == "abc1234"


def test_set_can_create_a_new_param_so_the_schema_can_refuse_it(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="set", path="harbor.crates.params.lids", value=True)])
    assert result.entries["harbor.crates"].params["lids"] is True


def test_set_on_a_missing_parent_is_refused(fjellvik: Recipe):
    with pytest.raises(EditRejected):
        apply_ops(fjellvik, [Op(op="set", path="harbor.crates.nope.count", value=1)])


def test_add_appends_to_a_list(fjellvik: Recipe):
    op = Op(op="add", path="harbor.crates.assets", value="ast_crate_01")
    result = apply_ops(fjellvik, [op])
    assert result.entries["harbor.crates"].assets == ["ast_crate_01"]


def test_add_on_an_existing_key_is_refused(fjellvik: Recipe):
    with pytest.raises(EditRejected):
        apply_ops(fjellvik, [Op(op="add", path="harbor.crates.params.count", value=3)])


def test_remove_deletes_a_param(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="remove", path="harbor.crates.params.style")])
    assert "style" not in result.entries["harbor.crates"].params


def test_remove_of_a_missing_key_is_refused(fjellvik: Recipe):
    with pytest.raises(EditRejected):
        apply_ops(fjellvik, [Op(op="remove", path="harbor.crates.params.nope")])


def test_add_creates_a_new_entry(fjellvik: Recipe):
    value = {
        "path": "harbor.racks",
        "kind": "prop_set",
        "params": {"count": 4},
        "seed": 12,
        "constraints": [],
        "assets": [],
        "origin": "wo_15",
    }
    result = apply_ops(fjellvik, [Op(op="add", path="entries.harbor.racks", value=value)])
    assert result.entries["harbor.racks"].params["count"] == 4


def test_remove_deletes_an_entry(fjellvik: Recipe):
    result = apply_ops(fjellvik, [Op(op="remove", path="entries.terrain.harbor")])
    assert "terrain.harbor" not in result.entries


def test_an_op_on_an_unknown_entry_is_refused(fjellvik: Recipe):
    with pytest.raises(EditRejected):
        apply_ops(fjellvik, [Op(op="set", path="harbor.nowhere.params.count", value=1)])


def test_touched_entries_names_the_entries_an_edit_reaches(fjellvik: Recipe):
    ops = [
        Op(op="set", path="harbor.crates.params.count", value=3),
        Op(op="set", path="seeds.terrain", value=1),
    ]
    assert touched_entries(fjellvik, ops) == {"harbor.crates"}


def test_diff_of_identical_documents_is_empty(fjellvik: Recipe):
    assert diff_recipes(fjellvik, fjellvik) == []


def test_diff_reports_a_changed_param(fjellvik: Recipe):
    head = apply_ops(fjellvik, [Op(op="set", path="harbor.crates.params.count", value=20)])
    ops = diff_recipes(fjellvik, head)
    assert ops == [Op(op="set", path="harbor.crates.params.count", value=20)]


def test_diff_reports_an_added_entry(fjellvik: Recipe):
    value = {
        "path": "harbor.racks",
        "kind": "prop_set",
        "params": {"count": 4},
        "seed": 12,
        "constraints": [],
        "assets": [],
        "origin": "wo_15",
    }
    head = apply_ops(fjellvik, [Op(op="add", path="entries.harbor.racks", value=value)])
    ops = diff_recipes(fjellvik, head)
    assert len(ops) == 1
    assert ops[0].op == "add"
    assert ops[0].path == "harbor.racks"


def test_diff_reports_a_removed_entry(fjellvik: Recipe):
    head = apply_ops(fjellvik, [Op(op="remove", path="entries.terrain.harbor")])
    ops = diff_recipes(fjellvik, head)
    assert ops == [Op(op="remove", path="terrain.harbor")]


def test_diff_reports_a_changed_seed(fjellvik: Recipe):
    head = apply_ops(fjellvik, [Op(op="set", path="seeds.terrain", value=99)])
    assert diff_recipes(fjellvik, head) == [
        Op(op="set", path="seeds.terrain", value=99)
    ]


def test_diff_round_trips_through_apply(fjellvik: Recipe):
    head = apply_ops(
        fjellvik,
        [
            Op(op="set", path="harbor.crates.params.count", value=20),
            Op(op="set", path="structure.south_span.params.load_factor", value=2.3),
            Op(op="set", path="seeds.weather", value=7),
            Op(op="remove", path="entries.terrain.harbor"),
        ],
    )
    ops = diff_recipes(fjellvik, head)
    assert apply_ops(fjellvik, ops) == head


def test_diff_is_deterministic_across_runs(fjellvik: Recipe):
    head = apply_ops(
        fjellvik,
        [
            Op(op="set", path="harbor.crates.params.count", value=20),
            Op(op="set", path="seeds.weather", value=7),
        ],
    )
    assert diff_recipes(fjellvik, head) == diff_recipes(fjellvik, head)
