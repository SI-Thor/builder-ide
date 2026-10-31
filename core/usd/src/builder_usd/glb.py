"""A minimal GLB reader — enough to open a GLB and measure it.

The pass/fail for this spike is that the GLB **opens** and that its bounding
box **matches the part**. Rather than pull in a mesh library for that, this
module reads the container directly: the 12-byte header, the JSON chunk, and
the accessor bounds that glTF already stores for ``POSITION``. The node
transform (a TRS or a matrix) is applied to the accessor corners, because the
accessor bounds live in the mesh's local space and glTF is Y-up while CAD is
Z-up.

Only what the check needs: no textures, no materials, no binary decoding.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["GlbError", "GlbInfo", "read_glb"]

_GLTF_MAGIC = 0x46546C67  # 'glTF'
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class GlbError(ValueError):
    """The file is not a GLB this reader can open."""


@dataclass(frozen=True)
class GlbInfo:
    """What the reader learned about a GLB."""

    version: int
    generator: str
    length: int
    meshes: int
    nodes: int
    triangles: int
    has_uvs: bool
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]


def _quaternion_matrix(rotation: list[float]) -> list[list[float]]:
    x, y, z, w = rotation
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _node_transform(node: dict[str, Any]) -> list[list[float]]:
    """The 3x3 rotation and translation of a node."""
    if "matrix" in node:
        matrix = node["matrix"]
        return [[matrix[0], matrix[4], matrix[8]], [matrix[1], matrix[5], matrix[9]], [matrix[2], matrix[6], matrix[10]]]
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    base = _quaternion_matrix(list(rotation))
    return [[base[row][col] * scale[col] for col in range(3)] for row in range(3)]


def _apply(matrix: list[list[float]], translation: list[float], point: tuple[float, float, float]):
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + translation[0],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + translation[1],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + translation[2],
    )


def read_glb(path: str | Path) -> GlbInfo:
    """Open a GLB and return what the check needs."""
    data = Path(path).read_bytes()
    if len(data) < 12:
        raise GlbError(f"{path} is too short to be a GLB")
    magic, version, length = struct.unpack("<III", data[:12])
    if magic != _GLTF_MAGIC:
        raise GlbError(f"{path} is not a GLB (magic {magic:#x})")
    if length != len(data):
        raise GlbError(f"{path} declares {length} bytes but holds {len(data)}")

    offset = 12
    gltf: dict[str, Any] | None = None
    binary_chunk = 0
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack("<II", data[offset : offset + 8])
        body = data[offset + 8 : offset + 8 + chunk_length]
        if chunk_type == _JSON_CHUNK and gltf is None:
            gltf = json.loads(body.decode("utf-8").rstrip("\x00 \t\r\n"))
        elif chunk_type == _BIN_CHUNK:
            binary_chunk = chunk_length
        offset += 8 + chunk_length
    if gltf is None:
        raise GlbError(f"{path} has no JSON chunk")

    accessors = gltf.get("accessors", [])
    meshes = gltf.get("meshes", [])
    nodes = gltf.get("nodes", [])

    mins: list[float] = []
    maxs: list[float] = []
    triangles = 0
    has_uvs = False

    for node in nodes:
        mesh_index = node.get("mesh")
        if mesh_index is None:
            continue
        mesh = meshes[mesh_index]
        transform = _node_transform(node)
        translation = list(node.get("translation", [0.0, 0.0, 0.0]))
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes", {})
            has_uvs = has_uvs or "TEXCOORD_0" in attributes
            position = attributes.get("POSITION")
            if position is None:
                continue
            accessor = accessors[position]
            if "min" not in accessor or "max" not in accessor:
                raise GlbError(f"{path} has a POSITION accessor without bounds")
            low, high = accessor["min"], accessor["max"]
            for ix in range(2):
                for iy in range(2):
                    for iz in range(2):
                        corner = (
                            low[0] if ix == 0 else high[0],
                            low[1] if iy == 0 else high[1],
                            low[2] if iz == 0 else high[2],
                        )
                        point = _apply(transform, translation, corner)
                        if not mins:
                            mins = list(point)
                            maxs = list(point)
                        else:
                            for axis in range(3):
                                mins[axis] = min(mins[axis], point[axis])
                                maxs[axis] = max(maxs[axis], point[axis])
            indices = primitive.get("indices")
            if indices is not None:
                count = accessors[indices].get("count", 0)
                triangles += count // 3
            else:
                triangles += len(attributes.get("POSITION", []) and []) or 0

    if not mins:
        raise GlbError(f"{path} has no positioned geometry")

    return GlbInfo(
        version=version,
        generator=str((gltf.get("asset") or {}).get("generator", "")),
        length=length,
        meshes=len(meshes),
        nodes=len(nodes),
        triangles=triangles,
        has_uvs=has_uvs,
        bbox_min=(mins[0], mins[1], mins[2]),
        bbox_max=(maxs[0], maxs[1], maxs[2]),
    )
