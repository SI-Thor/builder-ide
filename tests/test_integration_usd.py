"""The merge's own proof: the compiled scene comes from the committed
recipe — the one-way rule (§7.11) with both halves real.

The USD backbone compiles a recipe into a layered stage; the recipe store
commits the recipe. This test runs both on one store: the compiler's own
Fjellvik fixture (the placement/material vocabulary it compiles) is
committed through the real store, and the compiler reads that committed
version back through its adapter — the manifest it emits carries the
store's own root hash, and re-emitting the same version produces the
identical manifest (the determinism claim, checkable by hand with
``builder-usd verify``).

The shipped §1.5 words (crates' count/style/...) do not compile yet: the
compiler's entry vocabulary covers placements and materials, and the
crates generator is engine-side work (§6.2). Recorded in INTEGRATION.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("builder_usd.compile", reason="the usd extra's wheels")

from builder_usd.compile import compile_recipe  # noqa: E402
from builder_usd.provenance import Provenance  # noqa: E402
from builder_usd.recipe_source import BuilderRecipeSource  # noqa: E402

from core.recipe.blobs import MemoryBlobStore  # noqa: E402
from core.recipe.ledger import InMemoryLedger  # noqa: E402
from core.recipe.models import Actor, Recipe as StoreRecipe  # noqa: E402
from core.recipe.store import RecipeStore as TheRecipeStore  # noqa: E402

FIXTURE = Path(__file__).parent / "usd" / "fixtures" / "fjellvik_recipe.json"


def _committed_fixture() -> tuple[TheRecipeStore, str]:
    """The compiler's fixture, committed through the real store.

    ``require_schema=False`` — the engine-side document path: the fixture's
    placement params (vectors, part specs) are not §1.5 word params, so no
    vocabulary schema can describe them; the store still commits, versions
    and hashes it like any other recipe.
    """
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data = raw["recipe"]
    provenance = {path: Provenance.from_dict(record)
                  for path, record in (raw.get("provenance") or {}).items()}
    store = TheRecipeStore(ledger=InMemoryLedger(), blobs=MemoryBlobStore(),
                           require_schema=False)
    store.create_recipe(StoreRecipe.model_validate(data),
                        Actor(kind="owner", id="casey"))
    return store, store.get_branch("br_main").head, provenance


def test_the_compiled_scene_is_the_committed_recipe(tmp_path):
    store, head, provenance = _committed_fixture()

    result = compile_recipe(BuilderRecipeSource(store, head),
                            tmp_path / "stage", provenance=provenance)

    # the manifest speaks the store's own hash for the document it compiled
    assert result.recipe_hash == store.get_version(head).root_hash
    assert result.manifest["recipe"]["hash"] == result.recipe_hash

    # and the same version compiles to the identical manifest (§7.11: the
    # USD is a deterministic function of the recipe, nothing else)
    again = compile_recipe(BuilderRecipeSource(store, head),
                           tmp_path / "stage-again", provenance=provenance)
    assert again.manifest == result.manifest
