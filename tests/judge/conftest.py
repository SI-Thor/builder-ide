"""Shared fixtures for the judge seat's suite.

The tiles fixtures mirror ``tests/tiles/conftest.py`` — the shortlist
tests exercise the judge through the tiles acceptance rig's own shapes
(the M1 slice's crates word, six tiles, the simulated game).
"""

from __future__ import annotations

import pytest

from core.night.ledger import InMemoryLedger
from core.vocab.registry import VocabularyRegistry
from core.vocab.words import default_entries

from core.tiles.models import TileAuthor, TileStep, build_tile

FAKE_PROMPT_HASH = "sha256:" + "0" * 64

FAKE_AUTHOR = TileAuthor(
    model="fake/scripted-v1",
    provider="fake",
    prompt_hash=FAKE_PROMPT_HASH,
    cost_cents=0,
)


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def registry() -> VocabularyRegistry:
    return VocabularyRegistry(default_entries())


@pytest.fixture
def make_tile():
    """Build a tile in the closed vocabulary — the M1 slice's crates word."""

    def _make(style: str = "weathered", **overrides):
        params = overrides.pop("params", {"count": 12, "style": style, "from_library": 0})
        kwargs = {
            "family": "harbor.crates.style",
            "kind": "recipe_edit",
            "title": f"{style} crates",
            "steps": [
                TileStep(
                    word="props.harbor.crates",
                    path="harbor.crates",
                    params=params,
                )
            ],
            "author": FAKE_AUTHOR,
        }
        kwargs.update(overrides)
        return build_tile(**kwargs)

    return _make
