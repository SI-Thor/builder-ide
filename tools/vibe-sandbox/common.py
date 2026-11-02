"""Shared paths, the lane ledger, and box state for vibe-sandbox.

One SQLite ledger for the lane (the same shape as the world ledger: one
append-only row per stage decision). Every stage the runner completes writes
a row with its wall time and the box's state, so a report can always quote a
number with its load beside it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

LANE = Path(__file__).resolve().parent
REPO = LANE.parent.parent
ARTIFACTS = REPO / "artifacts" / "vibe-sandbox"
INBOX = ARTIFACTS / "inbox"
OUTBOX = ARTIFACTS / "outbox"
LEDGER = ARTIFACTS / "ledger.sqlite3"
RESULTS = REPO / "docs/lab/vibe-sandbox-scripts/results"

# The critic's mesh probe needs an interpreter that can ``import bpy``. On the
# Thor that is the Infinigen checkout's virtualenv (bpy 4.2); the system
# Blender 4.0.2 is used for the build/export stage, and a 4.2 bpy reads a
# 4.0 blend file fine.
BPY_PYTHON = Path.home() / "src/infinigen-thor/.venv/bin/python"

THOR_ADMIT = str(Path.home() / "lm-tools/thor-admit")
NODE_BIN = Path.home() / ".nvm/versions/node/v24.22.2/bin"
THREE_DIR = Path.home() / "lm-wt/agent-world/viewer/node_modules/three"
PLAYWRIGHT_MODULES = Path.home() / "lm-tools/playwright/node_modules"
VIEWER_PORT = 8129

# Gate parameters (v1). The frame budget is generous on purpose: headless
# Chromium renders WebGL in software (SwiftShader), so frame time here
# measures the Thor's CPU raster path, not a GPU budget.
FRAME_P95_MAX_MS = 250.0
MAX_RETRIES = 2
DECIMATE_MAX_TRIS = 20000

# Findings the generator knows how to repair, and the findings it does not.
REPAIRABLE = {
    "floating_object",
    "blocked_door",
    "prop_unreachable",
    "scale_bounds",
}


def ensure_dirs() -> None:
    for d in (ARTIFACTS, INBOX, OUTBOX, RESULTS):
        d.mkdir(parents=True, exist_ok=True)


def box_state() -> dict:
    """Load average and available memory, the two numbers reports quote."""
    load = open("/proc/loadavg").read().split()
    mem = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        mem[k] = int(v.strip().split()[0])
    return {
        "load1": float(load[0]),
        "load15": float(load[2]),
        "mem_available_gb": round(mem.get("MemAvailable", 0) / 1e6, 1),
    }


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(LEDGER)
    conn.execute(
        """create table if not exists events (
               at text not null,
               room text not null,
               attempt integer not null,
               stage text not null,
               status text not null,
               ms real,
               detail text
           )"""
    )
    return conn


def event(
    room: str,
    attempt: int,
    stage: str,
    status: str,
    ms: float | None = None,
    detail: dict | None = None,
) -> None:
    conn = connect()
    conn.execute(
        "insert into events values (?,?,?,?,?,?,?)",
        (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            room,
            attempt,
            stage,
            status,
            ms,
            json.dumps(detail or {}, sort_keys=True),
        ),
    )
    conn.commit()
    conn.close()


def admit(tier: str, peak: str, label: str, cmd: list[str]) -> list[str]:
    """Wrap a command in a thor-admit lease. Tiers: this lane is measurement,
    so ``study`` unless a live preview is being baked."""
    return [THOR_ADMIT, "run", "--tier", tier, "--peak", peak, "--label", label, "--"] + cmd


def run_leased(tier: str, peak: str, label: str, cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        admit(tier, peak, label, cmd), capture_output=True, text=True, check=False
    )


def viewer_alive() -> bool:
    """Is the hot-load viewer already listening on the lane's port?"""
    proc = subprocess.run(
        ["ss", "-ltn", f"sport = :{VIEWER_PORT}"], capture_output=True, text=True, check=False
    )
    return str(VIEWER_PORT) in proc.stdout
