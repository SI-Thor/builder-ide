"""The venv runtime — the v2 engine through its own CLI, as the Thor runs it.

The CLI double stands where the venv's ``infinigen`` binary stands: it
answers the package report, the clone's ``git rev-parse``, the traced
``graph.json`` and the rendered PNG — so what is tested is everything this
side of the subprocess boundary owns:

* the **pin is interrogated** (packages + commit → the pin; drift refused);
* the **name resolution** (rule 1: an unresolved generator is refused, never
  guessed; the subject names its entry);
* the **normalization** that makes a same-seed trace byte-identical (the
  experiment §3.3's two wobbles, removed) — the deterministic-rebuild
  property the merge gate byte-compares;
* the **refusals** that name their missing pieces.

The live run against the real venv is the acceptance suite's marked
``engine`` test (``tests/acceptance/m1/test_real_engine.py``) — minutes of
Cycles, not a unit test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.canon import canonical_bytes, content_hash
from core.engine import EngineUnavailable, Infinigen2Engine, open_engine
from core.engine.contract import PreviewRequest, StageRequest
from core.engine.infinigen1 import CommandResult
from core.engine.venv2 import Venv2Runtime, normalize_graph, render_dimensions

from .conftest import PIN_V2, fjellvik

GENERATORS = {
    "crates": "storage_cabinet_with_door_rand",
    "racks": "storage_cell_shelf_rand",
}

REPORT = {
    "python": "3.11.13",
    "packages": {
        "infinigen": {"version": "2.0.0a3", "licence": "BSD-3-Clause"},
        "procfunc": {"version": "0.37.0", "licence": "BSD-3-Clause"},
        "bpy": {"version": "4.2.0", "licence": "GPL-3.0"},
    },
}
COMMIT = "224598d4a2ff95b4fc928e72c222598b7122c698"


def _wobbly_graph(i: int) -> dict:
    """A traced graph as the CLI writes it: identical in meaning run to run,
    wobbling exactly where the experiment found wobble — the ``$repr``
    pointer leak and the ``generator_times`` wall-clock constant."""
    return {
        "name": "execute_generators",
        "nodes": [
            {"id": "n0", "type": "Constant", "value": {"$type": "rng"}},
            {"id": "n1", "type": "FunctionCall", "func": "spawn",
             "kwargs": {"rng": {"$ref": "n0"}}},
            {"id": "n2", "type": "Constant",
             "value": f"<function mix_shader at 0xffff{i:012x}>"},
            {"id": "n9", "type": "Constant", "value": 0.312 + i * 0.002},
        ],
        "outputs": {"generator_times": {"crates": {"$ref": "n9"}},
                    "objects": [{"$ref": "n1"}]},
    }


class CliDouble:
    """Answers the four subprocess shapes the runtime issues."""

    def __init__(self, *, graph=_wobbly_graph, png: bytes = b"\x89PNG-fake",
                 report: dict = REPORT, commit: str = COMMIT) -> None:
        self._graph = graph
        self._png = png
        self._report = report
        self._commit = commit
        self.argvs: list[list[str]] = []
        self.returncode = 0

    def run(self, argv, *, cwd=None) -> CommandResult:
        argv = [str(a) for a in argv]
        self.argvs.append(argv)
        if argv[0] == "git":
            return CommandResult(argv=argv, returncode=self.returncode,
                                 stdout=self._commit + "\n")
        if len(argv) > 1 and argv[1] == "-c":
            return CommandResult(argv=argv, returncode=self.returncode,
                                 stdout=json.dumps(self._report) + "\n")
        out = _output_of(argv)
        if out is None:
            return CommandResult(argv=argv, returncode=self.returncode)
        if "--trace" in argv:
            (out / "graph.json").write_text(
                json.dumps(self._graph(len(self.argvs))), encoding="utf-8")
        else:
            (out / "Camera").mkdir(parents=True, exist_ok=True)
            (out / "Camera" / "0000.png").write_bytes(self._png)
        return CommandResult(argv=argv, returncode=self.returncode)


def _output_of(argv: list[str]) -> Path | None:
    if "--output" in argv:
        return Path(argv[argv.index("--output") + 1])
    return None


@pytest.fixture
def venv_home(tmp_path) -> Path:
    """The venv's two files (the runtime checks they exist) and a clone."""
    bin_ = tmp_path / ".venv" / "bin"
    bin_.mkdir(parents=True)
    (bin_ / "python").touch()
    (bin_ / "infinigen").touch()
    clone = tmp_path / "src" / "infinigen-upstream"
    clone.mkdir(parents=True)
    return tmp_path


