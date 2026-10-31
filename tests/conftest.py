"""Shared fixtures.

Every test gets its own ``$BUILDER_HOME`` — a temp directory with a real
SQLite ledger in it. No test touches the developer's own home, and no test
shares a ledger with another.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.config import Settings
from core.events import core_actor
from core.svc import Core

# The dev token registry (config.Settings.default_tokens). Owner tokens are
# per actor: casey is the adult, magnus is the kid.
OWNER = {"Authorization": "Bearer dev-token-casey"}
KID = {"Authorization": "Bearer dev-token-magnus"}
PANEL = {"Authorization": "Bearer dev-token-panel"}
PROP = {"Authorization": "Bearer dev-token-propmaker"}
COMPANION = {"Authorization": "Bearer dev-token-companion"}

IDEM = {"Idempotency-Key": "k-1"}


@pytest.fixture
def home(tmp_path):
    return tmp_path / "builder-ide"


@pytest.fixture
def settings(home):
    return Settings.for_home(home)


@pytest.fixture
def core(settings):
    c = Core.open(settings)
    yield c
    c.store.close()


@pytest.fixture
def app(settings, core):
    return create_app(settings, core=core)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ helpers


@pytest.fixture
def make_client(settings):
    """Build a client over a given settings dir (for restart tests)."""
    def _make(s: Settings) -> TestClient:
        c = Core.open(s)
        return TestClient(create_app(s, core=c))
    return _make


def seed_nodes(core, branch: str, nodes: list[dict]) -> None:
    """Publish a nodes.json artifact the way the recipe half's compiler does,
    so the node registry projection has something to resolve."""
    payload = {"nodes": nodes}
    desc = core.store.artifacts.put(json.dumps(payload).encode("utf-8"), "nodes.json")
    core.store.append(core.store.new_event(
        "version.committed", core_actor(),
        {"entity_kind": "branch", "entity_id": branch},
        {"branch": branch, "head": "ver_1"},
        artifact=desc,
    ))


def seed_branch(core, branch_id: str = "br_main", purpose: str = "main",
                head: str = "ver_1") -> None:
    core.store.append(core.store.new_event(
        "branch.created", core_actor(),
        {"entity_kind": "branch", "entity_id": branch_id},
        {"id": branch_id, "name": "main" if purpose == "main" else branch_id,
         "head": head, "purpose": purpose, "protected": purpose == "main"},
    ))


def filed_work_order(core, *, title: str = "weathered crates", goal: str = "weather them",
                     owner: str = "casey", estimate=None, confirm_line: str | None = None,
                     acceptance=None):
    """File a work order and compile it to a draft, through the service."""
    from core.events import owner_actor
    from core.models import Budget, Estimate, Origin, Rail
    from core.svc.work_orders import WorkOrdersService

    svc = WorkOrdersService(core)
    wo = svc.file(
        owner_actor(owner),
        Origin(channel="text", packet="pk_1"),
        title, goal=goal,
    )
    est = estimate or Estimate(
        build_verify=Rail(gpu_minutes=20, wall_minutes=40),
        generate_test=Rail(gpu_minutes=10, wall_minutes=20),
    )
    line = confirm_line or (
        "weather the crates to a weathered tone · "
        "build/verify: ~0.3 GPU-h · generate/test: ~0.2 GPU-h")
    return svc.compile_draft(
        wo.id, title=title, goal=goal, targets=["props.harbor.crates"],
        acceptance=acceptance or [{"kind": "test_suite", "spec": {"suite": "default"}}],
        budget=Budget(), estimate=est, confirm_line=line,
    )
