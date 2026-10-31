"""Shared test fixtures for the recipe store.

Test-only helpers live here (not in the production package), per the
test-driven-development rules.
"""

from __future__ import annotations

import itertools
from typing import Callable

import pytest

from builder_recipe.models import (
    Actor,
    Constraint,
    EnginePin,
    GeneratorRef,
    Recipe,
    RecipeEntry,
)
from builder_recipe.schema import StaticSchemaRegistry


@pytest.fixture
def clock() -> Callable[[], str]:
    """A deterministic counter clock so timestamps are stable in tests."""
    counter = itertools.count()

    def _now() -> str:
        return f"2026-10-30T20:00:{next(counter):02d}Z"

    return _now


@pytest.fixture
def actor() -> Actor:
    return Actor(kind="owner", id="casey")


@pytest.fixture
def magnus() -> Actor:
    return Actor(kind="owner", id="magnus")


@pytest.fixture
def architect() -> Actor:
    return Actor(kind="character", id="architect", via="word")


@pytest.fixture
def pin() -> EnginePin:
    return EnginePin(
        repo="SI-Thor/infinigen-thor",
        commit="9f31c0e",
        config="sha256:cf90cafe",
        blender="4.2",
        python="3.12",
    )


@pytest.fixture
def fjellvik(pin: EnginePin) -> Recipe:
    """The Fjellvik example of core-spec v2 §1.1."""
    return Recipe(
        id="rcp_fjellvik",
        name="Fjellvik",
        engine_pin=pin,
        seeds={"terrain": 4471, "props": 4472, "weather": 4473},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates",
                kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.props",
                    func="crates",
                    variant="harbor",
                    rev="9f31c0e",
                ),
                params={"count": 12, "style": "weathered"},
                seed=4472,
                origin="builtin",
            ),
            "structure.south_span": RecipeEntry(
                path="structure.south_span",
                kind="structure",
                generator=GeneratorRef(
                    module="infinigen_thor.structures",
                    func="bridge",
                    variant="rope",
                    rev="9f31c0e",
                ),
                params={"length_m": 14.0, "planks": 8, "sway": 0.22, "load_factor": 1.1},
                seed=99,
                origin="builtin",
            ),
            "terrain.harbor": RecipeEntry(
                path="terrain.harbor",
                kind="terrain",
                params={"slope": 0.08},
                seed=4471,
                origin="builtin",
            ),
        },
        constraints=[
            Constraint(name="oak_dripline", kind="keep_clear", ref="oak_0117", value=0.35)
        ],
    )


@pytest.fixture
def schemas() -> StaticSchemaRegistry:
    """The three words of the slice (§6.1) plus the Fjellvik entries."""
    return StaticSchemaRegistry(
        {
            "harbor.crates": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 48},
                    "style": {"type": "string", "enum": ["plain", "weathered", "stained"]},
                    "from_library": {"type": "integer", "minimum": 0, "maximum": 48},
                    "seed": {"type": "integer", "minimum": 0, "maximum": 2**31},
                },
            },
            "structure.south_span": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "length_m": {"type": "number", "minimum": 0.5, "maximum": 60.0},
                    "planks": {"type": "integer", "minimum": 1, "maximum": 64},
                    "sway": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "load_factor": {"type": "number", "minimum": 0.0, "maximum": 10.0},
                },
            },
            "terrain.harbor": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"slope": {"type": "number", "minimum": 0.0, "maximum": 1.0}},
            },
            "props.harbor.crates": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 48},
                    "style": {"type": "string", "enum": ["plain", "weathered", "stained"]},
                },
            },
        }
    )


@pytest.fixture
def blobs(tmp_path):
    from builder_recipe.blobs import FileBlobStore

    return FileBlobStore(tmp_path / "builder-home")


@pytest.fixture
def ledger():
    from builder_recipe.ledger import InMemoryLedger

    return InMemoryLedger()


@pytest.fixture
def store(ledger, blobs, schemas: StaticSchemaRegistry, clock):
    from builder_recipe.store import RecipeStore

    return RecipeStore(ledger=ledger, blobs=blobs, schemas=schemas, clock=clock)


@pytest.fixture
def root_version(store: RecipeStore, fjellvik: Recipe, actor: Actor) -> str:
    store.create_recipe(fjellvik, actor)
    return "ver_0001"


class RecordingQuestions:
    """A stand-in for the API half's question store (test-only)."""

    def __init__(self) -> None:
        self.parked: list[dict] = []

    def park(self, *, name: str, branch: str, options: list[str], detail: str) -> str:
        self.parked.append(
            {"name": name, "branch": branch, "options": options, "detail": detail}
        )
        return f"q_{len(self.parked):04d}"


@pytest.fixture
def questions() -> RecordingQuestions:
    return RecordingQuestions()
