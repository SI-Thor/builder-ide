# seat-watcher: the scripts

Pure Python, standard library only. No third-party packages, no network access
except `capture.py`'s `ssh thor-lan`.

## Run them

```
python3 scripts/capture.py          # raw/     : every source, copied
python3 scripts/reconstruct.py      # data/    : stream.jsonl, stream-meta.json
python3 scripts/gates.py            # data/    : events.json
python3 scripts/score.py --sweep    # RESULT.json
```

About **30 s** end to end on this box, of which ~20 s is `capture.py` talking to
the Thor. `capture.py --skip-ssh` reuses the captured `raw/` and runs in ~2 s.

## What each one needs

| file | reads | writes |
|---|---|---|
| `scripts/capture.py` | `ssh thor-lan` (the Thor's logs, seats, git history, journal), `~/lm-ops/` | `raw/` |
| `scripts/reconstruct.py` | `raw/` | `data/stream.jsonl`, `data/stream-meta.json` |
| `scripts/gates.py` | `data/stream.jsonl` | `data/events.json` |
| `scripts/score.py` | `data/events.json`, `data/stream.jsonl` | `RESULT.json` |
| `scripts/labels.py` | nothing (it *is* the hand-extracted labels) | - |
| `scripts/common.py` | nothing (time zone and paths) | - |

`scripts/labels.py` runs on its own and prints the 13 episodes with their times.

## The order, and why

`capture` -> `reconstruct` -> `gates` -> `score`. Each step only reads what the
previous one wrote, so any step can be re-run on its own once `raw/` exists.

`capture.py` never overwrites good data with an empty file: if the Thor is
unreachable and a fetch comes back empty, the previous capture is kept and the
run says so. `scripts/retry-thor-capture.sh` waits for the Thor and re-captures.

**The Thor was down when the experiment was finished** (from ~15:50 on
2026-11-01), so `raw/seats-thor.jsonl` and `raw/git-commits-thor.jsonl` were
captured before the error-classification change and the Thor's seat transcripts
contribute 0 API-error records. When the Thor comes back:

```
./scripts/retry-thor-capture.sh      # or: python3 scripts/capture.py
python3 scripts/reconstruct.py && python3 scripts/gates.py && python3 scripts/score.py --sweep
```

and the API-error channel will fill in. That changes the API-burst rows of the
sensitivity sweep and possibly one or two episodes; the report says so in
"what was not verified".

## The gates, and the variants

`scripts/gates.py` scores six gates, not three:

| key | gate |
|---|---|
| `a` | the level gate, as the brief specifies it |
| `b` | the rate gate |
| `ab` | level + rate (the brief's (c)) |
| `a_live` | the level gate with the seat clause applied only to seats that have not exited |
| `bplus` | the rate gate plus one extra condition: **the box has not reported for 2 minutes** |
| `abplus` | level + rate + that extra condition |

`a_live` and `bplus` are **variants, not the brief's gates**. They are scored
and reported separately so the brief's three gates stay exactly as specified.
`bplus` exists because the Thor stopped answering at 15:50 while the experiment
was running: the telemetry-dark condition fired at 15:50:38, thirteen minutes
before the board's own page showed that the box was gone.

## The thresholds

`scripts/gates.py` holds the defaults in `PARAMS`. Every one of them is
overridable:

```
python3 scripts/gates.py --params my-params.json
```

The defaults and where they came from are in `docs/exp-seat-watcher.md`
sections 1.3 and 2.6. The memory-rate threshold (3 GB/min over a 10-minute
trailing window) was picked from the day's own distribution; the sweep in
`RESULT.json` shows recall does not move between 1 and 6 GB/min.

## Two things to know before changing the gates

1. **Rates need a contiguous history.** The trailing window ends at any gap
   larger than 30 s, so a rate is never computed across a daemon restart or
   across the box going down. The 2026-11-01 data has gaps of 84 s (a daemon
   restart), 8,479 s (the daemon was down 22:25-00:47) and 334 s (the reboot).
2. **Every condition has a 30-second hold.** The box's `MemAvailable` reads
   bimodally after a restart (127 GB / 17 GB alternating for minutes), and
   without the hold the rate gate produces 645 speeches a day instead of 13.

## Reproducibility caveats

- `capture.py` is a *capture*, not a fixture: the live `.out` mtimes and the
  git history move with the day. Re-running it later refreshes `raw/`.
- The seat `.out` files are **append-and-rewrite** artefacts. A seat that fails
  and is relaunched overwrites its own transcript, so most of the day's API
  errors are no longer on disk. This is a property of the data, not of the
  capture, and it is why the API-error channel is nearly empty.
- The Thor logs its timestamps in UTC with a `Z` suffix; both boxes are on
  `America/Anchorage`, which fell back at 02:00 local on 2026-11-01, so the
  local hour 01:00-02:00 happened twice. `scripts/common.py` converts with
  `zoneinfo` and every comparison is in epoch seconds.

## Outputs

- `RESULT.json` - the scores: precision, recall, false-positive rate, lead
  times and stall minutes per gate, per episode and per matching rule, plus the
  threshold sweep.
- `data/stream-meta.json` - what each channel covers, where it came from, and
  the validation against the board's own out-age column
  (676 comparisons, 0 mismatches; the count grows with the board loop,
  which was still writing snapshots during the capture).
- `data/events.json` - every speak-now event, with the numbers behind it.
- `data/stream.jsonl` - the change stream itself.
- `NOTES.md` - the trail, including the two bugs found while measuring.
