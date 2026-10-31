"""The library — the options, content addressed and versioned (§2 of the design).

Rules, all of them load-bearing:

1. **Content addressing.** A tile's id is the hash of its body, so the same
   script written twice is the same tile: adding it again is a no-op, not a
   second version.
2. **Versioning.** A tile belongs to a *family* — what it is for. A new body
   in a family is the family's next version, and the **library** assigns the
   number. The author does not get to claim a version.
3. **No deletion.** ``delete`` is refused, always. A tile leaves the eligible
   set by being **retired**, with a reason and a timestamp; its body, its
   plays and its history stay.
4. **The log is the source of truth.** With a ledger wired, the library
   writes ``tile.authored`` and ``tile.retired``; without one it is a plain
   store. Either way the library can be **folded back out of the log**
   (:func:`fold_library`), and the two agree.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, NoReturn, Sequence

from core.canon import canonical_bytes, now_utc
from core.records import Actor

from .door import validate_tile
from .models import Tile, TileRefusal
from .ports import LedgerPort, VocabularyPort

__all__ = ["TileLibrary", "fold_library", "MAX_PAYLOAD_BYTES"]

#: §1.8 — the ledger's payload cap. A tile bigger than this belongs in
#: artifacts/ and is hash-referenced; it is not admitted in pieces.
MAX_PAYLOAD_BYTES = 4096

#: Who writes the tile rows. The core is the only writer (core-spec §1.0);
#: the tiles seat writes as the core, on behalf of the tile.
CORE_ACTOR = Actor(kind="core", id="tiles", via="tile")


class TileLibrary:
    """The options a decision model may choose between."""

    def __init__(
        self,
        *,
        registry: VocabularyPort,
        ledger: LedgerPort | None = None,
        clock: Callable[[], str] = now_utc,
        tiles: Iterable[Tile] = (),
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._clock = clock
        self._tiles: dict[str, Tile] = {}
        for tile in tiles:
            self._add(tile, write_log=False)

    # -- the writes ------------------------------------------------------------

    def add(self, tile: Tile) -> Tile:
        """Admit a tile.

        The tile goes through the door first: the vocabulary admits it or the
        library refuses it. Then it is stamped with its version and kept.
        Adding a tile that is already in the library returns the tile that is
        there — content addressing, not an error.
        """
        validate_tile(tile, self._registry)
        return self._add(tile, write_log=True)

    def retire(self, tile_id: str, *, reason: str) -> Tile:
        """Retire a tile: it stops being an option, and it stays (§2)."""
        tile = self.require(tile_id)
        if tile.status == "retired":
            raise TileRefusal(
                "already_retired", f"{tile_id} was retired at {tile.retired_at}"
            )
        retired = tile.retired(reason=reason, at=self._clock())
        self._tiles[tile_id] = retired
        if self._ledger is not None:
            self._ledger.append(
                type="tile.retired",
                actor=CORE_ACTOR,
                subject={"entity_kind": "tile", "entity_id": tile_id},
                payload={
                    "tile_id": tile_id,
                    "family": retired.family,
                    "version": retired.version,
                    "reason": reason,
                    "retired_at": retired.retired_at,
                },
            )
        return retired

    def delete(self, tile_id: str) -> NoReturn:
        """Refused, always. Tiles are retired, never deleted (§2)."""
        raise TileRefusal(
            "tiles_are_never_deleted",
            f"{tile_id} is retired with a reason, not deleted",
        )

    # -- the reads -------------------------------------------------------------

    def get(self, tile_id: str) -> Tile | None:
        return self._tiles.get(tile_id)

    def require(self, tile_id: str) -> Tile:
        tile = self._tiles.get(tile_id)
        if tile is None:
            raise TileRefusal("tile_unknown", f"{tile_id!r} is not in the library")
        return tile

    def tiles(self) -> tuple[Tile, ...]:
        """Every tile the library holds, retired ones included."""
        return tuple(sorted(self._tiles.values(), key=lambda t: t.id))

    def active(self) -> tuple[Tile, ...]:
        """The tiles that are still options."""
        return tuple(tile for tile in self.tiles() if tile.status == "active")

    def versions(self, family: str) -> tuple[Tile, ...]:
        """Every version of a family, oldest first."""
        found = [tile for tile in self._tiles.values() if tile.family == family]
        return tuple(sorted(found, key=lambda t: (t.version, t.id)))

    def families(self) -> tuple[str, ...]:
        """The families the library holds, in order."""
        return tuple(sorted({tile.family for tile in self._tiles.values()}))

    def eligible(self, context: Mapping[str, Any]) -> tuple[Tile, ...]:
        """The options for this context: active, and their preconditions hold."""
        return tuple(
            tile for tile in self.active() if tile.is_eligible(context)
        )

    # -- internals -------------------------------------------------------------

    def _add(self, tile: Tile, *, write_log: bool) -> Tile:
        existing = self._tiles.get(tile.id)
        if existing is not None:
            # Content addressing: the same script is the same tile. Adding it
            # again changes nothing — it is not a new version.
            return existing

        stamped = tile.at_version(self._next_version(tile.family))
        self._tiles[stamped.id] = stamped

        if write_log and self._ledger is not None:
            payload = _authored_payload(stamped)
            if len(canonical_bytes(payload)) > MAX_PAYLOAD_BYTES:
                # Refuse rather than truncate: a half-written tile is not a
                # tile, and the ledger would spill it to artifacts/ anyway.
                self._tiles.pop(stamped.id, None)
                raise TileRefusal(
                    "tile_payload_too_large",
                    f"{stamped.id} does not fit in {MAX_PAYLOAD_BYTES} bytes",
                )
            self._ledger.append(
                type="tile.authored",
                actor=CORE_ACTOR,
                subject={"entity_kind": "tile", "entity_id": stamped.id},
                payload=payload,
            )
        return stamped

    def _next_version(self, family: str) -> int:
        versions = [tile.version for tile in self._tiles.values() if tile.family == family]
        return (max(versions) + 1) if versions else 1


def _authored_payload(tile: Tile) -> dict[str, Any]:
    """The payload of a ``tile.authored`` row."""
    return {
        "tile_id": tile.id,
        "family": tile.family,
        "version": tile.version,
        "kind": tile.kind,
        "title": tile.title,
        "body": tile.body(),
        "content_hash": tile.content_hash,
        "provenance": dict(tile.provenance),
        "created_at": tile.created_at,
    }


def fold_library(
    events: Sequence[Any],
    *,
    registry: VocabularyPort | None = None,
    clock: Callable[[], str] = now_utc,
) -> TileLibrary:
    """Rebuild a library from the audit log (§2).

    The log is the source of truth, so the library is a projection of it.
    A ``tile.authored`` row brings a tile back; a ``tile.retired`` row
    retires it again. The same log always folds into the same library.
    """
    library = TileLibrary(registry=registry, clock=clock) if registry else None
    if library is None:
        raise ValueError("folding a library needs the vocabulary registry")

    for event in events:
        event_type = getattr(event, "type", None)
        payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
        if event_type == "tile.authored":
            tile = _tile_from_payload(payload)
            library.add(tile)
        elif event_type == "tile.retired":
            tile_id = str(payload.get("tile_id", ""))
            reason = str(payload.get("reason", "retired"))
            if library.get(tile_id) is not None:
                library.retire(tile_id, reason=reason)
    return library


def _tile_from_payload(payload: Mapping[str, Any]) -> Tile:
    """Rebuild a tile from a ``tile.authored`` payload."""
    from .models import TileAuthor, TileStep, Precondition

    body = payload.get("body") or {}
    author = TileAuthor.model_validate(body.get("author") or {})
    steps = tuple(TileStep.model_validate(step) for step in body.get("steps", []))
    preconditions = tuple(
        Precondition.model_validate(p) for p in body.get("preconditions", [])
    )
    return Tile(
        id=str(payload.get("tile_id", "")),
        family=str(payload.get("family", "")),
        version=int(payload.get("version", 1)),
        kind=str(payload.get("kind", "recipe_edit")),  # type: ignore[arg-type]
        title=str(payload.get("title", "")),
        steps=steps,
        preconditions=preconditions,
        author=author,
        provenance=dict(payload.get("provenance") or {}),
        created_at=str(payload.get("created_at", "")),
    )
