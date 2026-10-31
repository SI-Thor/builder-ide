"""Reading the compiled stage back — the other half of the round-trip.

The compile is only half the contract: what comes out has to come back in.
This module opens the composed stage and reads the record back out of it —
the provenance dictionary, the pinned asset files, the semantics, the physics
— so a test can assert that what went in is what comes out.

It also compares two emission directories file by file, which is how the
determinism check is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pxr import Sdf, Usd

from builder_usd.canonical import hash_bytes
from builder_usd.provenance import ASSET_KEY, PROVENANCE_KEY, from_usd_value

__all__ = [
    "open_stage",
    "read_custom_data",
    "read_provenance",
    "read_assets",
    "read_semantics",
    "read_physics",
    "describe_stage",
    "compare_emissions",
    "EmissionDifference",
]


def open_stage(root: Path | str) -> Usd.Stage:
    """Open the composed stage at its root layer."""
    return Usd.Stage.Open(str(root))


def read_custom_data(prim) -> dict[str, Any]:
    """The prim's ``customData``, as plain Python."""
    data = prim.GetCustomData()
    if not data:
        return {}
    return {str(key): from_usd_value(value) for key, value in data.items()}


def read_provenance(stage: Usd.Stage) -> dict[str, dict[str, Any]]:
    """The provenance of every prim that carries one, keyed by prim path."""
    found: dict[str, dict[str, Any]] = {}
    for prim in stage.Traverse():
        data = read_custom_data(prim)
        if PROVENANCE_KEY in data:
            found[str(prim.GetPath())] = data[PROVENANCE_KEY]
    return found


def read_assets(stage: Usd.Stage) -> dict[str, dict[str, Any]]:
    """The pinned asset files of every prim that carries them."""
    found: dict[str, dict[str, Any]] = {}
    for prim in stage.Traverse():
        data = read_custom_data(prim)
        if ASSET_KEY in data:
            found[str(prim.GetPath())] = data[ASSET_KEY]
    return found


def read_semantics(stage: Usd.Stage) -> dict[str, dict[str, Any]]:
    """The semantic class and tags of every prim that carries them."""
    found: dict[str, dict[str, Any]] = {}
    for prim in stage.Traverse():
        entry: dict[str, Any] = {}
        kind = prim.GetAttribute("semantic:type")
        if kind and kind.HasAuthoredValue():
            entry["type"] = str(kind.Get())
        tags = prim.GetAttribute("semantic:tags")
        if tags and tags.HasAuthoredValue():
            entry["tags"] = [str(tag) for tag in tags.Get()]
        if entry:
            found[str(prim.GetPath())] = entry
    return found


def read_physics(stage: Usd.Stage) -> dict[str, dict[str, Any]]:
    """The rigid-body record of every prim that carries one."""
    found: dict[str, dict[str, Any]] = {}
    for prim in stage.Traverse():
        entry: dict[str, Any] = {}
        mass = prim.GetAttribute("physics:mass")
        if mass and mass.HasAuthoredValue():
            entry["mass"] = float(mass.Get())
        collision = prim.GetAttribute("physics:approximateCollision")
        if collision and collision.HasAuthoredValue():
            entry["collision"] = str(collision.Get())
        if entry:
            found[str(prim.GetPath())] = entry
    return found


def describe_stage(stage: Usd.Stage) -> str:
    """A readable tree of the composed stage — what the CLI prints."""
    lines: list[str] = []
    root = stage.GetRootLayer()
    lines.append(f"root layer: {root.identifier}")
    lines.append(f"sublayers: {list(root.subLayerPaths)}")
    lines.append(f"default prim: {stage.GetDefaultPrim().GetPath()}")
    for prim in stage.Traverse():
        custom = read_custom_data(prim)
        details = []
        if PROVENANCE_KEY in custom:
            record = custom[PROVENANCE_KEY]
            details.append(
                f"provenance(model={record.get('model')!r}, seed={record.get('seed')!r}, "
                f"licence={(record.get('licence') or {}).get('spdx')!r})"
            )
        if ASSET_KEY in custom:
            glb = (custom[ASSET_KEY] or {}).get("glb") or {}
            details.append(f"glb={glb.get('path')!r}")
        schema = prim.GetMetadata("apiSchemas")
        if schema:
            details.append(f"apiSchemas={list(schema.GetAddedOrExplicitItems())}")
        suffix = ("  # " + "; ".join(details)) if details else ""
        lines.append(f"  {prim.GetPath()} [{prim.GetTypeName()}]{suffix}")
    return "\n".join(lines)


@dataclass(frozen=True)
class EmissionDifference:
    """One file that differs between two emissions."""

    path: str
    left: str | None
    right: str | None

    def __str__(self) -> str:
        if self.left is None:
            return f"{self.path}: only in the second emission"
        if self.right is None:
            return f"{self.path}: only in the first emission"
        return f"{self.path}: {self.left[:12]} != {self.right[:12]}"


def _hash_tree(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hash_bytes(path.read_bytes())
    return hashes


def compare_emissions(left: Path, right: Path) -> list[EmissionDifference]:
    """Compare two emission directories file by file, by content hash."""
    left_hashes = _hash_tree(Path(left))
    right_hashes = _hash_tree(Path(right))
    differences: list[EmissionDifference] = []
    for path in sorted(set(left_hashes) | set(right_hashes)):
        first = left_hashes.get(path)
        second = right_hashes.get(path)
        if first != second:
            differences.append(EmissionDifference(path=path, left=first, right=second))
    return differences
