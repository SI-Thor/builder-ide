"""Print the alarms the shipped detector raises, for the lab note.

    python3 tools/drift/pauses.py --dataset docs/lab/drift-dataset/dataset.json \\
        --labels docs/lab/drift-dataset/labels.json --out docs/lab/drift-dataset/pauses.json

It reads the calibration report for the shipped thresholds, runs the
detector with them, and writes every alarm with the reason a human
would read. It is the "what would pause the world, and when" list.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.drift.config import DriftConfig, GateSpec  # noqa: E402
from core.drift.detect import DriftDetector  # noqa: E402
from core.drift.gate import RATE  # noqa: E402
from core.drift.ledger import series_from_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="docs/lab/drift-dataset/dataset.json")
    parser.add_argument("--labels", default="docs/lab/drift-dataset/labels.json")
    parser.add_argument("--calibration", default="docs/lab/drift-dataset/calibration.json")
    parser.add_argument("--out", default="docs/lab/drift-dataset/pauses.json")
    parser.add_argument("--mode", default=RATE)
    args = parser.parse_args(argv)

    document = json.loads(Path(args.dataset).read_text())
    series = series_from_dataset(document)
    calibration = json.loads(Path(args.calibration).read_text())
    config = DriftConfig()
    bucket_seconds = series.bucket_seconds

    first_bucket = int(series.start // bucket_seconds)
    last_bucket = int((series.end - 1) // bucket_seconds)
    split_index = first_bucket + (last_bucket - first_bucket) // 2
    split_at = split_index * bucket_seconds
    reference = (series.reference_start, split_at)

    thresholds = calibration["combined"][args.mode]["thresholds"]
    tuned = config
    for signal, point in thresholds.items():
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
    detection = DriftDetector(tuned, mode=args.mode).run(series, reference=reference)

    rows = []
    for alarm in detection.alarms:
        rows.append(
            {
                "at": alarm.at,
                "iso": datetime.fromtimestamp(alarm.at, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "signal": alarm.signal,
                "agent": alarm.agent,
                "level": alarm.level,
                "value": alarm.value,
                "fed": alarm.fed,
                "reason": alarm.reason,
            }
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "meta": {
                    "mode": args.mode,
                    "thresholds": thresholds,
                    "generated_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "alarms": len(rows),
                    "hours": round(series.hours, 3),
                },
                "alarms": rows,
            },
            indent=1,
        )
    )
    for row in rows:
        print(
            f"{row['iso']}  {row['level']:5s} {row['signal']:8s} "
            f"{row['agent'] or 'world':8s} {row['reason']}"
        )
    print()
    print(f"{len(rows)} alarms over {series.hours:.2f} h "
          f"= {len(rows) / series.hours:.2f} per hour")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
