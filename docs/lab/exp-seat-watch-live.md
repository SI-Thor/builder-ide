# The seat watcher, live: 2026-11-01

**Question.** The lab measured a gate over 2026-11-01 and said which one to
build (`docs/lab/exp-seat-watcher.md` §4). Does that gate, run live on the
director's seats, still say the same things — and what does it cost?

**Answer.** Yes, and the check is exact rather than approximate. Replaying
the lab's own recorded day through the live engine gives the lab's speeches
back one for one: **71 speeches for the rate gate, 184 for the level gate,
77 for the rate gate plus the telemetry-dark condition, 24 for the level
gate restricted to live seats.** The lab's own scorer, run on the replay's
events, gives the lab's own numbers back: **8 of 13 interventions caught,
mean lead 50.3 min, 385.3 min of stall saved.**

The live watcher's own gate is quieter than the lab's, because it watches
less: over the same day the four `BOX` conditions speak **23 times** (1.23
per hour, against the rate gate's 3.69), and they catch the two episodes
the box could have caught: the JAX runaway **30.1 min before the director**
and the disk floor **6.4 min before**.

Two findings came out of the work and one of them changes a number the brief
carries. The brief's disk floor of 20 GB was **never crossed** on 2026-11-01
— the Thor's disk bottomed out at 21 GB — so with the brief's `BOX` clause
exactly as written, the disk episode is missed. The lab's *disk-rate*
condition catches it, 6.4 min early, and is therefore in the watcher
(§3.4, §4.1).

**A third finding came out of the second run of this seat, and it is the
important one: the live path was measuring the difference between the two
boxes rather than either box's own trend, and would have cried `BOX` about
two minutes after every start, on healthy boxes** (§4.6). The replay never
showed it, because the lab's recorded stream is one box. It is fixed now —
one channel per box — the live watcher was installed on the ProArt and ran
against the real boxes for 240 s saying nothing (§2.5), and the regression
test for it is in the suite. The ProArt's own memory (the desk's MEM
signal) was added in the same pass: `BOX proart-memory` on `MemAvailable`
under 2 GB or swap in use and rising (§4.7).

---

## 1. The mechanism

### 1.1 The box under watch

Two boxes, and they are not the same box:

| | ProArt | Thor |
|---|---|---|
| role | the seat host | the box the seats run heavy work on |
| seats | tmux session `build`, windows `z-`/`m-`/`p-<job>` | tmux session `last-mile`, windows `z-`/`m-<job>` |
| output | `~/lm-ops/wt/<job>.out` | `~/lm-wt/<job>.out` |
| worktree | `~/lm-wt/<job>` | `~/lm-wt/<job>` |
| memory | 15 GB | 122 GB unified (GPU is system memory) |
| disk | 805 GB free | 86 GB free |

The watcher runs on the ProArt, because that is where the seats' tmux
windows and their `.out` files are, and it reads the Thor over one `ssh
thor-lan`. Both boxes run `America/Anchorage`, which fell back from AKDT to
AKST at 02:00 local on 2026-11-01, so the local hour 01:00-02:00 happened
twice that day. Every comparison is in epoch seconds.

**The two boxes are watched separately.** The brief's `BOX` clause is the
Thor's (its memory falling at the lab's rate, its disk under 20 GB). The
ProArt is watched too, for its own memory, because it is the seat host: 14
seats in a 16 GB WSL VM, and it was memory that killed the previous seat on
2026-11-01. That is the desk's MEM signal, and it prints `BOX proart-memory`.
One channel per box, for the reason in §4.6.

### 1.2 What the watcher reads

One poll, every 15 s:

* **the box** — `MemAvailable` from `/proc/meminfo`, free disk from `df -Pk`,
  both read on the Thor;
* **each seat** — its `.out` (size, mtime, its `EXIT` lines, whether it
  carries a quota marker, its last counter line), its `NOTES.md`, its
  worktree's `HEAD` sha, and its tmux pane's process tree: `utime + stime`
  over the tree and `bytes_sent + bytes_received` over the tree's sockets
  (`ss -tnip`).

The collector is one piece of Python that runs **twice from the same bytes**:
locally on the ProArt, and over the ssh on the Thor (`ssh host 'python3 -'`
with the source on stdin). That is why the installed watcher is a single
file: there is no second copy to drift.

### 1.3 The gate

The gate is the lab's. `docs/lab/exp-seat-watcher.md` §1.3 is its spec and
`docs/lab/seat-watcher/scripts/gates.py` is its reference implementation.
What is shared:

* the **trailing-window slope**, with the lab's two rules: the window is
  contiguous (the walk back stops at a gap — 30 s for memory, 120 s for
  disk, so a rate is never computed across a daemon restart or across the
  box going down) and it has to span 60 s (memory) or 120 s (disk);
