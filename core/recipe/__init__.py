"""The recipe store of builder-ide's core service (core-spec v2, half B).

A project is its recipe: generators, parameters, constraints and seeds. Meshes
and renders are caches. This package owns the recipe, its history and the
checks that keep a change honest:

* **recipes, versions and branches** — a recipe never mutates in place; change
  is a typed edit, a version is the canonical document it produced, and a
  branch is a named commit line whose head moves only forward (§1.1, §1.2);
* **typed edits** — the op list *is* the diff, in canonical JSON;
* **the recipe hash** — the sha256 over the canonical document, which the
  stage cache keys on (§1.9), and the dirty set that decides what a change
  re-evaluates (§1.1);
* **pre-render constraint checks** — out-of-schema params are refused at the
  door, and every machine-checkable project constraint is checked before
  anything is rendered (§1.5, §2.3.5).

The store is a projection over the audit log: every change is one append, and
the whole projection rebuilds by folding the log. It codes against the small
:class:`core.recipe.ledger.Ledger` protocol, so the API half hands it the
real SQLite ledger.

The seams the other half must fill
----------------------------------
* :class:`core.recipe.ledger.Ledger` — the append-only log (half A owns
  the real one; the SQLite implementation here is a conforming stub);
* :class:`core.recipe.schema.StaticSchemaRegistry` — the vocabulary param
  schemas, so ``/v1/vocab/call`` validates against the words the core knows;
* :class:`core.recipe.noderegistry.NodeRegistryProvider` — the node
  registry the engine publishes, which resolves a node id to an entry path;
* :class:`core.recipe.store.QuestionSink` — where a merge conflict parks
  its question;
* :class:`core.recipe.store.ApplyHook` — where the owner's apply scores
  the outstanding ``taste_keep`` predictions on that branch (§1.7).
"""

from __future__ import annotations

from core.recipe.blobs import BlobStore, FileBlobStore, MemoryBlobStore
from core.recipe.canonical import canonical_json, content_hash, hash_bytes
from core.recipe.constraints import ConstraintCheck, ConstraintChecker
from core.recipe.dirty import (
    AssetProducers,
    DirtySet,
    StaticAssetProducers,
    compute_dirty_set,
)
from core.recipe.edits import apply_ops, diff_recipes, touched_entries
from core.recipe.errors import (
    BranchError,
    ConstraintViolation,
    EditRejected,
    IntegrityError,
    MergeConflict,
    NotFound,
    RecipeError,
    SchemaDefinitionError,
    SchemaViolation,
)
from core.recipe.events import EVENT_TYPES, RECIPE_EVENT_TYPES
from core.recipe.ledger import InMemoryLedger, Ledger, SQLiteLedger
from core.recipe.merge import Conflict, three_way_merge
from core.recipe.models import (
    Actor,
    AuditEvent,
    Branch,
    BranchProposal,
    Constraint,
    EnginePin,
    GeneratorRef,
    NodeRef,
    Op,
    Recipe,
    RecipeEdit,
    RecipeEntry,
    RecipeRecord,
    RecipeVersion,
    ValidationReport,
)
from core.recipe.noderegistry import (
    NodeRegistry,
    NodeRegistryProvider,
    StaticNodeRegistryProvider,
    derive_node_id,
)
from core.recipe.schema import (
    ParamViolation,
    StaticSchemaRegistry,
    validate_params,
    validate_schema_definition,
)
from core.recipe.stagecache import entry_stage_key, stage_cache_key
from core.recipe.store import ApplyHook, QuestionSink, RecipeStore

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # models
    "Actor",
    "AuditEvent",
    "Branch",
    "BranchProposal",
    "Constraint",
    "EnginePin",
    "GeneratorRef",
    "NodeRef",
    "Op",
    "Recipe",
    "RecipeEdit",
    "RecipeEntry",
    "RecipeRecord",
    "RecipeVersion",
    "ValidationReport",
    # the store and its seams
    "RecipeStore",
    "ApplyHook",
    "QuestionSink",
    "Ledger",
    "InMemoryLedger",
    "SQLiteLedger",
    "BlobStore",
    "MemoryBlobStore",
    "FileBlobStore",
    "StaticSchemaRegistry",
    "ParamViolation",
    "validate_params",
    "validate_schema_definition",
    "NodeRegistry",
    "NodeRegistryProvider",
    "StaticNodeRegistryProvider",
    "derive_node_id",
    "AssetProducers",
    "StaticAssetProducers",
    "DirtySet",
    "compute_dirty_set",
    "ConstraintCheck",
    "ConstraintChecker",
    "Conflict",
    "three_way_merge",
    # hashes and ops
    "canonical_json",
    "content_hash",
    "hash_bytes",
    "apply_ops",
    "diff_recipes",
    "touched_entries",
    "stage_cache_key",
    "entry_stage_key",
    # events
    "EVENT_TYPES",
    "RECIPE_EVENT_TYPES",
    # errors
    "RecipeError",
    "NotFound",
    "IntegrityError",
    "SchemaDefinitionError",
    "SchemaViolation",
    "ConstraintViolation",
    "EditRejected",
    "BranchError",
    "MergeConflict",
]
