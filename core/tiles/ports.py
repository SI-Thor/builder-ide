"""The seams.

The tile seat writes audit events and nothing else, so it needs two doors
outward:

* **the ledger** — `core-api`'s to build (the service layer's keyword
  `append` is the shape the night runner and the daytime seat already code
  against);
* **the vocabulary** — `core/vocab`'s. The tiles seat does not own the
  words; it asks the registry whether a word exists and whether a tile's
  params are in schema, and refuses the tile when the answer is no.

Both are protocols here, so the seat can be built and measured before the
real implementations land, and so a future implementation of either does
not have to move this code.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from core.records import Actor, AuditEvent

__all__ = ["LedgerPort", "VocabularyPort"]


@runtime_checkable
class LedgerPort(Protocol):
    """The audit ledger — the log of record (core-spec §1.0, §1.8).

    The implementation must:

    * assign a gapless, monotone ``seq`` per project;
    * accept appends from a **single writer** process, one transaction per
      state change;
    * keep a payload under its cap (4 KiB) — a payload that does not fit
      belongs in artifacts/ and is hash-referenced, not truncated in place;
    * be append-only.
    """

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


@runtime_checkable
class VocabularyPort(Protocol):
    """The closed, typed vocabulary (core-spec §1.5).

    The implementation must:

    * know a word's parameter schema, and validate a call's params against
      it, refusing anything outside the schema;
    * raise ``KeyError`` for a word it does not know — the tiles seat turns
      that into a ``word_unknown`` refusal;
    * never widen a schema at the call: a word is added by the core, and a
      tile cannot add one.
    """

    def require(self, word: str) -> Any:
        """The vocabulary entry, or ``KeyError``."""
        ...

    def validate_params(self, word: str, params: Mapping[str, Any]) -> None:
        """Raise the vocabulary's own refusal if the params break the schema."""
        ...
