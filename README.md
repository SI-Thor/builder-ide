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
burn: `gc checkpoint --job J001 --crew-used-min 60`. If it reaches **80% of
its bid** and the goal line still has not passed, it must stop and report.
No open-ended runs. The ledger enforces this, not goodwill: the next
checkpoint is refused until the general contractor re-scopes the job with a
**change order**, extends it, or cancels it.

**The close.** The goal line passes. The job closes with the actuals: the
crew-time spent, the job-time spent, the late days, the overrun, the
penalty.

**The debt and the reputation.** Some jobs get underbid. The subcontractor
had to hire more crew to finish inside the window it promised, so it made no
money on that job. The overrun is **debt** the seat carries; a later
underrun repays it. A seat's **reputation** is its on-time rate, its
goal-line rate and how often it stayed inside its bid.

**The retooling.** A seat deep in debt on a class is not hired on that class
again until it has been **retooled** — a different model, a better brief, a
tool, smaller jobs — and the retooling is a ledger event with its reason.
Learning from the jobs you failed to make money on is the point.

## What is in the box

```
gc                 one binary, Rust, std only, no crates
ledger.jsonl       every event, append-only, every row hash-chained
seed/              the track record, rebuilt from the real lanes of 2026-11-01..02
tools/             the script that rebuilds the seed
docs/              the model, the prior art, the integration, the seed method
examples/demo.sh   a worked run, end to end
tests/             27 tests
```

## Getting it running

On the Thor (aarch64, `source ~/.cargo/env` first — cargo is not on the
default PATH):

```bash
cargo build --release
cargo test                       # 27 tests
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
gc job list
gc bid            --job J --sub S [--crew-min X] [--confidence C] [--submit]
gc award          --job J (--bid B | --auto)
gc checkpoint     --job J --crew-used-min X [--acceptance-passed]
gc close          --job J --crew-min X [--accepted|--failed] [--late-days N]
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

## The docs

| file | what is in it |
|---|---|
| `docs/model.md` | the entities, the arithmetic, the measurement, what is not verified |
| `docs/prior-art.md` | what crab-cell, nursery-v2, cuda-contract, flux-market, cuda-budget, trust-ledger, decision-ledger and ledger-continuity already had, what we take, and what each is missing |
| `docs/seed-method.md` | how the 50 lanes were rebuilt, and how to rebuild them |
| `docs/integration.md` | the three-line change to `desk.sh` that puts the contract in a seat's brief (proposed; `desk.sh` is not edited here) |
| `docs/design/language-fit.md` | why Rust, std only, and why Python for the script |
| `NOTES.md` | the dated working notes: what was tried, what happened, what was decided |

## What is not here

- No seat's promise is in the ledger yet. The reconstructed bids are proxies,
  and the promise curve stays empty until real jobs run through it.
- `gc` cannot make a seat report. A seat that never reports its burn is
  recorded as having reported nothing.
- The job classes of the reconstructed lanes are a reading, kept in one table
  in `tools/extract-lanes.py` so it can be argued with.
- Nothing is pushed anywhere. The ledger is local, and it is the record.
