"""The recipe store behind the spine's port — one store, one log.

Before the seats merged, `core.svc`'s `RecipeStore` port (commit_edit /
fast_forward / merge_conflicts, core/ports.py) answered
`UnavailableRecipeStore`, and a vocabulary call stayed an uncommitted
proposal. This module is the port's real implementation over
`core.recipe.store.RecipeStore`, with two translations the merge owes:

* **the ledger**: the recipe store codes against its small `Ledger`
  protocol; `SpineRecipeLedger` satisfies it with the spine's own SQLite
  store, so every `edit.proposed` / `version.committed` / `branch.*` event
  lands in the ONE audit log (§1.0) and folds into the same projections —
  the recipe store's own thread-bound SQLite ledger is not on this path.
* **the edit shape**: the spine's edit proposals carry `base: "head"` and
  address their target by *node id* (`{node}.params` = the whole params
  dict); the recipe store wants a `ver_` base and entry-path ops. The seam
  resolves both the way §1.4.0 says the node registry must — node id →
  entry path → params — and commits onto the branch it holds current.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..canon import new_id, now_utc
from ..events import Actor, core_actor
from ..records import AuditEvent, Op, Recipe, RecipeEdit
from ..store import LedgerStore
from core.recipe.blobs import BlobStore, FileBlobStore
from core.recipe.ledger import Ledger
from core.recipe.merge import three_way_merge
from core.recipe.models import Recipe as RecipeRecord
from core.recipe.schema import StaticSchemaRegistry
from core.recipe.store import RecipeStore as TheRecipeStore

__all__ = ["SpineRecipeLedger", "RecipeStoreSeam", "schemas_from_vocabulary"]

MAIN = "br_main"


class SpineRecipeLedger:
    """`core.recipe.ledger.Ledger` over the spine's one audit log.

    The spine's store is the single writer (§1.0) and is thread-safe (its
    connection is lock-guarded), so the recipe store may append from any
    worker. Recipe event types are in the spine's closed set (§1.8), and
    the spine's fold already projects them.
    """

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    def append(self, *, type: str, actor: Actor, subject: dict[str, Any],
               payload: dict[str, Any], artifact: dict[str, Any] | None = None,
               at: str | None = None) -> AuditEvent:
        ev = AuditEvent(
            id=new_id("audit"), at=at or now_utc(), actor=actor, type=type,
            subject=subject, payload=payload, artifact=artifact,
        )
        committed, _ = self._store.append(ev)
        return committed

    def events(self, *, since_seq: int | None = None,
               types: Sequence[str] | None = None) -> list[AuditEvent]:
        return self._store.events_since(
            since_seq or 0, types=list(types) if types is not None else None)

    def last_seq(self) -> int:
        events = self._store.events_since(0)
        return events[-1].seq if events else 0


def schemas_from_vocabulary(words) -> StaticSchemaRegistry:
    """The vocabulary is the validator: every word's param schema registers
    under its own name, and the registry's suffix rule maps
    `props.harbor.crates` onto the entry path `harbor.crates` (§1.1)."""
    schemas = StaticSchemaRegistry()
    for entry in words:
        schemas.register(entry.word, entry.params)
    return schemas


class RecipeStoreSeam:
    """The spine's `RecipeStore` port (core/ports.py) over the real store."""

    SEAM = None  # the real thing; there is no other half to name

    def __init__(self, core, *, schemas: StaticSchemaRegistry,
                 blobs: BlobStore | None = None) -> None:
        self._core = core
        self._store = core.store
        # Blobs default to the on-disk store under $BUILDER_HOME: recipe
        # documents are content-addressed and must outlive the process, or
        # a second fold over the same log (§5.2 step 1) cannot read them.
        self._recipes = TheRecipeStore(
            ledger=SpineRecipeLedger(core.store),
            blobs=blobs or FileBlobStore(core.settings.home),
            schemas=schemas,
            clock=now_utc,
        )
        self._owner = Actor(kind="owner", id="casey")
        #: spine branch id (or alias) -> the recipe store's branch id
        self._branch_ids: dict[str, str] = {MAIN: MAIN, "main": MAIN}
        #: the branch a live typed call commits onto (§1.2's branch context).
        #: The spine's edit proposal carries `base: "head"` — of *this*
        #: branch, not always main: a night's calls commit onto the night's
        #: branch and the morning decides. The spec amendment that puts the
        #: branch on the edit itself is pending; the seam holds it until
        #: then, defaulting to main.
        self.commit_branch: str = MAIN

    # -- setup ---------------------------------------------------------------

    def seed_recipe(self, recipe: Recipe | RecipeRecord | dict) -> str:
        """Create the project's recipe (idempotent): the root version and the
        protected main branch (§1.2). Returns the root version id."""
        if isinstance(recipe, dict):
            recipe = RecipeRecord.model_validate(recipe)
        if recipe.id in {b.recipe for b in self._recipes.list_branches()}:
            return self._recipes.get_branch(MAIN).head
        self._recipes.create_recipe(recipe, self._owner)
        return self._recipes.get_branch(MAIN).head

    def register_branch(self, alias: str, branch_id: str) -> None:
        self._branch_ids[alias] = branch_id

    def branch_id(self, alias_or_id: str) -> str:
        if alias_or_id in self._branch_ids:
            return self._branch_ids[alias_or_id]
        # a real store id passes through when the store knows it — a caller
        # holding the store's own branch id (the acceptance adapters do)
        # must not be silently routed to main
        if any(b.id == alias_or_id for b in self._recipes.list_branches()):
            return alias_or_id
        return MAIN

    def head(self, alias_or_id: str = MAIN) -> str:
        return self._recipes.get_branch(self.branch_id(alias_or_id)).head

    @property
    def store(self) -> TheRecipeStore:
        """The recipe store itself — e.g. for the compiler's adapter
        (``builder_usd.recipe_source.BuilderRecipeSource``), which reads
        committed versions through the store's own interface."""
        return self._recipes

    def document(self, version_id: str) -> dict:
        return self._recipes.get_document(version_id).model_dump(mode="json")

    def version(self, version_id: str) -> dict:
        """The committed-version record (§1.2): parent, edit, root_hash."""
        return self._recipes.get_version(version_id).model_dump(mode="json")

    def diff(self, base: str, head: str) -> list[Op]:
        """The canonical op list that turns ``base`` into ``head`` (§1.1:
        the diff *is* the op list)."""
        return self._recipes.diff(base, head)

    # -- the port (core/ports.py) ---------------------------------------------

    def commit_edit(self, edit: RecipeEdit) -> str:
        """A validated edit becomes a version (§1.1): node-id paths resolve
        through the registry, `base: "head"` resolves to the current head."""
        node_map = {
            row.get("node_id"): row.get("entry_path")
            for row in self._store.scan("node_refs")
            if not row.get("orphaned")
        }
        ops = []
        for op in edit.ops or []:
            parts = op.path.split(".")
            target = node_map.get(parts[0], parts[0])
            rest = parts[1:]
            if (rest[:1] == ["params"] and len(rest) == 1
                    and isinstance(op.value, dict) and op.op == "set"):
                for key, value in sorted(op.value.items()):
                    ops.append(Op(op="set", path=f"{target}.params.{key}",
                                  value=value))
                continue
            ops.append(Op(op=op.op, path=".".join([target, *rest]),
                          value=op.value))
        base = edit.base if edit.base.startswith("ver_") else self.head(
            self._branch_ids.get(self.commit_branch, self.commit_branch))
        version = self._recipes.apply_edit(
            base, ops,
            author=Actor(kind=edit.author.kind, id=edit.author.id,
                         via=edit.author.via),
            message=(edit.message or "typed edit")[:80],
            prediction=edit.prediction,
        )
        # A builder's live edit applies: the branch moves forward with the
        # version it just gained (§1.2 — a fast-forward, never a rewrite).
        # The move is the core executing the call the spine already audited
        # (vocab.call carries the character), so it rides a core actor —
        # on one log it must not read as a second owner decision (G §4.3,
        # found by the rewired melt week).
        self._recipes.move_head(
            self._branch_ids.get(self.commit_branch, self.commit_branch),
            version.id, core_actor(), reason="vocab call committed")
        return version.id

    def fast_forward(self, branch_id: str, to_version: str) -> None:
        target = self.branch_id(branch_id)
        if self._recipes.get_branch(target).head != to_version:
            self._recipes.move_head(target, to_version, core_actor(),
                                    reason="apply")

    def merge_conflicts(self, main_head: str, branch_head: str) -> list[str]:
        ours = self._recipes.get_version(main_head)
        theirs = self._recipes.get_version(branch_head)
        if ours.parent is None or theirs.parent != main_head:
            return []  # a fast-forward, not a merge
        base = self._recipes.get_document(ours.parent)
        _, conflicts = three_way_merge(
            base, self._recipes.get_document(main_head),
            self._recipes.get_document(branch_head),
        )
        return [str(getattr(c, "message", None) or c) for c in conflicts]
