"""Branches: named commit lines, pointer moves, and the morning flip (§1.2).

Applying a choice is a **pointer move**, not a re-render: the morning A/B/C
flip is ``main.head = branch.head`` (D §07:11). A rejection never deletes.
"""

from __future__ import annotations

import pytest

from builder_recipe.errors import BranchError
from builder_recipe.models import Actor, Op, Recipe
from builder_recipe.store import RecipeStore


def _seed(store: RecipeStore, fjellvik: Recipe, actor: Actor) -> None:
    store.create_recipe(fjellvik, actor)


def test_a_branch_is_created_at_a_version(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="night-2026-10-30",
        recipe="rcp_fjellvik",
        head="ver_0001",
        purpose="night",
        actor=actor,
    )
    assert branch.head == "ver_0001"
    assert branch.purpose == "night"
    assert branch.created_by == actor


def test_branch_ids_are_unique(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    first = store.create_branch(
        name="a", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    second = store.create_branch(
        name="b", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    assert first.id != second.id


def test_a_head_moves_forward(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    assert store.get_branch(branch.id).head == "ver_0002"


def test_a_head_never_moves_backwards(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    with pytest.raises(BranchError):
        store.move_head(branch.id, "ver_0001", actor=actor)


def test_moving_a_head_to_a_divergent_version_is_refused(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    other = store.create_branch(
        name="other", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    divergent = store.apply_edit(
        "ver_0001",
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=actor,
        message="a steeper slope",
        branch=other.id,
    )
    with pytest.raises(BranchError):
        store.move_head(branch.id, divergent.id, actor=actor)


def test_applying_a_branch_moves_the_main_head(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="option-a", recipe="rcp_fjellvik", head="ver_0001", purpose="morning-option", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    store.apply_branch(branch.id, actor=actor)
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    assert main.head == "ver_0002"


def test_applying_a_branch_is_a_pointer_move_and_commits_no_version(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="option-a", recipe="rcp_fjellvik", head="ver_0001", purpose="morning-option", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    before = len(store.list_versions("rcp_fjellvik"))
    store.apply_branch(branch.id, actor=actor)
    assert len(store.list_versions("rcp_fjellvik")) == before


def test_a_kid_apply_proposes_instead_of_applying(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, magnus: Actor
):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="option-a", recipe="rcp_fjellvik", head="ver_0001", purpose="morning-option", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    proposal = store.apply_branch(branch.id, actor=magnus)
    assert proposal.state == "pending"
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    assert main.head == "ver_0001"


def test_the_owner_confirms_a_kid_proposal(store: RecipeStore, fjellvik: Recipe, actor: Actor, magnus: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="option-a", recipe="rcp_fjellvik", head="ver_0001", purpose="morning-option", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    proposal = store.apply_branch(branch.id, actor=magnus)
    store.confirm_proposal(proposal.id, actor=actor)
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    assert main.head == "ver_0002"


def test_a_rejected_branch_is_kept_and_marked(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    branch = store.create_branch(
        name="option-b", recipe="rcp_fjellvik", head="ver_0001", purpose="morning-option", actor=actor
    )
    store.reject_branch(branch.id, actor=actor, reason="the planks read as glued")
    rejected = store.get_branch(branch.id)
    assert rejected.purpose == "rejected"
    assert rejected.head == "ver_0001"


def test_a_protected_branch_cannot_be_rejected(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    with pytest.raises(BranchError):
        store.reject_branch(main.id, actor=actor, reason="no")


def test_the_standing_options_are_two_branches(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    options = store.standing_options("rcp_fjellvik", "ver_0001", actor=actor)
    assert [option.name for option in options] == ["keep-yesterday", "back-to-plan"]
    assert {option.purpose for option in options} == {"standing"}
    assert all(option.head == "ver_0001" for option in options)


def test_a_branch_of_another_recipe_is_refused(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    _seed(store, fjellvik, actor)
    with pytest.raises(BranchError):
        store.create_branch(
            name="stray", recipe="rcp_elsewhere", head="ver_0001", purpose="night", actor=actor
        )
