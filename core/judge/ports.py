"""The seams.

The judge writes one audit type and nothing else, so it needs one door
outward:

* **the ledger** — the log of record (§1.8). Every judgment is a row
  there; a judgment that is not recorded did not happen.

It is the same protocol the night runner and the tiles seat code
against (``core.night.ledger`` implements it; ``core.tiles.ports``
names it), kept as a protocol here so the judge can be built and
measured before the real ledger lands, and so a future implementation
does not have to move this code.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from core.records import Actor, AuditEvent

__all__ = ["LedgerPort"]


@runtime_checkable
class LedgerPort(Protocol):
    """The audit ledger — the log of record (core-spec §1.0, §1.8)."""

    def append(
        self,
        *,
        type: str,
        actor: Actor,
        subject: dict[str, Any],
        payload: dict[str, Any],
        artifact: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> AuditEvent:
        """Append one event and return it as committed."""
        ...

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        """The committed events, oldest first, optionally filtered."""
        ...

    def last_seq(self) -> int:
        """The highest sequence number written."""
        ...
