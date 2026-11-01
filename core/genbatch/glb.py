"""Read a GLB: the container, and the mesh primitive inside it.

There is no glTF library on the Thor and the Thor does not need one. A GLB
is a twelve-byte header, a JSON chunk and a binary chunk; the mesh is a
POSITION accessor and an index accessor, both views into the binary chunk.
That is the whole of what the critic needs, so that is the whole of what
this reads.

The reader is strict on purpose. A prop that comes back as a malformed GLB
is a failed prop, and the morning has to be able to say so — so a file that
is not a GLB, or a GLB with no readable mesh, raises :class:`GlbError`
rather than returning something empty and plausible.

**One file is not one object.** TRELLIS.2 writes a single mesh, so the
first primitive is the whole prop — but a real asset is made of parts: the
SimReady forklift is **32** of them, and its first primitive is 0.2 % of
its geometry. Measuring the first primitive alone measures a fragment, and
the fragment's bounding box is not the object's. :attr:`Glb.asset` reads
the whole thing — every primitive the scene graph puts on the stage,
merged into one mesh — and that is what a measurement of *the object* has
to use.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["Glb", "GlbError", "Mesh", "read_glb", "parse_glb"]

_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942

#: glTF component types, mapped to numpy dtypes.
_COMPONENT_TYPES: dict[int, Any] = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}

#: glTF accessor types, mapped to the number of components each one holds.
_TYPE_COMPONENTS: dict[str, int] = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class GlbError(ValueError):
    """A GLB we cannot read, or cannot find a mesh in."""


def _node_matrix(node: dict) -> np.ndarray:
    """A node's local transform, as a 4×4 matrix.

    glTF stores a node's transform either as a column-major ``matrix`` or as
    the translation/rotation/scale triple; both are read here, and a node
    with none of them is the identity.
    """
    if "matrix" in node:
        # Column-major: the sixteen numbers are the columns.
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T

    matrix = np.eye(4, dtype=np.float64)
    translation = node.get("translation")
    if translation:
        matrix[:3, 3] = np.asarray(translation, dtype=np.float64)
    rotation = node.get("rotation")
    if rotation:
        x, y, z, w = (float(value) for value in rotation)
        matrix[:3, :3] = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ],
            dtype=np.float64,
        )
    scale = node.get("scale")
    if scale:
        matrix[:3, :3] = matrix[:3, :3] * np.asarray(scale, dtype=np.float64)
    return matrix


def _apply_matrix(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Place a set of points by a 4×4 matrix."""
    if matrix is None:
        return points
    points = np.asarray(points, dtype=np.float64)
    homogeneous = np.concatenate(
        [points, np.ones((points.shape[0], 1), dtype=np.float64)], axis=1
    )
    return (homogeneous @ matrix.T)[:, :3]


@dataclass(frozen=True)
class Mesh:
    """One mesh primitive: its vertices and its triangles.

    ``positions`` is ``(vertices, 3)`` float64 and ``indices`` is
    ``(triangles, 3)`` int64 — the two shapes the measurement code wants.
    """

    positions: np.ndarray
    indices: np.ndarray

    @property
    def vertices(self) -> int:
        return int(self.positions.shape[0])

    @property
    def triangles(self) -> int:
        return int(self.indices.shape[0])


