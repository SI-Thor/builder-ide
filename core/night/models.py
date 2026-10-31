"""The records the night runner owns (core-spec v2 §1.9).

**These records live in :mod:`core.records`** — one definition each, shared
with every other seat, because the night runner, the API half, the recipe
store and the vocabulary all write the same Task/Job/Night rows. This module
re-exports them so ``from core.night.models import Night`` still works and
``core.night.models.Night is core.records.Night`` is true.

The reconciliation this required is recorded in INTEGRATION.md: the API
half's ``AuditEvent`` (optional ``seq`` until commit, the ``refused`` flag)
is the richer one and won; ``Task.state`` gained the owner-kill ``dropped``
state the justification layer needs; everything else agreed field for field.
"""

from __future__ import annotations

from core.records import (
    Actor,
    ActorKind,
    AuditEvent,
    IterationPolicy,
    Job,
    JobState,
    Night,
    NightState,
    NightStatus,
    Rail,
    Task,
    TaskState,
)

__all__ = [
    "Actor",
    "ActorKind",
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
