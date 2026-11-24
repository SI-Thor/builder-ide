# How the seed was built

The track record is not invented. It is rebuilt from the files the director's
lanes left behind on 2026-11-01 and 2026-11-02.

- the script: `tools/extract-lanes.py`
- the output: `seed/lanes-2026-11-02.jsonl` (50 lanes)
- the importer: `gc seed import --file seed/lanes-2026-11-02.jsonl`

Run it again and you get the same file, except for lanes that were still
running when the snapshot was taken.

## Where the facts come from

| fact | source | measured or read |
|---|---|---|
| which lane was running, on which seat | `~/lm-ops/board-history/*.md` (1118 snapshots, one a minute, 2026-11-01 14:58 → 2026-11-02 10:00) | read |
| when a lane launched | the seat output file's birth time (`stat -c %w`), and `LAUNCHED hh:mm` in the queue | read |
| when a lane exited | the output file's last write (the `EXIT n` line) | read |
| how it ended | the `EXIT n` line: 0 finished, 4 quota stop, 1 failed, 143 killed | read |
| how many relaunches | breaks in the board's presence (over three minutes), against the extra `LAUNCHED` entries in the queue; the larger count wins | read |
| quota stops | the word "quota" in the queue line, plus an `EXIT 4` | read |
| what was asked | the lane's own `BRIEF.md` on the Thor; the queue line where there is no brief | read |
| the job class | a reading of the brief, in one table (`CLASSES`) | **judgement** |
| the plan allowance | `mcode`: the 240-minute run timeout in `desk.sh`; `zcode`/`zflash`/`zmain`: the five-hour plan window | read |

The Thor's own lanes are read over `ssh thor-lan`; the ProArt's lanes are
read directly.

## What the seed says about a lane

Each line of `seed/lanes-2026-11-02.jsonl` is one lane:

```json
{"lane": "night-v4-desk", "where": "proart", "seat": "mcode", "class": "long-run-babysit",
 "scope": "...", "goal_line": "...", "allowance_min": 240.0,
 "actual_crew_min": 541.7, "lane_span_min": 900.0, "relaunches": 1, "quota_stops": 0,
 "exit_code": 0, "outcome": "passed", "crossed_goal_line": true, "calibratable": false,
 "start": "...", "end": "...", "evidence": [...], "reconstructed": true}
```

`gc seed import` turns each line into four ledger rows — the job, the proxy
bid, the award and the close — all marked `reconstructed: true`, so nothing
in the ledger pretends to be more certain than it is.

## The three things the reconstruction had to decide

### 1. Which wall time is the crew-time

A seat's output file is recreated at every launch (`>` truncates in place
for `zcode` and `mcode`; `sed -i` renames a new inode into place for `pi`),
so its birth time is the **last** launch and its last write is the exit.
That gives the wall time of the last run.

The lane's **total occupancy** — first launch to exit, including the waits
between relaunches — is measured too, and kept as `lane_span_min`. It is not
calibrated against, because waiting is not work: a lane that sat for six
hours on a quota reset and then ran for nine minutes has used nine minutes
of crew-time, not six hours.

### 2. Which runs may set a bid

Only **clean** runs: the seat crossed its goal line, with no relaunch and no
quota stop. A run that was cut short by a quota says how long the seat was
away, not how long the work takes.

Of the 50 lanes, **31 are clean**. The other 19 stay in the record — they
are the debt, the missed goal lines and the late days — but they do not set
the factor. `gc report` prints both curves so the difference is visible.

### 3. What the "promise" is, when the history never recorded one

No lane wrote down a crew-time estimate before it ran. There is no
promise/actual pair in the history at all.

So a reconstructed bid is a **proxy**: its `crew_min` is the seat's plan
allowance, it is marked `proxy: true`, and its overrun means "the run took
longer than one plan window". A pi seat is billed in tokens and has no
minute allowance, so it has no proxy bid either — no promise, no overrun,
no debt, but its wall time still calibrates.

The bid itself is built from the seat's **factor** (q80 ÷ median of its
clean runs), which is scale-free: it does not need a promise to be
meaningful. See `docs/model.md` §3.

## The numbers this produced

50 lanes from 2026-11-01 to 2026-11-02:

- 41 finished (`EXIT 0`), 7 stopped on a quota (`EXIT 4`), 2 failed.
- 31 clean enough to calibrate a bid.
- Seats: 21 mcode, 13 pi, 6 zcode, 5 zflash, 4 zmain, 1 unknown.
- Classes: 21 lab-experiment, 17 build-feature, 10 research-read, 2 merge-fix.

Lanes still running when the snapshot was taken are left out: they have no
outcome and no final wall time.

## Reproducing it

On the ProArt (it reads `~/lm-ops` and pulls the Thor's facts over ssh):

```bash
python3 tools/extract-lanes.py --summary          # the table
python3 tools/extract-lanes.py -o seed/lanes-2026-11-02.jsonl
```

On the Thor, to rebuild the ledger from the seed:

```bash
gc seed import --rebuild --file seed/lanes-2026-11-02.jsonl
```

`--rebuild` refuses to run unless every row in the ledger belongs to a
reconstructed job, so a ledger that holds real work cannot be rebuilt from
under the general contractor.

## What this seed does not have

- **Promises.** Every reconstructed bid is a proxy. The promise curve in
  `gc report` is empty until real jobs are run through the ledger.
- **Token counts.** A pi seat's crew-time is a token count; the history does
  not keep them, so pi lanes contribute wall time and no allowance.
- **Machine-checkable goal lines.** A reconstructed lane's goal line is the
  seat's report and its exit code.
- **A seat's own view.** The seed says how long a lane took and whether it
  landed. It does not say whether the seat thought it did well.
