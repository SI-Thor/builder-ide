"""Shared test helpers for the night runner's suite.

Test-only code lives here, not in the production package (superpowers'
test-driven-development rules).
"""

from __future__ import annotations

import pytest

from core.night.ledger import InMemoryLedger
from core.night.models import Actor
from core.night.projection import NightProjection

CORE = Actor(kind="core", id="night-runner")
SCHEDULER = Actor(kind="scheduler", id="night-runner")

NIGHT = "night_2026-10-30"


class NightBuilder:
    """Builds a night's worth of events, so the fold can be tested directly."""

    def __init__(self, ledger: InMemoryLedger, night_id: str = NIGHT) -> None:
        self.ledger = ledger
        self.night_id = night_id

    def _append(self, type: str, payload: dict, at: str | None = None):
        return self.ledger.append(
            type=type,
            actor=CORE,
            subject={"entity_kind": "night", "entity_id": self.night_id},
            payload=payload,
            at=at,
        )

    def start(self, at: str = "2026-10-30T21:14:00Z", **overrides) -> "NightBuilder":
        payload = {
            "night_id": self.night_id,
            "rails": {"gpu_minutes": 360.0, "hosted_cents": 0, "wall_minutes": 560.0},
            "load_budget": {"trellis2": 1},
            "power_mode": 0,
            "batch_start": "both",
            "detach_deadline": "2026-10-30T21:44:00Z",
        }
        payload.update(overrides)
        self._append("night.started", payload, at=at)
        return self

    def preflight(self, at: str = "2026-10-30T21:14:10Z", **payload) -> "NightBuilder":
        body = {
            "lane_free": True,
            "lane_load": 0.3,
            "queue_depth": 2,
            "telemetry": True,
            "detach_deadline": "2026-10-30T21:44:00Z",
            "proposal": None,
        }
        body.update(payload)
        self._append("night.preflight", body, at=at)
        return self

    def tick(self, at: str, kind: str = "wall", **extra) -> "NightBuilder":
        payload = {"at": at, "kind": kind}
        payload.update(extra)
        self._append("night.tick", payload, at=at)
        return self

    def task(self, task_id: str, at: str = "2026-10-30T21:15:00Z", **fields) -> "NightBuilder":
        task = {
            "id": task_id,
            "night": self.night_id,
            "author": "casey",
            "owner_character": "prop-maker",
            "intention": fields.pop("intention", "Forest the east slope, keep the oak"),
            "recipe_scope": [],
            "cost_estimate": {"gpu_minutes": 30.0, "hosted_cents": 0, "wall_minutes": 45.0},
            "rail": {"gpu_minutes": 40.0, "hosted_cents": 0, "wall_minutes": 60.0},
            "state": "queued",
            "predictions": [],
            "branches": [],
        }
        task.update(fields)
        self._append(
            "night.task.created", {"task": task}, at=at
        )
        return self

    def task_state(
        self, task_id: str, state: str, at: str = "2026-10-30T21:20:00Z", reason: str | None = None
    ) -> "NightBuilder":
        payload = {"task_id": task_id, "state": state}
        if reason:
            payload["reason"] = reason
        self._append("night.task.state", payload, at=at)
        return self

    def spend(self, axis: str, amount: float, at: str = "2026-10-30T21:20:00Z") -> "NightBuilder":
        self._append(
            "budget.spend",
            {"axis": axis, "amount": amount, "scope": "night"},
            at=at,
        )
        return self

    def model_load(self, model: str, at: str = "2026-10-30T21:20:00Z") -> "NightBuilder":
        self._append("sched.model.load", {"model": model}, at=at)
        return self

    def verdict(
        self,
        prediction_id: str = "pr_0001",
        at: str = "2026-10-30T21:30:00Z",
        degraded: bool = False,
    ) -> "NightBuilder":
        self._append(
            "critic.verdict",
            {
                "prediction_id": prediction_id,
                "verdict": "hit",
                "degraded": degraded,
                "summary": "verdict@scripted" if degraded else "verdict@scripted",
            },
            at=at,
        )
        return self

    def stop(self, at: str = "2026-10-30T06:00:00Z") -> "NightBuilder":
        self._append("night.stopped", {"status": None}, at=at)
        return self

    def projection(self) -> NightProjection:
        return NightProjection(self.ledger.events())


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def night(ledger: InMemoryLedger) -> NightBuilder:
    return NightBuilder(ledger)
