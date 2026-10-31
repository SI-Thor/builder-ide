"""The layer structure — one concern per layer, one opinion per layer.

The spike's pass/fail (rev-tech spike 3) asks for "a layered USD stage with
one layer per concern (geometry refs / materials / physics / semantics)". These
tests check the shape of that layering, and the rule that keeps it
composable: **no two layers author the same opinion**, because ``customData``
is a whole-dictionary opinion and two writers would silently shadow each
other.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from builder_usd.compile import CONCERNS, ROOT_LAYER_NAME
from builder_usd.verify import open_stage

#: What each concern layer is allowed to say.
OWNERSHIP = {
    "geometry": ("references =", "xformOp:"),
    "materials": ("material:binding", "UsdPreviewSurface"),
    "physics": ("apiSchemas", "physics:"),
    "semantics": ("semantic:",),
    "provenance": ("customData",),
}

#: What no layer but its owner may say.
FORBIDDEN = {
    "geometry": ("customData", "apiSchemas", "material:binding", "semantic:", "physics:"),
    "materials": ("customData", "apiSchemas", "semantic:", "physics:"),
    "physics": ("customData", "semantic:", "material:binding"),
    "semantics": ("customData", "apiSchemas", "material:binding", "physics:"),
    "provenance": ("apiSchemas", "semantic:", "material:binding", "physics:"),
}


@pytest.mark.parametrize("concern", sorted(OWNERSHIP))
def test_each_layer_says_only_its_own_concern(demo_stage, concern):
    text = (demo_stage / f"{concern}.usda").read_text(encoding="utf-8")
    for marker in OWNERSHIP[concern]:
        assert marker in text, f"{concern}.usda does not carry {marker!r}"
    for marker in FORBIDDEN[concern]:
        assert marker not in text, f"{concern}.usda also carries {marker!r}"


def test_the_stage_has_a_layer_per_concern_plus_a_root(demo_stage):
    for concern in CONCERNS:
        assert (demo_stage / f"{concern}.usda").is_file()
    assert (demo_stage / ROOT_LAYER_NAME).is_file()


def test_the_root_layer_lists_every_concern(demo_stage):
    root = open_stage(demo_stage / ROOT_LAYER_NAME)
    listed = list(root.GetRootLayer().subLayerPaths)
    assert listed == sorted(f"{concern}.usda" for concern in CONCERNS)


def test_the_stage_opens_without_a_warning(demo_stage, repo_root):
    """USD writes composition problems to stderr — there must be none."""
    script = (
        "from pxr import Usd;"
        f"stage = Usd.Stage.Open({str(demo_stage / ROOT_LAYER_NAME)!r});"
        "print(len(list(stage.Traverse())))"
    )
    env = {"PYTHONPATH": str(repo_root / "core" / "usd" / "src")}
    import os

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env={**os.environ, **env}
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", f"opening the stage warned:\n{result.stderr}"
    assert int(result.stdout.strip()) > 0


def test_the_layout_carries_the_reference_arcs(demo_stage):
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    prim = stage.GetPrimAtPath("/World/harbor/crate_stack")
    assert prim, "the placement is missing"
    references = prim.GetMetadata("references")
    assert references, "the placement has no reference"
    targets = references.prependedItems or references.explicitItems or []
    assert any(str(item.assetPath).endswith("crate_lid.usda") for item in targets)


def test_the_referenced_part_brings_its_mesh(demo_stage):
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    mesh = stage.GetPrimAtPath("/World/harbor/crate_stack/mesh")
    assert mesh and mesh.GetTypeName() == "Mesh"
    points = mesh.GetAttribute("points").Get()
    assert points and len(points) > 3


def test_the_material_is_bound_to_the_placement(demo_stage):
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    binding = stage.GetPrimAtPath("/World/harbor/crate_stack").GetRelationship("material:binding")
    targets = list(binding.GetTargets())
    assert targets == [Sdf_path("/World/materials/oak")]


def Sdf_path(path: str):
    from pxr import Sdf

    return Sdf.Path(path)


def test_the_physics_layer_says_mass_and_collision(demo_stage):
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    prim = stage.GetPrimAtPath("/World/harbor/mooring_post")
    assert float(prim.GetAttribute("physics:mass").Get()) == 48.0
    assert str(prim.GetAttribute("physics:approximateCollision").Get()) == "boundingCube"


def test_the_semantics_layer_says_what_the_things_are(demo_stage):
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    prim = stage.GetPrimAtPath("/World/terrain/ground")
    assert str(prim.GetAttribute("semantic:type").Get()) == "ground"
    assert list(prim.GetAttribute("semantic:tags").Get()) == ["terrain"]


def test_the_placement_without_geometry_still_compiles(demo_stage):
    """A terrain entry has no asset — it is a place, not a thing."""
    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    prim = stage.GetPrimAtPath("/World/terrain/ground")
    assert prim
    assert not prim.GetChildren(), "the ground should carry no geometry"


def test_the_units_are_declared(demo_stage):
    from pxr import UsdGeom

    stage = open_stage(demo_stage / ROOT_LAYER_NAME)
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
    assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
