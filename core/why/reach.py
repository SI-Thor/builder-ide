"""Status evaluation over the justification graph — v0.2 semantics.

Ported 1:1 from why-core v0.2 (Rust), including the two external-audit fixes
(2026-10-30): explicit-only liveness, and deadness propagating through
explicit chains at any depth. Precedence order:

1. ``alive``   — a path of EXPLICIT edges to a live root exists, or a
   conjunctive group whose members are ALL alive.
2. ``unknown`` — the evidence is incomplete: an unattested or stale root is
   reachable, or the only path to a root runs through an INFERRED edge
   (candidate justifications never become verdicts), or a conjunctive group
   has an unknown member.
3. ``dead``    — certainty that no live reason exists: an explicit path to a
   dead (or ``until``-expired) root, or every conjunctive group contains a
   dead member.

Inferred edges can therefore never produce a dead finding either: the tool
refuses to recommend removal on a guessed link. The two failure directions
are not symmetric: ``unknown`` never fails a build, so anything that can
silently convert ``dead`` into ``unknown`` is the dangerous direction.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .dominators import IDom, reverse_dominators
from .model import Attestation, Graph, Liveness, NodeId, Provenance, RootStatus, Status


@dataclass(frozen=True)
class Coverage:
    """Wired/discovered coverage. Candidates never satisfy coverage."""

    wired: int
    discovered: int

    @property
    def pct(self) -> float:
        if self.discovered == 0:
            return 0.0
        return min(self.wired / self.discovered, 1.0) * 100.0


@dataclass
class Evaluation:
    """Result of evaluating a graph against attestations at a point in time."""

    status: dict[NodeId, Status] = field(default_factory=dict)
    #: predecessor used to reach this node (derivation chains; no "trust me")
    pred: dict[NodeId, NodeId] = field(default_factory=dict)
    #: reverse dominator tree on the alive subgraph (node -> immediate dominator)
    idom: IDom = field(default_factory=dict)
    coverage: Coverage | None = None
    #: alive-attested roots that went stale (review-by + grace passed)
    stale_roots: list[NodeId] = field(default_factory=list)
    #: alive-attested roots that hard-expired via ``until``
    expired_roots: list[NodeId] = field(default_factory=list)

    def status_of(self, node_id: NodeId) -> Status:
        """Status of a node; ABSENT for ids the graph has never seen."""
        return self.status.get(node_id, Status.ABSENT)

    def summary(self) -> dict[str, int]:
        """Counts per status — the necessity census."""
        counts = {s.value: 0 for s in Status}
        for st in self.status.values():
            counts[st.value] += 1
        return counts


def evaluate(graph: Graph, att: Attestation, as_of: str | None = None) -> Evaluation:
    """Evaluate every node's status given attestations and the evaluation date.

    ``as_of`` is None for "no clock" (expiry fields ignored); callers that
    want wall-clock behavior pass ``why.today()``.
    """
    ev = Evaluation()

    # ---- classify roots (external truth, with mortality) ----
    live_roots: list[NodeId] = []
    dead_roots: set[NodeId] = set()
    stale_roots: list[NodeId] = []
    expired_roots: list[NodeId] = []
    for rid, root in att.roots.items():
        eff = root.effective(as_of)
        if eff is RootStatus.ALIVE:
            live_roots.append(rid)
        elif eff is RootStatus.DEAD:
            if root.status is Liveness.ALIVE and root.until:
                expired_roots.append(rid)
            dead_roots.add(rid)
        else:  # STALE
            stale_roots.append(rid)
    ev.stale_roots = stale_roots
    ev.expired_roots = expired_roots

    # reverse adjacency: parent -> [(child, provenance), ...]
    reverse: dict[NodeId, list[tuple[NodeId, Provenance]]] = {}
    for child, parents in graph.edges.items():
        for parent, prov in parents:
            reverse.setdefault(parent, []).append((child, prov))

    status: dict[NodeId, Status] = {}
    pred: dict[NodeId, NodeId] = {}

    # ---- Pass 1 (fixpoint): alive via EXPLICIT edges and conjunctive groups ----
    # A conjunctive-derived alive node can confer aliveness on its own explicit
    # children, so edge-BFS and group-derivation iterate to a fixpoint.
    alive_set: set[NodeId] = set(live_roots)
    while True:
        before = len(alive_set)
        queue = deque(alive_set)
        seen = set(alive_set)
        while queue:
            node = queue.popleft()
            for child, prov in reverse.get(node, []):
                if prov is Provenance.EXPLICIT and child not in seen:
                    seen.add(child)
                    alive_set.add(child)
                    pred.setdefault(child, node)
                    queue.append(child)
        for child, groups in graph.conjunctive.items():
            if child in alive_set:
                continue
            for group in groups:
                if all(m in alive_set for m in group):
                    alive_set.add(child)
                    pred.setdefault(child, group[0])
                    break
        if len(alive_set) == before:
            break
    for node in alive_set:
        status[node] = Status.ALIVE

    # ---- Pass 2: candidate justification via INFERRED edges -> unknown ----
    # Anything reachable from a live root through any edge but NOT alive
    # through explicit ones is a candidate: unknown, never alive.
    seen_any: set[NodeId] = set(live_roots)
    cqueue: deque[NodeId] = deque(live_roots)
    while cqueue:
        node = cqueue.popleft()
        for child, _prov in reverse.get(node, []):
            if child not in seen_any:
                seen_any.add(child)
                if child not in alive_set:
                    status[child] = Status.UNKNOWN
                cqueue.append(child)

    # ---- Pass 3: dangling parents and stale roots -> unknown, propagated ----
    # A parent that carries its own justification chain is NOT a source: its
    # status derives from that chain, so deadness can propagate through it at
    # any depth (external audit 2026-10-30, Finding 2). Only dangling parents
    # — unattested, with no chain of their own — seed unknown.
    unknown_sources: set[NodeId] = set()

    def is_dangling(node_id: NodeId) -> bool:
        """Unattested, with no justification chain of its own: a true
        unknown-source. Everything else derives status from its chain."""
        return (
            node_id not in att.roots
            and node_id not in graph.edges
            and node_id not in graph.conjunctive
        )

    for parents in graph.edges.values():
        for parent, _prov in parents:
            if is_dangling(parent):
                unknown_sources.add(parent)
    for groups in graph.conjunctive.values():
        for group in groups:
            for member in group:
                if is_dangling(member):
                    unknown_sources.add(member)
    unknown_sources.update(stale_roots)

    for source in unknown_sources:
        if source not in alive_set:
            status.setdefault(source, Status.UNKNOWN)
    uqueue: deque[NodeId] = deque(unknown_sources)
    while uqueue:
        node = uqueue.popleft()
        for child, _prov in reverse.get(node, []):
            if child not in alive_set and child not in status:
                status[child] = Status.UNKNOWN
                uqueue.append(child)

    # ---- Pass 3.5: conjunctive group classification ----
    # A group is fully-alive (confers liveness), failed (any dead member —
    # definitively falsified; unknown siblings cannot revive it), or
    # undetermined (no dead, >=1 unknown). Undetermined groups block dead
    # verdicts: the node could still turn out alive once unknowns resolve.
    # Short-circuit law: dead beats unknown inside an all-of group.
    for _ in range(len(graph.conjunctive) + 2):
        changed = False
        for child, groups in graph.conjunctive.items():
            if child in status or not groups:
                continue
            if not all(member in status for group in groups for member in group):
                continue
            any_alive = False
            any_undetermined = False
            for group in groups:
                has_dead = False
                has_unknown = False
                for member in group:
                    member_status = status.get(member)
                    if member_status is Status.ALIVE:
                        continue
                    if member_status is Status.DEAD:
                        has_dead = True
                    else:
                        has_unknown = True
                if not has_dead and not has_unknown:
                    any_alive = True
                if not has_dead and has_unknown:
                    any_undetermined = True
            if any_alive:
                status[child] = Status.ALIVE
                changed = True
            elif any_undetermined:
                status[child] = Status.UNKNOWN
                changed = True
        if not changed:
            break

    # ---- Pass 4: dead roots and deadness through EXPLICIT paths ----
    # Attested-dead (or until-expired) roots are dead unless some live root
    # already justifies them; deadness then flows through explicit chains at
    # any depth. A fully dead graph must never exit clean.
    for root_id in dead_roots:
        if root_id not in alive_set:
            status.setdefault(root_id, Status.DEAD)
    dqueue: deque[NodeId] = deque(dead_roots)
    while dqueue:
        node = dqueue.popleft()
        for child, prov in reverse.get(node, []):
            if prov is Provenance.EXPLICIT and child not in alive_set and child not in status:
                status[child] = Status.DEAD
                dqueue.append(child)

    # ---- Pass 5: conjunctive groups all definitively failed -> dead ----
    for _ in range(len(graph.conjunctive) + 2):
        changed = False
        for child, groups in graph.conjunctive.items():
            if child in status or not groups:
                continue
            if not all(member in status for group in groups for member in group):
                continue
            if all(any(status.get(m) is Status.DEAD for m in group) for group in groups):
                status[child] = Status.DEAD
                changed = True
        if not changed:
            break

    # ---- Final sweep: everything else connected is unknown ----
    # Covers inferred-only paths to dead roots, mixed groups, and any node
    # whose evidence is simply incomplete. Never dead on a guessed link.
    for node in graph.nodes:
        if node not in status:
            status[node] = Status.UNKNOWN

    # ---- Reverse dominator tree over the alive subgraph ----
    live_root_set = [r for r in live_roots if r in alive_set]
    reverse_plain: dict[NodeId, list[NodeId]] = {}
    for parent, children in reverse.items():
        reverse_plain.setdefault(parent, []).extend(child for child, _prov in children)
    idom = reverse_dominators(alive_set, live_root_set, reverse_plain)

    coverage = (
        Coverage(wired=graph.wired(), discovered=graph.discovered)
        if graph.discovered is not None
        else None
    )

    ev.status = status
    ev.pred = pred
    ev.idom = idom
    ev.coverage = coverage
    return ev


def chain(graph: Graph, evaluation: Evaluation, node_id: NodeId) -> list[NodeId]:
    """Reconstruct a justification chain from a node toward roots.

    Prefers the pred map (from alive propagation). Falls back to the first
    outgoing edge — preferring an explicit parent so the printed "because"
    matches the edge that can actually determine status — then to conjunctive
    group members, so dead and unknown nodes still show their structural
    "because". Every status carries a derivation chain.
    """
    result = [node_id]
    current = node_id
    for _ in range(10_000):  # cycle protection
        if current in evaluation.pred:
            previous = evaluation.pred[current]
            result.append(previous)
            current = previous
        elif current in graph.edges:
            parents = graph.edges[current]
            chosen = next(
                (p for p, prov in parents if prov is Provenance.EXPLICIT),
                parents[0][0] if parents else None,
            )
            if chosen is None:
                break
            result.append(chosen)
            current = chosen
        elif current in graph.conjunctive:
            group = graph.conjunctive[current][0]
            result.extend(group)
            break
        else:
            break
    return result