@dataclass(frozen=True)
class Glb:
    """A parsed GLB: the glTF JSON and the binary chunk beside it."""

    path: Path
    gltf: dict
    binary: bytes

    @property
    def generator(self) -> str:
        """Whatever wrote the file, as the glTF asset block says."""
        return str(self.gltf.get("asset", {}).get("generator", ""))

    @property
    def mesh(self) -> Mesh:
        """The first mesh primitive in the file.

        TRELLIS.2 writes one mesh, and this is the one the critic measures.
        For a file with several parts this is one part, not the object —
        :attr:`asset` is the object.
        """
        meshes = self.gltf.get("meshes") or []
        if not meshes:
            raise GlbError(f"{self.path}: the GLB carries no mesh")
        primitives = meshes[0].get("primitives") or []
        if not primitives:
            raise GlbError(f"{self.path}: the mesh carries no primitive")
        primitive = primitives[0]
        positions, indices = self._read_primitive(primitive)
        matrix = self._matrix_of_mesh(0)
        if matrix is not None:
            positions = _apply_matrix(positions, matrix)
        return Mesh(positions=positions, indices=indices)

    @property
    def asset(self) -> Mesh:
        """The whole object: every primitive the scene graph puts on the stage.

        Each primitive is placed by its node's **world transform**, so the
        parts of a multi-part asset land where the file says they belong,
        and the result is one mesh whose bounding box is the object's.

        A file whose scene graph places no mesh falls back to every mesh in
        the file, untransformed — the degenerate case of a GLB with no scene
        at all.
        """
        meshes = self.gltf.get("meshes") or []
        if not meshes:
            raise GlbError(f"{self.path}: the GLB carries no mesh")

        placements = self._placements()
        if not placements:
            placements = [
                (index, np.eye(4, dtype=np.float64))
                for index in range(len(meshes))
            ]

        positions: list[np.ndarray] = []
        indices: list[np.ndarray] = []
        offset = 0
        for mesh_index, matrix in placements:
            primitives = meshes[mesh_index].get("primitives") or []
            for primitive in primitives:
                if int(primitive.get("mode", 4)) != 4:
                    # Not triangles: a mode the critic has no measurement for.
                    continue
                try:
                    chunk_positions, chunk_indices = self._read_primitive(primitive)
                except GlbError:
                    continue
                positions.append(_apply_matrix(chunk_positions, matrix))
                indices.append(chunk_indices + offset)
                offset += int(chunk_positions.shape[0])

        if not positions:
            raise GlbError(f"{self.path}: the GLB carries no triangle primitive")
        return Mesh(
            positions=np.concatenate(positions, axis=0),
            indices=np.concatenate(indices, axis=0),
        )

    # -- the scene graph ----------------------------------------------------

    def _placements(self) -> list[tuple[int, np.ndarray]]:
        """The meshes the scene puts on the stage, and where each one goes.

        Every node with a mesh contributes its mesh at its own world
        transform, so a mesh instanced twice is measured twice — once per
        place it stands.
        """
        nodes = self.gltf.get("nodes") or []
        if not nodes:
            return []
        world = self._world_matrices()
        placements: list[tuple[int, np.ndarray]] = []
        for index, node in enumerate(nodes):
            if "mesh" not in node:
                continue
            mesh_index = int(node["mesh"])
            matrix = world.get(index)
            if matrix is None:
                continue
            placements.append((mesh_index, matrix))
        return placements

    def _world_matrices(self) -> dict[int, np.ndarray]:
        """Each node's world transform, from the scene graph's roots down."""
        nodes = self.gltf.get("nodes") or []
        world: dict[int, np.ndarray] = {}
        visited: set[int] = set()
        identity = np.eye(4, dtype=np.float64)

        def walk(index: int, parent: np.ndarray) -> None:
            if index in visited or not 0 <= index < len(nodes):
                return
            visited.add(index)
            node = nodes[index]
            current = parent @ _node_matrix(node)
            world[index] = current
            for child in node.get("children") or []:
                walk(int(child), current)

        for root in self._roots():
            walk(int(root), identity)
        return world

    def _roots(self) -> list[int]:
        """The scene's root nodes."""
        nodes = self.gltf.get("nodes") or []
        scenes = self.gltf.get("scenes") or []
        scene_index = int(self.gltf.get("scene", 0))
        if scenes and 0 <= scene_index < len(scenes):
            return [int(node) for node in (scenes[scene_index].get("nodes") or [])]
        children = {
            int(child)
            for node in nodes
            for child in (node.get("children") or [])
        }
        return [index for index in range(len(nodes)) if index not in children]

    def _matrix_of_mesh(self, mesh_index: int) -> np.ndarray | None:
        """The world transform of the first node that places a given mesh."""
        for node_index, (placed, matrix) in enumerate(self._placements()):
            if placed == mesh_index:
                return matrix
        return None

    def _read_primitive(self, primitive: dict) -> tuple[np.ndarray, np.ndarray]:
        """One primitive's positions and indices."""
        attributes = primitive.get("attributes") or {}
        if "POSITION" not in attributes:
            raise GlbError(f"{self.path}: the primitive has no POSITION attribute")

        positions = self._read_accessor(attributes["POSITION"], "VEC3")
        if positions.shape[0] == 0:
            raise GlbError(f"{self.path}: the mesh has no vertices")
        if "indices" in primitive:
            flat = self._read_accessor(primitive["indices"], "SCALAR")
        else:
            flat = np.arange(positions.shape[0], dtype=np.uint32)
        if flat.size % 3 != 0:
            raise GlbError(
                f"{self.path}: the index buffer holds {flat.size} entries, "
                "which is not a whole number of triangles"
            )
        indices = flat.reshape(-1, 3).astype(np.int64)
        if indices.size and indices.max() >= positions.shape[0]:
            raise GlbError(f"{self.path}: an index points past the last vertex")
        return positions, indices

    def _read_accessor(self, index: int, expected_type: str) -> np.ndarray:
        accessors = self.gltf.get("accessors") or []
        if index >= len(accessors):
            raise GlbError(f"{self.path}: accessor {index} does not exist")
        accessor = accessors[index]
        accessor_type = accessor.get("type", "SCALAR")
        if accessor_type != expected_type:
            raise GlbError(
                f"{self.path}: accessor {index} is a {accessor_type}, "
                f"but a {expected_type} was needed"
            )
        component_type = accessor.get("componentType")
        dtype = _COMPONENT_TYPES.get(component_type)
        if dtype is None:
            raise GlbError(
                f"{self.path}: accessor {index} has an unknown component type "
                f"{component_type!r}"
            )
        components = _TYPE_COMPONENTS.get(accessor_type, 1)
        count = int(accessor.get("count", 0))

        view_index = accessor.get("bufferView")
        if view_index is None:
            # A sparse accessor with no buffer view: no data to read.
            return np.zeros((count, components), dtype=dtype)
        views = self.gltf.get("bufferViews") or []
        if view_index >= len(views):
            raise GlbError(f"{self.path}: buffer view {view_index} does not exist")
        view = views[view_index]
        offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        length = count * components * np.dtype(dtype).itemsize
        if offset + length > len(self.binary):
            raise GlbError(f"{self.path}: accessor {index} runs past the binary chunk")
        flat = np.frombuffer(self.binary, dtype=dtype, count=count * components, offset=offset)
        return flat.reshape(count, components).astype(np.float64)


