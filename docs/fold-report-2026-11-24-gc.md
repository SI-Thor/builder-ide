# Fold report: `gc` wired into builder-ide's night

**Branch** `fold-gc` (worktree `/home/proart/lm-wt/fold-gc`) — 9 commits on top of
`22c3d38`. Not pushed. Not merged.

---

## 1. What was built

builder-ide now holds a builder to its estimate the way `gc` holds a
subcontractor to its bid. `gc` stays a Rust binary; a fail-open Python bridge
drives it over `subprocess` and owns gc's ledger, which lives next to
builder-ide's own in the store's data directory.

The four goals of the brief, and where each one landed:

| goal | where | what it does |
|---|---|---|
| **1. Award** | `core/svc/work_orders.py` | a confirmed work order opens a gc **job**: `gc job new --external-id <work order id>`, with the order's two price lines as the estimate, the `per_order` rail as the ceiling and the night's rails as the job-time. The seat is hired with a bid and an award. |
| **2. Checkpoint** | `core/night/runner.py` + `core/svc/gc_night.py` | the night reports its burn to gc as a checkpoint (cumulative per task). When gc answers `stop_required`, the attempt is **cut** the way the night cuts any work — a queue mark with a reason, never an exception. |
| **3. Close** | `core/svc/report.py` | the morning report closes the night's contracts with a three-valued verdict and the actuals, and adds a `gc` section to the doc. |
| **4. Reputation** | `core/api.py` + `core/svc/gc_night.py` | `GET /v1/gc/reputation?seat=…&class=…` returns a builder's gc record: on time, inside the bid, goal-line rate, debt, retools, and a one-line sentence. |

### The mapping

| gc | builder-ide | derived from |
|---|---|---|
| job | one work order | keyed by `external_id` = the work order id |
| class | the order's gc class | the serving task's `kind`, else `"build-feature"` |
| estimate | `wo.estimate.build_verify + generate_test` (wall minutes) | the order's two price lines |
| ceiling (`budget_min`) | `wo.budget.per_order.wall_minutes`, else the estimate | the per-order rail |
| deadline (`deadline_min`) | the night's `rails.wall_minutes`, else the ceiling | the job-time envelope |
| goal line | a `test_suite` acceptance check carrying a `cmd` → `--accept-cmd`; otherwise report-kind | the order's acceptance |
| sub (seat) | `Attempt.engineer` | the seat that took the attempt |
| bid | computed by gc from the seat's track record | — |
| award | `gc award --auto` | — |
| checkpoint | the night's cumulative burn | the attempt's wall minutes |
| close | the order's terminal state | landed/kept → pass, failed/rejected → fail, cancelled → inconclusive |
| reputation | `gc report --json` | read back, never recomputed in Python |

Nothing is stored twice: the mapping between the two ledgers is **recomputed
from gc's own hash-chained rows** (`job.new.external_id`), which is the same
rule the rest of the repo follows — audit by recomputation, not by trust.

### The gc side (small, additive)

`tools/gc/` gained four things, all of them additive and all of them tested:

1. **`gc job new --external-id ID`** — stores the caller's own id in the
   `job.new` row. This is what binds a gc job to a builder-ide work order.
2. **`--json` on `job new`, `bid`, `award`, `checkpoint`, `close`** — one line
   of JSON on stdout, **last**, holding exactly the row body that was written
   to the ledger. The human-readable lines are untouched, so every existing
   test and every human reader is unaffected.
3. **`gc close --check inconclusive`** on a report-kind job. The error message
   already promised this (`tools/gc/src/main.rs`, the report-kind branch) and
   the code did not do it; now a close can say "could not tell".
4. **`gc report --json` seat rows** gain `on_time_jobs`, `on_time_total`,
   `on_time_known` and `retools`. `on_time_rate` is unchanged and equals
   `on_time_jobs / on_time_total` when there is a denominator. Before this,
   "no recorded deadline" and "never on time" both read `0`.

### The bridge (`core/svc/gc_bridge.py`)

The bridge finds the binary through `$BUILDER_GC_BIN` and then
`tools/gc/target/release/gc`, passes gc's global `--ledger <absolute path>` on
every call, and reads gc's ledger back to recompute which job a work order is
bound to and whether it is already awarded.

