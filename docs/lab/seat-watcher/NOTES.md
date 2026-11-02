# NOTES — seat-watcher experiment (2026-11-01)

Working directory: `/home/proart/lm-wt/seat-watcher`. Read-only everywhere else.
Rules: `/home/proart/lm-wt/DOC-RULES.md`. Brief: `BRIEF.md` (design: `projects/builder-ide/docs/design/screen-watcher.md`).

---

## 2026-11-01 15:36 — step 0: read the brief, the design, the doc rules

Read `BRIEF.md`, `DOC-RULES.md`, `docs/design/screen-watcher.md`, `docs/design/watching-teachers.md`.
No addendum or CONTINUE note exists: `BRIEF.md` is 36 lines and is the whole of it.
`seat-watcher/` contained only `BRIEF.md`; it is **not** a git repo and neither is `~/lm-wt`.
(So DOC-RULES rule 1's "commit" cannot be honoured here — no repo, and I may not create one
outside this directory. Trail is kept in this file instead. Flagged in the final report.)

## 2026-11-01 15:38 — step 1: where the data actually lives

The brief's pointers, checked one by one:

| source | path | found? | what it gives |
|---|---|---|---|
| interventions (ProArt) | `~/lm-ops/TEAM.md` | yes | 192 lines; timestamped director log |
| interventions (Thor) | `ssh thor-lan cat ~/last-mile-ops.md` | yes | 386 lines; the Thor's own log |
| seat outputs (ProArt) | `~/lm-ops/wt/*.out` | yes | 41 files |
| seat outputs (Thor) | `~/lm-wt/*.out` | yes | ~90 files |
| board snapshots | `~/lm-ops/board-history/` | yes | **43 files, 14:58:57 → 15:40:15 only** |
| thor-admit daemon log | `~/lm-tools/thor-admit-daemon.log` (Thor) | yes | 1.64 MB, from 2026-11-01 00:46 local |
| thor-admit daemon log | `~/.local/state/thor-admit/daemon.log` (Thor) | yes | 2.41 MB, from 2026-10-31 21:19 local |
| Wi-Fi events | `journalctl -b <boot-id>` | yes | on the **Thor**, boot `ea0658fc…` (the one that hung) + the boot after it |

**The two boxes.** ProArt = the seat host (15 GB RAM, 809 GB disk free). Thor = the GPU box
(122 GB RAM unified, 936 GB disk). So *memory-under-floor* and *disk-under-floor* are Thor
events, and the box-state channel is the Thor's. ProArt has no GPU and no Thor-scale memory.

**Clocks.** The Thor daemon logs ISO timestamps with a `Z` suffix but they are **UTC**
(verified: last log line `2026-11-02T00:43:08Z` against `date -u` = `2026-11-02T00:43:13`,
5 s apart). Both boxes are on `America/Anchorage`: AKDT (UTC-8) until 2026-11-01 02:00 local,
AKST (UTC-9) after. Everything in the scripts is converted with `zoneinfo`.

## 2026-11-01 15:44 — step 2: the labels (what the director did)

Read `TEAM.md` and `last-mile-ops.md` end to end. `last-mile-ops.md` has one section per
entry; the entries from `00:46` to `06:34` are undated but are Nov 1 (they continue the
2026-10-31 section and the next line is stamped `2026-11-01 07:57`).

Seven kinds of director action are visible, matching the brief's list:

1. **quota exhausted** — mcode Token Plan `2056` at ~02:25, ~08:30, ~14:20 (TEAM.md);
   z.ai weekly limit `1310` at 09:00 (TEAM.md 09:30 section; `last-mile-ops.md` 09:05).
2. **hung seat** — TEAM.md 02:48 (killed hung zcode seats; coldshelf-bakeoff ETIMEDOUT
   since 01:28) and 11:47 (pi seats stalled since the Thor hang).
3. **JAX runaway and hang** — `docs/lab/incident-2026-11-01-jax-hang.md`, TEAM.md 11:04.
4. **lock starvation** — `last-mile-ops.md` 03:53: an orphaned `syzygy gt_batch.sh` held
   `heavy.lock` for 5.4 h and starved `night-v3 run B`.
