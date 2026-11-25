"""The gc bridge's tests: the exact argv the bridge builds, the fail-open
path, the verdict mapping, and the ledger scan.

The suite passes whether or not the gc binary has been built. Everything
that needs gc drives a fake one — a tiny script that records the argv it
was called with and prints a canned payload — so the assertions are about
the bridge's own behaviour, not about gc's. The tests that use the real
binary are skipped, with a stated reason, when the binary is missing or is
too old to speak `--json` yet.

Run them with

    /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
        -p no:cacheprovider tests/test_gc_bridge.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from core.svc import gc_bridge
from core.svc.gc_bridge import GC_BIN_ENV, GC_LEDGER_NAME, GcBridge, GcResult

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = REPO_ROOT / "tools" / "gc" / "target" / "release" / "gc"

# A gc binary that is not there, for the tests that only read the ledger.
ABSENT_BINARY = Path("/nonexistent/gc")

# The fake gc: it records the argv it was called with, one JSON list per
# line, and prints the canned payload for the command it was given.
FAKE_GC = '''#!{python}
import json, os, sys

record = os.environ.get("FAKE_GC_RECORD")
if record:
    with open(record, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv) + "\\n")

words = sys.argv[1:]
key = None
if "job" in words and "new" in words:
    key = "job.new"
elif "report" in words:
    key = "report"
elif "checkpoint" in words:
    key = "checkpoint"
elif "close" in words:
    key = "close"
elif "award" in words:
    key = "award"
elif "bid" in words:
    key = "bid"

code = int(os.environ.get("FAKE_GC_EXIT", "0"))
if code:
    sys.stderr.write("gc: fake failure\\n")
    sys.exit(code)

payloads = json.loads(os.environ.get("FAKE_GC_PAYLOADS", "{{}}"))
print(json.dumps(payloads.get(key, {{}})))
'''


class FakeGc:
    """The fake gc binary and the file it records its calls in."""

    def __init__(self, script: Path, record: Path) -> None:
        self.script = script
        self.record = record

    def install(
        self,
        monkeypatch: pytest.MonkeyPatch,
        payloads: dict | None = None,
        exit_code: int = 0,
    ) -> None:
        monkeypatch.setenv(GC_BIN_ENV, str(self.script))
        monkeypatch.setenv("FAKE_GC_RECORD", str(self.record))
        monkeypatch.setenv("FAKE_GC_PAYLOADS", json.dumps(payloads or {}))
        monkeypatch.setenv("FAKE_GC_EXIT", str(exit_code))

    def calls(self) -> list[list[str]]:
        if not self.record.exists():
            return []
        return [
            json.loads(line)
            for line in self.record.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@pytest.fixture
def fake_gc(tmp_path) -> FakeGc:
    script = tmp_path / "fake-gc"
    script.write_text(FAKE_GC.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    return FakeGc(script=script, record=tmp_path / "calls.jsonl")


@pytest.fixture
def ledger(tmp_path) -> Path:
    return tmp_path / "gc-ledger.jsonl"


# --------------------------------------------------------------- helpers


def job_row(
    seq: int = 0,
    job_id: str = "J-0001",
    external_id: str = "wo-1",
    acceptance_kind: str = "report",
    job_class: str = "build-feature",
) -> dict:
    """A `job.new` row as gc writes it."""
    return {
        "seq": seq,
        "ts": "2026-11-24T09:00:00Z",
        "kind": "job.new",
        "body": {
            "id": job_id,
            "external_id": external_id,
            "title": "weather the crates",
            "scope": "props.harbor.crates",
            "class": job_class,
            "acceptance": {
                "kind": acceptance_kind,
                "cmd": "",
                "metric": "",
                "threshold": None,
                "note": "",
            },
            "deadline_min": 120.0,
            "estimate_min": 60.0,
            "budget_min": 90.0,
            "stop_ratio": 0.8,
            "clauses": [],
        },
        "prev": "0" * 64,
        "hash": "0" * 64,
    }


def award_row(seq: int = 1, job_id: str = "J-0001", seat: str = "Architect") -> dict:
    """An `award` row as gc writes it."""
    return {
        "seq": seq,
        "ts": "2026-11-24T09:05:00Z",
        "kind": "award",
        "body": {
            "job_id": job_id,
            "bid_id": "B-0001",
            "sub": seat,
            "score": 0.91,
        },
        "prev": "0" * 64,
        "hash": "0" * 64,
    }


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def expected_argv(binary: Path, ledger_path: Path, *args: str) -> list[str]:
    """The argv the bridge is expected to build: the binary, the global
    `--ledger` flag, the command, and `--json` last."""
    return [str(binary), "--ledger", str(ledger_path), *args, "--json"]


JOB_PAYLOAD = {
    "id": "J-0007",
    "external_id": "wo-1",
    "title": "weather the crates",
    "scope": "props.harbor.crates",
    "class": "build-feature",
    "acceptance": {"kind": "report", "cmd": "", "metric": "", "threshold": None},
    "deadline_min": 120.0,
    "estimate_min": 60.0,
    "budget_min": 90.0,
    "stop_ratio": 0.8,
    "clauses": [],
}
AWARD_PAYLOAD = {"job_id": "J-0001", "bid_id": "B-0001", "sub": "Architect", "score": 0.91}
CHECKPOINT_PAYLOAD = {
    "job_id": "J-0001",
    "crew_used_min": 42.0,
    "burn": 0.56,
    "stop_required": False,
    "check": {"verdict": "inconclusive", "by": "none", "exit_code": None, "note": ""},
    "metrics": [{"name": "crew_used_min", "value": 42.0}],
    "clauses": [],
    "forecast": {"verdict": "ok", "note": "on track"},
}
CLOSE_PAYLOAD = {
    "job_id": "J-0001",
    "accepted": True,
    "acceptance_verdict": "pass",
    "actual_crew_min": 55.0,
    "actual_job_min": 58.0,
    "late_days": 0.0,
    "effective_bid_min": 75.0,
    "overrun_min": 0.0,
    "penalty_min": 0.0,
    "debt_delta_min": 0.0,
    "method": "wall",
    "check": {"verdict": "pass", "by": "human", "exit_code": None, "note": ""},
}
REPORT_PAYLOAD = {
    "rows": 4,
    "jobs": 1,
    "bids": 1,
    "seats": [
        {"sub": "Architect", "class": "build-feature", "jobs": 3, "reputation": 91.0},
        {"sub": "Artist", "class": "build-feature", "jobs": 1, "reputation": 70.0},
    ],
    "factor_curve": [],
    "all_runs_curve": [],
    "promise_curve": [],
}


# ----------------------------------------------------------- the binary


def test_default_binary_is_the_built_one_in_the_repository():
    assert gc_bridge._DEFAULT_BINARY == DEFAULT_BINARY
    assert gc_bridge._REPO_ROOT == REPO_ROOT


def test_binary_is_found_through_the_environment(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch)
    assert GcBridge(ledger_path=ledger).enabled is True


def test_binary_is_found_through_the_default_path(monkeypatch, ledger):
    monkeypatch.delenv(GC_BIN_ENV, raising=False)
    if not (DEFAULT_BINARY.is_file() and os.access(DEFAULT_BINARY, os.X_OK)):
        pytest.skip("the gc binary has not been built at %s" % DEFAULT_BINARY)
    assert GcBridge(ledger_path=ledger).enabled is True


def test_ledger_path_defaults_to_builder_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDER_HOME", str(tmp_path / "home"))
    bridge = GcBridge()
    assert bridge.ledger_path == Path(
        os.path.realpath(str(tmp_path / "home" / GC_LEDGER_NAME))
    )


def test_the_constructor_overrides_the_default_ledger_path(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDER_HOME", str(tmp_path / "home"))
    bridge = GcBridge(ledger_path=tmp_path / "other" / "gc-ledger.jsonl")
    assert bridge.ledger_path == tmp_path / "other" / "gc-ledger.jsonl"


# ------------------------------------------------------------ fail open


def test_every_method_fails_open_when_gc_is_absent(tmp_path, ledger):
    bridge = GcBridge(ledger_path=ledger, binary=tmp_path / "no-such-gc")
    assert bridge.enabled is False
    assert bridge.open_job(
        external_id="wo-1",
        title="t",
        scope="s",
        job_class="build-feature",
        estimate_min=60.0,
        budget_min=90.0,
        deadline_min=120.0,
    ) is None
    assert bridge.award(external_id="wo-1", seat="Architect") is None
    assert bridge.checkpoint(external_id="wo-1", crew_used_min=10.0) is None
    assert bridge.close(external_id="wo-1", crew_min=10.0, verdict="pass") is None
    assert bridge.job_id_for("wo-1") is None
    assert bridge.reputation() is None
    assert bridge.reputation(seat="Architect") is None


def test_a_failing_gc_returns_none_and_does_not_raise(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, exit_code=3)
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    assert (
        bridge.open_job(
            external_id="wo-1",
            title="t",
            scope="s",
            job_class="build-feature",
            estimate_min=60.0,
            budget_min=90.0,
            deadline_min=120.0,
        )
        is None
    )
    assert bridge.reputation() is None


def test_a_gc_that_prints_no_json_returns_none(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    assert (
        bridge.open_job(
            external_id="wo-1",
            title="t",
            scope="s",
            job_class="build-feature",
            estimate_min=60.0,
            budget_min=90.0,
            deadline_min=120.0,
        )
        is None
    )


def test_a_failure_kind_is_logged_once(fake_gc, monkeypatch, ledger, caplog):
    """A missing or failing gc is a fact about the box, not an event that
    repeats on every call: one line per failure kind."""
    gc_bridge._LOGGED.clear()
    fake_gc.install(monkeypatch, exit_code=1)
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    with caplog.at_level("ERROR", logger="core.svc.gc_bridge"):
        for _ in range(3):
            bridge.reputation()
    records = [r for r in caplog.records if r.name == "core.svc.gc_bridge"]
    assert len(records) == 1


# ------------------------------------------------------- the exact argv


def test_open_job_builds_the_exact_argv(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={"job.new": JOB_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    job_id = bridge.open_job(
        external_id="wo-1",
        title="weather the crates",
        scope="props.harbor.crates",
        job_class="build-feature",
        estimate_min=60.0,
        budget_min=90.0,
        deadline_min=120.0,
    )
    assert job_id == "J-0007"
    assert fake_gc.calls() == [
        expected_argv(
            fake_gc.script,
            ledger,
            "job",
            "new",
            "--title",
            "weather the crates",
            "--class",
            "build-feature",
            "--scope",
            "props.harbor.crates",
            "--external-id",
            "wo-1",
            "--estimate-min",
            "60.0",
            "--budget-min",
            "90.0",
            "--deadline-min",
            "120.0",
        )
    ]


def test_open_job_passes_the_goal_line(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={"job.new": JOB_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    bridge.open_job(
        external_id="wo-1",
        title="t",
        scope="s",
        job_class="build-feature",
        estimate_min=60.0,
        budget_min=90.0,
        deadline_min=120.0,
        accept_cmd="pytest tests/acceptance",
    )
    argv = fake_gc.calls()[0]
    assert argv[-3:] == ["--accept-cmd", "pytest tests/acceptance", "--json"]


def test_open_job_passes_a_metric_goal_line(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={"job.new": JOB_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    bridge.open_job(
        external_id="wo-1",
        title="t",
        scope="s",
        job_class="build-feature",
        estimate_min=60.0,
        budget_min=90.0,
        deadline_min=120.0,
        accept_metric="psnr",
        accept_at=31.5,
    )
    argv = fake_gc.calls()[0]
    assert argv[-5:] == ["--accept-metric", "psnr", "--accept-at", "31.5", "--json"]


def test_award_bids_then_awards(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row()])
    fake_gc.install(
        monkeypatch, payloads={"bid": {"id": "B-0001"}, "award": AWARD_PAYLOAD}
    )
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    body = bridge.award(external_id="wo-1", seat="Architect")
    assert body == AWARD_PAYLOAD
    assert fake_gc.calls() == [
        expected_argv(
            fake_gc.script,
            ledger,
            "bid",
            "--job",
            "J-0001",
            "--sub",
            "Architect",
            "--submit",
        ),
        expected_argv(fake_gc.script, ledger, "award", "--job", "J-0001", "--auto"),
    ]


def test_checkpoint_builds_the_exact_argv(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row()])
    fake_gc.install(monkeypatch, payloads={"checkpoint": CHECKPOINT_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    body = bridge.checkpoint(
        external_id="wo-1",
        crew_used_min=42.0,
        check="auto",
        metrics={"psnr": 31.5, "crunch": 0.25},
    )
    assert body == CHECKPOINT_PAYLOAD
    assert body["stop_required"] is False
    assert fake_gc.calls() == [
        expected_argv(
            fake_gc.script,
            ledger,
            "checkpoint",
            "--job",
            "J-0001",
            "--crew-used-min",
            "42.0",
            "--check",
            "auto",
            "--metric",
            "psnr=31.5",
            "--metric",
            "crunch=0.25",
        )
    ]


def test_close_builds_the_exact_argv(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row()])
    fake_gc.install(monkeypatch, payloads={"close": CLOSE_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    body = bridge.close(
        external_id="wo-1",
        crew_min=55.0,
        verdict="pass",
        job_min=58.0,
        goal_line="the crates are weathered",
    )
    assert body == CLOSE_PAYLOAD
    assert fake_gc.calls() == [
        expected_argv(
            fake_gc.script,
            ledger,
            "close",
            "--job",
            "J-0001",
            "--crew-min",
            "55.0",
            "--job-min",
            "58.0",
            "--goal-line",
            "the crates are weathered",
            "--accepted",
        )
    ]


# ---------------------------------------------------- the verdict mapping


@pytest.mark.parametrize(
    "verdict,flag",
    [
        ("pass", "--accepted"),
        ("fail", "--failed"),
        ("inconclusive", "--check"),
    ],
)
def test_close_maps_the_verdicts_onto_the_flags(
    fake_gc, monkeypatch, ledger, verdict, flag
):
    write_ledger(ledger, [job_row(acceptance_kind="report")])
    fake_gc.install(monkeypatch, payloads={"close": CLOSE_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    bridge.close(external_id="wo-1", crew_min=55.0, verdict=verdict)
    argv = fake_gc.calls()[0]
    assert flag in argv
    if verdict == "inconclusive":
        assert argv[argv.index(flag) + 1] == "inconclusive"


def test_close_without_a_verdict_passes_no_verdict_flag(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row(acceptance_kind="report")])
    fake_gc.install(monkeypatch, payloads={"close": CLOSE_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    bridge.close(external_id="wo-1", crew_min=55.0)
    argv = fake_gc.calls()[0]
    assert "--accepted" not in argv
    assert "--failed" not in argv
    assert "--check" not in argv


@pytest.mark.parametrize("acceptance_kind", ["cmd", "metric"])
def test_close_does_not_state_an_outcome_gc_owns(
    fake_gc, monkeypatch, ledger, acceptance_kind
):
    """gc refuses `--accepted`/`--failed` on a cmd- or metric-kind job: it
    runs the command or measures the metric itself, so the bridge says
    nothing and takes gc's own verdict."""
    write_ledger(ledger, [job_row(acceptance_kind=acceptance_kind)])
    fake_gc.install(monkeypatch, payloads={"close": CLOSE_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    bridge.close(external_id="wo-1", crew_min=55.0, verdict="pass")
    argv = fake_gc.calls()[0]
    assert "--accepted" not in argv
    assert "--failed" not in argv
    bridge.close(external_id="wo-1", crew_min=55.0, verdict="fail")
    argv = fake_gc.calls()[1]
    assert "--accepted" not in argv
    assert "--failed" not in argv


# --------------------------------------------------------- the ledger scan


def test_the_ledger_scan_finds_a_job_by_external_id(ledger):
    write_ledger(
        ledger,
        [
            job_row(seq=0, job_id="J-0001", external_id="wo-1"),
            job_row(seq=1, job_id="J-0002", external_id="wo-2"),
        ],
    )
    bridge = GcBridge(ledger_path=ledger, binary=ABSENT_BINARY)
    assert bridge.job_id_for("wo-2") == "J-0002"
    assert bridge.job_id_for("wo-9") is None


def test_the_ledger_scan_recognises_an_award(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row(), award_row()])
    fake_gc.install(monkeypatch, payloads={"award": AWARD_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    body = bridge.award(external_id="wo-1", seat="Architect")
    assert body == {
        "job_id": "J-0001",
        "bid_id": "B-0001",
        "sub": "Architect",
        "score": 0.91,
    }
    # The contract was already awarded: nothing was written.
    assert fake_gc.calls() == []


def test_open_job_is_idempotent(fake_gc, monkeypatch, ledger):
    write_ledger(ledger, [job_row()])
    fake_gc.install(monkeypatch, payloads={"job.new": JOB_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    assert (
        bridge.open_job(
            external_id="wo-1",
            title="weather the crates",
            scope="props.harbor.crates",
            job_class="build-feature",
            estimate_min=60.0,
            budget_min=90.0,
            deadline_min=120.0,
        )
        == "J-0001"
    )
    assert fake_gc.calls() == []


def test_an_unreadable_ledger_fails_open(tmp_path, ledger):
    # A directory where the ledger file should be: reading it fails.
    ledger.mkdir(parents=True, exist_ok=True)
    bridge = GcBridge(ledger_path=ledger, binary=tmp_path / "no-such-gc")
    assert bridge.job_id_for("wo-1") is None
    assert bridge.award(external_id="wo-1", seat="Architect") is None


# ------------------------------------------------------------ reputation


def test_reputation_without_a_seat_returns_the_payload(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={"report": REPORT_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    payload = bridge.reputation()
    assert payload == REPORT_PAYLOAD
    assert fake_gc.calls() == [
        expected_argv(fake_gc.script, ledger, "report"),
    ]


def test_reputation_with_a_seat_returns_that_seats_rows(
    fake_gc, monkeypatch, ledger
):
    fake_gc.install(monkeypatch, payloads={"report": REPORT_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    rows = bridge.reputation(seat="Architect")
    assert rows == [
        {"sub": "Architect", "class": "build-feature", "jobs": 3, "reputation": 91.0}
    ]
    assert fake_gc.calls() == [
        expected_argv(fake_gc.script, ledger, "report", "--sub", "Architect"),
    ]


def test_reputation_with_a_seat_and_a_class(fake_gc, monkeypatch, ledger):
    fake_gc.install(monkeypatch, payloads={"report": REPORT_PAYLOAD})
    bridge = GcBridge(ledger_path=ledger, binary=fake_gc.script)
    rows = bridge.reputation(seat="Architect", job_class="build-feature")
    assert len(rows) == 1
    assert fake_gc.calls() == [
        expected_argv(
            fake_gc.script,
            ledger,
            "report",
            "--sub",
            "Architect",
            "--class",
            "build-feature",
        ),
    ]


# --------------------------------------------------------------- the type


def test_gc_result_is_frozen():
    result = GcResult(ok=True, returncode=0, stdout="{}", stderr="", data=None)
    assert result.data is None
    with pytest.raises(FrozenInstanceError):
        result.ok = False


# ------------------------------------------------------- the real binary


def _probe_real_gc() -> tuple[bool, str]:
    """Is the built gc binary present, and does it speak `--json` yet?

    The gc binary is being rebuilt with the `--json` and `--external-id`
    flags; until that build lands, `job new --json` prints no JSON and the
    real-binary tests have nothing to assert on.
    """
    if not (DEFAULT_BINARY.is_file() and os.access(DEFAULT_BINARY, os.X_OK)):
        return False, "the gc binary has not been built at %s" % DEFAULT_BINARY
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "gc-ledger.jsonl"
        try:
            proc = subprocess.run(
                [
                    str(DEFAULT_BINARY),
                    "--ledger",
                    str(ledger),
                    "job",
                    "new",
                    "--title",
                    "probe",
                    "--class",
                    "build-feature",
                    "--scope",
                    "probe",
                    "--external-id",
                    "probe-1",
                    "--estimate-min",
                    "60",
                    "--budget-min",
                    "90",
                    "--deadline-min",
                    "120",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, "the built gc binary could not be run: %s" % exc
    if proc.returncode != 0:
        return False, "the built gc binary rejected a probe job: %s" % (
            proc.stderr.strip()
        )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("id"):
            return True, ""
    return False, "the built gc binary does not answer `--json` yet"


REAL_GC_OK, REAL_GC_REASON = _probe_real_gc()
requires_real_gc = pytest.mark.skipif(not REAL_GC_OK, reason=REAL_GC_REASON)


@requires_real_gc
def test_the_real_binary_opens_awards_checkpoints_and_closes(tmp_path):
    ledger = tmp_path / "gc-ledger.jsonl"
    bridge = GcBridge(ledger_path=ledger, binary=DEFAULT_BINARY)
    job_id = bridge.open_job(
        external_id="wo-real-1",
        title="weather the crates",
        scope="props.harbor.crates",
        job_class="build-feature",
        estimate_min=60.0,
        budget_min=90.0,
        deadline_min=120.0,
    )
    assert job_id
    assert bridge.job_id_for("wo-real-1") == job_id

    award = bridge.award(external_id="wo-real-1", seat="Architect")
    assert award is not None
    assert award["job_id"] == job_id
    assert award["sub"] == "Architect"

    checkpoint = bridge.checkpoint(external_id="wo-real-1", crew_used_min=10.0)
    assert checkpoint is not None
    assert "stop_required" in checkpoint

    closed = bridge.close(external_id="wo-real-1", crew_min=20.0, verdict="pass")
    assert closed is not None
    assert closed["job_id"] == job_id
    assert closed["acceptance_verdict"] == "pass"


@requires_real_gc
def test_the_real_binary_reports_a_reputation(tmp_path):
    ledger = tmp_path / "gc-ledger.jsonl"
    bridge = GcBridge(ledger_path=ledger, binary=DEFAULT_BINARY)
    payload = bridge.reputation()
    assert payload is not None
    for key in (
        "rows",
        "jobs",
        "bids",
        "seats",
        "factor_curve",
        "all_runs_curve",
        "promise_curve",
    ):
        assert key in payload
