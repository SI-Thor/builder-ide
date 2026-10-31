"""The attachment contract: every asset, word, branch and work order carries
a justification chain; the borrowed lifecycle behaviours hold."""

from __future__ import annotations

import pytest

from core.justification import JustificationService, build_graph
from core.why import Status
from tests.fjellvik import AS_OF, EAST_TASK, fjellvik

#: The four kinds the brief names, plus the connective kinds.
ATTACHED_KINDS = ["asset", "vocab", "branch", "work_order", "goal", "entry"]


def entities_of(service, kind):
    return [j for j in service.all(AS_OF) if j.kind == kind]


def test_every_entity_has_a_chain_terminating_where_it_should():
    service = JustificationService(fjellvik())
    graph, att = build_graph(service.records)
    everything = service.all(AS_OF)
    assert {j.kind for j in everything} >= {
        "asset", "vocab", "branch", "work_order", "goal", "entry"}
    for j in everything:
        assert j.chain, f"{j.kind}:{j.key} has no chain"
        if j.status is Status.ALIVE:
            root = j.chain[-1].node
            assert root in att.roots, (
                f"{j.kind}:{j.key} is alive but its chain ends at {root}, "
                "which is not an attested root")
            assert j.chain[-1].status is Status.ALIVE


def test_alive_chains_name_who_they_serve():
    service = JustificationService(fjellvik())

    crates = service.status_of("asset", "ast_0207", AS_OF)
    assert crates.status is Status.ALIVE
    assert crates.label == "justified" and crates.weight == 1.0
    assert "harbor.crates" in crates.because and "br_main" in crates.because

    word = service.status_of("vocab", "bridge.rope", AS_OF)
    assert word.status is Status.ALIVE
    assert [s.key for s in word.chain] == ["bridge.rope", "wo_14", "task_8701"]
    assert "Harbor hamlet" in word.chain[-1].line  # the goal it serves, in words


def test_stale_goal_makes_dependents_questionable_not_dead():
    service = JustificationService(fjellvik())

    lantern = service.status_of("asset", "ast_0251", AS_OF)
    assert lantern.status is Status.UNKNOWN
    assert lantern.label == "questionable" and lantern.weight == 0.25
    assert lantern.may_enter_new_work is True   # kept running at a discount
    assert lantern.cause.key == "task_8702"
    assert "review-by 2026-08-15" in lantern.reason and "grace" in lantern.reason
    assert "nothing is deleted" in lantern.explanation


def test_rejected_branch_is_the_certified_dead_arm():
    service = JustificationService(fjellvik())

    wild = service.status_of("asset", "ast_0244", AS_OF)
    assert wild.status is Status.DEAD
    assert wild.label == "dead" and wild.weight == 0.0
    assert wild.may_enter_new_work is False
    assert wild.cause.key == "br_wild"
    assert "rejected" in wild.reason
    assert "never deleted" in wild.explanation  # removal justified, still retained

    assert service.status_of("branch", "br_wild", AS_OF).status is Status.DEAD
    assert (service.status_of("entry", "forest.wild_wood", AS_OF).status
            is Status.DEAD)


def test_terminal_work_order_is_dead():
    service = JustificationService(fjellvik())
    wo = service.status_of("work_order", "wo_11", AS_OF)
    assert wo.status is Status.DEAD
    assert wo.cause.key == "wo_11"   # blames its own terminal failure, not the
    assert "failed" in wo.reason     # stale goal it once served: a dead root is
    assert [s.key for s in wo.chain] == ["wo_11"]  # severed from its parents


def test_unwired_asset_is_absent_and_coverage_names_it():
    service = JustificationService(fjellvik())
    orphan = service.status_of("asset", "ast_0999", AS_OF)
    assert orphan.status is Status.ABSENT
    assert orphan.label == "unwired"
    assert "serves no entry" in orphan.reason

    report = service.morning_report(AS_OF)
    assert report.coverage["asset"] == (5, 6)   # ast_0999 drags it off total
    assert report.coverage["vocab"] == (4, 4)
    assert any("ast_0999" in line for line in report.lines)


@pytest.mark.parametrize("kind", ATTACHED_KINDS)
def test_each_kind_is_fully_represented(kind):
    """No kind silently drops out of the projection."""
    service = JustificationService(fjellvik())
    assert entities_of(service, kind), f"no {kind} entities reported"
