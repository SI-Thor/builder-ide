"""The seam onto the recipe store.

The store is merged (``core.recipe``), so the seam is proven both ways:

* the stub — a recipe held in memory or loaded from JSON;
* the adapter — :class:`BuilderRecipeSource`, which calls the store's own
  ``get_document(version_id)`` and converts what it gets back — tested
  against the **real store**, committing Fjellvik and reading the committed
  version back. The one-hash promise is asserted here: the hash the
  compiler computes is the hash the store committed (§1.2's ``root_hash``).
"""

from __future__ import annotations

import json

import pytest

from builder_usd.canonical import canonical_json
from builder_usd.recipe_source import (
    BuilderRecipeSource,
    RecipeDocument,
    StubRecipeSource,
    builder_recipe_available,
    document_from_dict,
    load_recipe_json,
)


class _FakeRecipe:
    """The shape the store's pydantic models have."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self) -> dict:
        return dict(self._data)


class _FakeStore:
    """The store's interface, as far as the compiler uses it."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.asked_for: list[str] = []

    def get_document(self, version_id: str) -> _FakeRecipe:
        self.asked_for.append(version_id)
        return _FakeRecipe(self.data)


RECIPE = {
    "id": "rcp_fjellvik",
    "name": "Fjellvik",
    "schema_version": 2,
    "engine_pin": {
        "repo": "SI-Thor/infinigen-thor",
        "commit": "abc",
        "config": "sha256:" + "1" * 64,
        "blender": "4.2",
        "python": "3.12",
    },
    "seeds": {"terrain": 7},
    "entries": {
        "harbor.crates": {
            "path": "harbor.crates",
            "kind": "prop_set",
            "params": {"location": [1.0, 0.0, 0.0]},
            "seed": 11,
        }
    },
    "constraints": [],
}


def test_the_stub_holds_a_document():
    source = StubRecipeSource.from_dict(RECIPE)
    document = source.document()
    assert isinstance(document, RecipeDocument)
    assert document.id == "rcp_fjellvik"
    assert document.entries["harbor.crates"].seed == 11


def test_the_adapter_reads_the_store_through_its_own_interface():
    store = _FakeStore(RECIPE)
    source = BuilderRecipeSource(store, "ver_0001")
    document = source.document()
    assert store.asked_for == ["ver_0001"], "the adapter did not use get_document"
    assert document.id == "rcp_fjellvik"
    assert document.entries["harbor.crates"].kind == "prop_set"


def test_both_sides_of_the_seam_agree():
    stub = StubRecipeSource.from_dict(RECIPE).document()
    adapter = BuilderRecipeSource(_FakeStore(RECIPE), "ver_0001").document()
    assert stub.canonical() == adapter.canonical()
    assert stub.recipe_hash() == adapter.recipe_hash()


def test_the_hash_is_the_canonical_hash():
    """The hash must be the one the store would compute for the same document."""
    document = StubRecipeSource.from_dict(RECIPE).document()
    assert document.recipe_hash() == "sha256:" + __import__("hashlib").sha256(
        canonical_json(document.canonical()).encode("utf-8")
    ).hexdigest()


def test_the_hash_is_stable_under_key_order():
    reordered = {
        "entries": RECIPE["entries"],
        "constraints": RECIPE["constraints"],
        "seeds": RECIPE["seeds"],
        "engine_pin": RECIPE["engine_pin"],
        "schema_version": RECIPE["schema_version"],
        "name": RECIPE["name"],
        "id": RECIPE["id"],
    }
    first = StubRecipeSource.from_dict(RECIPE).document().recipe_hash()
    second = StubRecipeSource.from_dict(reordered).document().recipe_hash()
    assert first == second


def test_a_recipe_file_loads(tmp_path):
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(RECIPE), encoding="utf-8")
    document = load_recipe_json(path).document()
    assert document.id == "rcp_fjellvik"


def test_the_store_is_on_the_path():
    """The seats are merged: the store the adapter probes is importable."""
    assert builder_recipe_available() is True


def test_the_adapter_reads_the_real_store_and_agrees_on_the_hash():
    """Fjellvik committed through the real store reads back through the
    adapter, and the compiler's hash is the store's committed root hash."""
    from core.recipe.blobs import MemoryBlobStore
    from core.recipe.ledger import InMemoryLedger
    from core.recipe.models import Actor, Recipe as StoreRecipe
    from core.recipe.schema import StaticSchemaRegistry
    from core.recipe.store import RecipeStore
    from core.vocab.seed import RECIPE_DOCUMENT
    from core.vocab.words import default_entries

    schemas = StaticSchemaRegistry()
    for word in default_entries():  # the vocabulary is the validator (§1.1)
        schemas.register(word.word, word.params)
    store = RecipeStore(ledger=InMemoryLedger(), blobs=MemoryBlobStore(),
                        schemas=schemas)
    store.create_recipe(StoreRecipe.model_validate(RECIPE_DOCUMENT),
                        Actor(kind="owner", id="casey"))
    version = store.get_branch("br_main").head

    document = BuilderRecipeSource(store, version).document()
    assert document.id == "rcp_fjellvik"
    assert document.entries["harbor.crates"].kind == "prop_set"
    # §1.2: the version's root_hash is the canonical document's hash — the
    # same bytes this package hashes, or the two halves never agreed.
    assert document.recipe_hash() == store.get_version(version).root_hash
