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
from core.engine.infinigen1 import Infinigen1xEngine
from core.engine.infinigen2 import Infinigen2Engine
from core.engine.registry import engine_from_env, open_engine
from core.engine.resident import ResidentEngine, ResidentPolicy

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
    "FakeEngine",
    "Infinigen1xEngine",
    "Infinigen2Engine",
    "PreviewRequest",
    "ResidentEngine",
    "ResidentPolicy",
    "PreviewResult",
    "ReexecuteRequest",
    "StageMechanism",
    "StageRequest",
    "StageResult",
    "check_pin",
    "engine_from_env",
    "expected_stage_key",
    "open_engine",
]
