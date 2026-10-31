"""The recipe read door: ``GET /v1/recipe/{version}`` and the diff between
two versions.

world-mcp's ``world://recipe`` could serve branches, hashes and history,
but not the document itself — a recipe is a content-addressed blob behind
the recipe store, and no door served it (thor-world-repo,
docs/design.md §8.2, its open question 2). An agent that wanted to diff
two versions of the world needed a filesystem on the Thor. This door is
the read that closes that: the document, hash-verified on read (§1.0),
and the canonical op list between two versions — the diff *is* the op
list (§1.1).

Writes stay where they were: the door is read-only, like every recipe
write path that matters (a typed call, a work order).
"""
from __future__ import annotations

import pytest

from core.recipe.errors import NotFound as RecipeNotFound  # noqa: F401 (used via api)
from core.records import Actor, Op
from core.svc.recipes import RecipeStoreSeam

from tests.conftest import PANEL, PROP


def _wire(core, schemas, fjellvik) -> tuple[RecipeStoreSeam, str]:
    seam = RecipeStoreSeam(core, schemas=schemas)
    core.recipes = seam
    root = seam.seed_recipe(fjellvik)
    return seam, root


def _edit(core, seam, base: str, path: str, value) -> str:
    return seam.store.apply_edit(
        base, [Op(op="set", path=path, value=value)],
        author=Actor(kind="owner", id="casey"), message="test edit").id


def test_the_document_door_serves_the_version_its_hash_and_its_document(
        core, client, settings, schemas, fjellvik):
    seam, root = _wire(core, schemas, fjellvik)
    r = client.get(f"/v1/recipe/{root}", headers=PANEL)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == root
    assert body["recipe"] == "rcp_fjellvik"
    assert body["root_hash"].startswith("sha256:")
    assert body["at"] and body["actor"]["id"] == "casey"
    # the document is the version's own blob, hash-verified on read (§1.0)
    assert body["document"] == seam.document(root)
    assert body["document"]["entries"]["harbor.crates"]["params"]["count"] == 12


def test_the_diff_door_answers_the_ops_between_two_versions(
        core, client, settings, schemas, fjellvik):
    seam, root = _wire(core, schemas, fjellvik)
    v2 = _edit(core, seam, root, "harbor.crates.params.count", 18)
    v3 = _edit(core, seam, v2, "structure.south_span.params.planks", 12)

    r = client.get(f"/v1/recipe/{v2}", params={"against": root}, headers=PANEL)
    assert r.status_code == 200
    body = r.json()
    assert body["base"] == root and body["version"] == v2
    assert body["ops"] == [{"op": "set", "path": "harbor.crates.params.count",
                            "value": 18}]

    # three versions, two hops: the diff composes
    r = client.get(f"/v1/recipe/{v3}", params={"against": root}, headers=PANEL)
    assert r.status_code == 200
    ops = r.json()["ops"]
    assert {"op": "set", "path": "harbor.crates.params.count", "value": 18} in ops
    assert {"op": "set", "path": "structure.south_span.params.planks", "value": 12} in ops


def test_the_diff_direction_is_base_to_version(
        core, client, settings, schemas, fjellvik):
    """``?against`` names the base: the ops turn the base into the version,
    not the other way — an agent replaying a night's edits reads forward."""
    seam, root = _wire(core, schemas, fjellvik)
    v2 = _edit(core, seam, root, "harbor.crates.params.count", 18)
    r = client.get(f"/v1/recipe/{root}", params={"against": v2}, headers=PANEL)
    assert r.status_code == 200
    assert r.json()["ops"] == [{"op": "set", "path": "harbor.crates.params.count",
                                "value": 12}]


def test_an_unknown_version_or_base_is_404(core, client, settings, schemas, fjellvik):
    _wire(core, schemas, fjellvik)
    assert client.get("/v1/recipe/ver_9999", headers=PANEL).status_code == 404
    root = seam_root = None
    for row in core.store.scan("branches"):
        if row["id"] == "br_main":
            root = row["payload"]["head"]
    assert client.get(f"/v1/recipe/{root}", params={"against": "ver_9999"},
                      headers=PANEL).status_code == 404


def test_without_the_recipe_half_the_door_answers_501_with_the_seam_named(
        core, client):
    """A fresh core has no recipe store behind the port — the door says so
    rather than faking a document (the /v1/world/scene precedent)."""
    r = client.get("/v1/recipe/ver_0001", headers=PANEL)
    assert r.status_code == 501
    assert "recipe" in r.json()["error"]["message"].lower()


def test_a_tampered_blob_fails_loud(core, client, settings, schemas, fjellvik):
    """§1.0: blobs are verified by hash on read. A document that is not
    the version's own is not a document — the door refuses, it does not
    serve the tampered bytes."""
    from core.recipe.blobs import FileBlobStore

    seam, root = _wire(core, schemas, fjellvik)
    blob = FileBlobStore(core.settings.home).path_for(
        seam.store.get_version(root).root_hash)
    blob.write_bytes(blob.read_bytes().replace(b'"count":12', b'"count":13'))
    r = client.get(f"/v1/recipe/{root}", headers=PANEL)
    assert r.status_code == 500
    assert "hash" in r.json()["error"]["message"].lower()


def test_a_character_token_can_read_the_document_an_agent_diffs_with(
        core, client, settings, schemas, fjellvik):
    """The door exists so agents can diff recipes: a character-class token
    (what an agent holds) reads it — a read-only door, open to the class
    that /v1/branches already serves."""
    _wire(core, schemas, fjellvik)
    for row in core.store.scan("branches"):
        if row["id"] == "br_main":
            root = row["payload"]["head"]
    assert client.get(f"/v1/recipe/{root}", headers=PROP).status_code == 200
    assert client.get(f"/v1/recipe/{root}").status_code == 401
