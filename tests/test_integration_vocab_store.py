"""The merge's own proof: a vocabulary call goes through the real door,
into the real recipe store, and lands in the real ledger.

Before the seats merged, the spine's `RecipeStore` port answered
`UnavailableRecipeStore` and a call stayed an uncommitted proposal; the
recipe store ran on its own ledger; the vocabulary's shipped document and
the store's entry kinds disagreed (the m1 acceptance run's DRIFTS). This
test closes all three: the Fjellvik document loads as a recipe unchanged
(drift 1), the real store commits through `SpineRecipeLedger` so every
recipe event lands in the ONE audit log and folds into the spine's own
projections (drift 2), and the call's edit is validated against the
vocabulary's own schema at the door (§1.1).
"""
from __future__ import annotations

from core.events import core_actor
from core.svc.recipes import RecipeStoreSeam, schemas_from_vocabulary
from core.svc.vocab import VocabService
from core.vocab.seed import RECIPE_DOCUMENT
from core.vocab.words import default_entries

from tests.conftest import seed_nodes


def _wire(core) -> RecipeStoreSeam:
    seam = RecipeStoreSeam(
        core, schemas=schemas_from_vocabulary(default_entries()))
    core.recipes = seam
    seam.seed_recipe(RECIPE_DOCUMENT)  # drift 1: loads as-is, kind prop_set
    return seam


def test_a_vocab_call_commits_through_the_real_store_into_the_one_ledger(core):
    seam = _wire(core)
    words = default_entries()
    crates = next(w for w in words if w.word == "props.harbor.crates")
    VocabService(core).add_word(crates.model_dump(mode="json"), core_actor())

    # the node registry the compiler publishes (§1.4.0) — the call names a node
    seed_nodes(core, "br_main", [
        {"node_id": "crates_01", "entry_path": "harbor.crates", "kind": "prop_set"},
    ])

    result = VocabService(core).call(
        "prop-maker", "props.harbor.crates",
        {"count": 6, "style": "weathered", "from_library": 0, "seed": 771}, node="crates_01")

    assert result["committed"] is True
    ver = result["version"]

    # the params really landed on the document at the committed version
    doc = seam.document(ver)
    assert doc["entries"]["harbor.crates"]["params"]["count"] == 6
    assert doc["entries"]["harbor.crates"]["params"]["style"] == "weathered"

    # and every step of it is in the ONE ledger, in §1.1's order: the call,
    # then the edit it produced, then the version it became
    events = core.store.events_since(0)
    types = [e.type for e in events]
    call_idx = max(i for i, t in enumerate(types) if t == "vocab.call")
    edit_idx = next(i for i in range(call_idx, len(types)) if types[i] == "edit.proposed")
    committed_idx = next(
        i for i, e in enumerate(events)
        if e.type == "version.committed" and e.payload.get("version") == ver)
    assert call_idx < edit_idx < committed_idx
    assert events[committed_idx].payload["root_hash"].startswith("sha256:")

    # the spine's own projection moved with it: the branch head it serves
    branch = core.store.get_row("branches", {"id": "br_main"})
    assert branch["head"] == ver


def test_the_recipe_store_rebuilds_from_the_spines_log_alone(core):
    """§5.2 step 1 on the merged tree: a second store over the same log
    folds to the same world — the projections are rebuildable, not owned."""
    seam = _wire(core)
    words = default_entries()
    crates = next(w for w in words if w.word == "props.harbor.crates")
    VocabService(core).add_word(crates.model_dump(mode="json"), core_actor())
    seed_nodes(core, "br_main", [
        {"node_id": "crates_01", "entry_path": "harbor.crates", "kind": "prop_set"},
    ])
    VocabService(core).call(
        "prop-maker", "props.harbor.crates",
        {"count": 9, "style": "plain", "from_library": 2, "seed": 5}, node="crates_01")
    head = seam.head()

    again = RecipeStoreSeam(
        core, schemas=schemas_from_vocabulary(default_entries()))
    assert again.head() == head
    assert again.document(head) == seam.document(head)
