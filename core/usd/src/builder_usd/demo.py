"""The demo recipe — a small Fjellvik harbour, used by the CLI and the tests.

Nothing here is a scenario: it is the smallest recipe that exercises every
layer of the compiler — a material, two CAD parts that share a script, a
placement with no geometry at all (the ground), semantics, physics, and a
provenance record for each.

The recipe is in the shape core-spec v2 §1.1 gives it, plus the provenance
records that the scheduler would stamp (core-spec v2 §1.6) — kept in a
separate map so the recipe document itself stays spec-shaped.
"""

from __future__ import annotations

from typing import Any

__all__ = ["demo_bundle", "demo_recipe"]

_ENGINE_PIN = {
    "repo": "SI-Thor/infinigen-thor",
    "commit": "0000000000000000000000000000000000000000",
    "config": "sha256:" + "0" * 64,
    "blender": "4.2",
    "python": "3.12",
}


def demo_recipe() -> dict[str, Any]:
    """The recipe document, in the spec's shape."""
    return {
        "id": "rcp_fjellvik",
        "name": "Fjellvik",
        "schema_version": 2,
        "engine_pin": dict(_ENGINE_PIN),
        "seeds": {"terrain": 7, "props": 11, "weather": 3},
        "entries": {
            "materials.oak": {
                "path": "materials.oak",
                "kind": "material",
                "params": {
                    "base_color": [0.36, 0.24, 0.12],
                    "roughness": 0.7,
                    "metallic": 0.0,
                },
                "origin": "builtin",
            },
            "materials.iron": {
                "path": "materials.iron",
                "kind": "material",
                "params": {
                    "base_color": [0.22, 0.23, 0.25],
                    "roughness": 0.35,
                    "metallic": 1.0,
                },
                "origin": "builtin",
            },
            "harbor.crate_stack": {
                "path": "harbor.crate_stack",
                "kind": "prop_set",
                "seed": 11,
                "origin": "wo_14",
                "params": {
                    "location": [3.5, 0.0, -1.25],
                    "rotation_euler_deg": [0.0, 15.0, 0.0],
                    "cad_part": {
                        "name": "crate_lid",
                        "params": {"length": 0.6, "width": 0.4, "thickness": 0.02},
                    },
                    "material": "materials.oak",
                    "semantic_type": "crate",
                    "semantic_tags": ["harbor", "wood"],
                    "mass_kg": 12.5,
                    "collision": "boundingCube",
                },
            },
            "harbor.mooring_post": {
                "path": "harbor.mooring_post",
                "kind": "structure",
                "seed": 11,
                "origin": "wo_14",
                "params": {
                    "location": [1.0, 0.0, 0.45],
                    "cad_part": {
                        "name": "mooring_post",
                        "params": {"height": 0.9, "diameter": 0.14},
                    },
                    "material": "materials.iron",
                    "semantic_type": "post",
                    "semantic_tags": ["harbor", "metal"],
                    "mass_kg": 48.0,
                    "collision": "boundingCube",
                },
            },
            "harbor.hinge_bracket": {
                "path": "harbor.hinge_bracket",
                "kind": "structure",
                "seed": 11,
                "origin": "wo_14",
                "params": {
                    "location": [2.0, 0.35, 0.2],
                    "rotation_euler_deg": [90.0, 0.0, 0.0],
                    "cad_part": {
                        "name": "hinge_bracket",
                        "params": {
                            "length": 0.12,
                            "width": 0.08,
                            "thickness": 0.008,
                            "hole_diameter": 0.012,
                            "hole_offset": 0.04,
                        },
                    },
                    "material": "materials.iron",
                    "semantic_type": "bracket",
                    "semantic_tags": ["harbor", "metal"],
                    "mass_kg": 0.4,
                    "collision": "mesh",
                },
            },
            "terrain.ground": {
                "path": "terrain.ground",
                "kind": "terrain",
                "seed": 7,
                "origin": "builtin",
                "params": {
                    "location": [0.0, 0.0, 0.0],
                    "semantic_type": "ground",
                    "semantic_tags": ["terrain"],
                },
            },
        },
        "constraints": [],
    }


def demo_bundle() -> dict[str, Any]:
    """The recipe plus the provenance records the scheduler would stamp."""
    return {
        "recipe": demo_recipe(),
        "provenance": {
            "harbor.crate_stack": {
                "source": "cad_script",
                "prompt": "crate_lid(length=0.6,width=0.4,thickness=0.02)",
                "model": "build123d",
                "seed": 11,
                "version": "0.13.0",
                "licence": {
                    "spdx": "Apache-2.0",
                    "dependency_terms": ["OCCT LGPL-2.1-with-exception"],
                    "commercial_ok": True,
                    "notes": "build123d code is Apache-2.0.",
                },
                "weights": {"repo": None, "revision": None},
                "library_versions": {"build123d": "0.13.0", "usd-core": "26.11"},
                "recipe_version_hash": None,
                "engine_pin": dict(_ENGINE_PIN),
            },
            "harbor.mooring_post": {
                "source": "cad_script",
                "prompt": "mooring_post(height=0.9,diameter=0.14)",
                "model": "build123d",
                "seed": 11,
                "version": "0.13.0",
                "licence": {
                    "spdx": "Apache-2.0",
                    "dependency_terms": ["OCCT LGPL-2.1-with-exception"],
                    "commercial_ok": True,
                    "notes": None,
                },
                "weights": {"repo": None, "revision": None},
                "library_versions": {"build123d": "0.13.0", "usd-core": "26.11"},
                "recipe_version_hash": None,
                "engine_pin": dict(_ENGINE_PIN),
            },
            "harbor.hinge_bracket": {
                "source": "cad_script",
                "prompt": "hinge_bracket(length=0.12,width=0.08,thickness=0.008)",
                "model": "build123d",
                "seed": 11,
                "version": "0.13.0",
                "licence": {
                    "spdx": "Apache-2.0",
                    "dependency_terms": ["OCCT LGPL-2.1-with-exception"],
                    "commercial_ok": True,
                    "notes": None,
                },
                "weights": {"repo": None, "revision": None},
                "library_versions": {"build123d": "0.13.0", "usd-core": "26.11"},
                "recipe_version_hash": None,
                "engine_pin": dict(_ENGINE_PIN),
            },
            "terrain.ground": {
                "source": "library",
                "prompt": "fjellvik terrain base",
                "model": "infinigen-thor",
                "seed": 7,
                "version": "0.0.0",
                "licence": {
                    "spdx": "BSD-3-Clause",
                    "dependency_terms": [],
                    "commercial_ok": True,
                    "notes": "Infinigen's procedural terrain is BSD-3-Clause.",
                },
                "weights": {"repo": None, "revision": None},
                "library_versions": {"infinigen-thor": "thor-spike"},
                "recipe_version_hash": None,
                "engine_pin": dict(_ENGINE_PIN),
            },
        },
    }