def _runtime(venv_home: Path, runner: CliDouble | None = None,
             generators: dict | None = None) -> Venv2Runtime:
    return Venv2Runtime(
        python=venv_home / ".venv" / "bin" / "python",
        generators=generators if generators is not None else GENERATORS,
        output_dir=venv_home / "engine",
        repo=venv_home / "src" / "infinigen-upstream",
        repo_name="princeton-vl/infinigen",
        runner=runner or CliDouble(),
    )


def _engine(venv_home: Path, runner: CliDouble | None = None) -> tuple[
        Infinigen2Engine, CliDouble]:
    runner = runner or CliDouble()
    rt = _runtime(venv_home, runner)
    return Infinigen2Engine(pin=rt.engine_pin(), runtime=rt), runner


# ------------------------------------------------------------------ the pin


def test_the_pin_is_interrogated_not_asserted(venv_home):
    """The venv is asked what it is; the config hash is over the resolved
    package set — the v2 way of RV patch 13 (no gin bundles to hash)."""
    rt = _runtime(venv_home)
    pin = rt.engine_pin()
    assert pin.repo == "princeton-vl/infinigen"
    assert pin.commit == COMMIT
    assert pin.blender == "bpy 4.2.0"
    assert pin.python == "3.11.13"
    assert pin.config == content_hash({
        "infinigen": REPORT["packages"]["infinigen"],
        "procfunc": REPORT["packages"]["procfunc"],
        "bpy": REPORT["packages"]["bpy"],
        "python": REPORT["python"],
    })
    assert rt.engine_pin() == rt.engine_pin()  # one interrogation, stable


def test_a_pinned_spec_that_drifts_from_the_venv_is_refused(venv_home):
    from core.records import EnginePin

    rt = _runtime(venv_home)
    drifted = EnginePin(
        repo="princeton-vl/infinigen", commit="deadbeef",
        config="sha256:" + "9" * 16, blender="bpy 4.2.0", python="3.11.13")
    with pytest.raises(EngineUnavailable) as caught:
        rt.engine_pin(drifted)
    assert caught.value.detail["pin"]["commit"] == "deadbeef"
    assert caught.value.detail["computed"]["commit"] == COMMIT


def test_a_venv_that_is_not_the_engine_is_named(venv_home):
    report = {"python": "3.11.13",
              "packages": {"infinigen": None, "procfunc": None, "bpy": None}}
    with pytest.raises(EngineUnavailable, match="infinigen"):
        _runtime(venv_home, CliDouble(report=report)).engine_pin()


def test_a_missing_venv_is_named(tmp_path):
    with pytest.raises(EngineUnavailable) as caught:
        Venv2Runtime(python=tmp_path / "nope" / "bin" / "python",
                     generators=GENERATORS, output_dir=tmp_path)
    assert caught.value.detail["missing"].endswith("python")


# ------------------------------------------------------------------ licence


def test_the_licence_row_comes_from_the_venvs_metadata(venv_home):
    """§1.6: the row is complete — spdx plus dependency terms, and the GPL
    entry says what it covers (the program, not the render)."""
    row = _runtime(venv_home).licence_row()
    assert row["spdx"] == "BSD-3-Clause"
    assert len(row["dependency_terms"]) == 3
    assert any("procfunc 0.37.0" in t for t in row["dependency_terms"])
    gpl = next(t for t in row["dependency_terms"] if "bpy" in t)
    assert "GPL-3.0" in gpl and "not the images" in gpl


# ------------------------------------------------------------- name resolution


def test_an_unresolved_generator_is_refused_never_guessed(venv_home):
    """A table that resolves only one of the recipe's generators: the other
    is refused by name — the adapter never picks a stand-in itself."""
    rt = _runtime(venv_home, generators={"crates": "storage_cabinet_with_door_rand"})
    engine = Infinigen2Engine(pin=rt.engine_pin(), runtime=rt)
    recipe = fjellvik(engine.describe().pin)
    with pytest.raises(EngineUnavailable) as caught:
        engine.generate_stage(StageRequest(
            recipe=recipe, version_hash="sha256:" + "a" * 64, stage="objects"))
    assert caught.value.detail["missing"] in ("crates", "racks")


def test_render_resolves_the_subject_entry(venv_home):
    """The subject names the entry: harbor.racks renders the racks chain,
    and the CLI is asked for the ladder's exact resolution and samples."""
    engine, cli = _engine(venv_home)
    result = engine.render_preview(PreviewRequest(
        recipe=fjellvik(engine.describe().pin),
        version_hash="sha256:" + "a" * 64,
        subject="harbor.racks", rung=2, seed=43))
    argv = cli.argvs[-1]
    assert argv[1] == "storage_cell_shelf_rand"
    assert argv[2] == "render_cycles"
    assert argv[argv.index("-r") + 1:argv.index("-r") + 3] == ["960", "540"]
    assert argv[argv.index("-s") + 1] == "16"
    assert argv[argv.index("--seed") + 1] == "43"
    assert result.data.startswith(b"\x89PNG")
    assert result.wall_ms is not None


