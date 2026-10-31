"""Three-way merge at entry granularity — core-spec v2 §1.2.

Merge into ``main`` is a fast-forward or, when ``main`` moved meanwhile, a
three-way merge at *entry* granularity: entries are independent by
construction. Two edits to the same entry conflict and park a question rather
than auto-merging — ambiguity is resolved by asking, never by guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Conflict", "three_way_merge", "merge_units"]


@dataclass(frozen=True)
class Conflict:
    """One unit both sides changed differently."""

    path: str
    base: Any
    ours: Any
    theirs: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "base": self.base,
            "ours": self.ours,
            "theirs": self.theirs,
        }


def _units(document: dict[str, Any]) -> dict[str, Any]:
    """Flatten a document into the units that are merged independently."""
    units: dict[str, Any] = {}
    for field in ("name", "schema_version"):
        units[field] = document.get(field)
    for field, value in (document.get("engine_pin") or {}).items():
        units[f"engine_pin.{field}"] = value
    for channel, value in (document.get("seeds") or {}).items():
        units[f"seeds.{channel}"] = value
    units["constraints"] = document.get("constraints") or []
    for path, entry in (document.get("entries") or {}).items():
        units[f"entries.{path}"] = entry
    return units


def merge_units(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> tuple[dict[str, Any], list[Conflict]]:
    """Merge three unit maps. Returns (merged units, conflicts)."""
    merged: dict[str, Any] = {}
    conflicts: list[Conflict] = []

    for unit in sorted(set(base) | set(ours) | set(theirs)):
        base_value = base.get(unit)
        our_value = ours.get(unit)
        their_value = theirs.get(unit)

        if our_value == their_value:
            merged[unit] = our_value
            continue
        if our_value == base_value:
            merged[unit] = their_value
            continue
        if their_value == base_value:
            merged[unit] = our_value
            continue
        conflicts.append(
            Conflict(
                unit.split(".", 1)[1] if unit.startswith("entries.") else unit,
                base_value,
                our_value,
                their_value,
            )
        )

    return merged, conflicts


def _rebuild(template: dict[str, Any], units: dict[str, Any]) -> dict[str, Any]:
    document = dict(template)
    document["name"] = units.get("name")
    document["schema_version"] = units.get("schema_version")
    document["engine_pin"] = {
        key.split(".", 1)[1]: value
        for key, value in units.items()
        if key.startswith("engine_pin.")
    }
    document["seeds"] = {
        key.split(".", 1)[1]: value
        for key, value in units.items()
        if key.startswith("seeds.")
    }
    document["constraints"] = units.get("constraints") or []
    document["entries"] = {
        key.split(".", 1)[1]: value
        for key, value in units.items()
        if key.startswith("entries.")
    }
    return document


def three_way_merge(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> tuple[dict[str, Any], list[Conflict]]:
    """Merge two documents against their common ancestor.

    ``ours`` is the receiving side (main), ``theirs`` the incoming side.
    """
    merged_units, conflicts = merge_units(_units(base), _units(ours), _units(theirs))
    return _rebuild(ours, merged_units), conflicts