* the **latch**: a condition speaks on the rising edge and re-arms when it
  clears, so one stall is one speech and not one per second;
* the **dwell**: a condition has to hold for 30 s before it speaks, because
  the box's `MemAvailable` reads bimodally (127 GB and 17 GB alternating)
  for minutes after a restart;
* the **thresholds**: 3 GB/min over a 10-minute window (memory), 10 GB/h
  over a 15-minute window (disk), 2 minutes of silence (telemetry dark).

Two numbers are not the lab's, and both are named in the code:

| number | the lab | the watcher | why |
|---|---|---|---|
| the disk floor | 30 GB | **20 GB** | the brief says 20 GB |
| the poll interval | ~9 s (the daemon) | **15 s** | keeps the memory samples inside the 30 s contiguity rule |

Everything else is the lab's. The live engine is the lab's engine with a
different set of conditions switched on, and `replay.py` proves it (§3.1).

### 1.4 The four reasons

```
DONE <machine> <job>     a new EXIT line — watch-all.sh's rule
QUOTA <job>              "usage limit" / "Limit Exhausted" in an .out
STALL <job> <reason>     a seat stopped making progress
BOX <reason>             the Thor's or the ProArt's own state went wrong
```

Checked in that order; the first one that fires is the one printed, with
one line on stdout and exit 0. The reasons are single tokens so the line
splits on whitespace; the numbers behind the reason go to
`~/lm-ops/seat-watch.log` and to stderr.

`BOX` has **five** reasons. Four are the Thor's (`memory_falling`,
`disk_falling`, `disk_low`, `telemetry_dark`); the fifth is the ProArt's own
memory, `proart-memory`, which the desk's MEM signal asks for: the ProArt's
`MemAvailable` under **2 GB**, or its **swap in use and rising** (§4.7).

**DONE** is watch-all.sh's rule unchanged: count the `EXIT <n>` lines in
every `.out` at the start and report the first job whose count goes up. The
markers present at the start do not count, and a `.out` that appears later
counts from zero.

**QUOTA** greps the two markers board.sh already greps for. One rule the
brief does not state: the marker has to be **new**. Six `.out` files on the
Thor and one on the ProArt still carry a quota marker from 2026-11-01 — the
lab's §3.3 explains why they are still there (a relaunch truncates the file,
but a seat that was never relaunched keeps its transcript) — so a watcher
that read them all would cry quota on every start. The watcher reports a
marker in a file it has seen written during this watch, or a marker that
was not there when the watch started.

**STALL** is the lab's method applied to a seat's own signals: commits,
`NOTES.md` growth, `.out` growth, child-process CPU and network bytes on
the seat's process tree. A seat that moves none of them for 10 minutes (the
lab's window) is stalled. Two shapes the brief names are watched for
besides: `ssh_child_idle` (an `ssh` child alive more than 30 minutes with no
output for the same span) and `watcher_loop` (the log's last counter line —
`c=0 t=0` and the like — showing nothing running, for an hour). A shape
that is *developing* holds the generic stall back, so the reason names the
shape instead of always saying "no progress".

Only seats with a **live tmux window** are watched. The lab's §2.3 found
that 160 of the level gate's 181 seat alarms were on seats that had already
exited; the lab's (a') variant exists for that reason, and the watcher
takes the (a') rule from the start.

**BOX** is the brief's clause plus two of the lab's conditions (§4.1).

---

## 2. The numbers

### 2.1 The dry run against the lab's recorded day

The lab's own fixture is the recorded day of 2026-11-01:
`docs/lab/seat-watcher/data/stream.jsonl` (10,721 records), the window
2026-11-01 00:00:00 → 16:05:00 AKST (17.08 h). The replay runs the live
engine over it with **the lab's own parameters** (from the lab's
`events.json`), walks the stream one second at a time, and compares the
result with the lab's committed `events.json` and `RESULT.json`.

```
$ python3 tools/seat-watch/replay.py --verify
gate     speeches (mine)  speeches (lab)   same?
a        184              184              yes
b        71               71               yes
ab       95               95               yes
bplus    77               77               yes
abplus   101              101              yes
a_live   24               24               yes
```

"same" is the physics of each speech — its time, its condition, its seat
and its value — not a count. The lab's own scorer, run on the replay's
events, gives the lab's own numbers:

