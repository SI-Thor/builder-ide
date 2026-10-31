"""STUB — owned by the `core-recipe` seat (sibling branch `core-recipe`).

Minimal, read-only stand-ins for the spec §1.1/§1.2 records the justification
layer reads: RecipeEntry, RecipeVersion, Branch. Field names follow spec v2;
only the fields justification actually reads are modelled. Replace wholesale
on merge — see core/STUBS.md.

Stub-only deltas (flagged in STUBS.md):

- ``RecipeVersion.entries`` materializes the version's document
  (spec §1.0 keeps documents as content-addressed blobs; the projection the
  real seat builds must expose the same mapping version -> entries).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.api import Actor  # Actor is shared vocabulary; defined in the api stub


@dataclass
class RecipeEntry:  # spec §1.1 (subset justification reads)
    path: str                    # dotted, ≤ 3 segments, e.g. "harbor.crates"
    kind: str                    # generator | structure | prop_set | … (spec §1.1)
    assets: list[str] = field(default_factory=list)   # ast_ ids this entry consumes
    origin: str | None = None    # wo_14 | "builtin" | word that made it


@dataclass
class RecipeVersion:  # spec §1.2 (subset justification reads)
    id: str                      # ver_…
    recipe: str                  # rcp_
    parent: str | None = None
    entries: dict[str, RecipeEntry] = field(default_factory=dict)  # STUB-ADDED projection


@dataclass
class Branch:  # spec §1.2 (subset justification reads)
    id: str                      # br_…
    name: str                    # "main" | "night-2026-10-30" | "wo-14" | …
    recipe: str = ""
    head: str = ""               # ver_…
    purpose: Literal["main", "night", "work-order", "morning-option",
                     "standing", "rejected"] = "night"
    created_by: Actor | None = None   # .via carries the wo_ id for WO branches
    protected: bool = False      # "main" and kept morning options (spec §1.2)
