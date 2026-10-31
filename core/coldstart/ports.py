"""The seams.

Cold start is a *read and a write against the ledger* (G's one-line verdict),
so it owns no store of its own: everything durable it does is an audit event,
and everything it decides it folds back out of the log. The seams below are
the pieces other seats own; the protocols mirror `docs/design/core-spec.md`
(v2) field for field so that when the real implementations land this code
does not move.

| seat | branch | owns | seam |
|---|---|---|---|
| `core-api` | `core-api` | the audit ledger, the HTTP/SSE API | `LedgerPort` |
| `vocab` | `vocab` | the confidence gate's constants and the sealed-prediction write path | `SealerPort`, the gate thresholds re-stated in `gate.py` |
| `night-runner` | `night-runner` | the night's rails, the queue, the batch admission | `Rail` (in `stubs.py`) |

The in-memory implementations of all three live in `stubs.py`, each headed by
the branch that owns the real one. They are not toys: they keep the rules that
make cold start's guarantees mean anything (a gapless sequence, an append-only
log, sealed-before-render ordering, the three-writer rule on taste rows).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .models import AuditEvent, Prediction

__all__ = ["Clock", "LedgerPort", "SealerPort"]


@runtime_checkable
class Clock(Protocol):
    """Anything that can say what time it is, in RFC 3339 UTC (§1.0).

    Everything that stamps a time takes a `Clock`, so a test can order events
    exactly — sealed-before-render is only meaningful under a controlled clock.
    """

    def now(self) -> str:  # pragma: no cover - protocol
        ...


@runtime_checkable
class LedgerPort(Protocol):
    """The audit ledger — `core-api`'s to build (branch `core-api`).

    Spec §1.8 / §1.0 / §5.1. The implementation must:

    * assign `seq` per project, monotone and **gapless** — it is the resume
      cursor and the client's `since_seq`;
    * accept appends from a **single writer** process; every state change is
      one transaction that appends the audit row and updates the projections
      atomically;
    * keep `prediction.sealed` **committed before** any `job.enqueued` that
      references that prediction — the ordering that makes a sealed bet
      unforgeable (§5.1);
    * be append-only, with exactly one exception: an owner-initiated taste
      erasure (§1.7).
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
class SealerPort(Protocol):
    """The sealed-prediction write path — the `vocab` seat's (branch `vocab`).

    Spec §1.7 / §5.1, as built in `core/vocab/predictions.py`. The
    implementation must:

    * hash the sealed payload (`seal_hash`, covering `render_spec`) and commit
      `prediction.sealed` **before** any render job exists;
    * carry `reason_code` in the audit payload (it is not a field of the
      `Prediction` record — §1.7 has no such field — because the taste gate is
      per reason code and the ledger is where the gate reads its denominators);
    * refuse unknown claim types and confidences, double scoring, and
      self-scoring (the three-writer rule, §1.7).

    The cold-start policy layers the melt on top of this seam (§3.5, decision
    13a): *which* confidence a builder may seal is decided by the gate, not
    offered as a free choice — see `sealing.ColdStartSealer`.
    """

    def seal(
        self,
        *,
        builder: str,
        claim: str,
        claim_type: str,
        confidence: str,
        basis: str,
        branch_ref: str,
        render_spec: Mapping[str, Any] | None = None,
        reason_code: str | None = None,
        actor: Any | None = None,
        at: str | None = None,
    ) -> Prediction: ...
