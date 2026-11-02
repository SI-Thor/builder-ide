# The seat watcher, measured: 2026-11-01

**Question.** Would a time-first gate have caught the director's interventions of
2026-11-01 earlier, and with fewer false alarms, than the director did by hand?

**Answer.** Yes for the rate gate, and the gain is large on lead time; no for the
level gate, which is drowned by its own false alarms. The rate gate caught **8 of
13** interventions against the level gate's **4**, using **71 speeches** against
the level gate's **184**, and it spoke a mean of **50 minutes** before the
director instead of **33**. The combined gate (c) was strictly worse than the rate
gate alone: it caught the same 8 and made 24 extra speeches.

What the experiment also found, and this turned out to matter more than the
precision numbers: **the day's failures were mostly not visible in the change
stream**, and the two that were visible (the JAX preallocation and the Wi-Fi
saturation) were visible *as rates* long before they were visible as levels.

And a third thing, which only showed up because the Thor died while the
experiment was running: **the watcher has to notice its own telemetry going
dark.** A rate gate with that one extra condition spoke at 15:50:38, thirteen
minutes before the board's own page showed that the box had stopped answering.

---

## 1. The mechanism

### 1.1 What was watched

The box under watch is the **Thor** (Jetson Thor, 122 GB unified memory, 936 GB
NVMe). The ProArt box is the seat host: 15 GB of RAM, 809 GB of disk, no GPU.
Every threshold in the brief (memory under 25 GB, disk under 30 GB) is a Thor
threshold, so the box-state channels are the Thor's.

The window is **2026-11-01 00:00:00 to 16:05:00 local** (17.08 h) - everything
the capture holds. The design doc proposed 06:00-15:00; the data covers more than
that and the early hours hold three of the thirteen interventions, so the whole
day is scored and the design-doc window is a subset. Both boxes run
`America/Anchorage`, which fell back from AKDT to AKST at 02:00 local that
morning: the local hour 01:00-02:00 happened twice. Every comparison in the
scripts is in epoch seconds.

### 1.2 The change stream

`scripts/capture.py` copies every source into `raw/`; `scripts/reconstruct.py`
turns them into a change stream of 10,721 records (`data/stream.jsonl`).

| channel | source | coverage | resolution |
|---|---|---|---|
| per-seat output age | `.out` mtime on both boxes | whole day | exact, 1 s by construction |
| per-seat last commit age | `git log` in each seat's worktree (15 Thor repos, 3 ProArt) | whole day | exact |
| box free memory | thor-admit `daemon.sample` `mem_available_bytes` | 2026-10-31 21:19 -> 2026-11-01 15:48 | ~9 s samples, held |
| box memory rate | trailing-window slope of the above | same | per tick |
| queue length | thor-admit `daemon.sample` `waiting` | same | ~9 s |
| disk free | board-history `Thor disk: NG free` | **14:58:57 -> 16:04:30 only** | ~42 s |
| disk rate | trailing-window slope | same | per tick |
| API error lines | provider failures in seat transcripts | 2 records (see 3.3) | per event |
| admission clients lost | thor-admit `lease.client_gone` | whole day | per event |
| network error rate | Thor journal `_cmd_abort_notify abort=1` | whole day | per minute |
| **telemetry alive** | the age of the last box sample | whole day | per tick |

**The reconstruction is exact against the board's own numbers.** The board prints
an `out age (min)` column for every seat in every snapshot; that column is
`now - .out mtime`, and the reconstruction reproduces it: **676 comparisons, 89
rows where the seat was still being written (consistent, age 0), 0 mismatches.**

Two gaps are structural and are recorded in `data/stream-meta.json` rather than
papered over:

1. **Disk free exists for 71 minutes of a 17-hour day.** `board.sh` only started
   writing snapshots at 14:58:57, and there is no other disk sampler on either
   box (`archive.log` and `to-ext.log` contain no `df`; there is no crontab).
   The disk clauses of both gates are therefore only evaluable after 14:58 -
   which happens to contain the one disk incident.
2. **Silence before a seat's last write is not recoverable.** The `.out` mtime
   is the last write. A seat that stalled at 10:00 and wrote once at 12:00 looks
   identical to one that wrote continuously. The reconstruction therefore treats a
   seat as producing output until its last write. This understates output age,
   so it under-reports stalls - the direction that loses catches, not the
   direction that invents them.

