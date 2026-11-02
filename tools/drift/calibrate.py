"""Calibrate the drift detector on the world's ledger, and compare a rate
gate against a level gate.

## The protocol

The ground truth is a set of labelled **drift episodes** — contiguous
runs of windows in which something was known to be wrong — and the
thresholds have to be chosen without seeing the episode they are scored
on. The run is cut into halves by time and the labelled episodes are
split with it, and each episode is then held out in turn.

1. **Split.** The run is cut in half by time: the first half is the
   **calibration** half, the second is the **holdout** half. The
   thresholds are chosen on the episodes that fall entirely in the
   calibration half, and the holdout half's episodes are scored with
   them. The holdout does not leak into the choice.
2. **Leave-one-out.** Because the drift events on this world are
   *clustered* — a box reboot takes out the hang, the wedge and the
   judge's absence together — a single time split leaves the
   calibration half with one drift episode. So each labelled episode is
   also held out in turn: the threshold is chosen on the other
   episodes and the held-out one is scored. That is the generalisation
   estimate, and it has one row per episode.
3. **Choose.** The threshold with the most held-out episodes detected
   wins, **subject to the pause budget**: the world may be in alarm
   for at most a tenth of its windows without anything being wrong.
   A gate that is permanently on is not worse on recall; it is worse
   on *time*, and time is what a pause costs.
4. **Score.** Precision, recall, false alarms, the onset latency and
   the alarm rate per hour of world.
5. **Compare.** At matched recall, the level gate and the rate gate are
   compared on fires and false alarms — the measurement
   ``docs/lab/exp-syzygy-keyframes.md`` §5.9 made on another stream,
   and the bar this build is held to.

**How a detector is scored.** The detector is a *state*: once a gate is
in alarm it stays in alarm until the signal clears. So the unit that
matters is the **alarm episode** — a contiguous run of windows in
alarm — and not the raw count of transitions. The numbers reported are:

* **recall** — the fraction of labelled drift episodes the detector's
  alarm covered. This is the syzygy recall: over events, not frames.
* **false alarm episodes** — the detector's alarm runs that touch no
  labelled episode.
* **false alarm windows** — the alarm windows that are not in a
  labelled episode. This is what the world actually pays.
* **onset latency** — the median number of windows between the start
  of an episode and the start of the alarm that covered it.

Ground truth comes from ``labels.json``: the world's clients' own
failure reports and the written incident records. Nothing in it comes
from the ledger the detector reads.

Run it:

    python3 tools/drift/calibrate.py --dataset docs/lab/drift-dataset/dataset.json \\
        --labels docs/lab/drift-dataset/labels.json --out docs/lab/drift-dataset/calibration.json

It takes under a minute and writes the report as JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.drift.config import DriftConfig, GateSpec  # noqa: E402
from core.drift.detect import DriftDetector  # noqa: E402
from core.drift.gate import HYBRID, LEVEL, RATE  # noqa: E402
from core.drift.ledger import series_from_dataset  # noqa: E402
from core.drift.signals import build_signals  # noqa: E402

#: The threshold grids, per signal. Each grid is in the units of that
#: signal's value, and each is wide enough to contain both a working
#: operating point and a useless one.
GRIDS: dict[str, dict[str, list[float]]] = {
    "stall": {
        RATE: [0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0, 100.0, 300.0],
        LEVEL: [1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 40.0, 100.0, 400.0],
    },
    "success": {
        RATE: [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4],
        LEVEL: [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4],
    },
    "errors": {
        RATE: [0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 0.95],
        LEVEL: [0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 0.95],
    },
    "spend": {
        RATE: [0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
        LEVEL: [1.05, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0, 50.0],
    },
}

#: The label classes that count as "the world was off track". The
#: designed yields are **not** in this set: the world yielding the box
#: when memory is low is the world behaving correctly.
POSITIVE_CLASSES = (
    "client_failure",
    "write_path_failure",
    "incident_hang",
    "incident_wedge",
    "incident_judge",
    "incident_judge_startup",
)

#: The classes reported on their own, so a signal that is circular
#: against one of them can be seen to be circular.
CLASSES = POSITIVE_CLASSES + ("designed_yield",)


def grid_for(signal: str, mode: str) -> list[dict]:
    """The thresholds to try, for one signal and one gate mode.

    The rate and level modes have one threshold each. The hybrid mode
    has two: the rate at which the alarm fires, and the level at which
    it lets go. Its grid is the product of the other two grids.
    """
    if mode == HYBRID:
        return [
            {"enter": rate, "level_exit": level}
            for rate in GRIDS[signal][RATE]
            for level in GRIDS[signal][LEVEL]
        ]
    return [{"enter": threshold, "level_exit": 0.0} for threshold in GRIDS[signal][mode]]


def spec_for(mode: str, spec: dict, dwell_up: float, dwell_down: float) -> GateSpec:
    """The gate spec for one mode and one grid point."""
    if mode == HYBRID:
        return GateSpec(
            enter=spec["enter"],
            exit=spec["enter"] * 0.6,
            level_exit=spec["level_exit"],
            dwell_up=dwell_up,
            dwell_down=dwell_down,
        )
    return GateSpec(
        enter=spec["enter"],
        exit=spec["enter"] * 0.6,
        dwell_up=dwell_up,
        dwell_down=dwell_down,
    )


def fmt_threshold(point: dict) -> str:
    """A grid point, as one short string."""
    if point.get("level_exit"):
        return f"r{point['enter']:g}/l{point['level_exit']:g}"
    return f"{point['enter']:g}"


def iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def runs(indices: Iterable[int]) -> list[tuple[int, int]]:
    """The contiguous runs of a sorted set of integers."""
    out: list[tuple[int, int]] = []
    for index in sorted(set(indices)):
        if out and index == out[-1][1] + 1:
            out[-1] = (out[-1][0], index)
        else:
            out.append((index, index))
    return out


def positive_windows(
    labels: Iterable[dict],
    bucket_seconds: int,
    overall_classes: tuple[str, ...] = POSITIVE_CLASSES,
) -> tuple[set[int], dict[str, set[int]]]:
    """The bucket indices that carry a label, overall and per class.

    A label with an ``until`` is a window, and every bucket of it is
    positive. The per-class map covers every class, including the
    negative control, so that the control can be scored separately.
    """
    overall: set[int] = set()
    per_class: dict[str, set[int]] = {name: set() for name in CLASSES}
    for label in labels:
        kind = label.get("kind")
        if kind not in CLASSES:
            continue
        start = int(float(label["at"]) // bucket_seconds)
        end = label.get("until")
        last = int(float(end) // bucket_seconds) if end else start
        indices = set(range(start, last + 1))
        per_class.setdefault(kind, set()).update(indices)
        if kind in overall_classes:
            overall |= indices
    return overall, per_class


def covers(alarm: set[int], episode: tuple[int, int], tolerance: int) -> bool:
    """Does the alarm touch the episode?"""
    low, high = episode
    return any(low - tolerance <= index <= high + tolerance for index in alarm)


def score(
    alarm_indices: set[int],
    fire_indices: set[int],
    positives: set[int],
    episodes: list[tuple[int, int]],
    tolerance: int = 1,
) -> dict[str, float]:
    """Score a detector's alarm state against the labelled windows."""
    alarm = set(alarm_indices)
    detector_episodes = runs(alarm)
    detected = [k for k, episode in enumerate(episodes) if covers(alarm, episode, tolerance)]
    false_episodes = sum(
        1
        for low, high in detector_episodes
        if not any(
            not (high < p_low - tolerance or low > p_high + tolerance)
            for p_low, p_high in episodes
        )
    )
    covered_windows = alarm & positives
    recall = len(detected) / len(episodes) if episodes else 0.0
    precision = (
        (len(detector_episodes) - false_episodes) / len(detector_episodes)
        if detector_episodes
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    latencies = []
    for k in detected:
        low, high = episodes[k]
        touching = [index for index in sorted(alarm) if low - tolerance <= index <= high + tolerance]
        if touching:
            latencies.append(touching[0] - low)
    return {
        "episodes": len(detector_episodes),
        "false_alarm_episodes": false_episodes,
        "true_alarm_episodes": len(detector_episodes) - false_episodes,
        "fires": len(fire_indices),
        "alarm_windows": len(alarm),
        "false_alarm_windows": len(alarm) - len(covered_windows),
        "covered_positive_windows": len(covered_windows),
        "positive_windows": len(positives),
        "positive_episodes": len(episodes),
        "detected_episodes": len(detected),
        "detected": detected,
        "onset_latency_windows": (
            sorted(latencies)[len(latencies) // 2] if latencies else None
        ),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run_detector(
    series,
    signal: str,
    mode: str,
    point: dict,
    reference: tuple[float, float],
    config: DriftConfig,
) -> tuple[set[int], set[int]]:
    """The alarm windows and the fires of one signal, one mode, one point."""
    gate = config.gate_for(signal)
    spec = spec_for(mode, point, gate.dwell_up, gate.dwell_down)
    tuned = config.with_thresholds(**{signal: spec})
    detection = DriftDetector(tuned, mode=mode).run(series, reference=reference)
    bucket_seconds = series.bucket_seconds
    alarm_indices = {
        int(at // bucket_seconds)
        for at, pairs in detection.alarm_windows.items()
        if any(pair[0] == signal for pair in pairs)
    }
    fire_indices = {
        int(alarm.at // bucket_seconds)
        for alarm in detection.alarms
        if alarm.signal == signal
    }
    return alarm_indices, fire_indices


def sweep(
    series,
    signal: str,
    mode: str,
    positives: set[int],
    episodes: list[tuple[int, int]],
    reference: tuple[float, float],
    config: DriftConfig,
    tolerance: int,
) -> list[dict]:
    """Every threshold on the grid, with its alarm state and its score."""
    rows: list[dict] = []
    for point in grid_for(signal, mode):
        alarm_indices, fire_indices = run_detector(
            series, signal, mode, point, reference, config
        )
        row = {
            "threshold": point,
            "_alarm": alarm_indices,
            "_fires": fire_indices,
        }
        row.update(
            score(alarm_indices, fire_indices, positives, episodes, tolerance)
        )
        rows.append(row)
    return rows


def choose(rows: list[dict], budget_windows: int, episodes: Iterable[int] = ()) -> dict:
    """The operating point to ship, for a set of episodes.

    The rule, in order:

    1. **Stay inside the pause budget.** A threshold whose
       false-alarm windows exceed ``budget_windows`` is not eligible:
       the world may be in alarm for that many windows without
       anything being wrong, and no more. This is what rules out a
       gate that is permanently on — such a gate is not worse on
       recall, it is worse on *time*, and time is what a pause costs.
    2. Among the eligible thresholds, the **most episodes detected**
       wins.
    3. Ties go to the fewest false-alarm windows, then the fewest
       fires, then the highest threshold: the most conservative
       choice.
    """
    wanted = set(episodes)
    if not wanted:
        wanted = set(range(rows[0]["positive_episodes"]))
    affordable = [row for row in rows if row["false_alarm_windows"] <= budget_windows]
    pool = affordable or rows
    best = max(
        len(wanted & set(row["detected"])) for row in pool
    )
    candidates = [
        row for row in pool if len(wanted & set(row["detected"])) >= best
    ]
    return min(
        candidates,
        key=lambda row: (
            row["false_alarm_windows"],
            row["episodes"],
            -row["threshold"]["enter"],
            -row["threshold"]["level_exit"],
        ),
    )


def signal_stats(series, reference: tuple[float, float], config: DriftConfig) -> dict:
    """What each signal's values look like, so the grids are not guesses."""
    stats: dict[str, dict] = {}
    for signal in build_signals():
        points = signal.compute(series, config, reference)
        values = [p.value for p in points if p.value is not None]
        finite = [v for v in values if math.isfinite(v)]
        changes = [
            abs(b - a)
            for a, b in zip(values, values[1:])
            if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)
        ]
        ordered = sorted(finite)
        ordered_changes = sorted(changes)
        stats[signal.name] = {
            "computable": signal.computable,
            "reason": signal.reason,
            "points": len(points),
            "defined": len(values),
            "min": ordered[0] if ordered else None,
            "median": ordered[len(ordered) // 2] if ordered else None,
            "p90": ordered[int(len(ordered) * 0.9)] if ordered else None,
            "max": ordered[-1] if ordered else None,
            "infinite": len(values) - len(finite),
            "median_change": (
                ordered_changes[len(ordered_changes) // 2] if ordered_changes else None
            ),
            "p90_change": (
                ordered_changes[int(len(ordered_changes) * 0.9)]
                if ordered_changes
                else None
            ),
            "max_change": ordered_changes[-1] if ordered_changes else None,
        }
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="docs/lab/drift-dataset/dataset.json")
    parser.add_argument("--labels", default="docs/lab/drift-dataset/labels.json")
    parser.add_argument("--out", default="docs/lab/drift-dataset/calibration.json")
    parser.add_argument("--tolerance", type=int, default=1)
    parser.add_argument(
        "--pause-budget",
        type=float,
        default=0.10,
        help="the share of the world's windows that may be in alarm without a "
        "label; the operating point must stay inside it",
    )
    parser.add_argument("--min-scored-plays", type=int, default=None)
    parser.add_argument("--stall-lookback", type=int, default=None)
    parser.add_argument("--signal-lookback", type=int, default=None)
    parser.add_argument("--dwell-down", type=float, default=None)
    args = parser.parse_args(argv)

    document = json.loads(Path(args.dataset).read_text())
    meta = document.get("meta") or {}
    label_document = json.loads(Path(args.labels).read_text())
    labels = label_document.get("labels") or []
    label_meta = label_document.get("meta") or {}
    series = series_from_dataset(document)
    config = DriftConfig()
    if args.min_scored_plays is not None:
        config = config.with_thresholds(min_scored_plays=args.min_scored_plays)
    if args.stall_lookback is not None:
        config = config.with_thresholds(stall_lookback_buckets=args.stall_lookback)
    if args.signal_lookback is not None:
        config = config.with_thresholds(signal_lookback_buckets=args.signal_lookback)
    if args.dwell_down is not None:
        for name in ("stall", "success", "errors", "spend"):
            spec = config.gate_for(name)
            config = config.with_thresholds(
                **{name: GateSpec(spec.enter, spec.exit, spec.dwell_up, args.dwell_down)}
            )
    bucket_seconds = series.bucket_seconds

    first_bucket = int(series.start // bucket_seconds)
    last_bucket = int((series.end - 1) // bucket_seconds)
    split_index = first_bucket + (last_bucket - first_bucket) // 2
    split_at = split_index * bucket_seconds
    reference = (series.reference_start, split_at)

    positives_all, per_class = positive_windows(labels, bucket_seconds)
    episodes = runs(positives_all)
    calibration_windows = split_index - first_bucket
    total_windows = last_bucket - first_bucket + 1
    budget_windows = int(args.pause_budget * total_windows)

    report: dict[str, object] = {
        "meta": meta,
        "label_meta": label_meta,
        "split": {
            "calibration": [iso(series.start), iso(split_at)],
            "holdout": [iso(split_at), iso(series.end)],
            "calibration_hours": round((split_at - series.start) / 3600.0, 3),
            "holdout_hours": round((series.end - split_at) / 3600.0, 3),
        },
        "labels": {
            "counts_by_kind": {
                kind: sum(1 for label in labels if label.get("kind") == kind)
                for kind in CLASSES
            },
            "positive_windows_total": len(positives_all),
            "positive_episodes": len(episodes),
            "episodes": [
                {
                    "index": k,
                    "from": iso(episodes[k][0] * bucket_seconds),
                    "to": iso(episodes[k][1] * bucket_seconds + bucket_seconds),
                    "windows": episodes[k][1] - episodes[k][0] + 1,
                    "in_calibration_half": episodes[k][0] < split_index,
                }
                for k in range(len(episodes))
            ],
        },
        "pause_budget": {
            "share": args.pause_budget,
            "calibration_windows": calibration_windows,
            "total_windows": total_windows,
            "allowed_false_alarm_windows": budget_windows,
        },
        "signal_stats": signal_stats(series, reference, config),
        "signals": {},
    }

    # -- the sweep, the leave-one-out, and the time split --------------------
    calibration_episodes = [k for k, ep in enumerate(episodes) if ep[0] < split_index]
    holdout_episodes = [k for k, ep in enumerate(episodes) if ep[0] >= split_index]

    for signal in GRIDS:
        entry: dict[str, object] = {}
        for mode in (RATE, LEVEL, HYBRID):
            rows = sweep(
                series, signal, mode, positives_all, episodes, reference, config, args.tolerance
            )
            # Leave-one-episode-out: the threshold is chosen on the
            # other episodes and the held-out one is scored.
            folds = []
            for k in range(len(episodes)):
                others = [i for i in range(len(episodes)) if i != k]
                # The held-out episode's own windows are removed from
                # the positive set, so the budget and the false-alarm
                # count are computed without them: the fold's
                # threshold never sees the episode it is scored on.
                held = set(range(episodes[k][0], episodes[k][1] + 1))
                without = positives_all - held
                fold_budget = int(
                    args.pause_budget * (total_windows - len(held))
                )
                fold_rows = []
                for row in rows:
                    copy = dict(row)
                    copy["false_alarm_windows"] = len(row["_alarm"] - without)
                    fold_rows.append(copy)
                chosen = choose(fold_rows, fold_budget, others)
                folds.append(
                    {
                        "held_out": k,
                        "threshold": chosen["threshold"],
                        "detected": k in chosen["detected"],
                        "false_alarm_windows": chosen["false_alarm_windows"],
                        "alarm_windows": chosen["alarm_windows"],
                        "fires": chosen["fires"],
                        "episodes": chosen["episodes"],
                    }
                )
            # The time split: thresholds from the calibration half's
            # episodes only, scored on the holdout half's episodes.
            time_split = choose(rows, budget_windows, calibration_episodes)
            entry[mode] = {
                "grid": [
                    {
                        k: v
                        for k, v in row.items()
                        if k not in ("_alarm", "_fires")
                    }
                    for row in rows
                ],
                "leave_one_out": {
                    "folds": folds,
                    "detected": sum(1 for fold in folds if fold["detected"]),
                    "of": len(folds),
                    "mean_false_alarm_windows": round(
                        sum(fold["false_alarm_windows"] for fold in folds) / len(folds), 3
                    )
                    if folds
                    else 0.0,
                    "mean_alarm_windows": round(
                        sum(fold["alarm_windows"] for fold in folds) / len(folds), 3
                    )
                    if folds
                    else 0.0,
                },
                "time_split": {
                    "threshold": time_split["threshold"],
                    "calibration_detected": sorted(
                        set(time_split["detected"]) & set(calibration_episodes)
                    ),
                    "holdout_detected": sorted(
                        set(time_split["detected"]) & set(holdout_episodes)
                    ),
                    "false_alarm_windows": time_split["false_alarm_windows"],
                    "alarm_windows": time_split["alarm_windows"],
                    "fires": time_split["fires"],
                },
                "shipped": {
                    "threshold": choose(rows, budget_windows)["threshold"],
                },
            }
        report["signals"][signal] = entry

    # -- the combined detector at the shipped thresholds ---------------------
    combined: dict[str, object] = {}
    for mode in (RATE, LEVEL, HYBRID):
        tuned = config
        for signal in GRIDS:
            point = report["signals"][signal][mode]["shipped"]["threshold"]
            gate = tuned.gate_for(signal)
            spec = spec_for(mode, point, gate.dwell_up, gate.dwell_down)
            tuned = tuned.with_thresholds(**{signal: spec})
        detection = DriftDetector(tuned, mode=mode).run(series, reference=reference)
        alarm_indices = {int(at // bucket_seconds) for at in detection.alarm_windows}
        fire_indices = {int(a.at // bucket_seconds) for a in detection.alarms}
        cal_alarm = {i for i in alarm_indices if i < split_index}
        cal_fire = {i for i in fire_indices if i < split_index}
        hold_alarm = {i for i in alarm_indices if i >= split_index}
        hold_fire = {i for i in fire_indices if i >= split_index}
        cal_episodes = [ep for ep in episodes if ep[0] < split_index]
        hold_episodes = [ep for ep in episodes if ep[0] >= split_index]
        combined[mode] = {
            "thresholds": {
                signal: report["signals"][signal][mode]["shipped"]["threshold"]
                for signal in GRIDS
            },
            "calibration": score(
                cal_alarm, cal_fire, positives_all & set(range(first_bucket, split_index)),
                cal_episodes, args.tolerance,
            ),
            "holdout": score(
                hold_alarm, hold_fire, positives_all & set(range(split_index, last_bucket + 1)),
                hold_episodes, args.tolerance,
            ),
            "alarms_total": len(detection.alarms),
            "alarms_by_level": {
                level: sum(1 for a in detection.alarms if a.level == level)
                for level in ("soft", "tier", "hard")
            },
            "alarms_by_signal": {
                signal: sum(1 for a in detection.alarms if a.signal == signal)
                for signal in GRIDS
            },
            "alarms_per_hour": round(
                len(detection.alarms) / series.hours if series.hours else 0.0, 4
            ),
            "holdout_alarms_per_hour": round(
                len([a for a in detection.alarms if a.at >= split_at])
                / ((series.end - split_at) / 3600.0)
                if series.end > split_at
                else 0.0,
                4,
            ),
            "alarm_windows_per_hour": round(
                len(alarm_indices) / series.hours if series.hours else 0.0, 4
            ),
        }
    report["combined"] = combined

    # Per-class scoring for the combined rate detector.
    tuned = config
    for signal in GRIDS:
        point = report["signals"][signal][RATE]["shipped"]["threshold"]
        gate = tuned.gate_for(signal)
        spec = spec_for(RATE, point, gate.dwell_up, gate.dwell_down)
        tuned = tuned.with_thresholds(**{signal: spec})
    detection = DriftDetector(tuned, mode=RATE).run(series, reference=reference)
    alarm_indices = {int(at // bucket_seconds) for at in detection.alarm_windows}
    fire_indices = {int(a.at // bucket_seconds) for a in detection.alarms}
    by_class: dict[str, dict] = {}
    for kind in CLASSES:
        windows = per_class.get(kind, set())
        by_class[kind] = score(
            alarm_indices,
            fire_indices,
            windows,
            runs(windows),
            args.tolerance,
        )
    report["by_class_rate_gate"] = by_class
    control = per_class.get("designed_yield", set())
    report["negative_control"] = {
        "designed_yield_windows": len(control),
        "alarmed_designed_yield_windows": len(control & alarm_indices),
        "designed_yield_alarm_rate": (
            round(len(control & alarm_indices) / len(control), 4) if control else 0.0
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))

    # -- the summary on the terminal -----------------------------------------
    print(f"run: {iso(series.start)} .. {iso(series.end)}  ({series.hours:.2f} h)")
    print(
        f"split: calibration {iso(series.start)} .. {iso(split_at)} | "
        f"holdout {iso(split_at)} .. {iso(series.end)}"
    )
    print(
        f"labelled drift episodes: {len(episodes)} "
        f"({len(calibration_episodes)} in the calibration half, "
        f"{len(holdout_episodes)} in the holdout half); "
        f"positive windows: {len(positives_all)}"
    )
    print(f"pause budget: {budget_windows} false-alarm windows on the calibration half")
    print()
    for signal in GRIDS:
        print(f"== {signal}")
        for mode in (RATE, LEVEL, HYBRID):
            entry = report["signals"][signal][mode]
            loo = entry["leave_one_out"]
            split = entry["time_split"]
            print(
                f"   {mode:6s} shipped tau={fmt_threshold(entry['shipped']['threshold'])} "
                f"LOEO: {loo['detected']}/{loo['of']} episodes, "
                f"mean fw={loo['mean_false_alarm_windows']:.1f} "
                f"mean aw={loo['mean_alarm_windows']:.1f} | "
                f"time split: tau={fmt_threshold(split['threshold'])} "
                f"cal={split['calibration_detected']} hold={split['holdout_detected']} "
                f"fw={split['false_alarm_windows']} aw={split['alarm_windows']}"
            )
    print()
    for mode in (RATE, LEVEL, HYBRID):
        entry = combined[mode]
        cal = entry["calibration"]
        hold = entry["holdout"]
        print(
            f"combined {mode:5s} thresholds={entry['thresholds']}"
        )
        print(
            f"    cal[ep={cal['positive_episodes']} det={cal['detected_episodes']} "
            f"aw={cal['alarm_windows']} fw={cal['false_alarm_windows']} "
            f"p={cal['precision']:.3f} r={cal['recall']:.3f} lat={cal['onset_latency_windows']}] "
            f"hold[ep={hold['positive_episodes']} det={hold['detected_episodes']} "
            f"aw={hold['alarm_windows']} fw={hold['false_alarm_windows']} "
            f"p={hold['precision']:.3f} r={hold['recall']:.3f} "
            f"lat={hold['onset_latency_windows']}]"
        )
        print(
            f"    alarms/h={entry['alarms_per_hour']} "
            f"holdout/h={entry['holdout_alarms_per_hour']} "
            f"alarm windows/h={entry['alarm_windows_per_hour']} "
            f"by level={entry['alarms_by_level']}"
        )
    print()
    print("per class (combined rate gate):")
    for kind, entry in by_class.items():
        print(
            f"   {kind:24s} windows={entry['positive_windows']:4d} "
            f"alarmed={entry['covered_positive_windows']:4d} "
            f"r={entry['recall']:.3f}"
        )
    control = report["negative_control"]
    print(
        f"negative control: {control['alarmed_designed_yield_windows']} of "
        f"{control['designed_yield_windows']} designed-yield windows alarmed "
        f"({control['designed_yield_alarm_rate']:.3f})"
    )
    print()
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
