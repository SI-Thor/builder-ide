"""The honest week on the **real engine** — the headless driver (plan item 14).

    .venv/bin/python tests/acceptance/week/realweek.py     # or:
    .venv/bin/python -m pytest tests/acceptance/week -m engine -q

The same seven nights `meltweek` plays, with the engine seam pointed at
the **v2 venv on this box** (`BUILDER_V2_HOME`, default `~/lm-wt/v2-thor`,
read-only): every render rung — the world bet's render and the landed
work order's preview — is Infinigen 2.0 + procfunc through Cycles on the
Thor's GPU, at rung 2 of the ladder (960×540, 16 spp; seconds a render,
minutes the week). The session performs the **explicit pin edit** first
(X R9), exactly as M1's real-engine run does — the week reuses M1's boot.

What this driver adds over the fake week's:

* **the budget, from the cost model** (`weekbudget`) — each night's plan
  (the bet render, the preview, the critic's verdict) priced from the
  measured bands at p95, the admission check against the night's rails,
  and the owner's two lines per evening;
* **the measured fold** — every render's wall and bytes from the ledger,
  the preview's measured wall, the verdict write's measured cost, beside
  the estimate each night was budgeted against;
* **the box's state beside every table** (the standing rule): load, GPU,
  and the whole-box `VIN` rail — a shared box, so the power reading is an
  upper bound on the week's energy, labelled as such.

Without the venv the run refuses, naming the missing piece — the
fake-engine week (`meltweek.py`) is the default suite and stays green.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_M1 = _HERE.parent / "m1"
for _p in (str(_M1), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from meltweek import build_week_world, play_week, teardown_week_world  # noqa: E402
from seats.engine import DEFAULT_V2_HOME, real_engine_spec  # noqa: E402
from session import Session, StepFailure  # noqa: E402

import weekbudget  # noqa: E402
from script import NIGHTS  # noqa: E402

#: The whole-box input rail (the lab's own mapping, `docs/lab/lab3-scripts/
#: boxstate.py` §INA: hwmon4 is the ina238 labelled VIN, power1_input in µW).
_VIN_POWER = "/sys/class/hwmon/hwmon4/power1_input"


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def box_state() -> str:
    """The standing rule: load, GPU and the whole-box rail, beside the
    numbers. Best effort — a missing tool is named, never guessed."""
    parts = []
    for argv in (["uptime"],
                 ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
                  "--format=csv,noheader"]):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                parts.append(out.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    vin = _read(_VIN_POWER)
    if vin is not None:
        parts.append(f"VIN rail {float(vin) / 1e6:.1f} W (whole box, shared)")
    else:
        parts.append("VIN rail unavailable")
    return " | ".join(parts)


def run_week(home: Path, run_dir: Path, v2_home: Path) -> tuple[Session, object, dict]:
    """Play the week on the real engine; returns (session, world, facts).

    `facts` carries what the record needs: the box states, the run's wall,
    the budget table, the engine's own description — collected whether the
    week finished or failed at a step (a failed run still gets its record).
    """
    os.environ["BUILDER_ENGINE"] = json.dumps(
        real_engine_spec(home, v2_home=v2_home))
    t0 = time.perf_counter()
    world = build_week_world(home, run_dir)
    facts: dict = {"box_state_start": box_state()}
    ses = Session(world)
    try:
        try:
            play_week(world, ses)
        except StepFailure as failure:
            facts["failure"] = str(failure)
    finally:
        facts["run_wall_s"] = time.perf_counter() - t0
        facts["box_state_end"] = box_state()
        engine = world.engine.engine.describe()
        facts["engine"] = {
            "flavour": engine.flavour, "source": engine.source,
            "pin": engine.pin.model_dump(mode="json"),
        }
        facts["budget"] = weekbudget.render_budget_table(
            world, ses.steps, NIGHTS)
        world.artifacts["facts"] = facts
        world.artifacts["session"] = ses
    return ses, world, facts


def write_record(run_dir: Path, ses: Session, world, facts: dict) -> str:
    """The run's whole record: the step table, the melt table, the budget
    table, the box states — one file, `run/engine/week.txt`."""
    parts = [
        ses.table(),
        world.week.get("table", ""),
        facts["budget"],
        "",
        f"engine: {facts['engine']['source']}",
        f"box state at the start: {facts['box_state_start']}",
        f"box state at the end:   {facts['box_state_end']}",
        f"the week's wall: {facts['run_wall_s'] / 60:.1f} min of the "
        f"{weekbudget.WEEK_WALL_BUDGET_MIN:.0f}-min budget",
    ]
    if facts.get("failure"):
        parts.append(f"FAILED: {facts['failure']}")
    out = "\n\n".join(parts)
    (run_dir / "week.txt").write_text(out + "\n", encoding="utf-8")
    return out


def main() -> int:
    v2_home = Path(
        os.environ.get("BUILDER_V2_HOME", str(DEFAULT_V2_HOME))).expanduser()
    if not (v2_home / ".venv" / "bin" / "python").is_file():
        print(f"the v2 venv is not at {v2_home} (set BUILDER_V2_HOME to point "
              "elsewhere); the real week has no engine to render with — the "
              "fake-engine week is the default suite")
        return 2
    run_dir = _HERE / "run" / "engine"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="real-week-home-") as tmp:
        home = Path(tmp) / "builder-ide"
        ses, world, facts = run_week(home, run_dir, v2_home)
        try:
            out = write_record(run_dir, ses, world, facts)
            print(out)
            ok = sum(1 for s in ses.steps if s.ok)
            print(f"\nThe honest week on the real engine: {len(ses.steps)} "
                  f"steps, {ok}/{len(ses.steps)} passed.")
            return 0 if ok == len(ses.steps) and not facts.get("failure") else 1
        finally:
            teardown_week_world(world)
            os.environ.pop("BUILDER_ENGINE", None)


if __name__ == "__main__":
    raise SystemExit(main())
