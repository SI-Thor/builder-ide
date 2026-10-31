"""The HTTP door: §4.2's endpoints, the token classes, and the refusals.

Most of these tests are negative on purpose. The spec's privacy and
authority rules are structural — a kid actor cannot submit free text, a
panel cannot write, a seat has no HTTP door at all — and a rule that is only
ever tested on the happy path is a rule nobody has checked.
"""
from __future__ import annotations

import json

import pytest

from core.svc.vocab import VocabService
from core.svc.work_orders import WorkOrdersService
from core.events import character_actor, core_actor, owner_actor

from tests.conftest import (
    COMPANION,
    IDEM,
    KID,
    OWNER,
    PANEL,
    PROP,
    seed_branch,
    seed_nodes,
)


# ------------------------------------------------------------- the token classes

def test_no_token_is_refused(client):
    r = client.get("/v1/slate")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_an_unknown_token_is_refused(client):
    r = client.get("/v1/slate", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_a_malformed_authorization_header_is_refused(client):
    r = client.get("/v1/slate", headers={"Authorization": "dev-token-casey"})
    assert r.status_code == 401


def test_a_panel_cannot_write(client):
    """panel is read + SSE. It never writes."""
    r = client.post("/v1/night", headers=PANEL, json={})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_a_kid_cannot_confirm_a_work_order(client, core):
    """Magnus proposes; Casey confirms. A kid's confirm is not the door."""
    from tests.conftest import filed_work_order

    wo = filed_work_order(core)
    r = client.post(f"/v1/work-orders/{wo.id}/confirm", headers=KID,
                    json={"answer": "go"})
    assert r.status_code == 403


def test_a_character_cannot_start_a_night(client):
    r = client.post("/v1/night", headers=PROP, json={})
    assert r.status_code == 403


# ------------------------------------------------------------- /v1/call

def test_an_owner_call_returns_a_draft_with_both_price_lines(client):
    r = client.post("/v1/call", headers=OWNER,
                    json={"utterance": "make the crates weathered",
                          "intent": {"title": "weathered crates"}})
    assert r.status_code == 200
    body = r.json()
    assert "draft" in body and "question" not in body
    line = body["draft"]["confirm_line"]
    assert "build/verify:" in line
    assert "generate/test:" in line


def test_two_plausible_referents_return_a_question_not_a_plan(client, core):
    """The spec's two-referent test: ambiguity asks, it never guesses.

    Referents are resolved through the node registry (RV patch 1), so the
    world has to have the nodes first — two entry-path groups means two
    plausible referent sets.
    """
    seed_branch(core, "br_main")
    seed_nodes(core, "br_main", [
        {"node_id": "node_a", "entry_path": "harbor.crates", "kind": "prop"},
        {"node_id": "node_b", "entry_path": "market.stalls", "kind": "prop"},
    ])
    r = client.post("/v1/call", headers=OWNER, json={
        "utterance": "weather these",
        "view": {"branch": "br_main", "selection": ["node_a", "node_b"]}})
    assert r.status_code == 200
    body = r.json()
    assert "question" in body, body
    assert "draft" not in body
    assert len(body["question"]["options"]) == 2


def test_one_referent_group_compiles_a_draft(client, core):
    seed_branch(core, "br_main")
    seed_nodes(core, "br_main", [
        {"node_id": "node_a", "entry_path": "harbor.crates", "kind": "prop"},
        {"node_id": "node_b", "entry_path": "harbor.dock", "kind": "prop"},
    ])
    r = client.post("/v1/call", headers=OWNER, json={
        "utterance": "weather these",
        "view": {"branch": "br_main", "selection": ["node_a", "node_b"]}})
    assert r.status_code == 200
    assert "draft" in r.json()


def test_a_kid_cannot_submit_free_text(client, core):
    """The privacy rule is structure, not policy (§4.1)."""
    r = client.post("/v1/call", headers=KID, json={"utterance": "I want a castle"})
    assert r.status_code == 422
    assert "chips only" in r.json()["error"]["message"]
    # ...and the refusal is audited: the edges are the story
    refused = core.store.events_since(0, types=["call.refused"])
    assert len(refused) == 1
    assert refused[0].refused is True
    assert refused[0].actor.id == "magnus"


def test_a_kid_may_use_chips(client):
    r = client.post("/v1/call", headers=KID, json={"chips": ["more crates"]})
    assert r.status_code == 200
    assert r.json()["chips"][0]["kind"] == "task"


def test_a_kids_utterance_never_reaches_the_log(client, core):
    """Not even in a refused event: there is nothing of his to retain."""
    client.post("/v1/call", headers=KID, json={"utterance": "my secret thought"})
    for ev in core.store.events_since(0):
        assert "my secret thought" not in json.dumps(ev.payload)


def test_an_unknown_field_is_refused(client):
    r = client.post("/v1/call", headers=OWNER,
                    json={"utterance": "hi", "surprise": "boom"})
    assert r.status_code == 422


# ------------------------------------------------------------- work orders

def test_the_board_lists_the_orders_with_their_price_lines(client, core):
    from tests.conftest import filed_work_order

    wo = filed_work_order(core)
    r = client.get("/v1/work-orders", headers=PANEL)
    assert r.status_code == 200
    rows = r.json()["work_orders"]
    assert len(rows) == 1
    assert rows[0]["id"] == wo.id
    assert rows[0]["state"] == "draft"
    assert "build/verify:" in rows[0]["confirm_line"]
    assert rows[0]["estimate"] is not None


def test_confirm_go_over_http(client, core):
    from tests.conftest import filed_work_order

    wo = filed_work_order(core)
    r = client.post(f"/v1/work-orders/{wo.id}/confirm", headers=OWNER,
                    json={"answer": "go"})
    assert r.status_code == 200
    assert r.json()["state"] == "queued"


def test_an_idempotent_replay_returns_the_original_result(client, core):
    """A doubled "Go" cannot start two attempts (§5.3)."""
    from tests.conftest import filed_work_order

    wo = filed_work_order(core)
    headers = {**OWNER, **IDEM}
    first = client.post(f"/v1/work-orders/{wo.id}/confirm", headers=headers,
                        json={"answer": "go"})
    second = client.post(f"/v1/work-orders/{wo.id}/confirm", headers=headers,
                         json={"answer": "go"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    confirmed = core.store.events_for("work_order", wo.id, ["wo.confirmed"])
    assert len(confirmed) == 1


def test_confirming_a_compiling_order_is_refused(client, core):
    from core.models import Origin
    from core.events import owner_actor

    wo = WorkOrdersService(core).file(
        owner_actor("casey"), Origin(channel="text", packet="pk"), "t", goal="g")
    r = client.post(f"/v1/work-orders/{wo.id}/confirm", headers=OWNER,
                    json={"answer": "go"})
    assert r.status_code == 422


def test_keep_over_http(client, core):
    from core.events import owner_actor

    from tests.conftest import filed_work_order

    wo = filed_work_order(core)
    svc = WorkOrdersService(core)
    svc.confirm(wo.id, owner_actor("casey"), "go")
    svc.start_attempt(wo.id, "aider-local")
    svc.deliver(wo.id, {
        "attempt": "seat-1", "commit": {"sha": "a"}, "code_diff": {"sha": "b"},
        "evidence": [{"kind": "test_run", "ref": "pytest", "sha256": "sha256:x",
                      "summary": "12 passed"}]})
    preview = core.store.artifacts.put(b"png", "preview.png")
    svc.land(wo.id, preview, [])
    r = client.post(f"/v1/work-orders/{wo.id}/keep", headers=OWNER, json={})
    assert r.status_code == 200
    assert r.json()["work_order"]["state"] == "kept"


# ------------------------------------------------------------- questions

def test_a_character_parks_a_question_and_the_owner_answers_it(client, core):
    r = client.post("/v1/questions", headers=PROP, json={
        "name": "which rope?", "options": ["the tarred one", "the new one"]})
    assert r.status_code == 200
    qid = r.json()["question"]["id"]
    r = client.post(f"/v1/questions/{qid}/answer", headers=OWNER,
                    json={"answer": "the tarred one"})
    assert r.status_code == 200
    assert r.json()["question"]["answer"] == "the tarred one"


def test_answering_an_unknown_question_is_a_404(client):
    r = client.post("/v1/questions/q_nope/answer", headers=OWNER, json={"answer": "x"})
    assert r.status_code == 404


# ------------------------------------------------------------- the slate & the night

def test_the_slate_shows_the_work_order_line(client, core):
    from tests.conftest import filed_work_order

    filed_work_order(core)
    r = client.get("/v1/slate", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert "work_order_line" in body
    assert "capability_rows" in body


def test_starting_a_night_returns_the_preflight_line(client):
    r = client.post("/v1/night", headers=OWNER, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["preflight_line"].startswith("PREFLIGHT:")
    assert body["night"]["state"] == "running"


def test_two_nights_at_once_are_refused(client):
    client.post("/v1/night", headers=OWNER, json={})
    r = client.post("/v1/night", headers=OWNER, json={})
    assert r.status_code == 422


def test_stopping_a_night_and_reading_the_report(client):
    started = client.post("/v1/night", headers=OWNER, json={}).json()
    nid = started["night"]["id"]
    r = client.post(f"/v1/night/{nid}/stop", headers=OWNER, json={"reason": "done"})
    assert r.status_code == 200
    assert r.json()["night"]["state"] == "stopped"

    as_json = client.get(f"/v1/nights/{nid}/report?mode=json", headers=PANEL)
    assert as_json.status_code == 200
    assert as_json.json()["report"]["night"]["id"] == nid

    as_text = client.get(f"/v1/nights/{nid}/report?mode=text", headers=PANEL)
    assert as_text.status_code == 200
    assert as_text.headers["content-type"].startswith("text/plain")

    as_html = client.get(f"/v1/nights/{nid}/report?mode=html", headers=PANEL)
    assert as_html.status_code == 200
    assert "<html" in as_html.text.lower()


def test_the_report_of_an_unknown_night_is_a_404(client):
    r = client.get("/v1/nights/night_nope/report", headers=PANEL)
    assert r.status_code == 404


def test_a_companion_files_a_task(client):
    r = client.post("/v1/tasks", headers=COMPANION,
                    json={"intention": "check the tide line"})
    assert r.status_code == 200
    assert r.json()["task"]["state"] == "slated"


def test_a_filed_task_is_priced_from_the_cost_model(client):
    """The client files an intention; the model says what it costs."""
    from core.night.cost import get_model

    r = client.post("/v1/tasks", headers=COMPANION,
                    json={"intention": "weather the harbour crates"})
    assert r.status_code == 200
    task = r.json()["task"]
    band = get_model().band("prop.goal")
    assert task["kind"] == "prop.goal"
    assert task["ask_source"] == "model"
    assert task["cost_estimate"]["gpu_minutes"] == pytest.approx(band.p50.gpu_minutes)
    assert task["rail"]["gpu_minutes"] == pytest.approx(band.p95.gpu_minutes)


def test_a_client_ask_is_an_override_and_the_api_says_so(client):
    r = client.post("/v1/tasks", headers=COMPANION,
                    json={"intention": "one very large render",
                          "cost_estimate": {"gpu_minutes": 300.0, "wall_minutes": 45.0}})
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["ask_source"] == "override"
    assert task["ask_basis"] == "estimate"
    assert task["cost_estimate"]["gpu_minutes"] == pytest.approx(300.0)


def test_a_task_can_name_its_job_kind(client):
    r = client.post("/v1/tasks", headers=COMPANION,
                    json={"intention": "a picture of a crate", "kind": "prop.image"})
    assert r.status_code == 200
    assert r.json()["task"]["kind"] == "prop.image"


def test_a_job_kind_the_model_does_not_know_is_refused(client):
    r = client.post("/v1/tasks", headers=COMPANION,
                    json={"intention": "a very large prop", "kind": "prop.gigantic"})
    assert r.status_code == 422
    assert "prop.gigantic" in r.json()["error"]["message"]


# ------------------------------------------------------------- budget

def test_the_budget_endpoint_reports_the_rails(client):
    r = client.get("/v1/budget", headers=OWNER)
    assert r.status_code == 200
    assert "rails" in r.json()


# ------------------------------------------------------------- vocabulary

def test_the_vocabulary_lists_words_and_the_capability_view(client, core):
    VocabService(core).add_word({
        "word": "bridge.rope", "kind": "prop", "status": "coming-soon",
        "owner_character": "prop-maker",
        "params": {"type": "object", "additionalProperties": False, "properties": {
            "material": {"type": "string", "enum": ["tarred"]},
            "diameter_m": {"type": "number", "minimum": 0.1, "maximum": 0.4}}},
    }, core_actor())
    r = client.get("/v1/vocab", headers=PROP)
    assert r.status_code == 200
    body = r.json()
    assert [w["word"] for w in body["words"]] == ["bridge.rope"]
    assert body["words"][0]["status"] == "coming-soon"
    assert "capability_rows" in body


def test_an_unknown_word_is_refused_and_audited(client, core):
    r = client.post("/v1/vocab/call", headers=PROP,
                    json={"word": "nope.nothing", "params": {}})
    assert r.status_code == 404
    refused = core.store.events_since(0, types=["vocab.call"])
    assert len(refused) == 1 and refused[0].refused is True


def test_a_word_outside_its_schema_is_refused_and_audited(client, core):
    VocabService(core).add_word({
        "word": "bridge.rope", "kind": "prop", "status": "active",
        "owner_character": "prop-maker",
        "params": {"type": "object", "additionalProperties": False, "properties": {
            "material": {"type": "string", "enum": ["tarred", "new"]}}},
    }, core_actor())
    r = client.post("/v1/vocab/call", headers=PROP,
                    json={"word": "bridge.rope", "params": {"material": "purple"}})
    assert r.status_code == 422
    refused = core.store.events_since(0, types=["vocab.call"])
    assert len(refused) == 1 and refused[0].refused is True


# ------------------------------------------------------------- predictions

def test_sealing_a_prediction_and_tallying_it(client, core):
    r = client.post("/v1/predictions/seal", headers=PROP, json={
        "branch_ref": "br_main", "claim": "the rope reads as wet",
        "claim_type": "taste_keep", "confidence": "medium",
        "basis": "1 observation",
        "render_spec": {"rung": 2, "resolution": "1024", "seed": 7}})
    assert r.status_code == 200
    pid = r.json()["prediction"]["id"]
    assert r.json()["prediction"]["verdict"] is None

    tally = client.get("/v1/predictions/tally", headers=PANEL)
    assert tally.status_code == 200
    assert tally.json()["tally"][0]["claim_type"] == "taste_keep"
    assert tally.json()["tally"][0]["denominator"] >= 1


def test_a_prediction_without_a_render_spec_is_refused(client):
    r = client.post("/v1/predictions/seal", headers=PROP, json={
        "branch_ref": "br_main", "claim": "the rope reads as wet",
        "claim_type": "taste_keep", "confidence": "medium"})
    assert r.status_code == 422


# ------------------------------------------------------------- taste

def test_the_taste_ledger_exports_erases_and_ratifies(client, core):
    from core.svc.taste import TasteService

    TasteService(core).append_note(
        owner_actor("casey"), author="casey", subject={"kind": "node", "id": "span_south"},
        artifact_ref="sha256:x", verdict="keep", reason_code="too_busy")
    r = client.get("/v1/ledger/taste/export?author=casey", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["rows"]

    r = client.post("/v1/ledger/taste/erase", headers=OWNER, json={"author": "casey"})
    assert r.status_code == 200
    assert client.get("/v1/ledger/taste/export?author=casey", headers=OWNER).json()["rows"] == []


def test_a_kid_cannot_erase_taste(client):
    r = client.post("/v1/ledger/taste/erase", headers=KID, json={"author": "magnus"})
    assert r.status_code == 403


# ------------------------------------------------------------- assets

def test_an_asset_is_registered_with_its_licence(client):
    r = client.post("/v1/assets", headers=PANEL, json={
        "kind": "mesh",
        "files": [{"role": "mesh", "path": "a.glb", "sha256": "sha256:abc", "bytes": 10}],
        "provenance": {"source": "generated"},
        "licence": {"spdx": "CC0-1.0", "dependency_terms": [], "commercial_ok": True}})
    assert r.status_code == 200
    listed = client.get("/v1/assets", headers=PANEL).json()
    assert listed["assets"][0]["licence"]["spdx"] == "CC0-1.0"


def test_an_asset_without_a_licence_is_refused(client):
    r = client.post("/v1/assets", headers=PANEL, json={
        "kind": "mesh", "files": [],
        "provenance": {"source": "generated"},
        "licence": {"spdx": "CC0-1.0"}})
    assert r.status_code == 422


# ------------------------------------------------------------- branches

def test_the_owner_applies_a_branch(client, core):
    from tests.conftest import seed_branch

    seed_branch(core, "br_main")
    r = client.post("/v1/branches/br_main/apply", headers=OWNER,
                    json={"to_version": "ver_2"})
    assert r.status_code == 200
    assert r.json()["head"] == "ver_2"


def test_a_kids_apply_is_a_proposal_pending_the_owner(client, core):
    """X C8/D4: a branch apply is a real edit, so his apply is a proposal."""
    from tests.conftest import seed_branch

    seed_branch(core, "br_main")
    r = client.post("/v1/branches/br_main/apply", headers=KID,
                    json={"to_version": "ver_2"})
    assert r.status_code == 200
    assert r.json()["proposed"] is True
    assert r.json()["pending_owner"] is True
    proposed = core.store.events_since(0, types=["branch.proposed"])
    assert len(proposed) == 1
    assert proposed[0].actor.id == "magnus"


def test_applying_an_unknown_branch_is_a_404(client):
    r = client.post("/v1/branches/br_nope/apply", headers=OWNER, json={})
    assert r.status_code == 404


# ------------------------------------------------------------- the other half

def test_the_scene_manifest_is_the_other_halfs_door(client):
    """Answered 501 with the seam named, not faked."""
    r = client.get("/v1/world/scene?branch=br_main", headers=PANEL)
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "other_half_unavailable"


def test_a_branch_can_be_opened(client, core):
    """POST /v1/branches is in §4.2's table too."""
    r = client.post("/v1/branches", headers=OWNER,
                    json={"name": "morning A", "base": "ver_1",
                          "purpose": "morning-option"})
    assert r.status_code == 200
    br = r.json()["branch"]
    assert br["id"].startswith("br_")
    assert br["purpose"] == "morning-option"
    assert br["created_by"]["id"] == "casey"
    listed = client.get("/v1/branches", headers=PANEL).json()["branches"]
    assert any(b["id"] == br["id"] for b in listed)


def test_a_kid_may_not_open_a_branch(client):
    """A kid's branch is a proposal; opening one is the owner's act."""
    r = client.post("/v1/branches", headers=KID, json={"name": "morning A"})
    assert r.status_code == 403


def test_the_acp_proxy_is_the_other_halfs_door(client):
    r = client.get("/acp/proxy/att_1", headers=PANEL)
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "other_half_unavailable"
