"""The projection: the night rebuilt by folding the audit log.

§1.0 makes the audit table the source of truth and every other table a
projection rebuilt by folding it. The night runner leans on that harder than
any other seat: the status line, the cut and the morning report are all folds,
which is what makes them survive the failure they describe (§3.4, §5.4).
"""

from __future__ import annotations

from core.night.ledger import InMemoryLedger
from core.night.models import Actor, Rail
from core.night.projection import NightProjection

CORE = Actor(kind="core", id="night-runner")


def test_a_folded_projection_rebuilds_the_night_with_its_rails():
    ledger = InMemoryLedger()
    ledger.append(
        type="night.started",
        actor=CORE,
        subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
        payload={
            "night_id": "night_2026-10-30",
            "rails": {"gpu_minutes": 360.0, "hosted_cents": 0, "wall_minutes": 560.0},
            "load_budget": {"trellis2": 1},
            "power_mode": 0,
            "batch_start": "both",
            "detach_deadline": "2026-10-30T21:44:00Z",
        },
    )
    projection = NightProjection(ledger.events())
    assert projection.night is not None
    assert projection.night.id == "night_2026-10-30"
    assert projection.night.rails == Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0)
    assert projection.night.load_budget == {"trellis2": 1}


def test_the_fold_sums_the_spend_against_the_night():
    ledger = InMemoryLedger()
    for amount in (10.0, 15.5):
        ledger.append(
            type="budget.spend",
            actor=CORE,
            subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
            payload={"axis": "gpu_minutes", "amount": amount, "scope": "night"},
        )
    ledger.append(
        type="budget.spend",
        actor=CORE,
        subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
        payload={"axis": "hosted_cents", "amount": 7, "scope": "night"},
    )
    projection = NightProjection(ledger.events())
    assert projection.spend == Rail(gpu_minutes=25.5, hosted_cents=7, wall_minutes=0.0)


def test_the_fold_counts_the_model_loads():
    ledger = InMemoryLedger()
    for model in ("trellis2", "trellis2", "sd-material"):
        ledger.append(
            type="sched.model.load",
            actor=CORE,
            subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
            payload={"model": model},
        )
    projection = NightProjection(ledger.events())
    assert projection.model_loads == {"trellis2": 2, "sd-material": 1}


def test_the_fold_knows_whether_the_client_is_attached():
    ledger = InMemoryLedger()
    ledger.append(
        type="client.attach",
        actor=CORE,
        subject={"entity_kind": "client", "entity_id": "proart"},
        payload={"client": "proart"},
    )
    assert NightProjection(ledger.events()).client_state() == "attached"

    ledger.append(
        type="client.detach",
        actor=CORE,
        subject={"entity_kind": "client", "entity_id": "proart"},
        payload={"client": "proart"},
    )
    assert NightProjection(ledger.events()).client_state() == "detached"


def test_the_fold_keeps_the_ticks_in_order():
    ledger = InMemoryLedger()
    for at in ("2026-10-30T21:20:00Z", "2026-10-30T21:30:00Z"):
        ledger.append(
            type="night.tick",
            actor=CORE,
            subject={"entity_kind": "night", "entity_id": "night_2026-10-30"},
            payload={"at": at, "kind": "wall"},
        )
    projection = NightProjection(ledger.events())
    assert [tick.payload["at"] for tick in projection.ticks] == [
        "2026-10-30T21:20:00Z",
        "2026-10-30T21:30:00Z",
    ]


def test_the_fold_collects_the_parked_questions_and_the_assumptions():
    ledger = InMemoryLedger()
    ledger.append(
        type="question.parked",
        actor=CORE,
        subject={"entity_kind": "question", "entity_id": "q_0001"},
        payload={"question_id": "q_0001", "name": "keep the oak?", "blocking": True},
    )
    ledger.append(
        type="assumption.recorded",
        actor=CORE,
        subject={"entity_kind": "question", "entity_id": "q_0001"},
        payload={"question_id": "q_0001", "assumption": "keep it", "branch": "br_07f2"},
    )
    projection = NightProjection(ledger.events())
    assert [question["question_id"] for question in projection.questions] == ["q_0001"]
    assert projection.assumptions[0]["assumption"] == "keep it"
    assert projection.questions[0]["assumptions"] == ["keep it"]


def test_the_fold_collects_the_sealed_bets_and_their_verdicts():
    ledger = InMemoryLedger()
    ledger.append(
        type="prediction.sealed",
        actor=CORE,
        subject={"entity_kind": "prediction", "entity_id": "pr_0001"},
        payload={
            "prediction_id": "pr_0001",
            "builder": "prop-maker",
            "claim_type": "shadow_count",
            "confidence": "guess",
            "basis": "0 observations",
        },
    )
    ledger.append(
        type="prediction.scored",
        actor=CORE,
        subject={"entity_kind": "prediction", "entity_id": "pr_0001"},
        payload={"prediction_id": "pr_0001", "verdict": "hit"},
    )
    projection = NightProjection(ledger.events())
    assert projection.predictions["pr_0001"]["verdict"] == "hit"
    assert projection.predictions["pr_0001"]["builder"] == "prop-maker"


def test_a_state_change_without_a_reason_clears_the_previous_reason():
    """The reason belongs to the state, not to the task forever."""
    ledger = InMemoryLedger()
    ledger.append(
        type="night.task.created",
        actor=CORE,
        subject={"entity_kind": "task", "entity_id": "task_0001"},
        payload={
            "task": {
                "id": "task_0001",
                "night": "night_2026-10-30",
                "author": "casey",
                "owner_character": "prop-maker",
                "intention": "Rope the jetty",
                "recipe_scope": [],
                "cost_estimate": {"gpu_minutes": 30.0, "hosted_cents": 0, "wall_minutes": 45.0},
                "rail": {"gpu_minutes": 40.0, "hosted_cents": 0, "wall_minutes": 60.0},
                "state": "queued",
                "predictions": [],
                "branches": [],
            }
        },
    )
    ledger.append(
        type="night.task.state",
        actor=CORE,
        subject={"entity_kind": "task", "entity_id": "task_0001"},
        payload={
            "task_id": "task_0001",
            "state": "queued",
            "reason": "re-queued after the restart",
        },
    )
    ledger.append(
        type="night.task.state",
        actor=CORE,
        subject={"entity_kind": "task", "entity_id": "task_0001"},
        payload={"task_id": "task_0001", "state": "kept"},
    )
    projection = NightProjection(ledger.events())
    assert projection.reason_for("task_0001") is None


def test_the_fold_keeps_the_failure_cards():
    ledger = InMemoryLedger()
    ledger.append(
        type="job.done",
        actor=CORE,
        subject={"entity_kind": "job", "entity_id": "job_0001"},
        payload={
            "job_id": "job_0001",
            "task_id": "task_0001",
            "outcome": "failed",
            "reason": "hollow mesh from the image-to-3D model",
            "artifact": "artifacts/ab/ab1234.png",
        },
    )
    projection = NightProjection(ledger.events())
    assert len(projection.failures) == 1
    assert projection.failures[0]["reason"] == "hollow mesh from the image-to-3D model"
    assert projection.failures[0]["artifact"] == "artifacts/ab/ab1234.png"
