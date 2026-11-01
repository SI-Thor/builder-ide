"""Build GLB files in memory, so the mesh checks can be tested without a GPU.

The GLB writer here is deliberately dumb: it writes exactly what the reader
has to cope with, and nothing more. It lives in the tests because it is
test-only code — the production reader never writes GLBs.
"""

from __future__ import annotations

import json
import math
import struct

__all__ = [
    "build_glb",
    "build_glb_parts",
    "cube_mesh",
    "quad_mesh",
    "bowtie_mesh",
    "mug_mesh",
    "revolve",
    "tetra_mesh",
]


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


def revolve(
    profile: list[tuple[float, float]], segments: int = 48
) -> tuple[list[tuple[float, float, float]], list[int]]:
    """A surface of revolution: a closed profile in (radius, height).

    The profile is a closed loop in the (radius, height) plane; revolving
    it about the height axis gives a closed surface. A loop that starts at
    radius zero and returns to it gives a solid of revolution; a loop that
    does not gives a hollow one.

    A point on the axis is **one** vertex, not a ring of them: a ring of
    coincident vertices would make every triangle around it degenerate,
    and the critic counts degenerate triangles as defects.
    """
    angles = [2.0 * math.pi * index / segments for index in range(segments)]
    positions: list[tuple[float, float, float]] = []
    rings: list[list[int]] = []
    for radius, height in profile:
        if radius == 0.0:
            pole = len(positions)
            positions.append((0.0, 0.0, height))
            rings.append([pole])
            continue
        ring: list[int] = []
        for angle in angles:
            ring.append(len(positions))
            positions.append(
                (radius * math.cos(angle), radius * math.sin(angle), height)
            )
        rings.append(ring)

    indices: list[int] = []
    count = len(profile)
    for index in range(count):
        here = rings[index]
        nxt = rings[(index + 1) % count]
        if len(here) == 1 and len(nxt) == 1:
            continue
        if len(here) == 1:
            pole = here[0]
            for segment in range(segments):
                indices += [pole, nxt[(segment + 1) % segments], nxt[segment]]
            continue
        if len(nxt) == 1:
            pole = nxt[0]
            for segment in range(segments):
                indices += [pole, here[segment], here[(segment + 1) % segments]]
            continue
        for segment in range(segments):
            following = (segment + 1) % segments
            # Wound so the surface faces outward: the signed volume of the
            # result is the material's, and positive.
            indices += [here[segment], nxt[following], nxt[segment]]
            indices += [here[segment], here[following], nxt[following]]
    return positions, indices


def mug_mesh(
    outer: float = 0.04,
    inner: float = 0.035,
    height: float = 0.09,
    bottom: float = 0.005,
) -> tuple[list[tuple[float, float, float]], list[int]]:
    """A **hollow mug**: a wall and a solid bottom, and nothing inside.

    This is the shape the critic used to call a ghost. The ceramic is
    ``pi*outer^2*height - pi*inner^2*(height-bottom) + pi*inner^2*bottom``,
    which is a small fraction of the space the mug occupies — and the space
    it occupies is what the critic has to measure.
    """
    profile = [
        (0.0, 0.0),
        (outer, 0.0),
        (outer, height),
        (inner, height),
        (inner, bottom),
        (0.0, bottom),
    ]
    return revolve(profile)


def build_glb_parts(
    parts: list[tuple[list[tuple[float, float, float]], list[int]]],
    translations: list[tuple[float, float, float]] | None = None,
) -> bytes:
    """A GLB with several mesh primitives, each on its own node.

    The real assets are made of parts — the SimReady forklift is 32 of them
    — and a reader that stops at the first one measures a fragment. This
    writes the shape of such a file: one mesh and one node per part, and
    optionally a translation on the node.
    """
    if translations is not None and len(translations) != len(parts):
        raise ValueError("one translation per part, or none")

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "genbatch-test"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(parts)))}],
        "nodes": [],
        "meshes": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
    }

    binary = bytearray()
    for index, (positions, indices) in enumerate(parts):
        pos_bytes = struct.pack(
            "<%df" % (3 * len(positions)), *[c for p in positions for c in p]
        )
        idx_bytes = struct.pack("<%dI" % len(indices), *indices)
        pos_offset = len(binary)
        binary += pos_bytes
        idx_offset = len(binary)
        binary += idx_bytes

        mins = [min((p[i] for p in positions), default=0.0) for i in range(3)]
        maxs = [max((p[i] for p in positions), default=0.0) for i in range(3)]
        position_accessor = len(gltf["accessors"])
        index_accessor = position_accessor + 1
        gltf["accessors"] += [
            {
                "bufferView": len(gltf["bufferViews"]),
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            },
            {
                "bufferView": len(gltf["bufferViews"]) + 1,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
            },
        ]
        gltf["bufferViews"] += [
            {"buffer": 0, "byteOffset": pos_offset, "byteLength": len(pos_bytes)},
            {"buffer": 0, "byteOffset": idx_offset, "byteLength": len(idx_bytes)},
        ]
        gltf["meshes"].append(
            {
                "name": f"part_{index}",
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor},
                        "indices": index_accessor,
                        "mode": 4,
                    }
                ],
            }
        )
        node: dict = {"mesh": index, "name": f"part_{index}"}
        if translations is not None:
            node["translation"] = list(translations[index])
        gltf["nodes"].append(node)

    gltf["buffers"] = [{"byteLength": len(binary)}]

    json_bytes = _pad4(json.dumps(gltf).encode("utf-8"), b" ")
    bin_bytes = _pad4(bytes(binary))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    out += struct.pack("<II", len(bin_bytes), 0x004E4942) + bin_bytes
    return out
