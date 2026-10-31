"""Merging into main: fast-forward, three-way at entry granularity, questions.

Entries are independent by construction; two edits to the same entry conflict
and park a question rather than auto-merging — ambiguity is resolved by
asking, never by guessing (V §"Calling the computer in-game").
"""

from __future__ import annotations

import pytest

from builder_recipe.errors import MergeConflict
from builder_recipe.models import Actor, Op, Recipe
from builder_recipe.store import RecipeStore


def _setup(store: RecipeStore, fjellvik: Recipe, actor: Actor):
    store.create_recipe(fjellvik, actor)
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    return branch


def test_a_merge_fast_forwards_when_main_has_not_moved(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    branch = _setup(store, fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    store.merge_branch(branch.id, actor=actor)
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    assert main.head == "ver_0002"
    assert len(store.list_versions("rcp_fjellvik")) == 2


def test_a_three_way_merge_combines_changes_to_different_entries(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    branch = _setup(store, fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=actor,
        message="a steeper slope",
        branch=main.id,
    )
    store.merge_branch(branch.id, actor=actor)
    merged = store.get_document(store.get_branch(main.id).head)
    assert merged.entries["harbor.crates"].params["count"] == 20
    assert merged.entries["terrain.harbor"].params["slope"] == 0.2


def test_the_merged_version_sits_on_top_of_main(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    branch = _setup(store, fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=actor,
        message="a steeper slope",
        branch=main.id,
    )
    before = store.get_branch(main.id).head
    version = store.merge_branch(branch.id, actor=actor)
    assert version.parent == before
    assert store.get_branch(main.id).head == version.id


def test_a_conflicting_merge_parks_a_question_and_commits_no_version(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, questions: RecordingQuestions
):
    store.questions = questions
    branch = _setup(store, fjellvik, actor)
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=actor,
        message="more crates",
        branch=branch.id,
    )
    main = [b for b in store.list_branches("rcp_fjellvik") if b.purpose == "main"][0]
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=30)],
        author=actor,
        message="even more crates",
        branch=main.id,
    )
    with pytest.raises(MergeConflict):
        store.merge_branch(branch.id, actor=actor)
    assert questions.parked
    assert "harbor.crates" in questions.parked[0]["detail"]
    assert len(store.list_versions("rcp_fjellvik")) == 3
