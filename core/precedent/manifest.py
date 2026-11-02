"""The BoardManifest: the board's ratified scope, in one file.

A manifest is the projection of the precedent ledger at one moment:
**which cases are active, and which scope keys are ratified**. It is the
object the rest of the system reads when it wants to know "what is the
board's current answer to what may happen" without reopening the whole
ledger — ``core/drift``'s build-drift signal reads it to say whether a
branch head has left the ratified scope.

Three properties it keeps:

- **it is derived, never authoritative.** ``from_store`` projects it
  from a ``PrecedentStore``; editing a manifest file changes what a
  reader believes, not what the board decided.
- **the fingerprint is the receipt.** ``fingerprint()`` hashes the
  content (version, active ids, rule keys, scope boundary) — not the
  creation time — so two seats that project the same board say the same
  word, and any edit to the file moves the word. ``load`` recomputes it
  from the content: the header is a receipt for the eye, the content is
  the truth.
- **it round-trips through markdown.** ``save`` writes a document a
  human can open, and ``load`` reads back what a human edited.

The file::

    # Board Manifest manifest/2:9f2a41c0b7d3
    - **Version:** 2
    - **Created:** 2026-11-02T09:00:00

    ## Active precedents (2)
    - seed-human-request
    - seed-kid-apply

    ## Scope keys (3)
    - ladder.p1.preflight
    - recipe.apply
    - world.human_request

    ## Scope boundary
    the spawn island
"""

from __future__ import annotations

import datetime
import json
import re
from hashlib import sha256
from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Union
from pathlib import Path

from .rules import Rule
from .store import PrecedentStatus, PrecedentStore


@dataclass(frozen=True, kw_only=True)
class BoardManifest:
    """The board's ratified scope at one version."""

    #: How many precedents the store held at projection time (abandoned
    #: ones included: the version counts the ledger, the ids count the
    #: board's active work).
    version: int
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    #: The ids of every active (not abandoned) precedent, sorted.
    precedent_ids: List[str]
    #: The scope keys the board has ratified, sorted. A proposal or a
    #: branch head carrying a key outside this set is out of scope.
    rule_keys: List[str]
    #: What the board is about, in a sentence (or None).
    scope_boundary: Optional[str] = None

    @classmethod
    def from_store(
        cls,
        store: PrecedentStore,
        up_to: Optional[int] = None,
        rules: Optional[Mapping[str, Union[str, Rule]]] = None,
        scope_boundary: Optional[str] = None,
    ) -> BoardManifest:
        """Project the store's current state into a manifest.

        ``rules`` is the rule mapping the validator uses (plain strings
        or ``Rule``); their keys join the ratified scope alongside the
        active precedents' own keys.
        """
        precedents = store.all()[:up_to] if up_to else store.all()
        active = [p for p in precedents if p.status is not PrecedentStatus.ABANDONED]
        keys = {key for p in active for key in p.keys}
        if rules:
            keys.update(rules)
        return cls(
            version=len(precedents),
            precedent_ids=sorted(p.id for p in active),
            rule_keys=sorted(keys),
            scope_boundary=scope_boundary,
        )

    def ratified_keys(self) -> frozenset:
        """The scope keys in force — what a build's keys are checked against."""
        return frozenset(self.rule_keys)

    def fingerprint(self) -> str:
        """``manifest/<version>:<12 hex>``: content, not creation time."""
        payload = json.dumps(
            {
                "precedent_ids": sorted(self.precedent_ids),
                "rule_keys": sorted(self.rule_keys),
                "scope_boundary": self.scope_boundary,
                "version": self.version,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"manifest/{self.version}:{digest}"

    # -- markdown ------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Write the manifest as a markdown document."""
        boundary = self.scope_boundary
        if boundary is not None and "\n" in boundary:
            raise ValueError("a scope boundary is one line")
        lines = [
            f"# Board Manifest {self.fingerprint()}",
            f"- **Version:** {self.version}",
            f"- **Created:** {self.created_at.isoformat()}",
            "",
            f"## Active precedents ({len(self.precedent_ids)})",
        ]
        for pid in sorted(self.precedent_ids):
            lines.append(f"- {pid}")
        lines += ["", f"## Scope keys ({len(self.rule_keys)})"]
        for key in sorted(self.rule_keys):
            lines.append(f"- {key}")
        lines += ["", "## Scope boundary", boundary or "Unrestricted", ""]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @classmethod
    def load(cls, path: Path) -> BoardManifest:
        """Read back a manifest — what a human saved, or edited.

        The ``# Board Manifest`` header's fingerprint is a receipt and is
        not checked: a human with the authority to widen the scope edits
        the content, and the recomputed ``fingerprint()`` of the loaded
        manifest is then the new truth.
        """
        return parse_manifest(Path(path).read_text(encoding="utf-8"))


_TITLE = re.compile(r"^#\s+Board Manifest\s+\S+")
_FIELD = re.compile(r"^-\s+\*\*(.+?):\*\*\s?(.*)$")


def parse_manifest(text: str) -> BoardManifest:
    """One manifest document back into a BoardManifest."""
    if not _TITLE.match(text.split("\n", 1)[0]):
        raise ValueError("not a board manifest document")
    version: Optional[int] = None
    created: Optional[datetime.datetime] = None
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in text.split("\n")[1:]:
        matched = _FIELD.match(line)
        if matched:
            name = matched.group(1).strip().lower()
            if name == "version":
                version = int(matched.group(2).strip())
            elif name == "created":
                created = datetime.datetime.fromisoformat(matched.group(2).strip())
            else:
                raise ValueError(
                    f"unknown manifest field: {matched.group(1).strip()!r}"
                )
            continue
        if line.startswith("## "):
            current = line[3:].strip().split(" (")[0].strip().lower()
            sections[current] = []
            continue
        if current is not None and line.strip():
            sections[current].append(line.strip().lstrip("-").strip())
    if version is None or created is None:
        raise ValueError("a manifest needs a Version and a Created field")

    boundary_lines = sections.get("scope boundary", [])
    boundary = "\n".join(boundary_lines) if boundary_lines else None
    if boundary == "Unrestricted":
        boundary = None
    return BoardManifest(
        version=version,
        created_at=created,
        precedent_ids=sorted(sections.get("active precedents", [])),
        rule_keys=sorted(sections.get("scope keys", [])),
        scope_boundary=boundary,
    )
