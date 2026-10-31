"""Shared fixtures for the tile seat's suite.

Test-only code lives here, not in the production package (the house rule).

The tiles seat codes against two seams — the **ledger** and the
**vocabulary** — and both are satisfied here by the tree's own conforming
implementations: the night runner's reference ledger (``core.night.ledger``)
and the vocabulary's registry with the M1 slice's three words.
"""

from __future__ import annotations

import pytest

from core.night.ledger import InMemoryLedger
from core.vocab.registry import VocabularyRegistry
from core.vocab.words import default_entries

from core.tiles.models import TileAuthor, TileStep, build_tile

#: The author the scripted cloud author pretends to be. The prompt hash is
#: the hash of the prompt that produced the tile — in a test, a fixed string
#: hashed, so it is stable and reproducible.
FAKE_PROMPT_HASH = "sha256:" + "0" * 64

FAKE_AUTHOR = TileAuthor(
    model="fake/scripted-v1",
    provider="fake",
    prompt_hash=FAKE_PROMPT_HASH,
    cost_cents=0,
)

#: The params of `props.harbor.crates` that the M1 slice's schema admits.
CRATES_PARAMS = {"count": 12, "style": "weathered", "from_library": 0}


@pytest.fixture
def registry() -> VocabularyRegistry:
    """The closed vocabulary: the three words of the M1 slice."""
    return VocabularyRegistry(default_entries())


@pytest.fixture
def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def author() -> TileAuthor:
    return FAKE_AUTHOR


@pytest.fixture
def make_tile(author: TileAuthor):
    """Build a tile in the closed vocabulary — the M1 slice's crates word."""

    def _make(**overrides):
        params = overrides.pop("params", dict(CRATES_PARAMS))
        kwargs = {
            "family": "harbor.crates.style",
            "kind": "recipe_edit",
            "title": "weathered crates",
            "steps": [
                TileStep(
                    word="props.harbor.crates",
                    path="harbor.crates",
                    params=params,
                )
            ],
            "author": author,
        }
        kwargs.update(overrides)
        return build_tile(**kwargs)

    return _make