| | the lab | the replay |
|---|---|---|
| speeches (rate gate) | 71 | 71 |
| episodes caught | 8 / 13 | 8 / 13 |
| recall | 0.6154 | 0.6154 |
| precision | 0.113 | 0.113 |
| false-positive rate | 0.887 | 0.887 |
| false alarms / hour | 3.69 | 3.69 |
| mean lead (min) | 50.3 | 50.3 |
| max lead (min) | 162.8 | 162.8 |
| stall minutes saved | 385.3 | 385.3 |

`abplus` is the one row where the replay and the lab do not have the same
input, and the reason is a defect in the lab's own code (§4.3).

**Box state beside the number.** The replay ran on the Thor at
2026-11-01 21:03 AKST: load average 17.14 / 18.51 / 19.05 (the box was
busy with other jobs — a `serve.qwen3-vl-8b` lease at 10 G, a
`refit-drift.exp2` practice lease at 2 G, and a `night-v5.heavy` lease at
40 G; the admission queue was 0), 92 GB of memory available, 85.6 GB of disk
free, Python 3.12.3. The replay is CPU-only and took 14 s; it allocates no
lease and no GPU memory.

### 2.2 The dry run against the board's own history

The board writes a snapshot every minute into `~/lm-ops/board-history/`.
Those snapshots are the board's own record of the day, so the watcher can be
run against them directly:

```
$ python3 tools/seat-watch/replay.py --board-history ~/lm-ops/board-history
board history: 380 snapshots, 2026-11-01 14:58:57 -> 2026-11-01 21:29:02 (6.50 h)
  snapshot spacing: min 10s max 220s median 62s
  box conditions fired 11 times
    2026-11-01 15:03:35  disk_falling_fast      value=-29.0
    2026-11-01 15:37:30  disk_falling_fast      value=-20.9
    2026-11-01 15:52:23  telemetry_dark         value=151
    2026-11-01 16:01:59  disk_falling_fast      value=-53.2
    2026-11-01 16:31:17  disk_falling_fast      value=-23.6
    2026-11-01 17:31:21  disk_falling_fast      value=-12.5
    2026-11-01 17:35:26  disk_falling_fast      value=-12.5
    2026-11-01 17:39:35  disk_falling_fast      value=-16.7
    2026-11-01 19:17:54  disk_falling_fast      value=-12.5
    2026-11-01 20:35:54  disk_falling_fast      value=-12.4
    2026-11-01 21:09:33  telemetry_dark         value=151
```

**The board's own series reproduces the lab's disk-rate speeches exactly**:
the lab's three `disk_falling_fast` events are at 15:03:35 (-29.0 GB/h),
15:37:30 (-20.9 GB/h) and 16:01:59 (-53.2 GB/h), with the same values. The
first of those is the lab's E13 catch — the disk condition that fired
6.4 min before the director.

Two things the board's series shows that the lab's window did not:

* **Seven more disk-rate alarms after 16:31**, none of which the lab ever
  saw, because the lab's disk channel stops at 16:04:30. They are the
  board's own coarseness: `board.sh` prints free disk in whole GB, so a
  2-3 GB move between two snapshots reads as a steep slope. The watcher
  reads `df -Pk` (exact kilobytes) every 15 s, so it does not have this
  problem; the numbers above are a property of the board's format, not of
  the condition.
* **No memory-rate alarm at all**, and this one is structural. The board's
  snapshots are a median of **62 s** apart, and the lab's memory slope
  needs a contiguous window: the walk stops at a gap over **30 s**. So the
  board's series cannot produce a memory rate at all — and the memory rate
  is the condition that caught the JAX runaway 30 min early. The board's
  series can reproduce the disk conditions; it cannot reproduce the memory
  ones. The watcher reads `/proc/meminfo` itself every 15 s, which is what
  makes that condition work.

The board's snapshots record **the Thor only** — `board.sh` reads the Thor's
`free` and `df` over ssh — so the ProArt's own memory conditions (§4.7) have
nothing to fire on here. That is a property of the board's format, not of the
conditions: the watcher reads the ProArt's `/proc/meminfo` locally, every
15 s.

The telemetry-dark speech at 15:52:23 is the board's own record of the
Thor going quiet: the board's snapshot loop fills the box section over ssh,
and the ssh fails, so the snapshots after the 15:50 outage have no box
state. The lab's own telemetry-dark condition fired at 15:50:38 — 13 min
before the board's page showed anything wrong — because it watched the
daemon's samples rather than the board's. The second telemetry-dark speech
at 21:09:33 is the same kind of event on a later day of the board's history.

### 2.3 What the live watcher's gate says about that day

The watcher's own condition set, run over the lab's recorded day with the
watcher's parameters (the brief's 20 GB floor, the lab's other numbers):

