"""Pointing the core at an engine is configuration, not code.

`open_engine(spec)` turns a plain mapping into a constructed `Engine` — the
one line the acceptance suites hold, and the one line a real engine changes:

    {"flavour": "fake", "pin": {...}}                              # tests
    {"flavour": "infinigen-1x", "pin": {...}, "repo": "...",       # the spike
     "python": ".../.venv/bin/python", "config_files": [...],
     "output_dir": "$BUILDER_HOME/stages"}
    {"flavour": "infinigen-2-procfunc", "runtime": "venv",         # the v2
     "python": "~/lm-wt/v2-thor/.venv/bin/python",                 # venv, today
     "repo": "~/lm-wt/v2-thor/src/infinigen-upstream",
     "generators": {"crates": "storage_cell_shelf_rand", ...},
     "output_dir": "$BUILDER_HOME/engine"}
    {"flavour": "infinigen-2-procfunc", "pin": {...}}              # in-process,
                                                                   # when the v2
                                                                   # gate lands
    {"flavour": "resident", "pin": {...}, "root": "$BUILDER_HOME/resident",
     "backend": "fake" | "blender", "python": ".../.venv/bin/python",
     "policy": {"max_restarts": 3, ...}}                           # the warm scene

`engine_from_env()` reads the same shape from ``BUILDER_ENGINE`` (JSON), so
deploying a real engine to the Thor is one environment variable on the
service — no code change, no recipe change (plan §3 week-1 item 3's
pass/fail). The venv flavour's pin is *interrogated* from the venv itself
(the resolved packages are the config), so its SPEC carries no pin — one may
be given, and drift is refused. The ``runner`` key (any flavour) and a
non-``"venv"`` ``runtime`` value accept the injected doubles and never
appear in real configuration.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

from core.engine.contract import Engine
from core.engine.fake import FakeEngine
from core.engine.infinigen1 import Infinigen1xEngine
from core.engine.infinigen2 import Infinigen2Engine
from core.engine.resident import ResidentEngine, ResidentPolicy
from core.records import EnginePin

__all__ = ["open_engine", "engine_from_env"]


def open_engine(spec: Mapping[str, Any]) -> Engine:
    """One configuration mapping → one engine behind the seam."""
    spec = dict(spec)
    flavour = spec.pop("flavour", None)
    if flavour == "fake":
        pin = spec.pop("pin", None)
        return FakeEngine(EnginePin.model_validate(pin) if pin else None)
    if flavour == "infinigen-1x":
        pin = EnginePin.model_validate(spec.pop("pin"))
        return Infinigen1xEngine(pin=pin, **spec)
    if flavour == "infinigen-2-procfunc":
        runtime = spec.pop("runtime", None)
        if runtime == "venv":
            from core.engine.venv2 import Venv2Runtime

            pinned = spec.pop("pin", None)
            venv = Venv2Runtime(**spec)
            pin = venv.engine_pin(
                EnginePin.model_validate(pinned) if pinned else None)
            return Infinigen2Engine(pin=pin, runtime=venv)
        pin = EnginePin.model_validate(spec.pop("pin"))
        if runtime is not None and not callable(getattr(runtime, "trace", None)):
            raise ValueError(
                f"unknown runtime {runtime!r}; it is 'venv' (the subprocess "
                "flavour) or an injected ProcfuncRuntime double"
            )
        return Infinigen2Engine(pin=pin, runtime=runtime)
    if flavour == "resident":
        pin = EnginePin.model_validate(spec.pop("pin"))
        policy = spec.pop("policy", None)
        if isinstance(policy, Mapping):
            policy = ResidentPolicy(**dict(policy))
        return ResidentEngine(
            pin=pin, root=spec.pop("root"), policy=policy, **spec
        )
    raise ValueError(
        f"unknown engine flavour {flavour!r}; the flavours are 'fake', "
        "'infinigen-1x', 'infinigen-2-procfunc' and 'resident'"
    )


def engine_from_env(environ: Mapping[str, str] | None = None) -> Engine | None:
    """The engine configuration from the environment, or ``None`` when the
    box has not been pointed at one (the caller decides what that means —
    honestly, never by inventing an engine)."""
    env = os.environ if environ is None else environ
    raw = env.get("BUILDER_ENGINE", "").strip()
    if not raw:
        return None
    return open_engine(json.loads(raw))
