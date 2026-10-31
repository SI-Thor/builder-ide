"""The procfunc graph — the recipe's lower layer, stored and diffed (E §2).

Round 2 established the two facts this module stands on
(`docs/research/engine-round2.md`):

1. the canonical graph a v2 trace emits is **byte-stable** — same seed,
   same bytes, across runs, processes and hash seeds (§2 there) — so it is
   a safe thing to hash, store and diff;
2. a one-``chosen_idx`` edit diffs **structurally**: +2,698 nodes added,
   0 removed, 2 shared ids touched, and only the desk's work executes
   (§4 there). The diff is not an approximation of what re-executes; at
   scene scale it was measured against a profile.

So the core treats the engine's graphs the way it treats the recipe: store
by hash (graphs are megabytes and two versions share most of one), diff by
node id, and close over **consumers** — the ``$ref`` edges' downstream —
because a dataflow node's value is a function of its inputs and nothing
else. That closure is the dirty-subtree term of the dirty-set contract
(`DIRTY.md` §3).

The graph document this module reads is the procfunc trace's own shape
(``{"name": …, "nodes": [{"id": "n0", "type": …, …}], "outputs": …}`` with
``{"$ref": "<id>"}`` edges nested anywhere in a node's fields). It is the
**engine's** format — contract rule 5 keeps it engine-side — so nothing
here interprets node *semantics*; ids, refs and content digests only.
Extraction from a stage's envelope recognizes the envelope shapes the
adapters on this seam actually write; anything else is honestly reported
as "no graph" and the contract degrades to stage granularity.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from core.canon import content_hash
from core.recipe.blobs import BlobStore, FileBlobStore
from core.recipe.errors import IntegrityError

__all__ = [
    "GraphDiff",
    "GraphRef",
    "GraphStore",
    "StageGraphs",
    "diff_graphs",
    "graph_hash",
    "graphs_of_stage",
]

#: The envelope markers this module can pull a graph out of — the v2
#: adapters' own lower-layer labels (contract rule 5: the lower layer
#: belongs to the engine, so it gets to name itself).
_V2_ENVELOPE = "infinigen-2-procfunc"
_V2_BUNDLE = "venv-cli"


# --------------------------------------------------------------------------- the document


def _walk_refs(value: Any) -> Iterator[str]:
    """Every ``$ref`` target nested in ``value`` (deterministic order)."""
    if isinstance(value, dict):
        if "$ref" in value and isinstance(value["$ref"], str):
            yield value["$ref"]
            return
        for key in sorted(value):
            yield from _walk_refs(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _walk_refs(item)


def _node_kind(node: Mapping[str, Any]) -> str:
    """A node's kind for the diff's census: what it *is*, most specific first."""
    for key in ("func", "method", "attribute"):
        if key in node:
            return str(node[key])
    return str(node.get("type", "?"))


def _kind_signature(node: Mapping[str, Any]) -> tuple:
    """What a node *is*, structurally: type plus its call target. A changed
    node whose signature moved is a re-bound id, not a new value of the
    same call (the positional tail artifact round 2 named)."""
    return (node.get("type"), node.get("func"), node.get("method"), node.get("attribute"))


def _embedded_node_count(node: Mapping[str, Any]) -> int:
    """How many inline node trees (``$type`` dicts) ride inside a node.

    The real graphs embed whole subtrees this way — round 2's join node
    carries the desk's objects as an inline ``Proxy`` tree with no ids of
    their own — so "grew" has to see them, not just ``$ref`` edges.
    """

    def count(value: Any) -> int:
        if isinstance(value, dict):
            here = 1 if "$type" in value else 0
            return here + sum(count(v) for v in value.values())
        if isinstance(value, list):
            return sum(count(v) for v in value)
        return 0

    return count({k: v for k, v in node.items() if k != "id"})


def graph_hash(graph: Mapping[str, Any]) -> str:
    """The canonical graph's content hash — the store's address for it."""
    return content_hash(dict(graph))


def is_procfunc_graph(value: Any) -> bool:
    """True when ``value`` looks like a procfunc trace document."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("nodes"), list)
        and all(isinstance(node, dict) and "id" in node for node in value["nodes"])
    )


