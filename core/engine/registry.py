"""Pointing the core at an engine is configuration, not code.

`open_engine(spec)` turns a plain mapping into a constructed `Engine` — the
one line the acceptance suites hold, and the one line a real engine changes:

    {"flavour": "fake", "pin": {...}}                              # tests
    {"flavour": "infinigen-1x", "pin": {...}, "repo": "...",       # the spike
     "python": ".../.venv/bin/python", "config_files": [...],
     "output_dir": "$BUILDER_HOME/stages"}
    {"flavour": "infinigen-2-procfunc", "pin": {...}}              # the decision

`engine_from_env()` reads the same shape from ``BUILDER_ENGINE`` (JSON), so
deploying the real engine to the Thor is one environment variable on the
service — no code change, no recipe change (plan §3 week-1 item 3's
pass/fail). The ``runner``/``runtime`` keys accept the injected doubles and
never appear in real configuration.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

from core.engine.contract import Engine
from core.engine.fake import FakeEngine
from core.engine.infinigen1 import Infinigen1xEngine
from core.engine.infinigen2 import Infinigen2Engine
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
        pin = EnginePin.model_validate(spec.pop("pin"))
        return Infinigen2Engine(pin=pin, **spec)
    raise ValueError(
        f"unknown engine flavour {flavour!r}; the flavours are 'fake', "
        "'infinigen-1x' and 'infinigen-2-procfunc'"
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
