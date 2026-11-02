"""The skill library — the tiles, and the ledger events that carry them.

A Voyager skill is a program. Our skill library is **our tiles**
(``core/tiles``), because the tiles already hold the three properties
the brief asks for:

* **content addressed** — a skill's id is the hash of its body, so the
  same program is the same skill whoever wrote it;
* **versioned by family** — a new program for the same goal is the
  family's next version, and the old one is *retired*, not deleted;
* **the log is the source of truth** — the library is a fold over the
  audit log, so a skill's history can be replayed and a run can be
  rewound.

How a program becomes a tile
----------------------------

A tile's content hash covers its body, so the program has to be inside
it. It goes in as a **step**: the ``voyager.skill_body`` word carries
the body's content hash and its length, and one step per primitive
records which closed-vocabulary words the program calls. The program
itself lives in the skill store, content addressed, beside the log.

One ledger event per skill
--------------------------

The brief asks for **one** event per skill, with the disposition
(``admitted`` / ``rejected`` / ``superseded``) on it. The event set is
closed (``core.records.EVENT_TYPES``) and the drift detector already
reads the two tile types, so the mapping uses them rather than widening
the schema:

| disposition | event | meaning |
|---|---|---|
| ``admitted`` | ``tile.authored`` | the skill entered the library |
| ``rejected`` | ``tile.retired`` | the skill was refused; it never entered |
| ``superseded`` | ``tile.retired`` | a newer version of the family replaced it |

A rejected skill's ``tile.retired`` row names a tile the log never
authored, and the fold ignores it — ``core.tiles.library.fold_library``
retires only a tile it holds. That is the behaviour we want: the refusal
is on the log, and the library is unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from core.canon import content_hash, now_utc
from core.records import Actor
from core.tiles.library import MAX_PAYLOAD_BYTES, TileLibrary, fold_library
from core.tiles.models import (
    Outcome,
    PlayCost,
    Tile,
    TileAuthor,
    TileRefusal,
    build_tile,
)
from core.tiles.plays import record_play
from core.tiles.ports import LedgerPort

from .models import Disposition, SkillProposal, SkillRecord
from .vocab import BODY_SCHEMA, BODY_WORD, SkillVocabulary, body_step, primitive_step

__all__ = [
    "SkillLibrary",
    "SKILL_ACTOR",
    "body_sha256",
    "fold_skills",
]

#: Who writes the skill rows. The core is the only writer (§1.0); this
#: seat writes as the core, on behalf of the skill.
SKILL_ACTOR = Actor(kind="core", id="voyager", via="skill")


def body_sha256(code: str) -> str:
    """The content hash of a skill's body, in the house's form."""
    return content_hash(code)


class SkillLibrary:
    """The skills, as tiles, with their bodies kept beside them.

    The library holds three things:

    * a ``core.tiles.TileLibrary`` — the tiles, content addressed and
      versioned;
    * a **body store** on disk — the programs, content addressed, so the
      same program is stored once however many skills point at it;
    * the **ledger** — one event per skill, and one event per play.
    """

    def __init__(
        self,
        *,
        registry: SkillVocabulary,
        ledger: LedgerPort | None = None,
        bodies_dir: Path | str = "skills",
        adapter: str = "",
        clock=None,
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._bodies = Path(bodies_dir)
        self._bodies.mkdir(parents=True, exist_ok=True)
        self._clock = clock or now_utc
        self._adapter = adapter
        # The tile library carries the ledger, so ``tile.authored`` and
        # ``tile.retired`` are written by the library itself — the
        # invariants (never deleted, one event per state change) are
        # the library's, not this seat's.
        self._tiles = TileLibrary(registry=registry, ledger=ledger)
        # A ledger-less staging library, used to record the play of a
        # skill that was **rejected**: the play has to be on the log
        # (the drift detector reads it) but the skill never entered the
        # library, so it is staged rather than admitted.
        self._staging = TileLibrary(registry=registry, ledger=None)
        self._records: dict[str, SkillRecord] = {}

    # -- the body store --------------------------------------------------------

    def store_body(self, code: str) -> tuple[str, Path]:
        """Write a body into the store, and say where it went.

        The file's name is the body's hash, so the same program is one
        file however many skills use it.
        """
        digest = body_sha256(code)
        path = self._bodies / f"{digest.replace(':', '_')}.txt"
        if not path.exists():
            path.write_text(code)
        return digest, path

    def read_body(self, digest: str) -> str:
        """The body behind a hash, or ``""`` when it is not in the store."""
        path = self._bodies / f"{digest.replace(':', '_')}.txt"
        if not path.exists():
            return ""
        return path.read_text()

    def bodies(self) -> dict[str, str]:
        """Every body in the store, by hash."""
        out: dict[str, str] = {}
        for path in sorted(self._bodies.glob("*.txt")):
            out[f"sha256:{path.stem}"] = path.read_text()
        return out

    # -- the writes ------------------------------------------------------------

    def submit(
        self,
        proposal: SkillProposal,
        *,
        author_model: str,
        author_role: str = "coder",
        prompt_hash: str = "",
        disposition: Disposition = "admitted",
        reason: str = "",
    ) -> SkillRecord:
        """Take a proposed skill and give it a disposition.

        The caller has already run the skill and judged it; this is the
        write half.

        **One event per skill's disposition.** An admitted skill writes
        ``tile.authored`` and enters the library. A rejected skill writes
        ``tile.retired`` with the reason prefixed ``rejected:``, for a
        tile the log never authored — so the fold leaves the library
        unchanged and the refusal is still on the log. A skill that a
        later skill supersedes is retired with ``superseded:<id>``.

        The **plays** are the second stream: one ``tile.played`` row per
        execution, including the executions that failed, because the
        drift detector's success signal is computed from the plays and a
        failure that is not on the log is a failure nobody can see.
        """
        digest, path = self.store_body(proposal.code)
        try:
            tile = self._build_tile(
                proposal, digest, path.stat().st_size, author_model, prompt_hash,
                author_role,
            )
        except TileRefusal as exc:
            # The static door refused the body: the skill never enters,
            # and the refusal is the record.
            stub = self._stub_tile(proposal, digest, author_model, prompt_hash)
            return self._record_rejection(
                stub, proposal, f"door:{exc.reason}", author_model, author_role, prompt_hash
            )

        if disposition == "rejected":
            staged = self._staging.add(tile)
            return self._record_rejection(
                staged, proposal, reason, author_model, author_role, prompt_hash
            )

        # Admitted: a new version of the family retires the old one.
        superseded = self._supersede_family(tile)
        try:
            stamped = self._tiles.add(tile)
        except TileRefusal as exc:
            # The door refused the tile: the skill does not enter, and
            # the refusal is the record.
            staged = self._staging.add(tile)
            return self._record_rejection(
                staged, proposal, f"door:{exc.reason}", author_model, author_role, prompt_hash
            )

        record = SkillRecord(
            id=stamped.id,
            title=stamped.title,
            family=stamped.family,
            version=stamped.version,
            disposition="admitted",
            milestone=proposal.milestone,
            body_sha256=digest,
            author_model=author_model,
            author_role=author_role,
            prompt_hash=prompt_hash,
            created_at=stamped.created_at,
        )
        self._records[stamped.id] = record
        if superseded is not None:
            self._records[superseded.id] = SkillRecord(
                id=superseded.id,
                title=superseded.title,
                family=superseded.family,
                version=superseded.version,
                disposition="superseded",
                milestone=superseded.provenance.get("milestone", ""),
                body_sha256=str(superseded.provenance.get("body_sha256", "")),
                author_model=superseded.author.model,
                author_role=str(superseded.provenance.get("author_role", "")) or "coder",
                prompt_hash=superseded.author.prompt_hash,
                created_at=superseded.created_at,
                reason=f"superseded:{stamped.id}",
                superseded_by=stamped.id,
            )
        return record

    def retire(self, tile_id: str, *, reason: str) -> SkillRecord:
        """Retire an admitted skill by hand."""
        tile = self._tiles.retire(tile_id, reason=reason)
        record = self._records.get(tile_id)
        if record is None:
            return SkillRecord(
                id=tile.id,
                title=tile.title,
                family=tile.family,
                version=tile.version,
                disposition="superseded",
                milestone=str(tile.provenance.get("milestone", "")),
                body_sha256=str(tile.provenance.get("body_sha256", "")),
                author_model=tile.author.model,
                author_role=str(tile.provenance.get("author_role", "")) or "coder",
                prompt_hash=tile.author.prompt_hash,
                created_at=tile.created_at,
                reason=reason,
            )
        updated = replace(record, disposition="superseded", reason=reason)
        self._records[tile_id] = updated
        return updated

    def record_play(
        self,
        *,
        tile_id: str,
        context: Mapping[str, Any],
        outcome: Outcome,
        cost: PlayCost | None = None,
        chooser: str = "voyager",
        at: str | None = None,
        scope: str | None = None,
    ) -> Any:
        """Record one use of a skill.

        The play is a ``tile.played`` row, which is what the drift
        detector reads: the gap between consecutive plays is the stall
        signal, and the outcome is the success signal. The attribution
        is ``context.bot`` — the name of the agent that played it.

        A skill that was **rejected** is not in the library, but its
        execution is still on the log: the play is recorded against the
        staging library, which holds the proposal without ever having
        authored it. The fold ignores the play, and the library is
        unchanged.
        """
        if self._ledger is None:
            # A library without a ledger is a plain store: there is
            # nowhere to write the play, and the run says so rather
            # than losing it quietly.
            return None
        tile = self._tiles.get(tile_id)
        library = self._tiles
        if tile is None:
            tile = self._staging.require(tile_id)
            library = self._staging
        return record_play(
            ledger=self._ledger,
            library=library,
            tile=tile,
            context=context,
            outcome=outcome,
            cost=cost,
            chooser=chooser,
            night=None,
            at=at,
            scope=scope,
        )

    # -- the reads -------------------------------------------------------------

    def tiles(self) -> tuple[Tile, ...]:
        return self._tiles.tiles()

    def active(self) -> tuple[Tile, ...]:
        return self._tiles.active()

    def records(self) -> tuple[SkillRecord, ...]:
        return tuple(self._records[k] for k in sorted(self._records))

    def counts(self) -> dict[str, int]:
        """How many skills ended each way.

        A skill has **one** disposition, so the three numbers are the
        three dispositions and they add up to the number of skills:

        * ``admitted`` — the skills that entered the library (the ones
          still active plus the ones a later skill superseded);
        * ``rejected`` — the skills the door or the verifier refused;
        * ``superseded`` — the admitted skills a later skill replaced.
        """
        out = {"admitted": 0, "rejected": 0, "superseded": 0, "active": 0}
        for record in self._records.values():
            if record.disposition == "rejected":
                out["rejected"] += 1
                continue
            out["admitted"] += 1
            if record.disposition == "superseded":
                out["superseded"] += 1
            else:
                out["active"] += 1
        return out

    # -- internals -------------------------------------------------------------

    def _build_tile(
        self,
        proposal: SkillProposal,
        digest: str,
        nbytes: int,
        author_model: str,
        prompt_hash: str,
        author_role: str = "coder",
    ) -> Tile:
        primitives = self._registry_primitives(proposal.code)
        steps = [body_step(digest, nbytes)]
        for word in primitives:
            steps.append(primitive_step(word))
        author = TileAuthor(
            model=author_model,
            provider="deepinfra",
            prompt_hash=prompt_hash or digest,
            temperature=None,
        )
        return build_tile(
            family=proposal.family,
            kind="behaviour",
            title=proposal.title,
            steps=tuple(steps),
            author=author,
            provenance={
                "milestone": proposal.milestone,
                "language": proposal.language,
                "body_sha256": digest,
                "primitives": list(primitives),
                "adapter": self._adapter,
                "description": proposal.description,
                "author_role": author_role,
            },
        )

    def _stub_tile(
        self,
        proposal: SkillProposal,
        digest: str,
        author_model: str,
        prompt_hash: str,
    ) -> Tile:
        """A tile for a body the door refused.

        It carries the body hash and nothing else, which is enough to
        name the skill on the log: the refusal is what is being
        recorded, not the program.
        """
        author = TileAuthor(
            model=author_model,
            provider="deepinfra",
            prompt_hash=prompt_hash or digest,
            temperature=None,
        )
        return build_tile(
            family=proposal.family,
            kind="behaviour",
            title=proposal.title or "rejected skill",
            steps=(body_step(digest, max(1, len(proposal.code))),),
            author=author,
            provenance={
                "milestone": proposal.milestone,
                "language": proposal.language,
                "body_sha256": digest,
                "primitives": [],
                "adapter": self._adapter,
                "description": proposal.description,
            },
        )

    def _registry_primitives(self, code: str) -> tuple[str, ...]:
        """The primitives the body calls, read out of its text.

        The scan is the **static door**: a name that is not a primitive
        of this world is refused here, before the body ever runs. The
        sandbox is the second door, for the calls a text scan cannot
        see.
        """
        from .vocab import scan_primitives

        known = self._registry.words()
        namespace = known[0].split(".")[0] if known else "mc"
        used = scan_primitives(code, namespace=namespace)
        unknown = [name for name in used if name not in known]
        if unknown:
            raise TileRefusal(
                "primitive_unknown",
                f"{unknown[0]!r} is not a primitive of this world; the known ones are "
                + ", ".join(known),
            )
        return used

    def _supersede_family(self, tile: Tile) -> Tile | None:
        """Retire the active skill of the same family, if there is one.

        The retirement is written by the tile library, so the log gets a
        ``tile.retired`` row whose reason is ``superseded:<new id>`` —
        the disposition is the reason's prefix, which is how the fold
        and the report both read it.
        """
        for existing in self._tiles.active():
            if existing.family != tile.family:
                continue
            if existing.id == tile.id:
                continue
            return self._tiles.retire(existing.id, reason=f"superseded:{tile.id}")
        return None

    def _record_rejection(
        self,
        tile: Tile,
        proposal: SkillProposal,
        reason: str,
        author_model: str,
        author_role: str,
        prompt_hash: str,
    ) -> SkillRecord:
        """Write the refusal on the log, and return the record.

        The event is a ``tile.retired`` row for a tile the log never
        authored. The fold ignores it, so the library is unchanged and
        the refusal is still on the log — the edges are the story.
        """
        detail = reason or "rejected"
        if self._ledger is not None:
            self._ledger.append(
                type="tile.retired",
                actor=SKILL_ACTOR,
                subject={"entity_kind": "tile", "entity_id": tile.id},
                payload={
                    "tile_id": tile.id,
                    "family": tile.family,
                    "version": 1,
                    "kind": "behaviour",
                    "title": tile.title,
                    "reason": f"rejected:{detail}",
                    "disposition": "rejected",
                    "milestone": proposal.milestone,
                    "body_sha256": str(tile.provenance.get("body_sha256", "")),
                    "author_model": author_model,
                    "prompt_hash": prompt_hash,
                    "retired_at": self._clock(),
                },
            )
        record = SkillRecord(
            id=tile.id,
            title=tile.title,
            family=tile.family,
            version=1,
            disposition="rejected",
            milestone=proposal.milestone,
            body_sha256=str(tile.provenance.get("body_sha256", "")),
            author_model=author_model,
            author_role=author_role,
            prompt_hash=prompt_hash,
            created_at=self._clock(),
            reason=detail,
        )
        self._records[tile.id] = record
        return record


def fold_skills(
    events: Sequence[Any],
    *,
    registry: SkillVocabulary,
    clock=None,
) -> SkillLibrary:
    """Rebuild the skill library from the log.

    The log is the source of truth, so this is how a run is rewound: the
    same log always folds into the same library. The bodies themselves
    are in the body store, not in the log — a program is bigger than the
    ledger's payload cap, and a truncated program is not a program.
    """
    library = SkillLibrary(registry=registry, ledger=None, clock=clock)
    tiles = fold_library(events, registry=registry, clock=clock)
    library._tiles = tiles
    for tile in tiles.tiles():
        library._records[tile.id] = SkillRecord(
            id=tile.id,
            title=tile.title,
            family=tile.family,
            version=tile.version,
            disposition="admitted" if tile.status == "active" else "superseded",
            milestone=str(tile.provenance.get("milestone", "")),
            body_sha256=str(tile.provenance.get("body_sha256", "")),
            author_model=tile.author.model,
            author_role=str(tile.provenance.get("author_role", "")) or "coder",
            prompt_hash=tile.author.prompt_hash,
            created_at=tile.created_at,
            reason=tile.retire_reason or "",
        )
    for event in events:
        if getattr(event, "type", None) != "tile.retired":
            continue
        payload = getattr(event, "payload", {}) or {}
        if str(payload.get("disposition", "")) != "rejected":
            continue
        tile_id = str(payload.get("tile_id", ""))
        library._records[tile_id] = SkillRecord(
            id=tile_id,
            title=str(payload.get("title", "")),
            family=str(payload.get("family", "")),
            version=int(payload.get("version", 1)),
            disposition="rejected",
            milestone=str(payload.get("milestone", "")),
            body_sha256=str(payload.get("body_sha256", "")),
            author_model=str(payload.get("author_model", "")),
            author_role="coder",
            prompt_hash=str(payload.get("prompt_hash", "")),
            created_at=str(payload.get("retired_at", "")),
            reason=str(payload.get("reason", "")),
        )
    return library
