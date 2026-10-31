"""Shared test fixtures for the whole merged core.

Two families live here and they do not collide:

* the **API half's** fixtures (`home`, `settings`, `core`, `app`, `client`,
  `live_server`) — every test gets its own ``$BUILDER_HOME``, a temp directory
  with a real SQLite ledger in it. No test touches the developer's own home,
  and no test shares a ledger with another.
* the **recipe store's** fixtures (`clock`, `actor`, `pin`, `fjellvik`,
  `schemas`, `blobs`, `ledger`, `store`, `root_version`, `questions`) — the
  Fjellvik example of §1.1 and the three words of the slice.

The recipe store's fixture module also supplied the imports its own
fixtures need; those are kept here so one conftest serves both halves.
"""
from __future__ import annotations

import itertools
import json
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from core.recipe.models import (
    Actor,
    Constraint,
    EnginePin,
    GeneratorRef,
    Recipe,
    RecipeEntry,
)
from core.recipe.schema import StaticSchemaRegistry
from core.api import create_app
from core.config import Settings
from core.events import core_actor
from core.svc import Core


# --- the vendored WHY kernel's corpus test -------------------------------
#
# tests/test_why_corpus.py is copied byte-identical from cognitive-ecology,
# where the kernel lives at ``ecology.why``. Here it is vendored at
# ``core.why`` (core/why/VENDORED.md). Rather than editing the test — which
# would break the "unchanged" property that pins us to upstream semantics —
# this binds ``ecology.why`` to the vendored package before the test module
# imports it.
import sys as _sys
import types as _types

from core import why as _vendored_why

_ecology = _sys.modules.get("ecology")
if _ecology is None:
    _ecology = _types.ModuleType("ecology")
    _ecology.__path__ = []  # mark as package so submodule imports resolve
    _sys.modules["ecology"] = _ecology
_ecology.why = _vendored_why
_sys.modules.setdefault("ecology.why", _vendored_why)


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


@pytest.fixture
def live_server(settings, core):
    """A real uvicorn server on an ephemeral port.

    Some things — a client that walks away mid-stream, the exact headers an
    EventSource sees — are facts about sockets, and the test transport does
    not reproduce them.
    """
    import socket
    import threading
    import time

    import uvicorn

    from core.api import create_app

    app = create_app(settings, core=core, run_boot=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - a broken environment
        raise RuntimeError("uvicorn did not start")
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(timeout=10)


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


# ------------------------------------------------------------------
# the recipe store's fixtures
# ------------------------------------------------------------------


@pytest.fixture
def clock() -> Callable[[], str]:
    """A deterministic counter clock so timestamps are stable in tests."""
    counter = itertools.count()

    def _now() -> str:
        return f"2026-10-30T20:00:{next(counter):02d}Z"

    return _now


@pytest.fixture
def actor() -> Actor:
    return Actor(kind="owner", id="casey")


@pytest.fixture
def magnus() -> Actor:
    return Actor(kind="owner", id="magnus")


@pytest.fixture
def architect() -> Actor:
    return Actor(kind="character", id="architect", via="word")


@pytest.fixture
def pin() -> EnginePin:
    return EnginePin(
        repo="SI-Thor/infinigen-thor",
        commit="9f31c0e",
        config="sha256:cf90cafe",
        blender="4.2",
        python="3.12",
    )


@pytest.fixture
def fjellvik(pin: EnginePin) -> Recipe:
    """The Fjellvik example of core-spec v2 §1.1."""
    return Recipe(
        id="rcp_fjellvik",
        name="Fjellvik",
        engine_pin=pin,
        seeds={"terrain": 4471, "props": 4472, "weather": 4473},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates",
                kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.props",
                    func="crates",
                    variant="harbor",
                    rev="9f31c0e",
                ),
                params={"count": 12, "style": "weathered"},
                seed=4472,
                origin="builtin",
            ),
            "structure.south_span": RecipeEntry(
                path="structure.south_span",
                kind="structure",
                generator=GeneratorRef(
                    module="infinigen_thor.structures",
                    func="bridge",
                    variant="rope",
                    rev="9f31c0e",
                ),
                params={"length_m": 14.0, "planks": 8, "sway": 0.22, "load_factor": 1.1},
                seed=99,
                origin="builtin",
            ),
            "terrain.harbor": RecipeEntry(
                path="terrain.harbor",
                kind="terrain",
                # clearance_m is what the project-level drip-line constraint
                # measures, so the recipe carries it (the constraint rests on it)
                params={"slope": 0.08, "clearance_m": 0.4},
                seed=4471,
                origin="builtin",
            ),
        },
        constraints=[
            Constraint(name="oak_dripline", kind="keep_clear", ref="oak_0117", value=0.35)
        ],
    )


@pytest.fixture
def schemas() -> StaticSchemaRegistry:
    """The three words of the slice (§6.1) plus the Fjellvik entries."""
    return StaticSchemaRegistry(
        {
            "harbor.crates": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 48},
                    "style": {"type": "string", "enum": ["plain", "weathered", "stained"]},
                    "from_library": {"type": "integer", "minimum": 0, "maximum": 48},
                    "seed": {"type": "integer", "minimum": 0, "maximum": 2**31},
                },
            },
            "structure.south_span": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "length_m": {"type": "number", "minimum": 0.5, "maximum": 60.0},
                    "planks": {"type": "integer", "minimum": 1, "maximum": 64},
                    "sway": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "load_factor": {"type": "number", "minimum": 0.0, "maximum": 10.0},
                },
            },
            "terrain.harbor": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "slope": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "clearance_m": {"type": "number", "minimum": 0.0, "maximum": 10.0},
                },
            },
            "props.harbor.crates": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "count": {"type": "integer", "minimum": 1, "maximum": 48},
                    "style": {"type": "string", "enum": ["plain", "weathered", "stained"]},
                },
            },
        }
    )


@pytest.fixture
def blobs(tmp_path):
    from core.recipe.blobs import FileBlobStore

    return FileBlobStore(tmp_path / "builder-home")


@pytest.fixture
def ledger():
    from core.recipe.ledger import InMemoryLedger

    return InMemoryLedger()


@pytest.fixture
def store(ledger, blobs, schemas: StaticSchemaRegistry, clock):
    from core.recipe.store import RecipeStore

    return RecipeStore(ledger=ledger, blobs=blobs, schemas=schemas, clock=clock)


@pytest.fixture
def root_version(store: RecipeStore, fjellvik: Recipe, actor: Actor) -> str:
    store.create_recipe(fjellvik, actor)
    return "ver_0001"


class RecordingQuestions:
    """A stand-in for the API half's question store (test-only)."""

    def __init__(self) -> None:
        self.parked: list[dict] = []

    def park(self, *, name: str, branch: str, options: list[str], detail: str) -> str:
        self.parked.append(
            {"name": name, "branch": branch, "options": options, "detail": detail}
        )
        return f"q_{len(self.parked):04d}"


@pytest.fixture
def questions() -> RecordingQuestions:
    return RecordingQuestions()
