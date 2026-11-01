"""Load a SimReady asset on the Thor, read its schema, and export it as glTF.

**Why this exists.** SimReady assets are USD packages. The Thor needs to read
them, to know what they are made of (mass, friction, materials, semantics),
and to hand them to the thor-world viewer and the world-stream as glTF. The
Thor already has ``usd-core`` (OpenUSD 26.11) in several project venvs, so the
read side needs nothing new; this module is the seam.

**No glTF library.** builder-ide's own rule, from ``core/genbatch/glb.py``:
"There is no glTF library on the Thor and the Thor does not need one." A
GLB is a twelve-byte header, a JSON chunk and a binary chunk. This module
writes one directly, so the deliverable depends only on ``pxr`` and
``numpy``.

**What it reads.** A SimReady package has a fixed shape::

    <asset>/.metadata/com.nvidia.simready.root_usds.json   the root USD files
    <asset>/com.nvidia.simready.packaging.json             the package manifest
    <asset>/simready_usd/sm_<asset>_01.usd                  the stage
    <asset>/simready_usd/payloads/base.usda                 semantics, mass
    <asset>/simready_usd/payloads/materials.usda            the surfaces
    <asset>/simready_usd/payloads/instances.usda            the mesh instances
    <asset>/simready_usd/payloads/instances_physx.usda      the PhysX variant
    <asset>/simready_usd/payloads/instances_newton.usda     the Newton variant
    <asset>/simready_usd/payloads/instances_mujoco.usda     the MuJoCo variant
    <asset>/simready_usd/payloads/Physics/physics.usda      the physics bodies
    <asset>/simready_usd/payloads/{MuJoCo,Newton,PhysX}/    the variant payloads

The root stage pulls the payloads in by reference and by payload, so opening
the root ``.usd`` is enough to see the whole asset.

**Two things a reader has to know, or it sees nothing.**

*Geometry is instanced.* The geometry prims carry ``instanceable = true``,
so their contents live in USD prototypes and do not appear in a plain
``stage.Traverse()``. The meshes are reached with
``Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())``. A reader
that uses the default traversal finds an asset with no mesh at all.

*Physics is not standard USD physics.* The rigid-body data on these assets
is carried twice over: as standard ``UsdPhysics`` attributes
(``physics:mass``, ``physics:centerOfMass``, ``physics:diagonalInertia``,
``physics:approximation``) and as custom attributes
(``pxr:usd:physics_mass``, ``pxr:usd:physics_centerofmass``). The variant
sets named ``MuJoCo``, ``Newton`` and ``PhysX`` choose which solver's
collider is active: the neutral payload carries a generic collider and the
PhysX payload replaces it with an SDF mesh collider plus contact offsets.

**Using it**

    python3 simready_loader.py probe   ~/lm-cold/simready-sample/dishware_mug_a01
    python3 simready_loader.py convert ~/lm-cold/simready-sample/dishware_mug_a01 out.glb
    python3 simready_loader.py batch   ~/lm-cold/simready-sample outdir/
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

__all__ = [
    "AssetSchema",
    "GlbStats",
    "SimReadyError",
    "asset_dirs",
    "convert_asset",
    "iter_prims",
    "load_stage",
    "read_schema",
    "root_usd_paths",
]


class SimReadyError(RuntimeError):
    """The package is not shaped like a SimReady package."""


# --- the package on disk ----------------------------------------------------


def asset_dirs(root: str | Path) -> list[Path]:
    """Every SimReady package under a root directory, sorted by name."""
    root = Path(root)
    return [
        child
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / "simready_usd").is_dir()
    ]


def root_usd_paths(asset_dir: str | Path) -> list[Path]:
    """The root USD files of a package, from its own metadata.

    The package says which file is the root, and the metadata is the
    authority; the entries are relative to the package directory and
    already carry the ``simready_usd/`` prefix.
    """
    asset_dir = Path(asset_dir)
    metadata = asset_dir / ".metadata" / "com.nvidia.simready.root_usds.json"
    if not metadata.exists():
        raise SimReadyError(f"{asset_dir} has no root_usds.json")
    payload = json.loads(metadata.read_text())
    entries = payload.get("entries") or []
    if not entries:
        raise SimReadyError(f"{metadata} lists no root USD files")
    return [asset_dir / entry for entry in entries]


def load_stage(asset_dir: str | Path, variant: str | None = None):
    """Open a package's root stage.

    ``Usd.Stage.Open`` on the root file composes the references and payloads
    underneath it, so one open sees the whole asset.

    ``variant`` selects one of the physics variant sets (``MuJoCo``,
    ``Newton``, ``PhysX``). The package ships with one of them selected
    already; passing a name switches it, which is how the collider
    differences between the solvers are read.
    """
    from pxr import Usd

    paths = root_usd_paths(asset_dir)
    for path in paths:
        if not path.exists():
            continue
        stage = Usd.Stage.Open(str(path))
        if stage is None:
            continue
        if variant:
            root = stage.GetPrimAtPath("/RootNode")
            if root:
                sets = root.GetVariantSets()
                if variant in sets.GetNames():
                    sets.GetVariantSet(variant).SetVariantSelection("Enabled")
        return stage
    raise SimReadyError(f"no root USD of {asset_dir} could be opened")


def iter_prims(stage, include_instance_proxies: bool = True):
    """Every prim on the stage, including the instance proxies.

    The geometry and the materials of these assets are instanced, so a
    traversal without the instance proxies sees an asset with no mesh and
    no material at all.
    """
    from pxr import Usd

    if include_instance_proxies:
        return Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())
    return stage.Traverse()


# --- the schema -------------------------------------------------------------


@dataclass
class AssetSchema:
    """What a SimReady asset carries beyond its mesh."""

    asset: str
    #: The stage's units: metres per unit, and the up axis.
    meters_per_unit: float | None = None
    up_axis: str | None = None
    #: The prim types present, with counts.
    prim_types: dict[str, int] = field(default_factory=dict)
    #: How many meshes, and how many triangles over them.
    meshes: int = 0
    triangles: int = 0
    points: int = 0
    #: The semantic labels the asset declares (wikidata class or label).
    semantic_labels: list[str] = field(default_factory=list)
    semantic_types: list[str] = field(default_factory=list)
    #: The SimReady asset type and conformance profile.
    asset_type: str | None = None
    profile: str | None = None
    profile_version: str | None = None
    uuid: str | None = None
    #: The physics variant sets the package offers, and the one selected.
    physics_variants: list[str] = field(default_factory=list)
    physics_variant_selected: dict[str, str] = field(default_factory=dict)
    #: Rigid-body facts.
    mass_kg_total: float | None = None
    mass_bodies: int = 0
    mass_min_kg: float | None = None
    mass_max_kg: float | None = None
    center_of_mass: list[float] | None = None
    inertia: list[float] | None = None
    density_kg_m3: list[float] = field(default_factory=list)
    #: Colliders.
    colliders: int = 0
    collider_approximations: list[str] = field(default_factory=list)
    collision_enabled: bool | None = None
    #: Friction and restitution.
    static_friction: list[float] = field(default_factory=list)
    dynamic_friction: list[float] = field(default_factory=list)
    restitution: list[float] = field(default_factory=list)
    #: Articulation: joints, and the prims they attach.
    joints: int = 0
    joint_types: list[str] = field(default_factory=list)
    joint_paths: list[str] = field(default_factory=list)
    #: Manipulation affordances: the grasp curves.
    grasp_curves: int = 0
    #: Materials.
    materials: int = 0
    shaders: list[str] = field(default_factory=list)
    mdl_libraries: list[str] = field(default_factory=list)
    textures: int = 0
    #: LOD.
    lods: int = 0
    lod_levels: list[int] = field(default_factory=list)
    #: The world-space bounding box of the geometry, in metres.
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    #: The world-space extents (size) of the geometry, in metres.
    size_m: list[float] | None = None
    #: Each mesh's own world-space box, in traversal order, so a reader that
    #: only opens the first primitive can be checked against the right one.
    mesh_boxes: list[dict[str, Any]] = field(default_factory=list)




def _transform(points: np.ndarray, matrix) -> np.ndarray:
    """Apply a USD transform to an (n, 3) array of points."""
    m = np.array(matrix, dtype=np.float64)
    return points @ m[:3, :3].T + m[3, :3]


def _transform_direction(directions: np.ndarray, matrix) -> np.ndarray:
    """Apply a USD transform to an (n, 3) array of directions (no translation)."""
    m = np.array(matrix, dtype=np.float64)
    return directions @ m[:3, :3].T


def _world_bbox(stage) -> tuple[list[float] | None, list[float] | None]:
    """The world-space bounds of every point on the stage."""
    from pxr import Usd, UsdGeom

    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    seen = False
    for prim in iter_prims(stage):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        points = UsdGeom.Mesh(prim).GetPointsAttr().Get()
        if not points:
            continue
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()
        )
        transformed = _transform(np.asarray(points, dtype=np.float64), matrix)
        for index in range(3):
            low[index] = min(low[index], float(transformed[:, index].min()))
            high[index] = max(high[index], float(transformed[:, index].max()))
        seen = True
    if not seen:
        return None, None
    return low, high


def read_schema(stage, asset_name: str = "") -> AssetSchema:
    """Read everything a SimReady asset carries beyond its mesh."""
    from pxr import Usd, UsdGeom, UsdShade

    schema = AssetSchema(asset=asset_name)

    # -- units ---------------------------------------------------------------
    try:
        schema.meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        schema.meters_per_unit = None
    try:
        axis = UsdGeom.GetStageUpAxis(stage)
        schema.up_axis = str(axis).rsplit(".", 1)[-1] if axis else None
    except Exception:
        schema.up_axis = None

    # -- prim census ---------------------------------------------------------
    types: dict[str, int] = {}
    for prim in iter_prims(stage):
        name = prim.GetTypeName() or "<untyped>"
        types[name] = types.get(name, 0) + 1
    schema.prim_types = dict(sorted(types.items(), key=lambda kv: -kv[1]))

    # -- geometry ------------------------------------------------------------
    for prim in iter_prims(stage):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        schema.meshes += 1
        counts = mesh.GetFaceVertexCountsAttr().Get() or []
        triangles = sum(max(int(c) - 2, 0) for c in counts)
        schema.triangles += triangles
        points = mesh.GetPointsAttr().Get()
        schema.points += len(points) if points else 0
        if points:
            matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default()
            )
            transformed = _transform(np.asarray(points, dtype=np.float64), matrix)
            schema.mesh_boxes.append(
                {
                    "name": str(prim.GetPath()),
                    "bbox_min": [float(v) for v in transformed.min(axis=0)],
                    "bbox_max": [float(v) for v in transformed.max(axis=0)],
                    "points": int(transformed.shape[0]),
                    "triangles": int(triangles),
                }
            )
        if (prim.GetTypeName() or "") == "LOD":
            schema.lods += 1
            schema.lod_levels.append(len(prim.GetAttribute("lodLevels").Get() or []))

    # -- semantics -----------------------------------------------------------
    for prim in iter_prims(stage):
        for attribute in prim.GetAttributes():
            name = attribute.GetName()
            value = attribute.Get()
            if value is None:
                continue
            if name.startswith("semantics:labels:"):
                schema.semantic_labels.extend(
                    str(v) for v in (value if isinstance(value, (list, tuple)) else [value])
                )
            elif name.startswith("semantic:") and name.endswith(":params:semanticData"):
                schema.semantic_types.append(str(value))

    # -- package-level metadata, on the layer -------------------------------
    try:
        layer = stage.GetRootLayer()
        data = layer.customLayerData or {}
        meta = data.get("SimReady_Metadata") or {}
        schema.asset_type = meta.get("asset_type")
        schema.uuid = meta.get("uuid")
        validation = meta.get("validation") or {}
        schema.profile = validation.get("profile")
        schema.profile_version = validation.get("profile_version")
        variants = (meta.get("Variants") or {}).get("Physics") or {}
        schema.physics_variants = sorted(variants)
    except Exception:
        pass

    # -- the variant selections actually in force ---------------------------
    root = stage.GetPrimAtPath("/RootNode")
    if root:
        for name in root.GetVariantSets().GetNames():
            variant_set = root.GetVariantSets().GetVariantSet(name)
            schema.physics_variant_selected[name] = variant_set.GetVariantSelection()

    # -- physics -------------------------------------------------------------
    # The same rigid body is described twice: the mesh prim carries the
    # standard ``physics:mass``, and the Xform that wraps it carries a copy
    # of the same number in the custom ``pxr:usd:physics_mass`` space.
    # Counting both would double every asset's mass, so the standard
    # attributes win and the custom ones are the fallback.
    standard_masses: list[float] = []
    custom_masses: list[float] = []
    approximations: list[str] = []
    for prim in iter_prims(stage):
        names = {attribute.GetName() for attribute in prim.GetAttributes()}
        applied = set(prim.GetAppliedSchemas())

        if "physics:mass" in names:
            mass = prim.GetAttribute("physics:mass").Get()
            if mass is not None:
                standard_masses.append(float(mass))
        elif "pxr:usd:physics_mass" in names:
            mass = prim.GetAttribute("pxr:usd:physics_mass").Get()
            if mass is not None:
                custom_masses.append(float(mass))
        if "physics:centerOfMass" in names and schema.center_of_mass is None:
            value = prim.GetAttribute("physics:centerOfMass").Get()
            if value is not None:
                schema.center_of_mass = [float(v) for v in value]
        if "pxr:usd:physics_centerofmass" in names and schema.center_of_mass is None:
            value = prim.GetAttribute("pxr:usd:physics_centerofmass").Get()
            if value is not None:
                schema.center_of_mass = [float(v) for v in value]
        if "physics:diagonalInertia" in names and schema.inertia is None:
            value = prim.GetAttribute("physics:diagonalInertia").Get()
            if value is not None:
                schema.inertia = [float(v) for v in value]
        if "pxr:usd:physics_inertia" in names and schema.inertia is None:
            value = prim.GetAttribute("pxr:usd:physics_inertia").Get()
            if value is not None:
                schema.inertia = [float(v) for v in value]
        if "physics:density" in names:
            value = prim.GetAttribute("physics:density").Get()
            if value is not None:
                schema.density_kg_m3.append(float(value))

        if "PhysicsColliderAPI" in applied or "PhysicsCollisionAPI" in applied:
            schema.colliders += 1
            approximation = prim.GetAttribute("physics:approximation").Get()
            if approximation is not None:
                approximations.append(str(approximation))
            enabled = prim.GetAttribute("physics:collisionEnabled").Get()
            if enabled is not None:
                schema.collision_enabled = bool(enabled)

        for attribute_name, target in (
            ("physics:staticFriction", schema.static_friction),
            ("physics:dynamicFriction", schema.dynamic_friction),
            ("physics:restitution", schema.restitution),
        ):
            if attribute_name in names:
                value = prim.GetAttribute(attribute_name).Get()
                if value is not None:
                    target.append(float(value))

        # Articulation.
        type_name = prim.GetTypeName() or ""
        if type_name.startswith("Physics") and type_name.endswith("Joint"):
            schema.joints += 1
            schema.joint_types.append(type_name)
            schema.joint_paths.append(str(prim.GetPath()))

    masses = standard_masses or custom_masses
    schema.mass_bodies = len(masses)
    if masses:
        schema.mass_kg_total = float(sum(masses))
        schema.mass_min_kg = float(min(masses))
        schema.mass_max_kg = float(max(masses))
    schema.collider_approximations = sorted(set(approximations))

    # -- grasp curves --------------------------------------------------------
    for prim in iter_prims(stage):
        if (prim.GetTypeName() or "") == "BasisCurves":
            name = prim.GetPath().pathString.lower()
            if "grasp" in name:
                schema.grasp_curves += 1

    # -- materials -----------------------------------------------------------
    for prim in iter_prims(stage):
        if not prim.IsA(UsdShade.Material):
            continue
        schema.materials += 1
        try:
            output = UsdShade.Material(prim).GetSurfaceOutput()
            source = output.GetConnectedSource() if output else None
        except Exception:
            source = None
        if not source:
            continue
        connectable = source[0]
        try:
            shader_prim = connectable.GetPrim()
            schema.shaders.append(shader_prim.GetTypeName() or "<shader>")
        except Exception:
            continue

    # The MDL libraries and the textures are referenced by asset-path
    # attributes, which is where the surface definitions actually live.
    for prim in iter_prims(stage):
        for attribute in prim.GetAttributes():
            if str(attribute.GetTypeName()) != "asset":
                continue
            value = attribute.Get()
            if value is None:
                continue
            text = str(value)
            if text.lower().endswith(".mdl"):
                schema.mdl_libraries.append(text)
            elif text.lower().endswith((".png", ".jpg", ".jpeg")):
                schema.textures += 1
    schema.shaders = sorted(set(schema.shaders))
    schema.mdl_libraries = sorted(set(schema.mdl_libraries))

    # -- bounds --------------------------------------------------------------
    schema.bbox_min, schema.bbox_max = _world_bbox(stage)
    if schema.bbox_min and schema.bbox_max:
        schema.size_m = [
            round(schema.bbox_max[axis] - schema.bbox_min[axis], 6) for axis in range(3)
        ]
    return schema


# --- the glTF writer --------------------------------------------------------

_COMPONENT_FLOAT = 5126
_COMPONENT_UINT32 = 5125


@dataclass
class GlbStats:
    """What the conversion produced."""

    asset: str
    glb_bytes: int
    meshes: int
    primitives: int
    vertices: int
    triangles: int
    materials: int
    seconds: float
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    size_m: list[float] | None = None


def _collect_meshes(stage) -> list[dict[str, Any]]:
    """Every mesh on the stage, in world space, with normals and UVs."""
    from pxr import Usd, UsdGeom

    meshes: list[dict[str, Any]] = []
    for prim in iter_prims(stage):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        if not points or not counts or not indices:
            continue
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()
        )
        vertices = _transform(np.asarray(points, dtype=np.float64), matrix)

        # Triangulate: a face with n vertices becomes n-2 triangles.
        triangles: list[int] = []
        offset = 0
        for count in counts:
            count = int(count)
            if count >= 3:
                for index in range(1, count - 1):
                    triangles.append(int(indices[offset]))
                    triangles.append(int(indices[offset + index]))
                    triangles.append(int(indices[offset + index + 1]))
            offset += count
        triangle_array = np.asarray(triangles, dtype=np.uint32)

        normal_attr = mesh.GetNormalsAttr().Get()
        if normal_attr:
            normals = _transform_direction(
                np.asarray(normal_attr, dtype=np.float64), matrix
            )
        else:
            normals = _face_normals(vertices, triangle_array.astype(np.int64))

        uvs = None
        primvar = UsdGeom.PrimvarsAPI(prim).GetPrimvar("st")
        if primvar and primvar.HasValue():
            values = primvar.Get()
            if values:
                per_vertex = np.asarray([value[0] for value in values], dtype=np.float64)
                uvs = per_vertex[triangle_array.astype(np.int64)]

        meshes.append(
            {
                "name": prim.GetName(),
                "vertices": vertices,
                "triangles": triangle_array,
                "normals": normals,
                "uvs": uvs,
            }
        )
    return meshes


def _face_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Per-vertex normals from the face normals, for a mesh with no normals."""
    normals = np.zeros_like(vertices)
    faces = triangles.reshape(-1, 3)
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    face_normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(face_normals, axis=1, keepdims=True)
    face_normals = face_normals / np.where(lengths > 1e-12, lengths, 1.0)
    for column in range(3):
        np.add.at(normals, faces[:, column], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.where(lengths > 1e-12, lengths, 1.0)


def _material_table(stage) -> list[dict[str, Any]]:
    """The materials on the stage, as glTF PBR values."""
    from pxr import UsdShade

    materials: list[dict[str, Any]] = []
    seen: set[str] = set()
    for prim in iter_prims(stage):
        if not prim.IsA(UsdShade.Material):
            continue
        name = prim.GetName()
        if name in seen:
            continue
        seen.add(name)
        entry = {
            "name": name,
            "base_color": [0.8, 0.8, 0.8, 1.0],
            "metallic": 0.0,
            "roughness": 0.5,
        }
        try:
            output = UsdShade.Material(prim).GetSurfaceOutput()
            source = output.GetConnectedSource() if output else None
        except Exception:
            source = None
        if source:
            connectable = source[0]
            try:
                for input_name, key in (
                    ("diffuseColor", "base_color"),
                    ("metallic", "metallic"),
                    ("roughness", "roughness"),
                ):
                    attribute = connectable.GetInput(input_name)
                    if attribute and attribute.HasAuthoredValue():
                        value = attribute.Get()
                        if value is not None:
                            entry[key] = (
                                [float(v) for v in value]
                                if key == "base_color"
                                else float(value)
                            )
            except Exception:
                pass
        materials.append(entry)
    return materials


def _build_gltf(
    meshes: list[dict[str, Any]], materials: list[dict[str, Any]]
) -> tuple[dict[str, Any], bytes]:
    """Assemble the glTF JSON and its binary buffer."""
    buffer = bytearray()
    accessors: list[dict[str, Any]] = []
    buffer_views: list[dict[str, Any]] = []
    gltf_meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    def add_view(data: bytes, target: int | None = None) -> int:
        while len(buffer) % 4:
            buffer.append(0)
        offset = len(buffer)
        buffer.extend(data)
        view: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        }
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def add_accessor(
        array: np.ndarray, component: int, type_name: str, target: int | None
    ) -> int:
        # The bytes on the wire must be the width the accessor declares.
        # numpy's default float is float64, and glTF's POSITION is float32:
        # writing float64 bytes under a float32 accessor produces a file
        # that every reader decodes into garbage.
        if component == _COMPONENT_FLOAT:
            array = np.ascontiguousarray(array, dtype=np.float32)
        elif component == _COMPONENT_UINT32:
            array = np.ascontiguousarray(array, dtype=np.uint32)
        else:
            array = np.ascontiguousarray(array)
        raw = array.tobytes()
        view = add_view(raw, target)
        accessor: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": int(array.shape[0]),
            "type": type_name,
        }
        if array.ndim == 1:
            accessor["min"] = [float(array.min())]
            accessor["max"] = [float(array.max())]
        else:
            accessor["min"] = [float(v) for v in array.min(axis=0)]
            accessor["max"] = [float(v) for v in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    for mesh in meshes:
        position = add_accessor(mesh["vertices"], _COMPONENT_FLOAT, "VEC3", 34962)
        attributes = {"POSITION": position}
        if mesh["normals"] is not None and len(mesh["normals"]) == len(mesh["vertices"]):
            attributes["NORMAL"] = add_accessor(
                mesh["normals"], _COMPONENT_FLOAT, "VEC3", 34962
            )
        if mesh["uvs"] is not None and len(mesh["uvs"]) == len(mesh["vertices"]):
            attributes["TEXCOORD_0"] = add_accessor(
                mesh["uvs"], _COMPONENT_FLOAT, "VEC2", 34962
            )
        indices = add_accessor(mesh["triangles"], _COMPONENT_UINT32, "SCALAR", 34963)
        gltf_meshes.append(
            {
                "name": mesh["name"],
                "primitives": [{"attributes": attributes, "indices": indices, "mode": 4}],
            }
        )
        nodes.append({"name": mesh["name"], "mesh": len(gltf_meshes) - 1})

    gltf_materials = [
        {
            "name": material["name"],
            "pbrMetallicRoughness": {
                "baseColorFactor": material["base_color"],
                "metallicFactor": material["metallic"],
                "roughnessFactor": material["roughness"],
            },
            "doubleSided": True,
        }
        for material in materials
    ]

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "simready_loader"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "materials": gltf_materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(buffer)}],
    }
    return gltf, bytes(buffer)


