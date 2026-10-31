"""The seam between the USD compiler and the recipe store.

The compiler codes against a small protocol — :class:`RecipeSource` — with
two implementations behind it:

* :class:`StubRecipeSource` — a recipe held in memory or loaded from a JSON
  file; what the CLI's ``--recipe`` path and the demo use.
* :class:`BuilderRecipeSource` — the adapter over the real store
  (``core.recipe``, merged). It calls ``RecipeStore.get_document(version_id)``
  and converts the store's pydantic model into the views below.

The views mirror core-spec v2 §1.1 field for field, and
:meth:`RecipeDocument.canonical` reproduces the shape
``core.recipe.models.Recipe.model_dump()`` produces — so the recipe hash
computed here is the same hash the store computes for the same document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from builder_usd.canonical import content_hash

__all__ = [
    "EnginePin",
    "RecipeEntry",
    "RecipeDocument",
    "RecipeSource",
    "StubRecipeSource",
    "BuilderRecipeSource",
    "builder_recipe_available",
    "load_recipe_json",
]


@dataclass(frozen=True)
class EnginePin:
    """The pinned engine — core-spec v2 §1.1."""

    repo: str
    commit: str
    config: str
    blender: str
    python: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "commit": self.commit,
            "config": self.config,
            "blender": self.blender,
            "python": self.python,
        }


@dataclass(frozen=True)
class RecipeEntry:
    """One typed entry of a recipe — core-spec v2 §1.1."""

    path: str
    kind: str
    generator: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    constraints: list[dict[str, Any]] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    origin: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "generator": self.generator,
            "params": self.params,
            "seed": self.seed,
            "constraints": self.constraints,
            "assets": self.assets,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class RecipeDocument:
    """A project is its recipe (core-spec v2 §1.1)."""

    id: str
    name: str
    schema_version: int = 2
    engine_pin: EnginePin = field(
        default_factory=lambda: EnginePin("", "", "sha256:0", "", "")
    )
    seeds: dict[str, int] = field(default_factory=dict)
    entries: dict[str, RecipeEntry] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)

    def canonical(self) -> dict[str, Any]:
        """The document as the store would dump it — the hash input."""
        return {
            "id": self.id,
            "name": self.name,
            "schema_version": self.schema_version,
            "engine_pin": self.engine_pin.to_dict(),
            "seeds": dict(self.seeds),
            "entries": {
                key: self.entries[key].to_dict() for key in sorted(self.entries)
            },
            "constraints": list(self.constraints),
        }

    def recipe_hash(self) -> str:
        """The content hash of the canonical document."""
        return content_hash(self.canonical())


class RecipeSource(Protocol):
    """The seam: something that can hand the compiler a recipe document."""

    def document(self) -> RecipeDocument:
        """The recipe to compile."""
        ...


class StubRecipeSource:
    """The stub implementation of the seam — a recipe held in memory."""

    def __init__(self, document: RecipeDocument) -> None:
        self._document = document

    def document(self) -> RecipeDocument:
        return self._document

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StubRecipeSource":
        return cls(document_from_dict(data))


def document_from_dict(data: dict[str, Any]) -> RecipeDocument:
    """Build a :class:`RecipeDocument` from the spec-shaped dictionary."""
    pin = data.get("engine_pin") or {}
    entries = {}
    for key, raw in (data.get("entries") or {}).items():
        entry = dict(raw)
        entry.setdefault("path", key)
        entries[key] = RecipeEntry(
            path=str(entry["path"]),
            kind=str(entry["kind"]),
            generator=entry.get("generator"),
            params=dict(entry.get("params") or {}),
            seed=entry.get("seed"),
            constraints=list(entry.get("constraints") or []),
            assets=list(entry.get("assets") or []),
            origin=entry.get("origin"),
        )
    return RecipeDocument(
        id=str(data.get("id", "rcp_unknown")),
        name=str(data.get("name", "unnamed")),
        schema_version=int(data.get("schema_version", 2)),
        engine_pin=EnginePin(
            repo=str(pin.get("repo", "")),
            commit=str(pin.get("commit", "")),
            config=str(pin.get("config", "sha256:0")),
            blender=str(pin.get("blender", "")),
            python=str(pin.get("python", "")),
        ),
        seeds={str(k): int(v) for k, v in (data.get("seeds") or {}).items()},
        entries=entries,
        constraints=list(data.get("constraints") or []),
    )


def load_recipe_json(path: str | Path) -> StubRecipeSource:
    """Load a recipe document from a JSON file (the CLI's input format)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return StubRecipeSource.from_dict(data)


def builder_recipe_available() -> bool:
    """Is the recipe store importable on this interpreter?

    The seats are merged, so this is ``core.recipe`` — always importable
    from the one tree. The probe stays (rather than a bare import) so the
    CLI can say so in words on an interpreter that lacks it.
    """
    try:
        import core.recipe  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class BuilderRecipeSource:
    """Adapter over the recipe store (``core.recipe``, merged).

    The adapter reads one version of one recipe through the store's own
    interface — ``RecipeStore.get_document(version_id)`` — and converts the
    result into the views this package compiles against. The store's
    pydantic model dumps to the same shape :meth:`RecipeDocument.canonical`
    reproduces, so the hash computed here is the hash the store committed.
    """

    def __init__(self, store: Any, version_id: str) -> None:
        self._store = store
        self._version_id = version_id

    def document(self) -> RecipeDocument:
        raw = self._store.get_document(self._version_id)
        return document_from_dict(raw.model_dump() if hasattr(raw, "model_dump") else raw)
