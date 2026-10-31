"""The command line — the surface a person or a seat actually touches.

``compile`` writes the stage, ``verify`` re-emits and compares, ``read``
opens the stage, ``probe`` measures the GPU claim. The CLI is also the
seam's most likely entry point for the seats, so it is tested the way they
would use it: as a subprocess, with a recipe file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

def _run(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "core" / "usd" / "src")
    return subprocess.run(
        [sys.executable, "-m", "builder_usd", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),
    )


def test_the_fixture_recipe_is_the_demo_recipe(repo_root):
    """The file the CLI reads and the recipe the CLI builds in are one recipe."""
    from builder_usd.demo import demo_bundle

    fixture = json.loads(
        (repo_root / "tests" / "usd" / "fixtures" / "fjellvik_recipe.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture == demo_bundle(), "the fixture has drifted from the demo recipe"


def test_compile_writes_the_stage(tmp_path, repo_root):
    out = tmp_path / "stage"
    result = _run(
        repo_root, "compile", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", result.stderr
    assert "recipe:  sha256:" in result.stdout
    for name in (
        "root.usda",
        "geometry.usda",
        "materials.usda",
        "physics.usda",
        "provenance.usda",
        "semantics.usda",
        "manifest.json",
    ):
        assert (out / name).is_file(), f"{name} was not written"


def test_verify_says_the_stage_re_emits_identically(tmp_path, repo_root):
    out = tmp_path / "stage"
    _run(
        repo_root, "compile", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    result = _run(
        repo_root, "verify", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "IDENTICAL" in result.stdout


def test_verify_notices_a_tampered_stage(tmp_path, repo_root):
    out = tmp_path / "stage"
    _run(
        repo_root, "compile", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    geometry = out / "geometry.usda"
    geometry.write_text(
        geometry.read_text(encoding="utf-8").replace("3.5", "3.6"), encoding="utf-8"
    )
    result = _run(
        repo_root, "verify", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    assert result.returncode == 1
    assert "DIFFERENT" in result.stdout
    assert "geometry.usda" in result.stdout


def test_read_prints_the_composed_stage(tmp_path, repo_root):
    out = tmp_path / "stage"
    _run(
        repo_root, "compile", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    result = _run(repo_root, "read", "--out", str(out))
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", result.stderr
    assert "/World/harbor/crate_stack" in result.stdout
    assert "provenance(model='build123d'" in result.stdout


def test_probe_reports_a_gpu_free_process(repo_root):
    result = _run(repo_root, "probe")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "gpu free:      True" in result.stdout


def test_the_manifest_is_canonical_json(tmp_path, repo_root):
    out = tmp_path / "stage"
    _run(
        repo_root, "compile", "--recipe", "tests/usd/fixtures/fjellvik_recipe.json", "--out", str(out)
    )
    text = (out / "manifest.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["recipe"]["name"] == "Fjellvik"
    assert data["layers"]["geometry"] == "geometry.usda"
    assert data["toolchain"]["build123d"] == "0.13.0"
    # canonical: sorted keys, no spaces after the separators
    assert ", " not in text.split('"toolchain"')[0]
