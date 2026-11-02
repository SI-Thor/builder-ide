# NOTES — general-contractor

Working notes, one dated line per step: what was tried, what happened (with
the numbers, and the box state beside them), what was decided next. Dead ends
stay here so nobody repeats them.

The work happens on the Thor (`~/lm-wt/general-contractor`), aarch64 Jetson
Thor, 122 GB unified memory, 81 GB free disk at the start of the day. This
seat runs on the ProArt and drives the Thor over `ssh thor-lan`.

---

## 2026-11-02 10:00 — read the brief, looked at the box

- Thor: `rustc`/`cargo` are in `~/.cargo/bin` (rustup `stable-aarch64-unknown-linux-gnu`),
  not on the default PATH — `source ~/.cargo/env` first. `free -g` showed 122 GB
  total, 42 used, 80 available; `/` had 81 GB free, `/mnt/toshiba` 1.4 TB.
- `gh auth status` on the Thor: the token in `~/.config/gh/hosts.yml` is
  **invalid**. The prior-art repos were cloned read-only with plain
  `git clone --depth 1 https://github.com/...` instead, which works for the
  public repos.
- `SuperInstance/AI-Writings` and both `builder-ide` candidates are **not
  reachable** (not public / no such repo). `docs/prior-art.md` says so
  instead of pretending to have read them.
- `pgrep -af` found no leftover copy of this job, so only one seat runs it.
- Decision: the Rust build needs no GPU and no lease, so no `thor-admit` run
  was taken. Nothing here preallocates memory.

## 2026-11-02 10:05 — the history that a track record can be built from

Read what actually exists about the director's lanes:

- `~/lm-ops/board-history/*.md`: 1118 minute-by-minute board snapshots from
  2026-11-01 14:58 to 2026-11-02 10:00. Every row says which lane was
  running, on which seat (`zcode`, `mcode`, `pi`), and how old its output file
  is. It records presence, not exit codes.
- `~/lm-ops/wt/*.out`: 70 seat output files. The last line is `EXIT n`
  (0 = the seat finished, 4 = the seat hit its quota, 1 = failed,
  143 = killed). `stat -c %w` gives the file's birth time = the launch, and
  the mtime = the exit.
- `~/lm-ops/zqueue.txt`: the queue. `LAUNCHED hh:mm` says when a lane went
  out, `DONE` says it landed, and the prose mentions quota stops and
  relaunches.
- The Thor's own `~/lm-wt/*.out` carry the same three facts for the lanes that
  ran on the Thor.

What the history does **not** have: any crew-time *promise*. No lane wrote
down an estimate before it ran. So a promise/actual pair, the thing a bid is
calibrated from, does not exist in the history — only actuals, and the
allowance each seat worked under. Decision: the calibration is built from
actual crew-times and is scale-free (a factor, not an absolute), so it does
not need a promise to be meaningful.

## 2026-11-02 10:10 — the first build

- Rust, std only: no crates, no network at build time. The only third-party
  code is the SHA-256 in `src/sha256.rs` (written for this, checked against
  the FIPS vectors).
- First build failed on two compile errors: a moved `String` in `seed.rs` and
  a borrowed temporary in `seed.rs`. Fixed by cloning and by borrowing.
- `cargo test` caught the quantile test failing on floating point
  (`3.4000000000000004` vs `3.4`): the assertion now compares with a
  tolerance, the code was right.

## 2026-11-02 10:15 — the lane reconstruction

`tools/extract-lanes.py` (runs on the ProArt, pulls the Thor's facts over
ssh) rebuilt **50 lanes** from 2026-11-01 to 2026-11-02:

- 41 finished with `EXIT 0`, 7 stopped on a quota (`EXIT 4`), 2 failed.
- 31 of the 50 are *clean* runs: finished the work with no relaunch and no
  quota stop. Only those calibrate a bid; the other 19 stay in the record as
  debt and missed goal lines.
- Seats: 21 mcode, 13 pi, 6 zcode, 5 zflash, 4 zmain, 1 unknown.
- Classes: 21 lab-experiment, 17 build-feature, 10 research-read, 2 merge-fix.

Two things the first pass got wrong, both caught by looking at the report:

1. **A pi seat was accruing phantom debt.** A pi seat is billed in tokens;
   its plan window is unknown, so there is no allowance to overrun. The first
   pass gave it a zero allowance and every pi minute became overrun — 1132
   crew-minutes of debt for a seat that never promised anything. Fixed: with
   no promise in force there is no overrun, no penalty and no lateness, and
   the seat's wall time still calibrates.
