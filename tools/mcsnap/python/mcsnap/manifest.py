"""The manifest — what a snapshot says about itself.

A snapshot of a live world is a directory of bytes. A manifest is what
makes it *a moment in a world*: it says which files the moment consists of,
what each of them hashed to, how big it was, what the world's own clock
read at that moment, which ledger row the moment sits behind, and which
files were left behind on purpose.

The fields, and why each is here:

``snapshot_id``
    the name of the snapshot, and the directory it lives in.
``taken_at``
    the wall clock (ISO-8601, UTC), so a human can find it.
``server``
    the Paper and Minecraft versions the world was running under. A
    snapshot taken under one version and restored under another is a
    different world; the manifest says which one it was.
``world``
    the seed, the tick (``level.dat``'s ``Time``), the time of day
    (``DayTime``), the data version and the spawn. The tick is the world's
    own clock — the thing that makes the snapshot a moment rather than a
    directory.
``ledger``
    the world ledger the snapshot sits behind: its path, and the highest
    ``seq`` it held when the snapshot was taken. This is the join between
    the world's *state* and the world's *story*: a rewind point in the
    ledger is matched to the nearest snapshot at or before it.
``files``
    every copied file: its path, its size, its sha256, its mtime, and the
    section it belongs to.
``skipped``
    every file that was left behind, and why.
``sections``
    the per-section totals, so a reader can see at a glance how much of
    the snapshot is blocks and how much is players.
``timing``
    how long each step of the snapshot took.

The manifest is JSON, written with ``indent=2`` so a human can read it and
a machine can diff it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "FileEntry",
    "Manifest",
    "sha256_file",
    "section_totals",
    "manifest_to_dict",
    "manifest_from_dict",
    "write_manifest",
    "read_manifest",
    "verify_directory",
    "MANIFEST_NAME",
]


#: The manifest's file name inside a snapshot directory.
MANIFEST_NAME = "manifest.json"


def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    """The sha256 of a file, read in chunks so a big region file is cheap."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileEntry:
    """One file in a snapshot."""

    relpath: str
    size: int
    sha256: str
    mtime: float
    section: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relpath,
            "size": self.size,
            "sha256": self.sha256,
            "mtime": self.mtime,
            "section": self.section,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            relpath=str(data["path"]),
            size=int(data.get("size", 0)),
            sha256=str(data.get("sha256", "")),
            mtime=float(data.get("mtime", 0.0)),
            section=str(data.get("section", "unclassified")),
        )


@dataclass(frozen=True)
class Manifest:
    """What a snapshot says about itself."""

    snapshot_id: str
    taken_at: str
    world_dir: str
    server: dict[str, Any] = field(default_factory=dict)
    world: dict[str, Any] = field(default_factory=dict)
    ledger: dict[str, Any] = field(default_factory=dict)
    files: tuple[FileEntry, ...] = ()
    skipped: tuple[dict[str, str], ...] = ()
    totals: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)

    @property
    def ledger_seq(self) -> int | None:
        """The ledger row this snapshot sits behind, if it has one."""
        value = self.ledger.get("seq")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def total_bytes(self) -> int:
        return int(self.totals.get("bytes", 0))


def section_totals(files: Iterable[FileEntry]) -> dict[str, dict[str, int]]:
    """How many files and how many bytes each section holds."""
    totals: dict[str, dict[str, int]] = {}
    for entry in files:
        bucket = totals.setdefault(entry.section, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += entry.size
    return totals


def manifest_to_dict(manifest: Manifest) -> dict[str, Any]:
    """The manifest as a plain dict, ready for JSON."""
    return {
        "snapshot_id": manifest.snapshot_id,
        "taken_at": manifest.taken_at,
        "world_dir": manifest.world_dir,
        "server": manifest.server,
        "world": manifest.world,
        "ledger": manifest.ledger,
        "totals": manifest.totals,
        "sections": manifest.sections,
        "timing": manifest.timing,
        "files": [entry.to_dict() for entry in manifest.files],
        "skipped": [dict(item) for item in manifest.skipped],
    }


def manifest_from_dict(data: dict[str, Any]) -> Manifest:
    """A manifest from a plain dict — the inverse of :func:`manifest_to_dict`."""
    return Manifest(
        snapshot_id=str(data.get("snapshot_id", "")),
        taken_at=str(data.get("taken_at", "")),
        world_dir=str(data.get("world_dir", "")),
        server=dict(data.get("server", {})),
        world=dict(data.get("world", {})),
        ledger=dict(data.get("ledger", {})),
        files=tuple(FileEntry.from_dict(item) for item in data.get("files", [])),
        skipped=tuple(dict(item) for item in data.get("skipped", [])),
        totals=dict(data.get("totals", {})),
        sections=dict(data.get("sections", {})),
        timing=dict(data.get("timing", {})),
    )


def write_manifest(manifest: Manifest, path: str | Path) -> Path:
    """Write the manifest as JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return target


def read_manifest(path: str | Path) -> Manifest:
    """Read a manifest from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return manifest_from_dict(data)


def verify_directory(root: str | Path, manifest: Manifest) -> list[str]:
    """Check a directory against a manifest; return the problems.

    An empty list means every file is present, the right size, and hashes
    to what the manifest says. The check is by **content**: a file that was
    restored with the right size but the wrong bytes is the failure this
    exists to catch.
    """
    base = Path(root)
    problems: list[str] = []
    for entry in manifest.files:
        absolute = base / entry.relpath
        if not absolute.is_file():
            problems.append(f"missing: {entry.relpath}")
            continue
        actual_size = absolute.stat().st_size
        if actual_size != entry.size:
            problems.append(
                f"size differs: {entry.relpath} "
                f"(manifest {entry.size} B, on disk {actual_size} B)"
            )
            continue
        actual_hash = sha256_file(absolute)
        if actual_hash != entry.sha256:
            problems.append(
                f"hash differs: {entry.relpath} "
                f"(manifest {entry.sha256[:16]}…, on disk {actual_hash[:16]}…)"
            )
    return problems