| gate | speeches | false alarms/h | episodes caught | mean lead | stall saved |
|---|---|---|---|---|---|
| the brief's `BOX` clause exactly (memory rate + disk < 20 GB) | 14 | 0.76 | 1 / 13 (E09) | 30.1 min | 12.9 min |
| plus the lab's disk-rate and telemetry-dark | 23 | 1.23 | 2 / 13 (E09, E13) | 18.3 min | 19.3 min |

and the lab's rate gate, for comparison: 71 speeches, 3.69 false alarms/h,
8 / 13 caught, 50.3 min mean lead, 385.3 min of stall saved.

Those two rows are the **Thor's** four conditions, and they are what the
watcher says about the Thor. The watcher's fifth `BOX` condition — the
ProArt's own memory (§4.7) — is silent on this day, because the lab's
recorded stream is the Thor's series and carries no ProArt data at all.
Its yield is unmeasured (§5).

The live gate is quieter because it is narrower: it watches the box, not the
seats. The five episodes the rate gate caught that the live gate does not
(E01 the GPU floor block, E03 and E10 the hung seats, E06 the FIFO hold,
E11 the Wi-Fi saturation) are **seat-level** episodes, and they belong to
the `STALL` channel, whose conditions are new and cannot be scored against
the lab's labels (§5).

### 2.4 The tests

```
$ python3 tools/seat-watch/test_seatwatch.py
Ran 48 tests in 14.528s
OK
```

(As of the 2026-11-02 tuning, §7: 62 tests, 14.5 s, same run time.)

The fixture is the lab's data directory: the recorded day, the lab's
parameters, the lab's `events.json`, the lab's `RESULT.json` and the lab's
own scorer. The headline test replays the day through the live engine and
checks the speeches one for one and the scores number for number; the rest
cover the latch, the contiguity rule, the DONE rule, the QUOTA rule, the
stall gate and its two shapes, the box conditions, the collector's scanning
of a real `.out`, the two boxes' separation (§4.6) and the ProArt's own
memory (§4.7).

**Box state beside the number:** the test suite ran on the Thor at
2026-11-01 21:32 AKST, load average 18.08 / 20.64 / 23.62 (the box was busy
with other seats: three leases — `night-v5.heavy` at 40 G peak,
`world-snapshot.server` at 4 G and `stratego.rl128` at 10 G — and the
admission queue was 0), 72.3 GB of memory available, 86 GB of disk free.
CPU-only, 14.5 s, no lease taken.

### 2.5 The live run

The watcher was installed on the ProArt at `~/lm-ops/seat-watch.sh` and run
against the live boxes for **240 s**, at the real poll interval of 15 s:

```
$ setsid nohup ~/lm-ops/seat-watch.sh --timeout 240 > /tmp/sw.out 2>&1 &
$ cat /tmp/sw.out
2026-11-01 21:27:27  watching 206 jobs (proart 63, thor 143); poll 15s; window 600s
TIMEOUT
```

**It said nothing.** No `DONE`, no `QUOTA`, no `STALL`, no `BOX` — the box
conditions held their fire through a real 15-minute disk window, and the
watcher's log recorded no poll error, so the ssh to the Thor answered on
every poll. `TIMEOUT` is the watcher's own "I watched for the whole window
and nothing happened", printed on stdout with exit 0.

This is the run that the first version of the watcher would have failed: on
that version the disk condition spoke about two minutes in, on healthy boxes,
with a rate of -21,504 GB/h (§4.6). The regression test for it is
`TestTheTwoBoxes` in `test_seatwatch.py`.

**Box state beside the number:** the run was on the ProArt at 21:27-21:31
AKST, 2026-11-01: 8.5 GB of memory available of 16 GB, 805 GB of disk free,
swap 0 of 8 GB in use, load average 0.14 / 0.29 / 0.32. The Thor, read over
the ssh on the same poll: 80.7 GB of memory available, 85.4 GB of disk free.

**What this run does not show.** The `STALL` channel was not exercised: its
window is 10 minutes and the run was 4, so a seat that had been silent for
the whole window could not have been reported. What the run does show is
that the box conditions do not fire on healthy boxes, which is the failure
mode that matters here.

---

## 3. What it makes possible

1. **The director's own job has a watcher.** The lab's interventions were
   13 hand-made judgements in a day; the rate gate would have caught 8 of
   them with a mean of 50 min of lead. That gate now runs, on the seats, at
   15-second resolution, and it says one line and stops.
2. **The box's own health is watched, not read by hand.** The disk episode
   was caught by the director reading `df` at 15:10; the watcher's
   disk-rate condition catches the same fall at 15:03:35, and its
   telemetry-dark condition is the only one that noticed the Thor's 15:50
   outage.
3. **The watcher is the same gate the lab measured, and that is checkable.**
   The replay is not a claim about equivalence; it is the lab's own fixture
   and the lab's own scorer, and it returns the lab's numbers.

