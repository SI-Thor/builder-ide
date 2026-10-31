"""The seeded world: Fjellvik, and the history the builders read.

A builder on night one has nothing to read (that is the cold start, spec §3.5).
A builder in an established project has a history: the owner's taste rows and
the builder's own scored bets. This module holds that history so the loop can
be exercised in both states — the melt is mechanical, and the melt starts
somewhere.

Everything here is **seed data**: Fjellvik's recipe document, Casey's taste
rows about it, and the Prop-maker's three earlier bets. The taste rows are
owner-authored (`casey`), and they are the only reason the crates word carries
taste notes with honest denominators.
"""

from __future__ import annotations

from typing import Any

from .hashing import short_hash
from .models import Actor, AuditEvent
from .predictions import seal_hash_for

__all__ = [
    "ENGINE_PIN",
    "RECIPE_DOCUMENT",
    "TASTE_ROWS",
    "PRIOR_BETS",
    "seed_audit_events",
]

#: §1.1 — the pinned engine. `config` is the sha256 of the engine-side config
#: bundle; without it the stage-cache key is not a function of the recipe
#: version (RV patch 13).
ENGINE_PIN: dict[str, Any] = {
    "repo": "SI-Thor/infinigen-thor",
    "commit": "9f31c0e",
    "config": "sha256:cf90a1d4e2b7",
    "blender": "4.2",
    "python": "3.12",
}

#: §1.1 — the recipe. Typed entries, generators, params, constraints, seeds.
RECIPE_DOCUMENT: dict[str, Any] = {
    "id": "rcp_fjellvik",
    "name": "Fjellvik",
    "schema_version": 2,
    "engine_pin": ENGINE_PIN,
    "seeds": {"terrain": 771, "props": 42, "weather": 1904},
    "entries": {
        "harbor.crates": {
            "path": "harbor.crates",
            "kind": "prop_set",
            "generator": {
                "module": "infinigen_thor.structures",
                "func": "crates",
                "variant": None,
                "rev": "9f31c0e",
            },
            "params": {"count": 8, "style": "weathered", "from_library": 4},
            "seed": 42,
            "constraints": [],
            "assets": [],
            "origin": "builtin",
        },
        "harbor.racks": {
            "path": "harbor.racks",
            "kind": "prop_set",
            "generator": {
                "module": "infinigen_thor.structures",
                "func": "racks",
                "variant": None,
                "rev": "9f31c0e",
            },
            "params": {"count": 3, "length_m": 2.4},
            "seed": 42,
            "constraints": [],
            "assets": [],
            "origin": "builtin",
        },
        "wood.weathering": {
            "path": "wood.weathering",
            "kind": "material",
            "generator": {
                "module": "infinigen_thor.materials",
                "func": "weathering",
                "variant": None,
                "rev": "9f31c0e",
            },
            "params": {"wear": 3, "tone": "gray"},
            "seed": 42,
            "constraints": [],
            "assets": [],
            "origin": "builtin",
        },
    },
    "constraints": [],
}

#: Casey's own decisions about Fjellvik's props (T §"Taste note fields").
#: `artifact_ref` points at a branch@commit — a claim about a thing that
#: exists and can be re-rendered, never a conversation.
TASTE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": "tn_0001",
        "at": "2026-10-22T07:12:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0008", "param_path": "harbor.crates.params.count", "value": 12},
        "artifact_ref": "br_main@ver_0112",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0002",
        "at": "2026-10-23T07:31:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0008", "param_path": "harbor.crates.params.count", "value": 8},
        "artifact_ref": "br_main@ver_0131",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0003",
        "at": "2026-10-24T07:44:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0008", "param_path": "harbor.crates.params.count", "value": 14},
        "artifact_ref": "br_main@ver_0140",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0004",
        "at": "2026-10-25T07:19:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0008", "param_path": "harbor.crates.params.count", "value": 10},
        "artifact_ref": "br_main@ver_0151",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0005",
        "at": "2026-10-26T07:52:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0006", "param_path": "harbor.crates.params.count", "value": 6},
        "artifact_ref": "br_main@ver_0163",
        "verdict": "reject",
        "reason_code": "too_empty",
        "words": "sparse reads wrong",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0006",
        "at": "2026-10-27T07:08:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "crates_0004", "param_path": "harbor.crates.params.count", "value": 4},
        "artifact_ref": "br_main@ver_0170",
        "verdict": "reject",
        "reason_code": "too_empty",
        "words": "sparse reads wrong",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0007",
        "at": "2026-10-25T08:03:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "racks_0004", "param_path": "harbor.racks.params.count", "value": 4},
        "artifact_ref": "br_main@ver_0153",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0008",
        "at": "2026-10-26T08:21:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "racks_0003", "param_path": "harbor.racks.params.count", "value": 3},
        "artifact_ref": "br_main@ver_0164",
        "verdict": "keep",
        "reason_code": "too_busy",
        "words": "busy is right",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0009",
        "at": "2026-10-27T08:44:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "racks_0002", "param_path": "harbor.racks.params.count", "value": 2},
        "artifact_ref": "br_main@ver_0172",
        "verdict": "reject",
        "reason_code": "too_empty",
        "words": "sparse reads wrong",
        "tags": ["clutter"],
    },
    {
        "id": "tn_0010",
        "at": "2026-10-25T09:15:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "deck_0001", "param_path": "wood.weathering.params.wear", "value": 4},
        "artifact_ref": "br_main@ver_0156",
        "verdict": "keep",
        "reason_code": "too_flat",
        "words": "flat and weathered",
        "tags": ["material", "age"],
    },
    {
        "id": "tn_0011",
        "at": "2026-10-26T09:02:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "deck_0001", "param_path": "wood.weathering.params.wear", "value": 3},
        "artifact_ref": "br_main@ver_0165",
        "verdict": "keep",
        "reason_code": "too_flat",
        "words": "flat and weathered",
        "tags": ["material", "age"],
    },
    {
        "id": "tn_0012",
        "at": "2026-10-27T09:41:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "deck_0002", "param_path": "wood.weathering.params.wear", "value": 5},
        "artifact_ref": "br_main@ver_0174",
        "verdict": "keep",
        "reason_code": "too_flat",
        "words": "flat and weathered",
        "tags": ["material", "age"],
    },
    {
        "id": "tn_0013",
        "at": "2026-10-28T09:05:00Z",
        "author": "casey",
        "status": "active",
        "subject": {"node_id": "deck_0003", "param_path": "wood.weathering.params.wear", "value": 1},
        "artifact_ref": "br_main@ver_0179",
        "verdict": "reject",
        "reason_code": "too_clean",
        "words": "too new for this pier",
        "tags": ["material", "age"],
    },
)

