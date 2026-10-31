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
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["Glb", "GlbError", "Mesh", "read_glb"]

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
        """
        meshes = self.gltf.get("meshes") or []
        if not meshes:
            raise GlbError(f"{self.path}: the GLB carries no mesh")
        primitives = meshes[0].get("primitives") or []
        if not primitives:
            raise GlbError(f"{self.path}: the mesh carries no primitive")
        primitive = primitives[0]
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
        return Mesh(positions=positions, indices=indices)

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