@dataclass(frozen=True)
class StageGraphs:
    """The graph(s) a stage's envelope carried, as the adapter wrote them.

    ``entries`` maps an entry path to its graph when the stage is a bundle
    of per-entry graphs (the venv boundary's shape); ``single`` carries the
    one graph of a whole-stage trace. Either may be empty — a stage that
    carries no graph (the fake's digest document) is ``empty``.
    """

    entries: dict[str, dict] = field(default_factory=dict)
    single: dict | None = None

    @property
    def empty(self) -> bool:
        return not self.entries and self.single is None

    def for_entry(self, entry_path: str) -> dict | None:
        if entry_path in self.entries:
            return self.entries[entry_path]
        return self.single


def graphs_of_stage(data: bytes) -> StageGraphs:
    """Pull the graph(s) out of a stage's bytes, or say there are none.

    Recognized shapes, in order: the v2 stage envelope of
    :class:`core.engine.infinigen2.Infinigen2Engine` (``engine`` marker,
    ``graph`` payload); inside it (or as the payload itself) the venv
    boundary's per-entry bundle (``engine: venv-cli``, ``entries``); a bare
    procfunc graph document. Anything else is not ours to interpret
    (contract rule 5) and comes back empty — the caller reports stage
    granularity and moves on.
    """
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return StageGraphs()
    if not isinstance(doc, dict):
        return StageGraphs()
    payload = doc["graph"] if doc.get("engine") == _V2_ENVELOPE else doc
    if not isinstance(payload, dict):
        return StageGraphs()
    if payload.get("engine") == _V2_BUNDLE and isinstance(
        payload.get("entries"), dict
    ):
        entries = {
            str(path): graph
            for path, graph in sorted(payload["entries"].items())
            if is_procfunc_graph(graph)
        }
        return StageGraphs(entries=entries)
    if is_procfunc_graph(payload):
        return StageGraphs(single=payload)
    return StageGraphs()


# --------------------------------------------------------------------------- the diff


@dataclass
class GraphDiff:
    """What changed between two canonical graphs, and what re-executes.

    The fields say exactly what round 2's §4.1 table said about the desk
    edit, so a report can be read against that measurement: added/removed/
    changed by id, the changed split into **join points** (grew by
    absorbing added content — round 2's ``_operator.add``, whose desk
    objects ride inline as an embedded Proxy tree), **edited** nodes (same
    kind, a value moved — the splice-safe case), and **re-bound ids** (the
    kind itself moved: the positional tail artifact), plus the
    **closure**: changed ∪ added ∪ removed, plus every transitive
    consumer, which is the dirty-subtree term of ``DIRTY.md`` §3.
    """

    base_hash: str
    head_hash: str
    base_nodes: int
    head_nodes: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    join_points: list[str] = field(default_factory=list)
    edited: list[str] = field(default_factory=list)
    rebound: list[str] = field(default_factory=list)
    closure: list[str] = field(default_factory=list)
    added_kinds: dict[str, int] = field(default_factory=dict)
    removed_kinds: dict[str, int] = field(default_factory=dict)
    changed_kinds: dict[str, int] = field(default_factory=dict)
    outputs_touched: bool = False
    wall_ms: float | None = None

    @property
    def additive(self) -> bool:
        """No removals — the round-2 desk shape ("purely additive": a
        subtree appears, nothing shrinks). An additive diff may still
        re-bind a positional tail id; see :attr:`splice_safe`."""
        return not self.removed

    @property
    def splice_safe(self) -> bool:
        """Whether a graph-edit engine may splice this diff in place:
        additive **and** no re-bound ids. Re-binds and removals are not
        splice-safe (``DIRTY.md`` §3) — the honest fallback is a full
        re-evaluation of the stage."""
        return not self.removed and not self.rebound

    @property
    def identical(self) -> bool:
        return self.base_hash == self.head_hash

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_hash": self.base_hash,
            "head_hash": self.head_hash,
            "base_nodes": self.base_nodes,
            "head_nodes": self.head_nodes,
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "join_points": self.join_points,
            "edited": self.edited,
            "rebound": self.rebound,
            "closure_nodes": len(self.closure),
            "closure_share": (
                round(len(self.closure) / self.head_nodes, 4)
                if self.head_nodes
                else 0.0
            ),
            "added_kinds": self.added_kinds,
            "changed_kinds": self.changed_kinds,
            "outputs_touched": self.outputs_touched,
            "additive": self.additive,
            "splice_safe": self.splice_safe,
            "wall_ms": self.wall_ms,
        }


