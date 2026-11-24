# gc into builder-ide's night — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** builder-ide holds a builder to its estimate the way `gc` holds a
subcontractor to its bid: a confirmed work order becomes a gc job with a bid and
an award; the night reports burn as gc checkpoints; gc's 80%-of-bid stop rule
stops the attempt as a builder-ide rail event; the morning report closes the job
with a three-valued verdict; and a read API returns a builder's gc reputation.

**Architecture:** `gc` stays a Rust binary. A new fail-open Python service,
`core/svc/gc_bridge.py`, drives it over `subprocess` and owns gc's ledger, which
lives next to builder-ide's own ledger in the store's data directory
(`$BUILDER_HOME/gc-ledger.jsonl`). The bridge is keyed by the builder-ide work
order id: gc's `job.new` row carries an `external_id`, so the mapping is
recomputed from gc's own hash-chained ledger rather than stored twice. Nothing
in builder-ide's existing behaviour changes when the gc binary is absent.

**Tech Stack:** Rust (std only, no crates) for `gc`; Python 3.12 + pydantic for
builder-ide; pytest; `subprocess` for the bridge.

## Global Constraints

- `gc` stays a Rust binary. Do NOT rewrite gc in Python.
- The bridge must be optional and fail open: with the gc binary absent,
  builder-ide behaves exactly as today (log once, carry on).
- Binary discovery order: `$BUILDER_GC_BIN`, then `tools/gc/target/release/gc`
  relative to the repository root.
- gc's ledger lives next to builder-ide's ledger in the store's data directory:
  `$BUILDER_HOME/gc-ledger.jsonl` (`Settings.home`, `core/config.py:118-119`).
- `cd tools/gc && cargo test --release` must stay green; new gc behaviour gets
  new tests.
- Python tests run from the worktree root with
  `/home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q -p no:cacheprovider --continue-on-collection-errors`.
  The set of FAILED/ERROR lines must equal `.baseline-fails.txt`. Zero new failures.
- House style (repo-root `CLAUDE.md`): honest numbers, no fake data; every
  number is measured or labelled as an estimate; documentation explains
  mechanisms and never claims.
- Do not touch `worlds/`, `engines/`, or unrelated seats. Do not edit
  `.baseline-fails.txt`. Do not install packages into the shared venv.
- No new event types in builder-ide's closed audit-event sets
  (`core/night/events.py:1-8`): gc's records ride as payloads or in gc's own
  ledger.
- Do not push. Do not merge. Commit on branch `fold-gc` in small commits.

---

## The mapping (the whole design in one table)

| gc | builder-ide | where |
|---|---|---|
| job | one **work order** | `gc job new --external-id <wo_id>` |
| class | the order's gc class (derived, see below) | `job_class` |
| estimate | `wo.estimate.build_verify.wall_minutes + wo.estimate.generate_test.wall_minutes` | the GC's view of the crew-time |
| ceiling (`budget_min`) | `wo.budget.per_order.wall_minutes`, else the estimate | the most it will pay |
| deadline (`deadline_min`) | the night's `rails.wall_minutes` when the order names a night, else the ceiling | the job-time envelope |
| goal line | the order's machine-checkable acceptance check | `--accept-cmd`, else report-kind |
| sub (seat) | the builder seat: `Attempt.engineer` | `gc bid --sub` |
| bid | gc computes it from the seat's track record | `gc bid --submit` |
| award | the seat is hired | `gc award --auto` |
| checkpoint | a burn report for the order | `gc checkpoint --crew-used-min` |
| close | the order's end of the night | `gc close --crew-min` |
| verdict | builder-ide's three-valued check | `--accepted` / `--failed` / `--check inconclusive` |
| reputation | a builder's gc record | `gc report --json` |

**Deriving the class.** builder-ide work orders carry no job class. The bridge
uses, in order: the serving task's `kind` when `wo.serves` resolves to a task
(`core/records.py:356`), else the constant `"build-feature"`. The derivation is
recorded in the gc job's `scope` line so the ledger says where it came from.

**Deriving the goal line.** builder-ide's `AcceptanceCheck.kind` is one of
`constraint | geometry | critic | test_suite | render_rung | manual`
(`core/records.py:630-641`). A `test_suite` check whose spec carries a `cmd`
becomes a gc `--accept-cmd` goal line (gc then runs it and reads the exit code).
Everything else becomes a **report-kind** job, closed by builder-ide's own word
(`--accepted` / `--failed`) or by `--check inconclusive`.