def test_a_subject_that_names_no_entry_renders_the_first(venv_home):
    """A work-order id is not an entry path; the first entry renders and the
    provenance records the resolution — never a fuzzy guess."""
    engine, cli = _engine(venv_home)
    engine.render_preview(PreviewRequest(
        recipe=fjellvik(engine.describe().pin),
        version_hash="sha256:" + "a" * 64,
        subject="wo/crates-v2", rung=1, seed=42))
    assert cli.argvs[-1][1] == "storage_cabinet_with_door_rand"
    assert cli.argvs[-1][cli.argvs[-1].index("-r") + 1] == "320"  # rung 1


def test_chained_resolutions_split_into_cli_words(venv_home):
    """A material entry resolves to a *chain* (material + its host), the way
    the box's table says the v2 CLI wants it."""
    rt = _runtime(venv_home, generators={
        "weathering": "wood_scratched_rand material_cube"})
    assert rt.chain_for("weathering") == ["wood_scratched_rand", "material_cube"]


def test_resolution_names_map_to_dimensions():
    assert render_dimensions("180p") == (320, 180)
    assert render_dimensions("1080p") == (1920, 1080)
    with pytest.raises(ValueError, match="ladder"):
        render_dimensions("4k")


# ------------------------------------------------------------------ the stage


def test_the_traced_stage_is_byte_identical_across_runs(venv_home):
    """Rule 3 + the gate's deterministic-rebuild rung: two generations of
    the same stage produce identical bytes, because the two wobbles the CLI
    leaves in graph.json are normalized away."""
    engine, _ = _engine(venv_home)
    request = StageRequest(
        recipe=fjellvik(engine.describe().pin),
        version_hash="sha256:" + "a" * 64, stage="objects")
    first = engine.generate_stage(request)
    second = engine.generate_stage(request)
    assert first.data == second.data
    assert first.stage_key == second.stage_key
    doc = json.loads(first.data)
    assert doc["engine"] == "infinigen-2-procfunc"
    assert doc["graph"]["engine"] == "venv-cli"
    assert set(doc["graph"]["entries"]) == {"harbor.crates", "harbor.racks"}
    # and the wobbles really are gone from the bytes
    assert b"0xffff" not in first.data
    assert b"<generator_times>" in first.data


def test_traces_ask_for_random_control(venv_home):
    """Choices exist only at RANDOM_CONTROL or finer (the experiment §3.2);
    the adapter always asks at that level so the graph is editable data."""
    engine, cli = _engine(venv_home)
    engine.generate_stage(StageRequest(
        recipe=fjellvik(engine.describe().pin),
        version_hash="sha256:" + "a" * 64, stage="objects"))
    traces = [a for a in cli.argvs if "--trace" in a]
    assert len(traces) == 2  # one per entry with a generator
    for argv in traces:
        assert argv[argv.index("--trace_level") + 1] == "RANDOM_CONTROL"


# ------------------------------------------------------------------ refusals


def test_reexecution_and_export_name_their_missing_pieces(venv_home):
    engine, _ = _engine(venv_home)
    base = engine.generate_stage(StageRequest(
        recipe=fjellvik(engine.describe().pin),
        version_hash="sha256:" + "a" * 64, stage="objects"))
    from core.engine.contract import ExportRequest, ReexecuteRequest
    with pytest.raises(EngineUnavailable) as replace_caught:
        engine.reexecute(ReexecuteRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "b" * 64, stage="objects",
            ops=[], base=base))
    assert replace_caught.value.detail["missing"] == "instrumented re-execution"
    # the runtime's own halves refuse with their pieces named; the engine's
    # format check answers first on the seam (it reports no formats at all)
    with pytest.raises(EngineUnavailable) as export_caught:
        _runtime(venv_home).export(
            {}, format="usda", profile="preview")
    assert export_caught.value.detail["missing"] == "v2 exporter"
    with pytest.raises(ValueError, match="usda"):
        engine.export(ExportRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "b" * 64, format="usda"))
    assert engine.describe().capabilities.export_formats == []


def test_a_failed_render_carries_the_engines_last_words(venv_home):
    engine, cli = _engine(venv_home, CliDouble())
    cli.returncode = 1
    from core.engine import EngineFailed
    with pytest.raises(EngineFailed, match="exited 1"):
        engine.render_preview(PreviewRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "a" * 64,
            subject="harbor.crates", rung=2, seed=42))


