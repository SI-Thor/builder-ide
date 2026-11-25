# The model

What `gc` knows, how it decides, and which of its numbers are measured.

Casey's words are the names. A **job** is what the general contractor wants
done. A **bid** is what a subcontractor says it will cost. An **award** is the
decision to hire. A **close** is the job finishing, with the numbers.

---

## 1. The entities

### Job

Written by the general contractor.

| field | what it is |
|---|---|
| `id` | `J001`, `J002`, ... in the order the jobs were written |
| `external_id` | the caller's own id of the job — a builder-ide work order, a ticket; empty when nobody said |
| `title`, `scope` | what was asked, in words |
| `class` | `lab-experiment`, `merge-fix`, `research-read`, `build-feature`, `long-run-babysit` |
| `acceptance` | the goal line: a command that must exit 0, or a named metric with a threshold |
| `deadline_min` | the job-time allowance — the T-minus |
| `estimate_min` | the general contractor's own estimate of the crew-time the work needs |
| `budget_min` | the crew-time ceiling — the most the GC will pay |
| `penalty_per_day_min` | what a late day costs the subcontractor |
| `stop_ratio` | the fraction of the bid at which the sub must stop and report (0.8) |
| `clauses` | contract terms in the clause grammar (§10), checked at checkpoints and close |
| `reconstructed` | true when the job was rebuilt from history, not written by hand |

`estimate_min` and `budget_min` are separate on purpose. The estimate is the
GC's view of how much work the job is; the ceiling is the commitment. A bid
above the ceiling is allowed, but `gc award` says so out loud.

### Bid

Written by a subcontractor (a seat type plus its model: `zcode`, `mcode`,
`zflash`, `pi:MiMo`).

| field | what it is |
|---|---|
| `crew_min` | the promise: crew-time in minutes |
| `job_min` | the promise for job-time (the T-minus) |
| `confidence` | 0..1, how sure the seat is of its own bid |
| `milestones` | the plan of milestones |
| `computed` | true when the bid was computed from the track record |
| `proxy` | true when the "bid" stands for a plan allowance, not a promise (see §5) |
| `calibratable` | true when the run was clean enough to calibrate a bid from |
| `basis` | in words, where the numbers came from |

### Award, checkpoint, change order, close, retool

- **award** — one row: the job, the bid, the seat, the score that chose it and
  why. May carry `clauses` negotiated at award (same grammar as the job's,
  overriding by metric name).
- **checkpoint** — a report of burn: crew-time used, milestones done, the
  **verdict of the goal-line check** (§8), the metric values in play, the
  clause checks, the **spend-rate forecast** (§11), and whether the stop rule
  fired.
- **change order** — the GC re-scopes or extends: more crew-time, more
  job-time, a reason. The promise moves with it.
- **close** — the job finished. The goal-line verdict (re-run here, §9), the
  clause breaches and their penalties, actuals, overrun, penalty, debt, and
  how the crew-time was measured.
- **retool** — a seat in deep debt on a class is retooled (different model,
  better brief, a tool, smaller jobs) before it is hired on that class again.
  It is a ledger event with its reason.

---

## 2. The ledger

One JSON object per line in `ledger.jsonl`. Append-only.

```json
{"seq":0,"ts":"2026-11-01T00:55:00Z","kind":"job.new","body":{...},"prev":"0000...","hash":"3f68..."}
```

- `prev` is the hash of the row before it; the first row chains from 64
  zeros.
- `hash` is SHA-256 over a fixed field order (`seq`, `ts`, `kind`, `prev`,
  `body`), with a domain separator `gc-ledger-v1`. The JSON text of the row
  is not what is hashed, so the row can be re-serialised for reading without
  changing its hash.
- `gc verify` walks the chain and recomputes every hash. Change one byte of
  any row and it fails, naming the row.

The ledger is the only state. Every number in the report is either read from
a row or recomputed from rows — never remembered between runs. That is the
rule from `nursery-v2`: audit by recomputation, not by trust.

The clock: every row takes `--at ISO8601`, or `GC_NOW` (unix seconds), or
the system clock. With a fixed clock the same commands write byte-identical
bytes, which is what the determinism test checks.

---

## 3. The bid

### The factor

A seat's track record for a job class is the list of crew-times it used on
its **clean** finished runs on that class (clean = it crossed its goal line,
with no relaunch and no quota stop).

The **factor** is

```
factor = q80(crew-times) / median(crew-times)
```

Scale-free on purpose. A job of a class can be big or small, so the GC's
estimate sets the size and the seat's history says how much bigger than its
own median this seat runs at the 80th percentile. A bid is then

