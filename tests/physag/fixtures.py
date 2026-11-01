"""A synthetic crate, for the tests and for shaking the builder out.

The tests need a mesh they can reason about: a box with a lid on top, a
hole through the middle, and nothing else. It is written as a GLB so the
builder reads it the same way it reads a generated prop — the same reader,
the same frame, the same code path.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

__all__ = ["box_mesh", "write_glb", "crate_mesh"]


def box_mesh(
    size: tuple[float, float, float] = (0.4, 0.4, 0.4),
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[np.ndarray, np.ndarray]:
    """The vertices and triangles of a closed box."""
    sx, sy, sz = (s / 2.0 for s in size)
    cx, cy, cz = center
    corners = np.array(
        [
            [cx - sx, cy - sy, cz - sz],
            [cx + sx, cy - sy, cz - sz],
            [cx + sx, cy + sy, cz - sz],
            [cx - sx, cy + sy, cz - sz],
            [cx - sx, cy - sy, cz + sz],
            [cx + sx, cy - sy, cz + sz],
            [cx + sx, cy + sy, cz + sz],
            [cx - sx, cy + sy, cz + sz],
        ],
        dtype=np.float64,
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],  # bottom
            [4, 5, 6],
            [4, 6, 7],  # top
            [0, 1, 5],
            [0, 5, 4],  # front
            [1, 2, 6],
            [1, 6, 5],  # right
            [2, 3, 7],
            [2, 7, 6],  # back
            [3, 0, 4],
            [3, 4, 7],  # left
        ],
        dtype=np.int64,
    )
    return corners, faces


def crate_mesh(
    body_size: tuple[float, float, float] = (0.4, 0.4, 0.3),
    lid_size: tuple[float, float, float] = (0.42, 0.42, 0.06),
) -> tuple[np.ndarray, np.ndarray]:
    """A crate: a body with a lid sitting on it, as one triangle soup."""
    body_v, body_f = box_mesh(body_size, (0.0, 0.0, body_size[2] / 2.0))
    lid_v, lid_f = box_mesh(lid_size, (0.0, 0.0, body_size[2] + lid_size[2] / 2.0))
    vertices = np.concatenate([body_v, lid_v])
    faces = np.concatenate([body_f, lid_f + body_v.shape[0]])
    return vertices, faces


def write_glb(path: str | Path, vertices: np.ndarray, triangles: np.ndarray) -> Path:
    """Write a triangle mesh as a GLB, the way the generator writes one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    positions = np.asarray(vertices, dtype=np.float32)
    indices = np.asarray(triangles, dtype=np.uint32).reshape(-1)

    buffer = bytearray()
    position_offset = 0
    buffer += positions.tobytes()
    index_offset = len(buffer)
    buffer += indices.tobytes()
    # The index buffer must be four-byte aligned inside the chunk.
    while len(buffer) % 4:
        buffer += b"\x00"

    gltf = {
        "asset": {"version": "2.0", "generator": "physag-lite test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "name": "mesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "material": 0,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "mat",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.8, 0.8, 0.85, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                },
            }
        ],
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": position_offset,
                "byteLength": positions.nbytes,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": index_offset,
                "byteLength": indices.nbytes,
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": int(positions.shape[0]),
                "type": "VEC3",
                "max": positions.max(axis=0).tolist(),
                "min": positions.min(axis=0).tolist(),
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": int(indices.shape[0]),
                "type": "SCALAR",
            },
        ],
    }

    json_bytes = json.dumps(gltf).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(buffer)
    bin_bytes += b"\x00" * ((4 - len(bin_bytes) % 4) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with path.open("wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, total))
        handle.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        handle.write(json_bytes)
        handle.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
        handle.write(bin_bytes)
    return path