---

## 4. What the work found

### 4.1 The brief's 20 GB disk floor misses the disk episode

The brief's `BOX` clause is "MemAvailable falling faster than the lab's
threshold, or disk < 20 GB". On 2026-11-01 the Thor's free disk bottomed
out at **21 GB** (15:14:25 and 15:19:33) and then recovered to 49 GB at
15:20:34 after the dedupe. So the 20 GB floor **was never crossed**, and
with the brief's clause exactly as written the disk episode (E13) is
missed. The lab's *disk-rate* condition catches it, 6.4 min before the
director, and that condition is therefore in the watcher.

This is a small change and it is flagged in the code and here: `BOX` has
four reasons, of which `memory_falling` and `disk_low` are the brief's,
`disk_falling` and `telemetry_dark` are the lab's.

The floor itself is kept, at the brief's 20 GB: it is a backstop, and on
that day it stayed quiet. With the lab's 30 GB floor the watcher's gate
speaks 24 times instead of 23 and catches the same two episodes, so the
floor's value is not what does the work here.

### 4.2 The board's series cannot produce a memory rate

§2.2: the board's snapshots are a median of 62 s apart and the memory slope
needs gaps under 30 s. The board's history is good enough for the disk
conditions and not good enough for the memory ones. The watcher samples
`/proc/meminfo` itself, every 15 s, which is why the condition that caught
the JAX runaway works live.

### 4.3 The lab's `abplus` gate is missing its level conditions

`docs/lab/seat-watcher/scripts/gates.py` runs its level block for `which in
("a", "ab")` — `abplus` is not in that tuple, so the gate labelled "level +
rate + telemetry-dark" runs no level condition at all. The lab's committed
`events.json` shows it: `abplus` has **77** speeches and its condition set
is exactly `bplus`'s. The correct gate has 101 (its `ab` has 95, plus the 6
telemetry-dark events).

This does not touch the lab's headline numbers — the report's table (§2.1)
does not list `abplus` — but the artefact is wrong and the replay says so
rather than hiding it. The lab note is corrected in the same commit
(`docs/lab/exp-seat-watcher.md` §1.3, with the defect named and the gate's
old label kept visible).

### 4.4 The lab's E13 row quotes a disk rate that is not in the data