def read_glb(path: str | Path) -> Glb:
    """Read a GLB from disk."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GlbError(f"{path}: cannot be read ({exc})") from exc
    return parse_glb(data, path=path)


def parse_glb(data: bytes, *, path: str | Path = "<bytes>") -> Glb:
    """Parse the bytes of a GLB."""
    path = Path(path)
    if len(data) < 12:
        raise GlbError(f"{path}: too short to be a GLB")
    magic, version, length = struct.unpack("<4sII", data[:12])
    if magic != _MAGIC:
        raise GlbError(f"{path}: not a GLB (magic {magic!r})")
    if version != 2:
        raise GlbError(f"{path}: GLB version {version} is not the version 2 we read")
    if length > len(data):
        raise GlbError(f"{path}: the header claims {length} bytes, the file has {len(data)}")

    gltf: dict | None = None
    binary = b""
    offset = 12
    while offset + 8 <= length:
        chunk_len, chunk_type = struct.unpack("<II", data[offset : offset + 8])
        start = offset + 8
        end = start + chunk_len
        if end > length:
            raise GlbError(f"{path}: a chunk runs past the end of the file")
        body = data[start:end]
        if chunk_type == _JSON_CHUNK:
            try:
                # The JSON chunk is padded with spaces to a four-byte boundary,
                # and the padding is not part of the JSON.
                gltf = json.loads(body.decode("utf-8").strip())
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GlbError(f"{path}: the JSON chunk is not JSON ({exc})") from exc
        elif chunk_type == _BIN_CHUNK:
            binary = body
        offset = end + ((4 - chunk_len % 4) % 4 if chunk_len % 4 else 0)

    if gltf is None:
        raise GlbError(f"{path}: the GLB has no JSON chunk")
    return Glb(path=path, gltf=gltf, binary=binary)
