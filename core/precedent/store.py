from __future__ import annotations
import datetime
import hashlib
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path


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
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    status: PrecedentStatus = PrecedentStatus.PROPOSED
    rule_override: Optional[str] = None
    keys: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        payload = "\x00".join([
            self.id,
            self.gap_id,
            self.decision,
            self.created_at.isoformat(),
            self.status.value,
        ]).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    def as_markdown(self) -> str:
        lines = [
            f"# Precedent {self.id}",
            "",
            f"**Gap:** {self.gap_id}",
            f"**Status:** {self.status.value}",
            f"**Author:** {self.author or 'system'}",
            f"**Created:** {self.created_at.isoformat()}",
            "",
            "## Decision",
            f"```",
            self.decision.strip(),
            f"```",
            "",
            "## Rationale",
            f"```",
            self.rationale.strip(),
            f"```",
            "",
        ]
        if self.rule_override:
            lines.append("**Rule override:** " + self.rule_override)
        if self.keys:
            lines.append("\n**Match keys:** " + ", ".join(self.keys))
        lines.append("\n---\n")
        return "\n".join(lines)


class PrecedentStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self._precedents: List[Precedent] = []
        self._by_id: Dict[str, Precedent] = {}
        self._by_key: Dict[str, List[Precedent]] = {}

    def append(self, p: Precedent) -> None:
        if p.id in self._by_id:
            raise ValueError(f"Precedent already exists: {p.id}")

        self._precedents.append(p)
        self._by_id[p.id] = p
        for key in p.keys:
            if key not in self._by_key:
                self._by_key[key] = []
            self._by_key[key].append(p)

    def get(self, id: str) -> Optional[Precedent]:
        return self._by_id.get(id)

    def match(self, proposal_keys: List[str]) -> List[Precedent]:
        matches = []
        seen = set()
        for key in proposal_keys:
            if key in self._by_key:
                for p in self._by_key[key]:
                    if p.id not in seen:
                        seen.add(p.id)
                        matches.append(p)
        return sorted(
            [p for p in matches if p.status == PrecedentStatus.ADJUDICATED or p.status == PrecedentStatus.CLOSED],
            key=lambda p: len(set(p.keys) & set(proposal_keys)),
            reverse=True
        )

    def all(self) -> List[Precedent]:
        return list(self._precedents)

    def save_markdown(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for p in self._precedents:
                f.write(p.as_markdown())
                f.write("\n")
