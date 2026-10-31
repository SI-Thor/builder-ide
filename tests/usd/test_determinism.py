"""Determinism — the property the whole backbone stands on.

The plan's pass/fail for this spike (rev-tech spike 3): *re-emit → identical
bytes, sorted prims, no timestamps*. These tests check that at three levels:

* **in one process** — compiling the same recipe twice gives the same bytes;
* **in two processes** — compiling in two separate interpreters, with
  different hash seeds, gives the same bytes;
* **in the bytes themselves** — no timestamp anywhere in the emitted text, and
  the prims are written in sorted order.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from builder_usd.canonical import hash_bytes
from builder_usd.compile import compile_recipe
from builder_usd.verify import compare_emissions

#: Anything that looks like a date or a clock time. The STEP header carries
#: a timestamp field, so it is pinned to the epoch — which this pattern
#: deliberately allows (see :data:`EPOCH_PATTERN`).
DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}")
CLOCK_PATTERN = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
EPOCH_PATTERN = re.compile(r"^1970-01-01T00:00:00$")


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hash_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_two_compiles_in_one_process_are_identical(tmp_path, demo_source_and_records):
    source, records = demo_source_and_records
    first = tmp_path / "first"
    second = tmp_path / "second"
    compile_recipe(source, first, records)
    compile_recipe(source, second, records)

    differences = compare_emissions(first, second)
    assert differences == [], f"re-emission differs: {[str(d) for d in differences]}"


def test_two_processes_with_different_hash_seeds_are_identical(tmp_path, repo_root):
    """The strong form: two interpreters, two hash seeds, the same bytes."""
    env_base = dict(os.environ)
    env_base["PYTHONPATH"] = str(repo_root / "core" / "usd" / "src")

    outputs = []
    for index, seed in enumerate(("0", "12345")):
        out_dir = tmp_path / f"run{index}"
        env = dict(env_base)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-m", "builder_usd", "compile", "--demo", "--out", str(out_dir)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo_root),
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == "", f"the compile printed warnings:\n{result.stderr}"
        outputs.append(out_dir)

    differences = compare_emissions(outputs[0], outputs[1])
    assert differences == [], f"two processes differ: {[str(d) for d in differences]}"


def test_the_recipe_hash_is_the_same_in_two_processes(tmp_path, repo_root):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "core" / "usd" / "src")
    env["PYTHONHASHSEED"] = "999"
    result = subprocess.run(
        [sys.executable, "-m", "builder_usd", "compile", "--demo", "--out", str(tmp_path / "s")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("recipe:  sha256:")


def test_no_timestamps_in_the_emitted_layers(demo_stage):
    """No wall clock anywhere in the USD text."""
    for path in sorted(demo_stage.rglob("*.usda")):
        text = path.read_text(encoding="utf-8")
        found = DATE_PATTERN.findall(text)
        assert not found, f"{path.name} carries a date: {found}"
        clocks = [m for m in CLOCK_PATTERN.findall(text) if not EPOCH_PATTERN.match(m)]
        assert not clocks, f"{path.name} carries a clock time: {clocks}"


def test_the_step_header_timestamp_is_pinned(demo_stage):
    """The STEP master is the one file OCCT would stamp with the wall clock."""
    for path in sorted((demo_stage / "assets").glob("*.step")):
        text = path.read_text(encoding="utf-8")
        assert "1970-01-01T00:00:00" in text, f"{path.name} lost its pinned timestamp"
        stamps = [m for m in DATE_PATTERN.findall(text)]
        assert len(stamps) == 1, f"{path.name} carries more than the pinned timestamp"


def test_the_prims_are_written_in_sorted_order(demo_stage):
    """Sorted prims are what makes a USD diff readable as a review artifact."""
    for layer_name in ("geometry.usda", "provenance.usda", "semantics.usda"):
        text = (demo_stage / layer_name).read_text(encoding="utf-8")
        for children in _children_by_parent(text):
            assert children == sorted(children), (
                f"{layer_name} has unsorted children: {children}"
            )


def _children_by_parent(text: str) -> list[list[str]]:
    """The child prim names under each parent, in the order they are written."""
    stack: list[str] = []
    parents: dict[str, list[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r'^(?:def|over)\s+\w+\s+"([^"]+)"', stripped)
        if match:
            name = match.group(1)
            parents.setdefault("/".join(stack), []).append(name)
            stack.append(name)
            continue
        if stripped.startswith("{"):
            stack.append("")
            continue
        if stripped.startswith("}"):
            while stack and stack[-1] == "":
                stack.pop()
            if stack:
                stack.pop()
            continue
    return list(parents.values())


def test_the_root_layer_lists_the_concerns_alphabetically(demo_stage):
    root = (demo_stage / "root.usda").read_text(encoding="utf-8")
    listed = re.findall(r"@([a-z]+)\.usda@", root)
    assert listed == sorted(listed)
    assert listed == ["geometry", "materials", "physics", "provenance", "semantics"]


def test_the_asset_files_are_identical_across_compiles(tmp_path, demo_source_and_records):
    source, records = demo_source_and_records
    first = tmp_path / "a"
    second = tmp_path / "b"
    compile_recipe(source, first, records)
    compile_recipe(source, second, records)

    for suffix in ("*.glb", "*.step"):
        left = _hash_tree(first / "assets")
        right = _hash_tree(second / "assets")
        assert left == right, f"{suffix} differs between compiles"


def test_the_manifest_hashes_match_the_files_on_disk(demo_stage):
    import json

    manifest = json.loads((demo_stage / "manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["files"].items():
        path = demo_stage / relative
        assert path.is_file(), f"{relative} is in the manifest but not on disk"
        assert hash_bytes(path.read_bytes()) == digest, f"{relative} does not match its hash"
