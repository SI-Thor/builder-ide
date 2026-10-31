"""Provenance — the record that says where a thing came from.

core-spec v2 §1.6: every generated or imported asset enters the library with
provenance and a licence, and **the scheduler stamps provenance, not the job**
(res-cad §9). This module is the shape of that stamp and its translation into
and out of USD ``customData``.

The five fields the spike must round-trip are the ones the brief names —
**prompt, model, seed, version, licence** — and they sit inside the
``provenance`` dictionary of the prim's ``customData``, next to the
``asset`` dictionary that pins the files by path and sha256.

Two rules the USD side forces on us — both measured on this box, not assumed:

* ``customData`` **merges** across layers and across composition arcs; the
  stronger opinion wins *per key*, and the whole dictionary is not replaced.
  (A typed prim also picks up a ``userDocBrief`` key from its schema, which
  is USD's doing and not ours.) So every layer must own a **distinct key**
  inside ``customData``, and no two layers may own the same key — otherwise
  the merge quietly decides what the record says.
* USD's dictionary writer accepts nested dictionaries, but a plain Python
  list is refused: an array must be a typed ``Vt`` array. :func:`to_usd_value`
  does that conversion, and :func:`from_usd_value` undoes it, so a
  round-trip returns exactly the value that went in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pxr import Vt

__all__ = [
    "Licence",
    "Provenance",
    "AssetFile",
    "AssetRecord",
    "to_usd_value",
    "from_usd_value",
    "PROVENANCE_KEY",
    "ASSET_KEY",
    "PART_KEY",
]

#: The ``customData`` key that holds the provenance dictionary.
PROVENANCE_KEY = "provenance"

#: The ``customData`` key that holds the pinned asset files, keyed by role.
ASSET_KEY = "asset"

#: The ``customData`` key that holds a part's own record, on the part's layer.
PART_KEY = "part"


def to_usd_value(value: Any) -> Any:
    """Convert a plain Python value into something USD will accept.

    Dictionaries stay dictionaries (USD writes them nested), lists become
    typed ``Vt`` arrays (a bare list is refused by the dictionary writer), and
    ``None`` disappears — USD has no null.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            item = to_usd_value(item)
            if item is None:
                continue
            converted[str(key)] = item
        return converted
    if isinstance(value, (list, tuple)):
        items = [to_usd_value(item) for item in value]
        if not items:
            return Vt.StringArray([])
        if all(isinstance(item, str) for item in items):
            return Vt.StringArray(items)
        if all(isinstance(item, bool) for item in items):
            return Vt.BoolArray(items)
        if all(isinstance(item, int) for item in items):
            return Vt.IntArray(items)
        if all(isinstance(item, float) for item in items):
            return Vt.DoubleArray(items)
        return Vt.ValueArray(items) if hasattr(Vt, "ValueArray") else items
    raise TypeError(f"cannot convert {type(value).__name__} into a USD value")


def from_usd_value(value: Any) -> Any:
    """Convert a value read back out of USD into plain Python."""
    if isinstance(value, Vt.StringArray):
        return [str(item) for item in value]
    if isinstance(value, Vt.TokenArray):
        return [str(item) for item in value]
    if isinstance(value, Vt.BoolArray):
        return [bool(item) for item in value]
    if isinstance(value, Vt.IntArray):
        return [int(item) for item in value]
    if isinstance(value, Vt.Int64Array):
        return [int(item) for item in value]
    if isinstance(value, Vt.DoubleArray):
        return [float(item) for item in value]
    if isinstance(value, Vt.FloatArray):
        return [float(item) for item in value]
    if isinstance(value, dict):
        return {str(key): from_usd_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [from_usd_value(item) for item in value]
    return value


@dataclass(frozen=True)
class Licence:
    """The licence of a thing, with the terms that ride with it.

    core-spec v2 §1.6: ``dependency_terms`` carries terms that come WITH the
    weights — OCCT's LGPL-with-exception for a CAD part, DINOv3's terms for a
    TRELLIS.2 prop — and ``commercial_ok`` is what the merge gate's licence
    scan reads.
    """

    spdx: str
    dependency_terms: tuple[str, ...] = ()
    commercial_ok: bool = True
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spdx": self.spdx,
            "dependency_terms": list(self.dependency_terms),
            "commercial_ok": self.commercial_ok,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Licence":
        return cls(
            spdx=str(data["spdx"]),
            dependency_terms=tuple(data.get("dependency_terms") or ()),
            commercial_ok=bool(data.get("commercial_ok", False)),
            notes=data.get("notes"),
        )


@dataclass(frozen=True)
class Provenance:
    """Where an artifact came from — the stamp the scheduler writes."""

    source: str
    prompt: str
    model: str
    seed: int | None = None
    version: str = ""
    licence: Licence = field(default_factory=lambda: Licence("UNKNOWN"))
    weights_repo: str | None = None
    weights_revision: str | None = None
    library_versions: dict[str, str] = field(default_factory=dict)
    recipe_version_hash: str | None = None
    engine_pin: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """The plain dictionary written into ``customData``."""
        return {
            "source": self.source,
            "prompt": self.prompt,
            "model": self.model,
            "seed": self.seed,
            "version": self.version,
            "licence": self.licence.to_dict(),
            "weights": {"repo": self.weights_repo, "revision": self.weights_revision},
            "library_versions": dict(self.library_versions),
            "recipe_version_hash": self.recipe_version_hash,
            "engine_pin": dict(self.engine_pin) if self.engine_pin else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        weights = data.get("weights") or {}
        return cls(
            source=str(data.get("source", "unknown")),
            prompt=str(data.get("prompt", "")),
            model=str(data.get("model", "")),
            seed=None if data.get("seed") is None else int(data["seed"]),
            version=str(data.get("version", "")),
            licence=Licence.from_dict(data.get("licence") or {"spdx": "UNKNOWN"}),
            weights_repo=weights.get("repo"),
            weights_revision=weights.get("revision"),
            library_versions=dict(data.get("library_versions") or {}),
            recipe_version_hash=data.get("recipe_version_hash"),
            engine_pin=dict(data["engine_pin"]) if data.get("engine_pin") else None,
        )


@dataclass(frozen=True)
class AssetFile:
    """One file of an asset, pinned by path and content hash."""

    role: str
    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "path": self.path, "sha256": self.sha256, "bytes": self.bytes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetFile":
        return cls(
            role=str(data["role"]),
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            bytes=int(data["bytes"]),
        )


@dataclass(frozen=True)
class AssetRecord:
    """The files an asset is made of: the master (STEP) and the interchange (GLB)."""

    files: tuple[AssetFile, ...] = ()

    def by_role(self, role: str) -> AssetFile | None:
        for item in self.files:
            if item.role == role:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {item.role: item.to_dict() for item in self.files}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetRecord":
        return cls(files=tuple(AssetFile.from_dict(item) for item in data.values()))
