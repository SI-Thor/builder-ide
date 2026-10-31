"""Zero GPU memory — the claim, measured.

rev-tech spike 3's pass/fail: *build123d/CadQuery use zero GPU memory*.
res-cad §7 checked that claim from the dependency trees (no CUDA, no GPU,
no torch anywhere in OCCT's tree); this checks it on the box, in the process
that actually does the work.

Two levels:

* **in this process** — after a full compile, nothing GPU-shaped is mapped
  and no ``/dev/nvidia*`` handle is open;
* **in a fresh process** — the same, through the CLI, so the check does not
  inherit anything this test session imported.

On this box ``nvidia-smi`` reports GPU memory as ``[N/A]`` (the memory is
unified with the CPU's — rev-tech R3), so there is no GPU number to read.
The claim is therefore structural: the process has no path to the GPU at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from builder_usd.probe import probe


def test_the_compile_process_maps_no_gpu_library(tmp_path, demo_source_and_records):
    from builder_usd.compile import compile_recipe

    source, records = demo_source_and_records
    compile_recipe(source, tmp_path / "stage", records)

    result = probe()
    assert result.gpu_mappings == (), f"GPU libraries are mapped: {result.gpu_mappings}"
    assert result.gpu_fds == (), f"GPU handles are open: {result.gpu_fds}"
    assert result.gpu_free


def test_the_process_never_opened_the_nvidia_device(tmp_path, demo_source_and_records):
    from builder_usd.compile import compile_recipe

    source, records = demo_source_and_records
    compile_recipe(source, tmp_path / "stage", records)
    for entry in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        assert "nvidia" not in target.lower(), f"the process holds {target}"


def test_a_fresh_process_reports_gpu_free(tmp_path, repo_root):
    """The same check in a clean interpreter, through the CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "core" / "usd" / "src")
    result = subprocess.run(
        [sys.executable, "-m", "builder_usd", "probe"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "gpu free:      True" in result.stdout, result.stdout


def test_the_compile_runs_in_a_fresh_process_without_a_gpu(tmp_path, repo_root):
    """Compile *and* probe, in one fresh interpreter."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "core" / "usd" / "src")
    script = (
        "import json, sys;"
        "from builder_usd.cli import load_bundle;"
        "from builder_usd.compile import compile_recipe;"
        "from builder_usd.demo import demo_bundle;"
        "from builder_usd.probe import probe;"
        f"source, records = load_bundle(demo_bundle());"
        f"compile_recipe(source, {str(tmp_path / 'stage')!r}, records);"
        "p = probe();"
        "print(json.dumps(p.to_dict()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    import json

    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["gpu_free"] is True, report
    assert report["gpu_mappings"] == []
    assert report["gpu_fds"] == []
    assert report["peak_rss_kb"] > 0


def test_the_dependency_tree_has_no_cuda(tmp_path, repo_root):
    """The claim from res-cad §7, checked against the installed wheels."""
    import importlib.metadata as metadata

    for distribution in metadata.distributions():
        name = (distribution.metadata["Name"] or "").lower()
        if name in {"torch", "nvidia-cuda-runtime-cu13", "nvidia-cublas-cu13"}:
            raise AssertionError(f"a GPU runtime is installed: {name}")

    build123d = metadata.distribution("build123d")
    requires = build123d.requires or []
    for requirement in requires:
        assert "torch" not in requirement.lower(), f"build123d pulls {requirement}"
