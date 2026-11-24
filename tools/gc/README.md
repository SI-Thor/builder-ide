# general-contractor

**The general contractor does not hand a subcontractor a blank check and ask
to be told when the job is done. The general contractor plans the greater
project as a sequence of subcontracts, thinks about the budget in both time
and money, and makes the subcontractor bid.**

This repository is that, in code. It is `gc`: one binary, one append-only
ledger, and a book of what every seat has actually cost.

---

## The carpet example

Casey's example, with the names this program uses.

**The job.** The general contractor wants 40 square metres of carpet laid in
the lobby. It is written down as a **job**: the scope, the **goal line**
(here, `cargo test --test carpet` must exit 0 — a command a machine can
check), the **job-time** (the T-minus: 480 minutes from the award), the
**crew-time ceiling** (240 minutes), and the **job class**
(`build-feature`).

**The bid.** The carpet subcontractor does not ask for the work and start. It
*bids*: "I will do it for 130 minutes of crew-time, at 0.7 confidence, in
these milestones." The bid is not a guess. It is computed from that seat's
track record on that class of work — the q80 of what it actually took,
divided by its median, which says how much bigger than its own usual this
seat runs when it is unlucky. Overbidding beats underbidding, so the bid is
the 80th percentile, not the middle. A seat with no track record bids the
prior: 25% over the general contractor's estimate.

**The award.** The general contractor picks. Cost, the seat's on-time record,
and fit with the class of work — one ledger event, with the score that chose
it written down.

**The execution.** The carpet is laid. At each milestone the sub reports its
burn: `gc checkpoint --job J001 --crew-used-min 60`. The checkpoint also
**runs the goal line itself** (the acceptance command, or the reported
metric against its threshold) and prints a **spend-rate forecast**: where
this burn rate lands by the deadline, so a job heading for the stop line is
visible while there is still job-time to re-plan with. If the burn reaches
**80% of the bid** and the goal line still has not passed, the sub must stop
and report. No open-ended runs. The ledger enforces this, not goodwill: the
next checkpoint is refused until the general contractor re-scopes the job
with a **change order**, extends it, or cancels it.

**The clauses.** The contract can carry more than the goal line. A clause is
one readable line — `waste_pct <= 10 window 480 penalty 15` — checked at
every checkpoint and at close, and a breach at close costs its penalty in
crew-minutes. The award can tighten or add clauses (negotiated terms, same
grammar).

