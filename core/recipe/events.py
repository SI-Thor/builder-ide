"""The closed set of audit event types — core-spec v2 §1.8.

New types are a schema change. The recipe store emits only from the recipe
group; the API half owns the rest.
"""

from __future__ import annotations

__all__ = ["EVENT_TYPES", "RECIPE_EVENT_TYPES", "QUESTION_EVENT_TYPES", "DAYTIME_EVENT_TYPES"]

WORK_ORDER_EVENT_TYPES = frozenset(
    {
        "wo.filed",
        "wo.compiled",
        "wo.questioned",
        "wo.confirmed",
        "wo.queued",
        "wo.attempt.started",
        "wo.attempt.delivered",
        "wo.testing",
        "wo.landed",
        "wo.kept",
        "wo.rejected",
        "wo.parked",
        "wo.resumed",
        "wo.failed",
        "wo.cancelled",
    }
)

RECIPE_EVENT_TYPES = frozenset(
    {
        "edit.proposed",
        "edit.validated",
        "version.committed",
        "branch.created",
        "branch.head.moved",
        "branch.rejected",
        "branch.proposed",
        "constraint.failed",
    }
)

PREDICTION_EVENT_TYPES = frozenset({"prediction.sealed", "prediction.scored"})

TASTE_EVENT_TYPES = frozenset({"taste.note.appended", "taste.erased", "taste.ratified"})

VOCABULARY_EVENT_TYPES = frozenset({"vocab.word.added", "vocab.word.status", "vocab.call"})

NIGHT_EVENT_TYPES = frozenset(
    {
        "night.started",
        "night.stopped",
        "night.preflight",
        "night.tick",
        "night.task.created",
        "night.task.state",
        "line.spoken",
    }
)

DAYTIME_EVENT_TYPES = frozenset(
    {
        "day.world.opened",
        "day.tick",
        "day.change",
        "day.yielded",
    }
)

SCHEDULER_EVENT_TYPES = frozenset(
    {
        "sched.model.load",
        "sched.model.unload",
        "sched.demote",
        "job.enqueued",
        "job.started",
        "job.done",
        "job.requeued",
        "render.completed",
        "scene.loaded",
        "scene.evicted",
        "power.mode.set",
    }
)

CRITIC_EVENT_TYPES = frozenset({"critic.verdict"})

BUDGET_EVENT_TYPES = frozenset({"budget.spend", "budget.threshold", "kill.switch"})

ASSET_EVENT_TYPES = frozenset({"asset.created", "asset.licence.checked"})

QUESTION_EVENT_TYPES = frozenset({"question.parked", "question.answered", "assumption.recorded"})

CONTINUITY_EVENT_TYPES = frozenset({"model.change.noticed"})

CLIENT_EVENT_TYPES = frozenset({"client.attach", "client.detach"})

SYSTEM_EVENT_TYPES = frozenset(
    {"core.boot", "core.recovered", "projection.rebuilt", "integrity.failure", "call.refused"}
)

EVENT_TYPES = frozenset(
    WORK_ORDER_EVENT_TYPES
    | RECIPE_EVENT_TYPES
    | PREDICTION_EVENT_TYPES
    | TASTE_EVENT_TYPES
    | VOCABULARY_EVENT_TYPES
    | NIGHT_EVENT_TYPES
    | DAYTIME_EVENT_TYPES
    | SCHEDULER_EVENT_TYPES
    | CRITIC_EVENT_TYPES
    | BUDGET_EVENT_TYPES
    | ASSET_EVENT_TYPES
    | QUESTION_EVENT_TYPES
    | CONTINUITY_EVENT_TYPES
    | CLIENT_EVENT_TYPES
    | SYSTEM_EVENT_TYPES
)
