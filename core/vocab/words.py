"""The three words of the M1 slice.

Spec §6.1 names them, and this is the vocabulary of one room — Fjellvik's
harbour — that a builder would actually use on a single evening:

    `props.harbor.crates {count 1–48, style enum[plain, weathered, stained],
                          from_library 0–count, seed}`
    `props.harbor.racks {count 1–24, length_m 0.5–6}`
    `material.wood.weathering {wear 0–5, tone enum[pale, gray, dark]}`

Three words, and the Prop-maker is the character who owns all of them (T
§"Five builders and one computer": the Prop-maker works "props, materials,
scale, wear").

Each entry is **typed and bounded** — its `params` is a schema from the §1.5
subset, so a call can be validated and a diff can be compared — and each
carries **taste notes** and **provenance**:

* the taste notes are the aggregate of the owner's own decisions about that
  entry (Casey's rows in `seed.py`), not adjectives written by hand;
* the provenance says where the word came from — `builtin` here, `wo_…` for a
  word promoted out of a kept work order (§2.3).

The one place the spec's subset needed extending is `from_library 0–count`: a
static `maximum` cannot express "at most the count", so the schema carries an
`x-cross-field` rule. See `schema.py` and `README.md`.
"""

from __future__ import annotations

from typing import Any

from .models import AcceptanceCheck, TasteNote, VocabularyEntry
from .seed import ENGINE_PIN, TASTE_ROWS
from .taste import TasteRow, aggregate_taste_notes

__all__ = [
    "CRATES_PARAMS",
    "RACKS_PARAMS",
    "WEATHERING_PARAMS",
    "crates_entry",
    "racks_entry",
    "weathering_entry",
    "default_entries",
    "seed_taste_rows",
]

#: §1.5 — the param schema subset, as a JSON Schema (draft 2020-12 subset).
CRATES_PARAMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["count", "style", "from_library"],
    "properties": {
        "count": {"type": "integer", "minimum": 1, "maximum": 48},
        "style": {"type": "string", "enum": ["plain", "weathered", "stained"]},
        # §6.1: "from_library 0–count". The subset needs a static maximum, so
        # the count-bound is the cross-field rule below.
        "from_library": {"type": "integer", "minimum": 0, "maximum": 48},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647, "x-seed": True},
    },
    "x-cross-field": [{"left": "from_library", "op": "<=", "right": "count"}],
}

RACKS_PARAMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["count", "length_m"],
    "properties": {
        "count": {"type": "integer", "minimum": 1, "maximum": 24},
        "length_m": {"type": "number", "minimum": 0.5, "maximum": 6},
    },
}

WEATHERING_PARAMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["wear", "tone"],
    "properties": {
        "wear": {"type": "integer", "minimum": 0, "maximum": 5},
        "tone": {"type": "string", "enum": ["pale", "gray", "dark"]},
    },
}


def seed_taste_rows() -> list[TasteRow]:
    """Casey's seeded decisions, as ledger rows."""
    return [
        TasteRow(
            id=str(row["id"]),
            at=str(row["at"]),
            author=str(row["author"]),
            status=row["status"],
            subject=dict(row["subject"]),
            artifact_ref=str(row["artifact_ref"]),
            verdict=row["verdict"],
            reason_code=str(row["reason_code"]),
            words=row.get("words"),
            tags=tuple(row.get("tags", ()) or ()),
        )
        for row in TASTE_ROWS
    ]


def _notes(entry_path: str) -> list[TasteNote]:
    """The taste aggregate for one entry, folded from the owner's rows."""
    return aggregate_taste_notes(
        seed_taste_rows(), author="casey", subject_prefix=entry_path
    )


def _provenance(spec_ref: str) -> dict[str, Any]:
    return {
        "origin": "builtin",
        "commit": None,
        "at": "2026-10-30T21:00:00Z",
        "spec_ref": spec_ref,
        "engine_pin": ENGINE_PIN["commit"],
    }


def crates_entry() -> VocabularyEntry:
    """`props.harbor.crates` — the fish crates on the harbour pier."""
    return VocabularyEntry(
        word="props.harbor.crates",
        kind="prop",
        owner_character="prop-maker",
        status="active",
        params=CRATES_PARAMS,
        # The known image-to-3D failure mode for this word: crates hollow from
        # below (R §2). A geometry check runs before the critic (§2.3 step 3),
        # so the template is a watertight check on the called node.
        acceptance_template=AcceptanceCheck(
            kind="geometry",
            spec={"check": "watertight", "tolerance": 0.0, "node": "{node}"},
        ),
        taste_notes=_notes("harbor.crates"),
        provenance=_provenance("docs/design/core-spec.md §6.1"),
        version=1,
    )


def racks_entry() -> VocabularyEntry:
    """`props.harbor.racks` — the drying racks along the pier."""
    return VocabularyEntry(
        word="props.harbor.racks",
        kind="prop",
        owner_character="prop-maker",
        status="active",
        params=RACKS_PARAMS,
        acceptance_template=AcceptanceCheck(
            kind="constraint",
            spec={
                "path": "{node}.params.length_m",
                "op": ">=",
                "value": 0.5,
                "method": "scale_bounds",
            },
        ),
        taste_notes=_notes("harbor.racks"),
        provenance=_provenance("docs/design/core-spec.md §6.1"),
        version=1,
    )


def weathering_entry() -> VocabularyEntry:
    """`material.wood.weathering` — how weathered the harbour timber reads."""
    return VocabularyEntry(
        word="material.wood.weathering",
        kind="material",
        owner_character="prop-maker",
        status="active",
        params=WEATHERING_PARAMS,
        acceptance_template=AcceptanceCheck(
            kind="constraint",
            spec={
                "path": "{node}.params.wear",
                "op": "<=",
                "value": 5,
                "method": "scale_bounds",
            },
        ),
        taste_notes=_notes("wood.weathering"),
        provenance=_provenance("docs/design/core-spec.md §6.1"),
        version=1,
    )


def default_entries() -> tuple[VocabularyEntry, ...]:
    """The three words, as the registry ships them."""
    return (crates_entry(), racks_entry(), weathering_entry())
