"""Time the glTF conversion properly: three runs, per-asset median.

One run of the batch is a timing of the machine as well as of the
converter, and the Thor is shared: model servers and an Infinigen render
were running during the first pass, and the same assets came out 40 % slower
on a later pass. So the converter is run three times and the **median**
per asset is reported, which is the number that does not depend on which
minute it ran.

The output is one JSON file: the per-asset medians, the totals, and the
run-to-run spread.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simready_loader import asset_dirs, convert_asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="the directory holding the packages")
    parser.add_argument("--outdir", required=True, help="where to write the GLBs")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", required=True, help="where to write the timings")
    args = parser.parse_args()

    assets = asset_dirs(args.root)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, dict]] = []
    for index in range(args.runs):
        row: dict[str, dict] = {}
        for asset in assets:
            stats = convert_asset(asset, outdir / f"{asset.name}.glb")
            row[asset.name] = {
                "seconds": stats.seconds,
                "triangles": stats.triangles,
                "glb_bytes": stats.glb_bytes,
            }
        runs.append(row)
        total = sum(v["seconds"] for v in row.values())
        print(f"run {index + 1}/{args.runs}: {total:.2f}s total", flush=True)

    medians = []
    for asset in assets:
        times = [run[asset.name]["seconds"] for run in runs]
        medians.append(
            {
                "asset": asset.name,
                "seconds_median": statistics.median(times),
                "seconds_min": min(times),
                "seconds_max": max(times),
                "triangles": runs[0][asset.name]["triangles"],
                "glb_bytes": runs[0][asset.name]["glb_bytes"],
            }
        )
    medians.sort(key=lambda row: -row["seconds_median"])

    summary = {
        "runs": args.runs,
        "assets": len(medians),
        "total_seconds_median_of_runs": [
            round(sum(run[asset.name]["seconds"] for asset in assets), 2)
            for run in runs
        ],
        "total_seconds_median": round(
            sum(row["seconds_median"] for row in medians), 2
        ),
        "per_asset_median_seconds": round(
            statistics.median(row["seconds_median"] for row in medians), 3
        ),
        "slowest": medians[0],
        "fastest": medians[-1],
        "triangles_total": sum(row["triangles"] for row in medians),
        "glb_bytes_total": sum(row["glb_bytes"] for row in medians),
        "assets": medians,
    }
    Path(args.json).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "assets"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
