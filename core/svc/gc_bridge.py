"""The gc bridge — a fail-open window onto the general contractor.

`gc` (tools/gc) is a Rust binary that holds a subcontractor to its bid: a
job is written, bids come in, one is awarded, the burn is checkpointed
against the bid, and the job is closed with a three-valued verdict. This
module is the Python side of that contract. It drives the binary over
`subprocess` and it owns gc's ledger — the hash-chained record of every
contract builder-ide has opened.

The bridge is keyed by builder-ide's work order id. gc's `job.new` row
carries that id in `external_id`, so the mapping between the two ledgers is
recomputed from gc's own rows rather than stored twice.

**It fails open.** With the gc binary absent, with a failing gc, with an
unreadable ledger, every method here returns None and raises nothing: a
builder-ide without gc behaves exactly as a builder-ide without gc did
before this module existed. Each kind of failure is logged once, not once
per call, so a night that asks for a hundred checkpoints does not write a
hundred identical lines.

**What it stubs**: nothing that gc owns. The bridge never computes a
verdict, a burn ratio or a reputation score — every number it hands back was
computed by gc and read out of gc's own JSON or gc's own ledger.

**How to run its tests**

    /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
        -p no:cacheprovider tests/test_gc_bridge.py

The suite passes whether or not the gc binary has been built; the tests
that need the real binary skip with a stated reason when it is absent or
when it is too old to speak `--json` yet.

**How it connects to the rest**: `core/svc/work_orders.py` opens a contract
when a work order is confirmed, `core/night/runner.py` checkpoints the burn
and cuts the task when gc says `stop_required`, `core/svc/report.py` closes
the contracts at the end of the night, and `core/api.py` reads the
reputation back. Every one of those calls comes through this module, and
every one of them can be ignored by it.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import default_settings

GC_BIN_ENV = "BUILDER_GC_BIN"
GC_LEDGER_NAME = "gc-ledger.jsonl"

_LOG = logging.getLogger("core.svc.gc_bridge")

# The repository root: core/svc/gc_bridge.py -> core/svc -> core -> <root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BINARY = _REPO_ROOT / "tools" / "gc" / "target" / "release" / "gc"

# One log line per failure kind for the life of the process. A missing
# binary is a fact about the box, not an event that repeats every call.
_LOGGED: set[str] = set()


def _log_once(kind: str, level: int, message: str, *args: object) -> None:
    """Log a failure the first time its kind is seen, and never again."""
    if kind in _LOGGED:
        return
    _LOGGED.add(kind)
    _LOG.log(level, message, *args)


@dataclass(frozen=True)
class GcResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    data: dict | None  # the parsed --json payload, or None


def _num(value: float) -> str:
    """A number the way gc parses it: plain decimal, never rounded."""
    return repr(float(value))


def _extract_json(stdout: str) -> dict | None:
    """The first JSON object printed on stdout, or None.

    gc keeps its human-readable lines and, with `--json`, adds one line of
    JSON. The JSON line is the one that parses as an object; the prose
    lines around it do not.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _default_ledger_path() -> Path:
    """`$BUILDER_HOME/gc-ledger.jsonl`, read the way the rest of the repo
    reads `BUILDER_HOME` (`core.config.default_settings`)."""
    try:
        home = default_settings().home
    except Exception:  # the bridge must not raise; fall back to the default
        home = Path(os.path.expanduser("~/builder-ide"))
    return Path(os.path.abspath(str(home / GC_LEDGER_NAME)))