The lab note's §2.2 table gives E13's condition as "disk falling 55 GB/h".
The lab's own committed event for that speech says **-29.0 GB/h**, and the
steepest 15-minute disk slope in the recorded series is **-49.9 GB/h** (at
15:14:25, measured with the lab's own slope code). The number 55 does not
appear in the data. The note is corrected in the same commit; the old text
is kept visible there, and the correction names the committed event it is
read from.

### 4.5 The lab's level gate measures a seat's age from its *first* captured write

`gates.py` builds each seat's record with `setdefault`, so a seat's
`write` is the first `.out` mtime it was captured with, not the last, even
though the accessor is called `seat_out_age` and its docstring says "since
the seat last produced output". On that day 183 of the 184 seats were
captured exactly once, so the first write and the last write are the same
moment for all but one seat: the lab's 181 seat alarms all match the
first-write age, and 180 of them also match the last-write age. The replay
mirrors the lab's semantics deliberately (the reproduction is the point) and
this is noted in the code where it does it.

### 4.6 The live path measured the difference between the boxes

**Found 2026-11-01, after the first seat of this work was killed by the
ProArt's crash.** The replay in §2.1 was always right, because the lab's
recorded stream is one box. The **live** path was not: the poll read the
ProArt and the Thor into **one** series for the memory and disk channels.
The ProArt had 804 GB of disk free and the Thor 85 GB, so the series
alternated between the two on every poll, and the trailing-window slope
measured the difference between the boxes rather than either box's own trend.

Measured on the real values, over the 120 s the disk window needs to fill:

| | the live path (both boxes in one series) | the Thor alone (the truth) |
|---|---|---|
| disk slope | **-21,504 GB/h** | 0.0 GB/h |
| memory slope | +42.0 GB/min | 0.0 GB/min |

The disk condition is "falling faster than 10 GB/h", so **-21,504 GB/h**
fires it, and the dwell is 30 s, so it would have spoken about **two
minutes after every start**, on healthy boxes, with a reason that named the
Thor. The memory channel read +42 GB/min instead of a fall, so it never
fired at all — which is worse, because the memory rate is the condition
that caught the JAX runaway 30 minutes early.

Nothing in §2.1 showed this, and nothing in the tests did either: the
tests fed the engine one box at a time, which is the lab's shape. It was
found by running the installed watcher on the live boxes and watching it
say nothing (§2.5) — after the fix. Before the fix, the live watcher was
**not** the thing this report describes, and the report's §2.1 numbers were
the only ones it ever had.

**The fix** is one channel per box (`BoxChannel` in `seatwatch.py`): the
Thor's memory and disk go to the Thor's channel, the ProArt's to the
ProArt's, and a record with no machine tag is the Thor's — which is what
the lab's stream is, so the lab's numbers are untouched (`replay.py --verify`
still returns 184 / 71 / 95 / 77 / 101 / 24 and 8 of 13). The regression
test is `TestTheTwoBoxes`.

### 4.7 The ProArt's own memory: the MEM signal

The desk's MEM signal: **the ProArt's `MemAvailable` under 2 GB, or its
swap in use and rising → `BOX proart-memory`**. Two conditions, one reason.

The floor is the desk's number, and it is the last thing to fire: the
ProArt's `MemAvailable` was 8.5 GB of 16 GB during the live run. The swap
condition is the leading indicator, because it can speak while there is
still memory to spare: the ProArt has 8 GB of swap, and swap that is *used*
and *rising* means the kernel is pushing pages out now, not that it has
run out.

| number | value | where it comes from |
|---|---|---|
| the memory floor | 2 GB | the desk's MEM signal |
| the swap rate | 0.5 GB/min | this seat's choice; the desk names no threshold |
| the swap window | 5 min | this seat's choice, the lab's window shape |
| the dwell | 30 s | the lab's |

The swap threshold is **not measured** — no swap episode was recorded on
the ProArt, so 0.5 GB/min over 5 minutes is a judgement, not a
measurement, and it is the first thing to sweep (§5). It is conservative in
one direction: 2.5 GB of swap consumed in 5 minutes on a 16 GB box is a lot,
so it will not fire on a seat that allocates and releases. It is not
conservative in the other: a box that swaps slowly and steadily can still
reach the floor, and the floor is the backstop. Both thresholds are
command-line knobs (`--proart-mem-low`, `--proart-swap-rate`).

The swap series is read from `/proc/meminfo` (`SwapTotal` - `SwapFree`) on
the ProArt, locally, every 15 s. The lab's contiguity rule applies to it
as it does to every other rate: the walk stops at a gap over 30 s, so a
gap in the evidence is never read as a rise.

---

## 5. What was not verified

- **The ProArt's MEM signal has never fired.** The two conditions
  (`proart_memory_low`, `proart_swap_rising`) are new, they are tested
  against synthetic fixtures, and the live run in §2.5 was on a healthy box
  (8.5 GB available, 0 swap in use), so neither could fire. The swap
  threshold of 0.5 GB/min over 5 min is a judgement, not a measurement: no
  swap episode has been recorded on the ProArt to measure it against. It
  is the first thing to sweep when one happens.
- **The live run was 240 s, so the `STALL` channel was not exercised
  live.** Its window is 10 minutes. What the run does show is that the box
  conditions do not fire on healthy boxes (§2.5) — which is the failure
  mode that matters, because it is the one the first version had (§4.6).
- **The watcher has not seen a real stall.** The lab's day is a replay; the
  live watcher's `STALL` conditions are new, and no seat stalled while the
  watcher was running. They are tested against synthetic fixtures and
  against the lab's recorded day, but "it catches a real stall" is not
  measured.
- **The coldshelf watcher-loop artefact could not be recovered.** The brief
  describes it as "a remote watcher/sleep loop whose log shows nothing
  running (the coldshelf case: `c=n t=n` lines for an hour)", but the
  coldshelf seat's `.out` on the ProArt is **0 bytes** — the 14:20 quota
  relaunch truncated it, which is the lab's §3.1 finding. The detector is
  written to the brief's description (a counter line whose values are all
  zero, repeated, unchanged, for an hour) and tested against a synthetic
  fixture. The exact line format of that artefact is not verified.
- **The network-byte signal is `ss(8)`'s per-socket counters**, not a
  kernel-level per-process byte count. `ss` is present on both boxes and
  was checked on both, but a socket's counters are reset when the socket is
  closed, so a seat that reconnects can show a drop in the cumulative
  total. That reads as "no progress" for one poll, not as a stall.
- **The lab's API-error channel is still nearly empty.** The watcher reads
  provider failures from the live `.out` files rather than from a counter
  that survives the relaunch, which is what the lab's §4.4 asked for, but
  the watcher has not been running during a quota episode, so the channel's
  live yield is unmeasured. A quota marker is reported as `QUOTA`, not
  through the lab's burst rule, and the burst rule's thresholds (2 failures
  in 5 min) were not re-measured against a live channel.
