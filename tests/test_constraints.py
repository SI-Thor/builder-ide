"""Pre-render constraint checks (core-spec v2 §1.1, §2.3.5).

Constraint checks precede renders in the pipeline: the drip-line constraint
failed *before* the critic ran (D §04:2x). The checks are scripted analytic
computations from the recipe's own parameters — there is no physics engine in
this system and no "sim" (X R11, §7.14).
"""

from __future__ import annotations

from builder_recipe.constraints import ConstraintChecker
from builder_recipe.models import Constraint, NodeRef, Recipe, RecipeEntry
from builder_recipe.noderegistry import NodeRegistry


def _entry(**params) -> RecipeEntry:
    return RecipeEntry(path="structure.south_span", kind="structure", params=params)


def _recipe(entry: RecipeEntry, constraints=None) -> Recipe:
    from builder_recipe.models import EnginePin

    return Recipe(
        id="rcp_fjellvik",
        name="Fjellvik",
        engine_pin=EnginePin(
            repo="SI-Thor/infinigen-thor",
            commit="9f31c0e",
            config="sha256:cf90cafe",
            blender="4.2",
            python="3.12",
        ),
        entries={entry.path: entry},
        constraints=constraints or [],
    )


def _check(recipe: Recipe, touched=None, registry=None):
    checker = ConstraintChecker(registry=registry)
    return checker.check(recipe, touched=touched if touched is not None else set(recipe.entries))


def test_a_load_floor_that_holds_passes():
    recipe = _recipe(_entry(load_factor=2.3))
    checks = _check(recipe)
    assert checks == []


def test_a_load_floor_that_is_under_the_floor_fails():
    recipe = _recipe(_entry(load_factor=1.1))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="south_span_load", kind="load_floor", ref=None, value=2.0)
    )
    checks = _check(recipe)
    assert len(checks) == 1
    assert checks[0].status == "fail"
    assert checks[0].name == "south_span_load"


def test_a_missing_parameter_fails_the_check_rather_than_passing_it():
    recipe = _recipe(_entry(planks=8))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="south_span_load", kind="load_floor", ref=None, value=2.0)
    )
    checks = _check(recipe)
    assert checks[0].status == "fail"
    assert "load_factor" in checks[0].reason


def test_a_keep_clearance_holds_or_fails():
    recipe = _recipe(_entry(clearance_m=0.4))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="dripline", kind="keep_clear", ref=None, value=0.35)
    )
    assert _check(recipe)[0].status == "pass"

    recipe.entries["structure.south_span"].params["clearance_m"] = 0.2
    assert _check(recipe)[0].status == "fail"


def test_a_scale_bound_fails_outside_its_tolerance():
    recipe = _recipe(_entry(scale=1.4))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="scale", kind="scale_bounds", ref=None, value=0.1)
    )
    assert _check(recipe)[0].status == "fail"


def test_a_reachability_floor_fails():
    recipe = _recipe(_entry(reach_m=3.0))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="reach", kind="reachability", ref=None, value=5.0)
    )
    assert _check(recipe)[0].status == "fail"


def test_a_custom_budget_ceiling_fails():
    recipe = _recipe(_entry(budget=90.0))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="budget", kind="budget_custom", ref=None, value=50.0)
    )
    assert _check(recipe)[0].status == "fail"


def test_a_watertight_constraint_is_deferred_to_the_geometry_check():
    recipe = _recipe(_entry(planks=8))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="solid", kind="watertight", ref=None, value=0.0)
    )
    checks = _check(recipe)
    assert checks[0].status == "deferred"
    assert "critic" in checks[0].reason


def test_a_constraint_that_references_an_unknown_node_fails_when_the_registry_is_published():
    recipe = _recipe(_entry(clearance_m=0.4))
    recipe.constraints.append(
        Constraint(name="dripline", kind="keep_clear", ref="oak_0117", value=0.35)
    )
    registry = NodeRegistry(
        [NodeRef(node_id="crate_07", entry_path="harbor.crates", kind="prop_set")]
    )
    checks = _check(recipe, registry=registry)
    assert checks[0].status == "fail"
    assert "oak_0117" in checks[0].reason


def test_an_unresolvable_node_reference_is_deferred_until_the_registry_is_published():
    recipe = _recipe(_entry(clearance_m=0.4))
    recipe.constraints.append(
        Constraint(name="dripline", kind="keep_clear", ref="oak_0117", value=0.35)
    )
    checks = _check(recipe, registry=None)
    assert checks[0].status == "deferred"


def test_a_node_reference_resolves_through_the_registry():
    recipe = _recipe(_entry(clearance_m=0.4))
    recipe.constraints.append(
        Constraint(name="dripline", kind="keep_clear", ref="span_south", value=0.35)
    )
    registry = NodeRegistry(
        [
            NodeRef(
                node_id="span_south", entry_path="structure.south_span", kind="structure"
            )
        ]
    )
    checks = _check(recipe, registry=registry)
    assert checks[0].status == "pass"
    assert checks[0].entry_path == "structure.south_span"


def test_a_project_level_constraint_is_checked_on_every_pass():
    recipe = _recipe(_entry(clearance_m=0.4))
    recipe.constraints.append(
        Constraint(name="dripline", kind="keep_clear", ref=None, value=0.35)
    )
    checks = _check(recipe, touched={"structure.south_span"})
    assert len(checks) == 1


def test_the_checker_reports_the_entry_a_check_belongs_to():
    recipe = _recipe(_entry(load_factor=1.1))
    recipe.entries["structure.south_span"].constraints.append(
        Constraint(name="south_span_load", kind="load_floor", ref=None, value=2.0)
    )
    checks = _check(recipe)
    assert checks[0].entry_path == "structure.south_span"
