"""The warm scene server — a resident process behind the engine seam.

Plan item 15 (draft 2, week 3): *"the measured numbers say the win is
builder wait and crash recovery, not edit→preview latency — so the server's
job is defined as holding the scene and surviving a kill."*

This package is that job, behind the seam:

* :mod:`core.engine.resident.engine` — :class:`ResidentEngine`, the
  ``Engine`` implementation: it holds a resident process, keeps it healthy,
  restarts it under a budget, checkpoints the recipe on a cadence, guards
  against memory growth, and replays the recipe onto a fresh resident when
  the resident dies;
* :mod:`core.engine.resident.transport` — the subprocess and the RPC that
  reaches it (the channel discipline the spike's findings demand);
* :mod:`core.engine.resident.journal` — the durable recipe: an append-only
  journal, a periodic snapshot and a checkpoint (the write-amplification
  fix, and the replay's source);
* :mod:`core.engine.resident.policy` — the four dials: health checks, the
  restart policy, the checkpoint cadence and the memory-growth guard;
* :mod:`core.engine.resident.protocol` — the wire format, and the mirror of
  the core's op grammar the resident applies (checked against the core by
  digest on every sync);
* :mod:`core.engine.resident.backend` — what a resident process must be
  able to do, and :mod:`core.engine.resident.fake_backend` the
  deterministic scene behind it;
* :mod:`core.engine.resident.worker` — the resident process itself;
* :mod:`core.engine.resident.blender_backend` — the real engine's scene
  (opt-in: it needs ``bpy`` and its own interpreter).

The package README is the handover note: what is measured, what is stubbed,
and how to run the tests and the benchmark.
"""
from __future__ import annotations

from core.engine.resident.backend import SceneBackend
from core.engine.resident.engine import ResidentEngine
from core.engine.resident.journal import SceneJournal
from core.engine.resident.policy import ResidentPolicy
from core.engine.resident.transport import (
    ResidentCrashed,
    ResidentError,
    ResidentProcess,
    ResidentRefused,
    ResidentTimeout,
)

__all__ = [
    "ResidentCrashed",
    "ResidentEngine",
    "ResidentError",
    "ResidentPolicy",
    "ResidentProcess",
    "ResidentRefused",
    "ResidentTimeout",
    "SceneBackend",
    "SceneJournal",
]
