"""The engine suite's shared doubles and factories.

Test-only code lives here, not in the production package. Two doubles do
the work a real box would:

* :class:`FakeCommandRunner` — stands where the v1 adapter's subprocess
  would stand: records the argv it was asked to run and writes the stage
  output the adapter was told to expect, so the subprocess *contract* is
  what is tested, never Blender;
* :class:`RecordingRuntime` — stands where procfunc would stand: records
  the five operations the v2 adapter asks for and answers with
  deterministic shapes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.engine.infinigen1 import CommandResult
from core.records import EnginePin, GeneratorRef, Op, Recipe, RecipeEntry

# Two pins the way the project will really have them: the v1 checkout the
# spike ran, and the v2 decision's pin. The config hashes are distinct, so
# a swap must change every stage key.
PIN_V1 = EnginePin(
    repo="SI-Thor/infinigen-thor",
    commit="9f31c0e",
    config="sha256:cf90a1d4e2b7",
    blender="4.2",
    python="3.11",
)
PIN_V2 = EnginePin(
    repo="SI-Thor/infinigen-thor",
    commit="v2-0001",
    config="sha256:" + "b" * 16,
    blender="4.2",
    python="3.11",
)


def fjellvik(pin: EnginePin, *, crates: int = 8) -> Recipe:
    """A two-entry recipe in our schema — the seam's input, never the
    engine's format."""
    return Recipe(
        id="rcp_fjellvik",
        name="Fjellvik",
        engine_pin=pin,
        seeds={"terrain": 771, "props": 42},
        entries={
            "harbor.crates": RecipeEntry(
                path="harbor.crates",
                kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="crates",
                    variant=None, rev=pin.commit,
                ),
                params={"count": crates, "style": "weathered"},
                seed=42,
            ),
            "harbor.racks": RecipeEntry(
                path="harbor.racks",
                kind="prop_set",
                generator=GeneratorRef(
                    module="infinigen_thor.structures", func="racks",
                    variant=None, rev=pin.commit,
                ),
                params={"count": 3},
                seed=43,
            ),
        },
    )


def param_ops(entry: str, **values) -> list[Op]:
    return [
        Op(op="set", path=f"{entry}.params.{key}", value=value)
        for key, value in sorted(values.items())
    ]


class FakeCommandRunner:
    """Records argv; writes whatever the adapter asked to be written."""

    def __init__(self, *, payload: bytes = b"stage-output-bytes") -> None:
        self.argvs: list[list[str]] = []
        self.payload = payload
        self.returncode = 0
        self.stderr = ""

    def run(self, argv, *, cwd=None) -> CommandResult:
        argv = list(argv)
        self.argvs.append(argv)
        out = _output_path(argv)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(self.payload)
        return CommandResult(
            argv=argv, returncode=self.returncode, stderr=self.stderr,
        )

    @property
    def last(self) -> list[str]:
        return self.argvs[-1]


def _output_path(argv: list[str]) -> Path | None:
    if "--output" in argv:
        i = argv.index("--output")
        return Path(argv[i + 1])
    return None


class RecordingRuntime:
    """Answers the five procfunc operations with deterministic shapes."""

    def __init__(self) -> None:
        self.ops: list[tuple] = []
        #: what a re-execution produced — differs from the base so tests can
        #: see the graph-edit actually flow through
        self.execute_payload = b"v2-reexecuted-stage"

    def trace(self, calls, seeds) -> dict:
        self.ops.append(("trace", [c.model_dump() for c in calls], dict(seeds)))
        return {
            "nodes": {
                f"n{i}": {"generator": c.name, "entry": c.entry_path,
                          "params": c.params}
                for i, c in enumerate(calls)
            },
            "edges": [],
            "traced": True,
        }

    def replace(self, graph: dict, edits) -> dict:
        self.ops.append(("replace", graph, [e.model_dump() for e in edits]))
        out = json.loads(json.dumps(graph))  # a copy, like the pure upstream
        for edit in edits:
            for node in out["nodes"].values():
                if node["entry"] == edit.entry_path:
                    node["params"] = {**node.get("params", {}), edit.param: edit.value}
        return out

    def execute(self, graph: dict) -> bytes:
        self.ops.append(("execute", graph))
        return self.execute_payload

    def render(self, calls, seeds, *, subject, resolution, samples, seed) -> bytes:
        self.ops.append(("render", [c.entry_path for c in calls], subject,
                         resolution, samples, seed))
        return f"v2-render {resolution} {samples}spp seed{seed}".encode()

    def export(self, graph: dict, *, format: str, profile: str) -> bytes:
        self.ops.append(("export", format, profile))
        return f"v2-export {format} {profile}".encode()


@pytest.fixture
def fake_runner():
    return FakeCommandRunner()


@pytest.fixture
def runtime():
    return RecordingRuntime()
