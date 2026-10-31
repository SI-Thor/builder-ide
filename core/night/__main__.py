"""The seat's command line: write a morning's report page.

    python -m core.night --scenario clean --out reports/
    python -m core.night --list

The report is a static page over the ledger, so the only thing this has to do
is fold a simulated night and write the page, its JSON and its text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.night.nights import (
    SimulatedNight,
    all_mornings,
    clean_night,
    degraded_night,
    did_not_run_night,
    failures_night,
    iteration_night,
    iteration_rail_cut_night,
    iteration_stalled_night,
    rail_cut_night,
    reboot_night,
)
from core.night.report import write_report

__all__ = ["main", "SCENARIOS"]

SCENARIOS = {
    "clean": clean_night,
    "failures": failures_night,
    "rail-cut": rail_cut_night,
    "reboot": reboot_night,
    "degraded": degraded_night,
    "did-not-run": did_not_run_night,
    "iteration": iteration_night,
    "iteration-rail-cut": iteration_rail_cut_night,
    "iteration-stalled": iteration_stalled_night,
}


def _scenario(name: str) -> SimulatedNight:
    if name == "did-not-run":
        return did_not_run_night("off")
    return SCENARIOS[name]()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="core.night", description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="clean",
        help="which simulated night to write",
    )
    parser.add_argument(
        "--out",
        default="reports",
        help="the directory the report is written to",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the simulated nights and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        for night in all_mornings():
            print(f"{night.name}\t{night.report.status.first_line}")
        return 0

    night = _scenario(args.scenario)
    path = write_report(night.report, Path(args.out))
    print(f"{night.report.status.first_line}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
