"""In-memory stubs for the three seams.

These stand in for work that is landing on other branches right now:

* `InMemoryLedger` — `core-api`'s audit ledger (branch `core-api`).
* `InMemoryRecipeStore` — `core-recipe`'s recipe store (branch `core-recipe`).
* `InMemoryScheduler` — the scheduler's job door, part of the core-api seat's
  night runner.

They are not toys: they enforce the rules that make the vocabulary seat's
guarantees mean anything — a gapless sequence, an append-only log, and the
**sealed-before-render ordering** of §5.1. When the real implementations land,
these are replaced by the real thing and the tests keep their meaning.

The stub recipe store keeps the recipe document as a plain canonical-JSON
mapping rather than a typed model: the document and its hash are
`core-recipe`'s to own, and a plain mapping is what a sha256 is taken over.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Sequence

from .hashing import content_hash, short_hash
from .models import Actor, AuditEvent, Branch, Op, RecipeEdit, RecipeVersion
from .ports import RenderJob, RenderRequest

__all__ = [
    "LedgerError",
    "InMemoryLedger",
    "InMemoryRecipeStore",
    "InMemoryScheduler",
]


class LedgerError(Exception):
    """The ledger refused an append. Carries a closed reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class InMemoryLedger:
    """A single-writer, append-only audit log.

    Implements `LedgerPort` (see `ports.py` for the invariants the real
    implementation owes).
    """

    def __init__(self, *, events: Sequence[AuditEvent] = ()) -> None:
        self._events: list[AuditEvent] = []
        self._by_id: dict[str, AuditEvent] = {}
        for event in events:
            self.append(event)

    # -- LedgerPort ------------------------------------------------------------

    def append(self, event: AuditEvent) -> AuditEvent:
        existing = self._by_id.get(event.id)
        if existing is not None:
            # Idempotency (§5.3): the same event twice is one event.
            if existing.payload == event.payload and existing.type == event.type:
                return existing
            raise LedgerError("duplicate_event_id", f"{event.id} already exists")

        if event.type == "job.enqueued":
            self._require_sealed_before_render(event)

        committed = event.model_copy(update={"seq": self.head_seq() + 1})
        self._events.append(committed)
        self._by_id[committed.id] = committed
        return committed

    def head_seq(self) -> int:
        return self._events[-1].seq if self._events else 0

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        wanted = set(types) if types is not None else None
        return [
            event
            for event in self._events
            if (since_seq is None or event.seq > since_seq)
            and (wanted is None or event.type in wanted)
        ]

    def find(self, event_type: str, **match: Any) -> AuditEvent | None:
        for event in reversed(self._events):
            if event.type != event_type:
                continue
            if all(event.payload.get(key) == value for key, value in match.items()):
                return event
        return None

    # -- internals -------------------------------------------------------------

    def _require_sealed_before_render(self, event: AuditEvent) -> None:
        """§5.1 — a render job may not reference an unsealed prediction.

        This is the load-bearing ordering: the seal is committed and fsynced
        before the render job exists, so a bet cannot be rewritten after the
        fact that might have disproved it.
        """
        prediction_id = event.payload.get("prediction_id")
        if prediction_id is None:
            return
        sealed = self.find("prediction.sealed", prediction_id=prediction_id)
        if sealed is None:
            raise LedgerError(
                "prediction_not_sealed",
                f"{prediction_id} has no committed prediction.sealed event",
            )


