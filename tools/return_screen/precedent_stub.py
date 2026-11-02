"""precedent_stub.py — the pending-question seam, with core.precedent's shape.

``core/precedent`` exists on the ``precedent-store`` lane branch
(``Precedent``, ``PrecedentStatus``, ``PrecedentStore.append/get/match/all``)
but has not landed on main, so this screen carries a stub with **the same
interface and the same event shape**: a JSONL of append-only precedent
events beside the server. When the lane lands, the import in ``serve.py``
swaps to ``core.precedent`` and this file retires — the API the page uses
does not change.

A stub is not a licence to invent questions. The one question the stub
proposes is derived from the ledger by rule (see :func:`seed_questions`):
a judge that has refused at least half its recent verdicts asks what the
bots should do while it is unreachable. Questions with no ledger fact
behind them are not asked.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class PrecedentStatus(Enum):
    PROPOSED = "proposed"
    ADJUDICATED = "adjudicated"
    CLOSED = "closed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, kw_only=True)
class Precedent:
    id: str
    gap_id: str
    decision: str
    rationale: str
    author: Optional[str] = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    status: PrecedentStatus = PrecedentStatus.PROPOSED
    rule_override: Optional[str] = None
    keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        payload = "\x00".join([
            self.id, self.gap_id, self.decision,
            self.created_at.isoformat(), self.status.value,
        ]).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["created_at"] = self.created_at.isoformat()
        d["hash"] = self.hash()
        return d


class PrecedentStore:
    """Append-only JSONL: one line per event (proposed, adjudicated, …)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    # -- the same four methods the lane's store carries --------------------

    def append(self, p: Precedent) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(p.as_dict()) + "\n")

    def all(self) -> list[Precedent]:
        if not self.path.exists():  # state may be cleared while we run
            self.path.touch()
            return []
        return [self._parse(line) for line in self.path.read_text().splitlines()
                if line.strip()]

    def get(self, id: str) -> Optional[Precedent]:
        # the log is append-only, so the latest event for an id is its state
        return next((p for p in reversed(self.all()) if p.id == id), None)

    def match(self, proposal_keys: list[str]) -> list[Precedent]:
        return [p for p in self.all()
                if p.status == PrecedentStatus.ADJUDICATED
                and set(p.keys) & set(proposal_keys)]

    # -- the stub's own read model -----------------------------------------

    def latest_by_gap(self) -> dict[str, Precedent]:
        out: dict[str, Precedent] = {}
        for p in self.all():
            out[p.gap_id] = p  # ordered read, last wins
        return out

    def pending(self) -> list[Precedent]:
        return [p for p in self.latest_by_gap().values()
                if p.status == PrecedentStatus.PROPOSED]

    def adjudicate(self, id: str, ruling: str, ruled_by: str,
                   note: str = "") -> Optional[Precedent]:
        current = self.get(id)
        if current is None or current.status != PrecedentStatus.PROPOSED:
            return None
        decided = Precedent(
            id=id, gap_id=current.gap_id,
            decision=current.decision, rationale=note or current.rationale,
            author=current.author,
            created_at=dt.datetime.now(dt.timezone.utc),
            status=PrecedentStatus.ADJUDICATED,
            keys=current.keys,
            metadata={**current.metadata, "ruling": ruling, "ruled_by": ruled_by},
        )
        self.append(decided)
        return decided

    @staticmethod
    def _parse(line: str) -> Precedent:
        d = json.loads(line)
        d.pop("hash", None)  # derived, not a field
        d["created_at"] = dt.datetime.fromisoformat(d["created_at"])
        d["status"] = PrecedentStatus(d["status"])
        return Precedent(**d)


def seed_questions(store: PrecedentStore, snapshot: dict[str, Any]) -> list[Precedent]:
    """Propose, from ledger facts alone, the questions the human can answer.

    One rule today: if the human's absence overlapped a **refusal episode**
    (≥ 50 % of the overlap's verdicts refused, ≥ 20 verdicts in it), ask
    once — about the **latest** such episode only. A return that opens with
    a stack of questions is a nag; the ruling on the current episode is the
    precedent for the rest. The gap_id is pinned to the episode's start, so
    it is never re-asked, and a judge that has since recovered still gets
    its question ("what about next time") — the ruling outlives the outage.
    """
    seeded: list[Precedent] = []
    episodes = [s for s in snapshot.get("refusals", [])
                if s.get("verdicts_in", 0) >= 20
                and (s.get("refused_in", 0) / max(s["verdicts_in"], 1)) >= 0.5]
    for seg in reversed(episodes):  # newest first
        gap_id = f"judge-refusal@{seg['start']}"
        if gap_id in store.latest_by_gap():
            return seeded  # the latest episode was asked — nothing new to ask
        share = seg["refused_in"] / max(seg["verdicts_in"], 1)
        state = ("and it is still refusing now" if seg.get("still_running")
                 else f"and it returned at {seg['end'][11:16]}Z")
        question = Precedent(
            id=f"prec_{uuid.uuid4().hex[:12]}",
            gap_id=gap_id,
            decision=(f"While you were away the judge refused {seg['refused_in']} of "
                      f"{seg['verdicts_in']} verdicts between {seg['overlap_start'][11:16]}Z "
                      f"and {seg['end'][11:16]}Z ({share:.0%}), {state}. When that happens, "
                      "do the bots keep choosing skills on their own bandit, or pause "
                      "choosing until the judge returns?"),
            rationale=(f"episode {seg['start']} → {seg['end']}; overlap since your last "
                       f"visit: {seg['refused_in']} refusals of {seg['verdicts_in']} verdicts"),
            author="return-screen stub (core.precedent not landed on main)",
            keys=["judge-refusal", "fallback-policy"],
            metadata={"options": [
                {"ruling": "keep_bandit",
                 "label": "Keep choosing on their own bandit (what they did)"},
                {"ruling": "pause_choosing",
                 "label": "Pause skill choices until the judge returns (next time)"},
            ], "asked_at_epoch": time.time()},
        )
        store.append(question)
        seeded.append(question)
        return seeded  # one question per return — a stack of them is a nag
    return seeded
