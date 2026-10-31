"""The compiler: recipe → layered USD.

res-cad §8: the recipe is the source of truth and **USD is a compiled output
and an assembly cache** — one way, never back. core-spec v2 §7.11 adopts
that verbatim, and this module is the compiler it describes.

The stage is layered by concern, one layer per question:

``geometry.usda``
    the layout — what is where. Placement prims, their transforms, and a
    **reference arc** into the part's own USD layer.
``materials.usda``
    the surfaces — ``UsdShade`` materials and the bindings onto the
    placements.
``physics.usda``
    the rigid bodies — mass and collision approximation.
``semantics.usda``
    what the things *are* — the SimReady-lite semantic class and tags.
``provenance.usda``
    where everything came from — the ``customData`` record: prompt, model,
    seed, version, licence, and the asset files pinned by sha256.
``root.usda``
    the composition root — the five layers above, in alphabetical order, with
    ``World`` as the default prim.

Two rules keep the composition honest — both measured on this box, not
assumed:

* **one key, one layer.** USD *merges* ``customData`` dictionaries across
  layers and across composition arcs; the stronger opinion wins **per key**,
  and the dictionary is not replaced. So each concern owns a distinct key
  inside ``customData``: ``provenance`` and ``asset`` for a placement,
  ``part`` for the asset's own record. (A typed prim also picks up a
  ``userDocBrief`` key from its schema — that one is USD's doing.)
* **one writer per concern.** Layers are authored independently and the root
  layer lists them alphabetically, so no layer's opinion depends on another's
  order. The first sublayer is the strongest — also measured — so the
  geometry layer, which owns the structure, leads.

And the whole thing is a pure function of the recipe: same recipe, same
bytes. Sorted prims, quantised floats, no timestamps anywhere.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt

from builder_usd import cad
from builder_usd.canonical import canonical_json, canonical_value, hash_bytes, quantize_float
from builder_usd.provenance import (
    ASSET_KEY,
    PART_KEY,
    PROVENANCE_KEY,
    AssetFile,
    AssetRecord,
    Licence,
    Provenance,
    to_usd_value,
)
from builder_usd.recipe_source import RecipeDocument, RecipeSource
from builder_usd.vocabulary import (
    MaterialSpec,
    Placement,
    PartSpec,
    parse_entry,
    prim_path_for,
)

__all__ = [
    "CONCERNS",
    "ROOT_LAYER_NAME",
    "ASSET_DIR",
    "CompiledAsset",
    "CompileResult",
    "compile_recipe",
    "toolchain_versions",
    "default_provenance",
]

#: The concerns, one layer each. The root layer lists them alphabetically.
CONCERNS = ("geometry", "materials", "physics", "provenance", "semantics")

#: The composition root.
ROOT_LAYER_NAME = "root.usda"

#: Where the CAD assets live, relative to the stage.
ASSET_DIR = "assets"

#: The prim path of the part inside a part layer.
PART_PRIM_PATH = "/Part"


@dataclass(frozen=True)
class CompiledAsset:
    """One CAD part, compiled: its files, its USD layer, and its bounds."""

    name: str
    entry_paths: tuple[str, ...]
    step: AssetFile
    glb: AssetFile
    usd_layer: AssetFile
    prim_path: str
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entries": list(self.entry_paths),
            "step": self.step.to_dict(),
            "glb": self.glb.to_dict(),
            "usd": self.usd_layer.to_dict(),
            "prim_path": self.prim_path,
            "bbox_min": list(self.bbox_min),
            "bbox_max": list(self.bbox_max),
        }


@dataclass(frozen=True)
class CompileResult:
    """What a compile produced."""

    out_dir: Path
    recipe_hash: str
    layers: dict[str, str]
    assets: dict[str, CompiledAsset]
    files: dict[str, str]
    manifest: dict[str, Any] = field(default_factory=dict)

    def file_paths(self) -> list[Path]:
        return [self.out_dir / name for name in sorted(self.files)]


def toolchain_versions() -> dict[str, str]:
    """The versions of the tools that wrote the stage — part of the record."""
    import importlib.metadata as metadata
    import platform

    try:
        usd_version = metadata.version("usd-core")
    except Exception:  # noqa: BLE001
        from pxr import Usd as _Usd

        usd_version = ".".join(str(part) for part in _Usd.GetVersion()[1:])
    try:
        build123d_version = metadata.version("build123d")
    except Exception:  # noqa: BLE001
        build123d_version = "unknown"
    return {
        "python": platform.python_version(),
        "build123d": build123d_version,
        "usd-core": usd_version,
    }


# --------------------------------------------------------------------------
# layer authoring helpers
# --------------------------------------------------------------------------


def _new_layer(path: Path) -> Sdf.Layer:
    """A fresh, empty layer on disk — the compiler owns its output directory."""
    if path.exists():
        path.unlink()
    return Sdf.Layer.CreateNew(str(path))


def _ensure_over(layer: Sdf.Layer, path: str) -> Sdf.PrimSpec:
    """Make sure ``path`` exists in ``layer`` as an ``over``, with ancestors."""
    current = ""
    for part in path.strip("/").split("/"):
        current = current + "/" + part
        spec = layer.GetPrimAtPath(current)
        if not spec:
            spec = Sdf.CreatePrimInLayer(layer, current)
            spec.specifier = Sdf.SpecifierOver
    return layer.GetPrimAtPath(path)


def _ensure_typed_parent(stage: Usd.Stage, path: str) -> None:
    """Create the ancestor prims of ``path`` as scopes, if they are missing."""
    parts = path.strip("/").split("/")
    current = ""
    for part in parts[:-1]:
        current = current + "/" + part
        if not stage.GetPrimAtPath(current):
            UsdGeom.Scope.Define(stage, current)


def _vec3(values: Iterable[float]) -> tuple[float, float, float]:
    x, y, z = (quantize_float(value) for value in values)
    return (x, y, z)


def _author_part_layer(
    path: Path, mesh: cad.MeshData, name: str, provenance: Provenance, asset: AssetRecord
) -> None:
    """Write a part's own USD layer: an Xform ``Part`` holding a Mesh.

    The part carries **its own** record — the script that made it, the kernel
    version, the licence — under its own ``customData`` key, so that the
    asset's history travels with the asset and does not merge with the
    placement's record. (USD merges ``customData`` dictionaries; distinct
    keys are what keep the two records apart.)
    """
    layer = Sdf.Layer.CreateAnonymous(".usda")
    stage = Usd.Stage.Open(layer)
    part = UsdGeom.Xform.Define(stage, PART_PRIM_PATH)
    part.GetPrim().SetMetadata("kind", "component")
    part.GetPrim().SetCustomDataByKey(PART_KEY, to_usd_value(provenance.to_dict()))
    part.GetPrim().SetCustomDataByKey(ASSET_KEY, to_usd_value(asset.to_dict()))
    usd_mesh = UsdGeom.Mesh.Define(stage, PART_PRIM_PATH + "/mesh")
    usd_mesh.CreatePointsAttr().Set(
        Vt.Vec3fArray([Gf.Vec3f(*point) for point in mesh.points])
    )
    usd_mesh.CreateFaceVertexCountsAttr().Set(Vt.IntArray(list(mesh.face_vertex_counts)))
    usd_mesh.CreateFaceVertexIndicesAttr().Set(Vt.IntArray(list(mesh.face_vertex_indices)))
    usd_mesh.CreateNormalsAttr().Set(
        Vt.Vec3fArray([Gf.Vec3f(*normal) for normal in mesh.normals])
    )
    usd_mesh.CreateExtentAttr().Set(
        Vt.Vec3fArray([Gf.Vec3f(*mesh.bbox_min), Gf.Vec3f(*mesh.bbox_max)])
    )
    usd_mesh.CreateSubdivisionSchemeAttr().Set(UsdGeom.Tokens.none)
    stage.SetDefaultPrim(part.GetPrim())
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    layer.Export(str(path))


def _author_geometry(
    layer: Sdf.Layer,
    placements: list[Placement],
    assets: dict[str, CompiledAsset],
) -> None:
    """The layout layer: where everything is, and what it is made of."""
    stage = Usd.Stage.Open(layer)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    for placement in sorted(placements, key=lambda item: item.prim_path):
        _ensure_typed_parent(stage, placement.prim_path)
        prim = UsdGeom.Xform.Define(stage, placement.prim_path)
        asset = assets.get(placement.entry_path)
        if asset is not None:
            prim.GetPrim().GetReferences().AddReference(
                Sdf.Reference(asset.usd_layer.path, asset.prim_path)
            )
        prim.AddTranslateOp().Set(Gf.Vec3d(*_vec3(placement.location)))
        if any(placement.rotation_euler_deg):
            prim.AddRotateXYZOp().Set(Gf.Vec3f(*_vec3(placement.rotation_euler_deg)))
        if any(value != 1.0 for value in placement.scale):
            prim.AddScaleOp().Set(Gf.Vec3f(*_vec3(placement.scale)))


def _author_materials(
    layer: Sdf.Layer,
    materials: dict[str, MaterialSpec],
    placements: list[Placement],
) -> None:
    """The materials layer: the surfaces, and what they are bound to.

    The ancestors are ``over`` specs, not typed prims: a layer that defines
    ``/World`` as a ``Scope`` while the geometry layer defines it as an
    ``Xform`` is a typeName conflict waiting to happen, and the geometry
    layer owns the structure.
    """
    stage = Usd.Stage.Open(layer)
    for path in sorted(materials):
        spec = materials[path]
        material_path = prim_path_for(path)
        parent_path = material_path.rsplit("/", 1)[0]
        _ensure_over(layer, parent_path)
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, material_path + "/surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(*_vec3(spec.base_color))
        )
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(
            quantize_float(spec.roughness)
        )
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(
            quantize_float(spec.metallic)
        )
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    for placement in sorted(placements, key=lambda item: item.prim_path):
        if not placement.material:
            continue
        if placement.material not in materials:
            raise ValueError(
                f"entry {placement.entry_path!r} binds material {placement.material!r}, "
                "which is not a material entry of this recipe"
            )
        _ensure_over(layer, placement.prim_path)
        prim = stage.GetPrimAtPath(placement.prim_path)
        prim.CreateRelationship("material:binding").SetTargets(
            [Sdf.Path(prim_path_for(placement.material))]
        )


def _author_physics(layer: Sdf.Layer, placements: list[Placement]) -> None:
    """The physics layer: rigid bodies, mass, collision approximation."""
    for placement in sorted(placements, key=lambda item: item.prim_path):
        if placement.mass_kg is None and placement.collision is None:
            continue
        spec = _ensure_over(layer, placement.prim_path)
        schemas = Sdf.TokenListOp()
        schemas.prependedItems = ["PhysicsRigidBodyAPI", "PhysicsCollisionAPI"]
        spec.SetInfo("apiSchemas", schemas)
        if placement.mass_kg is not None:
            attribute = Sdf.AttributeSpec(spec, "physics:mass", Sdf.ValueTypeNames.Float)
            attribute.default = quantize_float(placement.mass_kg)
        if placement.collision is not None:
            attribute = Sdf.AttributeSpec(
                spec, "physics:approximateCollision", Sdf.ValueTypeNames.Token
            )
            attribute.default = placement.collision
            enabled = Sdf.AttributeSpec(
                spec, "physics:collisionEnabled", Sdf.ValueTypeNames.Bool
            )
            enabled.default = True


def _author_semantics(layer: Sdf.Layer, placements: list[Placement]) -> None:
    """The semantics layer: what the things are (SimReady-lite, in attributes).

    SimReady writes its semantic keys into ``customData``. This backbone
    cannot: ``customData`` has one writer per prim, and the provenance layer
    owns it. So the semantic class and its tags are custom *attributes* with
    the ``semantic:`` prefix — the same information, in a place two layers can
    share.
    """
    for placement in sorted(placements, key=lambda item: item.prim_path):
        if placement.semantic_type is None and not placement.semantic_tags:
            continue
        spec = _ensure_over(layer, placement.prim_path)
        if placement.semantic_type is not None:
            attribute = Sdf.AttributeSpec(spec, "semantic:type", Sdf.ValueTypeNames.Token)
            attribute.default = placement.semantic_type
        if placement.semantic_tags:
            attribute = Sdf.AttributeSpec(
                spec, "semantic:tags", Sdf.ValueTypeNames.TokenArray
            )
            attribute.default = Vt.TokenArray(list(placement.semantic_tags))


def _author_provenance(
    layer: Sdf.Layer,
    placements: list[Placement],
    assets: dict[str, CompiledAsset],
    provenance: dict[str, Provenance],
) -> None:
    """The provenance layer: the ``customData`` record, one owner per prim."""
    for placement in sorted(placements, key=lambda item: item.prim_path):
        record = provenance.get(placement.entry_path)
        if record is None:
            continue
        asset = assets.get(placement.entry_path)
        data: dict[str, Any] = {PROVENANCE_KEY: record.to_dict()}
        if asset is not None:
            data[ASSET_KEY] = {
                asset.glb.role: asset.glb.to_dict(),
                asset.step.role: asset.step.to_dict(),
                asset.usd_layer.role: asset.usd_layer.to_dict(),
            }
        spec = _ensure_over(layer, placement.prim_path)
        spec.SetInfo("customData", to_usd_value(data))


def _author_root(path: Path, layer_names: list[str]) -> None:
    """The composition root: the concern layers, in alphabetical order.

    The root layer holds no prims of its own — the structure belongs to the
    geometry layer — only the composition and the stage's units.
    """
    layer = _new_layer(path)
    stage = Usd.Stage.Open(layer)
    layer.defaultPrim = "World"
    for name in sorted(layer_names):
        layer.subLayerPaths.append(name)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    layer.Save()


# --------------------------------------------------------------------------
# provenance defaults
# --------------------------------------------------------------------------


def default_provenance(
    placement: Placement,
    recipe: RecipeDocument,
    library_versions: dict[str, str],
) -> Provenance:
    """The provenance of a part the compiler built itself.

    The scheduler stamps provenance for generated assets (core-spec v2 §1.6);
    a CAD part has no model behind it, so the compiler stamps what it knows:
    the script is the asset, the kernel version is the version, and the
    licence is build123d's Apache-2.0 with OCCT's terms riding with it.
    """
    prompt = ""
    if placement.cad_part is not None:
        prompt = f"{placement.cad_part.name}({canonical_json(placement.cad_part.params)})"
    return Provenance(
        source="cad_script",
        prompt=prompt,
        model="build123d",
        seed=placement.seed,
        version=library_versions.get("build123d", "unknown"),
        licence=Licence(
            spdx="Apache-2.0",
            dependency_terms=("OCCT LGPL-2.1-with-exception",),
            commercial_ok=True,
            notes="build123d code is Apache-2.0; the OCCT kernel is LGPL-2.1 with an exception.",
        ),
        weights_repo=None,
        weights_revision=None,
        library_versions=dict(library_versions),
        recipe_version_hash=recipe.recipe_hash(),
        engine_pin=recipe.engine_pin.to_dict(),
    )


# --------------------------------------------------------------------------
# the compile
# --------------------------------------------------------------------------


def _part_key(spec: PartSpec) -> str:
    return spec.name + ":" + canonical_json(spec.params)


def compile_recipe(
    source: RecipeSource,
    out_dir: Path,
    provenance: dict[str, Provenance] | None = None,
) -> CompileResult:
    """Compile a recipe into a layered USD stage.

    ``out_dir`` is owned by the compiler: the layers, the assets directory
    and the manifest are rewritten on every run.
    """
    document = source.document()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    placements: list[Placement] = []
    materials: dict[str, MaterialSpec] = {}
    seeds: dict[str, int] = {}
    for path in sorted(document.entries):
        entry = document.entries[path]
        parsed = parse_entry(entry)
        if isinstance(parsed, MaterialSpec):
            materials[parsed.path] = parsed
        else:
            placements.append(parsed)
        if entry.seed is not None:
            seeds[path] = entry.seed

    placements.sort(key=lambda item: item.prim_path)

    # -- the assets: one CAD part per distinct script ----------------------
    asset_dir = out_dir / ASSET_DIR
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    versions = toolchain_versions()
    assets: dict[str, CompiledAsset] = {}
    by_key: dict[str, CompiledAsset] = {}
    for placement in placements:
        if placement.cad_part is None:
            continue
        key = _part_key(placement.cad_part)
        asset = by_key.get(key)
        if asset is None:
            asset = _compile_part(placement.cad_part, asset_dir, versions)
            by_key[key] = asset
        assets[placement.entry_path] = asset

    # -- the layers ---------------------------------------------------------
    # The layers are authored on disk, not in memory: a layer that knows its
    # own directory resolves its relative references while it is being
    # written, so a broken reference is caught at compile time rather than
    # when somebody opens the stage.
    layer_paths: dict[str, Path] = {}
    for concern in CONCERNS:
        layer_paths[concern] = out_dir / f"{concern}.usda"

    geometry = _new_layer(layer_paths["geometry"])
    _author_geometry(geometry, placements, assets)
    geometry.Save()

    materials_layer = _new_layer(layer_paths["materials"])
    _author_materials(materials_layer, materials, placements)
    materials_layer.Save()

    physics = _new_layer(layer_paths["physics"])
    _author_physics(physics, placements)
    physics.Save()

    semantics = _new_layer(layer_paths["semantics"])
    _author_semantics(semantics, placements)
    semantics.Save()

    provenance_layer = _new_layer(layer_paths["provenance"])
    records = dict(provenance or {})
    for placement in placements:
        records.setdefault(
            placement.entry_path, default_provenance(placement, document, versions)
        )
    _author_provenance(provenance_layer, placements, assets, records)
    provenance_layer.Save()

    root_path = out_dir / ROOT_LAYER_NAME
    _author_root(root_path, [f"{concern}.usda" for concern in CONCERNS])

    # -- the manifest -------------------------------------------------------
    files: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[path.relative_to(out_dir).as_posix()] = hash_bytes(path.read_bytes())

    manifest = {
        "recipe": {
            "id": document.id,
            "name": document.name,
            "hash": document.recipe_hash(),
            "engine_pin": document.engine_pin.to_dict(),
        },
        "layers": {concern: f"{concern}.usda" for concern in sorted(CONCERNS)},
        "root": ROOT_LAYER_NAME,
        "assets": {
            path: asset.to_dict() for path, asset in sorted(assets.items())
        },
        "placements": [placement.to_dict() for placement in placements],
        "materials": {path: spec.to_dict() for path, spec in sorted(materials.items())},
        "toolchain": versions,
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        canonical_json(canonical_value(manifest)) + "\n", encoding="utf-8"
    )

    return CompileResult(
        out_dir=out_dir,
        recipe_hash=document.recipe_hash(),
        layers={concern: f"{concern}.usda" for concern in sorted(CONCERNS)},
        assets=assets,
        files=files,
        manifest=manifest,
    )


def _compile_part(
    spec: PartSpec, asset_dir: Path, versions: dict[str, str]
) -> CompiledAsset:
    """Build one part, export its files, and write its USD layer."""
    shape = cad.build_part(spec.name, spec.params)
    files = cad.export_part(shape, asset_dir, spec.name)
    mesh = cad.tessellate(shape)

    def _file(role: str, path: Path) -> AssetFile:
        data = path.read_bytes()
        return AssetFile(
            role=role,
            path=path.relative_to(asset_dir.parent).as_posix(),
            sha256=hash_bytes(data),
            bytes=len(data),
        )

    step_file = _file("master", files.step)
    glb_file = _file("glb", files.glb)
    usd_path = asset_dir / f"{spec.name}.usda"

    part_provenance = Provenance(
        source="cad_script",
        prompt=f"{spec.name}({canonical_json(spec.params)})",
        model="build123d",
        seed=None,
        version=versions.get("build123d", "unknown"),
        licence=Licence(
            spdx="Apache-2.0",
            dependency_terms=("OCCT LGPL-2.1-with-exception",),
            commercial_ok=True,
            notes="build123d code is Apache-2.0; the OCCT kernel is LGPL-2.1 with an exception.",
        ),
        library_versions=dict(versions),
    )
    _author_part_layer(
        usd_path,
        mesh,
        spec.name,
        part_provenance,
        AssetRecord(files=(step_file, glb_file)),
    )
    usd_file = _file("usd", usd_path)

    return CompiledAsset(
        name=spec.name,
        entry_paths=(),
        step=step_file,
        glb=glb_file,
        usd_layer=usd_file,
        prim_path=PART_PRIM_PATH,
        bbox_min=mesh.bbox_min,
        bbox_max=mesh.bbox_max,
    )