class SilentCli(CliDouble):
    """A CLI that exits 0 and writes nothing — the run C shape, whatever
    its trigger was that morning: a manifest that no longer resolves the
    trailing render word, a skipped pass, a teardown that swallowed the
    work. The seam must turn that silence into a loud, diagnosable
    failure, not a missing-file guess."""

    def run(self, argv, *, cwd=None) -> CommandResult:
        argv = [str(a) for a in argv]
        self.argvs.append(argv)
        if argv[0] == "git":
            return CommandResult(argv=argv, returncode=0, stdout=COMMIT + "\n")
        if len(argv) > 1 and argv[1] == "-c":
            return CommandResult(argv=argv, returncode=0,
                                 stdout=json.dumps(REPORT) + "\n")
        return CommandResult(argv=argv, returncode=0,
                             stdout="infinigen: nothing to do\n")


def test_a_missing_render_subcommand_is_a_loud_failure(venv_home):
    """The CLI exits 0 having ignored the render word (a manifest that
    dropped it, the way PR #1's merge dropped a fallback in the fork): the
    render is refused loudly, with the exit, the argv and the CLI's own
    last words in the failure — never a silent None and never a bare
    'no PNG' without the engine's side of the story."""
    cli = SilentCli()
    rt = _runtime(venv_home, cli)
    engine = Infinigen2Engine(pin=rt.engine_pin(), runtime=rt)
    from core.engine import EngineFailed
    with pytest.raises(EngineFailed) as caught:
        engine.render_preview(PreviewRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "a" * 64,
            subject="harbor.crates", rung=2, seed=42))
    assert caught.value.detail["returncode"] == 0
    assert caught.value.detail["missing"].endswith(
        "render/harbor_crates-42-960x540-16spp")
    assert "no PNG" in caught.value.message
    assert "last words" in caught.value.message
    assert "nothing to do" in caught.value.message


def test_a_silent_no_op_trace_is_a_loud_failure(venv_home):
    """Same silence on the trace path: exit 0, no graph.json — refused with
    the CLI's last words, because a stage built from nothing must never
    enter the cache as if it were a stage."""
    cli = SilentCli()
    rt = _runtime(venv_home, cli)
    engine = Infinigen2Engine(pin=rt.engine_pin(), runtime=rt)
    from core.engine import EngineFailed
    with pytest.raises(EngineFailed) as caught:
        engine.generate_stage(StageRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "a" * 64, stage="objects"))
    assert caught.value.detail["returncode"] == 0
    assert "no graph.json" in caught.value.message
    assert "nothing to do" in caught.value.message


# ------------------------------------------------------------------ registry


def test_the_registry_builds_the_venv_flavour_from_configuration(venv_home):
    """`runtime: venv` + the venv's paths — one configuration mapping, no
    pin (the venv is asked), the seam's Engine behind it."""
    runner = CliDouble()
    spec = {
        "flavour": "infinigen-2-procfunc",
        "runtime": "venv",
        "python": str(venv_home / ".venv" / "bin" / "python"),
        "repo": str(venv_home / "src" / "infinigen-upstream"),
        "repo_name": "princeton-vl/infinigen",
        "generators": GENERATORS,
        "output_dir": str(venv_home / "engine"),
        "runner": runner,
    }
    engine = open_engine(spec)
    assert isinstance(engine, Infinigen2Engine)
    described = engine.describe()
    assert described.flavour == "infinigen-2-procfunc"
    assert described.pin.commit == COMMIT
    assert "venv-subprocess" in described.source
    assert described.capabilities.export_formats == []


def test_the_registry_refuses_an_unknown_runtime(venv_home):
    with pytest.raises(ValueError, match="venv"):
        open_engine({
            "flavour": "infinigen-2-procfunc",
            "pin": PIN_V2.model_dump(),
            "runtime": "grpc",
        })


# ------------------------------------------------------------------ normalize


def test_normalize_graph_removes_exactly_the_two_wobbles():
    """A pure function of the graph: timing constants and pointer addresses
    go; ids, order, choices and parameters pass through untouched."""
    a = _wobbly_graph(0)
    b = _wobbly_graph(7)
    assert canonical_bytes(a) != canonical_bytes(b)  # raw bytes differ
    assert canonical_bytes(normalize_graph(a)) == canonical_bytes(normalize_graph(b))
    kept = normalize_graph(a)
    assert kept["nodes"][0] == a["nodes"][0]           # untouched node
    assert kept["nodes"][1]["kwargs"] == a["nodes"][1]["kwargs"]
    assert kept["nodes"][3]["value"] == "<generator_times>"  # the timing
    assert kept["nodes"][2]["value"] == "<function mix_shader at 0xADDR>"
