"""The world's own tests, runnable from builder-ide's pytest.

The world's tests are **scripts**: each one is a ``python tests/test_x.py``
that prints one line per check and exits non-zero when a check fails.
They were run by hand, on the Thor, one at a time. This conftest makes
pytest run them too **without rewriting a line of them**: the file is
executed exactly as the world's own documentation says to execute it, in
a subprocess, and its exit code is the verdict. The output is only shown
when a check fails, so a passing run is quiet.

The world needs builder-ide on the import path (``core.*``). It finds it
by walking up from its own package — see
:func:`agent_world_reflex.ledger.builder_ide_root` — so the scripts run
from wherever the repository is checked out.

Run them all by hand, the way the world does:

    python worlds/minecraft/tests/test_reward.py
    python worlds/minecraft/tests/test_drift_yield.py
    python worlds/minecraft/tests/test_d1_port.py

Or through builder-ide's pytest, which now collects this directory:

    pytest worlds/minecraft/tests -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WORLD = HERE.parent
REPO = WORLD.parent.parent


def pytest_collect_file(file_path: Path, parent):
    """Collect the world's script-style tests as pytest items.

    A file here that defines a ``main()`` and no ``test_*`` function is a
    script, not a pytest module. pytest's own collector would import it
    and find no tests, which is not the same as running it — so the file
    is run instead.
    """
    if file_path.suffix != ".py" or not file_path.name.startswith("test_"):
        return None
    if file_path.parent != HERE:
        return None
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "def main(" not in source:
        return None
    if any(line.startswith("def test_") for line in source.splitlines()):
        return None  # a pytest module: pytest's own collector takes it
    return ScriptFile.from_parent(parent, path=file_path)


class ScriptFile(pytest.File):
    """One of the world's script-style tests."""

    def collect(self):
        yield ScriptItem.from_parent(self, name=self.path.name)


class ScriptItem(pytest.Item):
    """One script, run as a subprocess.

    The script is the test. It prints its own checks and says so in its
    exit code, so the verdict is the exit code and the report is the
    output.
    """

    def runtest(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (str(REPO), str(WORLD / "reflex"), str(WORLD), env.get("PYTHONPATH", ""))
            if part
        )
        result = subprocess.run(
            [sys.executable, str(self.path)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(WORLD),
            timeout=600,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"{self.path.name} failed (exit {result.returncode})\n"
                f"--- stdout ---\n{result.stdout[-4000:]}\n"
                f"--- stderr ---\n{result.stderr[-4000:]}"
            )

    def reportinfo(self):
        return self.path, 0, self.path.name