**It fails open.** With the binary absent, with a failing gc, with an
unreadable ledger: every method returns `None` and raises nothing, and each
kind of failure is logged **once** (not once per call — a night that asks for
a hundred checkpoints must not write a hundred identical lines). A
builder-ide without gc behaves exactly as a builder-ide without gc did before
this module existed.

`open_job` and `award` are idempotent: a contract that already has a job, or
an award, is left alone.

### The stop is a rail event, not a crash

`NightRunner` gained one optional argument, `gc: GcSeam | None = None`. With
it absent, the runner is byte-for-byte the night it was. With it present,
after the executor returns and the burn is known, the runner reports the
cumulative burn to gc. If gc answers `stop_required`, the attempt's outcome
becomes `"cut"` and its reason carries gc's own numbers:

> the 80% stop line fired at 96% of the bid — the goal line had not passed;
> the general contractor must re-scope, extend or cancel

which the night writes through `queue.mark(task.id, "cut", reason)` — the
existing vocabulary (`core/night/queue.py`). Nothing raises; the iteration
loop stops opening rounds on that contract.

---

## 2. Files touched

| file | change |
|---|---|
| `core/svc/gc_bridge.py` | **new** — the fail-open bridge (529 lines) |
| `core/svc/gc_night.py` | **new** — `GcNightSeam` (the seam the night calls) and `reputation_rows` (209 lines) |
| `core/svc/work_orders.py` | `file(..., serves=…)`; the contract is opened on confirm; the seat is hired on `start_attempt`; the gc derivations (estimate, ceiling, job-time, class, goal line) |
| `core/svc/report.py` | the morning closes the night's contracts and adds the `gc` section |
| `core/svc/__init__.py` | `Core.gc` — the bridge, built from `settings.home` |
| `core/svc/README.md` | **new** — what the gc wiring is, and that it is not wired into the driver yet |
| `core/night/runner.py` | the `GcSeam` protocol, the `gc` argument, the checkpoint, the cut |
| `core/api.py` | `GET /v1/gc/reputation` |
| `tools/gc/src/main.rs` | `--external-id`, `--json` on five commands, `close --check inconclusive` |
| `tools/gc/src/model.rs`, `accounting.rs`, `seed.rs` | `Job.external_id` (one line each in the two struct literals that must name it) |
| `tools/gc/src/report.rs` | the four new seat-row fields |
| `tools/gc/tests/cli.rs` | +5 CLI tests (573 lines added) |
| `tools/gc/README.md`, `tools/gc/docs/model.md` | the new flags and the new report fields |
| `tests/test_gc_bridge.py` | **new** — 31 bridge tests (777 lines) |
| `tests/test_gc_integration.py` | **new** — the end-to-end walk (209 lines) |
| `docs/superpowers/plans/2026-11-24-gc-into-night.md` | **new** — the plan this work followed |

Untouched: `worlds/`, `engines/`, `core/svc/gc_bridge.py`'s neighbours, the
`.baseline-fails.txt`, the shared venv.

---

## 3. Test evidence

### `cargo test --release` in `tools/gc`

```
$ cd tools/gc && cargo test --release
running 41 tests
test result: ok. 41 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.26s
running 20 tests
test result: ok. 20 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.22s
```

**61 passed, 0 failed** — the original 56 (41 unit + 15 through the real
binary) are unchanged and green, plus 5 new CLI tests. The crate is still
std-only, with no crates.io dependencies.

### The Python suite, against the baseline

```
$ /home/proart/projects/builder-ide/.venv-local/bin/python -m pytest -q \
      -p no:cacheprovider --continue-on-collection-errors
...
ERROR tests/drift/test_gate.py
ERROR tests/physag/test_builder_and_check.py
ERROR tests/physag/test_guards.py
ERROR tests/physag/test_segment.py
ERROR tests/physag/test_spec.py
ERROR tests/rewind/test_ledger.py
ERROR tests/sim/test_beacons_equivalence.py
ERROR tests/sim/test_beacons_rules.py
ERROR tests/usd - ModuleNotFoundError: No module named 'pxr'
FAILED tests/genbatch/test_mesh.py::test_the_old_measurement_can_still_be_asked_for
FAILED tests/genbatch/test_o3d_geometry.py::test_a_mesh_over_the_cap_is_unchecked_not_decimated
FAILED tests/genbatch/test_o3d_geometry.py::test_a_tighter_cap_declines_the_same_way
FAILED tests/genbatch/test_o3d_geometry.py::test_the_check_can_be_turned_off
FAILED tests/judge/test_backends.py::test_the_jev_backend_refuses_to_call_without_a_key
5 failed, 2113 passed, 41 skipped, 16 deselected, 8 warnings, 9 errors in 93.42s (0:01:33)
```

