"""The ``.nail`` export: a tile library and its chooser, portable and addressed.

**What this is.** `quilt-pincher` ships its reflex store as a ``.nail``
bundle: the reflexes, the veto rules, the compile history and the
provenance, content-addressed, so the same sheet runs in the cloud, on a
workstation and on an ESP32. This module writes the same *shape* for a tile
library, and adds the one thing pincher does not have: **the chooser**.

**Why the chooser travels with the tiles.** A library is half the answer.
What makes a library *good* is which tile it picks in which context, and
that knowledge lives in the chooser's estimates — a set of numbers that are
worth nothing on their own and everything next to the tiles they are about.
A bundle that carries the tiles but not the chooser would describe the
options and not the decisions, and the reader would have to relearn the
decisions from scratch.

**Why the fields keep pincher's names.** The two bundles are meant to be
comparable — a reader who knows one should be able to read the other. So the
field names are the same (``version``, ``reflexes``, ``vetoRules``,
``compileHistory``, ``metadata``) and the mapping is written down here:

===================  =========================================================
pincher              this bundle
===================  =========================================================
``reflex``           a **tile** — one script in the closed vocabulary. It is
                     a reflex in pincher's sense: an action compiled once by
                     a language model, then reused for free.
``embedding``        the tile's embedding — the same vector the retrieval
                     front matches against.
``intent``           the tile's title: what the reflex is for.
``action``           the tile's body: the script, in the typed vocabulary.
``safety``           the tile's preconditions — what has to hold before it
                     may be played. Pincher's veto rules are a sandbox and a
                     capability manifest; ours is stricter, because a tile
                     never runs code (see :mod:`core.tiles.door`).
``provenance``       who wrote the tile, which model, which prompt hash —
                     the same fields :class:`core.tiles.models.TileAuthor`
                     already keeps.
``compileHistory``   when each tile was authored, and which reflex it
                     produced.
``vetoRules``        the families the bundle may use, as hard rules.
``metadata.tier``    the bundle's tier, for a reader that runs more than one.
===================  =========================================================

**The hash is a promise about the whole body.** The bundle's content hash
covers the reflexes, the rules, the history, the metadata and the chooser
state — so a changed tile, a changed threshold or a changed estimate gives a
different hash, and the same bundle always gives the same one. The hash
covers the **embedder's record** too, because the embeddings in it were made
by that embedder: a bundle whose vectors came from a different model is a
different bundle, and the metadata says which model that was.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.canon import content_hash, now_utc

from .library import TileLibrary
from .models import Tile
from .retrieval import Embedder, describe_tile, embedder_record

__all__ = [
    "NAIL_FORMAT",
    "NAIL_VERSION",
    "NailBundle",
    "export_nail",
    "read_nail",
    "write_nail",
]


#: The format tag on every bundle this module writes.
NAIL_FORMAT = "nail"

#: The bundle's own version — the format, not the library.
NAIL_VERSION = "1"

#: How many decimals an embedding keeps in the file. Six is well past the
#: precision any retrieval decision uses, and it keeps the bundle small
#: enough to ship.
_EMBEDDING_PRECISION = 6


@dataclass(frozen=True)
class NailBundle:
    """A portable, content-addressed sheet of tiles and their chooser."""

    format: str = NAIL_FORMAT
    version: str = NAIL_VERSION
    reflexes: list[dict[str, Any]] = field(default_factory=list)
    vetoRules: list[dict[str, Any]] = field(default_factory=list)
    compileHistory: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    chooser: dict[str, Any] | None = None

    def body(self) -> dict[str, Any]:
        """What the content hash covers."""
        return {
            "format": self.format,
            "version": self.version,
            "reflexes": self.reflexes,
            "vetoRules": self.vetoRules,
            "compileHistory": self.compileHistory,
            "metadata": self.metadata,
            "chooser": self.chooser,
        }

    @property
    def content_hash(self) -> str:
        """``sha256:…`` over the whole body."""
        return content_hash(self.body())

    def to_json(self) -> str:
        """The bundle as JSON text, with the hash beside the body."""
        payload = self.body()
        payload["contentHash"] = self.content_hash
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "NailBundle":
        """Read a bundle back. The hash is recomputed, never trusted."""
        payload = json.loads(text)
        return cls(
            format=str(payload.get("format", NAIL_FORMAT)),
            version=str(payload.get("version", NAIL_VERSION)),
            reflexes=list(payload.get("reflexes") or []),
            vetoRules=list(payload.get("vetoRules") or []),
            compileHistory=list(payload.get("compileHistory") or []),
            metadata=dict(payload.get("metadata") or {}),
            chooser=payload.get("chooser"),
        )


def export_nail(
    *,
    library: TileLibrary,
    name: str,
    chooser: Any | None = None,
    embedder: Embedder | None = None,
    tier: str = "unknown",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> NailBundle:
    """Export a tile library, and the chooser that picks from it.

    **Only the active tiles are exported.** A retired tile is history, not
    an option: it stays in the library and in the log, but a reader that
    loaded the bundle would be offered something the library has already
    rejected. The count of the retired is in the metadata, so nothing is
    hidden.

    The embedder's record goes into the metadata and into every reflex's
    provenance: the embeddings in the bundle are only meaningful next to the
    model that made them.
    """
    if embedder is None:
        from .retrieval import default_embedder

        embedder = default_embedder()
    record = embedder_record(embedder)

    active = library.active()
    retired = len(library.tiles()) - len(active)

    vectors = _embed_tiles(active, embedder)

    reflexes: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for tile in active:
        reflex = _reflex(tile, vectors[tile.id], record)
        reflexes.append(reflex)
        history.append(
            {
                "trigger": "tile.authored",
                "reflexId": reflex["id"],
                "ts": tile.created_at,
            }
        )

    stamp = created_at or now_utc()
    metadata: dict[str, Any] = {
        "name": name,
        "createdAt": _created_at(active, stamp),
        "updatedAt": updated_at or _updated_at(active, stamp),
        "tier": tier,
        "retired": retired,
        "embedder": record,
        "tiles": len(active),
        "families": list(library.families()),
        "format": NAIL_FORMAT,
    }

    return NailBundle(
        reflexes=reflexes,
        vetoRules=_veto_rules(active),
        compileHistory=history,
        metadata=metadata,
        chooser=_chooser_state(chooser),
    )


def write_nail(path: str | Path, bundle: NailBundle) -> Path:
    """Write a bundle to a file, and return where it went."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bundle.to_json(), encoding="utf-8")
    return target