```
bid_crew_min = round(estimate_min * factor)
bid_job_min  = bid_crew_min
```

With no history on the class, the seat's other classes are used (shrunk
harder). With no history at all, the **prior factor of 1.25** applies: a bid
with no evidence behind it is an overbid, because overbidding beats
underbidding.

The shrinkage pulls the raw factor toward the prior:

```
factor = (n * raw + w * 1.25) / (n + w)      w = 2 (class), 4 (other classes)
```

### Confidence

```
spread = (q80 - q20) / median
base   = clamp(1 - spread / 4, 0.05, 0.95)
sample = sqrt(n / (n + 3))
confidence = clamp(base * sample, 0.05, 0.95)
```

No history at all: 0.30.

### Worked example (this is a test)

A seat's clean runs on a class: 40, 50 and 60 minutes. The GC's estimate for
a new job: 100 minutes.

- median 50, q80 = 50 + 0.6 * (60 - 50) = 56
- raw factor = 56 / 50 = 1.12
- shrunk = (3 * 1.12 + 2 * 1.25) / 5 = 1.172
- **bid = 117 crew-minutes**

A seat with no history at all bids 125 (100 * 1.25).

---

## 4. The award

`gc award --job J --auto` scores every bid on the job:

```
cost_score  = min_bid_crew / bid_crew                 (cheaper is better)
on_time     = the seat's on-time rate on the class, times (0.5 + 0.5 * confidence)
fit         = 1.0 if the seat has closed work on the class, else 0.4
score       = 0.40 * cost_score + 0.40 * on_time + 0.20 * fit
```

A seat with no history gets an on-time probability of 0.5: unknown is not
good. The highest score wins; ties break on the lower crew-time, then the
seat name, so the award is deterministic.

The award is refused when the seat is **in deep debt** on the class (see §6).

---

## 5. Crew-time: what is measured and what is estimated

This is the part to be careful with, so it is spelled out.

| seat | how it is billed | what the history gives |
|---|---|---|
| `zcode`, `zflash`, `zmain` | a flat plan on a five-hour window | wall time against that window |
| `mcode` | a flat plan, each run capped at 240 minutes (`desk.sh`) | wall time against that cap |
| `pi:*` | tokens | a token count, not minutes |

Every close row carries a `method`: `wall`, `tokens` or `estimated`.

**Measured**: the wall time of a lane's last run, from the seat output file's
birth time (the launch) to its last write (the exit). The output file is
recreated at every launch, so this is the last run, not the whole lane.

**Not measured, and kept separate**: the lane's total occupancy — first
launch to exit, including the waits between relaunches. It is recorded as
`lane_span_min` in the seed and is never calibrated against, because waiting
is not work.

**Estimated**: the plan allowance used as a stand-in for a promise. The
history has no promises: no lane wrote down a crew-time estimate before it
ran. So a reconstructed bid is a **proxy** bid (`proxy: true`) whose
`crew_min` is the seat's plan allowance. Its overrun means "the run took
longer than one plan window", which is a real statement about the run, but it
is not a promise that was broken.

A pi seat has no minute allowance, so it has **no promise at all**: its
bid's `crew_min` is null. With no promise in force there is no overrun, no
penalty and no lateness — a seat is not in debt for work it never agreed to.
Its wall time still calibrates.

---

## 6. Close, overrun, penalty, debt, repayment

```
effective_bid = the awarded bid + every change order's added crew-time
effective_deadline = the job's deadline + every change order's added job-time

overrun   = max(0, actual_crew - effective_bid)
late_days = ceil((actual_job - effective_deadline) / 1440)     (0 if not late)
penalty   = late_days * penalty_per_day_min + clause_penalties (§10)
repayment = min(debt carried, max(0, effective_bid - actual_crew))   (only if the goal line passed)
debt_delta = overrun + penalty - repayment
```

An underrun repays debt, but only a job that actually delivered earns that
credit: work that did not pass its goal line earns nothing — and a close the
check could not decide (§8) earns nothing either, without being counted as a
miss.

Debt is per (seat, job class) and is recomputed by summing the `debt_delta`
of every close on that pair.

**Deep debt**: 120 crew-minutes or more on a class. A seat in deep debt
cannot be awarded work on that class until a retooling is recorded for it.
The award is refused with the debt in the message.

**Retooling** is a ledger event: the seat, the class, the reason and the
action (a different model, a better brief template, a tool, smaller jobs).
After it, the seat may be hired on that class again.

---

## 7. The stop rule

