"""The precedent store: an append-only ledger of decided cases, in
markdown a human can read and edit.

The store holds **precedents** — one decided case each: the gap it
answered, the decision, the rationale, the keys a proposal must carry to
meet it, and (optionally) the rule this case overrides. Appends only:
the store never rewrites a precedent, it only adds and (through
``status``) records where the case stands.

**The markdown format is the storage format.** A precedent is one
document; a store is one file of them, or a directory of one-per-file
documents. A human can open either, read it, fix a typo in a rationale,
add a key, add a whole precedent, and load it back — ``load_markdown``
parses what a human wrote, not only what ``save_markdown`` produced.

One precedent, in full::

    # Precedent seed-kid-apply

    - **Gap:** gap-ladder-p1-apply
    - **Status:** adjudicated
    - **Created:** 2026-11-01T16:35:00
    - **Author:** casey
    - **Keys:** recipe.apply
    - **Metadata:** {"source": "core/recipe/store.py apply_branch"}

    ## Decision

    ```
    ask
    ```

    ## Rationale

    ```
    A kid actor's apply is a proposal ...
    ```

The rules of the format, and why:

- **the fields** are ``- **Name:** value`` bullets between the title and
  the first ``## `` section. ``Gap``, ``Status``, ``Created`` are
  required; ``Author``, ``Rule override``, ``Keys`` and ``Metadata`` are
  omitted when empty (so ``None`` round-trips as *absent*, not as the
  word "None"). Unknown field names raise: a typo in a field name is a
  bug, not a comment.
- **prose before the first section is ignored**, so a human can leave
  a note among the bullets.
- **a section's body** is either a fenced block (any length of backticks
  a human chooses) or plain text up to the next ``## ``.
  ``as_markdown`` fences with one more backtick than the longest run in
  the body, so a decision that itself contains a fenced block still
  round-trips — the render can always out-fence its own content.
- **a key may not contain a comma** (keys render comma-separated on one
  line); a key may not be empty.
- ``id`` appears in the title and is what ``get`` and ``append`` use.

Round-trip is exact for rendered documents: ``Precedent.from_markdown``
of ``p.as_markdown()`` is ``p``, every field included (tested for fenced
bodies, embedded headings, unicode, and empty metadata). It is
*normalised* for hand-written plain-text bodies (leading and trailing
blank lines are dropped), which is what a text editor does anyway.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence
from pathlib import Path


class PrecedentStatus(Enum):
    """Where a case stands."""

    PROPOSED = "proposed"
    ADJUDICATED = "adjudicated"
    CLOSED = "closed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, kw_only=True)
class Precedent:
    """One decided case."""

    #: The document's name; unique per store.
    id: str
    #: The open question this case answered.
    gap_id: str
    #: What was decided: ``allow``, ``deny`` or ``ask`` (ask a human).
    decision: str
    #: Why, in prose.
    rationale: str
    #: Who decided it. ``None`` for a system decision (not rendered).
    author: Optional[str] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    status: PrecedentStatus = PrecedentStatus.PROPOSED
    #: The key of the rule this case overrides. A hard rule cannot be
    #: overridden (see ``core/precedent/rules.py``).
    rule_override: Optional[str] = None
    #: The keys a proposal must carry to meet this case.
    keys: List[str] = field(default_factory=list)
    #: Anything else, JSON-serialisable (it is rendered as JSON).
    metadata: Dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        """A digest over every field, in a canonical order.

        The same precedent hashes the same way everywhere, so two seats
        can say "the same case" and mean the same bytes. Recomputed from
        the content on every call — nothing about the hash is stored (a
        human may edit the body, and an embedded hash would only make
        that an error instead of a decision).
        """
        payload = json.dumps(
            {
                "author": self.author,
                "created_at": self.created_at.isoformat(),
                "decision": self.decision,
                "gap_id": self.gap_id,
                "id": self.id,
                "keys": sorted(self.keys),
                "metadata": self.metadata,
                "rationale": self.rationale,
                "rule_override": self.rule_override,
                "status": self.status.value,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    # -- markdown ------------------------------------------------------------

    def as_markdown(self) -> str:
        """This precedent as one markdown document (see the module doc)."""
        if not self.id.strip() or "\n" in self.id:
            raise ValueError(
                f"a precedent id may not be blank or multi-line: {self.id!r}"
            )
        if "\n" in self.gap_id:
            raise ValueError(f"a gap id may not contain a newline: {self.gap_id!r}")
        lines = [f"# Precedent {self.id}", ""]
        lines.append(f"- **Gap:** {self.gap_id}")
        lines.append(f"- **Status:** {self.status.value}")
        lines.append(f"- **Created:** {self.created_at.isoformat()}")
        if self.author is not None:
            lines.append(f"- **Author:** {self.author}")
        if self.rule_override is not None:
            lines.append(f"- **Rule override:** {self.rule_override}")
        if self.keys:
            for key in self.keys:
                if "," in key:
                    raise ValueError(f"a key may not contain a comma: {key!r}")
            lines.append("- **Keys:** " + ", ".join(self.keys))
        if self.metadata:
            lines.append(
                "- **Metadata:** "
                + json.dumps(self.metadata, sort_keys=True, ensure_ascii=False)
            )
        lines += ["", "## Decision", "", _fenced(self.decision), ""]
        lines += ["## Rationale", "", _fenced(self.rationale), ""]
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str) -> "Precedent":
        """Exactly one markdown document, back into a Precedent."""
        blocks = _split_blocks(text)
        if len(blocks) != 1:
            raise ValueError(
                f"expected exactly one precedent document, found {len(blocks)}"
            )
        return _parse_block(blocks[0])


def _longest_backtick_run(text: str) -> int:
    best = current = 0
    for char in text:
        if char == "`":
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _fenced(content: str) -> str:
    """A fence one backtick longer than any run in ``content``."""
    fence = "`" * max(3, _longest_backtick_run(content) + 1)
    return "\n".join([fence, content, fence])


_FENCE_LINE = re.compile(r"^(`{3,})\s*$")
_TITLE = re.compile(r"^#\s+Precedent\s+(\S.*)$")
_FIELD = re.compile(r"^-\s+\*\*(.+?):\*\*\s?(.*)$")
_KNOWN_FIELDS = {"gap", "status", "created", "author", "rule override", "keys", "metadata"}


def _split_blocks(text: str) -> List[List[str]]:
    """Title-anchored blocks, fence-aware (a body may hold # Precedent)."""
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    open_fence: Optional[int] = None
    for line in text.split("\n"):
        fence = _FENCE_LINE.match(line)
        if fence and open_fence is None:
            open_fence = len(fence.group(1))
        elif fence and open_fence is not None and len(fence.group(1)) >= open_fence:
            open_fence = None
        elif open_fence is None and _TITLE.match(line):
            current = [line]
            blocks.append(current)
            continue
        if current is not None:
            current.append(line)
    return blocks


def _parse_block(lines: Sequence[str]) -> Precedent:
    title = _TITLE.match(lines[0])
    if not title:
        raise ValueError(f"not a precedent document: {lines[0]!r}")
    precedent_id = title.group(1).strip()

    fields: Dict[str, str] = {}
    sections: Dict[str, str] = {}
    index = 1

    # -- the field bullets, up to the first section
    while index < len(lines) and not lines[index].startswith("## "):
        line = lines[index]
        matched = _FIELD.match(line)
        if matched:
            name = matched.group(1).strip().lower()
            if name not in _KNOWN_FIELDS:
                raise ValueError(
                    f"unknown field {matched.group(1).strip()!r} in precedent "
                    f"{precedent_id!r}; known fields: "
                    + ", ".join(sorted(_KNOWN_FIELDS))
                )
            fields[name] = matched.group(2).strip()
        # Any other line here is a human's note to themselves; it is
        # ignored, exactly like a comment in the section bodies.
        index += 1

    # -- the sections, each fenced or plain
    while index < len(lines):
        if not lines[index].startswith("## "):
            index += 1
            continue
        name = lines[index][3:].strip().lower()
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        opening = (
            _FENCE_LINE.match(lines[index])
            if index < len(lines) and _FENCE_LINE.match(lines[index])
            else None
        )
        if opening:
            width = len(opening.group(1))
            index += 1
            body: List[str] = []
            while index < len(lines):
                closing = _FENCE_LINE.match(lines[index])
                if closing and len(closing.group(1)) >= width:
                    index += 1
                    break
                body.append(lines[index])
                index += 1
            else:
                raise ValueError(
                    f"unterminated {name!r} fence in precedent {precedent_id!r}"
                )
            sections[name] = "\n".join(body)
        else:
            body = []
            while index < len(lines) and not lines[index].startswith("## "):
                body.append(lines[index])
                index += 1
            sections[name] = "\n".join(body).strip("\n")

    def required(name: str) -> str:
        if name not in fields:
            raise ValueError(f"precedent {precedent_id!r} has no {name!r} field")
        return fields[name]

    for needed in ("decision", "rationale"):
        if needed not in sections:
            raise ValueError(
                f"precedent {precedent_id!r} has no {needed!r} section"
            )

    try:
        status = PrecedentStatus(required("status"))
    except ValueError:
        allowed = ", ".join(s.value for s in PrecedentStatus)
        raise ValueError(
            f"precedent {precedent_id!r}: not a status: "
            f"{fields.get('status')!r} (one of {allowed})"
        )
    try:
        created = datetime.datetime.fromisoformat(required("created"))
    except ValueError:
        raise ValueError(
            f"precedent {precedent_id!r}: created is not an ISO timestamp: "
            f"{fields.get('created')!r}"
        )

    raw_keys = fields.get("keys", "")
    keys = (
        [k.strip() for k in re.split(r",\s*", raw_keys) if k.strip()]
        if raw_keys
        else []
    )
    metadata: Dict[str, Any] = {}
    if "metadata" in fields:
        try:
            metadata = json.loads(fields["metadata"])
        except ValueError:
            raise ValueError(
                f"precedent {precedent_id!r}: metadata is not JSON: "
                f"{fields['metadata']!r}"
            )
        if not isinstance(metadata, dict):
            raise ValueError(f"precedent {precedent_id!r}: metadata is not an object")

    return Precedent(
        id=precedent_id,
        gap_id=required("gap"),
        decision=sections["decision"],
        rationale=sections["rationale"],
        author=fields.get("author") or None,
        created_at=created,
        status=status,
        rule_override=fields.get("rule override") or None,
        keys=keys,
        metadata=metadata,
    )


def parse_precedents(text: str) -> List[Precedent]:
    """A file of precedent documents, back into a list, in file order."""
    return [_parse_block(block) for block in _split_blocks(text)]


class PrecedentStore:
    """An append-only set of precedents, with three indexes."""

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
        """The decided cases this proposal meets, most specific first.

        Only ``adjudicated`` and ``closed`` cases answer (a proposal is
        not a ruling yet). The order is fully determined — by how many
        keys the case shares with the proposal, then by id — so the same
        proposal asks the same first case every time, whatever order its
        keys arrived in.
        """
        matches = []
        seen = set()
        for key in proposal_keys:
            if key in self._by_key:
                for p in self._by_key[key]:
                    if p.id not in seen:
                        seen.add(p.id)
                        matches.append(p)
        return sorted(
            [
                p
                for p in matches
                if p.status is PrecedentStatus.ADJUDICATED
                or p.status is PrecedentStatus.CLOSED
            ],
            key=lambda p: (-len(set(p.keys) & set(proposal_keys)), p.id),
        )

    def all(self) -> List[Precedent]:
        return list(self._precedents)

    # -- markdown ------------------------------------------------------------

    def save_markdown(self, path: Path) -> None:
        """Every precedent in this store, one document after another."""
        with open(path, "w", encoding="utf-8") as f:
            for p in self._precedents:
                f.write(p.as_markdown())
                f.write("\n")

    def load_markdown(self, path: Path) -> int:
        """Append every document in ``path``. Returns how many were added.

        Append-only, like ``append``: a duplicate id raises and nothing
        before it is rewound — load into a fresh store, or watch for the
        error and decide what the collision means.
        """
        added = 0
        for precedent in parse_precedents(Path(path).read_text(encoding="utf-8")):
            self.append(precedent)
            added += 1
        return added

    def save_files(self, directory: Path) -> List[Path]:
        """One ``<id>.md`` per precedent — the shape a human edits in."""
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        written: List[Path] = []
        for p in self._precedents:
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", p.id):
                raise ValueError(f"precedent id {p.id!r} is not safe as a file name")
            target = out / f"{p.id}.md"
            target.write_text(p.as_markdown() + "\n", encoding="utf-8")
            written.append(target)
        return written

    def load_files(self, directory: Path) -> int:
        """Append every ``.md`` in ``directory``, in sorted file order."""
        added = 0
        for target in sorted(Path(directory).glob("*.md")):
            for precedent in parse_precedents(target.read_text(encoding="utf-8")):
                self.append(precedent)
                added += 1
        return added
