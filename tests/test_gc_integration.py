"""The end-to-end walk: a confirmed work order is a gc contract, the night
checkpoints the burn, gc's 80% stop line cuts the task, the morning closes
the contract with a three-valued verdict, and the reputation reads back.

This is the whole wiring in one test, against the **real gc binary** — the
numbers below are gc's, read out of gc's own ledger, not asserted from
memory. When the gc binary is not built on this box the test skips with a
stated reason, so the suite is green with and without gc.

    /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
        -p no:cacheprovider tests/test_gc_integration.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.events import owner_actor
from core.models import Budget, Estimate, Origin, Rail
from core.night.clock import ScriptedClock
from core.night.executor import ScriptedExecutor, ScriptedTask
from core.night.ledger import InMemoryLedger
from core.night.models import Task
from core.night.runner import NightRunner
from core.svc.gc_night import GcNightSeam
from core.svc.nights import NightsService
from core.svc.report import ReportBuilder
from core.svc.tasks import TasksService
from core.svc.work_orders import WorkOrdersService
from tests.conftest import OWNER

gc_bridge = pytest.importorskip(
    "core.svc.gc_bridge",
    reason="the gc bridge half is not landed on this branch yet",
)

#: The seat that takes the order. gc's bid and its award carry this name.
SEAT = "architect"

#: The order's two price lines, in wall-minutes: 10 + 10 = 20. gc holds the
#: seat to a bid of 1.25 x that (25 min) until the seat has a track record,
#: and its stop line is 80% of the bid — 20 min.
ESTIMATE_MIN = 20.0

#: The attempt's actual cost: past the 80% stop line (24 of 25 min).
BURN_MIN = 24.0


def _gc_binary() -> Path | None:
    """The gc binary, found the way the bridge finds it."""
    env = os.environ.get(gc_bridge.GC_BIN_ENV)
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    candidate = Path(__file__).resolve().parents[1] / "tools" / "gc" / "target" / "release" / "gc"
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


GC_BINARY = _gc_binary()


def _gc_rows(core) -> list[dict]:
    """gc's own ledger, oldest first — the record of what really happened."""
    path = core.gc.ledger_path
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _rows_of_kind(rows: list[dict], kind: str) -> list[dict]:
    return [row.get("body") or {} for row in rows if row.get("kind") == kind]


@pytest.mark.skipif(GC_BINARY is None,
                    reason="the gc binary is not built on this box "
                           "(cargo build --release in tools/gc)")
