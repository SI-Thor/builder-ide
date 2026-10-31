"""Core data model for the WHY justification kernel.

Ported from why-core v0.2 (Rust). The important invariants:

- Liveness is *external truth recorded in att.txt*, never computed.
- Inferred edges are candidates: they can explain and suggest, but they never
  confer a verdict (alive or dead).
- Roots are mortal: ``until`` is a hard expiry, ``review-by`` is a soft one
  (30-day grace), and a stale attestation is never silently alive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .dates import add_days

NodeId = str


class Provenance(str, Enum):
    """Who wrote the edge: a human/authoritative field, or a heuristic."""

    EXPLICIT = "explicit"
    INFERRED = "inferred"


class Liveness(str, Enum):
    """Attested liveness of a root (external truth, not computed)."""

    ALIVE = "alive"
    DEAD = "dead"


class Status(str, Enum):
    """The four verdicts. ``unknown`` is first-class, never a failure to decide."""

    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"
    ABSENT = "absent"


class RootStatus(Enum):
    """Effective root status at the evaluation date.

    STALE means: attested alive, but the review-by soft expiry (plus the
    30-day grace) has passed. A stale attestation degrades the root — and
    everything depending on it — to ``unknown`` until re-attested.
    """

    ALIVE = "alive"
    DEAD = "dead"
    STALE = "stale"


@dataclass
class RootAttestation:
    """A declared living (or dead) necessity: project, regulation, contract…"""

    id: NodeId
    status: Liveness
    since: str | None = None
    by: str | None = None
    #: Hard expiry (YYYY-MM-DD). After this date the root is dead. No grace.
    until: str | None = None
    #: Soft expiry (YYYY-MM-DD). After this date + 30 days of grace the root
    #: degrades to unknown until re-attested.
    review_by: str | None = None

    def effective(self, as_of: str | None) -> RootStatus:
        """Effective liveness at ``as_of`` (None = no clock: expiry ignored)."""
        if self.until and as_of and self.until < as_of:
            return RootStatus.DEAD
        if self.status is Liveness.DEAD:
            return RootStatus.DEAD
        if self.status is Liveness.ALIVE and self.review_by and as_of:
            expiry = add_days(self.review_by, 30)
            if expiry and expiry < as_of:
                return RootStatus.STALE
        return RootStatus.ALIVE


@dataclass
class Edge:
    child: NodeId
    parent: NodeId
    provenance: Provenance


@dataclass
class Graph:
    """The justification graph: ``child because parent``.

    edges       — child -> [(parent, provenance), ...]
    conjunctive — child -> [group, ...] where group = [parent, ...] and the
                  child is justified only when ALL members of some group are
                  alive (``child -> all-of: p1 p2``).
    discovered  — artifact count declared by ``# discovered: N`` (written by
                  an extractor) so coverage can tell "unwired" from "audited".
    """

    edges: dict[NodeId, list[tuple[NodeId, Provenance]]] = field(default_factory=dict)
    nodes: set[NodeId] = field(default_factory=set)
    conjunctive: dict[NodeId, list[list[NodeId]]] = field(default_factory=dict)
    discovered: int | None = None

    def add_edge(self, child: NodeId, parent: NodeId, provenance: Provenance) -> None:
        self.nodes.add(child)
        self.nodes.add(parent)
        self.edges.setdefault(child, []).append((parent, provenance))

    def add_group(self, child: NodeId, parents: list[NodeId]) -> None:
        self.nodes.add(child)
        self.nodes.update(parents)
        self.conjunctive.setdefault(child, []).append(parents)

    def wired(self) -> int:
        """Nodes carrying at least one EXPLICIT justification.

        Inferred (candidate) wiring does not count: coverage measures
        adoption, and candidates prove nothing.
        """
        wired = {
            child
            for child, parents in self.edges.items()
            if any(prov is Provenance.EXPLICIT for _, prov in parents)
        }
        wired.update(self.conjunctive.keys())
        return len(wired)


@dataclass
class Attestation:
    """Root attestations keyed by root id (one per root; last write wins)."""

    roots: dict[NodeId, RootAttestation] = field(default_factory=dict)

    def insert(self, root: RootAttestation) -> None:
        self.roots[root.id] = root
