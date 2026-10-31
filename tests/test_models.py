"""The recipe models of core-spec v2 §1.1/§1.2 and their own invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from builder_recipe.models import (
    Actor,
    Branch,
    Constraint,
    EnginePin,
    Op,
    Recipe,
    RecipeEdit,
    RecipeEntry,
)


def test_engine_pin_requires_a_pinned_config_hash():
    with pytest.raises(ValidationError):
        EnginePin(repo="SI-Thor/infinigen-thor", commit="9f31c0e", blender="4.2", python="3.12")


def test_engine_pin_config_must_carry_the_sha256_prefix():
    with pytest.raises(ValidationError):
        EnginePin(
            repo="SI-Thor/infinigen-thor",
            commit="9f31c0e",
            config="cf90cafe",
            blender="4.2",
            python="3.12",
        )


def test_engine_pin_accepts_a_pinned_config_hash(pin: EnginePin):
    assert pin.config.startswith("sha256:")


@pytest.mark.parametrize("path", ["crates", "harbor.crates", "a.b.c"])
def test_entry_path_accepts_up_to_three_dotted_segments(path: str):
    entry = RecipeEntry(path=path, kind="prop_set")
    assert entry.path == path


@pytest.mark.parametrize("path", ["a.b.c.d", "", ".crates", "harbor..crates"])
def test_entry_path_rejects_more_than_three_segments_or_empty_segments(path: str):
    with pytest.raises(ValidationError):
        RecipeEntry(path=path, kind="prop_set")


def test_recipe_rejects_an_entry_whose_path_disagrees_with_its_key(fjellvik: Recipe):
    fjellvik.entries["harbor.crates"] = RecipeEntry(path="harbor.other", kind="prop_set")
    with pytest.raises(ValidationError):
        Recipe.model_validate(fjellvik.model_dump())


def test_recipe_defaults_to_schema_version_two(fjellvik: Recipe):
    assert fjellvik.schema_version == 2


def test_constraint_kind_is_a_closed_set():
    with pytest.raises(ValidationError):
        Constraint(name="x", kind="physics", ref=None, value=1.0)


def test_op_is_a_closed_verb_set():
    with pytest.raises(ValidationError):
        Op(op="mutate", path="harbor.crates.params.count", value=3)


def test_edit_rejects_more_than_thirty_two_ops():
    ops = [Op(op="set", path=f"harbor.crates.params.n{i}", value=i) for i in range(33)]
    with pytest.raises(ValidationError):
        RecipeEdit(
            id="ed_0001",
            base="ver_0001",
            ops=ops,
            author=Actor(kind="owner", id="casey"),
            message="too many ops",
        )


def test_edit_accepts_exactly_thirty_two_ops():
    ops = [Op(op="set", path=f"harbor.crates.params.n{i}", value=i) for i in range(32)]
    edit = RecipeEdit(
        id="ed_0001",
        base="ver_0001",
        ops=ops,
        author=Actor(kind="owner", id="casey"),
        message="exactly thirty two",
    )
    assert len(edit.ops) == 32


def test_edit_message_is_capped_at_eighty_characters():
    with pytest.raises(ValidationError):
        RecipeEdit(
            id="ed_0001",
            base="ver_0001",
            ops=[],
            author=Actor(kind="owner", id="casey"),
            message="x" * 81,
        )


def test_edit_message_is_one_line():
    with pytest.raises(ValidationError):
        RecipeEdit(
            id="ed_0001",
            base="ver_0001",
            ops=[],
            author=Actor(kind="owner", id="casey"),
            message="first line\nsecond line",
        )


def test_branch_purpose_is_a_closed_set():
    with pytest.raises(ValidationError):
        Branch(
            id="br_0001",
            name="mystery",
            recipe="rcp_fjellvik",
            head="ver_0001",
            base=None,
            purpose="spare",
            created_by=Actor(kind="owner", id="casey"),
        )


def test_actor_carries_kind_id_and_via():
    actor = Actor(kind="character", id="architect", via="word")
    assert (actor.kind, actor.id, actor.via) == ("character", "architect", "word")
