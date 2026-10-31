"""The records the night runner owns (core-spec v2 §1.9).

These are the scheduler's records: the night, the tasks it runs, the jobs it
dispatches and the three-axis rail they are measured against. They are
projections — every one of them is rebuildable by folding the audit log
(§1.0, §5), which is why they carry no state of their own beyond what the
log says.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Actor",
    "AuditEvent",
    "IterationPolicy",
    "Rail",
    "Task",
    "TaskState",
    "Job",
    "JobState",
    "Night",
    "NightState",
    "NightStatus",
]


class Actor(BaseModel):
    """Who did it (§1.8). Every event carries one."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["owner", "character", "engineer", "critic", "core", "scheduler", "client"]
    id: str
    via: str | None = None


class AuditEvent(BaseModel):
    """One row of the one log (§1.8)."""

    seq: int
    id: str
    at: str
    actor: Actor
    type: str
    subject: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    artifact: dict | None = None


class Rail(BaseModel):
    """Three axes of spend: lane time, hosted cents and wall clock (§1.3, §5.5).

    GPU-minutes come from the model registry's measured cost table, not from
    wall clock, so a cheap CPU-lane hour does not eat the GPU bar (§5.5).
    """

    gpu_minutes: float = 0.0
    hosted_cents: int = 0
    wall_minutes: float = 0.0

    def add(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=self.gpu_minutes + other.gpu_minutes,
            hosted_cents=self.hosted_cents + other.hosted_cents,
            wall_minutes=self.wall_minutes + other.wall_minutes,
        )

    def subtract(self, other: "Rail") -> "Rail":
        return Rail(
            gpu_minutes=self.gpu_minutes - other.gpu_minutes,
            hosted_cents=self.hosted_cents - other.hosted_cents,
            wall_minutes=self.wall_minutes - other.wall_minutes,
        )

    def fits(self, ask: "Rail") -> bool:
        """True when ``ask`` fits inside this rail (used as a ceiling)."""
        return (
            ask.gpu_minutes <= self.gpu_minutes
            and ask.hosted_cents <= self.hosted_cents
            and ask.wall_minutes <= self.wall_minutes
        )

    @property
    def is_zero(self) -> bool:
        return (
            self.gpu_minutes == 0.0
            and self.hosted_cents == 0
            and self.wall_minutes == 0.0
        )


TaskState = Literal["slated", "queued", "running", "kept", "reverted", "parked", "cut"]

JobState = Literal["queued", "running", "done", "failed", "requeued"]

NightState = Literal["starting", "running", "stopping", "stopped"]

NightStatus = Literal["ran as planned", "ran short", "ran degraded", "did not run"]


class IterationPolicy(BaseModel):
    """How deep the night goes on one goal — N, K and ε.

    It is a **rail**, not a preference: the budget can cut a loop short, and
    the morning says where it was cut. It rides on the night (the night's
    ``iteration``), so the depth the night ran at is foldable from the log
    like everything else.
    """

    variants_per_round: int = Field(default=3, ge=1)
    max_rounds: int = Field(default=3, ge=1)
    min_gain: float = Field(default=0.02, ge=0.0)


class Task(BaseModel):
    """One unit of the owner's plan (§1.9).

    A task exists before any night (RV patch 11): ``night`` is ``None`` and
    ``state`` is ``"slated"`` on the plan slate, which is why ``cost_estimate``
    — the *ask* — is stored, so the morning can name what was cut (X C11).
    """

    id: str
    night: str | None = None
    author: str = "casey"
    ends_at: str | None = None
    owner_character: str = "prop-maker"
    intention: str
    recipe_scope: list[str] = Field(default_factory=list)
    cost_estimate: Rail = Field(default_factory=Rail)
    rail: Rail = Field(default_factory=Rail)
    state: TaskState = "slated"
    predictions: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)


class Job(BaseModel):
    """One dispatched unit of work on a lane (§1.9)."""

    id: str
    lane: Literal["cpu", "gpu"]
    worker: str = "thor"
    model: str | None = None
    request: dict = Field(default_factory=dict)
    cost_estimate: Rail = Field(default_factory=Rail)
    claim_token: str = ""
    lease_until: str | None = None
    heartbeat_at: str | None = None
    power_mode: int | None = None
    stage_cache: Literal["hit", "miss", "partial"] | None = None
    state: JobState = "queued"
    outputs: list[str] = Field(default_factory=list)
    task_id: str | None = None


class Night(BaseModel):
    """One night: its rails, its load budget and its computed status (§1.9).

    ``status`` is **computed** at stop from the heartbeats and the admission
    waits — never narrated by whoever is awake to write it (§3.4).
    """

    id: str
    started_at: str
    stopped_at: str | None = None
    rails: Rail = Field(default_factory=Rail)
    load_budget: dict[str, int] = Field(default_factory=dict)
    power_mode: int = 0
    batch_start: Literal["detach", "deadline", "both"] = "both"
    detach_deadline: str | None = None
    state: NightState = "starting"
    status: NightStatus | None = None
    report: str | None = None
    #: The night's depth policy — how many variants per round, how many
    #: rounds, and the ε the loop stops below (the iterator's rails).
    iteration: IterationPolicy | None = None
