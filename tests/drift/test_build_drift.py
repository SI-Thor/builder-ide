"""The build-drift seam, now wired to a real BoardManifest.

The claims under test (docs/lab/exp-precedent-store.md):

- without a manifest the signal is still exactly the v1 seam — named,
  not computable, reason why — so nothing that reads ``build_signals()``
  changes behaviour;
- with a manifest it scores ``drift.build_drift`` rows against the
  board's ratified scope, and stale branches score as drifting at 1.0;
- the ledger reader that feeds it (``build_drift_events``) reads world
  rows of that type — none exist today, so the reader is exercised by
  writing them directly in a fixture.
"""

from __future__ import annotations

import base64
import datetime
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.drift import DriftDetector, build_drift_events, build_signals, parse_at
from core.drift.signals import BuildDriftSignal
from core.precedent import BoardManifest, seed_store, seed_rules


def manifest() -> BoardManifest:
    return BoardManifest.from_store(
        seed_store(), rules=seed_rules(), scope_boundary="the spawn island"
    )


def event(at: float, branch: str, keys, mf=None) -> dict:
    return {"at": at, "branch": branch, "keys": keys, "manifest": mf}


def test_without_a_manifest_the_signal_is_still_the_seam() -> None:
    signal = BuildDriftSignal()
    assert signal.computable is False
    assert signal.name == "build"
    assert signal.reason  # ... and it says why
    assert signal.compute(None, None, None) == []


def test_build_signals_keeps_the_same_names() -> None:
    signals = build_signals()
    assert [s.name for s in signals] == [
        "stall",
        "success",
        "errors",
        "violation",
        "spend",
        "build",
    ]
    assert signals[5].computable is False


def test_with_a_manifest_the_signal_is_computable() -> None:
    signal = BuildDriftSignal(manifest=manifest())
    assert signal.computable is True
    assert signal.reason == ""
    # a manifest with no branch events is computable and silent:
    # the honest state of the seam
    assert signal.compute(None, None, None) == []


def test_branch_events_are_scored_against_the_manifest() -> None:
    signal = BuildDriftSignal(
        manifest=manifest(),
        events=[
            event(3.0, "br/full", ["ladder.p1.preflight", "recipe.apply"]),
            event(2.0, "br/half", ["ladder.p1.preflight", "recipe.squash"]),
            event(1.0, "br/stale", ["recipe.apply"], "manifest/0:000000000000"),
            event(0.5, "br/none", []),
        ],
    )
    points = signal.compute(None, None, None)
    # ordered by time, whatever order the rows arrive in
    assert [(p.at, p.scope) for p in points] == [
        (0.5, "br/none"),
        (1.0, "br/stale"),
        (2.0, "br/half"),
        (3.0, "br/full"),
    ]
    by_branch = {p.scope: p.value for p in points}
    assert by_branch["br/full"] == 0.0   # every key ratified
    assert by_branch["br/half"] == 0.5   # one key out of two outside
    assert by_branch["br/stale"] == 1.0  # validated against another board
    assert by_branch["br/none"] is None  # nothing declared, nothing to say


def test_a_head_validated_against_the_current_manifest_is_not_stale() -> None:
    current = manifest().fingerprint()
    signal = BuildDriftSignal(
        manifest=manifest(),
        events=[event(1.0, "br/ok", ["recipe.apply"], current)],
    )
    assert signal.compute(None, None, None)[0].value == 0.0


def _write_ledger(path: Path, rows) -> Path:
    """A minimal world ledger holding exactly ``rows`` audit events."""
    connection = sqlite3.connect(path)
    connection.execute("create table if not exists audit (seq integer primary key, at text, type text, payload text)")
    for i, (stamp, kind, payload) in enumerate(rows):
        connection.execute(
            "insert into audit (seq, at, type, payload) values (?, ?, ?, ?)",
            (i, stamp, kind, json.dumps(payload)),
        )
    connection.commit()
    connection.close()
    return path


def test_the_ledger_reader_reads_build_drift_rows(tmp_path) -> None:
    stamp = lambda s: datetime.datetime(2026, 11, 2, 0, 0, s).isoformat()  # noqa: E731
    ledger = _write_ledger(
        tmp_path / "world.db",
        [
            (
                stamp(0),
                "BEES",
                {"i": 1, "rc": 0, "out": base64.b64encode(b"x").decode()},
            ),
            (
                stamp(1),
                "drift.build_drift",
                {"branch": "br/x", "keys": ["recipe.apply"], "manifest": None},
            ),
        ],
    )
    events = build_drift_events(ledger)
    assert len(events) == 1
    assert events[0]["branch"] == "br/x"
    assert events[0]["keys"] == ["recipe.apply"]
    assert events[0]["at"] == parse_at(stamp(1))


def test_the_detector_wires_the_manifest_through() -> None:
    detector = DriftDetector(
        manifest=manifest(),
        build_events=[event(1.0, "br/ok", ["recipe.apply"])],
    )
    build = [s for s in detector.signals if s.name == "build"][0]
    assert build.computable is True
    assert build.compute(None, None, None)[0].value == 0.0
    # ... and the v1 default still says seam
    assert [s for s in DriftDetector().signals if s.name == "build"][0].computable is False