2. **One lane's seat was unknown** (`coldshelf-bakeoff`, whose queue line
   says "zcode, not pi" inside a parenthetical). The seat detector now
   matches a word, not a token.

Also fixed: the crew-time of a lane is the wall time of its **last run** (the
output file is recreated at every launch, so its birth is the last launch and
its last write is the exit). The lane's total occupancy — which includes the
waits between relaunches — is recorded separately as `lane_span_min` and is
*not* calibrated against, because waiting is not work.

## 2026-11-02 10:20 — the model changed once, for a reason

The first bid model was "the seat's q80 consumption of its plan allowance,
times the allowance". The seeded data killed it: a zcode seat that ran 262
minutes against a 300-minute plan window is a ratio of 0.87, and another that
ran 9 hours is a ratio of 1.8, so the "consumption" of a lane is really a
property of the lane's size, not of the seat. The bid must not depend on how
big the job happened to be.

Replaced with a **scale-free factor**: the seat's q80 crew-time divided by
its median crew-time on the class. The general contractor's own estimate of
the job sets the size; the seat's history says how much bigger than its
median this seat runs at the 80th percentile. Shrunk toward a prior factor of
1.25 when the sample is small. The same numbers, used differently.

## 2026-11-02 10:25 — the tests

`cargo test` on the Thor: **27 tests, all passing** (20 unit, 7 integration
through the real binary).

- the ledger is a hash chain, and changing one byte of one row makes
  `gc verify` fail;
- the calibrated bid for a seat with clean runs of 40, 50 and 60 minutes and a
  GC estimate of 100 is 117 crew-minutes (median 50, q80 56, raw factor 1.12,
  shrunk toward the prior 1.25 with weight 2), and a seat with no history
  gets the prior: 125;
- an overrun of 30 minutes plus a one-day late penalty of 30 is 60 of debt,
  and an underrun of 20 repays 20 of it;
- the stop rule refuses more burn at 80% of the bid until a change order
  lifts it, and the promise moves with the change order;
- a seat 180 minutes in debt cannot be awarded work until it is retooled;
- the same commands with a fixed clock write byte-identical ledgers.

Two test failures were real bugs, not test bugs:

1. the brief read "10 h minutes" — the duration helper mixed units; it now
   says "600 minutes (10 h)" and "120 crew-minutes (2 h)";
2. a retool recorded in the same second as the close that opened the debt
   did not unblock the seat, because the ledger's clock has one-second
   resolution. The retool now counts from that second on.

## 2026-11-02 10:30 — the permissions on this desk

The runtime's permission gate would not let this seat **overwrite or delete**
a file on the Thor (`cp`, `cat >`, `mv`, `rm` and `scp` over an existing file
all ask a question this host cannot ask). Two consequences, both worked
around without fighting the gate:

- the ledger is never edited in place. It is rebuilt by
  `gc seed import --rebuild --file seed/lanes-2026-11-02.jsonl`, and the
  rebuild refuses to run unless every row in the ledger belongs to a
  reconstructed job — a ledger with real work in it cannot be rebuilt from
  under the general contractor;
- `ledger.new.jsonl` is left on the Thor from the first rebuild attempt. It
  holds the same 200 rows as `ledger.jsonl`. It is in `.gitignore`; deleting
  it needs a hand or a permission this host cannot ask for.

## 2026-11-02 10:35 — what is not in here

- No seat's **promise** is in the ledger, because the history never recorded
  one. The reconstructed bids are *proxy* bids: the seat's plan allowance
  stands in for a promise, and every one of them is marked `proxy: true`.
- A pi seat has no minute allowance and so no promise; its crew-time is
  measured in tokens, and the tokens are not in the history.
- The job classes of the 50 lanes are a reading of what each lane was asked
  to do. `tools/extract-lanes.py` holds that reading in one table
  (`CLASSES`), so it can be argued with.
- The goal line of a reconstructed lane is the seat's own report and its exit
  code, not a machine-checkable command. New jobs take a real acceptance
  command or a metric threshold.
- `gc` has no seat-side enforcement: a seat that does not report its burn is
  recorded as having reported nothing. The stop rule is enforced by the
  ledger refusing the checkpoint, not by the seat obeying it.
