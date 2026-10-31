"""Parsers for the two-file ``because`` format (v0.2).

graph.txt::

    # comment lines start with # (a `# discovered: N` header is meaningful)
    child-id -> parent-id (explicit|inferred)
    child-id -> all-of: parent-id parent-id [parent-id ...]

Bare ``child -> parent`` defaults to ``(explicit)``.

att.txt::

    # root-id  alive|dead  [since]  [by]  [until=YYYY-MM-DD]  [review-by=YYYY-MM-DD]
    jira:MIG-4821   dead   2023-04-12   ci
    reg:SOC2-CC6    alive  2024-01-01   security   review-by=2027-01-01

``since`` and ``by`` keep their legacy positional slots; the v0.2 mortality
fields are key=value tokens so they can never be confused with dates or
authors. Unknown fields are a parse error (strict by default).
"""

from __future__ import annotations

import contextlib

from .dates import is_valid_date
from .model import Attestation, Graph, Liveness, Provenance, RootAttestation


class ParseError(ValueError):
    """Raised with line number and content for any malformed line."""

    def __init__(self, line: int, content: str):
        self.line = line
        self.content = content
        super().__init__(f"invalid input on line {line}: {content}")


def parse_graph(text: str) -> Graph:
    g = Graph()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            rest = line[1:].strip()
            if rest.startswith("discovered:"):
                with contextlib.suppress(ValueError):
                    g.discovered = int(rest[len("discovered:") :].strip())
            continue

        if "->" not in line:
            raise ParseError(lineno, line)
        child, rest = line.split("->", 1)
        child = child.strip()
        rest = rest.strip()
        if not child or any(ch.isspace() for ch in child):
            raise ParseError(lineno, line)

        # Conjunctive group: `child -> all-of: p1 p2 p3`
        if rest.startswith("all-of:"):
            members = [m.strip("()") for m in rest[len("all-of:") :].split()]
            members = [m for m in members if m]
            if not members:
                raise ParseError(lineno, line)
            g.add_group(child, members)
            continue

        # parent may be followed by (explicit) or (inferred)
        if "(" in rest:
            idx = rest.index("(")
            parent = rest[:idx].strip()
            suffix = rest[idx:].lower()
            provenance = Provenance.INFERRED if "inferred" in suffix else Provenance.EXPLICIT
        else:
            parent, provenance = rest, Provenance.EXPLICIT

        if not parent or any(ch.isspace() for ch in parent):
            raise ParseError(lineno, line)
        g.add_edge(child, parent, provenance)
    return g


def parse_attestation(text: str) -> Attestation:
    att = Attestation()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            raise ParseError(lineno, line)
        root_id = parts[0]
        try:
            status = Liveness(parts[1].lower())
        except ValueError:
            raise ParseError(lineno, line) from None

        since: str | None = None
        by: str | None = None
        until: str | None = None
        review_by: str | None = None
        positional_used = 0

        for tok in parts[2:]:
            if "=" in tok:
                key, _, value = tok.partition("=")
                if key == "until":
                    if not is_valid_date(value):
                        raise ParseError(lineno, f"until={value} is not a YYYY-MM-DD date")
                    until = value
                elif key == "review-by":
                    if not is_valid_date(value):
                        raise ParseError(lineno, f"review-by={value} is not a YYYY-MM-DD date")
                    review_by = value
                elif key == "since":
                    since = value
                elif key == "by":
                    by = value
                else:
                    raise ParseError(lineno, f"unknown field {tok}")
            else:
                if positional_used == 0:
                    since = tok
                elif positional_used == 1:
                    by = tok
                else:
                    raise ParseError(lineno, line)
                positional_used += 1

        att.insert(RootAttestation(root_id, status, since, by, until, review_by))
    return att
