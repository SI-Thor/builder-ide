"""Fixtures: the cold world of night one, and the tools to warm it.

Night one per the continuity note (G §0) is Saturday 2026-10-24; the clock
starts at 19:58, the moment the empty project opens. Everything here is a
fold over the audit log, so a test can rebuild any service from the ledger
alone — the kill -9 property every gap test leans on.
"""

from __future__ import annotations

from typing import Callable

import pytest

from core.coldstart import (
    AskMode,
    ColdStartGate,
    ColdStartSealer,
    InMemoryLedger,
    PredictionSealer,
    SteppingClock,
    TasteRow,
)
from core.coldstart.models import Actor, AuditEvent
from core.coldstart.stubs import short_hash

#: The owner's tap: ask-mode answers are the owner's action, never a builder's.
OWNER = Actor(kind="owner", id="casey")

#: A builder trying to write taste — the three-writer rule must refuse it.
BUILDER = Actor(kind="character", id="companion", via="ask")


@pytest.fixture
def clock() -> SteppingClock:
    return SteppingClock("2026-10-24T19:58:00Z")


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def gate(ledger) -> ColdStartGate:
    return ColdStartGate(ledger)


@pytest.fixture
def ask(ledger, clock) -> AskMode:
    return AskMode(ledger=ledger, clock=clock)


@pytest.fixture
def sealer(ledger, clock) -> ColdStartSealer:
    return ColdStartSealer(
        ledger=ledger,
        clock=clock,
        sealer=PredictionSealer(ledger=ledger, clock=clock),
    )


@pytest.fixture
def write_row(ledger, clock) -> Callable[..., TasteRow]:
    """Write one taste row directly — the owner's unprompted keep or reject.

    Rows written this way carry no `asked-by` tag, so they count toward every
    builder's melt (the ledger is shared and readable); that is the contrast
    class the per-builder tests need.
    """

    def _write(
        *,
        reason_code: str,
        verdict: str = "keep",
        author: str = "casey",
        status: str = "active",
        artifact_ref: str = "br_main@ver_0001",
        param_path: str = "harbor.crates",
        value: str = "kept-thing",
        tags: tuple[str, ...] = (),
    ) -> TasteRow:
        at = clock.now()
        row = TasteRow(
            id=f"tn_{short_hash({'at': at, 'reason': reason_code, 'artifact': artifact_ref})}",
            at=at,
            author=author,
            status=status,  # type: ignore[arg-type]
            subject={"param_path": param_path, "value": value},
            artifact_ref=artifact_ref,
            verdict=verdict,  # type: ignore[arg-type]
            reason_code=reason_code,
            words=None,
            tags=tags,
        )
        ledger.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'taste.note.appended', 'row': row.id})}",
                at=at,
                actor=Actor(kind="owner", id=author),
                type="taste.note.appended",
                subject={"entity_kind": "taste_note", "entity_id": row.id},
                payload={
                    "row": {
                        "id": row.id,
                        "at": row.at,
                        "author": row.author,
                        "status": row.status,
                        "subject": row.subject,
                        "artifact_ref": row.artifact_ref,
                        "verdict": row.verdict,
                        "reason_code": row.reason_code,
                        "words": row.words,
                        "tags": list(row.tags),
                    }
                },
            )
        )
        return row

    return _write
