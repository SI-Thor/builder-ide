from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Set
from pathlib import Path
from .store import PrecedentStore, Precedent


@dataclass(frozen=True, kw_only=True)
class BoardManifest:
    version: int
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    precedent_ids: List[str]
    rule_keys: List[str]
    scope_boundary: Optional[str] = None

    @classmethod
    def from_store(cls, store: PrecedentStore, up_to: Optional[int] = None) -> BoardManifest:
        precedents = store.all()[:up_to] if up_to else store.all()
        active = [p.id for p in precedents if p.status not in {p.status.ABANDONED}]
        return BoardManifest(
            version=len(precedents),
            precedent_ids=active,
            rule_keys=[],
        )

    def fingerprint(self) -> str:
        payload = f"{self.version}\x00" + "\x00".join(sorted(self.precedent_ids))
        from hashlib import sha256
        return f"manifest/{self.version}:{sha256(payload.encode()).hexdigest()[:12]}"

    def save(self, path: Path) -> None:
        lines = [
            f"# Board Manifest {self.fingerprint()}",
            f"Version: {self.version}",
            f"Created: {self.created_at.isoformat()}",
            "",
            f"## Active precedents ({len(self.precedent_ids)})",
        ]
        for pid in sorted(self.precedent_ids):
            lines.append(f"- {pid}")
        lines.append("")
        lines.append("## Scope boundary")
        lines.append(self.scope_boundary or "Unrestricted")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