5. **GPU-floor block** — `last-mile-ops.md` 04:11: the daemon's 2 GiB lfb floor had blocked
   21 requests for over an hour with ~100 GB free; fix = restart with `--gpu-floor 0`.
6. **disk under the floor** — TEAM.md 15:10 (DISK 27 GB) and 15:22 (dedupe freed 77 GB).
7. **duplicate download** — TEAM.md 03:21: two `fetch_bf16` copies running at once.
8. **API timeouts from Wi-Fi saturation** — TEAM.md 13:07 / 13:17 / 13:35.

**How the labels were made exact (not just read off):**
- The Thor daemon log carries `lease.waiting_for_gpu_memory` (01:23:23, 01:38:59, 01:43:25,
  01:46:39) — the GPU-floor block, with `gpu_floor_bytes: 2147483648` and free blocks of
  0.5–3.5 GB against ~100 GB of system memory free. The director's fix (`--gpu-floor 0`)
  shows up as `daemon.started` at 04:12:10 with `gpu_floor_bytes: 0`. **Corroborated.**
- Seat `.out` files that end in a provider failure give the **exact minute** of the failure,
  because the runner rewrites the file with the failure and `EXIT 4`:
  `seed-oss-fp4.out` 02:26 (mcode quota), `cad-bakeoff.out` 08:31 and `judge-prompt-fix.out`
  08:34 (mcode quota), `warp-infinigen.out` 13:08 and `thor-admit.out` 13:10 (mcode
  "Request timed out"), `physag-lite.out` 13:08 (z.ai connect timeout), `coldshelf-bakeoff.out`
  and `scenebloom-eval.out` 13:15 (mcode timeout). All land on the TEAM.md times.
- The z.ai weekly-limit error carries a provider request id `20261102020001…`; z.ai ids are
  Beijing time (UTC+8), so `2026-11-01 18:00:01Z` = **09:00 local** — the exact moment the
  z.ai seats emptied. (Checked against the `week-v3` ProArt seat, whose `.out` mtime is 09:00.)
- The Wi-Fi class: the Thor journal has **726** `_cmd_abort_notify abort=1` lines in the
  pre-hang boot and **705** in the boot after it. Per hour: baseline 13–55, then
  **278/h at 12:00, 169/h at 13:00, 137/h at 14:00**. That is the saturation burst, and it
  starts at 12:00 — an hour before the 13:07 seat timeouts.

**Not verified / open:** `lab-motion/NOTES.md` stamps its own entries "AKDT" but the box was on
AKST by then, so the seat's notes are up to an hour off the wall clock. I use the daemon and
journal (both UTC) for timing and quote the seat's notes only for what they say, not when.

## 2026-11-01 15:50 — step 3: the change stream, and what it cannot see

Fields the brief asks for, and where each one actually comes from:

| field | source | coverage | resolution |
|---|---|---|---|
| per-seat output age | `.out` mtime (+ board's own `out age` column) | whole day (exact from each seat's last write) | 1 s by construction |
| per-seat last commit age | `git log` in each seat's worktree | whole day, exact | 1 s by construction |
| box free memory | Thor daemon `mem_available_bytes` | 2026-10-31 21:19 → 2026-11-01 15:40 | ~9 s samples, held |
| box memory rate | derivative of the above over a trailing window | same | per tick |
| queue length | Thor daemon `waiting` | same | ~9 s |
| disk free | board-history "Thor disk: NG free" | **14:58:57 → 15:40:15 only** | ~42 s |
| disk rate | derivative | same | per tick |
| API error lines | `.out` provider failures + journal Wi-Fi aborts | whole day | per minute |

**The reconstruction was validated against the board's own numbers**: the board's `out age`
column equals `now − .out mtime` for every seat in every one of the 43 snapshots
(lab-motion-desk 259 min at 15:26 vs mtime 11:07; warp-infinigen-desk 137 min vs 13:09;
agent-world-desk 1 min vs a file still being written). The board is the ground truth and my
reconstruction reproduces it.

