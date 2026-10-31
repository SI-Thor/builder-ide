"""The Infinigen 2.0 + procfunc adapter — in-process, graph in, diff out.

This is the engine the decision landed on (E §3, option C): v2's
single-process, in-memory generation is the warm-scene shape, and
procfunc's tracer supplies what neither v1 nor our own design had — a
machine-readable dependency graph of a generation. The adapter's shape is
the decision's two halves:

* **trace graph out** — a stage's data *is* the traced instance-level graph
  (E §2: "a procfunc instance-level graph is our recipe — a data document
  describing which generator was chosen, with what parameters, under which
  seed"). Our recipe sits *above* it; the graph is the lower layer the
  stage cache was missing.
* **recipe diff in, re-execution out** — an edit becomes a graph edit
  (``replace_in_graph`` on the touched ``choice``/param nodes) and the
  engine re-executes the *reachable* subgraph only: the targeted variant
  E's confirming experiment asks for (step 3). A base stage produced by
  another flavour is refused — a v1 blob is not ours to interpret.

The procfunc boundary is one injectable object (:class:`ProcfuncRuntime`).
The default (:class:`ImportedProcfuncRuntime`) imports ``procfunc`` and
``infinigen2`` lazily and, when they are absent — as they are on this
core's Python 3.12 (procfunc pins ``bpy==4.2.0`` and Python 3.11 exactly,
E §2) — raises :class:`~core.engine.errors.EngineUnavailable` naming the
exact missing piece rather than an import traceback. What is ours and
testable without the engine: the translation from our entries to generator
calls (the ``_rand_from_params`` convention), and from our edit ops to
graph edits. That translation is the adapter; the rest is configuration.
"""
from __future__ import annotations

import importlib
import json
import time
from typing import Any, Protocol

from pydantic import BaseModel, Field

from core.canon import bytes_hash, canonical_bytes
from core.engine.contract import (
    EngineCapabilities,
    EngineDescriptor,
    ExportRequest,
    ExportResult,
    PreviewRequest,
    PreviewResult,
    ReexecuteRequest,
    StageRequest,
    StageResult,
    check_pin,
    expected_stage_key,
)
from core.engine.errors import EngineUnavailable
from core.engine.infinigen1 import RUNG_LADDER
from core.records import EnginePin, Op, Recipe

__all__ = [
    "GeneratorCall",
    "GraphEdit",
    "ImportedProcfuncRuntime",
    "Infinigen2Engine",
    "ProcfuncRuntime",
    "generator_calls",
    "graph_edits",
]

#: The marker every stage envelope this adapter writes carries — the lower
#: layer's name, so a base stage's flavour is checkable before re-execution.
_ENVELOPE_ENGINE = "infinigen-2-procfunc"


class GeneratorCall(BaseModel):
    """One entry as v2 sees it: a named generator plus its explicit params.

    The naming follows v2's own convention (E §2): generators expose
    ``<name>_rand`` twins, and ``<name>_rand_from_params`` takes the
    parameters explicitly — which is what our recipe already has.
    """

    entry_path: str
    module: str
    name: str
    variant: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class GraphEdit(BaseModel):
    """One recipe op as a graph edit: the touched node's parameter, and the
    value it takes. Resolving the parameter to a graph node id is the
    runtime's half (it owns the graph's node ids); the *what* is ours."""

    entry_path: str
    param: str
    op: str
    value: Any = None


class ProcfuncRuntime(Protocol):
    """The adapter's one boundary to the engine: five operations, no state.

    ``trace`` returns the instance-level graph as a JSON-able dict;
    ``replace`` applies :class:`GraphEdit`\\ s (procfunc's
    ``replace_in_graph`` on the recorded nodes); ``execute`` re-executes a
    graph and returns the stage's output bytes; ``render`` renders a graph
    through Cycles; ``export`` compiles a graph to a one-way output —
    **ours to write**, because v2 ships no exporter at all (E §1).
    """

    def trace(self, calls: list[GeneratorCall], seeds: dict[str, int]) -> dict: ...
    def replace(self, graph: dict, edits: list[GraphEdit]) -> dict: ...
    def execute(self, graph: dict) -> bytes: ...
    def render(self, graph: dict, *, resolution: str, samples: int, seed: int) -> bytes: ...
    def export(self, graph: dict, *, format: str, profile: str) -> bytes: ...


