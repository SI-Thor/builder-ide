"""Pytest plumbing for the M1 acceptance session.

Run it with the directory's own venv (the brief allows PyPI test libraries
in a venv here):

    tests/acceptance/m1/.venv/bin/python -m pytest tests/acceptance/m1 -q

The sibling seats are materialized from their branches on first use
(`siblings.py`); the session gets a fresh `$BUILDER_HOME` per run.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest  # noqa: E402

from driver import build_world, teardown_world  # noqa: E402


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    home = tmp_path_factory.mktemp("m1-home") / "builder-ide"
    run_dir = _HERE / "run" / "latest"
    if run_dir.exists():
        import shutil

        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    w = build_world(home, run_dir)
    yield w
    teardown_world(w)
