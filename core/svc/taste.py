"""The taste ledger (§1.7): append-only, single writer — the owner only.
Magnus's rows are author-scoped, never merged into Casey's, never in any
slice a model reads (§7.6); his pre-ratification rows are inert. Export
and erase are mechanisms, not promises: erase is ONE transaction that
redacts the author's taste-event payloads and appends the compensating
taste.erased event (§1.0's single immutability exception)."""
from __future__ import annotations

from ..canon import new_id
from ..errors import NotFound, Refused
from ..events import Actor
from ..models import TasteNote

REASON_CODES = frozenset({
    "too_busy", "too_empty", "wrong_scale", "too_messy", "too_clean", "too_flat",
    "too_dark", "too_bright", "wrong_material", "wrong_era", "wrong_weather", "no_focus",
})


class TasteService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    # ------------------------------------------------------------- write (owner only)

    def append_note(self, actor: Actor, *, author: str, subject: dict, artifact_ref: str,
                    verdict: str, reason_code: str, words: str | None = None,
                    tags: list[str] | None = None) -> TasteNote:
        if actor.kind != "owner":
            raise Refused(
                "taste notes have a single writer: the owner only (§1.7) — the night's "
                "automated keeps are verdict writes", actor=actor.id)
        if reason_code not in REASON_CODES:
            raise Refused(f"reason_code must be one of the closed dozen (§1.7), got {reason_code!r}")
        if verdict not in ("keep", "reject", "keep_with_caveat"):
            raise Refused("verdict must be keep|reject|keep_with_caveat")
        if not artifact_ref:
            raise Refused("a taste note is a claim about a thing (branch@commit), never a conversation")
        note = TasteNote(
            id=new_id("taste_note"), author=author, subject=subject,
            artifact_ref=artifact_ref, verdict=verdict, reason_code=reason_code,
            words=words, tags=tags or [],
        )
        ev = self.store.new_event(
            "taste.note.appended", actor,
            {"entity_kind": "taste_note", "entity_id": note.id},
            {"row": note.model_dump(mode="json"), "author": author},
        )
        self.store.append(ev)
        return self.get(note.id)

    def get(self, note_id: str) -> TasteNote:
        row = self.store.get_row("taste_notes", {"id": note_id})
        if row is None:
            raise NotFound(f"taste note {note_id} not found", entity=note_id)
        return TasteNote(**row["payload"])

    # ------------------------------------------------------------- reads

    def list(self, author: str | None = None, *, slice_for_model: bool = False,
             include_pending: bool = True) -> list[dict]:
        out = []
        for row in self.store.scan("taste_notes"):
            doc = row["payload"]
            if author and doc.get("author") != author:
                continue
            if slice_for_model:
                # §7.6: kid authors' rows (pending or not) are never in a slice
                if doc.get("author") in self.store.kid_actors:
                    continue
            # the pending/active status lives on the row, not in the payload
            if not include_pending and row.get("status") == "pending_ratification":
                continue
            out.append(doc)
        return out

    def export(self, author: str) -> dict:
        rows = [r for r in self.list(author)]
        if not rows and self.store.get_row("taste_authors", {"author": author}) is None \
                and not self._ever_had_rows(author):
            raise NotFound(f"no taste rows for author {author!r}", author=author)
        codes: dict[str, int] = {}
        for r in rows:
            codes[r.get("reason_code", "")] = codes.get(r.get("reason_code", ""), 0) + 1
        return {
            "author": author,
            "rows": rows,
            "reason_codes": codes,
            "artifact_refs": sorted({r.get("artifact_ref", "") for r in rows}),
            "label": "taste ledger export — rows are author-scoped; artifacts and their "
                     "prompts travel with the world (X §6-8)",
        }

    def _ever_had_rows(self, author: str) -> bool:
        for ev in self.store.events_since(0, types=["taste.note.appended"]):
            if ev.payload.get("author") == author or ev.payload.get("row", {}).get("author") == author:
                return True
        return False

    # ------------------------------------------------------------- erase / ratify

    def erase(self, author: str, actor: Actor, *, idem_key: str | None = None) -> dict:
        """One transaction: payload redaction + compensating taste.erased;
        the fold then excludes the rows from every projection and slice."""
        if actor.kind != "owner":
            raise Refused("taste erasure is an owner action (§4.2)")
        key = f"taste:erase:{idem_key or author}"
        cached = self.store.idem_get(key)
        if cached:
            return cached["body"]
        compensating = self.store.new_event(
            "taste.erased", actor, {"entity_kind": "taste_author", "entity_id": author},
            {},
        )
        self.store.erase_taste_author(author, actor.model_dump(mode="json"),
                                      compensating, idem_key=key)
        return {"author": author, "erased": True, "compensating_event": compensating.id}

    def ratify(self, author: str, actor: Actor, *, idem_key: str | None = None) -> dict:
        """Ratify Magnus's keeps — asked once, in the report, in one line."""
        if actor.kind != "owner":
            raise Refused("ratification is an owner action (§4.2)")
        key = f"taste:ratify:{idem_key or author}"
        cached = self.store.idem_get(key)
        if cached:
            return cached["body"]
        row = self.store.get_row("taste_authors", {"author": author})
        if row is not None and row.get("ratified"):
            return {"author": author, "ratified": True, "already": True}
        ev = self.store.new_event(
            "taste.ratified", actor, {"entity_kind": "taste_author", "entity_id": author},
            {"author": author},
        )
        _, resp = self.store.append(ev, idem_key=key,
                                    response_builder=lambda e: {"author": author, "ratified": True})
        if resp and resp.get("__replay__"):
            return resp["body"]
        return {"author": author, "ratified": True}
