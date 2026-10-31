"""Content-addressed blobs — core-spec v2 §1.0.

Recipe version documents and artifacts are content-addressed blobs on disk,
referenced by hash from the database — so the database stays small and the
blobs are verified by hash on read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from builder_recipe.canonical import canonical_bytes, canonical_json, hash_bytes
from builder_recipe.errors import IntegrityError

__all__ = ["BlobStore", "MemoryBlobStore", "FileBlobStore"]


class BlobStore(Protocol):
    """Write-once, content-addressed storage."""

    def put_bytes(self, data: bytes) -> str:
        """Store the bytes and return their content hash (``sha256:…``)."""

    def put_json(self, value: Any) -> str:
        """Store a JSON value canonically and return its content hash."""

    def get_bytes(self, ref: str) -> bytes:
        """Read the bytes back, verifying the hash."""

    def path_for(self, ref: str) -> Path:
        """Where the blob lives (for the file-backed store)."""


class MemoryBlobStore:
    """An in-memory blob store (tests and short-lived processes)."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put_bytes(self, data: bytes) -> str:
        ref = hash_bytes(data)
        self._blobs.setdefault(ref, data)
        return ref

    def put_json(self, value: Any) -> str:
        return self.put_bytes(canonical_bytes(value))

    def get_bytes(self, ref: str) -> bytes:
        try:
            data = self._blobs[ref]
        except KeyError as exc:
            raise IntegrityError(f"blob {ref} is not in the store") from exc
        if hash_bytes(data) != ref:
            raise IntegrityError(f"blob {ref} does not match its hash")
        return data

    def path_for(self, ref: str) -> Path:
        raise NotImplementedError("the memory blob store has no paths")


class FileBlobStore:
    """Blobs under ``$BUILDER_HOME/artifacts/ab/ab1234…``, write-once.

    Writes are atomic (tmp + rename) so a half-written blob is never visible.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.artifacts = self.root / "artifacts"

    def _path(self, ref: str) -> Path:
        digest = ref.split(":", 1)[-1]
        return self.artifacts / digest[:2] / digest

    def put_bytes(self, data: bytes) -> str:
        ref = hash_bytes(data)
        path = self._path(ref)
        if path.exists():
            return ref
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return ref

    def put_json(self, value: Any) -> str:
        return self.put_bytes(canonical_bytes(value))

    def get_bytes(self, ref: str) -> bytes:
        path = self._path(ref)
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise IntegrityError(f"blob {ref} is missing from {path}") from exc
        if hash_bytes(data) != ref:
            raise IntegrityError(f"blob {ref} does not match its hash")
        return data

    def path_for(self, ref: str) -> Path:
        return self._path(ref)

    def write_mirror(self, name: str, value: Any) -> Path:
        """A human-readable mirror of a blob (``recipes/ver_0192.json``)."""
        mirror = self.root / "recipes" / name
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(canonical_json(value), encoding="utf-8")
        return mirror

    def read_json(self, ref: str) -> Any:
        return json.loads(self.get_bytes(ref).decode("utf-8"))