- **The queue, `lease.client_gone` and Wi-Fi-abort conditions are
  implemented but not fed.** The brief's `BOX` clause names memory and disk
  only. Turning them on is one poll of work each, and the lab's numbers
  for them are in `docs/lab/exp-seat-watcher.md` §2.6.
- **One day, one box.** 13 episodes is a small labelled set; the lab says
  so. The live watcher's condition set is the lab's, so the same caveat
  carries over.
- **The `STALL` window and the two shapes' thresholds are the brief's and
  the lab's window respectively; neither has been swept.** The lab's sweep
  (§2.6) covers the rate gate's thresholds, not a per-seat progress gate.

---

## 6. Reproducing it

```
python3 tools/seat-watch/replay.py --verify            # the lab's recorded day
python3 tools/seat-watch/replay.py --board-history ~/lm-ops/board-history
python3 tools/seat-watch/test_seatwatch.py              # 62 tests (48 before the 2026-11-02 tuning)
~/lm-ops/seat-watch.sh --once                          # one live poll
~/lm-ops/seat-watch.sh --timeout 240                   # four minutes live
```

Pure Python, standard library only. The replay takes 14 s on the Thor, the
tests 14.5 s, the board-history replay 2 s on the ProArt, and a live poll
about 1 s (one local collector and one ssh). `tools/seat-watch/README.md`
has the details.

The watcher's copy lives on the ProArt at `~/lm-ops/seat-watch.sh` (mode
755, installed 2026-11-01); the source is `tools/seat-watch/seatwatch.py` on
the Thor, and the installed copy is byte-identical to it. Despite the name
it is a Python program with a `#!/usr/bin/env python3` line: the brief asks
for one self-contained file, and a Python file is what the collector has to
be (the same bytes run locally and over ssh).

