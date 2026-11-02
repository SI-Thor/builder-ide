# `tools/seat-watch` — the live watcher for the director's seats

The lab measured a gate over 2026-11-01 and said which one to build:
`docs/lab/exp-seat-watcher.md` (§4). This is that gate, running live.

The watcher reads the seats on the ProArt and, over one ssh to the Thor, the
seats there. It never touches a seat: it reads, and when something is wrong
it prints **one line** and exits 0.

```
DONE <machine> <job>     a new EXIT line — watch-all.sh's rule
QUOTA <job>              "usage limit" / "Limit Exhausted" in an .out
STALL <job> <reason>     a seat stopped making progress
BOX <reason>             the Thor's or the ProArt's own state went wrong
```

The order above is the order they are checked in. The reasons are single
tokens, so the line can be split on whitespace; the numbers behind it go to
the log file and to stderr, not to stdout.

`BOX` has five reasons: four for the Thor (`memory_falling`, `disk_falling`,
`disk_low`, `telemetry_dark`) and one for the ProArt (`proart-memory`).

## What is in here

| file | what it is | how long |
|---|---|---|
| `seatwatch.py` | the watcher: the gate, the collectors, the five reasons | — |
| `replay.py` | the dry run: replay a recorded day, or the board's own history | 14 s / 2 s |
| `test_seatwatch.py` | the tests, against the lab's recorded fixtures | 14 s |

Pure Python, standard library only. No network access except the one ssh to
the Thor.

## Running it

```bash
# one poll, print what it saw, exit (the smoke test)
~/lm-ops/seat-watch.sh --once

# watch for real: one line, then exit 0
~/lm-ops/seat-watch.sh

# a bounded run, for a smoke test: prints TIMEOUT if nothing happened
~/lm-ops/seat-watch.sh --timeout 240

# the dry run against the lab's recorded day
python3 tools/seat-watch/replay.py --verify

# the dry run against the board's own history
python3 tools/seat-watch/replay.py --board-history ~/lm-ops/board-history

# the tests
python3 tools/seat-watch/test_seatwatch.py
```

The installed copy is `~/lm-ops/seat-watch.sh` on the ProArt (mode 755,
installed 2026-11-01, byte-identical to `seatwatch.py` here). Despite the
name it is a Python program with a `#!/usr/bin/env python3` line: the brief
asks for one self-contained file, and a Python file is what the collector
has to be (the same bytes run locally and over ssh).

Options: `--poll` (default 15 s), `--timeout` (default 36000 s, 0 = never),
`--ssh` (default `thor-lan`), `--ops` (default `$LM_OPS` or `~/lm-ops`),
`--window` (the no-progress window, default 600 s), `--ssh-child` (default
1800 s), `--loop-window` (default 3600 s), `--proart-mem-low` (default
2.0 GB), `--proart-swap-rate` (default 0.5 GB/min), `--once`.

## How it is put together

```
   ProArt                                  Thor
   ┌────────────────────────────┐          ┌─────────────────────────┐
   │ collector (python, local)  │  ssh     │ collector (same bytes)  │
   │  - the seats in wt/*.out   │ ───────► │  - the seats in lm-wt   │
   │  - tmux panes, /proc, ss   │          │  - MemAvailable, swap   │
   │  - MemAvailable, swap, df  │          │  - MemAvailable, df     │
   │                             │          │  - thor-admit leases    │
   └─────────────┬──────────────┘          └────────────┬────────────┘
                 │  JSON lines (each tagged with its box)  │
                 └───────────────┬────────────────────────┘
                                 ▼
                    Engine (the lab's gate)
                    ├─ BOX   memory rate, disk rate, disk floor, telemetry dark
                    │       (the Thor's channel) + the ProArt's memory
                    ├─ QUOTA the markers in the .out files
                    ├─ STALL per-seat progress, ssh child, watcher loop
                    └─ DONE  EXIT lines, watch-all.sh's rule
                                 │
                                 ▼
                    one line on stdout, exit 0
```