**Seat and the award moment.** gc's bid is *a seat's promise*, and the award is
the hiring of that seat. A work order names no seat until an attempt starts
(`Attempt.engineer`, `core/svc/work_orders.py:257`), so:

- `confirm("go")` writes the gc **job** (the contract exists), and writes the
  bid + award too when the caller supplies a seat (`confirm(..., seat=...)`).
- `start_attempt(wo_id, engineer)` writes the bid + award when the contract is
  not awarded yet (the seat is now known). Both steps are idempotent: a
  contract that already has an award is left alone.

This is recorded as an open question in `FOLD-REPORT.md`.

---

## Task 1: gc's CLI — the small additive changes

**Files:**
- Modify: `tools/gc/src/main.rs` (`cmd_job`, `cmd_bid`, `cmd_award`, `cmd_checkpoint`, `cmd_close`)
- Modify: `tools/gc/src/report.rs` (`json_report`)
- Modify: `tools/gc/src/model.rs` (`Job` — the `external_id` field)
- Test: `tools/gc/tests/cli.rs`

**Produces (the exact contract the Python bridge codes against):**

1. `gc job new --external-id ID` stores `external_id` in the `job.new` row
   body. `external_id` defaults to the empty string.
2. `gc job new --json`, `gc bid --json`, `gc award --json`,
   `gc checkpoint --json`, `gc close --json` print **one line of JSON on
   stdout** — the same body that is written to the ledger, plus the ids:
   - `job new --json` → the `job.new` body (has `id`, `external_id`, `title`,
     `scope`, `class`, `acceptance`, `deadline_min`, `estimate_min`,
     `budget_min`, `stop_ratio`, `clauses`).
   - `bid --json` → the `bid.new` body (has `id`, `job_id`, `sub`, `crew_min`,
     `job_min`, `confidence`, `computed`, `basis`).
   - `award --json` → the `award` body (has `job_id`, `bid_id`, `sub`, `score`).
   - `checkpoint --json` → the `checkpoint` body (has `job_id`,
     `crew_used_min`, `burn`, `stop_required`, `check.verdict`, `metrics`,
     `clauses`, `forecast.verdict`).
   - `close --json` → the `close` body (has `job_id`, `accepted`,
     `acceptance_verdict`, `actual_crew_min`, `actual_job_min`, `late_days`,
     `effective_bid_min`, `overrun_min`, `penalty_min`, `debt_delta_min`,
     `method`, `check.verdict`).
   The human-readable lines stay exactly as they are; `--json` **adds** the
   JSON line rather than replacing them, so existing tests keep passing.
3. `gc close --check inconclusive` is accepted on a **report-kind** job and
   records the verdict `inconclusive`. (Today the error message at
   `tools/gc/src/main.rs:952-957` promises `--check inconclusive` and the code
   does not implement it.) `--accepted`/`--failed` keep their current meaning.
4. `gc report --json` gains two fields on every seat row:
   - `retools`: the number of retool events for that (sub, class).
   - `on_time_known`: `false` when no close of that pair had a recorded
     deadline, so `on_time_rate: 0` is not read as "never on time".
   Existing fields keep their names and meanings.

**Tests to add** (`tools/gc/tests/cli.rs`, using the existing `gc()`/`ok()`/
`fails()` helpers):
- `--external-id` round-trips into the `job.new` row.
- `--json` on each of the five commands prints parseable JSON with the fields
  above.
- `close --check inconclusive` on a report-kind job closes with
  `acceptance_verdict == "inconclusive"`.
- `report --json` carries `retools` and `on_time_known`.
- The 56 existing tests stay green.

---

## Task 2: the bridge — `core/svc/gc_bridge.py`

**Files:**
- Create: `core/svc/gc_bridge.py`
- Create: `tests/test_gc_bridge.py`

**The exact public API (the wiring task codes against this and nothing else):**