The set of FAILED/ERROR test ids is **identical** to `.baseline-fails.txt` —
verified by diffing the two sets:

```
$ diff <(cut -d' ' -f1,2 .baseline-fails.txt | sort) <(awk '{print $1" "$2}' now-fails.txt | sort)
SAME SET of failing test ids (9 ERROR + 5 FAILED)
```

The one textual difference is that pytest appends its reason to the
`tests/usd` collection error (`ERROR tests/usd - ModuleNotFoundError: No
module named 'pxr'`) where the baseline line carries only the path. The
error is the same one (the USD extra is not installed on this laptop); the
baseline file was not edited. **Zero new failures.** 2113 passed against a
baseline of 2081 — the 32 new tests are the gc bridge's and the end-to-end
walk's.

### The bridge passes with and without the gc binary

```
$ BUILDER_GC_BIN=/nonexistent/gc python -m pytest -q -p no:cacheprovider \
      tests/test_gc_bridge.py tests/test_gc_integration.py
32 passed in 0.54s
```

With the binary absent, the same 32 tests pass — the bridge is inert and
builder-ide carries on. With the binary present, the real-binary tests run
instead of skipping.

### The end-to-end walk, against the real built gc binary

```
$ python -m pytest -q -p no:cacheprovider tests/test_gc_integration.py -v
tests/test_gc_integration.py .                                           [100%]
1 passed in 0.15s
```

It walks the whole way and asserts against **gc's own ledger rows**, not
against memory:

