"""Shared fixtures for the USD backbone tests.

The tests run against the repository's own virtualenv (``.venv``), which is
where ``usd-core`` and ``build123d`` live; ``core/usd/src`` is put on the path
so the package under test is the one in this tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "core" / "usd" / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from builder_usd.cli import load_bundle  # noqa: E402
from builder_usd.compile import compile_recipe  # noqa: E402
from builder_usd.demo import demo_bundle  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def demo_source_and_records():
    """The demo recipe and the provenance records that go with it."""
    return load_bundle(demo_bundle())


@pytest.fixture(scope="session")
def demo_stage(tmp_path_factory, demo_source_and_records) -> Path:
    """The demo recipe compiled once, for the read-only tests."""
    source, records = demo_source_and_records
    out_dir = tmp_path_factory.mktemp("demo-stage")
    compile_recipe(source, out_dir, records)
    return out_dir


@pytest.fixture(scope="session")
def demo_bundle_json() -> str:
    return json.dumps(demo_bundle(), sort_keys=True)