### 1.3 The gates

Each gate walks the stream one second at a time. Every condition **latches**: it
speaks on the rising edge and stays quiet until the condition clears, so one
stall is one speech and not one per second. Every condition must also **hold for
30 seconds** before the gate speaks, because the box's `MemAvailable` reads
bimodally after a restart (127 GB and 17 GB alternating for minutes at a time)
and without the hold the rate gate chatters.

**(a) Level gate** - the brief's fixed thresholds: output older than 45 min,
memory under 25 GB, disk under 30 GB.
**(b) Rate gate** - time-first: memory falling faster than 3 GB/min over a
10-minute trailing window; disk falling faster than 10 GB/h over 15 minutes; 2
provider failures in 5 minutes; 2 admission clients lost in 5 minutes; 20 Wi-Fi
driver aborts in 5 minutes; the queue growing by 3 in 10 minutes while more than
50 GB of memory is still free.
**(c) a+b** - both, as one gate.
**(a')** - a variant of (a): the seat clause applied only to seats that have not
reported an exit.
**(b+)** - a variant of (b) with one extra condition: **the box has not reported
for 2 minutes**. This one is not in the brief; it is reported separately because
it is the condition that noticed the Thor's second outage, and it was added
after the fact rather than designed in.

Rates need a *contiguous* history: the window ends at any gap larger than 30 s,
so no rate is ever computed across a daemon restart or across the box going
down.

### 1.4 The labels

13 episodes, 8 kinds, hand-extracted from `TEAM.md`, the Thor's
`last-mile-ops.md`, the daemon log, the journal and the seat transcripts, with
the source line recorded for each in `scripts/labels.py`. Each episode has an
**onset** (when the problem became observable), the director's **first action**
(`t_help`, the point a gate has to beat) and the **last action**. Two onsets are
the observable onset rather than the time the director wrote it down: the FIFO
hold began when the daemon's `waiting` count started climbing at 06:21:56 with
64-102 GB of memory free (TEAM.md stamps it 06:35), and the Wi-Fi saturation is
visible in the journal's 5-minute rolling abort count from 11:49 (26, against a
day median of 8), not from 12:00.

### 1.5 The scoring rule

Three matching rules are reported, because they answer different questions.

- **`time_only`** - the brief's literal rule: any speech within +/-10 min of the
  help point, whatever it was about.
- **`kind_aware`** - the same window, but the speech must be about the right kind
  of problem (`labels.SIGNALS`): a stale-seat alarm that lands two minutes
  before a quota exhaustion is a coincidence, not a catch.
- **`episode`** - kind-aware, with the window running from the problem's onset to
  the director's action. This is the rule that answers the question the
  experiment asks. A gate that speaks 2 h 43 m before the director acts is a
  better catch, not a worse one, and a +/-10 min window cannot see that.

Each help point takes at most one speech (the earliest, which gives it the best
lead credit); each speech matches at most one help point. `TP` = matched
speeches, `FP` = unmatched speeches, `FN` = unmatched episodes. The
false-positive rate is the share of speeches that were wrong, `FP/(TP+FP)`.
Lead time is `t_help - t_speak`; stall minutes saved is the same, capped at the
moment the problem became unrecoverable where that is known (for the JAX hang,
10:46:47, when the box stopped answering).

---

## 2. The numbers

### 2.1 The gates against the interventions

`episode` rule (the headline), over 17.08 h:

