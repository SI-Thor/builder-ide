"""The node registry (core-spec v2 §1.4.0).

World node ids and recipe entry paths are different keys for the same things.
The registry is the map between them — the chain view → referent → entry →
params → acceptance is broken without it (RV §1.2.1).

The registry is written by the engine/compiler only; the core keeps it as a
projection, keyed per branch head.
"""

from __future__ import annotations

from typing import Protocol

from builder_recipe.models import NodeRef, Recipe

__all__ = [
    "NodeRegistry",
    "NodeRegistryProvider",
    "StaticNodeRegistryProvider",
    "derive_node_id",
]


def derive_node_id(entry_path: str) -> str:
    """A best-effort node id for an entry path, used before the compiler runs.

    The compiler's registry is authoritative; this fallback exists so the
    slice can resolve referents before anything has been compiled.
    """
    return entry_path.split(".")[-1].replace("-", "_")


class NodeRegistry:
    """A published (or derived) map between node ids and entry paths."""

    def __init__(self, nodes: list[NodeRef], published: bool = True) -> None:
        self._nodes: list[NodeRef] = list(nodes)
        self.published = published

    @classmethod
    def from_artifact(cls, document: dict) -> "NodeRegistry":
        """Load the compiler's ``nodes.json`` artifact."""
        raw = document.get("nodes", [])
        nodes = [NodeRef.model_validate(item) for item in raw]
        return cls(nodes, published=True)

    @classmethod
    def derived_from(cls, recipe: Recipe) -> "NodeRegistry":
        """Derive a registry from the recipe's entry paths (fallback only)."""
        nodes = [
            NodeRef(
                node_id=derive_node_id(path),
                entry_path=path,
                kind=entry.kind,
                assets=list(entry.assets),
            )
            for path, entry in sorted(recipe.entries.items())
        ]
        return cls(nodes, published=False)

    def nodes(self) -> list[NodeRef]:
        return list(self._nodes)

    def resolve_node(self, node_id: str) -> NodeRef | None:
        for node in self._nodes:
            if node.node_id == node_id:
                return node
        return None

    def nodes_for_path(self, entry_path: str) -> list[NodeRef]:
        return [node for node in self._nodes if node.entry_path == entry_path]

    def orphan_missing(self, entry_paths: set[str]) -> list[NodeRef]:
        """Mark the nodes of removed entries as orphaned. Ids are never reused."""
        orphaned: list[NodeRef] = []
        for node in self._nodes:
            if node.entry_path not in entry_paths and not node.orphaned:
                node.orphaned = True
                orphaned.append(node)
        return orphaned


class NodeRegistryProvider(Protocol):
    """Supplies the registry for a version — the engine publishes it."""

    def registry_for(self, version_id: str) -> NodeRegistry | None: ...


class StaticNodeRegistryProvider:
    """A provider backed by a mapping (the slice's stand-in for the engine)."""

    def __init__(self, registries: dict[str, NodeRegistry] | None = None) -> None:
        self._registries = dict(registries or {})

    def publish(self, version_id: str, registry: NodeRegistry) -> None:
        self._registries[version_id] = registry

    def registry_for(self, version_id: str) -> NodeRegistry | None:
        return self._registries.get(version_id)
