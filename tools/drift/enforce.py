"""Apply the drift detector's pause decision — dry-run by default.

This is §3.5's ladder with a hand on it: the detector's alarm state at
one window becomes a pause-file entry (the world reads it at its
admission seam and yields politely) and, for the actors the label map
names, a one-tier demotion of their thor-admit presence entries (and,
at the hard level, no new proposals). No process is killed; a
demotion changes what starts next.

    python3 tools/drift/enforce.py --at 2026-11-01T19:45:00Z
    python3 tools/drift/enforce.py --enforce
    python3 tools/drift/enforce.py --clear world --enforce

Without ``--at`` the last window of the dataset is used. Without
``--enforce`` nothing is written: every line is prefixed ``dry-run:``.
The default dataset is the backfilled snapshot of build #3; pass
``--ledger`` to run against the live world instead (the detector's
yields come from the ledger's own ``drift.yield`` events once the
world writes them).

The label map defaults to ``world=agent-world`` — which matches no
presence entry today (the world's services run outside the lease
system), so the thor-admit door reports "nothing to demote" until the
world's work is registered under thor-admit. Pass ``--map actor=prefix``
to name the labels of the seats you want demoted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.drift.config import DriftConfig, GateSpec  # noqa: E402
from core.drift.detect import DriftDetector  # noqa: E402
from core.drift.gate import RATE  # noqa: E402
from core.drift.ledger import build_series, series_from_dataset  # noqa: E402
from core.drift.pause import PauseFile, apply, clear, plan_from_state  # noqa: E402
from core.drift.ledger import parse_at  # noqa: E402

#: Where the world reads its pauses (service.py::PAUSE_FILE's default).
DEFAULT_PAUSE_FILE = "~/lm-wt/agent-world/runtime/drift-pause.json"

#: Where thor-admit keeps the presence queue.
DEFAULT_PRESENCE = "~/.local/state/thor-admit/presence.json"

DEFAULT_MAP = {"world": "agent-world"}


def tuned_from_calibration(calibration: dict, mode: str = RATE) -> DriftConfig:
    """The shipped operating point: the calibration's chosen thresholds
    on the default config.

    The same eight lines live in ``pauses.py``; they are kept beside
    their user rather than shared through an import, because a tool
    that can be read from its own file is a tool that can be checked
    against its note.
    """
    tuned = DriftConfig()
    for signal, point in calibration["combined"][mode]["thresholds"].items():
        gate = tuned.gate_for(signal)
        tuned = tuned.with_thresholds(
            **{
                signal: GateSpec(
                    enter=point["enter"],
                    exit=point["enter"] * 0.6,
                    level_exit=point.get("level_exit", 0.0),
                    dwell_up=gate.dwell_up,
                    dwell_down=gate.dwell_down,
                )
            }
        )
    return tuned


#: The daemon's CLI on this box. ``thor-admit`` is not on the PATH; the
#: canonical binary is in ~/lm-tools, and a name that is not found is
#: a reload that did not happen, not a crash.
RELOAD_COMMAND = ["~/lm-tools/thor-admit", "reload"]


def _reload() -> bool:
    """Ask thor-admit to re-read its presence file (SIGHUP's CLI face)."""
    command = [Path(c).expanduser().as_posix() if c.startswith("~") else c for c in RELOAD_COMMAND]
    try:
        result = subprocess.run(command, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dataset", default="docs/lab/drift-pause-dataset/dataset.json")
    source.add_argument("--ledger", default=None, help="the live world ledger instead")
    parser.add_argument("--calibration", default="docs/lab/drift-pause-dataset/calibration.json")
    parser.add_argument("--mode", default=RATE)
    parser.add_argument(
        "--at",
        default=None,
        help="the window to act on, ISO (default: the dataset's last window)",
    )
    parser.add_argument("--enforce", action="store_true", help="write; default is dry-run")
    parser.add_argument("--ttl-mins", type=float, default=30.0, help="a pause's lifetime")
    parser.add_argument("--pause-file", default=DEFAULT_PAUSE_FILE)
    parser.add_argument("--presence-file", default=DEFAULT_PRESENCE)
    parser.add_argument("--map", action="append", default=[], metavar="ACTOR=PREFIX")
    parser.add_argument("--clear", action="append", default=[], metavar="ACTOR")
    parser.add_argument("--no-reload", action="store_true")
    parser.add_argument("--reload-cmd", default="thor-admit reload")
    args = parser.parse_args(argv)

    pause_file = PauseFile(Path(args.pause_file).expanduser())
    presence_path = Path(args.presence_file).expanduser()
    label_map = dict(DEFAULT_MAP)
    for mapping in args.map:
        actor, _, prefix = mapping.partition("=")
        label_map[actor.strip()] = prefix.strip()

    reload = None if args.no_reload else _reload
    if args.reload_cmd != "thor-admit reload":
        command = args.reload_cmd.split()
        reload = lambda: subprocess.run(command, capture_output=True, timeout=10).returncode == 0  # noqa: E731

    lines: list[str] = []
    if args.clear:
        lines += clear(pause_file, args.clear, enforce=args.enforce)
        print("\n".join(lines))
        return 0

    calibration = json.loads(Path(args.calibration).read_text())
    if args.ledger:
        series = build_series(Path(args.ledger).expanduser())
    else:
        series = series_from_dataset(json.loads(Path(args.dataset).read_text()))
    if not series.buckets:
        print("the dataset is empty; nothing to act on")
        return 1

    tuned = tuned_from_calibration(calibration, args.mode)
    detector = DriftDetector(tuned, mode=args.mode)
    detection = detector.run(series)

    bucket = series.bucket_seconds
    if args.at:
        at = parse_at(args.at)
        window = int(at // bucket) * bucket
        if not series.start <= window < series.end:
            print(f"--at {args.at} is outside the dataset's span")
            return 1
    else:
        window = series.buckets[-1].start

    plan = plan_from_state(
        detection,
        window,
        config=tuned,
        ttl_seconds=args.ttl_mins * 60.0,
        label_map=label_map,
    )
    lines += apply(
        plan,
        pause_file=pause_file,
        presence_path=presence_path,
        reload=reload,
        enforce=args.enforce,
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