| gate | speeches | episodes caught | recall | precision | FPR | false alarms/h | mean lead (min) | max lead (min) | stall minutes saved |
|---|---|---|---|---|---|---|---|---|---|
| **(a) level** | 184 | **4 / 13** | 0.308 | 0.022 | 0.978 | 10.54 | 32.6 | 57.6 | 113 |
| **(b) rate** | **71** | **8 / 13** | **0.615** | **0.113** | **0.887** | **3.69** | **50.3** | **162.8** | **385** |
| **(c) a+b** | 95 | 8 / 13 | 0.615 | 0.084 | 0.916 | 5.09 | 50.3 | 162.8 | 385 |
| (b+) rate + telemetry-dark | 77 | 8 / 13 | 0.615 | 0.104 | 0.896 | 4.04 | 50.3 | 162.8 | 385 |
| (a') level, live seats only | 24 | 2 / 13 | 0.154 | 0.083 | 0.917 | 1.29 | 16.2 | 27.1 | 15 |

`time_only` rule (the brief's literal +/-10 min), for comparison:

| gate | speeches | episodes caught | recall | precision | FPR | false alarms/h |
|---|---|---|---|---|---|---|
| (a) level | 184 | 10 / 13 | 0.769 | 0.054 | 0.946 | 10.19 |
| (b) rate | 71 | 10 / 13 | 0.769 | 0.141 | 0.859 | 3.57 |
| (c) a+b | 95 | 10 / 13 | 0.769 | 0.105 | 0.895 | 4.98 |
| (b+) | 77 | 10 / 13 | 0.769 | 0.130 | 0.870 | 3.92 |

The two rules disagree on **two** of the level gate's six "catches", and those two
were coincidences: a stale-seat alarm inside the +/-10 min window of a quota
exhaustion. That is the whole reason the stricter rule is reported.

### 2.2 Which episodes, and how early

`episode` rule, rate gate (b). Local times; the box state is the Thor's.

| episode | kind | onset | director acted | gate spoke | condition | lead (min) | stall saved (min) |
|---|---|---|---|---|---|---|---|
| E01 | gpu-floor-block | 01:23:23 | 04:11 | 01:28:11 | queue growing, 100 GB free | **+162.8** | +162.8 |
| E02 | quota-exhausted | 02:25 | 02:29 | - | - | - | - |
| E03 | hung-seat | 01:28 | 02:48 | (01:23:13 AKST = 10:23 UTC) | clients lost | +84.8 | +84.8 |
| E04 | duplicate-download | 02:29 | 03:21 | - | - | - | - |
| E05 | lock-starvation | 22:29 (Oct 31) | 03:53 | - | - | - | - |
| E06 | lock-starvation (FIFO) | 06:21 | 06:35 | 06:31:50 | queue growing, 75 GB free | +3.2 | +3.2 |
| E07 | quota-exhausted | 08:30 | 08:33 | - | - | - | - |
| E08 | quota-exhausted (z.ai) | 09:00 | 09:05 | - | - | - | - |
| E09 | JAX runaway | 10:28:50 | 11:04 | 10:33:52 | memory falling 3.0 GB/min | **+30.1** | **+12.9** |
| E10 | hung-seat | 10:45 | 11:47 | 11:21:33 | clients lost | +25.4 | +25.4 |
| E11 | API timeouts (Wi-Fi) | 11:49 | 13:07 | 11:52:30 | 26 aborts / 5 min | **+74.5** | +74.5 |
| E12 | quota-exhausted | 14:20 | 14:38 | 14:22:43 | clients lost | +15.3 | +15.3 |
| E13 | disk under floor | 14:58 | 15:10 | 15:03:35 | disk falling 55 GB/h | +6.4 | +6.4 |

(The E03 row is the Alaska fold: 01:23:13 AKST is 10:23 UTC, which is 55 minutes
*after* the 09:28 UTC onset, although the local clock reads earlier. All
comparisons are in epoch seconds.)

The same table for the level gate (a): it catches E03, E09, E10 and E13 only -
**4 episodes**, of which E13 (disk under 30 GB) it catches 5.4 min before the
director, and E09 (memory under 25 GB) 1.1 min before.

### 2.3 Why the level gate fails

**160 of the level gate's 181 seat alarms are on seats that had already exited.**
A seat that finishes cleanly leaves a `.out` file whose mtime never moves again,
so its "output age" grows without bound and it becomes a permanent alarm. The
level gate as literally specified has no way to tell a hung seat from a finished
one, because both look like "no recent output". The variant (a'), which applies
the seat clause only to seats that are still alive, cuts the gate from 184
speeches to 24 - and catches **fewer** episodes (2), because the seats it stops
alarming about are exactly the ones that had been killed by the director.

The remaining two level conditions are rare and useful: the memory floor fired
twice (10:36:53, during the JAX hang, and 11:02:57, during the relaunch of the
same run after the reboot) and the disk floor once (15:04:37, 5.4 min before the
director remounted the drive).

### 2.4 Why the rate gate wins

Three of the rate gate's catches are cases where the **level** was still fine and
only the **rate** was wrong:

| episode | level at the time | rate at the time |
|---|---|---|
| E01 GPU floor | 100 GB free, disk fine | queue 0 -> 10 in 15 min while 88 GB was free |
| E09 JAX | 74 GB free at 10:28:50, then 32 GB | 74.6 -> 32.3 GB in 6 min = **7.1 GB/min** |
| E11 Wi-Fi | no disk or memory pressure at all | 26 driver aborts in 5 min against a median of 8 |

E09 is the clearest case in the day. The level gate could not fire until the
memory had already fallen below 25 GB, at 10:36:53 - by which time the box was
4 minutes from dropping the desktop. The rate gate fired at **10:33:52**, on a
10-minute trailing slope of 3.0 GB/min, with 32 GB still free and the box still
alive. It would have spoken **30.1 minutes before the director** and saved
**12.9 minutes of stall** (capped at 10:46:47, when the box stopped answering;
the full gap to the director's 11:04 is 30.1 minutes).

E11 is the other one: the director's first action on the Wi-Fi saturation was at
13:07, when seats were already timing out. The journal's abort count had left
the day's baseline at 11:49 - **78 minutes earlier** - and the rate gate spoke
at 11:52:30.

### 2.5 The condition that was not in the brief

The Thor stopped answering at about 15:50, while the experiment was running
(the same signature as the 10:46 hang). The daemon's last sample before that
was 15:47:59. The board's own page showed the box state missing only at the
**16:04** snapshot, because `board.sh` fills that section over ssh and the ssh
fails.

The (b+) variant's extra condition - *the box has not reported for 2 minutes* -
fired at **15:50:38**, 2 min 39 s after the last sample and **13 minutes before
the board noticed**. The same condition fires four times during the 10:46 hang
(10:39:57, 10:43:20, 10:51:51, 10:58:17), because the daemon's sampling went
sparse (203 s and 230 s gaps) before the box died outright. E09 is credited to
the memory rate instead, which spoke earlier, but for the 15:50 outage the
telemetry-dark condition is the only thing that fired at all.

This is the time-first idea applied to the watcher itself: the rate of change
went to zero because there was nothing left to change.

### 2.6 Sensitivity

The rate gate's four free thresholds, swept with everything else held fixed
(`episode` rule). The headline row is the default.

| parameter | value | speeches | caught | precision | recall | FPR | false alarms/h |
|---|---|---|---|---|---|---|---|
| memory rate (GB/min) | 1 | 99 | 8 | 0.081 | 0.615 | 0.919 | 5.33 |
| | **3** | **71** | **8** | **0.113** | **0.615** | **0.887** | **3.69** |
| | 5 | 60 | 8 | 0.133 | 0.615 | 0.867 | 3.04 |
| Wi-Fi aborts / 5 min | 10 | 71 | 8 | 0.113 | 0.615 | 0.887 | 3.69 |
| | **15** | **70** | **9** | **0.129** | **0.692** | **0.871** | **3.57** |
| | 20 | 71 | 8 | 0.113 | 0.615 | 0.887 | 3.69 |
| API failures / 5 min | 1 | 72 | 9 | 0.125 | 0.692 | 0.875 | 3.69 |
| | **2** | **71** | **8** | **0.113** | **0.615** | **0.887** | **3.69** |
| queue growth / 10 min | 2 | 75 | 8 | 0.107 | 0.615 | 0.893 | 3.92 |
| | **3** | **71** | **8** | **0.113** | **0.615** | **0.887** | **3.69** |
| | 5 | 54 | 8 | 0.148 | 0.615 | 0.852 | 2.69 |

Recall is **insensitive** to the memory-rate threshold (8/13 from 1 to 6 GB/min):
the day has no other event that frees memory at more than 3 GB/min, so the
threshold is not carrying the result. Loosening the Wi-Fi threshold to 15
aborts/5 min or the API-failure threshold to 1 recovers one more episode each
(at a small precision cost). Tightening the queue-growth threshold from 3 to 5
removes 17 speeches and loses nothing - the queue-growth clause is the rate
gate's largest false-alarm source (25 of its 63 false alarms) and its cheapest
one (E06, 3.2 min of lead).

---

## 3. What each gate missed, and why

### 3.1 The rate gate missed five episodes

- **E02, E07, E12 - quota exhaustion (mcode, at 02:25, 08:30 and 14:20).**
  Two of the three are *unobservable in principle from the artefacts we kept*.
  The seats that hit the quota wrote their failure into the transcript and then
  were relaunched, overwriting the transcript. The 14:20 quota's three seats
  (`coldshelf-bakeoff-desk`, `scenebloom-eval-desk`, `thor-admit-desk`) have
  **0-byte** `.out` files: the relaunch truncated them. The only surviving trace
  of the 08:30 and 14:20 quota hits is `lease.client_gone` in the admission
  daemon's log, and the burst rule caught the 14:20 one (15.3 min early) but
  not the 08:30 one, which produced a single event and never reached two.
  The 02:25 quota produced no daemon event at all.
  **What this costs:** a gate that cannot see a quota hit cannot wake anyone for
  one. The channel has to be a *counter of provider errors*, written somewhere
  that survives the relaunch.
- **E08 - the z.ai weekly limit at 09:00.** The failure is in the ProArt
  transcript (`night-v3.out`, with the provider request id
  `202611020200016a8d780e46994bc8`, which is Beijing time and therefore 09:00
  local exactly). That is one error, and the burst rule wants two. A rule of "1
  provider failure" catches it - the sweep shows the recall going to 9/13 - but
  it also adds false alarms on a channel that is currently nearly empty.
- **E04 - the duplicate Seed-OSS download.** The director found it by hand at
  03:21 after noticing two `fetch_bf16` copies. Nothing in the stream showed it:
  the disk was not yet under pressure (disk free was not sampled at all before
  14:58), and the network abort rate at 02:25-03:00 was 26-49 an hour, below the
  day's own baseline. Two copies of a download are simply not visible in any
  channel we have. **A duplicate download needs a download ledger**, not a rate.
- **E05 - the `heavy.lock` starvation.** The orphaned `syzygy gt_batch.sh` held
  the flock for 5.4 h and starved `night-v3 run B`. There is **no channel for a
  file lock** in the change stream: nothing samples `flock`, and the queue
  counter did not move, because the lock was not the admission lock. This
  episode is unobservable by construction, and it is listed in `labels.py` with
  `observable: false`.

### 3.2 The level gate missed nine episodes, and why

Everything above, plus:

- **E01, the GPU floor block.** The level gate has no condition about the GPU's
  largest free block. The daemon's own `lease.waiting_for_gpu_memory` events
  show the floor blocking leases at 01:23:23, 01:38:59, 01:43:25 and 01:46:39
  while `gpu_free_bytes` was 0.5-5.5 GB against ~100 GB of *system* memory
  free. The rate gate caught this episode anyway, through the queue clause - the
  floor blocked the queue while memory was free, which is exactly the "queue
  growing with headroom free" signature. The level gate saw nothing, because
  nothing was low.
- **E06, the FIFO hold.** The queue grew from 0 to 25 while 64-102 GB of memory
  stayed free. Every level was healthy. Only the rate of one of them was not.
- **E11, the Wi-Fi saturation.** No level was breached. The box was at 85 GB
  available and the disk had room; the network was simply aborting 26 times in
  five minutes.

### 3.3 The instrument was the limit, twice over

- **The disk channel was 71 minutes long.** The disk-under-floor episode was
  caught 5-6 min early by both gates - but only because the board happened to
  start at 14:58, four minutes before the disk crossed 30 GB. A disk floor that
  had been crossed at 09:00 would have been invisible for the whole day. The
  box's disk was unmonitored for 15 of the 17 hours, and the director found it
  by reading `df` by hand.
- **The API-error channel was 2 records.** The seat transcripts carry no
  per-line timestamps: the errors are plain text in a file that gets rewritten.
  The one timestamp that survived was the provider's own request id, and only
  z.ai puts one in its errors. The Thor's transcripts were captured before the
  error-classification change and the Thor then stopped answering (see
  `NOTES.md`, 16:15), so the Thor contributes 0 API-error records; the ProArt
  contributes 2. **Every quota-exhaustion finding in this report therefore rests
  on one proxy channel** (`lease.client_gone`), which cannot tell a quota
  exhaustion from a network timeout from a seat that simply finished.

### 3.4 What the board's own numbers say that the gates cannot

The board already carries the box state - Thor memory, disk, leases, queue - and
the director read it by hand at 15:10. The rate gate's disk clause fired at
15:03:35, on the same board series. **The board was already the watcher's
stream**; what was missing was a thing that read it every second and said
something when the *shape* changed.

---

## 4. What this makes possible

1. **The rate gate is the one to build.** 8/13 episodes against 4/13, 71
   speeches against 184, mean lead 50 min against 33 min, 385 minutes of stall
   saved against 113. It is also the cheaper one per speech, which is the
   property the design doc cares about.
2. **The combined gate (c) is not worth building as specified.** It caught
   exactly what (b) caught and made 24 extra speeches (precision 0.084 vs
   0.113). The level clauses add cost without adding catches, because in this
   day's data every level breach was already preceded by a rate breach of the
   same quantity. If the level gate is kept at all, keep it as (a') - live seats
   only - and accept that it catches 2.
3. **Add the telemetry-dark condition.** It costs 6 speeches (71 -> 77) and
   catches nothing that was not already caught - in this day's data. It is in
   the report because it is the only condition that noticed the Thor's second
   outage, and because "the box stopped reporting" is the one failure mode a
   watcher cannot be surprised by if it does not watch its own telemetry.
4. **Two channels would have to exist for the gate to see a third of the day.**
   A **provider-error counter** written outside the seat transcript (the quota
   hits left no trace), and a **disk sampler** (71 minutes of coverage). With
   those, E02, E07, E08 and E04 are within reach; without them, a third of the
   day's interventions are simply outside the stream.
5. **The `heavy.lock` episode needs its own sensor.** A flock that is held for
   5.4 hours by an orphan is invisible to every channel in this experiment. A
   watcher that wanted it would have to sample the lock's holders.
6. **The false-alarm budget is the thing to tune, and the queue clause is where
   to tune it.** 25 of the rate gate's 63 false alarms are the queue clause;
   raising its threshold from 3 to 5 removes 17 speeches and loses no episode.
   The memory-rate threshold, by contrast, does nothing between 1 and 6 GB/min.

---

## 5. What was not verified

- **The Thor was down for the last part of the capture** (from ~15:50 on
  2026-11-01: "No route to host", then connection timeouts; still down at
  16:10). All data used here was captured before or up to that, but
  `raw/seats-thor.jsonl` predates the error-classification change, so the
  Thor's seat transcripts contribute **0** API-error records. A rerun with the
  Thor reachable would fill that channel in and would change the API-burst
  numbers in section 2.6.
- **Per-seat output age before a seat's last write is an assumption**, stated
  in 1.2: the seat is taken to have been producing output until its last write.
  This under-reports stalls and therefore under-counts catches.
- **The queue-growth headroom threshold (50 GB), the API-burst threshold (2) and
  the telemetry-dark threshold (120 s) were set by hand**, not derived from the
  day's distributions the way the memory-rate threshold was. The sweep in 2.6
  shows the first two are near a plateau; the third was not swept at all.
- **The `lease.client_gone` proxy is not a provider error.** It fires when an
  API client disappears from the admission daemon, which is what a quota
  exhaustion looks like, and also what a seat that finished normally looks
  like. Its false-alarm contribution is inside the rate gate's 63.
- **The lab-motion seat's own NOTES.md is stamped "AKDT"** although the box was
  on AKST by then, so its notes are up to an hour off the wall clock. The
  incident doc's "10:40" and the daemon's 10:28:50 memory decline disagree by
  about eleven minutes; the daemon and the journal (both UTC) were used for
  timing, and the incident doc was quoted only for what it says.
- **One day's data, one box.** 13 episodes is a small labelled set; the
  precision numbers have wide error bars and the recall numbers move by one
  episode when a threshold moves by one.
- **The 15:50 outage is not in the label set**, because it had not been written
  up as a director intervention when the capture ended. It is scored as a
  mechanism (the telemetry-dark condition firing) and not as an episode.

---

## 6. Reproducing it

```
python3 scripts/capture.py          # raw/ : every source, copied
python3 scripts/reconstruct.py      # data/stream.jsonl, data/stream-meta.json
python3 scripts/gates.py            # data/events.json
python3 scripts/score.py --sweep    # RESULT.json
```

Pure Python, standard library only. `scripts/README.md` has the details, the
run time and what each file needs. `NOTES.md` is the trail, including the two
bugs found while measuring (a trailing-window rate computed over the wrong
samples, and the missing debounce) and the Thor's disappearance at 15:50.

Related: `projects/builder-ide/docs/design/screen-watcher.md` (the design this
is the first experiment of), `docs/lab/incident-2026-11-01-jax-hang.md` (E09),
`~/lm-ops/TEAM.md` and the Thor's `~/last-mile-ops.md` (the labels).
