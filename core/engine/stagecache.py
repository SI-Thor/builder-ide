"""The stage cache, on disk — a hit skips the stage, eviction is by size.

The keys are §1.9's (computed by :mod:`core.recipe.stagecache` — the one
home for that arithmetic; this module never invents a key). The value is a
stage's bytes plus what the dirty-set contract needs to trust and reuse
them (``DIRTY.md`` §2, §4, §5):

* **a hit is byte-identical to re-evaluation** — every entry carries its
  artifact hash and is verified on read; a mismatch is an integrity error
  (rebuild, never serve) and a re-put of *different* bytes under a live
  key is refused outright, because that would mean an engine broke the
  same-request-same-bytes rule (contract rule 3);
* **entries never invalidate, they only get evicted** — the key is a
  function of the recipe version alone (RV patch 13), so eviction is the
  only removal there is: after each write the cache enforces a byte
  budget, least-recently-used first, the just-written entry excepted;
* **the counters are the nightly measure** — hits, misses, evictions and
  the derived hit rate (P §6-2: "hit rate per night reported"), reset per
  session by the caller who wants a clean denominator.

Single-process by design (the core service owns one); the store is a
derived cache in §5.2's sense — delete it and the engine re-generates.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from core.canon import bytes_hash
from core.recipe.errors import IntegrityError

__all__ = ["CachedStage", "StageCache", "DEFAULT_MAX_CACHE_BYTES"]

#: 2 GiB — a room's traced stage is ~5 MB and a night's edits touch tens
#: of stages; this holds a project's working set with room to spare and
#: stays a rounding error against the Thor's NVMe.
DEFAULT_MAX_CACHE_BYTES = 2 * 1024 * 1024 * 1024

CacheVerdict = Literal["hit", "miss", "partial"]


class CachedStage(BaseModel):
    """One cache entry, as a hit hands it back."""

    key: str
    data: bytes
    artifact: dict[str, Any]
    mechanism: str = ""
    #: the engine-reported (version-keyed) request key that produced these
    #: bytes — provenance, not the address (``DIRTY.md`` §2).
    request_key: str | None = None
    #: when the entry was written, for humans (wall clock, RFC 3339-ish ms)
    created_at: str = ""
    #: the cache's own monotonic access clock — LRU order. A sequence, not
    #: wall time, so two accesses inside one millisecond still order.
    last_used: int = 0

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _now_ms() -> int:
    return int(time.time() * 1000)


class StageCache:
    """Content-keyed stage bytes under ``stages/<k2>/<key>/``."""

    def __init__(self, root: Path | str, *, max_bytes: int = DEFAULT_MAX_CACHE_BYTES) -> None:
        self.root = Path(root)
        self.stages = self.root / "stages"
        self.stages.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        # key -> {"dir": Path, "bytes": int, "last_used": int,
        #         "created": int} — the in-memory view, scanned once
        self._entries: dict[str, dict] = {}
        self._total_bytes = 0
        self._clock = 0  # the LRU clock: bumped on every touch
        self._scan()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # -- reads ---------------------------------------------------------------

    def get(self, key: str) -> CachedStage | None:
        """A verified hit, or None (a counted miss). The bytes' artifact
        hash is checked on every read — a hit that cannot prove it is the
        stage it claims to be is an error, not a serve."""
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        stage = self._read(entry, key)
        entry["last_used"] = self._tick()
        self._write_meta(key, entry)
        self._hits += 1
        return stage

    def peek(self, key: str) -> CachedStage | None:
        """Read without counting: the honest check beside a verdict."""
        entry = self._entries.get(key)
        return self._read(entry, key) if entry is not None else None

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def total_bytes(self) -> int:
        return self._total_bytes

    # -- writes --------------------------------------------------------------

    def put(
        self,
        key: str,
        data: bytes,
        *,
        artifact: dict[str, Any] | None = None,
        mechanism: str = "",
        request_key: str | None = None,
    ) -> None:
        """Store a stage's bytes under a key. Write-once in spirit: the
        same key must mean the same bytes forever, so re-putting different
        bytes under a live, hash-verified entry is refused (contract rule
        3 broke); re-putting over a corrupt entry heals it."""
        artifact = artifact or {"sha256": bytes_hash(data), "kind": "stage",
                                "bytes": len(data)}
        entry_dir = self._dir_for(key)
        stage_path = entry_dir / "stage.bin"
        if key in self._entries:
            existing = self._entries[key]
            try:
                current = stage_path.read_bytes()
            except FileNotFoundError:
                current = None  # corrupt: the meta points at nothing
            if current is not None and current != data:
                recorded = bytes_hash(current)
                if recorded == existing.get("artifact_sha"):
                    raise IntegrityError(
                        f"stage {key} is already cached as {recorded} and the "
                        f"engine now offers {bytes_hash(data)}; the same key "
                        "must mean the same bytes (contract rule 3) — this is "
                        "an engine determinism break, not a cache problem"
                    )
                # corrupt entry (bytes no longer match their own record):
                # heal by overwrite

        entry_dir.mkdir(parents=True, exist_ok=True)
        tmp = entry_dir / "stage.bin.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, stage_path)
        previous = self._entries.get(key, {})
        added = len(data) - previous.get("bytes", 0)
        self._entries[key] = {
            "dir": entry_dir,
            "bytes": len(data),
            "last_used": self._tick(),
            "created": previous.get("created", self._clock),
            "created_at": previous.get("created_at", f"{_now_ms()}"),
            "artifact_sha": artifact.get("sha256", bytes_hash(data)),
            "artifact": artifact,
            "mechanism": mechanism,
            "request_key": request_key,
        }
        self._total_bytes += max(added, 0)
        self._write_meta(key, self._entries[key])
        self._evict(protect=key)

    # -- the measure ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        asked = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / asked, 4) if asked else None,
            "evictions": self._evictions,
            "entries": len(self._entries),
            "bytes": self._total_bytes,
            "max_bytes": self.max_bytes,
        }

    def reset_stats(self) -> None:
        """A clean denominator for a session's hit rate."""
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # -- internals -----------------------------------------------------------

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    def _dir_for(self, key: str) -> Path:
        digest = key.split(":", 1)[-1]
        return self.stages / digest[:2] / digest

    def _scan(self) -> None:
        self._total_bytes = 0
        if not self.stages.is_dir():
            return
        for meta_path in sorted(self.stages.rglob("meta.json")):
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # a torn entry is not a cache member
            key = meta.get("key")
            size = meta.get("bytes")
            if not isinstance(key, str) or not isinstance(size, int):
                continue
            self._entries[key] = {
                "dir": meta_path.parent,
                "bytes": size,
                "last_used": int(meta.get("last_used", 0)),
                "created": int(meta.get("created", 0)),
                "created_at": str(meta.get("created_at", "")),
                "artifact_sha": meta.get("artifact_sha"),
                "artifact": meta.get("artifact", {}),
                "mechanism": meta.get("mechanism", ""),
                "request_key": meta.get("request_key"),
            }
            self._total_bytes += size
            self._clock = max(self._clock, int(meta.get("last_used", 0)))

    def _read(self, entry: dict, key: str) -> CachedStage:
        stage_path = entry["dir"] / "stage.bin"
        try:
            data = stage_path.read_bytes()
        except FileNotFoundError as e:
            raise IntegrityError(
                f"stage {key} is in the cache index but its bytes are gone "
                f"({stage_path}); rebuild the stage"
            ) from e
        sha = bytes_hash(data)
        if entry.get("artifact_sha") not in (None, sha):
            raise IntegrityError(
                f"stage {key} does not match its recorded hash ({sha} vs "
                f"{entry['artifact_sha']}); a hit must be byte-identical to "
                "re-evaluation — rebuild, never serve"
            )
        return CachedStage(
            key=key,
            data=data,
            artifact=entry.get("artifact") or {"sha256": sha, "kind": "stage",
                                               "bytes": len(data)},
            mechanism=entry.get("mechanism", ""),
            request_key=entry.get("request_key"),
            created_at=entry.get("created_at", ""),
            last_used=entry.get("last_used", 0),
        )

    def _write_meta(self, key: str, entry: dict) -> None:
        meta = {k: v for k, v in entry.items() if k != "dir"}
        meta["key"] = key
        tmp = entry["dir"] / "meta.json.tmp"
        entry["dir"].mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        os.replace(tmp, entry["dir"] / "meta.json")

    def _evict(self, *, protect: str) -> None:
        """Enforce the byte budget, least-recently-used first. The entry
        just written is never the one evicted (``DIRTY.md`` §5)."""
        while self._total_bytes > self.max_bytes and len(self._entries) > 1:
            victim = min(
                (key for key in self._entries if key != protect),
                key=lambda k: (self._entries[k]["last_used"], k),
                default=None,
            )
            if victim is None:
                break
            entry = self._entries.pop(victim)
            shutil.rmtree(entry["dir"], ignore_errors=True)
            self._total_bytes -= entry["bytes"]
            self._evictions += 1
