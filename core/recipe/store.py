"""The recipe store — recipes, versions, branches and typed edits.

Core-spec v2 §1.1, §1.2. The store is a **projection** over the audit log:
every state change is one append to the ledger, and the whole projection can
be rebuilt by folding the log (§1.0). It owns no state of its own that the
log does not carry.

What the API half (half A) needs from here:

* :meth:`RecipeStore.create_recipe` — a project starts as its recipe;
* :meth:`RecipeStore.apply_edit` — the typed change, validated at the door;
* :meth:`RecipeStore.create_branch`, :meth:`RecipeStore.move_head`,
  :meth:`RecipeStore.apply_branch`, :meth:`RecipeStore.reject_branch`,
  :meth:`RecipeStore.merge_branch` — the branch model, including the kid
  actor's proposal path;
* :meth:`RecipeStore.diff` — the op list between two versions;
* :meth:`RecipeStore.get_document` — a version's canonical document.

The store codes against the small :class:`core.recipe.ledger.Ledger`
protocol, so the API half can hand it the real SQLite ledger.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from core.recipe.blobs import BlobStore, MemoryBlobStore
from core.recipe.canonical import canonical_bytes, content_hash
from core.recipe.constraints import ConstraintChecker
from core.recipe.dirty import AssetProducers, DirtySet, compute_dirty_set
from core.recipe.edits import apply_ops, diff_recipes, touched_entries
from core.recipe.errors import (
    BranchError,
    ConstraintViolation,
    EditRejected,
    MergeConflict,
    NotFound,
    RecipeError,
    SchemaViolation,
)
from core.recipe.ledger import Ledger
from core.recipe.merge import Conflict, three_way_merge
from core.recipe.models import (
    Actor,
    Branch,
    BranchProposal,
    Op,
    Recipe,
    RecipeEdit,
    RecipeRecord,
    RecipeVersion,
    ValidationReport,
)
from core.recipe.noderegistry import NodeRegistryProvider
from core.recipe.schema import ParamViolation, StaticSchemaRegistry, validate_params
from core.recipe.stagecache import entry_stage_key, stage_cache_key

__all__ = ["RecipeStore", "ApplyHook", "QuestionSink"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class QuestionSink(Protocol):
    """Where a merge conflict parks its question (the API half's store)."""

    def park(
        self, *, name: str, branch: str, options: list[str], detail: str
    ) -> str: ...


class ApplyHook(Protocol):
    """Called after a branch is applied.

    The API half resolves outstanding ``taste_keep`` predictions on that
    branch here — the owner's apply/keep/reject is the only event that scores
    them (§1.7).
    """

    def on_apply(self, *, branch: Branch, actor: Actor, version: RecipeVersion) -> None: ...


def _next_id(existing: Iterable[str], prefix: str, width: int = 4) -> str:
    highest = 0
    for item in existing:
        if item.startswith(prefix):
            suffix = item[len(prefix) :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1:0{width}d}"


class RecipeStore:
    """Recipes, versions and branches, projected over the audit log."""

    def __init__(
        self,
        *,
        ledger: Ledger,
        blobs: BlobStore | None = None,
        schemas: StaticSchemaRegistry | None = None,
        registry_provider: NodeRegistryProvider | None = None,
        questions: QuestionSink | None = None,
        apply_hook: ApplyHook | None = None,
        clock=_utcnow,
        home: Path | str | None = None,
        kid_actor_ids: Sequence[str] = ("magnus",),
        require_schema: bool = True,
    ) -> None:
        self.ledger = ledger
        self.blobs = blobs or MemoryBlobStore()
        self.schemas = schemas if schemas is not None else StaticSchemaRegistry()
        self.registry_provider = registry_provider
        self.questions = questions
        self.apply_hook = apply_hook
        self.clock = clock
        self.home = Path(home) if home is not None else None
        self.kid_actor_ids = set(kid_actor_ids)
        self.require_schema = require_schema

        self._recipes: dict[str, RecipeRecord] = {}
        self._versions: dict[str, RecipeVersion] = {}
        self._branches: dict[str, Branch] = {}
        self._edits: dict[str, RecipeEdit] = {}
        self._proposals: dict[str, BranchProposal] = {}
        self.rebuild()

    # -- projections -------------------------------------------------------

    def rebuild(self) -> None:
        """Fold the audit log into the projections (§1.0, §5.2 step 1)."""
        self._recipes.clear()
        self._versions.clear()
        self._branches.clear()
        self._edits.clear()
        self._proposals.clear()

        for event in self.ledger.events():
            payload = event.payload
            if event.type == "version.committed":
                if "version" not in payload:
                    # The spine's spelling (branch + head, document carried by
                    # the artifact): its projection is the spine's own fold.
                    continue
                version = RecipeVersion(
                    id=payload["version"],
                    recipe=payload["recipe"],
                    parent=payload.get("parent"),
                    edit=payload.get("edit"),
                    root_hash=payload["root_hash"],
                    at=event.at,
                    actor=event.actor,
                )
                self._versions[version.id] = version
                self._recipes.setdefault(
                    version.recipe,
                    RecipeRecord(
                        id=version.recipe,
                        name=payload.get("name", version.recipe),
                        root_version=version.id,
                        created_at=event.at,
                    ),
                )
            elif event.type == "branch.created":
                if "branch" not in payload or "recipe" not in payload:
                    continue  # the spine's spelling; see version.committed above
                branch = Branch(
                    id=payload["branch"],
                    name=payload["name"],
                    recipe=payload["recipe"],
                    head=payload["head"],
                    base=payload.get("base"),
                    purpose=payload["purpose"],
                    created_by=event.actor,
                    protected=bool(payload.get("protected", False)),
                )
                self._branches[branch.id] = branch
            elif event.type == "branch.head.moved":
                branch = self._branches.get(payload["branch"])
                if branch is not None:
                    branch.head = payload["to"]
            elif event.type == "branch.rejected":
                branch = self._branches.get(payload["branch"])
                if branch is not None:
                    branch.purpose = "rejected"
            elif event.type == "edit.proposed":
                self._edits[payload["edit"]] = RecipeEdit(
                    id=payload["edit"],
                    base=payload["base"],
                    ops=[Op.model_validate(op) for op in payload.get("ops", [])],
                    author=event.actor,
                    message=payload.get("message", ""),
                    prediction=payload.get("prediction"),
                )
            elif event.type == "branch.proposed":
                self._proposals[payload["proposal"]] = BranchProposal(
                    id=payload["proposal"],
                    branch=payload["branch"],
                    proposed_head=payload["head"],
                    by=event.actor,
                    at=event.at,
                    state="pending",
                )

    def listing(self) -> dict[str, Any]:
        """A deterministic listing of the store (the plan's ``--json`` check)."""
        return {
            "recipes": [
                self._recipes[key].model_dump() for key in sorted(self._recipes)
            ],
            "versions": [
                self._versions[key].model_dump() for key in sorted(self._versions)
            ],
            "branches": [
                self._branches[key].model_dump() for key in sorted(self._branches)
            ],
        }

    # -- reads -------------------------------------------------------------

    def get_recipe(self, recipe_id: str) -> RecipeRecord:
        record = self._recipes.get(recipe_id)
        if record is None:
            raise NotFound(f"no recipe {recipe_id!r}")
        return record

    def get_version(self, version_id: str) -> RecipeVersion:
        version = self._versions.get(version_id)
        if version is None:
            raise NotFound(f"no version {version_id!r}")
        return version

    def get_branch(self, branch_id: str) -> Branch:
        branch = self._branches.get(branch_id)
        if branch is None:
            raise NotFound(f"no branch {branch_id!r}")
        return branch

    def get_edit(self, edit_id: str) -> RecipeEdit:
        edit = self._edits.get(edit_id)
        if edit is None:
            raise NotFound(f"no edit {edit_id!r}")
        return edit

    def get_proposal(self, proposal_id: str) -> BranchProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise NotFound(f"no proposal {proposal_id!r}")
        return proposal

    def get_document(self, version_id: str) -> Recipe:
        """The canonical document of a version, read from its blob."""
        version = self.get_version(version_id)
        data = self.blobs.get_bytes(version.root_hash)
        return Recipe.model_validate(json.loads(data.decode("utf-8")))

    def version_blob_ref(self, version_id: str) -> str:
        """The content hash a version's document is stored under."""
        return self.get_version(version_id).root_hash

    def list_versions(self, recipe_id: str | None = None) -> list[RecipeVersion]:
        versions = [
            version
            for version in self._versions.values()
            if recipe_id is None or version.recipe == recipe_id
        ]
        return sorted(versions, key=lambda v: v.id)

    def list_branches(self, recipe_id: str | None = None) -> list[Branch]:
        branches = [
            branch
            for branch in self._branches.values()
            if recipe_id is None or branch.recipe == recipe_id
        ]
        return sorted(branches, key=lambda b: b.id)

    def list_edits(self) -> list[RecipeEdit]:
        return [self._edits[key] for key in sorted(self._edits)]

    def diff(self, base: str, head: str) -> list[Op]:
        """The op list between two versions."""
        return diff_recipes(self.get_document(base), self.get_document(head))

    # -- the stage cache and the dirty set ----------------------------------

    def stage_key(
        self, version_id: str, stage_name: str, dep_keys: Sequence[str] = ()
    ) -> str:
        """The stage-cache key of a stage at a version (§1.9)."""
        version = self.get_version(version_id)
        document = self.get_document(version_id)
        return stage_cache_key(
            version.root_hash, document.engine_pin, stage_name, dep_keys
        )

    def entry_stage_key(self, version_id: str, entry_path: str) -> str:
        """The stage-cache key of one entry's stage."""
        document = self.get_document(version_id)
        entry = document.entries.get(entry_path)
        if entry is None:
            raise NotFound(f"no entry {entry_path!r} in {version_id!r}")
        return entry_stage_key(entry_path, entry, document.engine_pin)

    def dirty_set(
        self,
        base: str,
        head: str,
        *,
        stages: Mapping[str, Sequence[str]] | None = None,
        asset_producers: AssetProducers | None = None,
    ) -> DirtySet:
        """The dirty set between two versions (§1.1)."""
        return compute_dirty_set(
            self.get_document(base),
            self.get_document(head),
            registry=self._registry_for(head),
            asset_producers=asset_producers,
            stages=stages,
        )

    # -- the vocabulary door ----------------------------------------------

    def build_vocab_edit(
        self,
        *,
        word: str,
        node: str | None,
        params: dict[str, Any],
        author: Actor,
        message: str,
        base: str,
        entry_path: str | None = None,
    ) -> RecipeEdit:
        """Validate a typed word call and build the edit it produces (§1.5).

        Anything outside the schema is refused here, at the door: the
        character hears "I can't do rope yet" instead of the world silently
        changing.
        """
        if self.schemas is not None and word not in self.schemas.words():
            raise SchemaViolation(
                [
                    ParamViolation(
                        "",
                        f"the word {word!r} is not in the vocabulary",
                        code="unknown-word",
                    )
                ]
            )

        path = entry_path or self._entry_for_node(node, base)
        if path is None:
            raise SchemaViolation(
                [
                    ParamViolation(
                        "",
                        f"the node {node!r} is not in the node registry",
                        code="no-referent",
                    )
                ]
            )

        schema = self.schemas.schema_for(path) if self.schemas else None
        if schema is None:
            raise SchemaViolation(
                [
                    ParamViolation(
                        path,
                        "there is no vocabulary schema for this entry",
                        code="no-schema",
                    )
                ]
            )

        violations = validate_params(params, schema)
        if violations:
            raise SchemaViolation(violations)

        ops = [
            Op(op="set", path=f"{path}.params.{key}", value=value)
            for key, value in sorted(params.items())
        ]
        edit_id = _next_id(self._edits.keys(), "ed_")
        return RecipeEdit(
            id=edit_id, base=base, ops=ops, author=author, message=message
        )

    def vocab_call(
        self,
        *,
        word: str,
        node: str | None,
        params: dict[str, Any],
        author: Actor,
        message: str,
        base: str,
        entry_path: str | None = None,
    ) -> RecipeVersion:
        """A character's typed call: validate at the door, then apply.

        Refused calls are audited — the edges are the story (D §5.5).
        """
        try:
            edit = self.build_vocab_edit(
                word=word,
                node=node,
                params=params,
                author=author,
                message=message,
                base=base,
                entry_path=entry_path,
            )
        except SchemaViolation as exc:
            self._audit_vocab_call(
                word=word,
                node=node,
                params=params,
                author=author,
                ok=False,
                reason=str(exc),
            )
            raise

        self._audit_vocab_call(
            word=word,
            node=node,
            params=params,
            author=author,
            ok=True,
            reason="",
        )
        return self.apply_edit(base, edit.ops, author=author, message=message)

    # -- writes: recipes and versions --------------------------------------

    def create_recipe(self, recipe: Recipe, actor: Actor) -> Recipe:
        """A project starts as its recipe: a root version and a main branch."""
        if recipe.id in self._recipes:
            raise RecipeError(f"recipe {recipe.id!r} already exists")
        report = self._validate(recipe, touched=set(recipe.entries), version_id=None)
        self._raise_for(report)
        version = self._commit_version(
            recipe, parent=None, edit=None, actor=actor, message="recipe created"
        )
        self._create_branch(
            name="main",
            recipe=recipe.id,
            head=version.id,
            purpose="main",
            actor=actor,
            base=None,
            protected=True,
        )
        return recipe

    def apply_edit(
        self,
        base: str,
        ops: Sequence[Op],
        *,
        author: Actor,
        message: str,
        prediction: str | None = None,
        branch: str | None = None,
    ) -> RecipeVersion:
        """Apply a typed edit to a version and commit the result.

        The edit is admitted only if the resulting document passes every
        touched entry's vocabulary param schema and every project constraint
        that is machine-checkable pre-render (§1.1).
        """
        base_version = self.get_version(base)
        base_document = self.get_document(base)

        edit_id = _next_id(self._edits.keys(), "ed_")
        edit = RecipeEdit(
            id=edit_id,
            base=base,
            ops=list(ops),
            author=author,
            message=message,
            prediction=prediction,
        )
        self.ledger.append(
            type="edit.proposed",
            actor=author,
            at=self.clock(),
            subject={"entity_kind": "edit", "entity_id": edit_id},
            payload={
                "edit": edit_id,
                "base": base,
                "ops": [op.model_dump() for op in edit.ops],
                "message": message,
                "prediction": prediction,
            },
        )
        self._edits[edit_id] = edit

        try:
            document = apply_ops(base_document, edit.ops)
        except EditRejected as exc:
            self._audit_failed_edit(edit, str(exc))
            raise

        touched = touched_entries(base_document, edit.ops)
        report = self._validate(document, touched=touched, version_id=base)
        if not report.ok:
            self._audit_failed_report(edit, report)
            self._raise_for(report)

        version_id = _next_id(self._versions.keys(), "ver_")
        self.ledger.append(
            type="edit.validated",
            actor=author,
            at=self.clock(),
            subject={"entity_kind": "edit", "entity_id": edit_id},
            payload={
                "ok": True,
                "edit": edit_id,
                "base": base,
                "version": version_id,
                "touched": report.touched,
            },
        )

        version = self._commit_version(
            document,
            parent=base,
            edit=edit_id,
            actor=author,
            message=message,
            version_id=version_id,
            at=self.clock(),
        )
        if branch is not None:
            self.move_head(branch, version.id, actor=author, reason="edit")
        return version

    # -- writes: branches --------------------------------------------------

    def create_branch(
        self,
        *,
        name: str,
        recipe: str,
        head: str,
        purpose: str,
        actor: Actor,
        base: str | None = None,
        protected: bool = False,
    ) -> Branch:
        if recipe not in self._recipes:
            raise BranchError(f"no recipe {recipe!r}")
        if head not in self._versions:
            raise BranchError(f"no version {head!r}")
        return self._create_branch(
            name=name,
            recipe=recipe,
            head=head,
            purpose=purpose,
            actor=actor,
            base=base,
            protected=protected,
        )

    def _create_branch(
        self,
        *,
        name: str,
        recipe: str,
        head: str,
        purpose: str,
        actor: Actor,
        base: str | None,
        protected: bool,
    ) -> Branch:
        if purpose == "main" and name == "main":
            branch_id = "br_main"
        else:
            branch_id = _next_id(self._branches.keys(), "br_")
        branch = Branch(
            id=branch_id,
            name=name,
            recipe=recipe,
            head=head,
            base=base,
            purpose=purpose,  # type: ignore[arg-type]
            created_by=actor,
            protected=protected,
        )
        self.ledger.append(
            type="branch.created",
            actor=actor,
            at=self.clock(),
            subject={"entity_kind": "branch", "entity_id": branch_id},
            payload={
                "branch": branch_id,
                "name": name,
                "recipe": recipe,
                "head": head,
                "base": base,
                "purpose": purpose,
                "protected": protected,
            },
        )
        self._branches[branch_id] = branch
        return branch

    def move_head(
        self, branch_id: str, head: str, actor: Actor, reason: str = "edit"
    ) -> Branch:
        """Move a branch head forward. Heads never move backwards."""
        branch = self.get_branch(branch_id)
        if head not in self._versions:
            raise BranchError(f"no version {head!r}")
        if not self._is_descendant(head, branch.head):
            raise BranchError(
                f"branch {branch_id!r} is at {branch.head!r}; a head moves only "
                f"forward, so it cannot move to {head!r}"
            )
        self.ledger.append(
            type="branch.head.moved",
            actor=actor,
            at=self.clock(),
            subject={"entity_kind": "branch", "entity_id": branch_id},
            payload={"branch": branch_id, "from": branch.head, "to": head, "reason": reason},
        )
        branch.head = head
        return branch

    def apply_branch(self, branch_id: str, actor: Actor) -> Branch | BranchProposal:
        """The morning flip: ``main.head = branch.head`` — a pointer move.

        A kid actor's apply is a proposal: a branch apply is a real edit, so
        Magnus's becomes ``branch.proposed`` until the owner confirms it.
        """
        branch = self.get_branch(branch_id)
        if self._is_kid(actor):
            return self._propose(branch, actor)
        main = self._main_branch(branch.recipe)
        self._apply_to_main(main, branch.head, actor)
        return main

    def confirm_proposal(self, proposal_id: str, actor: Actor) -> Branch:
        """The owner confirms a kid's proposed branch choice."""
        proposal = self.get_proposal(proposal_id)
        if proposal.state != "pending":
            raise BranchError(f"proposal {proposal_id!r} is {proposal.state}")
        branch = self.get_branch(proposal.branch)
        main = self._main_branch(branch.recipe)
        self._apply_to_main(main, proposal.proposed_head, actor)
        proposal.state = "confirmed"
        return main

    def decline_proposal(self, proposal_id: str, actor: Actor) -> BranchProposal:
        proposal = self.get_proposal(proposal_id)
        proposal.state = "declined"
        return proposal

    def reject_branch(
        self, branch_id: str, actor: Actor, reason: str | None = None
    ) -> Branch:
        """Rejection never deletes: the branch is retargeted and stays visitable."""
        branch = self.get_branch(branch_id)
        if branch.protected:
            raise BranchError(f"branch {branch_id!r} is protected and cannot be rejected")
        self.ledger.append(
            type="branch.rejected",
            actor=actor,
            at=self.clock(),
            subject={"entity_kind": "branch", "entity_id": branch_id},
            payload={"branch": branch_id, "reason": reason or ""},
        )
        branch.purpose = "rejected"
        return branch

    def standing_options(
        self, recipe: str, base_version: str, actor: Actor
    ) -> list[Branch]:
        """The two standing options every branch set contains (§1.2).

        *keep yesterday* is main unchanged; *back to the plan* is a fresh
        standing branch cut from the slate's base — "start over" is a
        checkout, not a deletion.
        """
        main = self._main_branch(recipe)
        keep = self._create_branch(
            name="keep-yesterday",
            recipe=recipe,
            head=main.head,
            purpose="standing",
            actor=actor,
            base=main.head,
            protected=False,
        )
        back = self._create_branch(
            name="back-to-plan",
            recipe=recipe,
            head=base_version,
            purpose="standing",
            actor=actor,
            base=base_version,
            protected=False,
        )
        return [keep, back]

    def merge_branch(self, branch_id: str, actor: Actor) -> RecipeVersion:
        """Merge a branch into main: fast-forward, or three-way at entry level."""
        branch = self.get_branch(branch_id)
        main = self._main_branch(branch.recipe)

        if self._is_descendant(branch.head, main.head):
            self.move_head(main.id, branch.head, actor=actor, reason="merge")
            return self.get_version(branch.head)

        ancestor = self._common_ancestor(main.head, branch.head)
        if ancestor is None:
            raise MergeConflict(
                [
                    Conflict(
                        "main",
                        None,
                        main.head,
                        branch.head,
                    )
                ]
            )

        base_document = self.get_document(ancestor).model_dump()
        main_document = self.get_document(main.head).model_dump()
        branch_document = self.get_document(branch.head).model_dump()
        merged, conflicts = three_way_merge(base_document, main_document, branch_document)

        if conflicts:
            detail = ", ".join(conflict.path for conflict in conflicts)
            if self.questions is not None:
                self.questions.park(
                    name="merge-conflict",
                    branch=branch.id,
                    options=["ours", "theirs"],
                    detail=detail,
                )
            raise MergeConflict(conflicts)

        document = Recipe.model_validate(merged)
        report = self._validate(document, touched=set(document.entries), version_id=main.head)
        self._raise_for(report)

        version = self._commit_version(
            document,
            parent=main.head,
            edit=None,
            actor=actor,
            message=f"merge {branch.name}",
        )
        self.move_head(main.id, version.id, actor=actor, reason="merge")
        return version

    # -- internals ---------------------------------------------------------

    def _main_branch(self, recipe: str) -> Branch:
        for branch in self._branches.values():
            if branch.recipe == recipe and branch.purpose == "main":
                return branch
        raise BranchError(f"recipe {recipe!r} has no main branch")

    def _is_kid(self, actor: Actor) -> bool:
        return actor.kind == "character" or actor.id in self.kid_actor_ids

    def _propose(self, branch: Branch, actor: Actor) -> BranchProposal:
        proposal_id = _next_id(self._proposals.keys(), "prop_")
        proposal = BranchProposal(
            id=proposal_id,
            branch=branch.id,
            proposed_head=branch.head,
            by=actor,
            at=self.clock(),
            state="pending",
        )
        self.ledger.append(
            type="branch.proposed",
            actor=actor,
            at=self.clock(),
            subject={"entity_kind": "branch_proposal", "entity_id": proposal_id},
            payload={
                "proposal": proposal_id,
                "branch": branch.id,
                "head": branch.head,
                "by": actor.id,
            },
        )
        self._proposals[proposal_id] = proposal
        return proposal

    def _apply_to_main(self, main: Branch, head: str, actor: Actor) -> Branch:
        if not self._is_descendant(head, main.head):
            raise BranchError(
                f"main is at {main.head!r}; {head!r} is not ahead of it, so this "
                "is a merge, not an apply"
            )
        self.move_head(main.id, head, actor=actor, reason="apply")
        if self.apply_hook is not None:
            self.apply_hook.on_apply(
                branch=main, actor=actor, version=self.get_version(head)
            )
        return main

    def _ancestors(self, version_id: str) -> list[str]:
        chain: list[str] = []
        current: str | None = version_id
        while current and current not in chain:
            chain.append(current)
            version = self._versions.get(current)
            if version is None:
                break
            current = version.parent
        return chain

    def _is_descendant(self, candidate: str, ancestor: str) -> bool:
        return ancestor in self._ancestors(candidate)

    def _common_ancestor(self, one: str, other: str) -> str | None:
        others = self._ancestors(other)
        for candidate in self._ancestors(one):
            if candidate in others:
                return candidate
        return None

    def _registry_for(self, version_id: str | None) -> Any:
        if version_id is None or self.registry_provider is None:
            return None
        return self.registry_provider.registry_for(version_id)

    def _entry_for_node(self, node: str | None, version_id: str) -> str | None:
        if node is None:
            return None
        registry = self._registry_for(version_id)
        if registry is None:
            return None
        ref = registry.resolve_node(node)
        return ref.entry_path if ref is not None else None

    def _audit_vocab_call(
        self,
        *,
        word: str,
        node: str | None,
        params: dict[str, Any],
        author: Actor,
        ok: bool,
        reason: str,
    ) -> None:
        recorded = params
        if len(canonical_bytes(params)) > 1024:
            recorded = {"truncated": True, "keys": sorted(params)}
        self.ledger.append(
            type="vocab.call",
            actor=author,
            at=self.clock(),
            subject={"entity_kind": "vocabulary_word", "entity_id": word},
            payload={
                "word": word,
                "node": node,
                "params": recorded,
                "ok": ok,
                "reason": reason,
            },
        )

    def _validate(
        self, document: Recipe, touched: set[str], version_id: str | None
    ) -> ValidationReport:
        violations: list[ParamViolation] = []
        for path in sorted(touched):
            entry = document.entries.get(path)
            if entry is None:
                continue
            schema = self.schemas.schema_for(path) if self.schemas else None
            if schema is None:
                if self.require_schema and entry.origin != "builtin":
                    violations.append(
                        ParamViolation(
                            path,
                            "there is no vocabulary schema for this entry",
                            code="no-schema",
                        )
                    )
                continue
            violations.extend(validate_params(entry.params, schema))

        checker = ConstraintChecker(registry=self._registry_for(version_id))
        checks = checker.check(document, touched=touched)
        failed = [check for check in checks if check.status == "fail"]

        return ValidationReport(
            ok=not violations and not failed,
            touched=sorted(touched),
            schema_violations=[violation.as_dict() for violation in violations],
            constraint_checks=[check.as_dict() for check in checks],
        )

    def _raise_for(self, report: ValidationReport) -> None:
        if report.schema_violations:
            raise SchemaViolation(
                [
                    ParamViolation(
                        item["path"], item["message"], item.get("code", "schema")
                    )
                    for item in report.schema_violations
                ]
            )
        failed = [item for item in report.constraint_checks if item["status"] == "fail"]
        if failed:
            raise ConstraintViolation(failed)

    def _audit_failed_edit(self, edit: RecipeEdit, reason: str) -> None:
        self.ledger.append(
            type="edit.validated",
            actor=edit.author,
            at=self.clock(),
            subject={"entity_kind": "edit", "entity_id": edit.id},
            payload={"ok": False, "edit": edit.id, "base": edit.base, "reason": reason},
        )

    def _audit_failed_report(self, edit: RecipeEdit, report: ValidationReport) -> None:
        """The refusal is in the log: the edit did not validate, and why."""
        failed = [item for item in report.constraint_checks if item["status"] == "fail"]
        self.ledger.append(
            type="edit.validated",
            actor=edit.author,
            at=self.clock(),
            subject={"entity_kind": "edit", "entity_id": edit.id},
            payload={
                "ok": False,
                "edit": edit.id,
                "base": edit.base,
                "schema_violations": report.schema_violations,
                "constraint_failures": failed,
            },
        )
        for check in failed:
            self.ledger.append(
                type="constraint.failed",
                actor=edit.author,
                at=self.clock(),
                subject={"entity_kind": "constraint", "entity_id": check["name"]},
                payload={"edit": edit.id, "base": edit.base, **check},
            )

    def _commit_version(
        self,
        document: Recipe,
        *,
        parent: str | None,
        edit: str | None,
        actor: Actor,
        message: str,
        version_id: str | None = None,
        at: str | None = None,
    ) -> RecipeVersion:
        payload_document = document.model_dump()
        root_hash = content_hash(payload_document)
        self.blobs.put_json(payload_document)

        if version_id is None:
            version_id = _next_id(self._versions.keys(), "ver_")
        at = at or self.clock()

        version = RecipeVersion(
            id=version_id,
            recipe=document.id,
            parent=parent,
            edit=edit,
            root_hash=root_hash,
            at=at,
            actor=actor,
        )
        self.ledger.append(
            type="version.committed",
            actor=actor,
            at=at,
            subject={"entity_kind": "recipe_version", "entity_id": version_id},
            payload={
                "version": version_id,
                "recipe": document.id,
                "parent": parent,
                "edit": edit,
                "root_hash": root_hash,
                "name": document.name,
                "message": message,
            },
            artifact={
                "sha256": root_hash,
                "kind": "recipe_doc",
                "bytes": len(canonical_bytes(payload_document)),
            },
        )
        self._versions[version_id] = version
        self._recipes.setdefault(
            document.id,
            RecipeRecord(
                id=document.id,
                name=document.name,
                root_version=version_id,
                created_at=at,
            ),
        )
        self._mirror(version_id, payload_document)
        return version

    def _mirror(self, version_id: str, document: dict[str, Any]) -> None:
        """The human-readable mirror of a version's document (§1.0)."""
        if self.home is None:
            return
        mirror = self.home / "recipes" / f"{version_id}.json"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