```python
GC_BIN_ENV = "BUILDER_GC_BIN"
GC_LEDGER_NAME = "gc-ledger.jsonl"

@dataclass(frozen=True)
class GcResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    data: dict | None          # the parsed --json payload, or None

class GcBridge:
    def __init__(self, *, ledger_path: Path | str | None = None,
                 binary: str | Path | None = None, timeout: float = 120.0) -> None: ...

    @property
    def enabled(self) -> bool: ...          # the binary was found and is executable
    @property
    def ledger_path(self) -> Path: ...

    # --- the contract lifecycle, keyed by the builder-ide work order id ---
    def open_job(self, *, external_id: str, title: str, scope: str, job_class: str,
                 estimate_min: float, budget_min: float, deadline_min: float,
                 accept_cmd: str | None = None,
                 accept_metric: str | None = None, accept_at: float | None = None,
                 ) -> str | None: ...         # the gc job id, or None
    def award(self, *, external_id: str, seat: str) -> dict | None: ...
    def checkpoint(self, *, external_id: str, crew_used_min: float,
                   check: str | None = None, metrics: dict[str, float] | None = None,
                   ) -> dict | None: ...      # the checkpoint body (has stop_required)
    def close(self, *, external_id: str, crew_min: float,
              verdict: str | None = None, job_min: float | None = None,
              goal_line: str | None = None) -> dict | None: ...
    def job_id_for(self, external_id: str) -> str | None: ...
    def reputation(self, seat: str | None = None,
                   job_class: str | None = None) -> dict | None: ...
```

**Rules:**
- Every method returns `None` when gc is missing, gc fails, or the ledger
  cannot be read. It never raises. It logs **once** per failure kind
  (`logging.getLogger("core.svc.gc_bridge")`).
- `open_job` is idempotent: if gc's ledger already holds a job with that
  `external_id`, it returns that job's id and writes nothing.
- `award` is idempotent: if the job already has an award row, it returns that
  award's body and writes nothing.
- `close` maps `verdict`:
  - `"pass"` → `--accepted` (report-kind jobs only),
  - `"fail"` → `--failed` (report-kind jobs only),
  - `"inconclusive"` → `--check inconclusive`,
  - `None` → no verdict flag (gc decides the goal line itself for cmd/metric
    jobs).
  For a cmd/metric job with a `pass`/`fail` verdict, the bridge does **not**
  pass `--accepted`/`--failed` (gc refuses them) — it lets gc run the command
  and takes gc's own verdict.
- `job_id_for` and the idempotency checks read gc's ledger
  (`ledger.jsonl`, one JSON object per line) and recompute: a `job.new` row
  whose body has `external_id == external_id` gives the job id; an `award` row
  whose body has that `job_id` means the contract is awarded.
- `reputation()` returns gc's `report --json` payload; with `seat` given it
  returns the seat's rows (one per class) as a list, otherwise the whole
  payload.
- Binary discovery: `$BUILDER_GC_BIN`, then
  `<repo root>/tools/gc/target/release/gc`, where the repo root is
  `Path(__file__).resolve().parents[2]`.
- Default ledger path: `$BUILDER_HOME/gc-ledger.jsonl` where `BUILDER_HOME`
  comes from `core/config.py`'s settings (default `~/builder-ide`); the
  constructor's `ledger_path` overrides it.
- Every `gc` call is `subprocess.run([...], cwd=ledger_dir, capture_output=True,
  text=True, timeout=self.timeout)`, and the `--ledger <abs path>` global flag
  is always passed.

**Tests** (`tests/test_gc_bridge.py`) — these must pass **with and without** the
gc binary present:
- The binary is found via `$BUILDER_GC_BIN` and via the default path; when
  neither exists `enabled` is `False` and every method returns `None` without
  raising (the fail-open test).
- The `--ledger` path passed to gc is the bridge's ledger path, absolute.
- `open_job` / `award` / `checkpoint` / `close` build the exact argv the
  contract says (assert on the recorded call), with `--json` last.
- `close` maps the three verdicts onto the three flag sets.
- The ledger scan finds a job by `external_id` and recognises an award.
- A gc that exits non-zero makes the method return `None`, not raise.
- Tests that need a real gc binary are marked
  `@pytest.mark.skipif(not bridge_available(), ...)` and use the built binary
  at `tools/gc/target/release/gc` when it is there.

---

## Task 3: the wiring — award, checkpoint, close, reputation

**Files:**
- Modify: `core/svc/work_orders.py`
- Modify: `core/svc/report.py`
- Modify: `core/night/runner.py`
- Modify: `core/api.py`
- Modify: `core/config.py` (only if a settings field is needed)
- Create: `tests/test_gc_integration.py`

**3.1 Award — `core/svc/work_orders.py`.**
- `WorkOrdersService.confirm(...)` gains an optional `seat: str | None = None`.
  After the `wo.confirmed` event is appended (`core/svc/work_orders.py:175-185`),
  the service opens the gc contract: `gc job new` with the derived estimate,
  ceiling, deadline and goal line, and — when a seat is known — the bid and the
  award.
- `WorkOrdersService.start_attempt(wo_id, engineer)` awards the contract when
  it is not awarded yet, with `engineer` as the seat.