**The blind spots (this is the finding, not a footnote):**
- **Disk free exists only for the last 40 minutes.** `board.sh` only started writing snapshots
  at 14:58:57. There is no other disk sampler on either box (`archive.log` and `to-ext.log`
  are empty of `df`; no crontab). So the disk clauses of both gates can only be evaluated
  between 14:58 and 15:40 — which happens to contain the one disk incident, but by luck.
- **Per-seat output age before a seat's last write is not recoverable.** The `.out` mtime is
  the last write; a seat that stalled at 10:00 and wrote once at 12:00 looks identical to one
  that wrote continuously. I therefore treat a seat as *producing output* until its last write
  and flag it as an assumption, rather than inventing silence.
- **The daemon went silent with the box.** Its last sample before the hang is the hang: memory
  reaches ~0 GB at 10:36:23 and the box dies at 10:49:53. A gate that needs the box to be
  alive to read it cannot report the box's own death.

Next: write `scripts/` (capture → reconstruct → gates → score), then the report.

## 2026-11-01 15:55 — step 4: the labels are written down (scripts/labels.py)

13 episodes, 8 kinds, each with onset / the director's first action / the last action,
and the source line for every one. Two rules I had to fix while writing them:

- **The Alaska fold bites twice.** The local hour 01:00-02:00 happened twice on
  2026-11-01. E03's onset is stamped 01:28 and the gate event that matches it is
  stamped 01:23:13 - which *looks* earlier but is 55 min later in absolute time
  (09:28 UTC vs 10:23 UTC). Everything is compared in epoch seconds; the local
  clock is only for display. The two onsets that fall in the repeated hour carry
  an explicit UTC instant in labels.py.
- **The onset is not the time the director wrote it down.** E06 (the FIFO hold):
  TEAM.md stamps it 06:35, but the daemon's own `waiting` count starts growing at
  06:21:56 with 64-102 GB of memory free. 06:21 is the observable onset and it is
  what the gate is scored against. Same for E11: the Wi-Fi saturation is visible
  in the journal's 5-minute rolling abort count from 11:49 (26, against a median
  of 8), not from 12:00.

## 2026-11-01 16:05 — step 5: the stream, and the gate

`scripts/reconstruct.py` -> `data/stream.jsonl` (10,721 change records).
`scripts/gates.py` -> `data/events.json`.
`scripts/score.py` -> `RESULT.json`.

**The reconstruction is exact against the board's own numbers:** 533 comparisons
of (snapshot time - .out mtime) against the board's `out age (min)` column, 76
rows where the seat was still being written (consistent, age 0), **0 mismatches**.

Three matching rules are reported, because they answer different questions:
- `time_only` - the brief's literal rule: any speech within +/-10 min of the
  help point. It flatters every gate, because a stale-seat alarm that lands two
  minutes before a quota exhaustion counts as catching the quota.
- `kind_aware` - the same window, but the speech must be about the right kind of
  problem (`labels.SIGNALS`).
- `episode` - kind-aware, with the window running from the problem's onset to the
  director's action. This is the rule that answers the question the experiment
  asks; a gate that speaks 2 h 43 m before the director acts is a better catch,
  not a worse one, and +/-10 min cannot see that.

Two gates changed while I measured them:
- The trailing-window rate was computed over the newest sample pair instead of
  over the window (my bug): it produced 645 "memory falling fast" speeches a day.
  Fixed: 13.
- `MemAvailable` reads **bimodally** after a restart (127 GB / 17 GB alternating
  for minutes), so every condition now has to hold for 30 s before the gate
  speaks. Without that hold the rate gate chatters.

## 2026-11-01 16:15 — step 6: the Thor went away again