class GcBridge:
    """A fail-open window onto the gc binary.

    The bridge owns gc's ledger: it passes `--ledger <absolute path>` on
    every call and it reads the same file back to recompute which job a
    builder-ide work order is bound to and whether that job is already
    awarded.
    """

    def __init__(
        self,
        *,
        ledger_path: Path | str | None = None,
        binary: str | Path | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.timeout = float(timeout)
        self._binary_override = (
            Path(os.path.expanduser(str(binary))) if binary is not None else None
        )
        if ledger_path is not None:
            self._ledger_path = Path(
                os.path.abspath(os.path.expanduser(str(ledger_path)))
            )
        else:
            self._ledger_path = _default_ledger_path()
        # gc writes the ledger itself, but the ledger's directory has to
        # exist for the process to run in it.
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log_once(
                "ledger-dir",
                logging.WARNING,
                "the gc ledger's directory %s could not be created: %s",
                self._ledger_path.parent,
                exc,
            )

    # ------------------------------------------------------------- basics

    @property
    def ledger_path(self) -> Path:
        """The absolute path of gc's ledger — the file this bridge owns."""
        return self._ledger_path

    @property
    def enabled(self) -> bool:
        """Whether the gc binary was found and can be executed."""
        return self._find_binary() is not None

    def _find_binary(self) -> Path | None:
        """The gc binary: `$BUILDER_GC_BIN` first, then the built binary in
        the repository. An explicit `binary=` is the only candidate."""
        candidates: list[Path] = []
        if self._binary_override is not None:
            candidates.append(self._binary_override)
        else:
            env = os.environ.get(GC_BIN_ENV)
            if env:
                candidates.append(Path(os.path.expanduser(env)))
            candidates.append(_DEFAULT_BINARY)
        for candidate in candidates:
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return candidate
            except OSError:
                continue
        return None

    # ------------------------------------------------------------ running

    def _run(self, args: list[str]) -> GcResult | None:
        """Run gc with the global `--ledger` flag and `--json`, or None."""
        binary = self._find_binary()
        if binary is None:
            _log_once(
                "binary",
                logging.WARNING,
                "the gc binary was not found (looked at %s); the gc bridge is inert",
                ", ".join(str(c) for c in self._candidates()),
            )
            return None
        argv = [str(binary), "--ledger", str(self.ledger_path), *args, "--json"]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.ledger_path.parent),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            _log_once(
                "timeout",
                logging.ERROR,
                "gc %s timed out after %.0f seconds",
                args[0] if args else "?",
                self.timeout,
            )
            return None
        except (OSError, ValueError) as exc:
            _log_once(
                "spawn",
                logging.ERROR,
                "gc %s could not be run: %s",
                args[0] if args else "?",
                exc,
            )
            return None
        if proc.returncode != 0:
            _log_once(
                "exit",
                logging.ERROR,
                "gc %s exited %s: %s",
                args[0] if args else "?",
                proc.returncode,
                proc.stderr.strip(),
            )
            return None
        return GcResult(
            ok=True,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            data=_extract_json(proc.stdout),
        )

    def _candidates(self) -> list[Path]:
        if self._binary_override is not None:
            return [self._binary_override]
        out: list[Path] = []
        env = os.environ.get(GC_BIN_ENV)
        if env:
            out.append(Path(os.path.expanduser(env)))
        out.append(_DEFAULT_BINARY)
        return out

    # ------------------------------------------------------- the ledger

    def _rows(self) -> list[dict] | None:
        """gc's ledger rows, oldest first. None when it cannot be read."""
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            _log_once(
                "ledger",
                logging.ERROR,
                "gc's ledger %s could not be read: %s",
                self.ledger_path,
                exc,
            )
            return None
        rows: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                _log_once(
                    "ledger",
                    logging.ERROR,
                    "gc's ledger %s holds a line that is not JSON; the rest of it is still read",
                    self.ledger_path,
                )
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    @staticmethod
    def _body(row: dict) -> dict:
        body = row.get("body")
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _job_id_in_rows(rows: list[dict], external_id: str) -> str | None:
        """The gc job id bound to a work order id, recomputed from rows."""
        found: str | None = None
        for row in rows:
            if row.get("kind") != "job.new":
                continue
            body = GcBridge._body(row)
            if body.get("external_id") != external_id:
                continue
            job_id = body.get("id")
            if isinstance(job_id, str) and job_id:
                found = job_id
        return found

    def _job_body(self, job_id: str) -> dict | None:
        """The `job.new` body of a job, recomputed from the ledger."""
        rows = self._rows()
        if rows is None:
            return None
        for row in rows:
            if row.get("kind") != "job.new":
                continue
            body = self._body(row)
            if body.get("id") == job_id:
                return body
        return None

    def _award_body(self, job_id: str) -> dict | None:
        """The `award` body of a job, or None when it is not awarded yet."""
        rows = self._rows()
        if rows is None:
            return None
        found: dict | None = None
        for row in rows:
            if row.get("kind") != "award":
                continue
            body = self._body(row)
            if body.get("job_id") == job_id:
                found = body
        return found

    def _acceptance_kind(self, job_id: str) -> str:
        """How the job's goal line is decided: `cmd`, `metric` or `report`.

        gc refuses `--accepted`/`--failed` on a cmd- or metric-kind job: it
        runs the command or measures the metric itself. The bridge reads the
        kind out of the ledger so it never states an outcome gc owns.
        """
        body = self._job_body(job_id)
        if body is None:
            return "report"
        acceptance = body.get("acceptance")
        if not isinstance(acceptance, dict):
            return "report"
        kind = acceptance.get("kind")
        return kind if isinstance(kind, str) else "report"

    # ---------------------------------------------------- the lifecycle

    def open_job(
        self,
        *,
        external_id: str,
        title: str,
        scope: str,
        job_class: str,
        estimate_min: float,
        budget_min: float,
        deadline_min: float,
        accept_cmd: str | None = None,
        accept_metric: str | None = None,
        accept_at: float | None = None,
    ) -> str | None:
        """Open the contract for a work order and return gc's job id.

        Idempotent: when gc's ledger already holds a job for this
        `external_id`, that job's id is returned and nothing is written.
        """
        existing = self.job_id_for(external_id)
        if existing is not None:
            return existing
        rows = self._rows()
        if rows is None:
            # The ledger cannot be read, so whether this contract already
            # exists is unknown; writing now could open it twice.
            return None
        args = [
            "job",
            "new",
            "--title",
            title,
            "--class",
            job_class,
            "--scope",
            scope,
            "--external-id",
            external_id,
            "--estimate-min",
            _num(estimate_min),
            "--budget-min",
            _num(budget_min),
            "--deadline-min",
            _num(deadline_min),
        ]
        if accept_cmd:
            args += ["--accept-cmd", accept_cmd]
        elif accept_metric:
            args += ["--accept-metric", accept_metric]
            if accept_at is not None:
                args += ["--accept-at", _num(accept_at)]
        result = self._run(args)
        if result is None or not result.data:
            return None
        job_id = result.data.get("id")
        return job_id if isinstance(job_id, str) and job_id else None

    def award(self, *, external_id: str, seat: str) -> dict | None:
        """Hire a seat for the contract: a bid, then the award.

        Idempotent: when the job already holds an `award` row, that row is
        returned and nothing is written.
        """
        job_id = self.job_id_for(external_id)
        if job_id is None:
            return None
        existing = self._award_body(job_id)
        if existing is not None:
            return existing
        bid = self._run(["bid", "--job", job_id, "--sub", seat, "--submit"])
        if bid is None:
            return None
        award = self._run(["award", "--job", job_id, "--auto"])
        if award is None or not award.data:
            return None
        return award.data

    def checkpoint(
        self,
        *,
        external_id: str,
        crew_used_min: float,
        check: str | None = None,
        metrics: dict[str, float] | None = None,
    ) -> dict | None:
        """Report the burn so far; the body carries `stop_required`."""
        job_id = self.job_id_for(external_id)
        if job_id is None:
            return None
        args = [
            "checkpoint",
            "--job",
            job_id,
            "--crew-used-min",
            _num(crew_used_min),
        ]
        if check is not None:
            args += ["--check", check]
        for name, value in (metrics or {}).items():
            args += ["--metric", f"{name}={_num(value)}"]
        result = self._run(args)
        return result.data if result is not None else None

    def close(
        self,
        *,
        external_id: str,
        crew_min: float,
        verdict: str | None = None,
        job_min: float | None = None,
        goal_line: str | None = None,
    ) -> dict | None:
        """Close the contract with the actuals and the verdict.

        The verdict maps onto gc's flags: `pass` -> `--accepted`, `fail` ->
        `--failed`, `inconclusive` -> `--check inconclusive`, `None` -> no
        verdict flag at all. On a cmd- or metric-kind job the bridge states
        no outcome: gc runs the command or measures the metric itself, and
        its own verdict is what comes back.
        """
        job_id = self.job_id_for(external_id)
        if job_id is None:
            return None
        args = ["close", "--job", job_id, "--crew-min", _num(crew_min)]
        if job_min is not None:
            args += ["--job-min", _num(job_min)]
        if goal_line is not None:
            args += ["--goal-line", goal_line]
        if verdict == "inconclusive":
            args += ["--check", "inconclusive"]
        elif verdict == "pass" and self._acceptance_kind(job_id) == "report":
            args.append("--accepted")
        elif verdict == "fail" and self._acceptance_kind(job_id) == "report":
            args.append("--failed")
        result = self._run(args)
        return result.data if result is not None else None

    def job_id_for(self, external_id: str) -> str | None:
        """The gc job id bound to a builder-ide work order id, if any."""
        rows = self._rows()
        if rows is None:
            return None
        return self._job_id_in_rows(rows, external_id)

    def reputation(
        self, seat: str | None = None, job_class: str | None = None
    ) -> dict | None:
        """gc's reputation report.

        With no seat the whole `report --json` payload comes back; with a
        seat, that seat's rows (one per class) come back as a list.
        """
        args = ["report"]
        if seat:
            args += ["--sub", seat]
        if job_class:
            args += ["--class", job_class]
        result = self._run(args)
        if result is None or not result.data:
            return None
        payload = result.data
        if seat is None:
            return payload
        rows = payload.get("seats")
        if not isinstance(rows, list):
            return []
        return [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("sub") == seat
            and (job_class is None or row.get("class") == job_class)
        ]