At `stop_ratio` (0.8) of the bid's crew-time, with the goal line not
passing, the sub must stop and report.

The ledger enforces it, not the seat's goodwill: the next `gc checkpoint` is
refused with a message naming the burn, until the GC records a change order
(re-scope or extend) or cancels the job. A change order lifts the stop; the
promise moves with it.

This is the same shape as `crab-cell`'s float plan: with a deadline, silence
is information.

---

## 8. Three-valued verdicts

Every check `gc` runs — the goal line at a checkpoint, the goal line at
close, a clause, a forecast — ends in one of **three** values:

- **pass** — the check ran and the goal line held;
- **fail** — the check ran and it did not;
- **inconclusive** — the check could not run: the command timed out or could
  not spawn, the metric was never reported, no machine check was ever
  written down.

From `receiptd`: "a gate that can't say UNKNOWN will lie to you." A boolean
verdict has two ways to lie — a timeout becomes a fail, or worse, a miss
becomes a pass because someone passed a flag. In `gc`:

- the goal-line rate in the report counts pass/(closes that could say);
  inconclusive closes leave the denominator instead of being read as misses;
- an inconclusive close earns no repayment credit (nothing was delivered
  that the ledger can point at) and no goal-line miss;
- the stop rule does not lift on an inconclusive check — only a pass lifts
  it, because only a pass means the goal line was crossed.

Old v1 rows keep their meaning: `acceptance_passed: true/false` replays as
pass/fail, and a row with no check at all is inconclusive, not failed.

---

## 9. The honest close

The goal line is decided by `gc`, not reported to it (from `nursery-v2`:
audit by recomputation; from `crab-cell`: "does it report honestly?" asked
every cycle).

At close, by acceptance kind:

