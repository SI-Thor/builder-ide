"""The v1 adapter skeleton — the subprocess contract, without a checkout.

The fake command runner records argv and writes the output the adapter
asked for, so what is tested is the contract: the pinned module, the task
flags, the seed, the config bundle, the content-addressed output path, and
the two refusals that guard the cache (a checkout that is not the pin, a
recipe pinned elsewhere).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.engine import EngineFailed, EngineUnavailable, Infinigen1xEngine
from core.engine.contract import (
    ExportRequest,
    PreviewRequest,
    ReexecuteRequest,
    StageRequest,
)
from core.engine.infinigen1 import RUNG_LADDER, config_bundle_hash

from .conftest import PIN_V2, FakeCommandRunner, fjellvik, param_ops

VERSION = "sha256:" + "a" * 64


def _engine(tmp_path, runner, *, pin=None, config=None):
    config_files = [config or tmp_path / "base.gin"]
    if config is None:
        config_files[0].write_text("# base config\n")
    pin = pin or pin_over(config_files)
    return Infinigen1xEngine(
        pin=pin,
        repo=tmp_path / "infinigen-thor",
        python=tmp_path / "venv" / "bin" / "python",
        config_files=config_files,
        output_dir=tmp_path / "stages",
        runner=runner,
    )


def pin_over(config_files) -> object:
    """The pin that honestly names this config bundle."""
    from .conftest import PIN_V1

    return PIN_V1.model_copy(update={"config": config_bundle_hash(config_files)})


def _ready_engine(tmp_path, runner, **kw):
    engine = _engine(tmp_path, runner, **kw)
    engine._repo.mkdir(parents=True, exist_ok=True)
    engine._python.parent.mkdir(parents=True, exist_ok=True)
    engine._python.touch()
    return engine


def _stage(engine, *, stage="coarse", version=VERSION, recipe=None):
    return StageRequest(
        recipe=recipe or fjellvik(engine.describe().pin),
        version_hash=version, stage=stage,
    )


def _output_path(argv: list[str]) -> Path:
    return Path(argv[argv.index("--output") + 1])


def test_the_config_bundle_is_verified_against_the_pin(tmp_path, fake_runner):
    """The one construction-time check that guards the cache: a checkout
    whose config hashes to anything but the pin's is not the pinned engine
    (RV patch 13 — config drift would defeat §5.3)."""
    config = tmp_path / "base.gin"
    config.write_text("denoise = False\n")
    pin = pin_over([config]).model_copy(update={"config": "sha256:0000dead"})
    with pytest.raises(EngineUnavailable) as caught:
        _engine(tmp_path, fake_runner, pin=pin, config=config)
    assert "config" in str(caught.value)
    assert caught.value.detail["pin"] == "sha256:0000dead"


def test_a_missing_config_file_is_the_missing_piece_named(tmp_path, fake_runner):
    from .conftest import PIN_V1

    with pytest.raises(EngineUnavailable) as caught:
        Infinigen1xEngine(
            pin=PIN_V1, repo=tmp_path / "repo",
            python=tmp_path / "py", config_files=[tmp_path / "nope.gin"],
            output_dir=tmp_path / "stages", runner=fake_runner,
        )
    assert str(tmp_path / "nope.gin") in str(caught.value)


def test_a_recipe_pinned_elsewhere_is_refused(tmp_path, fake_runner):
    engine = _ready_engine(tmp_path, fake_runner)
    with pytest.raises(Exception, match="pin"):
        engine.generate_stage(StageRequest(
            recipe=fjellvik(PIN_V2), version_hash=VERSION, stage="coarse"))


def test_the_subprocess_contract_argv(tmp_path, fake_runner):
    """The adapter asks our fork's stage runner for the task, hands it the
    recipe as a path to canonical JSON, the pinned configs, and a
    content-addressed output path."""
    engine = _ready_engine(tmp_path, fake_runner)
    result = engine.generate_stage(_stage(engine))
    argv = fake_runner.last
    assert argv[0].endswith("python")
    assert argv[1:3] == ["-m", "infinigen_thor.stage_runner"]
    assert argv[argv.index("--task") + 1] == "coarse"
    assert "-g" in argv and str(tmp_path / "base.gin") in argv
    assert argv[argv.index("--version-hash") + 1] == VERSION
    assert result.data == fake_runner.payload
    assert result.mechanism == "full-reeval"
    # the output path is the stage key, content-addressed under stages/
    out = _output_path(argv)
    assert str(out).startswith(str(tmp_path / "stages"))
    assert out.name == result.stage_key.removeprefix("sha256:")
    assert out.parent.name == result.stage_key.removeprefix("sha256:")[:2]


def test_the_recipe_crosses_as_data_canonical_json(tmp_path, fake_runner):
    """§2.2's rule: data, never code — the document is written beside the
    outputs, and re-asking for the same version does not rewrite it."""
    engine = _ready_engine(tmp_path, fake_runner)
    engine.generate_stage(_stage(engine))
    engine.generate_stage(_stage(engine))
    recipe_path = tmp_path / "stages" / "recipes" / ("a" * 64 + ".json")
    assert recipe_path.is_file()
    doc = json.loads(recipe_path.read_text())
    assert doc["id"] == "rcp_fjellvik"
    assert doc["entries"]["harbor.crates"]["params"]["count"] == 8


def test_a_failing_subprocess_fails_loudly_with_its_own_words(
        tmp_path, fake_runner):
    engine = _ready_engine(tmp_path, fake_runner)
    fake_runner.returncode = 1
    fake_runner.stderr = "CUDA_ERROR_NO_BINARY_FOR_GPU_ARCH"
    with pytest.raises(EngineFailed) as caught:
        engine.generate_stage(_stage(engine))
    assert "NO_BINARY" in str(caught.value)


def test_success_without_an_output_is_the_named_missing_piece(
        tmp_path, fake_runner):
    """The runner's output contract is the engine repo's half of the seam;
    an adapter that invented bytes here would be a fabrication."""
    engine = _ready_engine(tmp_path, fake_runner)

    def running_blind(argv, *, cwd=None):
        from core.engine.infinigen1 import CommandResult

        return CommandResult(argv=list(argv), returncode=0)

    engine._runner = type("Blind", (), {"run": staticmethod(running_blind)})()
    with pytest.raises(EngineFailed) as caught:
        engine.generate_stage(_stage(engine))
    assert "stage runner" in str(caught.value)


def test_no_checkout_is_engine_unavailable_not_a_traceback(tmp_path, fake_runner):
    engine = _engine(tmp_path, fake_runner)  # repo/python never created
    with pytest.raises(EngineUnavailable) as caught:
        engine.generate_stage(_stage(engine))
    assert "checkout" in str(caught.value)


def test_unknown_stages_are_refused_with_the_table(tmp_path, fake_runner):
    engine = _ready_engine(tmp_path, fake_runner)
    with pytest.raises(ValueError, match="coarse"):
        engine.generate_stage(_stage(engine, stage="solve"))


def test_the_rung_ladder_resolves_resolution_and_samples(tmp_path, fake_runner):
    engine = _ready_engine(tmp_path, fake_runner)
    result = engine.render_preview(PreviewRequest(
        recipe=fjellvik(engine.describe().pin), version_hash=VERSION,
        subject="harbor.crates", rung=2, seed=42))
    argv = fake_runner.last
    assert argv[argv.index("--resolution") + 1] == "480p"
    assert argv[argv.index("--samples") + 1] == "16"
    assert argv[argv.index("--seed") + 1] == "42"
    assert result.resolution == "480p"
    assert RUNG_LADDER[2] == ("480p", 16)  # P §2.1's documented knob


def test_export_uses_v1s_own_exporter(tmp_path, fake_runner):
    """v1 keeps tools/export.py (E §1) — the one export surface this fork
    does not have to write."""
    engine = _ready_engine(tmp_path, fake_runner)
    engine.generate_stage(_stage(engine, stage="scene"))
    fake_runner.argvs.clear()
    result = engine.export(ExportRequest(
        recipe=fjellvik(engine.describe().pin), version_hash=VERSION,
        format="usda"))
    argv = fake_runner.last
    assert argv[argv.index("-m") + 1] == "infinigen.tools.export"
    assert argv[argv.index("--formats") + 1] == "usda"
    assert result.format == "usda"
    with pytest.raises(ValueError, match="usda"):
        engine.export(ExportRequest(
            recipe=fjellvik(engine.describe().pin), version_hash=VERSION,
            format="webp"))


def test_reexecution_is_an_honest_full_reeval(tmp_path, fake_runner):
    """v1 has no graph to edit: the mechanism says full-reeval, and the
    base stage's key rides the argv so the runner can reuse its inputs."""
    engine = _ready_engine(tmp_path, fake_runner)
    base = engine.generate_stage(_stage(engine))
    fake_runner.argvs.clear()
    edited = fjellvik(engine.describe().pin, crates=9)
    again = engine.reexecute(ReexecuteRequest(
        recipe=edited, version_hash="sha256:" + "b" * 64, stage="coarse",
        ops=param_ops("harbor.crates", count=9), base=base))
    argv = fake_runner.last
    assert argv[argv.index("--base-stage") + 1] == base.stage_key
    assert again.mechanism == "full-reeval"
    assert again.stage_key != base.stage_key


def test_the_wall_time_is_measured_not_invented(tmp_path, fake_runner):
    engine = _ready_engine(tmp_path, fake_runner)
    result = engine.render_preview(PreviewRequest(
        recipe=fjellvik(engine.describe().pin), version_hash=VERSION,
        subject="harbor.crates", rung=2, seed=42))
    assert result.wall_ms is not None and result.wall_ms >= 0.0
