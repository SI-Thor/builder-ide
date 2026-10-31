"""A character's typed call — the door out-of-schema params do not get through.

core-spec v2 §1.5: ``POST /v1/vocab/call {word, node | region, params}`` →
the core validates against the schema, binds the acceptance template, and
produces a ``RecipeEdit`` authored ``{kind: character, id: …, via: word}``.
Anything outside the schema is refused at the door — that refusal, said in
character, is the "I can't do rope yet" moment (D §21:08). Refused calls are
audited too: the edges are the story (D §5.5).
"""

from __future__ import annotations

import pytest

from core.recipe.errors import SchemaViolation
from core.recipe.models import Actor, NodeRef, Op, Recipe
from core.recipe.noderegistry import NodeRegistry, StaticNodeRegistryProvider
from core.recipe.store import RecipeStore


def _store_with_registry(store: RecipeStore, version_id: str = "ver_0001") -> RecipeStore:
    provider = StaticNodeRegistryProvider()
    provider.publish(
        version_id,
        NodeRegistry(
            [
                NodeRef(node_id="crate_07", entry_path="harbor.crates", kind="prop_set"),
                NodeRef(
                    node_id="span_south",
                    entry_path="structure.south_span",
                    kind="structure",
                ),
                # the oak the project-level drip-line constraint refers to
                NodeRef(node_id="oak_0117", entry_path="terrain.harbor", kind="terrain"),
            ]
        ),
    )
    store.registry_provider = provider
    return store


def test_a_call_with_in_schema_params_produces_an_edit(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    version = store.vocab_call(
        word="props.harbor.crates",
        node="crate_07",
        params={"count": 20},
        author=architect,
        message="more crates",
        base="ver_0001",
    )
    assert version.id == "ver_0002"
    assert store.get_document("ver_0002").entries["harbor.crates"].params["count"] == 20


def test_the_edit_is_authored_by_the_character_with_via_word(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    store.vocab_call(
        word="props.harbor.crates",
        node="crate_07",
        params={"count": 20},
        author=architect,
        message="more crates",
        base="ver_0001",
    )
    edit = store.list_edits()[0]
    assert edit.author.kind == "character"
    assert edit.author.via == "word"
    assert edit.ops == [Op(op="set", path="harbor.crates.params.count", value=20)]


def test_a_call_outside_the_schema_is_refused(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.vocab_call(
            word="props.harbor.crates",
            node="crate_07",
            params={"count": 999},
            author=architect,
            message="too many crates",
            base="ver_0001",
        )


def test_a_refused_call_commits_no_version(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.vocab_call(
            word="props.harbor.crates",
            node="crate_07",
            params={"style": "gleaming"},
            author=architect,
            message="a style that is not in the vocabulary",
            base="ver_0001",
        )
    assert [v.id for v in store.list_versions("rcp_fjellvik")] == ["ver_0001"]


def test_a_refused_call_is_audited(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.vocab_call(
            word="props.harbor.crates",
            node="crate_07",
            params={"count": 999},
            author=architect,
            message="too many crates",
            base="ver_0001",
        )
    calls = [event for event in store.ledger.events() if event.type == "vocab.call"]
    assert len(calls) == 1
    assert calls[0].payload["ok"] is False


def test_a_successful_call_is_audited_too(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    store.vocab_call(
        word="props.harbor.crates",
        node="crate_07",
        params={"count": 20},
        author=architect,
        message="more crates",
        base="ver_0001",
    )
    calls = [event for event in store.ledger.events() if event.type == "vocab.call"]
    assert len(calls) == 1
    assert calls[0].payload["word"] == "props.harbor.crates"
    assert calls[0].payload["ok"] is True


def test_a_call_for_a_word_that_is_not_in_the_vocabulary_is_refused(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.vocab_call(
            word="props.harbor.rope_coils",
            node="crate_07",
            params={"count": 2},
            author=architect,
            message="rope coils are not in my hands yet",
            base="ver_0001",
        )


def test_a_call_whose_node_is_unknown_is_refused(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, architect: Actor
):
    _store_with_registry(store)
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.vocab_call(
            word="props.harbor.crates",
            node="crate_99",
            params={"count": 2},
            author=architect,
            message="a crate that is not there",
            base="ver_0001",
        )