def read_nail(path: str | Path) -> NailBundle:
    """Read a bundle back from a file.

    The stored hash is **not** trusted: it is recomputed from the body, so
    a bundle that was edited on disk reads back with the hash of what it now
    says, not the hash of what it used to say.
    """
    return NailBundle.from_json(Path(path).read_text(encoding="utf-8"))


# --- internals ----------------------------------------------------------------


def _created_at(tiles: Sequence[Tile], fallback: str) -> str:
    """When the bundle's content first existed: the oldest tile's own stamp.

    **The bundle's timestamps are part of its content, not the clock.** A
    wall-clock stamp would make every export of the same library a
    different bundle, and the hash would stop being an address — it would
    be a timestamp with a hash on it. So the bundle says when its oldest
    tile was authored and when its newest one was, and re-exporting an
    unchanged library gives back the same bundle, byte for byte.
    """
    if not tiles:
        return fallback
    return min(tile.created_at for tile in tiles)


def _updated_at(tiles: Sequence[Tile], fallback: str) -> str:
    """When the bundle's content last changed: the newest tile's stamp."""
    if not tiles:
        return fallback
    return max(tile.created_at for tile in tiles)


def _embed_tiles(tiles: Sequence[Tile], embedder: Embedder) -> dict[str, list[float]]:
    """The embedding of every tile, in one batch."""
    if not tiles:
        return {}
    vectors = embedder.embed([describe_tile(tile) for tile in tiles])
    return {
        tile.id: [round(float(value), _EMBEDDING_PRECISION) for value in vectors[row]]
        for row, tile in enumerate(tiles)
    }


def _reflex(tile: Tile, embedding: list[float], record: Mapping[str, Any]) -> dict[str, Any]:
    """One tile, as a reflex.

    The id is the content hash of the reflex body, so the same script in the
    same library always has the same id, and a reader can check that the
    bundle it holds is the bundle it was given.
    """
    body: dict[str, Any] = {
        "intent": tile.title,
        "action": tile.body(),
        "embedding": embedding,
        "provenance": {
            "compiledBy": f"{tile.author.provider}/{tile.author.model}",
            "parentReflex": None,
            "tileId": tile.id,
            "tileVersion": tile.version,
            "author": tile.author.model_dump(),
            "promptHash": tile.author.prompt_hash,
            "embedder": dict(record),
        },
        "safety": {
            "preconditions": [
                precondition.model_dump() for precondition in tile.preconditions
            ],
            "kind": tile.kind,
            "words": list(tile.words),
        },
        "confidence": None,
        "hits": 0,
        "createdAt": tile.created_at,
        "lastHitAt": None,
    }
    return {"id": content_hash(body), **body}


def _veto_rules(tiles: Sequence[Tile]) -> list[dict[str, Any]]:
    """The rules that say what this bundle may be used for.

    One hard rule per family — a tile from another family is not in this
    bundle — and one rule when the tiles carry preconditions, because those
    are the conditions under which they may be played at all.
    """
    rules: list[dict[str, Any]] = []
    families = sorted({tile.family for tile in tiles})
    for family in families:
        rules.append({"rule": f"family:{family}", "severity": "hard"})
    if any(tile.preconditions for tile in tiles):
        rules.append({"rule": "preconditions", "severity": "hard"})
    return rules


def _chooser_state(chooser: Any | None) -> dict[str, Any] | None:
    """The chooser's state, as it would need to be to keep choosing.

    The estimates are the point: a chooser with no estimates is a chooser
    that has to start again. The arms are what it has learned, per context
    bucket, with the denominator kept.
    """
    if chooser is None:
        return None

    state: dict[str, Any] = {
        "name": getattr(chooser, "name", ""),
        "version": getattr(chooser, "version", ""),
    }

    feature_keys = getattr(chooser, "feature_keys", None)
    if feature_keys is not None:
        state["featureKeys"] = [str(key) for key in feature_keys]

    current_epsilon = getattr(chooser, "current_epsilon", None)
    if callable(current_epsilon):
        state["epsilon"] = float(current_epsilon())
    elif hasattr(chooser, "epsilon"):
        state["epsilon"] = float(chooser.epsilon)

    for attribute, key in (
        ("epsilon_decay", "epsilonDecay"),
        ("min_epsilon", "minEpsilon"),
        ("prior", "prior"),
    ):
        if hasattr(chooser, attribute):
            state[key] = float(getattr(chooser, attribute))

    plays = getattr(chooser, "plays", None)
    if callable(plays):
        state["plays"] = int(plays())

    stats = getattr(chooser, "stats", None)
    if callable(stats):
        summary = stats()
        state["arms"] = summary.get("buckets", {})
        state["overall"] = summary.get("overall", {})
    else:
        state["arms"] = {}
    return state