def _write_glb(path: str | Path, gltf: dict[str, Any], binary: bytes) -> int:
    """Write a GLB: a header, a JSON chunk and a binary chunk."""
    document = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(document) % 4:
        document += b" "
    blob = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(document) + 8 + len(blob)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, total))
        handle.write(struct.pack("<II", len(document), 0x4E4F534A))
        handle.write(document)
        handle.write(struct.pack("<II", len(blob), 0x004E4942))
        handle.write(blob)
    return total


def convert_asset(asset_dir: str | Path, out_path: str | Path) -> GlbStats:
    """Convert one SimReady package to a GLB, and time it."""
    started = time.perf_counter()
    asset_dir = Path(asset_dir)
    stage = load_stage(asset_dir)
    meshes = _collect_meshes(stage)
    materials = _material_table(stage)
    gltf, binary = _build_gltf(meshes, materials)

    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for mesh in meshes:
        vertices = mesh["vertices"]
        for axis in range(3):
            low[axis] = min(low[axis], float(vertices[:, axis].min()))
            high[axis] = max(high[axis], float(vertices[:, axis].max()))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    size = _write_glb(out_path, gltf, binary)
    elapsed = time.perf_counter() - started
    has_geometry = bool(meshes)
    return GlbStats(
        asset=asset_dir.name,
        glb_bytes=size,
        meshes=len(meshes),
        primitives=sum(len(m["primitives"]) for m in gltf["meshes"]),
        vertices=sum(len(m["vertices"]) for m in meshes),
        triangles=sum(len(m["triangles"]) // 3 for m in meshes),
        materials=len(materials),
        seconds=elapsed,
        bbox_min=low if has_geometry else None,
        bbox_max=high if has_geometry else None,
        size_m=[high[axis] - low[axis] for axis in range(3)] if has_geometry else None,
    )


# --- the command line -------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="read an asset's schema")
    probe.add_argument("asset", help="the package directory")
    probe.add_argument("--variant", help="a physics variant to select")

    convert = sub.add_parser("convert", help="convert a package to GLB")
    convert.add_argument("asset", help="the package directory")
    convert.add_argument("out", help="the .glb path to write")

    batch = sub.add_parser("batch", help="convert every package under a root")
    batch.add_argument("root", help="the directory holding the packages")
    batch.add_argument("outdir", help="the directory to write the .glb files into")
    batch.add_argument("--json", help="write the timings as JSON here")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "probe":
        stage = load_stage(args.asset, variant=args.variant)
        schema = read_schema(stage, Path(args.asset).name)
        print(json.dumps(schema.to_json() if hasattr(schema, "to_json") else asdict(schema), indent=2))
        return 0

    if args.command == "convert":
        stats = convert_asset(args.asset, args.out)
        print(json.dumps(asdict(stats), indent=2))
        return 0

    if args.command == "batch":
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        results = []
        for asset in asset_dirs(args.root):
            try:
                stats = convert_asset(asset, outdir / f"{asset.name}.glb")
            except Exception as error:
                results.append(
                    {"asset": asset.name, "error": f"{type(error).__name__}: {error}"}
                )
                print(f"{asset.name}: {type(error).__name__}: {error}", file=sys.stderr)
                continue
            results.append(asdict(stats))
            print(
                f"{asset.name}: {stats.glb_bytes / 1024**2:.1f} MiB, "
                f"{stats.triangles} triangles, {stats.seconds:.2f}s",
                flush=True,
            )
        if args.json:
            Path(args.json).write_text(json.dumps(results, indent=2) + "\n")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