- Every gc call is wrapped so a missing or failing gc changes nothing:
  builder-ide's own events are written first, and the gc call happens after.

**3.2 Checkpoint — `core/night/runner.py`.**
- `NightRunner.__init__` gains one optional keyword argument:
  `gc_contracts: GcContractResolver | None = None`. `None` means the runner
  behaves exactly as today.
- `GcContractResolver` is a tiny protocol in `core/night/runner.py`:
  ```python
  class GcContractResolver(Protocol):
      def contracts_for(self, task_id: str) -> list[dict]:
          """The open gc contracts for a task: [{"external_id":…, "seat":…}]."""
  ```
- In `_run_attempt` (`core/night/runner.py:682-815`), after the executor
  returns and the burn is known (`actual_cost.wall_minutes`), the runner asks
  the resolver for the task's contracts and reports the cumulative burn
  (`self._gc_burn[task.id] += actual_cost.wall_minutes`) as a gc checkpoint.
- **If a checkpoint comes back with `stop_required`, the attempt is cut as a
  rail event, not a crash**: `self.queue.cut(task.id, reason)` with the gc
  message, and the task is settled with `state="cut"`. The reason names gc's
  numbers ("the 80% stop line fired at 84% of the bid"). No exception escapes.
- The runner's cumulative burn is per task, reset when the task is re-queued.

**3.3 Close — `core/svc/report.py`.**
- `ReportBuilder.build(night_id)` closes the night's open gc contracts before
  it renders: for every work order of that night in a terminal state
  (`landed`, `failed`, `kept`, `rejected`, `cancelled`), `gc close` with the
  order's actual crew-minutes (`spend_so_far.wall_minutes`) and the verdict:
  `landed`/`kept` → pass, `failed`/`rejected` → fail, otherwise inconclusive.
- The doc gains a `gc` key: the closed contracts (job id, seat, verdict,
  actuals) and the per-builder reputation rows.
- The doc's shape otherwise does not change: the existing keys keep their
  names and meanings.

**3.4 Reputation — the read API.**
- `core/api.py` gains `GET /v1/gc/reputation?seat=<name>&class=<name>` →
  `{"reputation": [...], "count": n}`. With no `seat`, every seat is returned.
- Each row is:
  ```python
  {"seat": "Architect", "class": "build-feature", "jobs": 18,
   "on_time": 14, "on_time_total": 18, "on_time_rate": 0.777,
   "on_time_known": True, "goal_line_rate": 0.85,
   "goal_line_inconclusive": 2, "inside_bid_rate": 0.9,
   "debt_min": 0, "retools": 2, "reputation": 92, "blocked": False,
   "line": "Architect: 14 of 18 on time, 2 retools"}
  ```
  `on_time` is `None` and `on_time_known` is `False` when gc has no deadline
  for the pair — the honest "n/a", never a flattering 0 %.
- The row is derived from gc's `report --json`, never recomputed in Python.

**3.5 The end-to-end test** (`tests/test_gc_integration.py`):
confirm a work order → run a scripted night attempt → close → read
reputation, against the **real built gc binary**. It is skipped when the binary
is absent (`@pytest.mark.skipif`), so the suite is green either way.

---

## Task 4: the report and the commits

- `FOLD-REPORT.md` at the worktree root: what was built, the files touched, the
  test evidence (the exact commands and their output), the open questions, and
  what was deliberately not done and why. The last line is
  `STATUS: DONE` (or `STATUS: BLOCKED: <reason>`).
- `tools/gc/README.md` and `tools/gc/docs/model.md` are updated for the new
  flags (`--external-id`, `--json`, `close --check inconclusive`) and the new
  report fields. builder-ide's package README for the bridge
  (`core/svc/README.md` if it exists, else a new one) is written.
- Commits on `fold-gc`, in this order:
  1. `feat(gc): --external-id, --json on the writing commands, an inconclusive close`
  2. `feat(gc): the report JSON carries retools and on_time_known`
  3. `feat(core): the gc bridge — a fail-open window onto the general contractor`
  4. `feat(core): a confirmed work order is a gc contract`
  5. `feat(core): the night checkpoints gc; the 80% stop line cuts the task`
  6. `feat(core): the morning report closes the contracts and reads the reputation`
  7. `test(core): the end-to-end walk, against the real gc binary`
  8. `docs: the gc bridge, the mapping, and what it does not do`
  9. `docs: the fold report`
- Do not push. Do not merge.
