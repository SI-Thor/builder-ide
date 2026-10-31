"""The vocabulary door — what the compiler refuses, and why it matters.

CLAUDE.md: builders change recipes through a closed, typed vocabulary. The
compiler is one of the doors, so it refuses a parameter it does not
understand **by name** — an unknown parameter is an error, not a shrug.
"""

from __future__ import annotations

import pytest

from builder_usd.recipe_source import RecipeEntry, document_from_dict
from builder_usd.vocabulary import Placement, VocabularyError, parse_entry


def _entry(**params) -> RecipeEntry:
    return RecipeEntry(path="harbor.crates", kind="prop_set", params=params)


def test_a_placement_is_read():
    placement = parse_entry(
        _entry(
            location=[1.0, 2.0, 3.0],
            rotation_euler_deg=[0.0, 90.0, 0.0],
            scale=2.0,
            cad_part={"name": "crate_lid", "params": {"length": 0.6}},
            material="materials.oak",
            semantic_type="crate",
            semantic_tags=["harbor", "wood"],
            mass_kg=12.5,
            collision="boundingCube",
        )
    )
    assert isinstance(placement, Placement)
    assert placement.prim_path == "/World/harbor/crates"
    assert placement.location == (1.0, 2.0, 3.0)
    assert placement.scale == (2.0, 2.0, 2.0)
    assert placement.cad_part.name == "crate_lid"
    assert placement.cad_part.params == {"length": 0.6}
    assert placement.semantic_tags == ("harbor", "wood")
    assert placement.seed is None


def test_an_unknown_parameter_is_refused_by_name():
    with pytest.raises(VocabularyError) as error:
        parse_entry(_entry(location=[0, 0, 0], cad_part={"name": "crate_lid"}, wibble=1))
    assert "wibble" in str(error.value)


def test_an_unknown_part_parameter_is_refused_by_name():
    with pytest.raises(VocabularyError) as error:
        parse_entry(
            _entry(
                location=[0, 0, 0],
                cad_part={"name": "crate_lid", "params": {"wobble": 1}},
            )
        )
    assert "wobble" in str(error.value)


def test_an_unknown_kind_is_refused():
    with pytest.raises(VocabularyError) as error:
        parse_entry(
            RecipeEntry(path="harbor.weather", kind="weather", params={"location": [0, 0, 0]})
        )
    assert "weather" in str(error.value)


def test_a_missing_location_is_refused():
    with pytest.raises(VocabularyError) as error:
        parse_entry(_entry(cad_part={"name": "crate_lid"}))
    assert "location" in str(error.value)


def test_a_location_of_the_wrong_shape_is_refused():
    with pytest.raises(VocabularyError):
        parse_entry(_entry(location=[0, 0], cad_part={"name": "crate_lid"}))
    with pytest.raises(VocabularyError):
        parse_entry(_entry(location="origin", cad_part={"name": "crate_lid"}))


def test_a_placement_without_geometry_is_refused():
    with pytest.raises(VocabularyError) as error:
        parse_entry(_entry(location=[0, 0, 0]))
    assert "cad_part" in str(error.value)


def test_a_terrain_may_have_no_geometry():
    placement = parse_entry(
        RecipeEntry(path="terrain.ground", kind="terrain", params={"location": [0, 0, 0]})
    )
    assert isinstance(placement, Placement)
    assert placement.cad_part is None


def test_an_unknown_collision_model_is_refused():
    with pytest.raises(VocabularyError) as error:
        parse_entry(
            _entry(
                location=[0, 0, 0],
                cad_part={"name": "crate_lid"},
                collision="boundingBlob",
            )
        )
    assert "boundingBlob" in str(error.value)


def test_a_material_out_of_range_is_refused():
    with pytest.raises(VocabularyError):
        parse_entry(
            RecipeEntry(
                path="materials.oak",
                kind="material",
                params={"base_color": [0.1, 0.2, 0.3], "roughness": 1.4},
            )
        )


def test_a_material_is_read():
    spec = parse_entry(
        RecipeEntry(
            path="materials.oak",
            kind="material",
            params={"base_color": [0.36, 0.24, 0.12], "roughness": 0.7},
        )
    )
    assert spec.base_color == (0.36, 0.24, 0.12)
    assert spec.roughness == 0.7
    assert spec.metallic == 0.0


def test_the_document_keeps_the_spec_shape():
    document = document_from_dict(
        {
            "id": "rcp_test",
            "name": "Test",
            "schema_version": 2,
            "engine_pin": {
                "repo": "SI-Thor/infinigen-thor",
                "commit": "abc",
                "config": "sha256:" + "0" * 64,
                "blender": "4.2",
                "python": "3.12",
            },
            "seeds": {"terrain": 7},
            "entries": {
                "harbor.crates": {
                    "path": "harbor.crates",
                    "kind": "prop_set",
                    "params": {"location": [0, 0, 0]},
                }
            },
            "constraints": [],
        }
    )
    canonical = document.canonical()
    assert set(canonical) == {
        "id",
        "name",
        "schema_version",
        "engine_pin",
        "seeds",
        "entries",
        "constraints",
    }
    assert set(canonical["entries"]["harbor.crates"]) == {
        "path",
        "kind",
        "generator",
        "params",
        "seed",
        "constraints",
        "assets",
        "origin",
    }
    assert document.recipe_hash().startswith("sha256:")