Related: `docs/lab/exp-seat-watcher.md` (the measurement this is built
from, with two corrections), `docs/design/screen-watcher.md` (the design it
is the first experiment of), `~/lm-ops/watch-all.sh` (the DONE rule's
source), `~/lm-ops/board.sh` (the QUOTA markers' source).

---

## 7. The 2026-11-02 tuning: four false signals, and the EXIT that was missed

**Question.** After a night of live use, the director's log: of 7 signals,
4 were false — 3 `STALL` (seats waiting 10-13 min between checks, as their
briefs tell them to) and 2 `BOX memory_falling` (a heavy step loading
*inside its own thor-admit lease*, 65-72 GB still free) — and one seat's
`EXIT` was missed while the watcher restarted. Can the watcher tell the
false ones from the true ones without losing the true ones?

**Answer.** Yes, with three small changes and 14 new tests (62 total).
The replay is untouched: it still returns the lab's numbers one for one
(184 / 71 / 95 / 77 / 101 / 24, 8 of 13, 50.3 min, 385.3 min), because the
lab's stream carries no lease records and the new condition is not in the
lab's gates.

The false signals, from the watcher's own log (`~/lm-ops/seat-watch.log`):

```
2026-11-01 21:45:50  STALL stratego-desk ssh_child_idle
2026-11-01 23:57:39  STALL crafter-r2 no_progress
2026-11-02 00:24:59  STALL ingame-phase2-desk no_progress
2026-11-01 22:06:01  BOX memory_falling  value=-4.02
2026-11-02 00:14:43  BOX memory_falling  value=-4.23
```

### 7.1 Why the false ones were false

* **`STALL` on a sleeping seat.** The progress signals are commits,
  `NOTES.md` growth, `.out` growth, child-process CPU and network bytes. A
  seat that sleeps between checks, as its brief instructs, moves none of
  them for 10-13 minutes — longer than the 10-minute window — and is
  reported `no_progress` while doing exactly what it was told to do.
  A heavy step under its own lease is the same shape: while JAX loads,
  the seat's tree is nearly idle, its `.out` is quiet, and the lease's
  RSS/GPU are not among the watched signals.
* **`BOX memory_falling` on lease growth.** The lab's memory rate is right
  for a runaway (it caught the JAX episode 30.1 min early), but it cannot
  tell a runaway from the box doing its job: a seat's own lease growing
  *is* free memory falling. The admission daemon already makes this
  distinction — its `guard.unexplained_drop` events separate
  `lost_bytes` from `lease_growth_bytes` — the watcher did not.

### 7.2 What changed

1. **Two more progress signals for `STALL`** (tonight's three false
   alarms):
   * a `sleep` or `timeout` child under the seat's tree counts that poll as
     progress — the seat's own scheduled wait;
   * the seat's own leases, matched by pid/pgid into the seat's process
     tree from `thor-admit status --json` (read on the Thor, where the
     daemon lives): a lease whose RSS or GPU high-water moves between
     polls is a working step, so any change is progress. A lease that is
     alive but *frozen* is still a stall.
2. **`BOX memory_falling` now means *unexplained*.** The live gate's memory
   condition is `memory_unexplained`: the lab's rate with the leases' own
   growth subtracted (their summed current RSS + GPU high-water, over the
   same 10-minute window and contiguity rules), firing only when the
   unexplained drop remains over **3 GB/min**, or when `MemAvailable` is
   near the floor — **25 GB**, the daemon's own floor, the lab's
   `mem_low_gb`. A box with no lease data falls back to the lab's raw
   rate, so the JAX-runaway catch is structurally preserved. The lab's
   gates never run the new condition, and the lab's stream has no lease
   records, so `replay.py --verify` is byte-identical to before.
3. **The missed-DONE rule.** On start — before this run writes its first
   log line — the watcher reads the previous run's log and reports `DONE`
   for any `.out` that carries an `EXIT` line and was written after the
   previous run's last log line. A DONE the previous run already spoke for
   is not re-reported: its `speaking:` line came after the EXIT, so the
   `.out` is older than the log's last line.

### 7.3 The numbers

| | before | after |
|---|---|---|
| tests | 48 | **62** (14.5 s on the Thor) |
| replay `--verify` | 184/71/95/77/101/24, 8 of 13 | unchanged |
| STALL on a 13-min scheduled sleep | fired at 10 min | held, then names the real stall when the sleep ends |
| `memory_falling` on a 4 GB/min fall that is 4 GB/min of lease growth (65-72 GB free) | fired | held |
| `memory_falling` on the same fall with no leases | fired | fires (the JAX catch) |
| an `EXIT` written while the watcher was down | swallowed by the new baseline | reported on start |

The 14 new tests take tonight's cases as fixtures: the 13-minute sleep
(plus `timeout`), a lease loading with its RSS moving, a lease with only
its GPU high-water moving, a lease alive but frozen (still a stall),
the explained / partially-explained / unexplained fall, the near-floor
clause, and the missed `EXIT` in four shapes.

The near-floor clause also caught a **real** near-OOM in the board
history that the old rate gate never caught: on 2026-11-01 15:49:52 the
board reads “Thor: 0 GB available” (47 GB at 15:48, spiking up and down
as the leases fought each other), and the board's box section goes
dark at 15:51. The replay over the grown board history (980 snapshots,
14:58 → 07:40, 16.7 h — §2.2's run was a snapshot at 21:29) now has 12
box conditions, the extra one being
`2026-11-01 15:50:22 memory_unexplained "the Thor has 0.0 GB of memory
free (near the 25 GB floor)"`. The old `memory_falling_fast` needs a
sustained, contiguous fall; this event is a spike into zero, which only
a level condition can see. **Box state beside the number:** the rerun
took 46 s on the ProArt (load 0.34, 8 GB free).

The 14 new tests' run and the replay `--verify` ran on the Thor at
2026-11-02 07:35 AKST, load average 12.03 / 11.42 / 9.88 (5 leases on the
box, ~27 GB of lease memory), 72.9 GB of memory available, 81.5 GB of
disk free. CPU-only, 14.5 s, no lease taken.

The watcher was reinstalled on the ProArt at `~/lm-ops/seat-watch.sh`
at 07:34 on 2026-11-02, byte-identical to `seatwatch.py`, and one instance
is running with `--window 1800` (the two old instances, which had been
running in parallel, were retired on the swap).

### 7.4 What this does not verify

* **Neither fix has been exercised live yet.** The lease subtraction and
  the lease/sleep progress signals are tested against fixtures shaped on
  tonight's cases; the watcher has not yet been running through a real
  heavy step under a lease, or a real scheduled sleep. The first such
  episode is the verification.
* **A sleeping seat is now trusted unconditionally.** A hung seat sitting
  in a `sleep 900` loop is progress on that channel, and the `no_progress`
  gate will not name it. The brief told the seats to sleep between checks,
  so the brief says that shape is progress; the `ssh_child_idle` and
  `watcher_loop` shapes are unchanged and can still name such a seat.
* **The missed-DONE rule uses the `.out`'s mtime as the EXIT's time.** An
  `.out` written *after* its EXIT line (trailing wrapper output) moves its
  mtime forward and can re-report an already-spoken DONE at the next
  restart. No such case was in tonight's log; it is the first thing to
  watch for.
* **The lease match is by pid/pgid membership in the seat's tree.** A lease
  started from outside the seat's pane (a background server the seat talks
to) is not its progress, and its growth is not subtracted per-seat — the
  box-level subtraction still covers it, because it sums *all* leases.
