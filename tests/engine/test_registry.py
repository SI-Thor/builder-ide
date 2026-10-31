"""Pointing the core at an engine is configuration — `open_engine`."""

from __future__ import annotations

import pytest

from core.engine import (
    EngineUnavailable,
    FakeEngine,
    Infinigen1xEngine,
    Infinigen2Engine,
    engine_from_env,
    open_engine,
)
from core.engine.infinigen1 import config_bundle_hash

from .conftest import PIN_V1, PIN_V2, FakeCommandRunner, RecordingRuntime


def test_the_fake_flavour_takes_its_pin_from_the_spec():
    engine = open_engine({"flavour": "fake", "pin": PIN_V1.model_dump()})
    assert isinstance(engine, FakeEngine)
    assert engine.describe().pin == PIN_V1


def test_the_v1_flavour_builds_the_subprocess_adapter(tmp_path):
    config = tmp_path / "base.gin"
    config.write_text("denoise = False\n")
    engine = open_engine({
        "flavour": "infinigen-1x",
        "pin": PIN_V1.model_copy(
            update={"config": config_bundle_hash([config])}).model_dump(),
        "repo": tmp_path / "repo",
        "python": tmp_path / "py",
        "config_files": [str(config)],
        "output_dir": tmp_path / "stages",
        "runner": FakeCommandRunner(),
    })
    assert isinstance(engine, Infinigen1xEngine)
    assert engine.describe().flavour == "infinigen-1x"


def test_the_v2_flavour_builds_the_in_process_adapter():
    engine = open_engine({
        "flavour": "infinigen-2-procfunc",
        "pin": PIN_V2.model_dump(),
        "runtime": RecordingRuntime(),
    })
    assert isinstance(engine, Infinigen2Engine)


def test_an_unknown_flavour_names_the_flavours():
    with pytest.raises(ValueError, match="infinigen-2-procfunc"):
        open_engine({"flavour": "blender-magic"})


def test_the_environment_is_the_real_engines_deploy_line():
    """One environment variable on the service — no code change, no recipe
    change (the branch's pass/fail). Unset means unset: no engine is
    invented to fill the gap."""
    spec = '{"flavour": "fake", "pin": {"repo": "r", "commit": "c", ' \
           '"config": "sha256:abcd1234", "blender": "4.2", "python": "3.11"}}'
    engine = engine_from_env({"BUILDER_ENGINE": spec})
    assert isinstance(engine, FakeEngine)
    assert engine.describe().pin.commit == "c"
    assert engine_from_env({}) is None


def test_no_configuration_is_never_a_silent_default(tmp_path):
    """A box not pointed at a real engine gets the named refusal when the
    adapter runs — not a quietly constructed fake. The v1 adapter's own
    refusal is the missing checkout (test_infinigen1); the v2 adapter's is
    the missing procfunc (test_infinigen2)."""
    from core.engine.contract import StageRequest

    from .conftest import fjellvik

    config = tmp_path / "base.gin"
    config.write_text("# base\n")
    engine = Infinigen1xEngine(
        pin=PIN_V1.model_copy(update={"config": config_bundle_hash([config])}),
        repo=tmp_path / "repo", python=tmp_path / "py",
        config_files=[config], output_dir=tmp_path / "stages",
        runner=FakeCommandRunner(),
    )
    assert engine.describe().flavour == "infinigen-1x"  # describe is free
    with pytest.raises(EngineUnavailable):
        engine.generate_stage(StageRequest(
            recipe=fjellvik(engine.describe().pin),
            version_hash="sha256:" + "a" * 64, stage="coarse"))
