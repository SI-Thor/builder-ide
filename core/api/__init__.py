"""STUB — owned by the `core-api` seat (sibling branch `core-api`).

Minimal, read-only stand-ins for the spec §1.3/§1.6/§1.9 records the
justification layer (`core.justification`) reads: WorkOrder, Task, Asset and
Actor. Field names follow spec v2; only the fields justification actually
reads are modelled, each marked below. Replace wholesale on merge — see
core/STUBS.md for the full stub inventory and the contract the real models
must keep.

Stub-only deltas (flagged for the spec, listed in STUBS.md):

- ``Task.state`` gains ``"dropped"`` — the owner's morning "drop this goal"
  decision. The spec's ``cut`` is budget-driven and requeues; it is not an
  owner kill.
- ``WorkOrder.serves`` — the task/goal the order is for. The spec relates a
  WO to the plan only through the context packet; justification needs the
  explicit link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: spec §1.3 WoState — plus nothing (stub keeps the full closed list so
#: illegal states fail loudly in tests).
WoState = Literal[
    "compiling", "questioned", "draft", "queued", "building", "testing",
    "landed", "kept", "rejected", "parked", "failed", "cancelled",
]

#: spec §1.9 Task.state — plus the stub-only owner-kill terminal "dropped".
TaskState = Literal[
    "slated", "queued", "running", "kept", "reverted", "parked", "cut",
    "dropped",
]


@dataclass
class Actor:  # spec §1.1 (RecipeEdit.author)
    kind: Literal["character", "engineer", "owner", "core", "critic",
                  "scheduler", "client"]
    id: str
    via: str | None = None       # word | wo_ id — spec Actor.via


@dataclass
class WorkOrder:  # spec §1.3 (subset justification reads)
    id: str                      # wo_…
    at: str
    filed_by: Actor
    title: str                   # "Rope bridge, south span"
    state: WoState
    serves: str | None = None    # STUB-ADDED: task_ id of the goal it is for
    vocabulary_gap: dict | None = None   # {"word": "bridge.rope", …} (spec §1.3)


@dataclass
class Task:  # spec §1.9 (subset justification reads)
    id: str                      # task_…
    author: str                  # "casey" | "magnus"
    owner_character: str
    intention: str               # "Forest the east slope, keep the oak" — the goal text
    state: TaskState
    branches: list[str] = field(default_factory=list)   # br_ ids (spec Task.branches)
    slated_at: str | None = None          # date the slate carried it
    review_by: str | None = None          # STUB-ADDED: soft expiry for the GOAL (YYYY-MM-DD)


@dataclass
class Asset:  # spec §1.6 (subset justification reads)
    id: str                      # ast_…
    kind: Literal["mesh", "texture", "material", "cad_part", "motion_clip",
                  "audio"]
    spdx: str = "MIT"            # Licence.spdx — presence matters, terms don't, here
