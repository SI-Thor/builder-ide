"""WHY — the justification kernel (conservation law of the ecology).

A faithful Python port of why-core v0.2 (SuperInstance/why, Rust).

The two-file format:

    graph.txt:   child-id -> parent-id (explicit|inferred)
                 child-id -> all-of: parent-id parent-id [...]
    att.txt:     root-id  alive|dead  [since] [by] [until=...] [review-by=...]

Status semantics (precedence order):

    alive    — a path of EXPLICIT edges to a live root, or an all-of group
               whose members are all alive.
    unknown  — incomplete evidence: an unattested/stale root is reachable,
               or the only path runs through an INFERRED edge (candidate
               justifications never become verdicts), or a conjunctive group
               has an unknown member.
    dead     — certainty that no live reason exists: an explicit path to a
               dead (or until-expired) root, or every conjunctive group
               contains a dead member.
    absent   — the node never appears in any justification edge.

The kernel is a pure function of (graph, attestations, as_of). No I/O, no
hidden clock, no globals — the ecology calls it; it never calls the ecology.
"""

from .dates import add_days, is_valid_date, today
from .dominators import dom_chain, dom_subtree, reverse_dominators
from .model import (
    Attestation,
    Edge,
    Graph,
    Liveness,
    NodeId,
    Provenance,
    RootAttestation,
    RootStatus,
    Status,
)
from .parse import ParseError, parse_attestation, parse_graph
from .reach import Coverage, Evaluation, chain, evaluate

__all__ = [
    "add_days",
    "is_valid_date",
    "today",
    "dom_chain",
    "dom_subtree",
    "reverse_dominators",
    "Attestation",
    "Edge",
    "Graph",
    "Liveness",
    "NodeId",
    "Provenance",
    "RootAttestation",
    "RootStatus",
    "Status",
    "ParseError",
    "parse_attestation",
    "parse_graph",
    "Coverage",
    "Evaluation",
    "chain",
    "evaluate",
]
