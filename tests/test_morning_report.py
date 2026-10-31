"""The morning-report case (BRIEF.md #3): kill a goal; its dependent assets
show up as questionable with the broken chain explained — and nothing is
deleted."""

from __future__ import annotations

from core.justification import JustificationService
from core.why import Status
from fjellvik import AS_OF, EAST_TASK, fjellvik

#: Everything whose only justification is the east-slope goal.
EAST_DEPENDENTS = {
    ("asset", "ast_0231"),
    ("asset", "ast_0232"),
    ("entry", "props.felled_timber"),
    ("entry", "forest.east_slope"),
    ("branch", "br_east"),
    ("work_order", "wo_15"),
    ("vocab", "props.timber.pile"),
}


def test_before_the_kill_the_night_is_justified():
    service = JustificationService(fjellvik())  # task_8801 still "running"
    for kind, key in EAST_DEPENDENTS:
        assert service.status_of(kind, key, AS_OF).status is Status.ALIVE, \
            f"{kind}:{key} should be justified before the kill"


def test_kill_goal_makes_dependents_questionable():
    # The owner's morning decision: drop the goal. In the real core this is
    # an audited task-state change; the justification projection only reads.
    records = fjellvik(east_state="dropped")
    service = JustificationService(records)

    for kind, key in EAST_DEPENDENTS:
        j = service.status_of(kind, key, AS_OF)
        assert j.status is Status.UNKNOWN, f"{kind}:{key} should be questionable"
        assert j.label == "questionable"
        assert j.weight == 0.25          # the borrowed discount: kept, starving
        assert j.may_enter_new_work      # questionable continues; dead may not
        assert j.cause.key == EAST_TASK  # the chain is explained at the goal


def test_the_broken_chain_is_explained_in_plain_words():
    service = JustificationService(fjellvik(east_state="dropped"))

    timber = service.status_of("asset", "ast_0231", AS_OF)
    assert [s.kind for s in timber.chain] == [
        "asset", "entry", "branch", "goal"]
    assert [s.key for s in timber.chain] == [
        "ast_0231", "props.felled_timber", "br_east", EAST_TASK]
    assert timber.reason == "you dropped this goal from the plan"
    assert "Forest the east slope, keep the oak" in timber.explanation
    assert timber.explanation.startswith("asset ast_0231: questionable")
    assert "nothing is deleted" in timber.explanation

    word = service.status_of("vocab", "props.timber.pile", AS_OF)
    assert [s.key for s in word.chain] == [
        "props.timber.pile", "wo_15", EAST_TASK]
    assert "dropped this goal" in word.explanation


def test_kept_work_is_untouched_by_the_kill():
    service = JustificationService(fjellvik(east_state="dropped"))
    for kind, key in [
        ("asset", "ast_0207"),        # crates on kept main
        ("vocab", "bridge.rope"),     # promoted by kept WO-14
        ("branch", "br_main"),
        ("work_order", "wo_14"),
        ("goal", "task_8701"),
        ("vocab", "props.harbor.crates"),   # builtin
    ]:
        assert service.status_of(kind, key, AS_OF).status is Status.ALIVE, \
            f"{kind}:{key} must not be questioned by an unrelated kill"


def test_nothing_is_deleted_and_the_report_says_so():
    records = fjellvik(east_state="dropped")
    service = JustificationService(records)
    report = service.morning_report(AS_OF)

    # every record still exists — statuses flag, they never remove
    assert len(records.assets) == 6 and len(records.branches) == 4
    assert len(records.vocabulary) == 4 and len(records.work_orders) == 3

    flagged = {(j.kind, j.key) for j in report.questionable + report.dead_retained}
    assert EAST_DEPENDENTS <= flagged                      # the killed goal's work
    assert ("asset", "ast_0251") in flagged                # the stale goal's lantern
    assert ("asset", "ast_0244") in {(j.kind, j.key) for j in report.dead_retained}

    assert report.lines[0].startswith("Justification:")
    assert "12 questionable" in report.lines[0]  # east goal + 6 deps + stale north trio
    # every questionable and dead entity is named on a line, as words (§4.3)
    for j in report.questionable + report.dead_retained:
        assert any(j.key in line for line in report.lines), \
            f"{j.kind}:{j.key} missing from the report lines"
    assert any("ast_0231" in line and "Forest the east slope" in line
               for line in report.lines), "the crate card must name the dead goal"


def test_census_is_the_necessity_census_over_all_entities():
    """alive 9 · questionable 12 · dead 4 · unwired 1, over all 26 entities —
    an unwired asset counts (the kernel's own summary cannot see it)."""
    report = JustificationService(fjellvik(east_state="dropped")).morning_report(AS_OF)
    assert report.census == {"alive": 9, "unknown": 12, "dead": 4, "absent": 1}
