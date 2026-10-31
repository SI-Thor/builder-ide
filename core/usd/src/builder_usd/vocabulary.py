"""The compiler's closed, typed vocabulary.

CLAUDE.md: builders change recipes through a closed, typed vocabulary, never
by writing code. The same rule applies one level down — the USD compiler
reads a small set of parameter names and **refuses everything else at the
door**, with the offending key named. An unknown parameter is not a warning
that scrolls past; it is an error, because a parameter nobody understands is
a parameter that silently does nothing.

Two things can be compiled:

``Placement``
    an entry of kind ``structure``, ``prop_set``, ``asset_ref`` or ``terrain``
    that puts something in the world at a place;

``MaterialSpec``
    an entry of kind ``material`` that describes a surface.

Placement parameters
--------------------
``location``          ``[x, y, z]`` metres (required)
``rotation_euler_deg`` ``[rx, ry, rz]`` degrees about X, Y, Z
``scale``             a number, or ``[sx, sy, sz]``
``cad_part``          ``{"name": ..., "params": {...}}`` — a build123d script
``asset``             a prebuilt asset file name inside the assets directory
``material``          the path of a ``material`` entry to bind
``semantic_type``     a SimReady-lite semantic class (``crate``, ``post`` …)
``semantic_tags``     a list of semantic tags
``mass_kg``           the rigid-body mass, for the physics layer
``collision``         the collision approximation (``boundingCube`` …)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from builder_usd import cad
from builder_usd.recipe_source import RecipeEntry

__all__ = [
    "VocabularyError",
    "PartSpec",
    "MaterialSpec",
    "Placement",
    "PLACEMENT_KINDS",
    "MATERIAL_KINDS",
    "parse_entry",
    "prim_path_for",
]

#: Entry kinds that put something in the world.
PLACEMENT_KINDS = ("structure", "prop_set", "asset_ref", "terrain")

#: Entry kinds that describe a surface.
MATERIAL_KINDS = ("material",)

_PLACEMENT_KEYS = {
    "location",
    "rotation_euler_deg",
    "scale",
    "cad_part",
    "asset",
    "material",
    "semantic_type",
    "semantic_tags",
    "mass_kg",
    "collision",
}

_MATERIAL_KEYS = {"base_color", "roughness", "metallic"}

_COLLISION_MODELS = ("none", "boundingCube", "boundingSphere", "convexHull", "mesh")


class VocabularyError(ValueError):
    """A recipe entry the compiler refuses, with the reason and the key."""


@dataclass(frozen=True)
class PartSpec:
    """A CAD part to build: a name from the closed set, plus its parameters."""

    name: str
    params: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "params": dict(self.params)}


@dataclass(frozen=True)
class MaterialSpec:
    """A surface described by a recipe entry."""

    path: str
    base_color: tuple[float, float, float] = (0.8, 0.8, 0.8)
    roughness: float = 0.5
    metallic: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "base_color": list(self.base_color),
            "roughness": self.roughness,
            "metallic": self.metallic,
        }


@dataclass(frozen=True)
class Placement:
    """Something in the world, at a place, with what it is made of."""

    entry_path: str
    prim_path: str
    kind: str
    location: tuple[float, float, float]
    rotation_euler_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    cad_part: PartSpec | None = None
    asset: str | None = None
    material: str | None = None
    semantic_type: str | None = None
    semantic_tags: tuple[str, ...] = ()
    mass_kg: float | None = None
    collision: str | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_path": self.entry_path,
            "prim_path": self.prim_path,
            "kind": self.kind,
            "location": list(self.location),
            "rotation_euler_deg": list(self.rotation_euler_deg),
            "scale": list(self.scale),
            "cad_part": self.cad_part.to_dict() if self.cad_part else None,
            "asset": self.asset,
            "material": self.material,
            "semantic_type": self.semantic_type,
            "semantic_tags": list(self.semantic_tags),
            "mass_kg": self.mass_kg,
            "collision": self.collision,
            "seed": self.seed,
        }


def prim_path_for(entry_path: str) -> str:
    """The USD prim path an entry path becomes: ``harbor.crates`` → ``/World/harbor/crates``."""
    return "/World/" + "/".join(entry_path.split("."))


def _refuse(entry: RecipeEntry, message: str) -> VocabularyError:
    return VocabularyError(f"entry {entry.path!r}: {message}")


def _number(value: Any, entry: RecipeEntry, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _refuse(entry, f"parameter {key!r} must be a number, got {value!r}")
    return float(value)


def _vector3(value: Any, entry: RecipeEntry, key: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _refuse(entry, f"parameter {key!r} must be three numbers, got {value!r}")
    return (
        _number(value[0], entry, key),
        _number(value[1], entry, key),
        _number(value[2], entry, key),
    )


def _scale(value: Any, entry: RecipeEntry) -> tuple[float, float, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (float(value), float(value), float(value))
    return _vector3(value, entry, "scale")


def _part_spec(value: Any, entry: RecipeEntry) -> PartSpec:
    if not isinstance(value, dict):
        raise _refuse(entry, "parameter 'cad_part' must be an object")
    unknown = sorted(set(value) - {"name", "params"})
    if unknown:
        raise _refuse(entry, f"parameter 'cad_part' has unknown keys {unknown}")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise _refuse(entry, "parameter 'cad_part' needs a 'name'")
    raw_params = value.get("params") or {}
    if not isinstance(raw_params, dict):
        raise _refuse(entry, "parameter 'cad_part.params' must be an object")
    params = {}
    for key, item in sorted(raw_params.items()):
        params[str(key)] = _number(item, entry, f"cad_part.params.{key}")
    try:
        cad.known_part(name, params)
    except ValueError as error:
        raise _refuse(entry, str(error)) from error
    return PartSpec(name=name, params=params)


def _material_spec(entry: RecipeEntry) -> MaterialSpec:
    params = entry.params
    unknown = sorted(set(params) - _MATERIAL_KEYS)
    if unknown:
        raise _refuse(entry, f"unknown parameter(s) {unknown}; allowed: {sorted(_MATERIAL_KEYS)}")
    base_color = _vector3(params.get("base_color", [0.8, 0.8, 0.8]), entry, "base_color")
    roughness = _number(params.get("roughness", 0.5), entry, "roughness")
    metallic = _number(params.get("metallic", 0.0), entry, "metallic")
    for name, value in (("roughness", roughness), ("metallic", metallic)):
        if not 0.0 <= value <= 1.0:
            raise _refuse(entry, f"parameter {name!r} must be within [0, 1], got {value}")
    return MaterialSpec(path=entry.path, base_color=base_color, roughness=roughness, metallic=metallic)


def parse_entry(entry: RecipeEntry) -> Placement | MaterialSpec:
    """Turn one recipe entry into what the compiler understands.

    Raises :class:`VocabularyError` — the door — for anything outside the
    closed vocabulary.
    """
    if entry.kind in MATERIAL_KINDS:
        return _material_spec(entry)
    if entry.kind not in PLACEMENT_KINDS:
        raise _refuse(
            entry,
            f"kind {entry.kind!r} is not compiled by the USD backbone "
            f"(supported: {sorted(PLACEMENT_KINDS + MATERIAL_KINDS)})",
        )

    params = entry.params
    unknown = sorted(set(params) - _PLACEMENT_KEYS)
    if unknown:
        raise _refuse(entry, f"unknown parameter(s) {unknown}; allowed: {sorted(_PLACEMENT_KEYS)}")

    if "location" not in params:
        raise _refuse(entry, "parameter 'location' is required")
    location = _vector3(params["location"], entry, "location")
    rotation = _vector3(params.get("rotation_euler_deg", [0.0, 0.0, 0.0]), entry, "rotation_euler_deg")
    scale = _scale(params.get("scale", 1.0), entry)

    cad_part = None
    if "cad_part" in params:
        cad_part = _part_spec(params["cad_part"], entry)
    asset = params.get("asset")
    if asset is not None and not isinstance(asset, str):
        raise _refuse(entry, f"parameter 'asset' must be a string, got {asset!r}")
    if cad_part is None and asset is None and entry.kind != "terrain":
        raise _refuse(entry, "needs either a 'cad_part' or an 'asset' to have geometry")

    material = params.get("material")
    if material is not None and not isinstance(material, str):
        raise _refuse(entry, f"parameter 'material' must be a string, got {material!r}")

    semantic_type = params.get("semantic_type")
    if semantic_type is not None and not isinstance(semantic_type, str):
        raise _refuse(entry, f"parameter 'semantic_type' must be a string, got {semantic_type!r}")

    tags = params.get("semantic_tags", [])
    if not isinstance(tags, (list, tuple)):
        raise _refuse(entry, "parameter 'semantic_tags' must be a list of strings")
    for tag in tags:
        if not isinstance(tag, str):
            raise _refuse(entry, f"parameter 'semantic_tags' must be a list of strings, got {tag!r}")

    mass_kg = params.get("mass_kg")
    if mass_kg is not None:
        mass_kg = _number(mass_kg, entry, "mass_kg")

    collision = params.get("collision")
    if collision is not None:
        if not isinstance(collision, str):
            raise _refuse(entry, f"parameter 'collision' must be a string, got {collision!r}")
        if collision not in _COLLISION_MODELS:
            raise _refuse(
                entry,
                f"parameter 'collision' must be one of {list(_COLLISION_MODELS)}, got {collision!r}",
            )

    return Placement(
        entry_path=entry.path,
        prim_path=prim_path_for(entry.path),
        kind=entry.kind,
        location=location,
        rotation_euler_deg=rotation,
        scale=scale,
        cad_part=cad_part,
        asset=asset,
        material=material,
        semantic_type=semantic_type,
        semantic_tags=tuple(tags),
        mass_kg=mass_kg,
        collision=collision,
        seed=entry.seed,
    )