class ImportedProcfuncRuntime:
    """The default runtime: import the engine, in this process.

    Raises :class:`EngineUnavailable` (never a bare ``ImportError``) naming
    the module that is missing and the version constraint that matters on
    this box — the engine decision's own facts (E §2): procfunc pins
    ``bpy==4.2.0`` and Python ``==3.11.*``, so it cannot import under this
    core's 3.12 until the core runs on the engine's interpreter or the
    runtime proxies to it.
    """

    def __init__(self) -> None:
        self._procfunc: Any = None
        self._infinigen: Any = None

    def _load(self) -> None:
        if self._procfunc is not None:
            return
        try:
            self._procfunc = importlib.import_module("procfunc")
        except ImportError as e:
            raise EngineUnavailable(
                "the v2 engine needs `procfunc` (and `infinigen2`) in this "
                "process; procfunc pins bpy==4.2.0 and Python ==3.11.*, so "
                f"under this interpreter ({_py_version()}) it cannot import. "
                "Point the core at the engine's interpreter or proxy the "
                "runtime (E §2).",
                missing="procfunc",
            ) from e
        try:
            self._infinigen = importlib.import_module("infinigen2.generate")
        except ImportError as e:
            raise EngineUnavailable(
                "`procfunc` imports but `infinigen2.generate` does not; the "
                "infinigen checkout is not on this interpreter's path",
                missing="infinigen2.generate",
            ) from e

    def trace(self, calls: list[GeneratorCall], seeds: dict[str, int]) -> dict:
        self._load()
        raise NotImplementedError(
            "tracing through the imported runtime is the engine lane's next "
            "step (the v2-thor gate, plan week-1 item 2); the adapter's "
            "translation and the seam are what this branch lands"
        )

    def replace(self, graph: dict, edits: list[GraphEdit]) -> dict:
        self._load()
        raise NotImplementedError("see trace() — the imported runtime lands with the v2 gate")

    def execute(self, graph: dict) -> bytes:
        self._load()
        raise NotImplementedError("see trace() — the imported runtime lands with the v2 gate")

    def render(self, graph: dict, *, resolution: str, samples: int, seed: int) -> bytes:
        self._load()
        raise NotImplementedError("see trace() — the imported runtime lands with the v2 gate")

    def export(self, graph: dict, *, format: str, profile: str) -> bytes:
        self._load()
        raise NotImplementedError(
            "the v2 exporter is ours to write — v2 ships none (E §1); "
            "builder_usd is its natural home"
        )


def _py_version() -> str:
    import sys

    return f"Python {sys.version_info.major}.{sys.version_info.minor}"


# --------------------------------------------------------------------------- the translations
# These are the adapter's own, pure, testable half: our schema ⇄ v2's calls.


def generator_calls(recipe: Recipe) -> list[GeneratorCall]:
    """Our entries → v2 generator calls. A generator ref is a *name*; the
    ``_rand_from_params`` twin is chosen whenever the entry carries params,
    because params in hand is exactly what that entry point is for."""
    calls: list[GeneratorCall] = []
    for path, entry in sorted(recipe.entries.items()):
        if entry.generator is None:
            continue  # asset_ref and its kind carry no generator to call
        calls.append(
            GeneratorCall(
                entry_path=path,
                module=entry.generator.module,
                name=entry.generator.func,
                variant=entry.generator.variant,
                params=dict(entry.params),
                seed=entry.seed,
            )
        )
    return calls


def graph_edits(ops: list[Op]) -> list[GraphEdit]:
    """Our edit ops → graph edits. The path grammar is the spec's own
    (``harbor.crates.params.count``): a dotted entry path of up to three
    segments, the ``params`` step, the parameter name. Anything else is
    refused — an op this translation does not know is a schema change, not
    a silent pass-through."""
    edits: list[GraphEdit] = []
    for op in ops:
        parts = op.path.split(".")
        if len(parts) < 3 or parts[-2] != "params":
            raise ValueError(
                f"op path {op.path!r} is not <entry>.params.<name>; the v2 "
                "translation covers param edits only (structure edits are a "
                "graph re-trace, not a graph edit)"
            )
        edits.append(
            GraphEdit(
                entry_path=".".join(parts[:-2]), param=parts[-1],
                op=op.op, value=op.value,
            )
        )
    return edits


