"""Build GLB files in memory, so the mesh checks can be tested without a GPU.

The GLB writer here is deliberately dumb: it writes exactly what the reader
has to cope with, and nothing more. It lives in the tests because it is
test-only code — the production reader never writes GLBs.
"""

from __future__ import annotations

import json
import struct

__all__ = ["build_glb", "cube_mesh", "quad_mesh", "bowtie_mesh", "tetra_mesh"]


def _pad4(data: bytes, fill: bytes = b"\x00") -> bytes:
    return data + fill * ((4 - len(data) % 4) % 4)


def build_glb(positions: list[tuple[float, float, float]], indices: list[int]) -> bytes:
    """A GLB with one mesh primitive: POSITION (float32) + indices (uint32)."""
    pos_bytes = struct.pack(
        "<%df" % (3 * len(positions)), *[c for p in positions for c in p]
    )
    idx_bytes = struct.pack("<%dI" % len(indices), *indices)
    mins = [min((p[i] for p in positions), default=0.0) for i in range(3)]
    maxs = [max((p[i] for p in positions), default=0.0) for i in range(3)]
    gltf = {
        "asset": {"version": "2.0", "generator": "genbatch-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "mesh"}],
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}
                ]
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(pos_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(pos_bytes),
                "byteLength": len(idx_bytes),
                "target": 34963,
            },
        ],
        "buffers": [{"byteLength": len(pos_bytes) + len(idx_bytes)}],
    }
    # The GLB spec pads the JSON chunk with spaces and the binary chunk with
    # zeros, each to a four-byte boundary.
    json_bytes = _pad4(json.dumps(gltf).encode("utf-8"), b" ")
    bin_bytes = _pad4(pos_bytes + idx_bytes)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    out += struct.pack("<II", len(bin_bytes), 0x004E4942) + bin_bytes
    return out


def cube_mesh() -> tuple[list[tuple[float, float, float]], list[int]]:
    """A unit cube centred on the origin: 8 vertices, 12 triangles."""
    positions = [
        (-0.5, -0.5, -0.5),
        (0.5, -0.5, -0.5),
        (0.5, 0.5, -0.5),
        (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5),
        (0.5, -0.5, 0.5),
        (0.5, 0.5, 0.5),
        (-0.5, 0.5, 0.5),
    ]
    indices = [
        0, 2, 1, 0, 3, 2,  # -z
        4, 5, 6, 4, 6, 7,  # +z
        0, 1, 5, 0, 5, 4,  # -y
        3, 7, 6, 3, 6, 2,  # +y
        0, 4, 7, 0, 7, 3,  # -x
        1, 2, 6, 1, 6, 5,  # +x
    ]
    return positions, indices


def quad_mesh() -> tuple[list[tuple[float, float, float]], list[int]]:
    """An open square: two triangles, four boundary edges."""
    positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    indices = [0, 1, 2, 0, 2, 3]
    return positions, indices


def bowtie_mesh() -> tuple[list[tuple[float, float, float]], list[int]]:
    """Three triangles hanging off one shared edge: a non-manifold edge.

    Edge (0, 2) is used by all three triangles, so it is not a manifold edge —
    the mesh has a seam that cannot be closed.
    """
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (-1.0, 1.0, 0.0),
    ]
    indices = [0, 1, 2, 0, 2, 3, 0, 2, 4]
    return positions, indices


def tetra_mesh() -> tuple[list[tuple[float, float, float]], list[int]]:
    """A unit tetrahedron: 4 vertices, 4 triangles, volume 1/6."""
    positions = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    indices = [0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3]
    return positions, indices