def _consumers(graph: Mapping[str, Any]) -> dict[str, set[str]]:
    """For each node id, the ids of nodes that reference it."""
    ids = {node["id"] for node in graph["nodes"]}
    consumers: dict[str, set[str]] = {}
    for node in graph["nodes"]:
        for ref in _walk_refs({k: v for k, v in node.items() if k != "id"}):
            if ref in ids:  # a dangling ref has no consumer edge
                consumers.setdefault(ref, set()).add(node["id"])
    return consumers


def diff_graphs(base: Mapping[str, Any], head: Mapping[str, Any]) -> GraphDiff:
    """The structural diff of two canonical graphs, closed over consumers."""
    started = time.monotonic()
    base_nodes = {node["id"]: node for node in base["nodes"]}
    head_nodes = {node["id"]: node for node in head["nodes"]}

    added = sorted(set(head_nodes) - set(base_nodes))
    removed = sorted(set(base_nodes) - set(head_nodes))
    changed = sorted(
        node_id
        for node_id in set(base_nodes) & set(head_nodes)
        if base_nodes[node_id] != head_nodes[node_id]
    )
    added_set = set(added)

    # a changed node is one of three things: a join point (same call, grew
    # by absorbing added content — an id ref or a larger inline tree), an
    # edited node (same call, a value moved — splice-safe), or a re-bound
    # id (the call itself moved: the positional tail artifact)
    join_points: list[str] = []
    edited: list[str] = []
    rebound: list[str] = []
    for node_id in changed:
        base_node, head_node = base_nodes[node_id], head_nodes[node_id]
        refs_added = bool(
            added_set
            & set(_walk_refs({k: v for k, v in head_node.items() if k != "id"}))
        )
        grew_inline = _embedded_node_count(head_node) > _embedded_node_count(base_node)
        if _kind_signature(head_node) != _kind_signature(base_node):
            rebound.append(node_id)
        elif refs_added or grew_inline:
            join_points.append(node_id)
        else:
            edited.append(node_id)

    # the dirty subtrees: seeds plus everyone downstream of them
    seeds = set(added) | set(removed) | set(changed)
    consumers = _consumers(head)
    closure = set(seeds)
    frontier = list(seeds)
    while frontier:
        node_id = frontier.pop()
        for consumer in consumers.get(node_id, ()):  # head's edges decide reach
            if consumer not in closure:
                closure.add(consumer)
                frontier.append(consumer)

    outputs_touched = any(
        ref in closure for ref in _walk_refs(head.get("outputs", {}))
    )

    diff = GraphDiff(
        base_hash=graph_hash(base),
        head_hash=graph_hash(head),
        base_nodes=len(base_nodes),
        head_nodes=len(head_nodes),
        added=added,
        removed=removed,
        changed=changed,
        join_points=sorted(join_points),
        edited=sorted(edited),
        rebound=sorted(rebound),
        closure=sorted(closure),
        added_kinds={
            kind: sum(
                1 for node_id in added if _node_kind(head_nodes[node_id]) == kind
            )
            for kind in sorted({_node_kind(head_nodes[n]) for n in added})
        },
        removed_kinds={
            kind: sum(
                1 for node_id in removed if _node_kind(base_nodes[node_id]) == kind
            )
            for kind in sorted({_node_kind(base_nodes[n]) for n in removed})
        },
        changed_kinds={
            kind: sum(
                1 for node_id in changed if _node_kind(head_nodes[node_id]) == kind
            )
            for kind in sorted({_node_kind(head_nodes[n]) for n in changed})
        },
        outputs_touched=outputs_touched,
        wall_ms=(time.monotonic() - started) * 1000.0,
    )
    return diff