**The close.** Nobody's word is taken for it. `gc close` **re-runs the
acceptance command itself** and reads the exit code (a metric goal line is
compared against the reported value; only a job with no machine-checkable
goal line takes the desk's `--accepted`/`--failed`). Every check is
**three-valued — pass, fail, or inconclusive** — because a gate that cannot
say "could not tell" will eventually lie. An inconclusive close earns no
credit and counts as neither a hit nor a miss. The close also refuses
actuals below what the checkpoints already reported. The job closes with
the actuals: the crew-time spent, the job-time spent, the late days, the
overrun, the penalties, the clause breaches.

**The debt and the reputation.** Some jobs get underbid. The subcontractor
had to hire more crew to finish inside the window it promised, so it made no
money on that job. The overrun is **debt** the seat carries; a later
underrun repays it. A seat's **reputation** is its on-time rate, its
goal-line rate and how often it stayed inside its bid.

**The retooling.** A seat deep in debt on a class is not hired on that class
again until it has been **retooled** — a different model, a better brief, a
tool, smaller jobs — and the retooling is a ledger event with its reason.
Learning from the jobs you failed to make money on is the point.

## Five minutes, on your own repo

Build `gc` once, then take it to any repository — it writes one file,
`ledger.jsonl`, in the working directory, and nothing else. Real output from
a scratch repo (a `check.sh` that fails until `fixed.txt` exists):

```console
$ gc job new --title "make check.sh pass" --class build-feature \
      --scope "Fix whatever check.sh complains about." \
      --accept-cmd "./check.sh" --estimate-min 20 --deadline-min 60
J001 — make check.sh pass [build-feature] goal line: `./check.sh` exits 0 —
job-time 60 min, GC estimate 20 min, ceiling 30 min

$ gc bid --job J001 --sub aider --submit
bid B001 on J001 by aider: 25 crew-min, confidence 0.30
(no finished run of seat 'aider' on class 'build-feature': the prior factor 1.25)

$ gc award --job J001 --auto
awarded J001 to aider (bid B001): score 0.610

$ gc checkpoint --job J001 --crew-used-min 5
checkpoint on J001: 5 crew-min used of 25 (20% of the bid)
goal line: fail (command re-run by gc, exit 1)     # the check runs, it is not asked

$ touch fixed.txt                                  # the work happens

$ gc checkpoint --job J001 --crew-used-min 12
checkpoint on J001: 12 crew-min used of 25 (48% of the bid)
goal line: pass (command re-run by gc, exit 0)

$ gc close --job J001 --crew-min 14
closed J001: 14 crew-min against a promise of 25, overrun 0, penalty 0, debt +0
goal line: pass (command re-run by gc, exit 0)
```

What you got in those five minutes:

- the **goal line ran three times** and nobody's word was taken for it —
  try `gc close --job J001 --crew-min 14 --accepted` on a job whose command
  fails and the close is refused outright;
- the **bid was priced from evidence** (the prior, 1.25x, because the seat
  had no history) rather than asked;
- the **book** (`gc report`) now holds a promise/actual pair — actual 14
  against the promise 25 — so the next bid this seat gets is computed from
  what it really took, not from what it said;
- `gc verify` walks the hash chain on `ledger.jsonl` and names any row that
  was changed.

A job with clauses, a stop at 80%, a change order and an honest close is
`./examples/demo.sh` — the carpet story, end to end, in a scratch directory.

## What is in the box

```
gc                 one binary, Rust, std only, no crates
ledger.jsonl       every event, append-only, every row hash-chained
seed/              the track record, rebuilt from the real lanes of 2026-11-01..02
tools/             the script that rebuilds the seed
docs/              the model, the prior art, the integration, the seed method
examples/demo.sh   a worked run, end to end (clauses, stop, honest close)
tests/             61 tests (41 unit, 20 through the real binary)
```

## Getting it running

On the Thor (aarch64, `source ~/.cargo/env` first — cargo is not on the
default PATH):

```bash
cargo build --release
cargo test                       # 61 tests
./target/release/gc report       # the book, over the seeded history
./examples/demo.sh               # a worked run in a scratch directory
```

The ledger in the repo is the seeded history: 50 real lanes from
2026-11-01..02. To rebuild it from the seed file:

```bash
./target/release/gc seed import --rebuild --file seed/lanes-2026-11-02.jsonl
```

## The commands

```
gc job new        --title T --class C --scope S --accept-cmd CMD
                  --estimate-min M --deadline-min M [--budget-min M]
                  [--external-id ID] [--json]
                  [--clause "metric <= target [window W] [penalty P]" ...]
gc job list
gc bid            --job J --sub S [--crew-min X] [--confidence C] [--submit] [--json]
gc award          --job J (--bid B | --auto) [--clause ...] [--json]
gc checkpoint     --job J --crew-used-min X [--check auto|pass|fail|inconclusive]
                  [--metric name=value ...] [--check-timeout-sec S] [--json]
gc close          --job J --crew-min X [--metric name=value ...]
                  [--accepted|--failed|--check inconclusive]
                                                  (report-kind jobs only)
                  [--json]
gc change-order   --job J --reason R [--add-crew-min X] [--add-job-min Y]
gc cancel         --job J --reason R
gc retool         --sub S --class C --reason R --action A
gc report         [--sub S] [--class C] [--json]
gc brief          --job J
gc verify
gc seed import    --file FILE [--rebuild]
```

Every writing command takes `--at ISO8601`, or `GC_NOW` in unix seconds, to
fix the clock. With a fixed clock the same commands write byte-identical
bytes.

## The machine contract

The night cycle reads `gc` over a pipe, not by eye. Three things make that
possible, and none of them changes what the program means.

**`--external-id`** keys a gc job to a caller of its own — a builder-ide
work order, a ticket. It is written into the `job.new` row, so the mapping
is in the ledger and not in anybody's memory:

```console
$ gc job new --title t --class build-feature --scope s \
      --external-id WO-42 --estimate-min 60 --deadline-min 1440
```

The field is always there; it is the empty string when nobody said.

**`--json`** on `job new`, `bid`, `award`, `checkpoint` and `close` prints
**one line of JSON** on stdout: the body of the row that was just written.
The human-readable lines stay exactly as they were and the JSON line comes
**last**, so the same command serves the desk and the pipe:

```console
$ gc job new --title t --class build-feature --scope s \
      --accept-cmd true --estimate-min 60 --deadline-min 1440 --json
J001 — t [build-feature] goal line: `true` exits 0 — job-time 1440 min, GC estimate 60 min, ceiling 90 min
row 0 written (hash 4557a529f8de)
{"id":"J001","external_id":"","title":"t",...,"clauses":[],"reconstructed":false,"source":"gc job new"}
```

The flag may sit anywhere among the other flags.

**`gc close --check inconclusive`** is what a report-kind job says when the
outcome could not be judged — the goal line was never machine-checkable, and
the desk cannot tell either. It is recorded as `inconclusive`: the close
stands, it earns no credit, and it counts as neither a hit nor a miss. A
command-kind or metric-kind job still refuses a stated outcome
(`--check pass`, `--check fail`, `--accepted`, `--failed`): there the goal
line decides for itself.

## The ledger

One JSON object per line. Every row carries the hash of the row before it,
so the file is tamper-evident:

```json
{"seq":0,"ts":"2026-11-01T00:55:00Z","kind":"job.new","body":{...},"prev":"0000...","hash":"3f68..."}
```

`gc verify` walks the chain and recomputes every hash. Change one byte of
any row and it fails, naming the row.

Nothing is stored twice. Every number in `gc report` is read from a row or
recomputed from rows.

## The track record, as it stands

The seed is the director's lanes of 2026-11-01 and 2026-11-02, rebuilt from
the board's minute-by-minute history, the seats' output files and the queue:
**50 lanes** — 41 finished, 7 stopped on a quota, 2 failed — of which **31**
are clean runs good enough to calibrate a bid.

What the seats look like today (the history, not a guess):

| seat | class | clean runs | median | q80 | factor |
|---|---|---|---|---|---|
| mcode | build-feature | 5 | 85.8 min | 127.9 min | 1.49 |
| mcode | lab-experiment | 3 | 33.9 min | 58.7 min | 1.73 |
| zcode | lab-experiment | 3 | 129.7 min | 149.6 min | 1.15 |
| zflash | build-feature | 2 | 29.3 min | 29.0 min | 1.01 |

The factor is what a bid is built from: the GC's estimate of the job times
the factor.

## Being honest about the numbers

- **Measured**: the wall time of a lane's last run, from the seat output
  file's birth (the launch) to its last write (the exit).
- **Measured separately**: the lane's total occupancy, including the waits
  between relaunches. It is never calibrated against, because waiting is not
  work.
- **Estimated**: the plan allowance used in place of a promise. The history
  never recorded a crew-time promise, so every reconstructed bid is a
  **proxy** and says so.
- **Unknown**: lateness. No historical lane had a recorded deadline, so the
  on-time column reads `n/a` rather than a flattering 100%.
- **Tokens**: a pi seat is billed in tokens. Its crew-time is a token count,
  it has no minute allowance, and it forms no promise and no debt.
- **The forecast is a projection, not a measurement.** It assumes the seat
  started working at the award and that the average rate so far holds; a
  seat that sat idle before its first checkpoint looks cheaper than it is.
  It stays quiet until at least a minute of job-time has passed, because a
  rate from less than that is noise.
- **The checkpoint check costs what the command costs.** `--check auto`
  runs the acceptance command at every checkpoint of a cmd-kind job — that
  is the point, but a slow suite makes checkpoints slow. `--check
  inconclusive` records that the check could not run this time; the record
  prefers a recorded shrug over an invented yes.

## The docs

| file | what is in it |
|---|---|
| `docs/model.md` | the entities, the arithmetic, the measurement, what is not verified |
| `docs/prior-art.md` | what crab-cell, nursery-v2, cuda-contract, flux-market, cuda-budget, trust-ledger, decision-ledger and ledger-continuity already had, what we take, and what each is missing |
| `docs/prior-art-scout.md` | the scout's wider survey: 19 repos read, what each lent v2 (three-valued verdicts, the honest close, the clause grammar, the forecast), and the negative results |
| `docs/seed-method.md` | how the 50 lanes were rebuilt, and how to rebuild them |
| `docs/integration.md` | the three-line change to `desk.sh` that puts the contract in a seat's brief (proposed; `desk.sh` is not edited here) |
| `docs/design/language-fit.md` | why Rust, std only, and why Python for the script |
| `NOTES.md` | the dated working notes: what was tried, what happened, what was decided |

## What is not here

- The promise curve holds exactly one real pair (J051, this repo's own v2
  job: 140 promised, 58 closed, the goal line re-run at close) — every other
  bid in the ledger is a reconstructed proxy. One pair is a start, not a
  calibration.
- `gc` cannot make a seat report. A seat that never reports its burn is
  recorded as having reported nothing.
- The job classes of the reconstructed lanes are a reading, kept in one table
  in `tools/extract-lanes.py` so it can be argued with.
- A timed-out acceptance check kills the shell it spawned; a grandchild that
  shell already started may outlive it. Untested edge, recorded here.
- The acceptance command runs in the closing process's working directory
  under `sh -c`; a command that needs a different environment (a GPU, a
  container) records inconclusive at close rather than a verdict it cannot
  honestly reach. Fixing that means a `--check-cwd` or an env profile, which
  v2 does not have.
- Nothing is pushed anywhere. The ledger is local, and it is the record.
