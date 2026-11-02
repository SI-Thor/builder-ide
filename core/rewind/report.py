"""The report: what was kept, what was dropped, what was parked, and why.

Every row the selection did not keep carries a reason, and every parked
question carries the thing that could not be decided. The report is the part
a human reads before deciding anything, so it says the reason rather than a
count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Outcome", "Parked", "RewindReport"]


@dataclass(frozen=True)
class Outcome:
    """One row of the ledger, and what became of it."""

    seq: int
    at: str
    actor: str
    kind: str
    kept: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "actor": self.actor,
            "kind": self.kind,
            "kept": self.kept,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Parked:
    """A question parked instead of a guess made."""

    name: str
    branch: str
    options: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "branch": self.branch,
            "options": list(self.options),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RewindReport:
    """The whole story of one rewind: the point, the selection, the outcome."""

    source: str
    point: str
    selection: str
    kept: tuple[Outcome, ...] = ()
    dropped: tuple[Outcome, ...] = ()
    parked: tuple[Parked, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "point": self.point,
            "selection": self.selection,
            "kept": [outcome.as_dict() for outcome in self.kept],
            "dropped": [outcome.as_dict() for outcome in self.dropped],
            "parked": [parked.as_dict() for parked in self.parked],
            "notes": list(self.notes),
        }

    def render(self) -> str:
        """The report as text: a person reads this."""
        lines: list[str] = []
        lines.append(f"rewind to {self.point}")
        lines.append(f"  selection: {self.selection}")
        lines.append(f"  ledger:    {self.source}")
        lines.append(
            f"  kept {len(self.kept)}, dropped {len(self.dropped)}, "
            f"parked {len(self.parked)}"
        )
        if self.kept:
            lines.append("  kept:")
            for outcome in self.kept:
                lines.append(f"    seq {outcome.seq} {outcome.kind} {outcome.actor} — {outcome.reason}")
        if self.dropped:
            lines.append("  dropped:")
            for outcome in self.dropped:
                lines.append(
                    f"    seq {outcome.seq} {outcome.kind} {outcome.actor} — {outcome.reason}"
                )
        if self.parked:
            lines.append("  parked:")
            for parked in self.parked:
                options = " | ".join(parked.options)
                lines.append(f"    {parked.name} [{options}] {parked.detail}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)
