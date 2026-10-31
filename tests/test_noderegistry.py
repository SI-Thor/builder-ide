"""The node registry projection and the referents it resolves."""

from __future__ import annotations

from core.recipe.models import NodeRef, Recipe
from core.recipe.noderegistry import (
    NodeRegistry,
    StaticNodeRegistryProvider,
    derive_node_id,
)


def _registry() -> NodeRegistry:
    return NodeRegistry(
        [
            NodeRef(
                node_id="span_south",
                entry_path="structure.south_span",
                kind="structure",
                assets=["ast_plank_01"],
                part="deck",
            ),
            NodeRef(
                node_id="pier_s2",
                entry_path="structure.south_span",
                kind="structure",
                assets=[],
                part="pier",
            ),
            NodeRef(
                node_id="crate_07",
                entry_path="harbor.crates",
                kind="prop_set",
                assets=[],
            ),
        ]
    )


def test_a_node_id_resolves_to_its_entry_path():
    registry = _registry()
    node = registry.resolve_node("span_south")
    assert node is not None
    assert node.entry_path == "structure.south_span"
    assert node.part == "deck"


def test_an_unknown_node_id_resolves_to_nothing():
    assert _registry().resolve_node("span_north") is None


def test_the_registry_lists_every_node_of_an_entry():
    nodes = _registry().nodes_for_path("structure.south_span")
    assert {node.node_id for node in nodes} == {"span_south", "pier_s2"}


def test_the_registry_loads_from_the_compiler_artifact():
    registry = NodeRegistry.from_artifact(
        {
            "nodes": [
                {
                    "node_id": "span_south",
                    "entry_path": "structure.south_span",
                    "kind": "structure",
                    "assets": [],
                    "part": "deck",
                }
            ]
        }
    )
    assert registry.published is True
    assert registry.resolve_node("span_south").entry_path == "structure.south_span"


def test_a_node_whose_entry_is_gone_is_orphaned_and_never_reused():
    registry = _registry()
    orphaned = registry.orphan_missing({"harbor.crates"})
    assert [node.node_id for node in orphaned] == ["span_south", "pier_s2"]
    assert registry.resolve_node("span_south").orphaned is True
    assert registry.resolve_node("span_south").entry_path == "structure.south_span"


def test_the_derived_fallback_names_a_node_after_its_entry_path():
    assert derive_node_id("structure.south_span") == "south_span"


def test_the_derived_fallback_is_not_a_published_registry(fjellvik: Recipe):
    registry = NodeRegistry.derived_from(fjellvik)
    assert registry.published is False
    assert registry.resolve_node("crates").entry_path == "harbor.crates"


def test_the_provider_returns_the_registry_published_for_a_version():
    provider = StaticNodeRegistryProvider()
    provider.publish("ver_0001", _registry())
    assert provider.registry_for("ver_0001") is not None
    assert provider.registry_for("ver_9999") is None
