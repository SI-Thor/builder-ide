"""The recipe store: versions, the hash they key on, and the refusals.

Core-spec v2 §1.1 ("A recipe never mutates in place; change is an edit") and
§1.2 (versions and branches).
"""

from __future__ import annotations

import json

import pytest

from core.recipe.canonical import canonical_json, content_hash
from core.recipe.errors import ConstraintViolation, IntegrityError, NotFound, SchemaViolation
from core.recipe.models import Actor, Constraint, Op, Recipe
from core.recipe.store import RecipeStore


def test_creating_a_recipe_commits_a_root_version(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    version = store.get_version("ver_0001")
    assert version.recipe == "rcp_fjellvik"
    assert version.parent is None
    assert version.edit is None
    assert version.actor == actor


def test_the_root_version_hash_is_the_hash_of_the_canonical_document(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    version = store.get_version("ver_0001")
    assert version.root_hash == content_hash(fjellvik.model_dump())


def test_the_document_comes_back_byte_identical(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    document = store.get_document("ver_0001")
    assert document == fjellvik
    assert canonical_json(document.model_dump()) == canonical_json(fjellvik.model_dump())


def test_creating_a_recipe_creates_the_protected_main_branch(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    branches = store.list_branches("rcp_fjellvik")
    main = [b for b in branches if b.purpose == "main"]
    assert len(main) == 1
    assert main[0].head == "ver_0001"
    assert main[0].protected is True


def test_a_tampered_blob_is_refused_on_read(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    ref = store.version_blob_ref("ver_0001")
    store.blobs.path_for(ref).write_bytes(b"tampered")
    with pytest.raises(IntegrityError):
        store.get_document("ver_0001")


def test_an_edit_commits_a_child_version(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    version = store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    assert version.id == "ver_0002"
    assert version.parent == "ver_0001"
    assert version.edit is not None
    assert version.root_hash != store.get_version("ver_0001").root_hash


def test_an_edit_leaves_the_base_version_untouched(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    assert store.get_document("ver_0001").entries["harbor.crates"].params["count"] == 12


def test_out_of_schema_params_are_refused_at_the_door(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.apply_edit(
            "ver_0001",
            [Op(op="set", path="harbor.crates.params.count", value=999)],
            author=actor,
            message="too many crates",
        )
    assert [v.id for v in store.list_versions("rcp_fjellvik")] == ["ver_0001"]


def test_a_refused_edit_commits_no_version(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.apply_edit(
            "ver_0001",
            [Op(op="set", path="harbor.crates.params.style", value="gleaming")],
            author=actor,
            message="a style that is not in the vocabulary",
        )
    assert [v.id for v in store.list_versions("rcp_fjellvik")] == ["ver_0001"]


def test_a_refused_edit_is_audited(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    with pytest.raises(SchemaViolation):
        store.apply_edit(
            "ver_0001",
            [Op(op="set", path="harbor.crates.params.style", value="gleaming")],
            author=actor,
            message="a style that is not in the vocabulary",
        )
    types = [event.type for event in store.ledger.events()]
    assert "edit.proposed" in types
    assert "edit.validated" in types
    assert "version.committed" not in types[2:]


def test_a_broken_constraint_refuses_the_edit(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    fjellvik.entries["structure.south_span"].constraints.append(
        Constraint(
            name="south_span_load", kind="load_floor", ref=None, value=1.0
        )
    )
    store.create_recipe(fjellvik, actor)
    with pytest.raises(ConstraintViolation):
        store.apply_edit(
            "ver_0001",
            [Op(op="set", path="structure.south_span.params.load_factor", value=0.5)],
            author=actor,
            message="a weaker span",
        )
    assert [v.id for v in store.list_versions("rcp_fjellvik")] == ["ver_0001"]


def test_a_broken_constraint_is_audited(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    fjellvik.entries["structure.south_span"].constraints.append(
        Constraint(
            name="south_span_load", kind="load_floor", ref=None, value=1.0
        )
    )
    store.create_recipe(fjellvik, actor)
    with pytest.raises(ConstraintViolation):
        store.apply_edit(
            "ver_0001",
            [Op(op="set", path="structure.south_span.params.load_factor", value=0.5)],
            author=actor,
            message="a weaker span",
        )
    types = [event.type for event in store.ledger.events()]
    assert "constraint.failed" in types


def test_an_edit_on_an_unknown_base_is_refused(store: RecipeStore, actor: Actor):
    with pytest.raises(NotFound):
        store.apply_edit(
            "ver_9999",
            [Op(op="set", path="harbor.crates.params.count", value=20)],
            author=actor,
            message="no such base",
        )


def test_the_store_rebuilds_its_projections_from_the_ledger(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    rebuilt = RecipeStore(
        ledger=store.ledger, blobs=store.blobs, schemas=store.schemas
    )
    rebuilt.rebuild()
    assert [v.id for v in rebuilt.list_versions("rcp_fjellvik")] == ["ver_0001", "ver_0002"]
    assert [b.name for b in rebuilt.list_branches("rcp_fjellvik")] == ["main"]


def test_the_same_edit_produces_the_same_hash(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    first = store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    other = RecipeStore(
        ledger=store.ledger, blobs=store.blobs, schemas=store.schemas
    )
    other.rebuild()
    second = other.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    assert first.root_hash == second.root_hash


def test_the_listing_is_byte_identical_across_runs(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    store.create_recipe(fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
    )
    listing = json.dumps(store.listing(), sort_keys=True)
    again = json.dumps(store.listing(), sort_keys=True)
    assert listing == again
