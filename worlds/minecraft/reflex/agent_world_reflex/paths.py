"""Where the world's files are.

The world used to be its own repository at ``~/lm-wt/agent-world``, and
its paths said so. It is now a package of builder-ide, at
``worlds/minecraft`` — and the paths are computed from the package's own
location instead, so they are right wherever the repository is checked
out and they follow the package if it moves again.

Every path here can still be overridden by the environment variable it
always had, because a box that wants the world's runtime somewhere else
(the Thor's runtime tree is not in git) must still be able to say so:

===========================  =========================  ==================
what                        environment variable        default
===========================  =========================  ==================
the runtime tree            ``AW_RUNTIME``              ``<world>/runtime``
the skill library           ``AW_SKILLS_DIR``           ``<runtime>/skills``
the log of record           ``AW_LEDGER``               ``<runtime>/world-ledger.sqlite3``
the builders' own log       ``AW_LOG_DIR``              ``<runtime>/logs``
===========================  =========================  ==================
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "world_root",
    "runtime_dir",
    "skills_dir",
    "ledger_path",
    "logs_dir",
    "pause_file",
]


def world_root() -> Path:
    """The world's own root — the directory that holds ``reflex`` and ``gym``."""
    return Path(__file__).resolve().parents[2]


def runtime_dir() -> Path:
    """The runtime tree: not in git, all of it re-creatable."""
    return Path(os.environ.get("AW_RUNTIME", str(world_root() / "runtime"))).expanduser()


def skills_dir() -> Path:
    """Where the skill library lives."""
    return Path(
        os.environ.get("AW_SKILLS_DIR", str(runtime_dir() / "skills"))
    ).expanduser()


def ledger_path() -> Path:
    """The log of record: one SQLite file."""
    return Path(
        os.environ.get("AW_LEDGER", str(runtime_dir() / "world-ledger.sqlite3"))
    ).expanduser()


def logs_dir() -> Path:
    """Where the world's own logs are written."""
    return Path(os.environ.get("AW_LOG_DIR", str(runtime_dir() / "logs"))).expanduser()


def pause_file() -> Path:
    """The drift detector's pause file — the world's admission seam."""
    return Path(
        os.environ.get("AW_DRIFT_PAUSE", str(runtime_dir() / "drift-pause.json"))
    ).expanduser()
