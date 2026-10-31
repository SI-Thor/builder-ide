# The night runner

The core's **overnight loop**: while you sleep, the builders work a queue of
goals under a budget of hours and model time, and in the morning there is a
page that says what happened — what was kept, what was cut, what failed, and
what the night tried and dropped.

This package is the seat that runs the night. It is deliberately small and
deliberately honest:

* the **log is the source of truth** — the status line, the cut and the
  morning report are all *folds* over the audit log, so they survive the
  failure they describe (a `kill -9` mid-night, a box that reboots);
* **nothing is narrated** — the status line is computed from the log, never
  written by hand;
* **nothing is invented** — the critic refuses to score a variant it has no
  score for, and the power meter reads the board's *measured* rails, so the
  morning's joules are a measurement rather than a plausible-looking zero.

It is built against **core-spec v2** (`docs/design/core-spec.md`), and the
seat's handover note — what was built, the mornings it produces, where it
departs from the spec — is [`docs/lab/night-runner.md`](../../docs/lab/night-runner.md).

## What it does, in one night

1. **Start.** The night's rails are written into the log: hours of GPU, cents
   hosted, wall-clock minutes, the model-load caps, and the **depth policy**
   (how many variants a round, how many rounds, the ε the loop stops below).
2. **Pre-flight.** The lane is free? The client detached? If not, the
   morning says *did not run* — and *why*: off, busy, no plan, or blind.
3. **Work the queue.** Each task is admitted against the rails *before* the
   spend, and then it runs.
4. **Iterate.** A task is **no longer one attempt**. For each goal the night
   generates **N variants**, scores each with the critic, keeps the best and
   **refines from it** (warm start) for up to **K rounds**, or until the
   score stops improving by more than **ε**. The bar can cut a loop short,
   and the morning says where.
5. **Stop.** The night writes its status and the report page — HTML, JSON and
   text — over the log.

## Running the tests and a simulated night

Everything runs from the worktree's own venv:

```bash
cd ~/lm-wt/night-runner

.venv/bin/python -m pytest -q          # the whole suite
.venv/bin/python -m pytest -q tests/test_loop.py    # the iterator loop alone
.venv/bin/python -m core.night --list                # every morning and its first line
.venv/bin/python -m core.night --scenario clean --out reports/
```

`--scenario` takes one of `clean`, `failures`, `rail-cut`, `reboot`,
`degraded`, `did-not-run`, `iteration`, `iteration-rail-cut`,
`iteration-stalled`. Each writes `report.html`, `report.json` and
`report.txt` into `--out`.

The simulated nights are in `core/night/nights.py`. A night is a **log**, a
**status** and a **report** — you can fold any of them again, at any time,
and get the same answer:

```python
from core.night.nights import iteration_night

night = iteration_night()
night.status.first_line   # "ran as planned · nothing failed"
night.report.iterations[0].winner.label   # "refined c"
night.html()              # the whole page, as a string
```

## The night's arithmetic

The budget is not a set of typed-in numbers. It is arithmetic over
measurements taken on this box, and it lives in
[`core/night/cost/`](cost/README.md):