At ~15:50 the Thor stopped answering: "No route to host", then "Connection timed
out", for 20+ minutes. Same signature as the 10:46 hang. The raw capture from
15:48 is complete, so the experiment is unaffected, but `raw/seats-thor.jsonl` and
`raw/git-commits-thor.jsonl` were captured **before** the error-classification
change, so the Thor's seat transcripts contribute 0 API-error records. The ProArt
transcripts contribute 2. A retry loop (`scripts/retry-thor-capture.sh`) is
running; if the Thor comes back it will refresh those two files and the
`api_error_burst` channel will fill in.

This is also the day's own theme, so it is evidence rather than noise: the
14:20 mcode quota and the 08:30 one left **no transcript trace** (the seat files
were overwritten by the relaunch), and the only surviving trace of both is
`lease.client_gone` in the admission daemon's log. That channel is now in the
stream as `client_lost`, and it is the only thing that catches the 14:20 quota.

## 2026-11-01 16:20 — step 7: the Thor went down again, and the gate noticed

At ~15:50 the Thor stopped answering for good. The daemon's last sample was
15:47:59; `board.sh` fills its "## The box" section over ssh, so the **16:04
board snapshot has an empty box section** - the board itself noticed 13 minutes
after the box went.

That produced a gate condition that was not in the brief and that I would not
have written without the accident: **the box has not reported for 2 minutes**.
It is the time-first idea applied to the watcher itself - the rate of change
went to zero because there was nothing left to change. Added as the variant
**b+** (the brief's gates are left exactly as specified and scored separately).

- It fires at **15:50:38**, 2 min 39 s after the last sample, 13 min before the
  board noticed, and it is the only condition that fired at all for that outage.
- It fires four times during the 10:46 hang (10:39:57, 10:43:20, 10:51:51,
  10:58:17): the daemon's sampling went sparse (203 s and 230 s gaps) before the
  box died outright at 10:49:53.

It does **not** change the scored result for E09 - the memory-rate condition
spoke earlier (10:33:52) and takes the credit - and it costs 6 speeches
(71 -> 77). It is reported because it is the one failure mode a watcher cannot
be surprised by if it does not watch its own telemetry.

## 2026-11-01 16:25 — step 8: the final numbers

Window widened to 00:00:00-16:05:00 (17.08 h) so that everything the capture
holds is inside it, including the 15:50 outage.

| gate | speeches | caught | recall | precision | FPR | FA/h | mean lead | stall saved |
|---|---|---|---|---|---|---|---|---|
| (a) level | 184 | 4/13 | 0.308 | 0.022 | 0.978 | 10.54 | 32.6 min | 113 min |
| (b) rate | 71 | **8/13** | **0.615** | **0.113** | **0.887** | **3.69** | **50.3 min** | **385 min** |
| (c) a+b | 95 | 8/13 | 0.615 | 0.084 | 0.916 | 5.09 | 50.3 min | 385 min |
| (b+) rate + telemetry-dark | 77 | 8/13 | 0.615 | 0.104 | 0.896 | 4.04 | 50.3 min | 385 min |
| (a') level, live seats only | 24 | 2/13 | 0.154 | 0.083 | 0.917 | 1.29 | 16.2 min | 15 min |

Every table in `docs/exp-seat-watcher.md` was checked against `RESULT.json`
programmatically after the last run. The report and the JSON agree.

**The answer to the brief's question.** A time-first gate catches twice as many
of the director's interventions as a level gate, with 2.6x fewer speeches and
17 minutes more lead on average, and the lead is concentrated exactly where the
level gate is blind: the JAX preallocation (30.1 min early, at a time when the
level was still 32 GB free), the Wi-Fi saturation (74.5 min early, with no
level breached at all) and the admission FIFO hold (3.2 min early, with 75 GB
free). The level gate's own false alarms are the reason: 160 of its 181 seat
alarms are on seats that had already exited.

**What I could not do.** The Thor is down, so its seat transcripts contribute 0
API-error records and the API-error channel rests on one proxy. The retry loop
(`scripts/retry-thor-capture.sh`) is still waiting; if the Thor comes back it
refreshes `raw/seats-thor.jsonl` and `raw/git-commits-thor.jsonl` and the
pipeline can be re-run.
