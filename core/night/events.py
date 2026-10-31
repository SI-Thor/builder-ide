"""The closed set of audit event types (core-spec v2 §1.8).

The set is closed: a new type is a schema change. The groups below are the
spec's own (§1.8's groups, verbatim), kept because they name which rows this
seat writes; the set itself is :data:`core.records.EVENT_TYPES` — the one
copy every seat shares, so no two packages can drift apart on the one list
they all append to.
"""

from __future__ import annotations

from core.records import EVENT_TYPES as RECORDS_EVENT_TYPES

__all__ = [
    "EVENT_TYPES",
    "NIGHT_RUNNER_EVENT_TYPES",
    "DAYTIME_EVENT_TYPES",
    "TILE_EVENT_TYPES",
]

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

#: The tile seat's four types (core/tiles/events.py). Mirrored here so every
#: reader of the log agrees on the closed set (§1.8).
TILE_EVENT_TYPES = frozenset(
    {"tile.authored", "tile.retired", "tile.played", "tile.retrained"}
)

EVENT_TYPES = (
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
    | TILE_EVENT_TYPES
)

#: The types this seat (the night runner) writes. Everything else in the log
#: belongs to another seat — the recipe store, the vocabulary, the API half.
NIGHT_RUNNER_EVENT_TYPES = frozenset(
    NIGHT_EVENT_TYPES
    | SCHEDULER_EVENT_TYPES
    | BUDGET_EVENT_TYPES
    | CLIENT_EVENT_TYPES
    | SYSTEM_EVENT_TYPES
    | QUESTION_EVENT_TYPES
    | PREDICTION_EVENT_TYPES
    | CRITIC_EVENT_TYPES
    | CONTINUITY_EVENT_TYPES
    | ASSET_EVENT_TYPES
)

#: The union of the groups above must be the shared closed set — the merge
#: made them one list, and this pin keeps a future group edit from quietly
#: forking the runner's view of the log it appends to.
#:
#: The comparison is against ``core.records``' copy, under a different
#: name: the local ``EVENT_TYPES`` is the union itself, so comparing the
#: union to itself would pin nothing.
assert (
    EVENT_TYPES
    == RECORDS_EVENT_TYPES
), "core.night's event groups have drifted from core.records.EVENT_TYPES"