1. **confirm** — the work order is filed (naming the plan goal it serves),
   compiled and confirmed; gc's `job.new` row carries
   `external_id == <work order id>`, `estimate_min == 20.0`,
   `budget_min == 40.0` (the per-order rail), `deadline_min == 560.0` (the
   night's rails), `class == task.kind`, and a scope that says where the class
   came from.
2. **award** — `start_attempt(..., "architect")` produces gc's `bid.new` and
   `award` rows, both naming the seat.
3. **night** — a scripted attempt burns 24 wall-minutes; gc's checkpoint row
   reads `crew_used_min == 24.0` and `stop_required is True` (the bid was 25
   minutes — gc's 1.25 prior factor on the 20-minute estimate — so 24 is 96 %
   of it).
4. **the stop** — the night's own log holds a `night.task.state` event with
   `state == "cut"` and gc's reason on it. No exception.
5. **close** — the morning closes the contract: gc's `close` row reads
   `actual_crew_min == 24.0` and `acceptance_verdict == "fail"`; the report's
   `gc.contracts[0]` carries the work order, the gc job, the seat, the
   verdict and the actuals.
6. **reputation** — `GET /v1/gc/reputation` returns 200 and a row for the
   seat with gc's own numbers (jobs 1, 1 of 1 on time, inside-bid 1.0,
   reputation 60.0 — in gc's 0–100 range).

---

## 4. Open questions

1. **The seam has no production call site.** `NightRunner` takes
   `gc=GcNightSeam(core)` as an optional argument and the mechanism works, but
   nothing in production passes it. The reason is structural and pre-existing:
   the spine's night service (`core/svc/nights.py`) writes the night's rows and
   never constructs a runner, the runner seat drives the attempts, and the one
   production driver (`core/genbatch/night.py:249`, the prop seat's night) runs
   prop tasks against its own SQLite ledger, not the store's work orders. The
   two halves are not joined in this repo, and joining them is a bigger change
   than this brief. The seam, the checkpoint and the cut are proven by the
   end-to-end test.
2. **The award moment.** The brief asks for "a gc job + bid + award" when a
   work order is confirmed. Implemented: the **job** is written at confirm; the
   **bid and award** are written when the builder is seated — at
   `start_attempt`, or at confirm when the caller passes `confirm(..., seat=…)`.
   The reason is gc's own model: a bid is *a seat's promise* and the award is
   the hiring of that seat, and a work order names no seat until an attempt
   starts. Recording a bid at confirm time would mean inventing a seat name
   that no builder had taken. `confirm` grew the optional `seat` parameter so
   a caller that does know the seat can have all three at confirm.
3. **The morning report closes contracts, so building it is not a pure read.**
   `ReportBuilder.build()` closes the night's contracts before it renders. The
   brief puts the close at the morning report, and the close has to happen
   somewhere; the alternative is a separate "close the night" step that
   nothing calls. A second build is safe — gc refuses a second close and the
   bridge reads the existing job id back — and the doc is byte-identical after
   a cold reopen (the existing test still passes).
4. **The "80%" in the cut reason is a constant.** gc does not put its
   `--stop-ratio` in the checkpoint body, so the reason says "the 80% stop
   line". Every contract opened through the bridge carries gc's default stop
   ratio, because the bridge never asks for another one; the *percentage of
   the bid* in the reason is gc's own number, read out of the checkpoint body.
5. **A terminal order with no gc contract still gets a report row**
   (`"job": null`). That is honest — the order was closed, there was simply no
   contract — but it may be noise in the morning.
6. **`WorkOrder.serves` was a stub.** The field exists on the model and the
   justification graph reads it, but nothing set it. `file(..., serves=…)`
   now sets it, and the fold carries it without a change (the fold copies
   whatever the filed work order holds). This is what lets the night find the
   contract for a task.

### One incidental fix, outside the brief

`WorkOrdersService.record_spend` called `NightsService.check_thresholds`,
but that method lives on `BudgetService` — the spend was written and then an
`AttributeError` was raised. The close needs that spend (it is the contract's
`crew_min`), so the call was fixed. It was a live bug on the path this work
touches; it is called out here rather than buried.

---

## 5. What was deliberately not done

- **gc was not rewritten in Python.** It stays a Rust binary; the bridge
  drives it over `subprocess`. The only Rust changes are the four additive
  ones listed above.
- **No new packages.** Nothing was installed into
  `/home/proart/projects/builder-ide/.venv-local` or anywhere else; the
  bridge uses only the standard library plus the repo's own modules.
- **No new audit-event types.** builder-ide's event sets are closed
  (`core/night/events.py:1-8`). gc's records ride in gc's own ledger, and the
  builder-ide side writes nothing new — the cut is an ordinary
  `night.task.state` event with a reason.
- **`worlds/`, `engines/` and unrelated seats were not touched.** In
  particular `core/genbatch/night.py` (the prop seat's night driver) was left
  alone: adding a `gc=` parameter there would have been plumbing for a night
  that runs prop tasks, which carry no work-order contracts.
- **The top README was not refreshed.** CLAUDE.md reserves that for the
  director when a report lands or a branch merges; this branch is neither
  merged nor landed, so the status table is left as it is.
- **The seeded `tools/gc/ledger.jsonl` was not touched**, and `gc seed import
  --rebuild` was never run — the bridge never passes `--rebuild`.
- **Nothing was pushed and nothing was merged.**

---

## 6. Commits

```
6b888d2 docs(svc): the gc wiring — what the bridge is, and that it is not wired into the night driver yet
d7e3923 feat(gc): the report JSON carries retools and on_time_known
985ccd2 feat(gc): --external-id, --json on the writing commands, an inconclusive close
0f1baba test(core): the end-to-end walk, against the real gc binary
453cb41 feat(core): the reputation read API
45308e9 feat(core): the morning report closes the contracts and reads the reputation
9e02ad6 feat(core): the night checkpoints gc; the 80% stop line cuts the task
1a19bf2 feat(core): a confirmed work order is a gc contract
b4d9048 feat(core): the gc bridge — a fail-open window onto the general contractor
```

The work was done by three subagents on disjoint files (the Rust CLI, the
bridge, the wiring), reviewed here, and integrated on `fold-gc`. The plan is
`docs/superpowers/plans/2026-11-24-gc-into-night.md`; the agents' own reports
are under `.superpowers/sdd/2026-11-24-gc-into-night/`.

---

STATUS: DONE
