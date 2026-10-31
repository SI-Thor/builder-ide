"""The dirty set — core-spec v2 §1.1.

Entries are independent by construction, so applying an edit must re-evaluate
only the dirty set: the touched entries, plus the entries coupled to them by
constraints, by assets and by declared stage dependencies. Untouched stages
must be byte-identical on re-evaluation — that is what a stage-cache *hit*
means.
"""

from __future__ import annotations

from core.recipe.dirty import StaticAssetProducers, compute_dirty_set
from core.recipe.edits import apply_ops
from core.recipe.models import Constraint, NodeRef, Op, Recipe
from core.recipe.noderegistry import NodeRegistry
from core.recipe.stagecache import entry_stage_key


def _registry() -> NodeRegistry:
    return NodeRegistry(
        [
            NodeRef(node_id="oak_0117", entry_path="terrain.harbor", kind="terrain"),
            NodeRef(node_id="crate_07", entry_path="harbor.crates", kind="prop_set"),
        ]
    )


def _touch_crates(fjellvik: Recipe) -> Recipe:
    return apply_ops(fjellvik, [Op(op="set", path="harbor.crates.params.count", value=20)])


def test_the_dirty_set_is_the_touched_entries(fjellvik: Recipe):
    head = _touch_crates(fjellvik)
    dirty = compute_dirty_set(fjellvik, head, registry=_registry())
    assert dirty.entries == {"harbor.crates"}


def test_an_untouched_entry_is_not_dirty(fjellvik: Recipe):
    head = _touch_crates(fjellvik)
    dirty = compute_dirty_set(fjellvik, head, registry=_registry())
    assert "terrain.harbor" not in dirty.entries
    assert "structure.south_span" not in dirty.entries


def test_an_entry_coupled_by_a_constraint_is_dirty(fjellvik: Recipe):
    """The oak's drip line crosses terrain and props (a shared constraint name)."""
    fjellvik.entries["harbor.crates"].constraints.append(
        Constraint(name="oak_dripline", kind="keep_clear", ref="oak_0117", value=0.35)
    )
    head = _touch_crates(fjellvik)
    dirty = compute_dirty_set(fjellvik, head, registry=_registry())
    assert "harbor.crates" in dirty.entries


def test_an_entry_whose_constraint_couples_a_touched_entry_is_dirty(fjellvik: Recipe):
    """Touching the oak's entry re-opens the entry that must stay clear of it."""
    fjellvik.entries["harbor.crates"].constraints.append(
        Constraint(name="oak_dripline", kind="keep_clear", ref="oak_0117", value=0.35)
    )
    head = apply_ops(
        fjellvik, [Op(op="set", path="terrain.harbor.params.slope", value=0.2)]
    )
    dirty = compute_dirty_set(fjellvik, head, registry=_registry())
    assert "harbor.crates" in dirty.entries
    assert "harbor.crates" in dirty.constraints


def test_an_entry_consuming_an_asset_produced_by_a_touched_entry_is_dirty(fjellvik: Recipe):
    fjellvik.entries["harbor.crates"].assets = ["ast_crate_01"]
    head = apply_ops(
        fjellvik, [Op(op="set", path="terrain.harbor.params.slope", value=0.2)]
    )
    producers = StaticAssetProducers({"ast_crate_01": "terrain.harbor"})
    dirty = compute_dirty_set(fjellvik, head, registry=_registry(), asset_producers=producers)
    assert "harbor.crates" in dirty.entries
    assert "harbor.crates" in dirty.assets


def test_a_downstream_stage_whose_dep_keys_include_a_touched_entry_is_dirty(fjellvik: Recipe):
    head = _touch_crates(fjellvik)
    key = entry_stage_key(
        "harbor.crates", head.entries["harbor.crates"], fjellvik.engine_pin
    )
    stages = {"compile-scene": [key], "assemble-glb": ["sha256:" + "f" * 64]}
    dirty = compute_dirty_set(
        fjellvik, head, registry=_registry(), stages=stages
    )
    assert "compile-scene" in dirty.stages
    assert "assemble-glb" not in dirty.stages


def test_the_dirty_set_reports_why_each_entry_is_dirty(fjellvik: Recipe):
    head = _touch_crates(fjellvik)
    dirty = compute_dirty_set(fjellvik, head, registry=_registry())
    assert dirty.reasons["harbor.crates"]