class InMemoryRecipeStore:
    """The recipe store: versions, branches, typed edits, the recipe hash.

    Implements `RecipeStorePort`. The vocabulary is injected as a validator so
    the dependency runs the way it will after the merge: the recipe store asks
    the vocabulary whether a touched entry's params are still inside its
    schema (§1.1) — it does not know the schema itself.
    """

    def __init__(
        self,
        *,
        document: Mapping[str, Any],
        branches: Sequence[Branch],
        validator: Callable[[Mapping[str, Any]], None] | None = None,
        clock: Any | None = None,
    ) -> None:
        self._documents: dict[str, Mapping[str, Any]] = {}
        self._versions: dict[str, RecipeVersion] = {}
        self._branches: dict[str, Branch] = {branch.id: branch for branch in branches}
        self._validator = validator
        self._clock = clock

        root = self._root_id(document)
        self._root = root
        # A version's document is its own: an edit may never leak into the
        # version it was applied to, or into the document the store was
        # seeded with.
        self._documents[root] = copy.deepcopy(dict(document))
        self._versions[root] = RecipeVersion(
            id=root,
            recipe=str(document.get("id", "rcp_unknown")),
            parent=None,
            edit=None,
            root_hash=content_hash(document),
            at="2026-10-30T21:00:00Z",
            actor=Actor(kind="core", id="core"),
        )
        for branch in branches:
            self._branches[branch.id] = branch.model_copy(update={"head": root})

    # -- RecipeStorePort -------------------------------------------------------

    @property
    def root_version(self) -> str:
        """The id of the root version the store was seeded with."""
        return self._root

    def head(self, branch_id: str) -> str:
        return self._require_branch(branch_id).head

    def version(self, version_id: str) -> RecipeVersion:
        try:
            return self._versions[version_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown version {version_id}") from exc

    def document(self, version_id: str) -> Mapping[str, Any]:
        return self._documents[version_id]

    def apply_edit(self, edit: RecipeEdit) -> RecipeVersion:
        base = self._documents.get(edit.base)
        if base is None:
            raise KeyError(f"unknown base version {edit.base}")

        document = copy.deepcopy(dict(base))
        for op in edit.ops:
            _apply_op(document, op)

        if self._validator is not None:
            # §1.1: an edit is admitted only if the resulting document passes
            # every touched entry's vocabulary param schema.
            self._validator(document)

        version_id = self._root_id(document)
        version = RecipeVersion(
            id=version_id,
            recipe=str(document.get("id", "rcp_unknown")),
            parent=edit.base,
            edit=edit.id,
            root_hash=content_hash(document),
            at=self._now(),
            actor=edit.author,
        )
        self._documents[version_id] = document
        self._versions[version_id] = version
        return version

    def move_head(self, branch_id: str, version_id: str) -> Branch:
        branch = self._require_branch(branch_id)
        if version_id not in self._versions:
            raise KeyError(f"unknown version {version_id}")
        current = self._versions[branch.head]
        target = self._versions[version_id]
        if target.id != current.id and target.parent != current.id:
            raise ValueError(
                f"{branch_id} head {current.id} does not fast-forward to {version_id}"
            )
        moved = branch.model_copy(update={"head": version_id})
        self._branches[branch_id] = moved
        return moved

    def branches(self) -> Sequence[Branch]:
        return tuple(self._branches.values())

    # -- internals -------------------------------------------------------------

    def _require_branch(self, branch_id: str) -> Branch:
        try:
            return self._branches[branch_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown branch {branch_id}") from exc

    def _now(self) -> str:
        if self._clock is not None:
            return self._clock.now()
        return "2026-10-30T21:00:00Z"

    @staticmethod
    def _root_id(document: Mapping[str, Any]) -> str:
        return f"ver_{short_hash(document)}"


def _apply_op(document: dict[str, Any], op: Op) -> None:
    """Apply one op to the document.

    Paths are dotted and relative to the recipe's entries, as the spec's own
    example is (`harbor.crates.params.count` — §1.1): the longest matching
    entry path wins, and the rest of the path resolves inside that entry. A
    path that names no entry resolves against the document itself.
    """
    parts = op.path.split(".")
    root, rest = _resolve_path(document, parts)

    cursor: Any = root
    for part in rest[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(f"path {op.path!r} does not exist in the recipe")
        cursor = cursor[part]
    leaf = rest[-1]
    if not isinstance(cursor, dict):
        raise KeyError(f"path {op.path!r} does not exist in the recipe")

    if op.op == "set":
        cursor[leaf] = op.value
    elif op.op == "add":
        current = cursor.get(leaf)
        if isinstance(current, list):
            current.append(op.value)
        elif isinstance(current, (int, float)) and isinstance(op.value, (int, float)):
            cursor[leaf] = current + op.value
        else:
            raise KeyError(f"cannot add to {op.path!r}")
    elif op.op == "remove":
        if leaf not in cursor:
            raise KeyError(f"path {op.path!r} does not exist in the recipe")
        del cursor[leaf]
    else:  # pragma: no cover - the model restricts the literal
        raise ValueError(f"unknown op {op.op!r}")


def _resolve_path(document: Mapping[str, Any], parts: list[str]) -> tuple[Any, list[str]]:
    """Split a dotted path into (the thing it addresses, the path within it)."""
    entries = document.get("entries")
    if isinstance(entries, Mapping):
        for split in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:split])
            if candidate in entries:
                return entries[candidate], parts[split:]
    return document, parts


class InMemoryScheduler:
    """The scheduler's job door.

    Enqueuing a render commits a `job.enqueued` event — and the ledger refuses
    it if the bet it is meant to test was never sealed (§5.1). That refusal is
    the ordering guarantee, enforced where the ordering happens.
    """

    def __init__(self, *, ledger: InMemoryLedger, clock: Any) -> None:
        self._ledger = ledger
        self._clock = clock
        self._jobs: dict[str, RenderJob] = {}

    def enqueue_render(self, request: RenderRequest) -> RenderJob:
        job_id = f"job_{short_hash(request.as_request())}"
        job = RenderJob(
            id=job_id,
            request=request,
            created_at=self._clock.now(),
            prediction_id=request.prediction_id,
        )
        self._jobs[job_id] = job
        self._ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'job.enqueued', 'job': job_id})}",
                at=job.created_at,
                actor=Actor(kind="core", id="scheduler", via="wo"),
                type="job.enqueued",
                subject={"entity_kind": "job", "entity_id": job_id},
                payload={
                    "job_id": job_id,
                    "prediction_id": request.prediction_id,
                    "request": request.as_request(),
                    "lane": job.lane,
                    "worker": job.worker,
                },
            )
        )
        return job

    def job(self, job_id: str) -> RenderJob | None:
        return self._jobs.get(job_id)
