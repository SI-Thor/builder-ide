"""CAD parts as code: build123d → STEP (master) → GLB (interchange) → mesh.

res-cad §1: build123d is the primary CAD authoring API — typed, property
based, Apache-2.0, explicitly supported on linux/aarch64, and pure CPU. The
kernel is OCCT, which has no RNG and no GPU anywhere in the dependency tree:
the same script plus a pinned wheel gives byte-identical geometry.

Three files come out of one part, each with a job:

``<part>.step``
    the **master** — CAD-precise, re-editable. Its header carries a
    timestamp, so the export pins it to the epoch; an unstable header would
    make every re-emission a diff.
``<part>.glb``
    the **interchange** copy, for the ProArt client and for Blender. It
    carries UVs and the glTF Y-up convention.
``<part>.usda``
    the part as a **USD asset layer** — the thing the stage's geometry layer
    references, so the composition arc is a real USD reference.

The mesh is tessellated from the same OCCT shape and converted from CAD's
Z-up to USD's Y-up (``x, z, -y``), so the USD geometry, the GLB and the part
agree on the same box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "PART_BUILDERS",
    "PART_PARAMETERS",
    "STEP_TIMESTAMP",
    "TESSELLATION_TOLERANCE",
    "MeshData",
    "build_part",
    "export_part",
    "tessellate",
    "cad_to_yup",
    "known_part",
]

#: The pinned STEP header timestamp. OCCT writes the wall clock into the
#: STEP header, which would make every re-emission a diff; the epoch is the
#: same convention SOURCE_DATE_EPOCH uses.
STEP_TIMESTAMP = "1970-01-01T00:00:00"

#: Linear deflection of the tessellation, in metres (0.5 mm).
TESSELLATION_TOLERANCE = 0.0005

#: Angular deflection of the tessellation, in radians.
TESSELLATION_ANGULAR_TOLERANCE = 0.2


def _hinge_bracket(length: float, width: float, thickness: float, hole_diameter: float, hole_offset: float):
    """A flat bracket with a bolt hole near one end."""
    from build123d import Box, Cylinder, Pos

    body = Box(length, width, thickness)
    hole = Pos(length / 2.0 - hole_offset, 0.0, 0.0) * Cylinder(hole_diameter / 2.0, thickness * 3.0)
    return body - hole


def _crate_lid(length: float, width: float, thickness: float, handle_width: float):
    """A crate lid with a raised handle."""
    from build123d import Box, Pos

    lid = Box(length, width, thickness)
    handle = Pos(0.0, width / 2.0 - handle_width / 2.0, 0.0) * Box(
        handle_width, handle_width, thickness * 3.0
    )
    return lid + handle


def _mooring_post(height: float, diameter: float):
    """A post with a wider cap."""
    from build123d import Cylinder, Pos

    shaft = Cylinder(diameter / 2.0, height)
    cap = Pos(0.0, 0.0, height / 2.0) * Cylinder(diameter * 0.65, height * 0.08)
    return shaft + cap


#: The closed set of part scripts. A name outside this set is refused.
PART_BUILDERS: dict[str, Callable[..., Any]] = {
    "hinge_bracket": _hinge_bracket,
    "crate_lid": _crate_lid,
    "mooring_post": _mooring_post,
}

#: The parameters each part script accepts, with their defaults in metres.
PART_PARAMETERS: dict[str, dict[str, float]] = {
    "hinge_bracket": {
        "length": 0.12,
        "width": 0.08,
        "thickness": 0.008,
        "hole_diameter": 0.012,
        "hole_offset": 0.04,
    },
    "crate_lid": {
        "length": 0.6,
        "width": 0.4,
        "thickness": 0.02,
        "handle_width": 0.12,
    },
    "mooring_post": {
        "height": 0.9,
        "diameter": 0.14,
    },
}


@dataclass(frozen=True)
class MeshData:
    """A tessellated part, in USD's Y-up convention."""

    points: tuple[tuple[float, float, float], ...]
    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]
    normals: tuple[tuple[float, float, float], ...]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]

    @property
    def triangles(self) -> int:
        return len(self.face_vertex_counts)


