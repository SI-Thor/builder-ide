"""Seams to the other half (branch core-recipe: recipe store, node
registry publisher, compiler) and to the engine/runner halves that follow.
Everything here is behind a Protocol named after the spec section that
defines it; the defaults are honest stubs that raise OtherHalfUnavailable
naming the seam, so the merge is a matter of supplying implementations.

What each seam needs from its owner:

- NodeRegistry (§1.4.0): the recipe half's compiler publishes nodes.json as
  a content-addressed artifact on version.committed (event.artifact.kind ==
  "nodes.json", payload.branch names the branch head). The default here
  reads the node_refs projection folded from those artifacts — no extra
  contract needed beyond that publishing convention.
- RecipeStore (§1.1–§1.2): commit typed edits to versions/branches, detect
  fast-forward vs merge, materialize recipe documents.
- MergeGateEngine (§2.3 steps 1–6): deterministic rebuild, render ladder,
  analytic constraint runs, critic. The gate orchestration lives here; the
  engine work is the seam.
- Telemetry (§3.2.2): lane load for the pre-flight; None means blind and
  the pre-flight says so in words, never guesses.
- Power (§5.5): nvpmodel ownership. RecordOnly logs power.mode.set and
  changes nothing — flipping the real box's mode is an operator decision,
  not a library default.
"""
from __future__ import annotations

from typing import Protocol

from .errors import OtherHalfUnavailable
from .models import NodeRef, RecipeEdit


class NodeRegistry(Protocol):
    def resolve(self, branch: str, node_ids: list[str]) -> list[NodeRef]: ...
    def nodes_for_branch(self, branch: str) -> list[NodeRef]: ...


class ProjectionNodeRegistry:
    """Default: the node_refs projection (fold of nodes.json artifacts)."""

    def __init__(self, store) -> None:
        self.store = store

    def _rows(self, branch: str) -> list[dict]:
        return [
            r for r in self.store.scan("node_refs")
            if r.get("branch") == branch
        ]

    def resolve(self, branch: str, node_ids: list[str]) -> list[NodeRef]:
        by_id = {r["node_id"]: r for r in self._rows(branch) if not r.get("orphaned")}
        out = []
        for nid in node_ids:
            row = by_id.get(nid)
            if row is None:
                continue
            p = row.get("payload", {})
            # absent fields take the model's defaults; a node the compiler
            # published without an assets list is still a node
            out.append(NodeRef(**{k: p[k] for k in
                                  ("node_id", "entry_path", "kind", "assets", "part")
                                  if p.get(k) is not None}))
        return out

    def nodes_for_branch(self, branch: str) -> list[NodeRef]:
        return self.resolve(branch, [r["node_id"] for r in self._rows(branch)])


class RecipeStore(Protocol):
    def commit_edit(self, edit: RecipeEdit) -> str: ...  # -> ver_
    def fast_forward(self, branch_id: str, to_version: str) -> None: ...
    def merge_conflicts(self, main_head: str, branch_head: str) -> list[str]: ...


class UnavailableRecipeStore:
    SEAM = "recipe-store (branch core-recipe, core-spec §1.1–§1.2)"

    def commit_edit(self, edit: RecipeEdit) -> str:
        raise OtherHalfUnavailable(
            "committing recipe edits is the recipe half", seam=self.SEAM)

    def fast_forward(self, branch_id: str, to_version: str) -> None:
        raise OtherHalfUnavailable(
            "branch tip moves are the recipe half", seam=self.SEAM)

    def merge_conflicts(self, main_head: str, branch_head: str) -> list[str]:
        raise OtherHalfUnavailable(
            "merge detection is the recipe half", seam=self.SEAM)


class MergeGateEngine(Protocol):
    def deterministic_rebuild(self, edit_id: str | None) -> dict: ...
    def render_rung(self, rung: int, seed: int) -> dict: ...
    def run_checks(self, checks: list[dict]) -> list[dict]: ...


class UnavailableMergeGateEngine:
    SEAM = "merge-gate engine (core-spec §2.3; engine + critic half)"

    def deterministic_rebuild(self, edit_id: str | None) -> dict:
        raise OtherHalfUnavailable("deterministic rebuild needs the engine", seam=self.SEAM)

    def render_rung(self, rung: int, seed: int) -> dict:
        raise OtherHalfUnavailable("render ladder needs the engine", seam=self.SEAM)

    def run_checks(self, checks: list[dict]) -> list[dict]:
        raise OtherHalfUnavailable("analytic checks need the engine", seam=self.SEAM)


class Telemetry(Protocol):
    def lane_load(self) -> float | None: ...


class BlindTelemetry:
    """No telemetry: the pre-flight reports `did not run — unknown (no
    telemetry)` rather than guessing (§3.4)."""

    def lane_load(self) -> float | None:
        return None


class Power(Protocol):
    def set_mode(self, mode: int) -> None: ...


class RecordOnlyPower:
    """Records the intent (power.mode.set) without touching the box."""

    def set_mode(self, mode: int) -> None:
        return None


class SpineLedgerPort:
    """The seats' `LedgerPort` (core.vocab.ports, core.coldstart.ports) over
    the spine's one audit store (§1.0).

    Before the seats merged, the vocabulary's Prop-maker loop and cold
    start's ask-mode ran on their own in-memory ledgers, bridged into the
    spine by mirrors. On the merged tree there is one store, and this
    adapter is the resident shape of their protocol over it: appends take
    the write lock and assign the gapless seq, `line.spoken` /
    `taste.note.appended` / `prediction.*` are all in the closed set (§1.8),
    and the spine's fold projects the rows every reader reads — the seats'
    in-memory ledgers remain their own unit-test seams, never on this path.

    Found by the rewired acceptance run (branch m1-real); the mirror
    bridges it deleted are the point.
    """

    def __init__(self, store) -> None:
        self._store = store

    def append(self, event):
        return self._store.append(event)[0]

    def head_seq(self) -> int:
        return self._store.max_seq()

    def events(self, *, since_seq: int | None = None, types=None):
        return self._store.events_since(
            since_seq or 0, list(types) if types is not None else None)

    def find(self, event_type: str, **match):
        for ev in reversed(self.events(types=[event_type])):
            if all((ev.payload or {}).get(k) == v for k, v in match.items()):
                return ev
        return None