def test_the_whole_walk_against_the_real_gc_binary(core, settings, client):
    """confirm → night → checkpoint → the 80% stop → close → reputation."""
    # ---------------------------------------------------------------- the goal
    tasks = TasksService(core)
    task = tasks.create(author="casey", owner_character="prop-maker",
                        intention="Forest the east slope, keep the oak")

    nights = NightsService(core, core.settings)
    night_id = nights.start(owner_actor("casey"))["night"]["id"]

    # -------------------------------------------------------- the work order
    svc = WorkOrdersService(core)
    budget = Budget(night=night_id,
                    per_order=Rail(gpu_minutes=20.0, hosted_cents=0, wall_minutes=40.0))
    filed = svc.file(
        owner_actor("casey"), Origin(channel="text", packet="pk_1"),
        "weather the crates", goal="weather them to a weathered tone",
        serves=task.id, budget=budget,
    )
    draft = svc.compile_draft(
        filed.id, title="weather the crates", goal="weather them to a weathered tone",
        targets=["props.harbor.crates"],
        acceptance=[{"kind": "test_suite", "spec": {"suite": "default"}}],
        budget=budget,
        estimate=Estimate(build_verify=Rail(gpu_minutes=10.0, hosted_cents=0, wall_minutes=10.0),
                          generate_test=Rail(gpu_minutes=10.0, hosted_cents=0, wall_minutes=10.0),
                          basis="estimate"),
        confirm_line=("weather the crates to a weathered tone · "
                      "build/verify: ~0.2 GPU-h · generate/test: ~0.2 GPU-h"),
    )
    svc.confirm(draft.id, owner_actor("casey"), "go")

    bridge = core.gc
    assert bridge is not None, "the core carries a gc bridge"
    assert bridge.ledger_path == settings.home / "gc-ledger.jsonl"

    # The contract exists, keyed by the work order's id.
    job_id = bridge.job_id_for(draft.id)
    if job_id is None:
        pytest.skip("the gc binary on this box does not speak --external-id/--json yet")
    assert job_id

    job_body = _rows_of_kind(_gc_rows(core), "job.new")[0]
    assert job_body["external_id"] == draft.id
    assert job_body["estimate_min"] == ESTIMATE_MIN
    assert job_body["budget_min"] == 40.0        # the per_order rail is the ceiling
    assert job_body["deadline_min"] == 560.0     # the night's rails are the job-time
    assert job_body["class"] == task.kind        # the serving task's kind
    assert "gc class:" in job_body["scope"]      # the ledger says where it came from

    # ------------------------------------------------------------- the seat
    svc.start_attempt(draft.id, SEAT)
    award = _rows_of_kind(_gc_rows(core), "award")
    assert award, "the contract is awarded to the seat that started the attempt"
    assert award[0]["sub"] == SEAT
    bids = _rows_of_kind(_gc_rows(core), "bid.new")
    assert bids and bids[0]["sub"] == SEAT

    # ------------------------------------------------------------- the night
    # The gc bid is the rail under test here, so the task carries no rail of
    # its own (a zero rail is skipped by the runner's admission check).
    executor = ScriptedExecutor({
        task.id: ScriptedTask(gpu_minutes=10.0, hosted_cents=0, wall_minutes=BURN_MIN,
                              actual_wall_minutes=BURN_MIN),
    })
    ledger = InMemoryLedger()
    runner = NightRunner(
        ledger, executor, night_id=night_id,
        rails=Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0),
        clock=ScriptedClock("2026-10-30T21:14:00Z"),
        gc=GcNightSeam(core),
    )
    runner.start([Task(id=task.id, intention=task.intention,
                       cost_estimate=task.cost_estimate, rail=Rail())])
    runner.run()
    runner.stop()

    # The burn was checkpointed to gc, at the number the attempt cost.
    checkpoints = _rows_of_kind(_gc_rows(core), "checkpoint")
    assert checkpoints, "the night's burn was reported to gc"
    assert checkpoints[-1]["crew_used_min"] == BURN_MIN
    assert checkpoints[-1]["stop_required"] is True

    # The stop line cut the task — a rail event, with gc's reason on it.
    states = [ev for ev in ledger.events() if ev.type == "night.task.state"]
    cut = next(ev for ev in states if ev.payload.get("state") == "cut")
    reason = cut.payload["reason"]
    assert "stop line" in reason
    assert "% of the bid" in reason
    assert "re-scope" in reason

    # ------------------------------------------------------------- the close
    # The night spent what it spent; the order ends without a pass.
    svc.record_spend(draft.id, night_id,
                     {"gpu_minutes": 10.0, "hosted_cents": 0, "wall_minutes": BURN_MIN})
    svc.fail(draft.id, "the night cut the attempt at the contractor's stop line",
             to_state="failed")

    doc = ReportBuilder(core).build(night_id)["doc"]
    contracts = doc["gc"]["contracts"]
    assert len(contracts) == 1
    closed = contracts[0]
    assert closed["work_order"] == draft.id
    assert closed["job"] == job_id
    assert closed["seat"] == SEAT
    assert closed["verdict"] == "fail"      # three-valued: landed/kept, failed/rejected, cancelled
    assert closed["crew_min"] == BURN_MIN

    close_rows = _rows_of_kind(_gc_rows(core), "close")
    assert close_rows, "the contract was closed with gc"
    assert close_rows[-1]["actual_crew_min"] == BURN_MIN
    assert close_rows[-1]["acceptance_verdict"] == "fail"

    # ---------------------------------------------------------- the reputation
    response = client.get("/v1/gc/reputation", headers=OWNER)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    row = next(r for r in body["reputation"] if r["seat"] == SEAT)
    assert row["class"] == task.kind
    assert row["jobs"] == 1
    assert row["line"].startswith(f"{SEAT}: ")
    # the numbers are gc's: the reputation score is in gc's own range
    assert 0.0 <= row["reputation"] <= 100.0
