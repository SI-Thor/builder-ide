"""Replay-kept: the cherry-pick, the merge, and the parked conflicts.

The scenarios are the design note's (§2.5): *"something went wrong around
14:00, but the thing they built at 16:00 is good — keep that."* Two actors
edit the same canon; the human keeps one actor's work and drops the other's;
the result lands on a fork, and the canon does not move.
"""

from __future__ import annotations

import pytest

from core.recipe.models import Actor, Op, Recipe
from core.recipe.store import RecipeStore
from core.rewind import (
    RewindPoint,
    cherry_pick,
    fork_at_point,
    main_branch,
    parse,
    point_at_version,
    points,
    replay_kept,
)


def _setup(store: RecipeStore, fjellvik: Recipe, actor: Actor) -> None:
    store.create_recipe(fjellvik, actor)


def test_a_fork_leaves_the_canon_exactly_where_it_was(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    main = main_branch(store, "rcp_fjellvik")
    assert main.head == "ver_0001"

    fork = fork_at_point(store, version="ver_0001", name="rewind", actor=actor)

    assert fork.head == "ver_0001"
    assert fork.base == "ver_0001"
    assert fork.purpose == "work-order"
    # The canon's own branch did not move, and no version was removed.
    assert main_branch(store, "rcp_fjellvik").head == "ver_0001"
    assert [point.version for point in points(store)] == ["ver_0001"]


def test_the_rewind_point_carries_the_ledger_seq(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    point = point_at_version(store, "ver_0001")
    assert point.version == "ver_0001"
    assert point.seq == 1
    assert point.recipe == "rcp_fjellvik"


def test_the_cherry_pick_keeps_one_actors_work_and_drops_anothers(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    magnus = Actor(kind="owner", id="magnus")

    # The night's branch: magnus adds crates at 16:00.
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="more crates",
        branch=branch.id,
    )

    # The canon moved meanwhile: casey changed the terrain.
    main = main_branch(store, "rcp_fjellvik")
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=actor,
        message="a steeper slope",
        branch=main.id,
    )
    assert main_branch(store, "rcp_fjellvik").head == "ver_0003"

    pick = cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=actor,
    )

    # The fork is cut at the point, and the canon's own branch did not move.
    assert pick.fork.head == "ver_0001" or pick.fork.head == pick.version
    assert main_branch(store, "rcp_fjellvik").head == "ver_0003"
    assert pick.merged_cleanly

    # The kept work came across; the dropped work did not.
    assert pick.merged is not None
    assert pick.merged.entries["harbor.crates"].params["count"] == 20
    # The canon's own change is in the merge, because the merge is with main.
    assert pick.merged.entries["terrain.harbor"].params["slope"] == 0.2

    # The report says which events were kept and which were dropped.
    kinds = {outcome.kind for outcome in pick.kept}
    assert "edit.proposed" in kinds
    assert {outcome.actor for outcome in pick.kept} == {"magnus"}
    assert {outcome.actor for outcome in pick.dropped} == {"casey"}
    for outcome in pick.dropped:
        assert outcome.reason


def test_the_selection_drops_the_events_it_does_not_match(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    magnus = Actor(kind="owner", id="magnus")
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="more crates",
        branch=branch.id,
    )
    store.apply_edit(
        branch.head,
        [Op(op="set", path="terrain.harbor.params.slope", value=0.2)],
        author=actor,
        message="a steeper slope",
        branch=branch.id,
    )

    pick = cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=actor,
    )

    kept_authors = {outcome.actor for outcome in pick.kept}
    assert "magnus" in kept_authors
    assert "casey" not in kept_authors

    dropped_authors = {outcome.actor for outcome in pick.dropped}
    assert "casey" in dropped_authors
    for outcome in pick.dropped:
        assert outcome.reason


def test_a_conflicting_merge_parks_a_question_and_moves_nothing(
    store: RecipeStore, fjellvik: Recipe, actor: Actor, questions
):
    _setup(store, fjellvik, actor)
    magnus = Actor(kind="owner", id="magnus")

    # The canon changed the same entry, differently.
    main = main_branch(store, "rcp_fjellvik")
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=30)],
        author=actor,
        message="thirty crates",
        branch=main.id,
    )
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="twenty crates",
        branch=branch.id,
    )

    pick = cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=actor,
        questions=questions,
    )

    assert not pick.merged_cleanly
    assert pick.merged is None
    assert pick.parked
    assert pick.parked[0].name == "merge-conflict"
    assert "harbor.crates" in pick.parked[0].detail
    # The question went to the sink, and the canon did not move.
    assert questions.parked
    assert "harbor.crates" in questions.parked[0]["detail"]
    assert main_branch(store, "rcp_fjellvik").head == "ver_0002"


def test_the_parked_question_is_in_the_ledger_when_there_is_no_sink(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    magnus = Actor(kind="owner", id="magnus")
    main = main_branch(store, "rcp_fjellvik")
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=30)],
        author=actor,
        message="thirty crates",
        branch=main.id,
    )
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="twenty crates",
        branch=branch.id,
    )

    cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=actor,
        questions=None,
    )

    parked = [event for event in store.ledger.events(types=["question.parked"])]
    assert len(parked) == 1
    assert parked[0].payload["name"] == "merge-conflict"
    assert parked[0].payload["options"] == ["ours", "theirs"]


def test_the_report_says_what_was_kept_dropped_and_parked(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    magnus = Actor(kind="owner", id="magnus")
    branch = store.create_branch(
        name="night", recipe="rcp_fjellvik", head="ver_0001", purpose="night", actor=actor
    )
    store.apply_edit(
        "ver_0001",
        [Op(op="set", path="harbor.crates.params.count", value=20)],
        author=magnus,
        message="more crates",
        branch=branch.id,
    )

    pick = cherry_pick(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = magnus"),
        actor=actor,
    )
    report = pick.report(source="the core's ledger")
    text = report.render()

    assert "kept" in text
    assert "dropped" in text
    assert "actor = magnus" in text
    assert report.as_dict()["selection"] == "actor = magnus"


def test_a_kept_edit_that_was_never_committed_carries_no_work(
    store: RecipeStore, fjellvik: Recipe, actor: Actor
):
    _setup(store, fjellvik, actor)
    # An edit that was proposed and never committed: it is in the ledger,
    # and it changes nothing.
    store.ledger.append(
        type="edit.proposed",
        actor=actor,
        subject={"entity_kind": "edit", "entity_id": "ed_9999"},
        payload={
            "edit": "ed_9999",
            "base": "ver_0001",
            "ops": [{"op": "set", "path": "harbor.crates.params.count", "value": 44}],
            "message": "never committed",
        },
    )

    ops, reasons, kept, dropped = replay_kept(
        store,
        point=point_at_version(store, "ver_0001"),
        selection=parse("actor = casey"),
    )
    assert ops == []
    assert any("never committed" in reason for reason in reasons.values())
