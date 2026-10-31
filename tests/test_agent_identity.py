"""Per-agent tokens: the audit log records *which agent* acted for whom.

§4.1 carried the actor — the token is an identity, an owner token is per
actor (``casey``, ``magnus``). Building world-mcp against these doors found
the gap (thor-world-repo, docs/design.md §8.1): the token says *for whom*
but not *by what*, so the agent's own name rode in tool results instead of
the audit log, and "who did this" needed a second source to answer.

A token entry may now carry an ``agent`` claim: one actor, many agents.
The claim lands on the audit row's actor — ``{kind, id, via, agent}`` —
so every ledger row names both halves. **A1 is permissive: recorded, not
gated** — no door checks the claim, and a token without one behaves
exactly as before.
"""
from __future__ import annotations

import json

from core.auth import principal_for

from tests.conftest import COMPANION, OWNER, PANEL, PROP


def _agent_registry() -> dict:
    """The dev registry plus per-agent tokens: the same classes and actors
    the dev defaults carry, with an ``agent`` claim on two of them."""
    return {"tokens": {
        "dev-token-casey": {"class": "owner", "actor": "casey"},
        "dev-token-magnus": {"class": "owner", "actor": "magnus", "kid": True},
        "dev-token-panel": {"class": "panel", "actor": "panel"},
        "dev-token-propmaker": {"class": "character", "actor": "prop-maker"},
        "dev-token-companion": {"class": "character", "actor": "companion"},
        "dev-token-casey-world-mcp": {"class": "owner", "actor": "casey",
                                      "agent": "world-mcp"},
        "dev-token-props-world-mcp": {"class": "character", "actor": "prop-maker",
                                      "agent": "world-mcp"},
        "dev-token-companion-tile-author": {"class": "character", "actor": "companion",
                                            "agent": "tile-author"},
    }}


CASEY_MCP = {"Authorization": "Bearer dev-token-casey-world-mcp"}
PROPS_MCP = {"Authorization": "Bearer dev-token-props-world-mcp"}


def _install_tokens(settings) -> None:
    settings.tokens_file.write_text(json.dumps(_agent_registry()), encoding="utf-8")


def _rows_with_agent(core):
    return [(e.type, e.actor.model_dump(mode="json"))
            for e in core.store.events_since(0)]


def test_the_agent_claim_resolves_onto_the_principal(settings):
    _install_tokens(settings)
    p = principal_for("dev-token-casey-world-mcp", settings)
    assert (p.token_class, p.actor, p.agent) == ("owner", "casey", "world-mcp")
    plain = principal_for("dev-token-casey", settings)
    assert (plain.actor, plain.agent) == ("casey", None)


def test_an_agent_owner_token_records_which_agent_acted_for_whom(core, client, settings):
    """Every write the agent makes through the owner's doors names both
    halves on the row: the agent that acted, the actor it acted for."""
    _install_tokens(settings)
    r = client.post("/v1/tasks", headers=CASEY_MCP,
                    json={"intention": "more crates on the south span"})
    assert r.status_code == 200
    r = client.post("/v1/call", headers=CASEY_MCP,
                    json={"utterance": "weather the harbour crates"})
    assert r.status_code == 200
    agent_rows = [(t, a) for t, a in _rows_with_agent(core)
                  if a.get("agent") == "world-mcp"]
    assert agent_rows, "no ledger row recorded the agent"
    for t, a in agent_rows:
        assert a["kind"] == "owner" and a["id"] == "casey"


def test_an_agent_character_token_records_the_word_it_came_through(core, client, settings):
    _install_tokens(settings)
    from core.events import core_actor
    from core.svc.vocab import VocabService
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 48},
                             "style": {"type": "string",
                                       "enum": ["plain", "weathered", "stained"]}}}
    VocabService(core).add_word(
        {"word": "props.harbor.crates", "kind": "prop", "owner_character": "",
         "params": schema}, core_actor())
    r = client.post("/v1/vocab/call", headers=PROPS_MCP,
                    json={"word": "props.harbor.crates",
                          "params": {"count": 6, "style": "weathered"}})
    assert r.status_code == 200
    calls = [a for t, a in _rows_with_agent(core) if t == "vocab.call"]
    assert calls and all(
        a["kind"] == "character" and a["id"] == "prop-maker"
        and a.get("via") == "props.harbor.crates" and a.get("agent") == "world-mcp"
        for a in calls)


def test_a_token_without_an_agent_records_no_agent(core, client, settings):
    _install_tokens(settings)
    client.post("/v1/tasks", headers=COMPANION,
                json={"intention": "check the tide gates"})
    rows = [a for t, a in _rows_with_agent(core) if t == "night.task.created"]
    assert rows and all(a.get("agent") is None for a in rows)


def test_recorded_not_gated(core, client, settings):
    """A1 is permissive: an agent token's authority is exactly its class's —
    every door its class may use answers, no door asks for the claim."""
    _install_tokens(settings)
    assert client.get("/v1/vocab", headers=PROPS_MCP).status_code == 200
    assert client.post("/v1/predictions/seal", headers=PROPS_MCP, json={
        "branch_ref": "br_main", "claim": "12 crates, weathered",
        "claim_type": "clutter_density", "confidence": "guess",
        "render_spec": {"rung": 1, "resolution": "512", "seed": 7},
    }).status_code == 200
    # and the class's refusals still refuse: an agent owner token is still
    # not the adult owner's door when the actor is a kid
    kid_mcp = {"Authorization": "Bearer dev-token-magnus-world-mcp"}
    settings.tokens_file.write_text(json.dumps({"tokens": {
        **_agent_registry()["tokens"],
        "dev-token-magnus-world-mcp": {"class": "owner", "actor": "magnus",
                                       "kid": True, "agent": "world-mcp"},
    }}), encoding="utf-8")
    r = client.post("/v1/call", headers=kid_mcp,
                    json={"utterance": "free text", "chips": ["more crates"]})
    assert r.status_code == 422
    assert client.post("/v1/call", headers=kid_mcp,
                       json={"chips": ["more crates"]}).status_code == 200


def test_the_agent_rides_the_task_row_the_slate_serves(core, client, settings):
    """The slate's answer to 'who filed this' is the actor (Task.author);
    the ledger's answer adds the agent. One actor, many agents."""
    _install_tokens(settings)
    r = client.post("/v1/tasks", headers=CASEY_MCP,
                    json={"intention": "retrain on tonight's plays"})
    task = r.json()["task"]
    assert task["author"] == "casey"
    created = [a for t, a in _rows_with_agent(core) if t == "night.task.created"]
    assert created[-1]["agent"] == "world-mcp"
    assert created[-1]["id"] == "casey"


def test_unknown_token_and_missing_claim_still_behave(settings):
    _install_tokens(settings)
    import pytest as _pytest
    from core.errors import AuthError
    with _pytest.raises(AuthError):
        principal_for("dev-token-nobody", settings)
