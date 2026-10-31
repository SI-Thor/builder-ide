"""The dirty set — core-spec v2 §1.1.

Entries are independent by construction, so applying an edit must
re-evaluate **only** the dirty set: the touched entries, plus

1. entries whose constraints reference nodes inside touched entries (the
   project-level constraints are exactly the cross-entry couplers: the oak's
   drip line crosses terrain and props);
2. entries consuming assets produced by touched entries;
3. downstream compile stages whose declared dependency keys include a
   touched entry's stage key.

Untouched stages must be byte-identical on re-evaluation — that is what a
stage-cache **hit** means, and what makes the Workshop clock physical rather
than aspirational.

How a constraint couples two entries
------------------------------------
The spec names the coupling but not the key that carries it, so this module
uses the constraint's **name**: an entry that carries a constraint named
``oak_dripline`` is coupled to the entry that constraint's referent lives in.
A project-level constraint therefore couples the entries that carry a
constraint of the same name — the oak's drip line crosses terrain and props
because both sides name it. The engine can override the rule with the
``constraint_coupler`` seam when it knows better.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from core.recipe.edits import diff_recipes, touched_entries
from core.recipe.models import Constraint, Recipe
from core.recipe.noderegistry import NodeRegistry
from core.recipe.stagecache import entry_stage_key

__all__ = [
    "DirtySet",
    "AssetProducers",
    "StaticAssetProducers",
    "compute_dirty_set",
]


class AssetProducers(Protocol):
    """Which entry produced which asset (the asset library's knowledge)."""

    def producer_of(self, asset_id: str) -> str | None: ...


class StaticAssetProducers:
    """A mapping-backed producer table (the slice's stand-in)."""

    def __init__(self, producers: Mapping[str, str] | None = None) -> None:
        self._producers = dict(producers or {})

    def producer_of(self, asset_id: str) -> str | None:
        return self._producers.get(asset_id)


@dataclass
class DirtySet:
    """What must be re-evaluated, and why."""

    entries: set[str] = field(default_factory=set)
    constraints: dict[str, list[str]] = field(default_factory=dict)
    assets: dict[str, list[str]] = field(default_factory=dict)
    stages: dict[str, list[str]] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": sorted(self.entries),
            "constraints": {k: sorted(v) for k, v in sorted(self.constraints.items())},
            "assets": {k: sorted(v) for k, v in sorted(self.assets.items())},
            "stages": {k: sorted(v) for k, v in sorted(self.stages.items())},
            "reasons": {k: sorted(v) for k, v in sorted(self.reasons.items())},
        }


def _resolve_referent(
    recipe: Recipe, constraint: Constraint, registry: NodeRegistry | None
) -> str | None:
    if constraint.ref is None:
        return None
    if constraint.ref in recipe.entries:
        return constraint.ref
    if registry is not None:
        node = registry.resolve_node(constraint.ref)
        if node is not None and node.entry_path in recipe.entries:
            return node.entry_path
    return None


def compute_dirty_set(
    base: Recipe,
    head: Recipe,
    *,
    registry: NodeRegistry | None = None,
    asset_producers: AssetProducers | None = None,
    stages: Mapping[str, Sequence[str]] | None = None,
    constraint_coupler: Callable[[Recipe, Constraint, set[str]], list[str]] | None = None,
) -> DirtySet:
    """The dirty set between two recipe documents."""
    dirty = DirtySet()

    ops = diff_recipes(base, head)
    touched = touched_entries(base, ops)
    for path in touched:
        dirty.entries.add(path)
        dirty.reasons.setdefault(path, []).append("touched")

    # 3. downstream compile stages whose dep-keys include a touched entry's stage key
    dirty_stage_keys: set[str] = set()
    for path in sorted(touched):
        entry = head.entries.get(path) or base.entries.get(path)
        if entry is None:
            continue
        dirty_stage_keys.add(
            entry_stage_key(path, entry, head.engine_pin, seeds=head.seeds)
        )
    for stage, dep_keys in (stages or {}).items():
        hits = sorted(key for key in dep_keys if key in dirty_stage_keys)
        if hits:
            dirty.stages[stage] = hits

    # 1. entries whose constraints reference nodes inside touched entries
    named_owners: dict[str, list[str]] = {}
    for path, entry in head.entries.items():
        for constraint in entry.constraints:
            named_owners.setdefault(constraint.name, []).append(path)

    def _mark(entry_path: str, reason: str) -> None:
        if entry_path not in dirty.entries:
            dirty.entries.add(entry_path)
        dirty.reasons.setdefault(entry_path, []).append(reason)

    for constraint in head.constraints:
        referent = _resolve_referent(head, constraint, registry)
        if referent is None or referent not in touched:
            continue
        coupled = (
            constraint_coupler(head, constraint, touched)
            if constraint_coupler is not None
            else named_owners.get(constraint.name, [])
        )
        for path in coupled:
            _mark(path, f"constraint:{constraint.name}")
            dirty.constraints.setdefault(path, []).append(constraint.name)

    for path, entry in head.entries.items():
        for constraint in entry.constraints:
            referent = _resolve_referent(head, constraint, registry)
            if referent is None or referent not in touched:
                continue
            if path in dirty.entries and "touched" in dirty.reasons.get(path, []):
                continue
            _mark(path, f"constraint:{constraint.name}")
            dirty.constraints.setdefault(path, []).append(constraint.name)

    # 2. entries consuming assets produced by touched entries
    if asset_producers is not None:
        for path, entry in head.entries.items():
            for asset in entry.assets:
                producer = asset_producers.producer_of(asset)
                if producer is None or producer not in touched:
                    continue
                _mark(path, f"asset:{asset}")
                dirty.assets.setdefault(path, []).append(asset)

    return dirty
