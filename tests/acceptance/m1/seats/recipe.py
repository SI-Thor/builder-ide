"""The recipe seat — `core.recipe` behind the spine's own seam, one store.

Before the merge this adapter ran the recipe store on its **own**
`InMemoryLedger` under the run directory (the honest seam of the day: the
seats were not merged, so the recipe store's audit log was not the spine's
one log) and carried two cross-seat DRIFTS. The integrated core resolves
both at the source:

* the spine's `RecipeStore` port is `core.svc.recipes.RecipeStoreSeam` —
  the real store over `SpineRecipeLedger`, so every `edit.proposed` /
  `version.committed` / `branch.*` event lands in the ONE audit log and
  folds into the spine's projections (§1.0; INTEGRATION.md §2);
* vocab's shipped Fjellvik document writes `prop_set` (the seat fixed it
  at the source), so the compat translation is gone — the document loads
  into the real store unchanged.

What remains adapter-shaped, on purpose:

* the driver addresses branches by alias ("main", "night", "plan"); the
  seam registers the spine's `br_…` ids against them;
* the session's **branch context** — which branch the night's typed calls
  commit onto — is still adapter state the driver sets
  (`recipe.seam_branch = "night"`); §1.2 makes branch context part of the
  edit itself once the spec amendment lands, and the seam's
  `commit_branch` is the hook for that day.

The node registry stays the publishing convention it always was: the
compiler's `nodes.json` artifact on `version.committed` (core/ports.py),
which the driver writes through the spine (`door.publish_nodes`).
"""

from __future__ import annotations

from typing import Any

RECIPE_ID = "rcp_fjellvik"
MAIN_BRANCH = "br_main"

#: Cross-seat drifts this adapter used to paper over — both resolved by the
#: merge (INTEGRATION.md §2, §5), kept here as the record of the rewiring.
DRIFTS: list[str] = [
    "RESOLVED: vocab's RECIPE_DOCUMENT wrote entry kind 'prop'; fixed at the "
    "source (core/vocab/seed.py) — the document loads unchanged now",
    "RESOLVED: the recipe seat ran on its own InMemoryLedger; "
    "SpineRecipeLedger routes the real store's appends into the spine's one "
    "audit log, so the seam's commits are the spine's own events",
]


class RecipeSeat:
    """The recipe store seat, wired once per session over the one store."""

    def __init__(self, seats, core) -> None:
        from core.svc.recipes import RecipeStoreSeam, schemas_from_vocabulary

        self.br = seats.recipe
        self._vocab = seats.vocab
        self._core = core

        seam = RecipeStoreSeam(
            core, schemas=schemas_from_vocabulary(seats.vocab.default_entries())
        )
        core.recipes = seam
        self.seam = seam
        self.store = seam.store
        self.owner = seam._owner
        self._seeded_version: str | None = None
        self._branch_ids: dict[str, str] = {MAIN_BRANCH: MAIN_BRANCH, "main": MAIN_BRANCH}

    @property
    def root_version(self) -> str:
        """The project's root version — seeded on first use, because with
        one store the recipe's creation events ARE the spine's first
        history, and the session's fresh-home step reads the log before
        `boot/recipe-seat` makes that history (§1.0)."""
        if self._seeded_version is None:
            self._seeded_version = self.seam.seed_recipe(
                self._vocab.seed.RECIPE_DOCUMENT)
        return self._seeded_version

    # -- the branch context (§1.2's pending amendment) ---------------------------

    @property
    def seam_branch(self) -> str:
        return getattr(self.seam, "commit_branch", MAIN_BRANCH)

    @seam_branch.setter
    def seam_branch(self, alias: str) -> None:
        self.seam.commit_branch = self.branch_id(alias)

    # -- the node registry (§1.4.0) ----------------------------------------------

    def derived_nodes(self, recipe: Any = None) -> list[dict]:
        registry = self.br.NodeRegistry.derived_from(recipe or self.recipe_document())
        return [
            {
                "node_id": node.node_id,
                "entry_path": node.entry_path,
                "kind": node.kind,
                "assets": list(node.assets),
            }
            for node in registry.nodes()
        ]

    def recipe_document(self) -> Any:
        return self.store.get_document(self.head(MAIN_BRANCH))

    def refresh_recipe(self, version_id: str) -> Any:
        return self.store.get_document(version_id)

    # -- versions and branches (§1.1–§1.2) -----------------------------------------
    # Branches are addressed by alias here ("main", "night", "plan"); the
    # store allocates br_… ids, and the mapping also answers the spine's
    # RecipeStore seam (spine br_ id → the store's own branch id).

    def register(self, alias: str, branch_id: str) -> None:
        self._branch_ids[alias] = branch_id
        self.seam.register_branch(alias, branch_id)

    def branch_id(self, alias_or_spine_id: str) -> str:
        return self._branch_ids.get(alias_or_spine_id, MAIN_BRANCH)

    def head(self, alias: str = MAIN_BRANCH) -> str:
        return self.seam.head(self.branch_id(alias))

    def document(self, version_id: str) -> dict:
        return self.seam.document(version_id)

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
        self.register(alias, branch.id)
        if spine_id:
            self.register(spine_id, branch.id)
        return branch.id

    def move_head(self, alias: str, version: str) -> None:
        self.store.move_head(self.branch_id(alias), version, self.owner)

    def diff_ops(self, base: str, head: str) -> list[dict]:
        return [
            {"op": op.op, "path": op.path, "value": op.value}
            for op in self.store.diff(base, head)
        ]

    def rebind(self, core) -> None:
        """After the kill: re-open the seam over the reopened core.

        The store itself survived in the ONE log (every recipe event is a
        spine event now), so the fresh store re-folds the same branches and
        versions; only the seam object and the branch map re-attach."""
        from core.svc.recipes import RecipeStoreSeam, schemas_from_vocabulary

        saved_branch = self.seam_branch
        seam = RecipeStoreSeam(
            core, schemas=schemas_from_vocabulary(self._vocab.default_entries())
        )
        core.recipes = seam
        self.seam = seam
        self.store = seam.store
        self._core = core
        for alias, branch_id in self._branch_ids.items():
            seam.register_branch(alias, branch_id)
        seam.commit_branch = saved_branch

    # the spine's RecipeStore port is the seam itself (the core's real
    # implementation — there is no adapter half left to name)
    def seam(self) -> object:
        return self.seam
