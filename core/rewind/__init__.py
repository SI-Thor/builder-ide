"""``core.rewind`` — "rewind to here, keep these".

Build #5 of ``docs/design/vibecode-in-world.md`` (§2.5): the selection step
the cherry-pick was missing. The merge exists (``core/recipe/merge.py``,
three-way at entry granularity, conflicts park a question); the fork exists
(``lm branch``, and the recipe store's branches); what was missing was the
**selection**: a way for a human to say which of the ledger's events are the
ones to keep.

The pieces:

* :func:`parse` — the selection language: one expression over a ledger, by
  actor, time range, event kind, tile/skill id or verdict;
* :func:`select` — run it over a ledger's rows; every row that is not kept
  carries the reason it was dropped;
* :func:`fork_at_point` — cut a branch of the canon at a version. The
  canon's own branch does not move: a rewind is a fork, never a deletion;
* :func:`cherry_pick` — replay the kept events onto the fork and merge them
  through the existing three-way merge, parking any conflict rather than
  guessing;
* :func:`keep_from_round` — the same thing on the Bevy world, where the
  round's own machinery (``lm branch --drop``) and this package's replay
  (``lm run --inject``) are made to agree.

Nothing in this package deletes anything. The ledger keeps every row it had,
the canon keeps every version, and the fork is a new branch beside them.
"""

from .bevy import (
    BevyError,
    BevyKeep,
    BevyWorld,
    DiffResult,
    ReplayResult,
    injection_lines,
    keep_from_round,
)
from .fork import (
    RewindPoint,
    fork_at_point,
    main_branch,
    point_at_version,
    points,
)
from .ledger import (
    EPOCH,
    TICK,
    Ledger,
    LedgerRow,
    read_bevy_dump,
    read_bevy_header,
    read_core_ledger,
    read_world_ledger,
)
from .report import Outcome, Parked, RewindReport
from .replay import (
    CherryPick,
    LedgerQuestions,
    cherry_pick,
    events_to_ledger,
    replay_kept,
)
from .snapshot import (
    Placement,
    ReappliableOp,
    RewindPlan,
    nearest_snapshot_at_or_before,
    read_manifests,
    read_placements,
    rewind_plan,
    rewind_plan_from_store,
)
from .selection import (
    FIELDS,
    NUMERIC_FIELDS,
    Selection,
    SelectionError,
    SelectionResult,
    parse,
    select,
)

__all__ = [
    "BevyError",
    "BevyKeep",
    "BevyWorld",
    "CherryPick",
    "DiffResult",
    "EPOCH",
    "FIELDS",
    "Ledger",
    "LedgerQuestions",
    "LedgerRow",
    "NUMERIC_FIELDS",
    "Outcome",
    "Parked",
    "ReplayResult",
    "RewindPlan",
    "RewindPoint",
    "RewindReport",
    "Selection",
    "SelectionError",
    "SelectionResult",
    "TICK",
    "cherry_pick",
    "events_to_ledger",
    "fork_at_point",
    "injection_lines",
    "keep_from_round",
    "main_branch",
    "parse",
    "point_at_version",
    "points",
    "read_bevy_dump",
    "read_bevy_header",
    "read_core_ledger",
    "Placement",
    "ReappliableOp",
    "nearest_snapshot_at_or_before",
    "read_manifests",
    "read_placements",
    "rewind_plan",
    "rewind_plan_from_store",
    "read_world_ledger",
    "replay_kept",
    "select",
]
