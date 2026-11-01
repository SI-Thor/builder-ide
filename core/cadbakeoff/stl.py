"""A minimal STL reader and writer.

The meshes are small (a prop's worth of triangles), so the reader keeps the
vertices in memory and the comparator works on them directly.

The URDF world is in metres, so the writer takes metres and the reader returns
metres.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Mesh", "read_stl", "write_stl"]


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]

    @property
    def bbox(self) -> tuple[float, float, float, float, float, float]:
        if not self.vertices:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def scaled(self, factor: float) -> "Mesh":
        return Mesh(
            vertices=[(v[0] * factor, v[1] * factor, v[2] * factor) for v in self.vertices],
            triangles=list(self.triangles),
        )


def read_stl(path: str | Path) -> Mesh:
    data = Path(path).read_bytes()
    if data[:5].lower() == b"solid" and b"facet" in data[:2048]:
        return _read_ascii(data)
    return _read_binary(data)


def _read_binary(data: bytes) -> Mesh:
    count = struct.unpack_from("<I", data, 80)[0]
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    offset = 84
    for _ in range(count):
        vals = struct.unpack_from("<12f", data, offset)
        offset += 50
        base = len(vertices)
        vertices.append((vals[3], vals[4], vals[5]))
        vertices.append((vals[6], vals[7], vals[8]))
        vertices.append((vals[9], vals[10], vals[11]))
        triangles.append((base, base + 1, base + 2))
    return Mesh(vertices=vertices, triangles=triangles)


def _read_ascii(data: bytes) -> Mesh:
    text = data.decode("utf-8", errors="replace")
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    current: list[int] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0] == "vertex":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            current.append(len(vertices) - 1)
            if len(current) == 3:
                triangles.append((current[0], current[1], current[2]))
                current = []
    return Mesh(vertices=vertices, triangles=triangles)


def write_stl(path: str | Path, mesh: Mesh, name: str = "prop") -> None:
    """Write a binary STL.

    The layout is the one the reader (and every other STL tool) expects: an
    80-byte header, a 4-byte little-endian triangle count, then 50 bytes per
    triangle — twelve floats for the normal and the three vertices, and a
    2-byte attribute. The count is not optional: a reader that starts the
    triangles at byte 84 reads the first triangle's normal as the count if
    it is missing.
    """
    out = bytearray()
    header = name.encode("utf-8")[:80]
    out += header + b"\0" * (80 - len(header))
    out += struct.pack("<I", len(mesh.triangles))
    for a, b, c in mesh.triangles:
        va, vb, vc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        ux, uy, uz = (vb[0] - va[0], vb[1] - va[1], vb[2] - va[2])
        wx, wy, wz = (vc[0] - va[0], vc[1] - va[1], vc[2] - va[2])
        nx = uy * wz - uz * wy
        ny = uz * wx - ux * wz
        nz = ux * wy - uy * wx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        nx, ny, nz = nx / length, ny / length, nz / length
        out += struct.pack(
            "<12fH",
            nx, ny, nz,
            va[0], va[1], va[2],
            vb[0], vb[1], vb[2],
            vc[0], vc[1], vc[2],
            0,
        )
    Path(path).write_bytes(bytes(out))
