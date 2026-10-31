"""The seams.

Two other seats are building the core in parallel:

| seat | branch | owns | seam |
|---|---|---|---|
| `core-api` | `core-api` | the audit ledger, the HTTP/SSE API, the event stream | `LedgerPort` |
| `core-recipe` | `core-recipe` | the recipe store, typed edits, the recipe hash | `RecipeStorePort` |

This module is the contract between those seats and the vocabulary seat. The
protocols below mirror what `docs/design/core-spec.md` (v2) says the core
service is, field for field, so that when the real implementations land the
vocabulary code does not have to move.

The invariants each implementation must uphold are written into the protocol
docstrings, because a protocol that only lists methods hides the rules that
matter.

A third seam appears in this seat's work and is declared here for the same
reason: `SchedulerPort`. The preview step of the Prop-maker's loop enqueues a
render job (§1.9 `Job`), and the job's enqueue is the event that must come
*after* the seal (§5.1). The scheduler belongs with the core-api seat's night
runner; until then it is stubbed in `stubs.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .models import AuditEvent, Branch, RecipeEdit, RecipeVersion

__all__ = [
    "LedgerPort",
    "RecipeStorePort",
    "SchedulerPort",
    "RenderRequest",
    "RenderJob",
]


@runtime_checkable
class LedgerPort(Protocol):
    """The audit ledger — `core-api`'s to build (branch `core-api`).

    Spec §1.8 / §1.0 / §5.1. The implementation must:

    * assign `seq` per project, monotone and **gapless** — it is the resume
      cursor and the client's `since_seq`;
    * accept appends from a **single writer** process; every state change is
      one transaction that appends the audit row and updates the projections
    * atomically, and commit **side effects only after** the event that
      justifies them exists on disk;
    * keep `prediction.sealed` **committed before** any `job.enqueued` that
      references that prediction — the ordering that makes a sealed bet
      unforgeable (§5.1). An implementation that lets a render job reference
      an unsealed prediction has broken the guarantee the whole ledger exists
      for;
    * be append-only, with exactly one exception: an owner-initiated taste
      erasure redacts that author's `taste.note.appended` payloads in the same
      transaction that appends the compensating `taste.erased` event (§1.0).
    """

    def append(self, event: AuditEvent) -> AuditEvent:
        """Append one event, assigning `seq`; return it as committed."""
        ...

    def head_seq(self) -> int:
        """The sequence number of the last committed event (0 when empty)."""
        ...

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        """Committed events in ledger order, optionally after `since_seq`."""
        ...

    def find(self, event_type: str, **match: Any) -> AuditEvent | None:
        """The most recent event of a type whose payload matches `match`."""
        ...


@runtime_checkable
class RecipeStorePort(Protocol):
    """The recipe store — `core-recipe`'s to build (branch `core-recipe`).

    Spec §1.1 / §1.2. The implementation must:

    * keep the **recipe** (typed, ours) as the source of truth and treat
      renders and meshes as caches;
    * never mutate a version in place — change is an edit, and the diff *is*
      the op list (§1.1);
    * admit an edit only if the resulting document passes **every touched
      entry's vocabulary param schema** (§1.1) and every machine-checkable
      project constraint, checked **before** any render (§1.1, D §04:2x);
    * hash each version document canonically — `root_hash` is the sha256 of the
      canonical JSON (§1.2, §1.0);
    * move a branch head **forward only** (fast-forward, never rewrite) and
      park a question rather than auto-merging two edits to the same entry
      (§1.2).
    """

    def head(self, branch_id: str) -> str:
        """The `ver_` id the branch points at."""
        ...

    def version(self, version_id: str) -> RecipeVersion:
        """A committed version and its root hash."""
        ...

    def document(self, version_id: str) -> Mapping[str, Any]:
        """The canonical recipe document of a version."""
        ...

    def apply_edit(self, edit: RecipeEdit) -> RecipeVersion:
        """Validate, apply and commit an edit; returns the new version."""
        ...

    def move_head(self, branch_id: str, version_id: str) -> Branch:
        """Fast-forward a branch head to a committed version."""
        ...

    def branches(self) -> Sequence[Branch]:
        """Every branch the store knows."""
        ...


@dataclass(frozen=True)
class RenderRequest:
    """What a render job asks for (spec §1.9 `Job.request`, seeded and bounded)."""

    branch_ref: str
    entry_paths: tuple[str, ...]
    rung: int
    resolution: str
    seed: int
    prediction_id: str | None = None

    def as_request(self) -> dict[str, Any]:
        return {
            "branch_ref": self.branch_ref,
            "entry_paths": list(self.entry_paths),
            "rung": self.rung,
            "resolution": self.resolution,
            "seed": self.seed,
        }


@dataclass
class RenderJob:
    """A render job (spec §1.9 `Job`)."""

    id: str
    request: RenderRequest
    lane: str = "gpu"
    worker: str = "thor"
    model: str | None = None
    state: str = "queued"
    created_at: str = ""
    prediction_id: str | None = None
    outputs: list[str] = field(default_factory=list)


@runtime_checkable
class SchedulerPort(Protocol):
    """The scheduler's job door — part of the core-api seat's night runner.

    Spec §1.9 / §5.1. The implementation must:

    * commit the `job.enqueued` event **after** the event that justifies the
      job exists, and in particular after the `prediction.sealed` of the bet
      the render is meant to test (§5.1);
    * price the job against the rails **before** dispatch (§1.9);
    * stamp provenance on the artifacts it produces, from the job record
      rather than from the creating process (§1.6).
    """

    def enqueue_render(self, request: RenderRequest) -> RenderJob:
        """Enqueue a render and return the job."""
        ...

    def job(self, job_id: str) -> RenderJob | None:
        """A job by id, or `None`."""
        ...
