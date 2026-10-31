"""Plan intentions from agents: a ``/v1/tasks`` kind for the night's slate.

world-mcp found that an agent could queue genbatch work (kind ``prop.*``)
but could not propose a *plan*: the slate's tasks were the owner's and the
Companion's alone (thor-world-repo, docs/design.md §8.4, its open question
4). A cloud tile author is exactly the caller who sees tomorrow's slate
from outside — the gaps in the vocabulary, the plays that won — and its
proposals belong on the slate the owner reads before starting the night.

The kind is ``plan.intention``. It is priced by the cost model like
everything else: the ask is the model's (a slate row and the owner's
decision on it — the attention estimate, marked ``[e]``), the rail its
p95, an override recorded as an override. The night work an intention may
seed is priced by its own kind when the night actually runs it — an
intention that is not picked up costs the proposal's footprint and
nothing else. A1 stays permissive: an agent files through its
character-class token, the agent claim rides the ledger row (the
per-agent tokens), nothing is gated.
"""
from __future__ import annotations

import json

from core.night.cost.model import ESTIMATE
from core.night.cost.pricing import known_kinds, price_job

from tests.conftest import COMPANION, OWNER


def _tile_author_headers() -> dict:
    """An agent at the door: a character-class token with an agent claim
    (the per-agent tokens of the world-mcp round)."""
    return {"Authorization": "Bearer dev-token-companion-tile-author"}


def _install_agent_token(settings) -> None:
    settings.tokens_file.write_text(json.dumps({"tokens": {
        "dev-token-casey": {"class": "owner", "actor": "casey"},
        "dev-token-companion": {"class": "character", "actor": "companion"},
        "dev-token-companion-tile-author": {"class": "character",
                                            "actor": "companion",
                                            "agent": "tile-author"},
    }}), encoding="utf-8")


def test_the_kind_is_in_the_cost_model():
    priced = price_job("plan.intention")
    assert priced.kind == "plan.intention"
    assert priced.basis == ESTIMATE  # an estimate stays marked until measured
    assert priced.ask.gpu_minutes == 0.0      # filing runs nothing on the box
    assert priced.ask.hosted_cents == 0
    assert priced.ask.wall_minutes > 0.0      # the owner's decision on it
    assert priced.rail.gpu_minutes == 0.0


def test_an_unknown_kind_still_refuses_and_names_the_known_ones():
    from core.errors import Refused
    from core.svc.tasks import TasksService

    class _Core:
        store = None

    try:
        TasksService(_Core).price("prop.plans")
    except Refused as refused:
        assert "prop.plans" in str(refused)
        assert "plan.intention" in str(refused)
    else:  # pragma: no cover
        raise AssertionError("an unknown kind must be refused")


def test_an_agent_files_an_intention_through_the_door(core, client, settings):
    _install_agent_token(settings)
    r = client.post("/v1/tasks", headers=_tile_author_headers(), json={
        "intention": "author six crate tiles against the vocabulary gap",
        "kind": "plan.intention",
    })
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["kind"] == "plan.intention"
    assert task["state"] == "slated"
    assert task["author"] == "companion"          # for whom
    assert task["ask_source"] == "model"          # priced by the model
    assert task["cost_estimate"]["gpu_minutes"] == 0.0

    # the ledger row answers "which agent acted for whom" by itself
    created = [e for e in core.store.events_since(0)
               if e.type == "night.task.created"]
    assert created[-1].actor.agent == "tile-author"
    assert created[-1].actor.id == "companion"


def test_the_slate_shows_the_intention_with_its_mark(core, client, settings):
    _install_agent_token(settings)
    client.post("/v1/tasks", headers=_tile_author_headers(), json={
        "intention": "author six crate tiles against the vocabulary gap",
        "kind": "plan.intention",
    })
    slate = client.get("/v1/slate", headers=OWNER).json()
    rows = [row for row in slate["rows"] if row["kind"] == "plan.intention"]
    assert len(rows) == 1
    row = rows[0]
    assert row["ask_source"] == "model"
    assert row["marked"] == "[e]"                 # an estimate, marked
    assert row["ask"]["gpu_minutes"] == 0.0
    # and the slate's own ask grew by the intention's, not by a goal's
    assert slate["ask"]["gpu_minutes"] == 0.0


def test_the_night_takes_a_fitting_intention_like_any_task(core, client, settings):
    _install_agent_token(settings)
    client.post("/v1/tasks", headers=_tile_author_headers(), json={
        "intention": "retrain the chooser on today's plays",
        "kind": "plan.intention",
    })
    night = client.post("/v1/night", headers=OWNER, json={})
    assert night.status_code == 200
    # the task left the slate into the night's queue (§3.2: slate → queue)
    tasks = [t for t in core.store.scan("tasks")
             if t["payload"].get("kind") == "plan.intention"]
    assert tasks and tasks[0]["state"] == "queued"


def test_an_override_is_kept_an_override(core, client, settings):
    _install_agent_token(settings)
    r = client.post("/v1/tasks", headers=COMPANION, json={
        "intention": "a hand-priced intention",
        "kind": "plan.intention",
        "cost_estimate": {"gpu_minutes": 5.0, "wall_minutes": 30.0},
    })
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["ask_source"] == "override"
    assert task["cost_estimate"]["gpu_minutes"] == 5.0
    # the owner is held to the number they filed: the rail is never below
    # the ask, and it is at least the model's p95
    assert task["rail"]["gpu_minutes"] >= 5.0
