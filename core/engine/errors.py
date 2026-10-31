"""The engine seam's failures — three honest shapes, no fourth.

An engine that is *not there* (:class:`EngineUnavailable`) names the exact
missing piece (a module, a checkout, a Python version) rather than failing
with an import traceback. An engine that *is there but is the wrong one*
(:class:`EnginePinMismatch`) refuses the recipe instead of silently
reinterpreting it — a recipe pinned to engine A rendered by engine B is the
"reinterpreted" betrayal the corpus forbids (X R9). An engine that *fails*
(:class:`EngineFailed`) carries the engine's own last words.
"""
from __future__ import annotations

from core.errors import CoreError


class EngineUnavailable(CoreError):
    """The engine behind the adapter is not present on this box — the error
    names the exact missing piece (module, checkout, interpreter), never a
    bare ImportError."""

    status = 503
    code = "engine_unavailable"


class EnginePinMismatch(CoreError):
    """The recipe is pinned to an engine this adapter does not implement.
    A swap is an explicit pin edit, never a silent reinterpretation."""

    status = 409
    code = "engine_pin_mismatch"


class EngineFailed(CoreError):
    """The engine ran and failed; the message is its own output (a non-zero
    exit, a raised generator error), verbatim."""

    status = 500
    code = "engine_failed"
