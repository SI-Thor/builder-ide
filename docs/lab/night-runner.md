# The night runner and the morning report (seat: night-runner)

Branch `night-runner`. Built against **core-spec v2** (`docs/design/core-spec.md`)
and plan item 10 (Week 2): *the minimal night runner and the morning report
page*.

This is the seat's handover note: what was built, the mornings it produces,
the seams the other seats fill, and where it departs from the spec.

## What is here

| Module | What it owns | Spec |
|---|---|---|
| `core/night/models.py` | the records: `Rail`, `Task`, `Job`, `Night`, `Actor`, `AuditEvent` | §1.9, §1.3 |
| `core/night/events.py` | the closed set of audit event types (§1.8), taken from the recipe store's copy when it is installed | §1.8 |
| `core/night/ledger.py` | the ledger seam: `append` / `events` / `last_seq`, with an in-memory and an fsynced SQLite implementation | §1.0, §5.1 |
| `core/night/projection.py` | the fold: the night, its tasks, ticks, spend, loads and failures, rebuilt from the log alone | §1.0, §5.4 |
| `core/night/rails.py` | the three-axis rail, admission before spend, the graduated throttle, the per-model load cap | §5.5 |
| `core/night/queue.py` | the task queue: the order, the cut, the park, Magnus's lane closing hard at his hour | §1.9, §3.2 |
| `core/night/heartbeat.py` | `night.tick` rows and the gaps between them | §3.4 |
| `core/night/status.py` | the computed status line: the four values and the three `did not run` variants | §3.4 |
| `core/night/runner.py` | the night's lifecycle: start, pre-flight, detach-or-timeout, the queue, the stop | §3.2, §3.4 |
| `core/night/resume.py` | the boot sequence: rebuild, requeue, resume or stop cleanly | §5.2 |
| `core/night/executor.py` | the work seam — simulated here, the GPU stations later | §5.5 |
| `core/night/report.py` | the morning report: the data, the static HTML, the text mode | §3.2.9 |
| `core/night/nights.py` | the simulated nights and the four-mornings suite | §3.4, plan M2 |
| `core/night/__main__.py` | `python -m core.night --scenario clean --out reports/` | — |

## The mornings it produces

The status line is **computed from the log**, never narrated (§3.4). The nine
scenarios in `core/night/nights.py` cover every morning the product can wake
up to:

| Scenario | First line | What the report says |
|---|---|---|
| clean | `ran as planned · nothing failed · 1 parked` | two tasks kept, one question parked, the tally shows one hit and one miss with the denominator |
| failures | `ran short — 1 task failed: hollow mesh from the image-to-3D model` | the failure leads, with its artifact, and the night counts one kept and one reverted |
| rail cut | `ran short — 0.5 lane-h of the ask was cut at the 80% bar; Rope the jetty is re-queued for tonight` | the cut is named *and* the work that was dropped is named; the task waits for tomorrow |
| reboot | `ran short — 61 min lost to a reboot` | the night resumed from its last sealed step; the lost time is in the report's "lost time" section |
| degraded | `ran degraded — one batch stalled 41 min on the lane · the ProArt stayed attached — the deadline started the batches 30 min late · nothing failed outright` | contention named, the late start named, and the standing exits still there |
| did not run (off) | `did not run — the Thor was off. Nothing ran; nothing was lost. Your plan is unstarted, unchanged.` | the plan is re-offered verbatim: *start now · tonight · drop it* |
| did not run (busy) | `did not run — the GPU spent the night on your render job. Ours queued and was never admitted.` | the same recovery offer — dark ≠ asleep ≠ busy, said in words |
| did not run (no plan) | `did not run — no plan was started.` | nothing to re-offer, and nothing claimed |
| did not run (unknown) | `did not run — unknown (no telemetry)` | a status line may be uncertain; it is never fabricated |

The report page is a **static file over the ledger** — no panel-side state, no
`<script>` — in the spec's order: status line, failures, the cut named, the
night's numbers (no single prediction score), the branches (the two standing
exits included), the parked questions triaged to three plus a count, the
landed work orders, the lost time, the tally per builder × claim type with
denominators, the three-number line, and then "The box".

## The seams the other seats fill

Everything below is stubbed here, behind a protocol, and is listed so the
director knows what is waiting:

1. **The real ledger** — `core/night/ledger.py` implements the
   `append` / `events` / `last_seq` protocol, which is deliberately the same
   shape as `builder_recipe.ledger.Ledger` on the core-recipe branch. When
   half A lands, the real ledger is a constructor argument; nothing else
   changes.
2. **The event-type set** — `core/night/events.py` carries the spec's closed
   set (§1.8) and *prefers the recipe store's copy* when that package is
   importable, so the two seats cannot drift.
3. **The recipe store** — the night's branches, edits and versions are read
   from the log, not written by this seat. The report counts `edit.proposed`
   rows as recipe edits; the branch list is the recipe store's.
4. **The work** — `core/night/executor.py`'s `TaskExecutor` is the seam where
   the engine and the GPU stations land: they answer *what will this cost
   and which model does it need* (checked before the spend) and *run it*.
5. **The client's presence** — the runner asks a `presence` callable whether
   the ProArt is still watching; the API half's `client.attach` /
   `client.detach` events are the durable form of that answer.
6. **The lane** — the runner asks a `lane_free` callable; the API half's
   telemetry answers it, and "blind" is an answer the status line respects.
7. **The predictions' author** — the builders seal their bets; the runner
   writes the seal *before* the render job is enqueued (§5.1) and records the
   Critic's verdict after it, never a taste write (§1.7).

## Departures from the spec, and why

1. **"The box" comes last.** The spec's page order (§3.2.9) has seven items
   and does not mention "The box"; M2 requires the section. It is appended
   after the three-number line so the spec's order is untouched.
2. **The recovery offer sits under the status line.** §3.4 says every
   `did not run` morning "ends identically" with the plan re-offered. It is
   the same words in all variants, but placed under the status line, where
   the decision actually is, rather than at the foot of the page.
3. **The attention hours are an estimate, and say so.** The number of
   decisions is measured (parked questions, work orders, one branch
   choice); the hours are `decisions × 15 min` and are rendered `[e]`. The
   spec's own example is 2 h for 9 decisions; the rate is a constant here
   and is labelled an estimate rather than dressed up as a measurement.
4. **A `night.tick` carries a `kind`.** The spec's tick is "a wall-clock row
   plus every sealed step". Contention and the late batch start are facts
   about the same window, so they ride on the tick's payload
   (`stall`, `batches`) rather than inventing new event types — the event
   set is closed and new types are a schema change (§1.8).
5. **The stall is not lost time.** A stalled batch keeps the core alive, so
   the heartbeat keeps ticking; only a *gap* in the ticks is lost time. The
   two are therefore separate numbers on the morning.
6. **A task's own rail may be unset.** A task with a zero rail is not
   refused by the per-task check (a zero rail would otherwise refuse
   everything); it is bounded by the night's rail only.
7. **`branch.created` is the recipe store's event.** The runner writes it
   only to carry the branch into the morning's branch list; the recipe
   store owns the branch itself, and the two halves agree on the type name.

## How to reproduce

```bash
cd ~/lm-wt/night-runner            # this worktree
.venv/bin/python -m pytest -q      # the whole suite, green
.venv/bin/python -m core.night --list              # every morning and its first line
.venv/bin/python -m core.night --scenario clean --out reports/
.venv/bin/python -m pytest tests/test_budget.py -s # the measured clocks
```

The measurements are in [morning-report-clock.md](morning-report-clock.md).