* a **cost model** — what each job kind costs (an Infinigen stage by scene
  type, a TRELLIS.2 prop at each resolution, a render at each rung of the
  ladder, a critic's verdict), with p50 and p95 from the recorded samples,
  in GPU-minutes, CPU-lane minutes, wall minutes, hosted cents, iterations
  per goal and **joules**;
* a **price** — a job kind as a task carries it: the p50 is the **ask** and
  the p95 the **rail** the task is held to, with the band's basis and source
  beside them. A task names its kind and the model prices it; a client that
  files its own number gets an **override**, recorded and shown, and is held
  to its own number rather than to the model's;
* an **admission check** — does tonight's plan fit the rails, and what is
  cut, **named**;
* the owner's **two lines** — what tonight will cost, and whether it fits —
  written into `night.started` and read back by the morning. The API's plan
  slate shows the same two lines before the night starts, and a slate that
  does not fit is refused at the door with the cut named;
* a **refresh path** — when the box records new timings, the model's data
  follows: the recording is re-pinned by md5 and row count, and `--check`
  says whether it has moved on since.

The joules are the board's **measured** rails, so the morning's line has a
fourth number that is a measurement rather than an estimate. The only
estimate left in the model is the owner's attention per decision, and the
page still marks it `[e]`.

## The seams it stubs

Everything below is a small protocol, implemented here by a scripted stand-in.
The real implementations land later without changing the night runner.

| Seam | What it answers | Stand-in |
|---|---|---|
| **the ledger** (`ledger.py`) | append an event; read it back | `InMemoryLedger`, `SQLiteLedger` — the real one replaces it as a constructor argument |
| **the event set** (`events.py`) | the closed set of event types (§1.8) | taken from the recipe store's copy when that package is importable, so the two seats cannot drift |
| **the recipe store** | branches, edits and versions | read from the log, never written by this seat |
| **the work** (`executor.py`) | *what will this cost and which model does it need* (checked before the spend) and *run it* — now for a **variant**, not only a task | `ScriptedExecutor` with scripted failures, stalls and per-variant scripts |
| **the critic** (`iterate.py`) | *how good is this variant?* — the score that picks the winner | `ScriptedCritic`; it **raises** on a variant it has no score for |
| **the variant source** (`iterate.py`) | *what else could we try?* — seeds, parameter perturbations, alternative recipe edits | `PerturbationSource` (deterministic) and `ScriptedVariantSource` |
| **the power meter** (`iterate.py`) | *what did the attempt cost in joules?* | `RailPowerMeter` — reads the board's **measured** rails (`docs/lab/exp-engines.md` §4.4: the whole box drew 47.5 W on the `VIN` rail); `NullPowerMeter` is the stand-in for a box with no rails |
| **the client's presence** (`runner.py`) | is the ProArt still watching? | a `presence` callable; the API half's `client.attach` / `client.detach` events are the durable form |
| **the lane** (`runner.py`) | is the GPU free of somebody else's job? | a `lane_free` callable; "blind" is an answer the status line respects |

## How it connects to the core

* **The log is the contract.** The night runner writes audit events and
  nothing else. The core's own tables are projections of that log (§1.0),
  and this package ships its own projection — `NightProjection` — which is
  how the status line and the morning report are built.
* **The recipe store is the sibling half.** It emits the recipe group of the
  closed event set; the night runner emits the continuity, job and critic
  rows. The two agree on the type names because the night runner *imports*
  the recipe store's set when it can.
* **The API half answers for the box.** Presence and lane telemetry come in
  as `client.attach` / `client.detach` and pre-flight rows; the runner asks
  for them through callables so it never has to know the transport.
* **The taste ledger is the owner's, not the night's.** The runner writes a
  *verdict*, never a taste write (§1.7): what the critic kept is the
  night's decision, and whether *you* like it is yours to say in the
  morning.
* **The builders' bets are sealed before the render.** A prediction is
  sealed and committed *before* its job is enqueued (§5.1), and scored after
  it. In a loop, the seal covers the goal and is written once, before the
  first variant's job.
* **The loop rides on existing events.** The event set is closed and a new
  type is a schema change (§1.8), so a variant attempt is a *job*: the
  variant rides on the job's request, its score on the job's outcome, and
  the loop's own record — the winner, the rounds, the quality gained in each
  — rides on the task's own row.

## The files

| Module | What it owns |
|---|---|
| `models.py` | the records: `Rail`, `Task`, `Job`, `Night`, `Actor`, `AuditEvent`, `IterationPolicy` |
| `cost/` | the measured cost table, the admission check and the owner's two lines (see [its README](cost/README.md)) |
| `events.py` | the closed set of audit event types (§1.8) |
| `ledger.py` | the ledger seam: `append` / `events` / `last_seq` |
| `projection.py` | the fold: the night, its tasks, ticks, spend, loads, failures and the loop's attempts |
| `rails.py` | the three-axis rail, admission before spend, the graduated throttle, the per-model load cap |
| `queue.py` | the task queue: the order, the cut, the park, Magnus's lane closing hard at his hour |
| `heartbeat.py` | `night.tick` rows and the gaps between them |
| `iterate.py` | **the iterator's seams**: variants, the critic, the power meter, the depth policy |
| `executor.py` | the work seam — simulated here, the GPU stations later |
| `runner.py` | the night's lifecycle: start, pre-flight, detach-or-timeout, the queue, **the loop**, the stop |
| `resume.py` | the boot sequence: rebuild, requeue, resume or stop cleanly |
| `status.py` | the computed status line: the four values and the three `did not run` variants |
| `report.py` | the morning report: the data, the static HTML, the text mode |
| `nights.py` | the simulated nights and the four-mornings suite |
| `__main__.py` | `python -m core.night --scenario clean --out reports/` |
