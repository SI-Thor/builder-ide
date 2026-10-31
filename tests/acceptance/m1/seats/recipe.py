"""The recipe seat (branch `core-recipe`): the store, and the node registry.

What this adapter does, all with the sibling's own code:

* **Fjellvik is created as a recipe** — `Recipe.model_validate` over the
  document the vocabulary seat ships (`core.vocab.seed.RECIPE_DOCUMENT`) is
  itself a cross-seat compatibility check: the two seats' recipe shapes
  must agree, or nothing downstream compiles.
* **The vocabulary validates edits** — `StaticSchemaRegistry` is seeded from
  the vocabulary seat's three words (`core.vocab.words.default_entries`),
  so the recipe store refuses out-of-schema params exactly as §1.1 demands.
  The registry's suffix rule maps the word `props.harbor.crates` onto the
  entry path `harbor.crates`.
* **The node registry is derived** — `NodeRegistry.derived_from(recipe)` is
  the §1.4.0 fallback derivation; the adapter publishes it into the spine
  as the compiler's `nodes.json` artifact, which is core-api's documented
  publishing convention (`core/ports.py`). The two-referent test at the end
  of the session resolves through exactly this chain.
* **The branch flip is a pointer move** — the morning's A/B options are
  committed versions on this store; `move_head` is fast-forward-only, and
  the adapter implements core-api's tiny `RecipeStore` seam (`commit_edit`
  / `fast_forward` / `merge_conflicts`) over it, so the spine's
  `/v1/branches/{id}/apply` reports `recipe_sync: ok` instead of
  `unavailable`.

The store runs on its own SQLite ledger under the run directory — the
honest seam of today: the seats are not merged, so the recipe store's audit
log is not yet the spine's one log. The README says so; the merge makes it
one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RECIPE_ID = "rcp_fjellvik"
MAIN_BRANCH = "br_main"

#: Cross-seat drifts the adapter papers over today, each a merge-time
#: decision. Found by this session; each is named where it is applied.
DRIFTS: list[str] = [
    "vocab's RECIPE_DOCUMENT writes entry kind 'prop'; spec §1.1 and "
    "core-recipe's RecipeEntry say 'prop_set' — translated on load",
    "the recipe seat runs on core-recipe's InMemoryLedger, not its "
    "SQLiteLedger: SQLiteLedger's connection is thread-bound and the spine's "
    "HTTP worker calls the seam from another thread (an artifact of the "
    "in-process TestClient; the single-writer SQLite ledger is the spine's)",
]


def _compat_document(document: dict) -> dict:
    """Seat-to-seat translation of the shipped Fjellvik document (see DRIFTS)."""
    import copy

    doc = copy.deepcopy(document)
    for entry in doc.get("entries", {}).values():
        _compat_entry_in_place(entry)
    return doc


def _compat_entry(entry: dict) -> dict:
    import copy

    out = copy.deepcopy(entry)
    _compat_entry_in_place(out)
    return out


def _compat_entry_in_place(entry: dict) -> None:
    if entry.get("kind") == "prop":
        entry["kind"] = "prop_set"


class RecipeSeam:
    """core-api's `RecipeStore` port (core/ports.py) over the real store.

    core-api's edit proposals carry `base: "head"` and node-id targets; the
    seam resolves both the way §1.4.0 says the node registry must — node id →
    entry path → params — and commits onto the branch the session has made
    current (adapter state; after the merge there is one store and one
    branch context, and this disappears).
    """

    def __init__(self, seat: "RecipeSeat") -> None:
        self._seat = seat

    @property
    def _branch(self) -> str:
        return getattr(self._seat, "seam_branch", None) or MAIN_BRANCH

    def commit_edit(self, edit) -> str:
        br = self._seat.br
        node_map = {n["node_id"]: n["entry_path"] for n in self._seat.derived_nodes()}
        ops = []
        for op in edit.ops or []:
            parts = op.path.split(".")
            if parts[0] in node_map:
                entry_path = node_map[parts[0]]
                rest = parts[1:]
                if rest[:1] == ["params"] and isinstance(op.value, dict) and len(rest) == 1:
                    for key, value in sorted(op.value.items()):
                        ops.append(br.Op(op="set", path=f"{entry_path}.params.{key}",
                                         value=value))
                    continue
                ops.append(br.Op(op=op.op, path=".".join([entry_path, *rest]),
                                 value=op.value))
            else:
                ops.append(br.Op(op=op.op, path=op.path, value=op.value))
        base = edit.base if edit.base.startswith("ver_") else self._seat.head(self._branch)
        version = self._seat.store.apply_edit(
            base, ops,
            author=br.Actor(kind=edit.author.kind, id=edit.author.id, via=edit.author.via),
            message=(edit.message or "typed edit")[:80], prediction=edit.prediction,
        )
        return version.id

    def fast_forward(self, branch_id: str, to_version: str) -> None:
        target = self._seat.branch_id(branch_id)
        if self._seat.store.get_branch(target).head != to_version:
            self._seat.store.move_head(target, to_version, self._seat.owner)

    def merge_conflicts(self, main_head: str, branch_head: str) -> list[str]:
        store = self._seat.store
        ours = store.get_version(main_head)
        theirs = store.get_version(branch_head)
        if ours.parent is None or theirs.parent != main_head:
            return []  # a fast-forward, not a merge
        base = store.get_document(ours.parent)
        _, conflicts = self._seat.br.three_way_merge(
            base, store.get_document(main_head), store.get_document(branch_head)
        )
        return [str(getattr(c, "message", None) or c) for c in conflicts]


class RecipeSeat:
    """The recipe store seat, wired once per session."""

    def __init__(self, seats, run_dir: Path) -> None:
        br = seats.recipe
        self.br = br
        self._vocab = seats.vocab

        schemas = br.StaticSchemaRegistry()
        for entry in seats.vocab.default_entries():
            schemas.register(entry.word, entry.params)

        self.store = br.RecipeStore(
            ledger=br.InMemoryLedger(), schemas=schemas
        )
        self.recipe = br.Recipe.model_validate(_compat_document(seats.vocab.seed.RECIPE_DOCUMENT))
        self.owner = br.Actor(kind="owner", id="casey")
        self.store.create_recipe(self.recipe, self.owner)
        self.root_version = self.store.get_branch(MAIN_BRANCH).head
        self._branch_ids: dict[str, str] = {MAIN_BRANCH: MAIN_BRANCH}
        #: which branch alias the seam commits edits onto (adapter state; §1.2
        #: makes branch context part of the edit once there is one store)
        self.seam_branch: str = MAIN_BRANCH

    # -- the node registry (§1.4.0) ----------------------------------------------

    def derived_nodes(self, recipe: Any = None) -> list[dict]:
        registry = self.br.NodeRegistry.derived_from(recipe or self.recipe)
        return [
            {
                "node_id": node.node_id,
                "entry_path": node.entry_path,
                "kind": node.kind,
                "assets": list(node.assets),
            }
            for node in registry.nodes()
        ]

    def refresh_recipe(self, version_id: str) -> Any:
        self.recipe = self.store.get_document(version_id)
        return self.recipe

    # -- versions and branches (§1.1–§1.2) -----------------------------------------
    # Branches are addressed by alias here ("main", "night", "plan"); the
    # store's own ids are br_… strings it allocates, and the mapping below
    # also answers the spine's RecipeStore seam (spine br_ id → alias).

    def branch_id(self, alias_or_spine_id: str) -> str:
        return self._branch_ids.get(alias_or_spine_id, MAIN_BRANCH)

    def head(self, alias: str = MAIN_BRANCH) -> str:
        return self.store.get_branch(self.branch_id(alias)).head

    def document(self, version_id: str) -> dict:
        return self.store.get_document(version_id).model_dump(mode="json")

    def apply_params(self, entry_path: str, params: dict, *, message: str,
                     base: str | None = None) -> str:
        """A typed param edit, validated against the vocabulary at the door."""
        ops = [
            self.br.Op(op="set", path=f"{entry_path}.params.{key}", value=value)
            for key, value in sorted(params.items())
        ]
        version = self.store.apply_edit(
            base or self.head(MAIN_BRANCH), ops, author=self.owner, message=message
        )
        return version.id

    def add_entry(self, entry: dict, *, message: str, base: str | None = None) -> str:
        """Add a whole entry (the evening's market stalls, for the referent test).

        `add` at a not-yet-existing entry path creates the entry (edits.py's
        creating rule); the path grammar is entry-relative, like the spec's
        own `harbor.crates.params.count`.
        """
        entry = _compat_entry(entry)
        op = self.br.Op(op="add", path=entry["path"], value=entry)
        version = self.store.apply_edit(
            base or self.head(MAIN_BRANCH), [op], author=self.owner, message=message
        )
        return version.id

    def new_branch(self, *, alias: str, name: str, purpose: str,
                   head: str | None = None, base: str | None = None,
                   spine_id: str | None = None) -> str:
        branch = self.store.create_branch(
            name=name, recipe=RECIPE_ID, head=head or self.head(MAIN_BRANCH),
            purpose=purpose, actor=self.owner, base=base,
        )
        self._branch_ids[alias] = branch.id
        if spine_id:
            self._branch_ids[spine_id] = branch.id
        return branch.id

    def move_head(self, alias: str, version: str) -> None:
        self.store.move_head(self.branch_id(alias), version, self.owner)

    def diff_ops(self, base: str, head: str) -> list[dict]:
        return [
            {"op": op.op, "path": op.path, "value": op.value}
            for op in self.store.diff(base, head)
        ]

    def seam(self) -> RecipeSeam:
        return RecipeSeam(self)