# --------------------------------------------------------------------------- the store


class GraphRef(dict):
    """The index row for a recorded graph: where it is and how big."""

    def __init__(self, stage_key: str, ref: str, nodes: int, size: int) -> None:
        super().__init__(
            stage_key=stage_key, graph=ref, nodes=nodes, bytes=size
        )

    @property
    def stage_key(self) -> str:
        return self["stage_key"]

    @property
    def graph(self) -> str:
        return self["graph"]

    @property
    def nodes(self) -> int:
        return self["nodes"]

    @property
    def size_bytes(self) -> int:
        return self["bytes"]


class GraphStore:
    """The graphs a project's stages produced, stored by hash, one each.

    Two recipe versions share most of a graph (the round-2 desk edit shares
    18,725 of 21,423 nodes), so the blobs are content-addressed and deduped:
    recording the same graph under a new stage key adds an index row, not
    five megabytes. The index is one canonical JSON file, written atomically;
    the blobs are the blob store's own write-once bytes, hash-verified on
    read. Like every cache in the spec (§5.2), the whole store is derived:
    delete it and the engine re-traces.
    """

    def __init__(self, root: Path | str, blobs: BlobStore | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._blobs = blobs or FileBlobStore(self.root)
        self._index_path = self.root / "index.json"
        self._index: dict[str, dict] = {}
        self._load_index()

    # -- reads ---------------------------------------------------------------

    def ref_for(self, stage_key: str) -> GraphRef | None:
        row = self._index.get(stage_key)
        return GraphRef(stage_key, row["graph"], row["nodes"], row["bytes"]) if row else None

    def get(self, stage_key: str) -> dict | None:
        """The graph a stage key produced, or None — hash-verified on read."""
        ref = self.ref_for(stage_key)
        if ref is None:
            return None
        data = self._blobs.get_bytes(ref.graph)
        try:
            graph = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise IntegrityError(
                f"graph blob {ref.graph} (stage {stage_key}) is not JSON: {e!r}"
            ) from e
        if graph_hash(graph) != ref.graph:
            raise IntegrityError(
                f"graph blob {ref.graph} (stage {stage_key}) does not match its hash"
            )
        return graph

    def __contains__(self, stage_key: str) -> bool:
        return stage_key in self._index

    def __len__(self) -> int:
        return len(self._index)

    def listing(self) -> list[GraphRef]:
        return [
            GraphRef(key, row["graph"], row["nodes"], row["bytes"])
            for key, row in sorted(self._index.items())
        ]

    def total_bytes(self) -> int:
        """Unique blob bytes on disk — the same graph under two stage keys
        is one blob (deduped both in the store and in this count)."""
        seen: dict[str, int] = {}
        for row in self._index.values():
            seen[row["graph"]] = row["bytes"]
        return sum(seen.values())

    # -- writes --------------------------------------------------------------

    def record(self, stage_key: str, graph: Mapping[str, Any]) -> GraphRef:
        """Store a graph under a stage key. Same graph, same blob."""
        if not is_procfunc_graph(graph):
            raise ValueError(
                "not a procfunc graph (want {name, nodes: [{id, …}], outputs}); "
                "the diff and the store read the engine's own document shape"
            )
        blob = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
        ref = self._blobs.put_bytes(blob)
        row = GraphRef(stage_key, ref, len(graph["nodes"]), len(blob))
        self._index[stage_key] = dict(row)
        self._save_index()
        return row

    # -- internals -----------------------------------------------------------

    def _load_index(self) -> None:
        if not self._index_path.is_file():
            return
        try:
            loaded = json.loads(self._index_path.read_text("utf-8"))
        except json.JSONDecodeError:
            return  # a torn index is rebuilt as stages re-record; blobs stay
        if isinstance(loaded, dict):
            self._index = {
                key: row for key, row in loaded.items() if isinstance(row, dict)
            }

    def _save_index(self) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._index, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, self._index_path)