**One channel per box.** The two boxes' memory and disk are hundreds of
gigabytes apart (the ProArt has 804 GB of disk free, the Thor 85 GB), so
they are kept in separate series. Feeding both into one series makes the
slope read the *difference between the boxes* rather than either box's own
trend: the live watcher's disk slope read **-21,504 GB/h** on healthy boxes
and the condition would have fired about two minutes after every start. The
record's `m` field names the box, and a record without one is the Thor's —
which is what the lab's recorded stream is, so the replay is unchanged.
See `docs/lab/exp-seat-watch-live.md` §4.6.

**The gate is the lab's.** `docs/lab/exp-seat-watcher.md` §1.3 is its spec
and `docs/lab/seat-watcher/scripts/gates.py` is its reference implementation.
The parts that are shared:

* the **trailing-window slope** — the window is contiguous (the walk stops at
  a gap: 30 s for memory, 120 s for disk) and has to span 60 s (memory) or
  120 s (disk);
* the **latch** — a condition speaks on the rising edge and re-arms when it
  clears, so one stall is one speech;
* the **dwell** — a condition must hold for 30 s before it speaks, because
  the box's `MemAvailable` reads bimodally after a restart;
* the **thresholds** — 3 GB/min over 10 min (memory), 10 GB/h over 15 min
  (disk), 2 min of silence (telemetry dark).

Two numbers are not the lab's: the disk floor is **20 GB** (the brief's; the
lab used 30 GB) and the poll is **15 s** (the lab's daemon sampled every
~9 s; 15 s keeps the memory samples inside the 30 s contiguity rule).

`replay.py --verify` is the proof: it replays the lab's recorded day through
this engine and compares the result with the lab's own `events.json` and
`RESULT.json`. The numbers are in `docs/lab/exp-seat-watch-live.md`.

## The four reasons, and what each one watches

### DONE — a new EXIT line

watch-all.sh's rule, unchanged: count the `EXIT <n>` lines in every `.out`
at the start, and report the first job whose count goes up. The markers
present at the start do not count, and a `.out` that appears later counts
from zero.

**The missed-DONE rule** (the 2026-11-02 tuning): while the watcher was down
(crash, or a reinstall), a seat's EXIT line could go unreported, and the new
run's baseline would count it as old forever. So on start, before the first
log line of the new run, the watcher reads the previous run's log and
reports as `DONE` any `.out` that carries an EXIT line and was written after
the previous run's last log line. A DONE the previous run already spoke for
is not re-reported: its `speaking:` line came after the EXIT, so the `.out`
is older than the log's last line. The machine is `proart` or `thor`, as in
watch-all.sh.

### QUOTA — a provider refused

`usage limit` or `Limit Exhausted` in an `.out`, case-insensitively — the
markers board.sh already greps for.

One rule the brief does not say: the marker has to be **new**. Six `.out`
files on the Thor and one on the ProArt still carry a quota marker from
2026-11-01, and a watcher that read them all would cry quota on every
start. So the watcher reports a marker in a file it has seen written during
this watch, or a marker that was not there when the watch started.

### STALL — a seat stopped making progress

The lab's method (rate first, a trailing window, a dwell, a latch) applied
to a seat's own signals. The progress signals are:

| signal | how it is read |
|---|---|
| a commit | the worktree's `HEAD` sha (read from `.git`, no `git` process) |
| `NOTES.md` | the file's size in the seat's worktree |
| the `.out` | the file's size |
| child-process CPU | `utime + stime` over the seat's tmux pane process tree |
| network bytes | `bytes_sent + bytes_received` over that tree's sockets (`ss`) |
| a scheduled wait | a `sleep`/`timeout` child under the seat's tree (the 2026-11-02
  tuning: the director's briefs tell a seat to sleep 10-13 min between
  checks, and that is not a stall) |