class Infinigen2Engine:
    """v2 + procfunc behind the seam: one resident process, one graph."""

    def __init__(self, *, pin: EnginePin, runtime: ProcfuncRuntime | None = None) -> None:
        self._pin = pin
        self._runtime = runtime or ImportedProcfuncRuntime()

    # -- the seam ------------------------------------------------------------

    def describe(self) -> EngineDescriptor:
        return EngineDescriptor(
            flavour="infinigen-2-procfunc",
            pin=self._pin,
            capabilities=EngineCapabilities(
                stages=True,
                previews=True,
                export_formats=["usda", "usdc", "glb"],
                reexecute="graph-edit",
            ),
            source=(
                f"infinigen 2.0 + procfunc · {self._pin.repo}@{self._pin.commit} "
                f"· in-process · config {self._pin.config}"
            ),
        )

    def generate_stage(self, request: StageRequest) -> StageResult:
        check_pin(self.describe(), request.recipe)
        graph = self._runtime.trace(generator_calls(request.recipe), dict(request.recipe.seeds))
        data = self._envelope(request, graph)
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage",
                      "bytes": len(data)},
            mechanism="graph-edit",
        )

    def reexecute(self, request: ReexecuteRequest) -> StageResult:
        check_pin(self.describe(), request.recipe)
        graph = self._graph_of(request.base)
        edited = self._runtime.replace(graph, graph_edits(request.ops))
        started = time.monotonic()
        out = self._runtime.execute(edited)
        data = self._envelope(request, edited, outputs=out)
        return StageResult(
            stage_key=expected_stage_key(request, self.describe()),
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "stage",
                      "bytes": len(data)},
            mechanism="graph-edit",
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    def render_preview(self, request: PreviewRequest) -> PreviewResult:
        check_pin(self.describe(), request.recipe)
        if request.rung not in RUNG_LADDER:
            ladder = {r: RUNG_LADDER[r] for r in sorted(RUNG_LADDER)}
            raise ValueError(f"unknown rung {request.rung}; the ladder is {ladder}")
        resolution, samples = RUNG_LADDER[request.rung]
        graph = self._runtime.trace(generator_calls(request.recipe), dict(request.recipe.seeds))
        started = time.monotonic()
        data = self._runtime.render(
            graph, resolution=resolution, samples=samples, seed=request.seed)
        return PreviewResult(
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": "render",
                      "bytes": len(data)},
            rung=request.rung,
            seed=request.seed,
            resolution=resolution,
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    def export(self, request: ExportRequest) -> ExportResult:
        check_pin(self.describe(), request.recipe)
        formats = self.describe().capabilities.export_formats
        if request.format not in formats:
            raise ValueError(f"this engine exports {formats}, not {request.format!r}")
        graph = self._runtime.trace(generator_calls(request.recipe), dict(request.recipe.seeds))
        started = time.monotonic()
        data = self._runtime.export(
            graph, format=request.format, profile=request.profile)
        return ExportResult(
            data=data,
            artifact={"sha256": bytes_hash(data), "kind": f"export:{request.format}",
                      "bytes": len(data)},
            format=request.format,
            profile=request.profile,
            wall_ms=(time.monotonic() - started) * 1000.0,
        )

    # -- internals -----------------------------------------------------------

    def _envelope(
        self,
        request: StageRequest | ReexecuteRequest,
        graph: dict,
        *,
        outputs: bytes | None = None,
    ) -> bytes:
        """The stage's data: the traced graph (the recipe's lower layer)
        plus, when the stage was executed, the digest of what it produced."""
        doc: dict[str, Any] = {
            "engine": _ENVELOPE_ENGINE,
            "pin": self._pin.model_dump(mode="json"),
            "stage": request.stage,
            "graph": graph,
        }
        if outputs is not None:
            doc["outputs_sha256"] = bytes_hash(outputs)
        return canonical_bytes(doc)

    def _graph_of(self, base: StageResult) -> dict:
        """Rule 5: only this flavour's own lower layer is ours to edit."""
        try:
            doc = json.loads(base.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            doc = None
        if not isinstance(doc, dict) or doc.get("engine") != _ENVELOPE_ENGINE:
            raise EngineUnavailable(
                f"the base stage (mechanism {base.mechanism!r}) is not a "
                "traced v2 graph; each engine re-executes only its own "
                "lower layer — re-trace the stage instead",
                base_stage_key=base.stage_key,
            )
        return doc["graph"]
