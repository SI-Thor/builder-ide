"""The engine adapter — one seam, so a v1 → v2 change is one adapter.

The recipe is the source of truth and it is **ours**; the engine that
compiles and renders it is pinned per project and **swappable**. This
package is the thin seam between them (core-spec §1.1/§1.9; the engine
decision E, whose first falsifier — alpha churn — is mitigated exactly by
putting our schema above the engine):

* :mod:`core.engine.contract` — the `Engine` protocol and its five rules
  (the recipe is ours; the pin is checked; same request, same bytes; stage
  keys are canonical; the lower layer belongs to the engine);
* :mod:`core.engine.fake` — the deterministic fake the tests and the
  acceptance suites run on;
* :mod:`core.engine.infinigen1` — v1 as the spike runs it: one pinned
  subprocess per stage, config bundle verified against the pin;
* :mod:`core.engine.infinigen2` — 2.0 + procfunc in-process: the traced
  instance graph out, a recipe diff re-executed in;
* :mod:`core.engine.venv2` — 2.0 through its own venv's CLI (the
  subprocess boundary that renders on the Thor today): trace + render real,
  the pin interrogated from the venv, re-execution and export refused with
  their missing pieces named;
* :mod:`core.engine.graph` — the procfunc graph, the recipe's lower
  layer: stored by hash, diffed by node, closed over consumers (the
  dirty-subtree term of the contract, ``core/engine/DIRTY.md`` §3);
* :mod:`core.engine.stagecache` — the stage cache on disk: a hit skips
  the stage, eviction is by size (LRU), every read is hash-verified;
* :mod:`core.engine.regen` — :class:`Regenerator`, the contract's driver:
  dirty set in, per-entry hit/miss/partial through this seam, graphs and
  their diffs reported (``DIRTY.md`` is the contract itself);
* :mod:`core.engine.gate` — the merge gate's engine rungs over any engine;
* :mod:`core.engine.resident` — the warm scene server: a resident process
  holding the scene while builders work (plan item 15 — the win is builder
  wait and crash recovery, not edit→preview latency);
* :mod:`core.engine.registry` — :func:`open_engine` / :func:`engine_from_env`:
  pointing the core at a real engine is configuration.

The package README (`core/engine/README.md`) is the handover note: what is
real, what is skeleton, and the named missing piece for each flavour.
"""
from __future__ import annotations

from core.engine.contract import (
    Engine,
    EngineCapabilities,
    EngineDescriptor,
    ExportRequest,
    ExportResult,
    PreviewRequest,
    PreviewResult,
    ReexecuteRequest,
    StageMechanism,
    StageRequest,
    StageResult,
    check_pin,
    expected_stage_key,
)
from core.engine.errors import EngineFailed, EnginePinMismatch, EngineUnavailable
from core.engine.fake import FAKE_PIN, FakeEngine
from core.engine.gate import EngineGateEngine
from core.engine.graph import (
    GraphDiff,
    GraphRef,
    GraphStore,
    StageGraphs,
    diff_graphs,
    graph_hash,
    graphs_of_stage,
)
from core.engine.infinigen1 import Infinigen1xEngine
from core.engine.infinigen2 import Infinigen2Engine
from core.engine.regen import EntryOutcome, RegenerationReport, Regenerator
from core.engine.registry import engine_from_env, open_engine
from core.engine.resident import ResidentEngine, ResidentPolicy
from core.engine.stagecache import CachedStage, StageCache

__all__ = [
    "Engine",
    "EngineCapabilities",
    "EngineDescriptor",
    "EngineFailed",
    "EngineGateEngine",
    "EnginePinMismatch",
    "EngineUnavailable",
    "ExportRequest",
    "ExportResult",
    "FAKE_PIN",
    "CachedStage",
    "FakeEngine",
    "GraphDiff",
    "GraphRef",
    "GraphStore",
    "StageGraphs",
    "Infinigen1xEngine",
    "Infinigen2Engine",
    "PreviewRequest",
    "ResidentEngine",
    "ResidentPolicy",
    "PreviewResult",
    "RegenerationReport",
    "Regenerator",
    "EntryOutcome",
    "ReexecuteRequest",
    "StageGraphs",
    "StageCache",
    "StageMechanism",
    "StageRequest",
    "StageResult",
    "check_pin",
    "diff_graphs",
    "engine_from_env",
    "expected_stage_key",
    "graph_hash",
    "graphs_of_stage",
    "open_engine",
]
