"""The justification projection: statuses, chains and the morning-report view.

A pure fold over project records (see ``graph.py`` for the node scheme and
the root mapping, and ``lifecycle.py`` for the borrowed behaviours). Nothing
here writes: killing a goal is an owner decision recorded by the core (the
task leaves the plan), and this layer *reads* it — in line with the spec's
§5 rule that the audit log is the source of truth and every other table is a
projection rebuilt from it.

The morning-report answer the whole attachment exists for:

    kill a goal -> its dependents (assets, entries, branches, work orders,
    words) show up QUESTIONABLE, with the broken chain explained in plain
    words — and nothing is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import why
from core.justification.graph import (
    ProjectRecords,
    asset_node,
    branch_node,
    build_graph,
    entry_node,
    goal_node,
    vocab_node,
    wo_node,
)
from core.justification.lifecycle import label as _label
from core.justification.lifecycle import may_enter_new_work, weight as _weight

#: The entity kinds that carry a justification chain (BRIEF.md: every asset,
#: vocabulary entry, recipe branch and work order — plus the connective kinds).
KINDS = ("asset", "vocab", "branch", "work_order", "goal", "entry")

_NODE_FOR = {
    "asset": asset_node,
    "vocab": vocab_node,
    "branch": branch_node,
    "work_order": wo_node,
    "goal": goal_node,
    "entry": entry_node,
}

_KIND_WORDS = {
    "asset": "asset", "vocab": "word", "branch": "branch",
    "work_order": "work order", "goal": "goal", "entry": "entry",
}


@dataclass(frozen=True)
class ChainStep:
    """One link of a because-chain, resolved to a human-readable record."""

    node: str
    kind: str
    key: str
    line: str
    status: why.Status


@dataclass(frozen=True)
class Justification:
    kind: str
    key: str
    status: why.Status
    label: str
    weight: float
    chain: tuple[ChainStep, ...]
    because: str
    cause: ChainStep | None      # the broken link; None when justified
    reason: str | None           # plain words for the cause
    explanation: str             # the morning-report one-liner

    @property
    def may_enter_new_work(self) -> bool:
        return may_enter_new_work(self.status)


@dataclass
class MorningReport:
    """The justification section of the morning report (spec §3.2.8)."""

    as_of: str | None
    census: dict[str, int]
    justified: list[Justification]
    questionable: list[Justification]
    dead_retained: list[Justification]
    unwired: list[Justification]
    coverage: dict[str, tuple[int, int]]   # kind -> (wired, total)
    lines: list[str]


class JustificationService:
    """Evaluates and explains the justification graph of one record snapshot."""

    def __init__(self, records: ProjectRecords):
        self.records = records

    # ---- evaluation -----------------------------------------------------

    def evaluate(self, as_of: str | None = None) -> why.Evaluation:
        graph, att = build_graph(self.records)
        return why.evaluate(graph, att, as_of)

    def status_of(self, kind: str, key: str,
                  as_of: str | None = None) -> Justification:
        graph, att = build_graph(self.records)
        evaluation = why.evaluate(graph, att, as_of)
        node = _NODE_FOR[kind](key)
        status = evaluation.status_of(node)
        return self._justify(graph, att, evaluation, node, kind, key, status,
                             as_of)

    def all(self, as_of: str | None = None) -> list[Justification]:
        """Every entity of every KINDS kind, with its chain."""
        graph, att = build_graph(self.records)
        evaluation = why.evaluate(graph, att, as_of)
        out: list[Justification] = []
        for kind, key in self._entities():
            node = _NODE_FOR[kind](key)
            out.append(self._justify(graph, att, evaluation, node, kind, key,
                                     evaluation.status_of(node), as_of))
        return out

    # ---- the morning report ----------------------------------------------

    def morning_report(self, as_of: str | None = None) -> MorningReport:
        everything = self.all(as_of)
        justified = [j for j in everything if j.status is why.Status.ALIVE]
        questionable = [j for j in everything if j.status is why.Status.UNKNOWN]
        dead = [j for j in everything if j.status is why.Status.DEAD]
        unwired = [j for j in everything if j.status is why.Status.ABSENT]

        # coverage: the wired fraction per attached kind — an unwired library
        # must never read as healthy (the kernel's coverage lesson).
        coverage: dict[str, tuple[int, int]] = {}
        for kind in ("asset", "vocab", "branch", "work_order"):
            keys = {key for k, key in self._entities() if k == kind}
            wired = sum(1 for j in everything
                        if j.kind == kind and j.status is not why.Status.ABSENT)
            coverage[kind] = (wired, len(keys))

        # The necessity census over the entities this projection reports —
        # the kernel's own summary() can't see unwired entities (they never
        # enter the graph), and an unwired library must never read as healthy.
        census = {s.value: 0 for s in why.Status}
        for j in everything:
            census[j.status.value] += 1
        lines = [
            f"Justification: {len(justified)} justified · "
            f"{len(questionable)} questionable · {len(dead)} dead (retained) · "
            f"{len(unwired)} unwired"
        ]
        lines += [f"  {j.explanation}" for j in questionable + dead + unwired]
        return MorningReport(
            as_of=as_of, census=census, justified=justified,
            questionable=questionable, dead_retained=dead, unwired=unwired,
            coverage=coverage, lines=lines,
        )

    # ---- internals --------------------------------------------------------

    def _entities(self) -> list[tuple[str, str]]:
        r = self.records
        out: list[tuple[str, str]] = []
        out += [("asset", a.id) for a in r.assets]
        out += [("vocab", v.word) for v in r.vocabulary]
        out += [("branch", b.id) for b in r.branches]
        out += [("work_order", w.id) for w in r.work_orders]
        out += [("goal", t.id) for t in r.tasks]
        entries: set[str] = set()
        for b in r.branches:
            head = next((v for v in r.versions if v.id == b.head), None)
            if head:
                entries.update(head.entries)
        out += [("entry", path) for path in sorted(entries)]
        return out

    def _describe(self, node: str) -> tuple[str, str, str]:
        """node id -> (kind, key, human line)."""
        prefix, _, key = node.partition(":")
        kind = {"goal": "goal", "branch": "branch", "wo": "work_order",
                "vocab": "vocab", "entry": "entry", "asset": "asset"}[prefix]
        r = self.records
        if kind == "goal":
            task = next((t for t in r.tasks if t.id == key), None)
            text = f"goal “{task.intention}” ({key})" if task else f"goal {key}"
        elif kind == "branch":
            br = next((b for b in r.branches if b.id == key), None)
            text = f"branch {br.name} ({key})" if br else f"branch {key}"
        elif kind == "work_order":
            wo = next((w for w in r.work_orders if w.id == key), None)
            text = f"work order “{wo.title}” ({key})" if wo else f"work order {key}"
        elif kind == "vocab":
            text = f"word {key}"
        elif kind == "entry":
            text = f"entry {key}"
        else:
            a = next((x for x in r.assets if x.id == key), None)
            text = f"asset {key} ({a.kind})" if a else f"asset {key}"
        return kind, key, text

    def _justify(self, graph: why.Graph, att: why.Attestation,
                 evaluation: why.Evaluation, node: str, kind: str, key: str,
                 status: why.Status, as_of: str | None) -> Justification:
        raw = why.chain(graph, evaluation, node)
        steps: list[ChainStep] = []
        for n in raw:
            nkind, nkey, nline = self._describe(n)
            nstatus = evaluation.status_of(n)
            steps.append(ChainStep(n, nkind, nkey, nline, nstatus))
            # For a justified entity, stop at the live root that carries it —
            # structural edges beyond a root are history, not its lifeline.
            if status is why.Status.ALIVE and nstatus is why.Status.ALIVE \
                    and n in att.roots:
                break
        because = " because ".join(s.line for s in steps)

        cause: ChainStep | None = None
        reason: str | None = None
        if status is why.Status.ALIVE:
            explanation = f"{_KIND_WORDS[kind]} {key}: justified — {because}"
        else:
            # The broken link: the root-most step carrying the SAME verdict —
            # for a questionable entity that is the dangling/stale root its
            # chain runs into; for a dead one, the attested-dead root (a dead
            # order blames its own terminal failure, not the stale goal it
            # once served — dead roots are severed from their parents).
            same = [s for s in steps if s.status is status]
            cause = (same[-1] if same else steps[-1]) if steps else None
            reason = self._reason(cause, evaluation, as_of) if cause else "no chain"
            word = _label(status)
            if status is why.Status.UNKNOWN:
                kept = "retained at 0.25 weight — nothing is deleted"
            elif status is why.Status.DEAD:
                kept = "removal justified — retained, never deleted"
            else:  # ABSENT
                kept = "no justification edge mentions it — wire it or retire it"
            explanation = (
                f"{_KIND_WORDS[kind]} {key}: {word} — broken at {cause.line} "
                f"({reason}); {kept}"
            )
        return Justification(
            kind=kind, key=key, status=status, label=_label(status),
            weight=_weight(status), chain=tuple(steps), because=because,
            cause=cause, reason=reason, explanation=explanation,
        )

    def _reason(self, step: ChainStep, evaluation: why.Evaluation,
                as_of: str | None) -> str:
        """Plain words for a broken link, from the records and the evaluation."""
        node = step.node
        if step.status is why.Status.ABSENT:
            return {
                "asset": "serves no entry on any branch",
                "vocab": "promoted by no order and not a builtin word",
                "branch": "owned by no task or order, kept by nobody",
                "work_order": "serves no goal on any slate",
            }.get(step.kind, "no justification edge mentions it")
        if node in evaluation.stale_roots:
            task = next((t for t in self.records.tasks
                         if goal_node(t.id) == node), None)
            horizon = (f"review-by {task.review_by}" if task and task.review_by
                       else "its review-by")
            return (f"the goal went stale — {horizon} plus the 30-day grace "
                    f"passed as of {as_of}; re-affirm it on a slate or drop it")
        if node in evaluation.expired_roots:
            return "the goal hard-expired (until)"

        prefix = node.partition(":")[0]
        state = None
        if prefix == "goal":
            task = next((t for t in self.records.tasks
                         if goal_node(t.id) == node), None)
            state = task.state if task else None
        elif prefix == "wo":
            wo = next((w for w in self.records.work_orders
                       if wo_node(w.id) == node), None)
            state = wo.state if wo else None
        elif prefix == "branch":
            br = next((b for b in self.records.branches
                       if branch_node(b.id) == node), None)
            state = "rejected" if br and br.purpose == "rejected" else None

        if step.status is why.Status.DEAD:
            return {
                "reverted": "you reverted this goal's outcome",
                "rejected": "you rejected this branch — it stays visitable, "
                            "but its content is dead",
                "failed": "the order failed terminally",
                "cancelled": "the order was cancelled",
            }.get(state, "attested dead — no live reason remains")
        return {
            "dropped": "you dropped this goal from the plan",
            "cut": "cut at the budget bar and never re-queued onto a slate",
        }.get(state, "no live attestation carries it — nothing on any slate "
                     "or keep owns it")
