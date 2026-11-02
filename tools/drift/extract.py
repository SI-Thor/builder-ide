"""Build the drift detector's dataset, and its ground truth, from the world.

Two things come out of here, and they are kept apart on purpose:

* ``dataset.json`` — the world's ledger, folded into five-minute
  windows. This is the detector's **input**. It comes from the ledger
  and nothing else.
* ``labels.json`` — the labelled drift events. This is the ground
  truth, and it comes from instruments **outside** the ledger: the
  bots' own log, and the two incident notes. If the labels came from
  the ledger, the measurement would be circular: the detector would be
  scored against the same rows it reads.

Run it:

    python3 tools/drift/extract.py --ledger ~/lm-wt/agent-world/runtime/world-ledger.sqlite3 \
        --bots ~/lm-wt/agent-world/runtime/logs/bots.jsonl --out docs/lab/drift-dataset

With ``--yields-from-bots`` the dataset is additionally folded with the
world's stand-asides reconstructed from the clients' decision log (see
``yields_from_bots``): the historical ledger carries no ``drift.yield``
events, and this is how the committed snapshot is re-folded as if it
had. Going forward the ledger's own events are read by
``build_series`` and the backfill is a stopgap.

It takes a few seconds and writes two JSON files. The ledger is opened
read-only and the world keeps running while it does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.drift.ledger import build_series, parse_at  # noqa: E402

#: Where the world lives on the Thor. Both are defaults, not requirements.
DEFAULT_LEDGER = "~/lm-wt/agent-world/runtime/world-ledger.sqlite3"
DEFAULT_BOTS = "~/lm-wt/agent-world/runtime/logs/bots.jsonl"

# -- the incident windows ----------------------------------------------------
#
# These two are **not** derived from the ledger. They come from two
# written records, and the derivation is spelled out so that it can be
# checked rather than believed.
#
# The box's timezone is AKST (UTC-9). ``journalctl --list-boots`` on
# the Thor prints AKST, and the incident note's boot id (ea0658fc) is
# the boot that ended at 10:49:53 AKST = 19:49:53Z. The note says the
# box dropped off the network at ~10:45 and came back at ~10:59, which
# is 19:45Z and 19:59Z. The world's ledger has a twenty-five minute
# hole over exactly that stretch, and the playtest note says "rebooted
# at ~20:00 UTC; the world came back at 20:06" — which is the same
# event, in UTC, from the other note.
INCIDENT_HANG = ("2026-11-01T19:40:00Z", "2026-11-01T20:06:00Z")

#: The playtest note (agent-world/docs/playtest-2026-11-01-reward.md)
#: records that the builders could not move — they were wedged against
#: cobble faces — and that "the last ledger win was 17:22Z". The note's
#: measured hour, 21:53Z–22:53Z, is after the fix. So the wedge ran
#: from the last win to the start of the measured hour.
INCIDENT_WEDGE = ("2026-11-01T17:22:00Z", "2026-11-01T21:53:00Z")

#: The same note, section 3: "the judge: unreachable, twice". The
#: world came back at 20:06Z and its own d1-2B was not up until
#: `ops/d1.sh start` brought it up; the note's measured hour reports
#: "1,828 calls, 0 failures". So the decision model was unreachable
#: from the world's return until then.
INCIDENT_JUDGE = ("2026-11-01T20:06:00Z", "2026-11-01T21:45:00Z")

#: The first of the judge's two absences: the world started at 05:37Z
#: and the decision model was not answering until 09:05Z (the ledger's
#: refusal rate leaves 1.0 at 09:05Z). The world played on priors.
INCIDENT_JUDGE_STARTUP = ("2026-11-01T06:25:00Z", "2026-11-01T09:05:00Z")

INCIDENTS = (
    ("incident_hang", INCIDENT_HANG, "docs/lab/incident-2026-11-01-jax-hang.md"),
    ("incident_wedge", INCIDENT_WEDGE, "agent-world/docs/playtest-2026-11-01-reward.md"),
    ("incident_judge", INCIDENT_JUDGE, "agent-world/docs/playtest-2026-11-01-reward.md"),
    (
        "incident_judge_startup",
        INCIDENT_JUDGE_STARTUP,
        "agent-world/docs/playtest-2026-11-01-reward.md",
    ),
)

#: The refusals that are **not** failures. The world's own admission
#: rule yields the box when memory is low, and the seat rule yields it
#: when another seat holds the lease. Both are the world behaving
#: correctly, and a detector that alarms on them is wrong. This is the
#: negative control.
YIELD_MARKERS = ("yielded:", "leased:")

#: The refusals that **are** failures: the world's own write path broke
#: (the ledger's id collided) or the reflex did not answer in time.
FAILURE_MARKERS = ("IntegrityError", "ProgrammingError", "did not answer in time")


@dataclass(frozen=True)
class Label:
    """One labelled event, with where the label came from.

    An incident is a **window**, not an instant: it carries ``until``,
    and every bucket it covers is a positive one.
    """

    at: float
    kind: str
    source: str
    detail: str
    until: float | None = None
    #: How many events of this kind happened in this window. The
    #: clients' failures are grouped by window so the file stays
    #: small; the count is kept so the report can say how many.
    count: int = 1

    def to_json(self) -> dict[str, object]:
        return {
            "at": self.at,
            "until": self.until,
            "count": self.count,
            "iso": datetime.fromtimestamp(self.at, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "kind": self.kind,
            "source": self.source,
            "detail": self.detail,
        }


def sha256_of(path: Path) -> str:
    """The hash of a file, so the dataset says what it was cut from."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def labels_from_bots(
    path: Path, bucket_seconds: int, until: float | None = None
) -> list[Label]:
    """The world's clients' own failure reports.

    ``bots.jsonl`` is written by the bots, not by the reflex and not by
    the judge, so it is an instrument outside the ledger.

    The events are **grouped by window**: eight thousand refusals in
    one hour are one label with a count, not eight thousand labels.
    The calibration only needs to know which windows were bad, and the
    file stays small enough to commit.
    """
    groups: dict[tuple[str, int], dict[str, object]] = {}
    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = record.get("kind")
            event = record.get("event")
            detail = str(record.get("detail") or "")
            at = record.get("at")
            if not at:
                continue
            stamp = parse_at(at)
            if until is not None and stamp >= until:
                continue
            label_kind: str | None = None
            if kind == "error":
                label_kind = "client_failure"
            elif kind == "note" and event in {
                "reflex_unreachable",
                "play_not_recorded",
                "kicked",
            }:
                label_kind = "client_failure"
                detail = f"{event}: {detail}"
            elif kind == "decision" and record.get("reason") == "refused":
                if any(marker in detail for marker in FAILURE_MARKERS):
                    label_kind = "write_path_failure"
                elif any(marker in detail for marker in YIELD_MARKERS):
                    label_kind = "designed_yield"
            if label_kind is None:
                continue
            bucket = int(stamp // bucket_seconds) * bucket_seconds
            key = (label_kind, bucket)
            group = groups.get(key)
            if group is None:
                group = {
                    "at": bucket,
                    "kind": label_kind,
                    "source": "bots.jsonl",
                    "detail": detail,
                    "count": 0,
                }
                groups[key] = group
            group["count"] = int(group["count"]) + 1
    return [
        Label(
            float(group["at"]),
            str(group["kind"]),
            str(group["source"]),
            str(group["detail"]),
            count=int(group["count"]),
        )
        for group in sorted(groups.values(), key=lambda g: (g["at"], g["kind"]))
    ]


def yields_from_bots(path: Path) -> list[dict[str, object]]:
    """The world's stand-asides, reconstructed from the clients' reports.

    This is the **backfill** for the ledger gap of build #2: the
    reflex began writing ``drift.yield`` in build #3, so the historical
    ledger carries none, and the clients' own decision log is the
    instrument that says the world yielded and when — the same records
    the ``designed_yield`` labels are cut from. Two consequences, said
    plainly:

    * on the backfilled dataset the negative control measures the
      **plumbing** — does an honoured yield stop the alarm — not an
      independent discovery, because the input and the label share a
      source;
    * the independent checks are the ones whose labels come from other
      instruments: the holdout recall and the false-alarm windows.

    A ``drift pause`` stand-aside reports ``yielded:`` through the same
    seam, so the going-forward events and this backfill agree on the
    marker.
    """
    points: list[dict[str, object]] = []
    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") != "decision" or record.get("reason") != "refused":
                continue
            detail = str(record.get("detail") or "")
            if not any(marker in detail for marker in YIELD_MARKERS):
                continue
            at = record.get("at")
            bot = record.get("bot")
            if not at or not bot:
                continue
            points.append(
                {"at": parse_at(at), "agent": str(bot), "reason": detail}
            )
    return points


def _incidents_until(until: float) -> list[Label]:
    """The incident windows, cut to the run's end.

    An incident that runs past ``until`` is clipped to it, so a label
    never claims windows the dataset does not carry."""
    cut: list[Label] = []
    for label in labels_from_incidents():
        if label.at >= until:
            continue
        if label.until is not None and label.until > until:
            label = Label(
                label.at, label.kind, label.source, label.detail, until=until
            )
        cut.append(label)
    return cut


def labels_from_incidents() -> list[Label]:
    """The incident windows, one label each, from the written records.

    A window, not an instant: the label carries ``until`` so that
    every bucket of the incident is a positive one.
    """
    labels: list[Label] = []
    for kind, (start, end), source in INCIDENTS:
        labels.append(
            Label(
                parse_at(start),
                kind,
                source,
                f"from {start} to {end}",
                until=parse_at(end),
            )
        )
    return labels


def write_dataset(
    path: Path,
    out: Path,
    *,
    bucket_seconds: int = 300,
    baseline_horizon_seconds: int = 24 * 3600,
    extra_yields: list[dict[str, object]] | None = None,
    until: float | None = None,
) -> dict[str, object]:
    """Fold the ledger into windows and write the dataset.

    ``extra_yields`` are the backfilled stand-asides; they are folded
    exactly as the ledger's own ``drift.yield`` events are, so the
    censored gaps and the excused idles of the committed dataset are
    the ones the detector would have seen had the world written the
    events at the time.
    """
    series = build_series(
        path,
        bucket_seconds=bucket_seconds,
        baseline_horizon_seconds=baseline_horizon_seconds,
        extra_yields=extra_yields,
        until=until,
    )
    buckets = []
    for bucket in series.buckets:
        buckets.append(
            {
                "at": bucket.start,
                "agents": {
                    agent: {
                        "plays": entry.plays,
                        "wins": entry.wins,
                        "losses": entry.losses,
                        "partials": entry.partials,
                        "gap_p50": entry.gap_p50,
                        "gap_p99": entry.gap_p99,
                        "gap_max": entry.gap_max,
                        "idle_seconds": entry.idle_seconds,
                        "gpu_minutes": entry.gpu_minutes,
                        "hosted_cents": entry.hosted_cents,
                    }
                    for agent, entry in bucket.agents.items()
                },
                "yields": {
                    agent: entry.yields
                    for agent, entry in bucket.agents.items()
                    if entry.yields
                },
                "verdicts": bucket.verdicts,
                "refused": bucket.refused,
                "error_codes": bucket.error_codes,
                "rule_violations": dict(bucket.rule_violations),
            }
        )
    meta = {
        "ledger": str(path),
        "ledger_sha256": sha256_of(path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_seconds": bucket_seconds,
        "agents": series.agents,
        "span": [
            datetime.fromtimestamp(series.start, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            datetime.fromtimestamp(series.end, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        ],
        "hours": round(series.hours, 4),
        "reference_start": series.reference_start,
        "reference_end": series.reference_end,
        "yield_points": len(extra_yields or []),
        "yield_source": (
            "ledger+backfill:bots.jsonl" if extra_yields else "ledger"
        ),
    }
    document = {"meta": meta, "buckets": buckets}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=1))
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=os.path.expanduser(DEFAULT_LEDGER))
    parser.add_argument("--bots", default=os.path.expanduser(DEFAULT_BOTS))
    parser.add_argument("--out", default="docs/lab/drift-dataset")
    parser.add_argument("--bucket-seconds", type=int, default=300)
    parser.add_argument(
        "--until",
        default=None,
        help="cut the run at this ISO time, exclusive (the ledger is live; "
        "a before/after must be cut from the same span of world)",
    )
    parser.add_argument(
        "--yields-from-bots",
        action="store_true",
        help="fold the dataset with the world's stand-asides backfilled "
        "from the clients' decision log (the historical ledger carries "
        "no drift.yield events)",
    )
    args = parser.parse_args(argv)

    ledger = Path(args.ledger)
    bots = Path(args.bots)
    out = Path(args.out)

    until = parse_at(args.until) if args.until else None
    labels = labels_from_bots(bots, args.bucket_seconds, until=until) + (
        labels_from_incidents() if until is None else _incidents_until(until)
    )
    labels.sort(key=lambda label: label.at)
    out.mkdir(parents=True, exist_ok=True)
    (out / "labels.json").write_text(
        json.dumps(
            {
                "meta": {
                    "bots_log": str(bots),
                    "generated_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "kinds": sorted({label.kind for label in labels}),
                    "incidents": [
                        {"kind": kind, "window": list(window), "source": source}
                        for kind, window, source in INCIDENTS
                    ],
                },
                "labels": [label.to_json() for label in labels],
            },
            indent=1,
        )
    )

    extra_yields = yields_from_bots(bots) if args.yields_from_bots else []
    if until is not None and extra_yields:
        extra_yields = [y for y in extra_yields if float(y["at"]) < until]
    meta = write_dataset(
        ledger,
        out / "dataset.json",
        bucket_seconds=args.bucket_seconds,
        extra_yields=extra_yields or None,
        until=until,
    )
    counts: dict[str, int] = {}
    for label in labels:
        counts[label.kind] = counts.get(label.kind, 0) + 1
    print(json.dumps({"meta": meta, "label_counts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
