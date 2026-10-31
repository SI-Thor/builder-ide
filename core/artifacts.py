"""Content-addressed artifact store (§1.0): write-once, tmp+rename, verified
by hash on read. Blobs live on disk under artifacts/<key2>/<key>/…; the DB
stays small and references them by hash."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .canon import bytes_hash
from .errors import IntegrityFailure

_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sha: str) -> Path:
        hexpart = sha.removeprefix("sha256:")
        return self.root / hexpart[:2] / hexpart

    def put(self, data: bytes, kind: str) -> dict:
        """Write once; an identical blob is a no-op (content-addressed).
        Returns the event artifact descriptor {sha256, kind, bytes}."""
        sha = bytes_hash(data)
        if not _SHA_RE.match(sha):
            raise IntegrityFailure("bad hash form")
        path = self._path_for(sha)
        if path.exists():
            return {"sha256": sha, "kind": kind, "bytes": len(data)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)  # atomic: readers never see a partial blob
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return {"sha256": sha, "kind": kind, "bytes": len(data)}

    def has(self, sha: str) -> bool:
        return self._path_for(sha).exists()

    def get(self, sha: str) -> bytes:
        path = self._path_for(sha)
        if not path.exists():
            raise IntegrityFailure(f"artifact missing: {sha}")
        data = path.read_bytes()
        if bytes_hash(data) != sha:
            raise IntegrityFailure(f"artifact hash mismatch: {sha}")
        return data

    def verify(self, sha: str) -> bool:
        """True if present and hash-clean; a broken reference fails loud at
        boot (§5.2 step 2)."""
        try:
            self.get(sha)
            return True
        except IntegrityFailure:
            return False
