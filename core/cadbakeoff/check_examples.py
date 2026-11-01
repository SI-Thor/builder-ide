#!/usr/bin/env python3
"""Check that the two few-shot examples in the prompt really build.

The prompt carries one worked example per kernel. If that example does not
build, every answer is anchored on a broken pattern, so this check runs before
any model call is spent.

    python -m core.cadbakeoff.check_examples
"""

from __future__ import annotations

import json
import pathlib
import sys

from core.cadbakeoff.build import build_build123d, build_solidcraft
from core.cadbakeoff.prompts import EXAMPLE_BUILD123D, EXAMPLE_SOLIDCRAFT
from core.cadbakeoff.validate import build123d_exports, load_registry

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path.home() / "lm-wt/cad-bakeoff"
CLI = ROOT / "solidcraft/target/release/solidcraft-cli"
REGISTRY = ROOT / "registry.json"
PY123D = ROOT / "b123d/bin/python"
RUNNER = HERE / "b123d_runner.py"


def example_json() -> dict:
    """The SolidCraft example: the JSON object on the line after 'Answer:'."""
    for line in EXAMPLE_SOLIDCRAFT.splitlines():
        line = line.strip()
        if line.startswith('{"commands"'):
            return json.loads(line)
    raise SystemExit("the SolidCraft example has no JSON object")


def example_python() -> str:
    """The build123d example: the module under 'Answer:'."""
    marker = "Answer:"
    body = EXAMPLE_BUILD123D.split(marker, 1)[1]
    return body.strip() + "\n"


def main() -> int:
    work = ROOT / "work/examples"
    work.mkdir(parents=True, exist_ok=True)
    registry = load_registry(REGISTRY)
    failures = 0

    sc_path = work / "example_solidcraft.json"
    sc_path.write_text(json.dumps(example_json(), indent=1))
    result = build_solidcraft(
        "sample_box", sc_path, work / "solidcraft", cli=CLI, registry=registry
    )
    print("solidcraft example: ok =", result.ok, "error =", result.error)
    if result.ok:
        print("  bodies:", json.dumps(result.bodies, indent=1)[:1200])
    else:
        failures += 1

    py_path = work / "example_build123d.py"
    py_path.write_text(example_python())
    spec = {
        "prop": "sample_box",
        "density_kg_m3": 700.0,
        "bodies": [
            {"name": "base", "role": "static"},
            {"name": "lid", "role": "moving"},
        ],
    }
    result = build_build123d(
        "sample_box", py_path, work / "build123d", python=PY123D, runner=RUNNER, spec=spec
    )
    print("build123d example: ok =", result.ok, "error =", result.error)
    if result.ok:
        print("  bodies:", json.dumps(result.bodies, indent=1)[:1200])
    else:
        failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