| kind | how the verdict is decided |
|---|---|
| `cmd` | `gc` runs the command (`sh -c`, output discarded, timeout 600 s or `--check-timeout-sec`) and reads the exit code: 0 is pass, anything else is fail, a spawn failure or timeout is inconclusive |
| `metric` | the reported value (`--metric name=value`) against the threshold: at or above is pass, below is fail, no value is inconclusive |
| `report` | no machine check was written down; the desk states `--accepted` or `--failed` (a human's word, recorded as such) or records `--check inconclusive` |

`--accepted`/`--failed` are **refused** on cmd- and metric-kind jobs: a flag
cannot assert what a command or a measurement decides. The verdict, who
decided it (`gc`, `metric`, `human`), the exit code when there was one, and
the reason when the check could not run are all in the close row.

**The inconclusive close of a report-kind job.** A report-kind job has no
machine-checkable goal line, so the desk's word is the check — and the desk
sometimes cannot tell. `gc close --check inconclusive` records exactly that:
the close stands, `accepted` is `false`, `acceptance_verdict` is
`inconclusive`, and the job is neither a hit nor a miss in the reports
(§8). The refusal to say anything at all stays: a close with no outcome
given is still an error, because "could not tell" must be said out loud.
`--check pass`/`--check fail` on a cmd- or metric-kind job are refused for
the same reason `--accepted`/`--failed` are: the goal line decides for
itself there.

Actuals get the same treatment where they are recomputable:

- a close cannot report **less** crew-time than the job's last checkpoint
  already wrote to the ledger (the floor is recomputable; the close refuses);
- the metrics `gc` computes itself (`crew_used_min`, `burn`,
  `job_elapsed_min` — job-time since the award) cannot be asserted over by a
  reported metric of the same name.

What is **not** checked: the ceiling of the actuals. Crew-time above the
last checkpoint is taken on the reporter's word, priced honestly by the
plan's window share, and labelled by `method` (wall / tokens / estimated).

Determinism: the check's result is the exit code and the verdict — never a
duration, never captured output — so the same command closes byte-identical
on a slow day.

---

## 10. The clause grammar

A clause is contract arithmetic in one line (from `cuda-contract`'s
`SlaClause { metric, target, window, penalty }`):

```
<metric> <op> <target> [window <job-min>] [penalty <crew-min>]
```

- `op` is `>=` or `<=`;
- `window` places the clause inside the first N job-minutes after the award
  (a clause outside its window is not checked, not breached);
- `penalty` is the crew-minutes a breach at close costs, landing in the same
  `penalty_min` (and so the same debt) as a late day.

Example: `waste_pct <= 10 window 480 penalty 15` — the metric `waste_pct`
must be at most 10, checked within 480 job-minutes of the award, and a
breach at close costs 15 crew-minutes.

Where clauses live: `job new --clause ...` (the contract as written) and
`award --clause ...` (negotiated terms; same metric name = override). The
clauses in force are the job's own plus the award's overrides.

How they are checked: at every checkpoint and at close, each clause in force
is evaluated against the metric values of that moment — those `gc` computes
(`crew_used_min`, `burn`, `job_elapsed_min`) and those reported with
`--metric name=value`. A clause whose metric has no value is inconclusive,
not breached: the check could not run. Only a **fail at close** costs the
penalty.

---

## 11. The spend-rate forecast

By the time the burn crosses the stop ratio it is too late to re-plan. At
every checkpoint, `gc` projects the burn (from `cuda-budget`'s spend-rate
forecasting and `build-guardian`'s trend alert):

```
rate        = crew_used_min / job-min elapsed since the award
projected   = rate * effective_deadline_min
minutes_to_stop_line = (stop_line - crew_used_min) / rate
```

Verdicts, three-valued like every check:

- **warn** — projected ≥ the stop line: at this rate the stop line is
  reached before the deadline. Printed as `FORECAST WARNING`; a warning is
  not a stop, it is the moment to re-plan;
- **ok** — projected < the stop line;
- **inconclusive** — under a minute of job-time has passed (a rate from less
  would be noise), or the job has no deadline, or the clock cannot be read.

The projection's assumptions, labelled: it assumes the seat started working
at the award (an idle start dilutes the rate and looks cheaper than it is)
and that the average rate so far holds. It is a projection, not a
measurement.

---

## 12. The machine contract

`gc` is read by a night cycle over a pipe as well as by a person at the
desk. Three things make that reading possible, and none of them changes what
the program means.

**`--external-id`.** `gc job new --external-id ID` writes the caller's own id
of the job into the `job.new` row. The mapping between the caller's work
order and gc's job is then in the ledger — recomputable, not remembered. The
field is always present; it is the empty string when nobody said.

**`--json`.** On `job new`, `bid`, `award`, `checkpoint` and `close`, one line
of JSON is printed on stdout: the body of the row that was just written, the
same bytes the ledger holds. The human-readable lines are unchanged and come
first; the JSON line comes **last**. The flag may sit anywhere among the
others. The body is the whole row body, so the ids, the numbers and the
verdicts are all there.

**`gc report --json`.** Every seat row carries the counts behind its rates,
so a caller can say "14 of 18 on time" instead of only a fraction:

| field | what it is |
|---|---|
| `on_time_jobs` | the closes of that (seat, class) pair that finished inside their recorded deadline |
| `on_time_total` | the closes of that pair that had a recorded deadline at all |
| `on_time_known` | `false` when `on_time_total` is 0 |
| `retools` | the retool events of that (seat, class) pair |

The rule is the one behind `on_time_rate`: a close with no recorded deadline
has no lateness to measure and stays outside the denominator.
`on_time_rate` itself is unchanged — where `on_time_total > 0` it is exactly
`on_time_jobs / on_time_total` — and where `on_time_total` is 0 it is 0 and
`on_time_known` is `false`: that 0 is "unknown", never "never on time".

---

## 13. What is not verified

- The job classes of the 50 reconstructed lanes are a reading of what each
  lane was asked to do. `tools/extract-lanes.py` holds that reading in one
  table so it can be argued with.
- The goal line of a reconstructed lane is the seat's own report and its exit
  code. It is not a machine-checkable command. New jobs take a real
  acceptance command or a metric threshold.
- The seat of a lane is what the board and the queue recorded. One lane
  (`coldshelf-bakeoff`) took its seat from a parenthetical in the queue.
- `gc` cannot make a seat report. A seat that never reports its burn is
  recorded as having reported nothing; the GC sees a job with no
  checkpoints.
- The factor is computed over few runs (1 to 8 per seat and class). The
  shrinkage and the confidence both say so, but a factor from three runs is
  three runs' worth of evidence.
- The five-hour plan window is a documented property of the zcode/mcode
  plans, not something this program measures.
- A timed-out acceptance check kills the shell it spawned; a grandchild that
  shell had already started may outlive the timeout. Untested edge.
- The acceptance command at close runs in the closing process's working
  directory, under `sh -c`, with its output discarded. A goal line that
  needs a different environment (a GPU, a container) records inconclusive
  rather than a verdict it cannot honestly reach; v2 has no `--check-cwd`
  or environment profile to fix that.
- The forecast's "work starts at the award" assumption is untested against
  seats that idle between the award and their first checkpoint.
- The 600-second default check timeout is a judgement, not a measurement.