| the seat's own leases | the leases (from `thor-admit status --json`) whose process tree is
  under the seat's pane: a lease whose RSS or GPU high-water moves between
  polls is a working step, so any change is progress (the 2026-11-02
  tuning: a heavy step loading inside its own lease is not a stall) |

A seat that moves none of them for **10 minutes** (the lab's window) is
stalled. Two failure shapes the brief names are watched for as well:

* `ssh_child_idle` — an `ssh` child alive for more than 30 minutes with no
  output for the same span;
* `watcher_loop` — the log's last counter line (`c=0 t=0` and the like)
  shows nothing running, and has for an hour.

A shape that is *developing* holds the generic stall back, so the reason
names the shape rather than always saying "no progress".

Only seats with a **live tmux window** are watched. The lab's §2.3 found
that 160 of the level gate's 181 seat alarms were on seats that had already
exited; a seat with no window is not a stalled seat.

### BOX — the boxes' own state

The Thor's four conditions, all the lab's:

* `memory_falling` — the live gate's memory condition (the 2026-11-02
  tuning): free memory falling faster than **3 GB/min** over 10 minutes
  (the lab's threshold) **with the leases' own growth subtracted** — a
  heavy step loading inside its own thor-admit lease takes the box's memory
  (the daemon's `lease_growth` accounting), and that is not a box problem —
  **or** `MemAvailable` near the floor (**25 GB**, the daemon's own floor,
  the lab's `mem_low_gb`). The leases' own memory is the sum of their
  current RSS and GPU high-water from `thor-admit status --json`, read on
  the Thor every poll; a box that reports no leases falls back to the lab's
  raw rate, which is what caught the JAX runaway 30 minutes early;
* `disk_low` — free disk under **20 GB** (the brief);
* `disk_falling` — free disk falling faster than **10 GB/h** over 15 minutes
  (the lab's condition; see the report for why it is here);
* `telemetry_dark` — the Thor has not reported for **2 minutes** (the lab's
  (b+) condition).

And the ProArt's one, the desk's MEM signal:

* `proart-memory` — the **ProArt's** `MemAvailable` under **2 GB**, or its
  **swap in use and rising** (0.5 GB/min over 5 minutes). The ProArt hosts
  the seats and this watcher, in a 16 GB WSL VM; it was memory that killed
  the previous seat on 2026-11-01. The floor is the last thing to fire; the
  swap condition is the leading indicator. Both thresholds are knobs
  (`--proart-mem-low`, `--proart-swap-rate`) and neither has been measured
  against a real episode — see the report's §5.

## What it does not do

* It never kills, stops or signals anything. It reports.
* It does not read the admission queue, the daemon's `lease.client_gone`
  events or the Wi-Fi driver aborts. The engine implements all three (the
  replay needs them to reproduce the lab's numbers), but the brief's BOX
  clause names memory and disk only. They are one poll of work to turn on.
* It does not watch a seat whose tmux window died without writing an `EXIT`
  line. The DONE rule needs an `EXIT` line, exactly as watch-all.sh does.

## The tests

62 tests, 14 seconds. The fixture is the lab's recorded day — the only
record of a day of real stalls that exists — plus the 2026-11-02 false
alarms (a scheduled sleep under a seat's tree, a seat's own lease loading,
and an EXIT written while the watcher was down).

```
python3 tools/seat-watch/test_seatwatch.py
```

The headline test replays the lab's day through this engine and checks that
the speeches are the lab's speeches, and that the lab's own scorer gives the
lab's numbers on them.

Two of the tests are about the two boxes: `TestTheTwoBoxes` is the
regression test for the defect in `docs/lab/exp-seat-watch-live.md` §4.6
(the boxes in one series, the disk slope reading -21,504 GB/h on healthy
boxes), and `TestProartMemory` covers the MEM signal.

See `docs/lab/exp-seat-watch-live.md` for the measured numbers and for what
was not verified.
