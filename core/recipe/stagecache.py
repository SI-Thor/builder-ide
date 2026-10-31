"""The stage cache key — core-spec v2 §1.9.

The stage cache is content-addressed on disk under ``stages/<key2>/<key>/``.
Its key must be a function of the recipe version alone: no wall-clock, no
hostname, no ambient config — otherwise a hit is not the same work (RV
patch 13).

Two hashes live here:

``stage_cache_key``
    the key of a *stage*: ``sha256(canonical(recipe_version_hash ⊕
    engine_pin ⊕ stage_name ⊕ dep_keys))``. The engine pin carries the
    pinned config hash, so config drift cannot defeat the cache. This is
    the *request* key — the identity of one ask at one recipe version
    (what the engine seam reports and callers verify, contract rule 4).

``entry_stage_key``
    the key of an *entry's* stage. It is content-addressed rather than
    version-addressed, because the dirty-set contract (§1.1) needs a stage
    key that survives across versions: an entry nobody touched keeps its
    key, so the stages that depend on it stay cache hits and the world does
    not rebuild itself every night. The key is over the entry's
    **effective inputs** — its own content, its **effective seed** (its
    own seed when set, else the recipe seed for its root segment: the
    fallback every adapter on the engine seam uses to resolve a seed), the
    engine pin, and the **dep-keys** of the entries it is coupled to (a
    coupled entry whose coupling changed is a different stage even though
    its own content did not move). Both terms are the dirty-set contract's
    (``core/engine/DIRTY.md`` §1): content decides, not op shape.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from core.recipe.canonical import content_hash
from core.recipe.models import EnginePin, RecipeEntry

__all__ = [
    "stage_cache_key",
    "entry_stage_key",
    "effective_seed",
    "DEFAULT_ENTRY_STAGE_NAME",
]

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


def effective_seed(
    entry_path: str, entry: RecipeEntry, seeds: Mapping[str, int] | None = None
) -> int:
    """The seed an entry's stage actually runs with: its own when set, else
    the recipe seed for its root segment, else 0 — the fallback every
    adapter on the seam applies (``venv2.trace``'s rule). A key that hashed
    only ``entry.seed`` would go stale the moment a fallback-seeded entry's
    recipe seed moved, so the key hashes this instead."""
    if entry.seed is not None:
        return entry.seed
    return int((seeds or {}).get(entry_path.split(".")[0], 0))


def entry_stage_key(
    entry_path: str,
    entry: RecipeEntry,
    engine_pin: EnginePin,
    stage_name: str = DEFAULT_ENTRY_STAGE_NAME,
    *,
    seeds: Mapping[str, int] | None = None,
    dep_keys: Sequence[str] = (),
) -> str:
    """The cache key of an entry's stage — stable while the entry's
    effective inputs are stable, across recipe versions."""
    return content_hash(
        {
            "entry_path": entry_path,
            "entry": entry.model_dump(),
            "engine_pin": engine_pin.model_dump(),
            "stage_name": stage_name,
            "seed": effective_seed(entry_path, entry, seeds),
            "dep_keys": sorted(dep_keys),
        }
    )
