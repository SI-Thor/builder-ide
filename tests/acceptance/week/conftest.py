"""Pytest plumbing for the seven-night melt run.

Run it with this directory's own venv (the brief allows PyPI test
libraries in a venv):

    tests/acceptance/week/.venv/bin/python -m pytest tests/acceptance/week -q

The M1 driver's seats are reused: this conftest puts `tests/acceptance/m1`
on `sys.path` first (its session modules — driver, session, budgets,
seats/… — resolve there), then this directory (owner, script, weekseat,
meltweek — names that exist nowhere in m1). The sibling seats materialize
from their branches on first use; the week gets one fresh `$BUILDER_HOME`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_M1 = _HERE.parent / "m1"
for _p in (str(_M1), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from meltweek import build_week_world, teardown_week_world  # noqa: E402


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    home = tmp_path_factory.mktemp("week-home") / "builder-ide"
    run_dir = _HERE / "run" / "latest"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    w = build_week_world(home, run_dir)
    yield w
    teardown_week_world(w)
