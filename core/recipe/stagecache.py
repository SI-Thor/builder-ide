"""The stage cache key — core-spec v2 §1.9.

The stage cache is content-addressed on disk under ``stages/<key2>/<key>/``.
Its key must be a function of the recipe version alone: no wall-clock, no
hostname, no ambient config — otherwise a hit is not the same work (RV
patch 13).

Two hashes live here:

``stage_cache_key``
    the key of a *stage*: ``sha256(canonical(recipe_version_hash ⊕
    engine_pin ⊕ stage_name ⊕ dep_keys))``. The engine pin carries the
    pinned config hash, so config drift cannot defeat the cache.

``entry_stage_key``
    the key of an *entry's* stage. It is content-addressed rather than
    version-addressed, because the dirty-set contract (§1.1) needs a stage
    key that survives across versions: an entry nobody touched keeps its
    key, so the stages that depend on it stay cache hits and the world does
    not rebuild itself every night.
"""

from __future__ import annotations

from typing import Sequence

from core.recipe.canonical import content_hash
from core.recipe.models import EnginePin, RecipeEntry

__all__ = ["stage_cache_key", "entry_stage_key", "DEFAULT_ENTRY_STAGE_NAME"]

DEFAULT_ENTRY_STAGE_NAME = "entry"


def stage_cache_key(
    recipe_version_hash: str,
    engine_pin: EnginePin,
    stage_name: str,
    dep_keys: Sequence[str] = (),
) -> str:
    """The cache key of a stage."""
    return content_hash(
        {
            "recipe_version_hash": recipe_version_hash,
            "engine_pin": engine_pin.model_dump(),
            "stage_name": stage_name,
            "dep_keys": sorted(dep_keys),
        }
    )


def entry_stage_key(
    entry_path: str,
    entry: RecipeEntry,
    engine_pin: EnginePin,
    stage_name: str = DEFAULT_ENTRY_STAGE_NAME,
) -> str:
    """The cache key of an entry's stage — stable while the entry is stable."""
    return content_hash(
        {
            "entry_path": entry_path,
            "entry": entry.model_dump(),
            "engine_pin": engine_pin.model_dump(),
            "stage_name": stage_name,
        }
    )
