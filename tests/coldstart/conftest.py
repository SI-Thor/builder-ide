"""Fixtures: the cold world of night one.

Night one per the continuity note (G §0) is Saturday 2026-10-24; the clock
starts at 19:58, the moment the empty project opens.
"""

from __future__ import annotations

import pytest

from core.coldstart import InMemoryLedger, SteppingClock


@pytest.fixture
def clock() -> SteppingClock:
    return SteppingClock("2026-10-24T19:58:00Z")


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()
