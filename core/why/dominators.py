"""Reverse dominator tree over the alive subgraph.

Liveness flows from live roots down through ``child because parent`` edges
reversed; the dominator tree of that flow tells you which single justification
*gate* every path to a node must pass through — the structural answer to
"what breaks if this root dies" (impact) and "which nodes hang by a thread"
(fragile). Ported from why-core v0.2 using the iterative
Cooper–Harvey–Kennedy algorithm with a synthetic source when several live
roots exist.
"""

from __future__ import annotations

from collections import deque

from .model import NodeId

#: Synthetic entry when the alive subgraph has more than one live root.
SYNTHETIC_SOURCE = "__why_synthetic_source__"

#: node -> immediate dominator (its justification gate)
IDom = dict[NodeId, NodeId]


def reverse_dominators(
    alive: set[NodeId],
    live_roots: list[NodeId],
    reverse: dict[NodeId, list[NodeId]],
) -> IDom:
    """Immediate dominators on the alive subgraph.

    ``reverse`` maps parent -> children (liveness flows parent -> child).
    Roots dominate themselves; with multiple roots a synthetic source is
    added and then stripped, so roots stay their own gates.
    """
    roots = [r for r in live_roots if r in alive]
    if not roots:
        return {}

    # Successors within the alive subgraph.
    succ: dict[NodeId, list[NodeId]] = {n: [] for n in alive}
    for parent, children in reverse.items():
        if parent in alive:
            for child in children:
                if child in alive and child != parent:
                    succ[parent].append(child)

    multi = len(roots) > 1
    if multi:
        succ[SYNTHETIC_SOURCE] = list(roots)
        entries = [SYNTHETIC_SOURCE]
    else:
        entries = roots

    # BFS ordering + predecessor lists over the reachable subgraph.
    order: list[NodeId] = []
    seen: set[NodeId] = set(entries)
    preds: dict[NodeId, list[NodeId]] = {n: [] for n in seen}
    queue: deque[NodeId] = deque(entries)
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in succ.get(node, []):
            if child not in seen:
                seen.add(child)
                preds[child] = []
                queue.append(child)
    for node in seen:
        for child in succ.get(node, []):
            if child in preds:
                preds[child].append(node)

    idom: IDom = {entries[0]: entries[0]}
    depth: dict[NodeId, int] = {entries[0]: 0}

    def walk_depth() -> None:
        depth.clear()
        depth[entries[0]] = 0
        dq = deque([entries[0]])
        while dq:
            n = dq.popleft()
            for c in succ.get(n, []):
                if c in seen and c not in depth:
                    depth[c] = depth[n] + 1
                    dq.append(c)

    walk_depth()

    def intersect(a: NodeId, b: NodeId) -> NodeId:
        """Lowest common ancestor in the (partial) dominator tree."""
        guard = 0
        while a != b and guard < 100_000:
            while depth.get(a, 0) > depth.get(b, 0):
                a = idom.get(a, a)
                guard += 1
            while depth.get(b, 0) > depth.get(a, 0):
                b = idom.get(b, b)
                guard += 1
            if a != b:
                a = idom.get(a, a)
                b = idom.get(b, b)
                guard += 1
        return a

    changed = True
    rounds = 0
    while changed and rounds < 10_000:
        changed = False
        rounds += 1
        for node in order:
            if node == entries[0] or node in idom:
                continue
            processed = [p for p in preds[node] if p in idom]
            if not processed:
                continue
            new_idom = processed[0]
            for p in processed[1:]:
                new_idom = intersect(new_idom, p)
            if idom.get(node) != new_idom:
                idom[node] = new_idom
                walk_depth()
                changed = True

    if multi:
        idom.pop(SYNTHETIC_SOURCE, None)
    return idom


def dom_subtree(idom: IDom, node: NodeId) -> set[NodeId]:
    """All nodes whose every live path passes through ``node`` (impact set)."""
    children: dict[NodeId, list[NodeId]] = {}
    for child, parent in idom.items():
        if child != parent:
            children.setdefault(parent, []).append(child)
    subtree: set[NodeId] = set()
    queue = deque([node])
    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
            if child not in subtree:
                subtree.add(child)
                queue.append(child)
    return subtree


def dom_chain(idom: IDom, node: NodeId) -> list[NodeId]:
    """The chain of gates from ``node`` up toward the roots."""
    result = [node]
    current = node
    for _ in range(10_000):
        parent = idom.get(current)
        if parent is None or parent == current:
            break
        result.append(parent)
        current = parent
    return result