def cad_to_yup(point: tuple[float, float, float]) -> tuple[float, float, float]:
    """Convert a CAD (Z-up) point to the world (Y-up): ``x, z, -y``."""
    x, y, z = point
    return (x, z, -y)


def known_part(name: str, params: dict[str, float] | None = None) -> None:
    """Refuse an unknown part name or an unknown parameter of a part.

    The door, at the vocabulary level: the part registry is data, so the
    check costs nothing and does not need the CAD kernel loaded.
    """
    if name not in PART_BUILDERS:
        raise ValueError(
            f"unknown CAD part {name!r}; the closed set is {sorted(PART_BUILDERS)}"
        )
    defaults = PART_PARAMETERS[name]
    for key in (params or {}):
        if key not in defaults:
            raise ValueError(
                f"CAD part {name!r} has no parameter {key!r}; it accepts {sorted(defaults)}"
            )


def build_part(name: str, params: dict[str, float] | None = None):
    """Build a part by name. Unknown names and unknown parameters are refused."""
    known_part(name, params)
    builder = PART_BUILDERS[name]
    defaults = PART_PARAMETERS[name]
    merged: dict[str, float] = dict(defaults)
    for key, value in (params or {}).items():
        merged[key] = float(value)
    return builder(**merged)


def tessellate(shape, tolerance: float = TESSELLATION_TOLERANCE,
               angular_tolerance: float = TESSELLATION_ANGULAR_TOLERANCE) -> MeshData:
    """Tessellate an OCCT shape into a Y-up triangle mesh with vertex normals."""
    vertices, triangles = shape.tessellate(
        tolerance=tolerance, angular_tolerance=angular_tolerance
    )
    points = tuple(cad_to_yup((float(v.X), float(v.Y), float(v.Z))) for v in vertices)

    counts: list[int] = []
    indices: list[int] = []
    accumulated = [[0.0, 0.0, 0.0] for _ in points]
    for triangle in triangles:
        counts.append(len(triangle))
        indices.extend(int(i) for i in triangle)
        a, b, c = (points[i] for i in triangle)
        ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        for i in triangle:
            accumulated[i][0] += nx
            accumulated[i][1] += ny
            accumulated[i][2] += nz

    normals: list[tuple[float, float, float]] = []
    for nx, ny, nz in accumulated:
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length == 0.0:
            normals.append((0.0, 0.0, 1.0))
        else:
            normals.append((nx / length, ny / length, nz / length))

    mins = tuple(min(point[axis] for point in points) for axis in range(3))
    maxs = tuple(max(point[axis] for point in points) for axis in range(3))
    return MeshData(
        points=points,
        face_vertex_counts=tuple(counts),
        face_vertex_indices=tuple(indices),
        normals=tuple(normals),
        bbox_min=mins,
        bbox_max=maxs,
    )


@dataclass(frozen=True)
class PartFiles:
    """The files one part produced."""

    step: Path
    glb: Path


def export_part(shape, out_dir: Path, name: str) -> PartFiles:
    """Write the STEP master and the GLB interchange copy of a part.

    Both exports are deterministic for a pinned wheel: the STEP header's
    timestamp is pinned to the epoch, and the GLB is a pure function of the
    shape. The STEP is written in **millimetres** — OCCT's STEP length unit —
    with build123d scaling the metres-authored shape into it; the GLB is in
    **metres**, the glTF convention.
    """
    from build123d.build_enums import Unit
    from build123d.exporters3d import export_gltf, export_step

    out_dir.mkdir(parents=True, exist_ok=True)
    step_path = out_dir / f"{name}.step"
    glb_path = out_dir / f"{name}.glb"
    export_step(shape, str(step_path), unit=Unit.M, timestamp=STEP_TIMESTAMP)
    export_gltf(shape, str(glb_path), unit=Unit.M, binary=True)
    return PartFiles(step=step_path, glb=glb_path)
