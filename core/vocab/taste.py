"""The taste ledger, read.

Two things live here:

* `TasteRow` — a row of the taste ledger (T §"Taste note fields"; spec §1.7).
  Written by the owner's verdict event and by nothing else; builders read and
  cite, they never write (T §"The taste ledger").
* `aggregate_taste_notes` — the read side that turns rows into the per-entry
  `TasteNote` aggregate the vocabulary carries (§1.5).

Two rules from the spec shape the read side:

* **Author-scoped.** Casey's rows and Magnus's rows never mix. Magnus's rows
  are separable, exportable and deletable in one action each, and they are
  *never* included in any slice read into a model prompt (§7.6).
* **Inert until ratified.** Magnus's first three keeps are
  `pending_ratification` and excluded from every slice any builder reads
  (§1.7, G §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from .models import TasteNote

__all__ = [
    "TasteRow",
    "TasteVerdict",
    "TasteStatus",
    "aggregate_taste_notes",
    "taste_rows_from_events",
    "kept_verdicts",
]

TasteVerdict = Literal["keep", "reject", "keep_with_caveat"]
TasteStatus = Literal["active", "pending_ratification"]

#: A "keep with caveat" is a keep that carries a condition; it counts as kept.
kept_verdicts: frozenset[str] = frozenset({"keep", "keep_with_caveat"})


@dataclass(frozen=True)
class TasteRow:
    """One row of the taste ledger — a judgement about an artifact, not a feeling."""

    id: str
    at: str
    author: str
    status: TasteStatus
    subject: dict[str, Any]
    artifact_ref: str
    verdict: TasteVerdict
    reason_code: str
    words: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def param_path(self) -> str | None:
        path = self.subject.get("param_path")
        return path if isinstance(path, str) else None

    @property
    def kept(self) -> bool:
        return self.verdict in kept_verdicts


def aggregate_taste_notes(
    rows: Iterable[TasteRow],
    *,
    author: str = "casey",
    subject_prefix: str | None = None,
) -> list[TasteNote]:
    """Fold taste rows into the per-reason-code aggregate a vocabulary entry carries.

    `author` is required in spirit and defaulted in practice: it is the owner
    whose taste a builder is entitled to read. Magnus's rows are never mixed in
    (§7.6) — there is no "all authors" mode on this function on purpose.

    `subject_prefix` narrows the fold to one recipe entry ("harbor.crates"),
    which is how a word gets the taste notes that are about it.
    """
    buckets: dict[str, list[TasteRow]] = {}
    for row in rows:
        if row.author != author:
            continue
        if row.status != "active":
            continue  # pending_ratification rows are inert
        if subject_prefix is not None:
            path = row.param_path or ""
            if not (path == subject_prefix or path.startswith(f"{subject_prefix}.")):
                continue
        buckets.setdefault(row.reason_code, []).append(row)

    notes: list[TasteNote] = []
    for reason_code, group in buckets.items():
        kept = sum(1 for row in group if row.kept)
        observed = len(group)
        basis = f"{kept}/{observed} kept"
        latest = max(group, key=lambda row: row.at)
        notes.append(
            TasteNote(
                code="keep" if kept > observed - kept else "avoid",
                reason_code=reason_code,
                note=(latest.words or "")[:80],
                basis=basis,
            )
        )
    notes.sort(key=lambda note: (note.code != "keep", note.reason_code))
    return notes


def taste_rows_from_events(events: Sequence[Any]) -> list[TasteRow]:
    """Read taste rows out of `taste.note.appended` audit events."""
    rows: list[TasteRow] = []
    for event in events:
        if getattr(event, "type", None) != "taste.note.appended":
            continue
        payload: Mapping[str, Any] = getattr(event, "payload", {}) or {}
        row = payload.get("row")
        if not isinstance(row, Mapping):
            continue
        rows.append(
            TasteRow(
                id=str(row.get("id", event.id)),
                at=str(row.get("at", event.at)),
                author=str(row.get("author", "")),
                status=row.get("status", "active"),
                subject=dict(row.get("subject", {})),
                artifact_ref=str(row.get("artifact_ref", "")),
                verdict=row.get("verdict", "keep"),
                reason_code=str(row.get("reason_code", "")),
                words=row.get("words"),
                tags=tuple(row.get("tags", ()) or ()),
            )
        )
    return rows
