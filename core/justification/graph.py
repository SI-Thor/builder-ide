"""Project records -> the WHY kernel's inputs: a project's justification graph.

Node ids (namespaced like upstream's ``project:…``):

    goal:<task_id>   a plan goal (spec §1.9 Task — the slate row's intention)
    branch:<br_id>   a recipe branch (spec §1.2)
    wo:<wo_id>       a work order (spec §1.3)
    vocab:<word>     a vocabulary entry (spec §1.5; the word is its own key)
    entry:<path>     a recipe entry (spec §1.1) as it rides a branch head
    asset:<ast_id>   a library asset (spec §1.6)

Edges are ``child because parent``, all EXPLICIT — structural facts from the
spec's own records, not heuristic candidates:

    asset  -> entry   the entry consumes the asset (RecipeEntry.assets)
    entry  -> branch  the entry rides the branch's head version
    branch -> task    the task owns the branch (Task.branches)
    branch -> wo      the branch was cut by the order (Branch.created_by.via)
    wo     -> task    the order serves the goal (WorkOrder.serves — stub)
    vocab  -> wo      the word was promoted from / requested by the order
                      (VocabularyEntry.provenance.origin, WorkOrder.vocabulary_gap)

Roots — the two strengths of ADR-0002 (upstream
``docs/ADRs/0002-questionable-vs-dead.md``) mapped onto spec lifecycle facts:

- ``goal:<task>`` is attested ALIVE while the plan carries it (slated,
  queued, running, kept, parked), with ``review_by`` carrying the slate's
  soft expiry. The owner KILLING a goal (state ``dropped``) *withdraws* the
  attestation — the root goes dangling and every dependent becomes UNKNOWN =
  **questionable, never deleted**. Certified death is not the owner's to
  give here: builder-ide never deletes, and another goal may adopt the
  dependents, so removal is not yet justified. ``reverted`` (the owner
  rejected the outcome) is the one certified goal death.
- ``branch:<br>`` is ALIVE when the owner kept/applied it (purpose ``main``
  or protected) and DEAD when ``rejected`` — an owner rejection is a
  certified death; the branch itself is retained and visitable (spec §1.2:
  "a rejection is a branch you can revisit, not a hole in the ground").
- ``wo:<wo>`` is DEAD when terminally ``failed``/``cancelled`` — a system
  lifecycle fact, certain by construction.
- ``vocab:<word>`` with ``provenance.origin == "builtin"`` is attested ALIVE
  by "builtin" — the night-one vocabulary is a given of the project, like
  any other foundation (spec §6.1).

Stale goals (review-by + 30-day grace past ``as_of``) degrade their
dependents to questionable by the kernel's own mortality rules — none of
that is re-implemented here. INFERRED edges are reserved for candidate
re-wirings (e.g. an engineer proposing that an orphaned asset serve another
entry); candidates never confer verdicts, so the builder emits none yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.recipe.models import RecipeEntry, RecipeVersion
from core.models import Asset, Branch, Task, WorkOrder
from core.vocab.models import VocabularyEntry
from core.why import Attestation, Graph, Liveness, Provenance, RootAttestation

#: Task states that keep a goal's attestation alive (spec §1.9).
GOAL_ALIVE_STATES = frozenset({"slated", "queued", "running", "kept", "parked"})
#: Terminal states that WITHDRAW the goal's attestation -> dangling -> questionable.
GOAL_WITHDRAWN_STATES = frozenset({"cut", "dropped"})
#: Terminal states that attest the goal DEAD with certainty.
GOAL_DEAD_STATES = frozenset({"reverted"})

#: Work-order states that attest the order DEAD with certainty (spec §1.3).
WO_DEAD_STATES = frozenset({"failed", "cancelled"})


def goal_node(task_id: str) -> str:
    return f"goal:{task_id}"


def branch_node(branch_id: str) -> str:
    return f"branch:{branch_id}"


def wo_node(wo_id: str) -> str:
    return f"wo:{wo_id}"


def vocab_node(word: str) -> str:
    return f"vocab:{word}"


def entry_node(entry_path: str) -> str:
    return f"entry:{entry_path}"


def asset_node(asset_id: str) -> str:
    return f"asset:{asset_id}"


@dataclass
class ProjectRecords:
    """The project records the justification projection reads.

    These are the *real* spec records now that every seat has landed:
    ``core.models``'s Task/Branch/WorkOrder/Asset, the recipe store's
    RecipeVersion, and the vocabulary's VocabularyEntry. Nothing here is a
    stub: the why-kernel seat's ``core.api``/``core.recipe``/``core.vocab``
    stub packages are gone, and this layer reads the same classes the rest
    of the service reads.

    ``version_entries`` carries the one mapping the records cannot hold:
    spec §1.0 keeps recipe documents as content-addressed blobs, so a
    version's entries are materialized from the store rather than stored on
    the version record (see ``core.justification.records``)."""

    tasks: list[Task] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    versions: list[RecipeVersion] = field(default_factory=list)
    work_orders: list[WorkOrder] = field(default_factory=list)
    vocabulary: list[VocabularyEntry] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    #: version id -> {entry path -> entry}, materialized from the recipe store
    version_entries: dict[str, dict[str, RecipeEntry]] = field(default_factory=dict)


def build_graph(records: ProjectRecords) -> tuple[Graph, Attestation]:
    """Fold records into the kernel's ``(graph, attestations)`` inputs."""
    graph = Graph()
    att = Attestation()

    versions = {v.id: v for v in records.versions}
    wo_ids = {w.id for w in records.work_orders}

    # --- edges: asset -> entry -> branch; branch -> task / wo ---
    for branch in records.branches:
        head = versions.get(branch.head)
        if head is not None:
            for entry in records.version_entries.get(head.id, {}).values():
                graph.add_edge(entry_node(entry.path), branch_node(branch.id),
                               Provenance.EXPLICIT)
                for ast_id in entry.assets:
                    graph.add_edge(asset_node(ast_id), entry_node(entry.path),
                                   Provenance.EXPLICIT)
        for task in records.tasks:
            if branch.id in task.branches:
                graph.add_edge(branch_node(branch.id), goal_node(task.id),
                               Provenance.EXPLICIT)
        via = branch.created_by.via if branch.created_by else None
        if via in wo_ids:
            graph.add_edge(branch_node(branch.id), wo_node(via), Provenance.EXPLICIT)

    # --- edges: wo -> task; vocab -> wo ---
    for wo in records.work_orders:
        if wo.serves and any(t.id == wo.serves for t in records.tasks):
            graph.add_edge(wo_node(wo.id), goal_node(wo.serves), Provenance.EXPLICIT)
    for entry in records.vocabulary:
        origin = str(entry.provenance.get("origin", ""))
        if origin in wo_ids:
            graph.add_edge(vocab_node(entry.word), wo_node(origin), Provenance.EXPLICIT)
        for wo in records.work_orders:
            if wo.vocabulary_gap and wo.vocabulary_gap.get("word") == entry.word:
                graph.add_edge(vocab_node(entry.word), wo_node(wo.id),
                               Provenance.EXPLICIT)

    # --- attestations: the roots, per the module docstring's mapping ---
    for task in records.tasks:
        if task.state in GOAL_ALIVE_STATES:
            att.insert(RootAttestation(
                id=goal_node(task.id), status=Liveness.ALIVE,
                since=task.slated_at, by=task.author, review_by=task.review_by))
        elif task.state in GOAL_DEAD_STATES:
            att.insert(RootAttestation(
                id=goal_node(task.id), status=Liveness.DEAD,
                since=task.slated_at, by=task.author))
        # withdrawn states (cut, dropped): no attestation -> dangling -> questionable

    for branch in records.branches:
        if branch.purpose == "rejected":
            att.insert(RootAttestation(
                id=branch_node(branch.id), status=Liveness.DEAD, by="owner"))
        elif branch.purpose == "main" or branch.protected:
            att.insert(RootAttestation(
                id=branch_node(branch.id), status=Liveness.ALIVE, by="owner"))

    for wo in records.work_orders:
        if wo.state in WO_DEAD_STATES:
            att.insert(RootAttestation(
                id=wo_node(wo.id), status=Liveness.DEAD, by="core"))

    # Builtin words are givens of the project (the night-one vocabulary,
    # spec §6.1) — attested alive by "builtin", like any other foundation.
    for entry in records.vocabulary:
        if entry.provenance.get("origin") == "builtin":
            att.insert(RootAttestation(
                id=vocab_node(entry.word), status=Liveness.ALIVE, by="builtin"))

    # A dead root is severed from its own parents: it no longer claims to be
    # "because of" anything — it stands on the attestation alone. Upstream's
    # roots are parentless by construction; without this, the kernel's pass
    # order lets an unresolved parent drag an attested-dead root back to
    # unknown (and a live parent would resurrect it), both of which blunt the
    # certainty an attestation is supposed to carry. Death severs upward;
    # dependents below still inherit it.
    for rid, root in att.roots.items():
        if root.status is Liveness.DEAD:
            graph.edges.pop(rid, None)

    return graph, att
