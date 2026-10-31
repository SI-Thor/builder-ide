"""Fixtures: a small Fjellvik to run the loop in.

Two worlds are available and they are the two the product has to serve:

* the **established** world — Casey's taste rows and the Prop-maker's three
  earlier bets are in the ledger, so the builder has priors and may act alone;
* the **cold** world — night one, nothing in the ledger, so the builder may
  bet but must ask.

The melt between them is mechanical (G §1), and both are exercised here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from core.vocab import (
    InMemoryLedger,
    InMemoryRecipeStore,
    InMemoryScheduler,
    PredictionService,
    PropMaker,
    SteppingClock,
    VocabularyRegistry,
    default_entries,
)
from core.vocab.models import Actor, Branch
from core.vocab.seed import RECIPE_DOCUMENT, seed_audit_events


@dataclass
class World:
    """Everything a night needs, wired to the seams."""

    registry: VocabularyRegistry
    ledger: InMemoryLedger
    clock: SteppingClock
    recipes: InMemoryRecipeStore
    scheduler: InMemoryScheduler
    predictions: PredictionService
    maker: PropMaker


def _build(*, seeded: bool) -> World:
    registry = VocabularyRegistry(default_entries())
    ledger = InMemoryLedger(events=seed_audit_events() if seeded else ())
    clock = SteppingClock("2026-10-30T21:20:00Z")
    recipes = InMemoryRecipeStore(
        document=RECIPE_DOCUMENT,
        branches=[
            Branch(
                id="br_main",
                name="main",
                recipe="rcp_fjellvik",
                head="ver_root",
                purpose="main",
                created_by=Actor(kind="owner", id="casey"),
            )
        ],
        validator=registry.validate_document,
        clock=clock,
    )
    scheduler = InMemoryScheduler(ledger=ledger, clock=clock)
    predictions = PredictionService(ledger=ledger, clock=clock)
    maker = PropMaker(
        registry=registry,
        ledger=ledger,
        recipes=recipes,
        scheduler=scheduler,
        clock=clock,
        predictions=predictions,
    )
    return World(
        registry=registry,
        ledger=ledger,
        clock=clock,
        recipes=recipes,
        scheduler=scheduler,
        predictions=predictions,
        maker=maker,
    )


@pytest.fixture
def world() -> World:
    """Fjellvik with its history: the builder has priors."""
    return _build(seeded=True)


@pytest.fixture
def cold_world() -> World:
    """Fjellvik on night one: nothing in the ledger."""
    return _build(seeded=False)


@pytest.fixture
def world_factory() -> Callable[..., World]:
    return _build