#: The Prop-maker's own earlier bets, and how they landed. These are what the
#: world gate counts: `material_read` sealed 3, hit 2 → 2/3 hit, "medium".
PRIOR_BETS: tuple[dict[str, Any], ...] = (
    {
        "id": "pr_seed_0001",
        "builder": "prop-maker",
        "at": "2026-10-28T22:14:00Z",
        "branch_ref": "br_night_2026-10-28@ver_0181",
        "claim": "weathered oak reads as weathered on all 12 crates",
        "claim_type": "material_read",
        "confidence": "guess",
        "basis": "0 observations",
        "render_spec": {"rung": 2, "resolution": "480p", "seed": 42},
        "verdict": "hit",
    },
    {
        "id": "pr_seed_0002",
        "builder": "prop-maker",
        "at": "2026-10-29T23:02:00Z",
        "branch_ref": "br_night_2026-10-29@ver_0186",
        "claim": "stained crates read as tar, not as wood",
        "claim_type": "material_read",
        "confidence": "low",
        "basis": "1/1 hit",
        "render_spec": {"rung": 2, "resolution": "480p", "seed": 42},
        "verdict": "hit",
    },
    {
        "id": "pr_seed_0003",
        "builder": "prop-maker",
        "at": "2026-10-29T23:41:00Z",
        "branch_ref": "br_night_2026-10-29@ver_0189",
        "claim": "pale pine reads as new timber on all 8 crates",
        "claim_type": "material_read",
        "confidence": "low",
        "basis": "2/2 hit",
        "render_spec": {"rung": 2, "resolution": "480p", "seed": 42},
        "verdict": "miss",
    },
)


def seed_audit_events() -> list[AuditEvent]:
    """The seeded history as audit events, ready for the ledger.

    The events are appended in the order they happened, so the ledger's
    sequence tells the same story the wall clock does.
    """
    events: list[AuditEvent] = []
    owner = Actor(kind="owner", id="casey")

    for row in TASTE_ROWS:
        events.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'taste.note.appended', 'row': row['id']})}",
                at=row["at"],
                actor=owner,
                type="taste.note.appended",
                subject={"entity_kind": "taste_note", "entity_id": row["id"]},
                payload={"row": dict(row)},
            )
        )

    for bet in PRIOR_BETS:
        sealed_payload = {
            "builder": bet["builder"],
            "at": bet["at"],
            "branch_ref": bet["branch_ref"],
            "claim": bet["claim"],
            "claim_type": bet["claim_type"],
            "confidence": bet["confidence"],
            "basis": bet["basis"],
            "render_spec": bet["render_spec"],
        }

        events.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'prediction.sealed', 'pid': bet['id']})}",
                at=bet["at"],
                actor=Actor(kind="character", id=bet["builder"], via="word"),
                type="prediction.sealed",
                subject={"entity_kind": "prediction", "entity_id": bet["id"]},
                payload={
                    "prediction_id": bet["id"],
                    "seal_hash": seal_hash_for(sealed_payload),
                    "claim_type": bet["claim_type"],
                    "namespace": "world",
                    "sealed_payload": sealed_payload,
                },
            )
        )
        events.append(
            AuditEvent(
                seq=0,
                id=f"aud_{short_hash({'type': 'prediction.scored', 'pid': bet['id']})}",
                at=bet["at"],
                actor=Actor(kind="critic", id="critic-local"),
                type="prediction.scored",
                subject={"entity_kind": "prediction", "entity_id": bet["id"]},
                payload={
                    "prediction_id": bet["id"],
                    "verdict": bet["verdict"],
                    "seal_hash": seal_hash_for(sealed_payload),
                },
            )
        )
    return events
