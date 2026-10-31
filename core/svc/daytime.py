"""The daytime world behind the spine's own doors.

The spine owns the one ledger (§1.0), so the daytime writes into it:
:class:`SpineDayLedger` satisfies the daytime seat's small ``Ledger``
protocol with the spine's SQLite store, exactly as ``SpineRecipeLedger``
does for the recipe store. Every ``day.*`` row therefore lands in the same
audit log as the night's, and folds into the same projections.

The gate is one setting. Casey has not decided B3, so the daytime is off
unless ``daytime_enabled`` says otherwise — and the morning report reads
the log either way, so the report's shape does not change with the flag.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..canon import new_id, now_utc
from ..events import Actor
from ..records import AuditEvent, Recipe
from ..store import LedgerStore
from core.daytime.budget import DayBudget
from core.daytime.models import DayWorld
from core.daytime.projection import DayProjection
from core.daytime.runner import DayRunner

__all__ = ["SpineDayLedger", "DaytimeService"]


class SpineDayLedger:
    """``core.daytime.ledger.Ledger`` over the spine's one audit log.

    The spine's store is the single writer (§1.0) and its connection is
    lock-guarded, so the daytime may append from any worker.
    """

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

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
        ev = AuditEvent(
            id=new_id("audit"),
            at=at or now_utc(),
            actor=actor,
            type=type,
            subject=subject,
            payload=payload,
            artifact=artifact,
        )
        committed, _ = self._store.append(ev)
        return committed

    def events(
        self,
        *,
        since_seq: int | None = None,
        types: Sequence[str] | None = None,
    ) -> list[AuditEvent]:
        return self._store.events_since(
            since_seq or 0, types=list(types) if types is not None else None
        )

    def last_seq(self) -> int:
        events = self._store.events_since(0)
        return events[-1].seq if events else 0


class DaytimeService:
    """The daytime world, as the spine runs it."""

    def __init__(self, core: Any, settings: Any = None) -> None:
        self.core = core
        self.settings = settings if settings is not None else core.settings
        self.ledger = SpineDayLedger(core.store)

    @property
    def enabled(self) -> bool:
        """Is the daytime on? One setting, on by default (B3, decided)."""
        return bool(getattr(self.settings, "daytime_enabled", True))

    def projection(self) -> DayProjection:
        """The log, folded."""
        return DayProjection(self.ledger.events())

    def tick(
        self,
        recipe: Recipe,
        version_id: str,
        *,
        actor: Actor | None = None,
        budget: DayBudget | None = None,
    ) -> DayWorld | None:
        """One daytime tick, if the daytime is on.

        Returns the new world, or ``None`` when the daytime stood down —
        to the night lane, or to its own budget. Nothing happens at all
        while the setting is off.
        """
        if not self.enabled:
            return None
        runner = DayRunner(
            self.ledger, recipe, version_id, actor=actor, budget=budget
        )
        return runner.tick()

    def world(self) -> DayWorld | None:
        """The room, as the log says it is."""
        return self.projection().world

    def while_you_were_away(self, night_id: str) -> dict:
        """The line the morning report shows for this night."""
        from core.daytime.report import while_you_were_away

        return while_you_were_away(self.projection().day_before(night_id))
