"""STUB — owned by the `vocab` seat (sibling branch `vocab`).

Minimal, read-only stand-in for the spec §1.5 record the justification layer
reads: VocabularyEntry. Field names follow spec v2; only the fields
justification actually reads are modelled. Replace wholesale on merge — see
core/STUBS.md. No stub-only deltas: ``provenance["origin"]`` (the wo_/builtin
a word came from) is already a spec field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class VocabularyEntry:  # spec §1.5 (subset justification reads)
    word: str                    # the key itself: "bridge.rope" (spec §1.0)
    kind: Literal["structure", "prop", "material", "terrain", "weather",
                  "motion", "light", "constraint", "character"]
    owner_character: str
    status: Literal["active", "coming-soon", "retired"] = "active"
    provenance: dict = field(default_factory=dict)   # {"origin": "wo_14" | "builtin", …}
    version: int = 1
