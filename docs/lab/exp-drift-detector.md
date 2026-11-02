# exp-drift-detector — the drift detector on the world ledger, measured

**What was asked.** Build §3.4's drift detector and its auto-pause signal,
offline, on the world ledger that already exists: the six rate signals, each
a rate gate with hysteresis, calibrated on a held-out split, with precision,
recall and an alarm rate, compared against a level gate held to the bar
`docs/lab/exp-syzygy-keyframes.md` set.

**What was built.** `core/drift/` (the six signals, the gate, the pause
ladder) and `tools/drift/` (the extraction, the calibration, the pause list).
Forty-six tests. The ledger's own numbers are in the table below and the
artefacts that produced them are committed beside this note.

**The short version.** Four of the six signals are computable from the world
ledger and two are not. The rate gate beats the level gate on the signal
where the comparison is cleanest by **7× on alarm time** and **8× on false
alarms**; on the combined detector it detects **6 of the 6** labelled drift
episodes in the holdout half, where the level gate detects 4 of 6, at
**1.63 alarms per hour of world**. The negative control fails on one third of
its windows, and that failure is a gap in the ledger, not in the detector.

---

## 1. The mechanism

The design is `docs/design/vibecode-in-world.md` §3.4 (the six signals) and
§3.5 (the three levels of pause). This note does not restate them; it says
what was built on them and what the world's own ledger says about it.

**The gate is one quantity, two ways of thresholding it.** Every signal
produces a *badness* — a number where higher is worse — and the detector
compares it to a threshold in one of two ways:

* a **level gate** fires when the badness is bad now;
* a **rate gate** fires when the badness *rose*.

The rate is **one-sided**: only a rise is drift, a fall is recovery. This is
the same shape as the syzygy gate, which fires on ``conf[i-1] - conf[i] >
tau`` — the reader *losing* the scene — and not on the reader regaining it
(`~/lm-wt/syzygy-keyframes/harness/gates_conf.py`).

The gate is `core/hysteresis`'s band-and-dwell gate, reused: split
thresholds, a minimum dwell, the caller's clock. One addition was needed and
it is in `core/hysteresis/gate.py` now: `reset_pending()`, so that a window
with **no reading** drops a pending transition instead of carrying it across
the gap. A gap in the evidence is not evidence of persistence.

**The pause ladder** is §3.5's, wired to the signals: one agent drifting is a
**soft** pause (that agent waits on its own branch); the world's own signal
drifting, or two agents at once, is a **tier** pause (the world's work is
demoted from `live` to `preparation`); a rule violation is a **hard** pause
(the doors close).

**The hard signal is kept apart from the scored ones.** §3.4 is explicit that
a promise to a person is not a rate and that averaging it into a score would
be worse than useless. So the violation path has no threshold, no band and
no dwell: one occurrence escalates immediately. The path is wired and tested
even though the ledger carries no violations yet (§3).

## 2. Which of the six the ledger can carry

| signal | scope | computable | what it is computed from |
|---|---|---|---|
| stall time rising | per agent | **yes** | the gap between consecutive `tile.played` events |
| success rate falling | per agent | **yes** | the outcome on `tile.played` |
| error bursts | the world | **yes** | `judge.verdict` rows flagged `refused: true` |
| rule violations | per agent | **no** | nothing writes a violation to the ledger |
| spend per productive decision | per agent | **partly** | the ledger's own cost fields |
| build drift | a branch | **no** | the ledger has no branch head and no constraint set |

### Two corrections to §3.4, and one substitution

**The outcome is on the play, not on the verdict.** §3.4 reads the success
signal from "`judge.verdict` rows with a good outcome". In the world's
ledger a verdict carries the *decision* — the agent it was asked about
(`judgments[].qid`) and the confidence — and **no outcome**. The outcome is on
`tile.played` (`outcome.result`), attributed per agent by `context.bot`. The
signal is built from the plays, and the per-actor attribution comes from the
payload, not from the `actor` column: that column names the *seat* that
wrote the row (the reflex, the judge), not the agent the row is about.

**Two of the three error events are canon-side.** §3.4 counts
"`constraint.failed`, `wo.failed`, and events whose payload is flagged
`refused: true`". The first two are `core/fold.py`'s canon event types; the
world ledger has neither. The third — `refused: true` — is exactly the
world's own refusal event, and that half of the definition holds verbatim.

**The spend is the ledger's, not thor-admit's.** §3.4 reads the spend from
"thor-admit ledger by label ÷ `tile.played`". thor-admit's ledger books the
world's hours under **no world label** — the world's services run outside the
lease system, so there is no by-label spend for them to divide. The spend is
in the ledger itself (`cost.gpu_minutes`, `cost.hosted_cents`), charged to
the agent the verdict was about. `hosted_cents` is **0 on every row of this
world** (the world's decision model is local), so the hosted half contributes
nothing here and the two halves are not commensurable in general; GPU minutes
are used.

**The formula, not the name.** §3.4's signal is named "spend per productive
decision" and its formula divides by every `tile.played`. The formula is
followed — the cost of a decision against the agent's own reference cost of a
decision — because dividing by the **wins** instead would be the win rate
again under another name, and §3.4 already has a signal for the win rate.

**The two that cannot be carried.** Rule violations are enforced in the bots'
own code (`agent-world/bots/src/humanity.js`, `bots/test/no-grief.test.js`)
and never reach the ledger; build drift is a canon-side property
(`core/recipe/store.py` holds the heads, `core/recipe/constraints.py` the
ratified scope) and the world does not commit to the canon yet. Both seams
are wired — the detector reads `drift.rule_violation` and `drift.build_drift`
events — so the day the world writes one, the path is live and tested. The
hard path is tested with a fixture, not with a claim.

## 3. The data

**The ledger.** `~/lm-wt/agent-world/runtime/world-ledger.sqlite3`, opened
read-only, folded into five-minute windows (§6.2 of the design note asks for
a five-minute window). The committed dataset is a snapshot:

| | |
|---|---|
| ledger sha256 | `6a6af17b6ae603b7…` (the full hash is in `drift-dataset/dataset.json`) |
| span | 2026-11-01T05:40:00Z .. 2026-11-02T04:20:00Z (**22.67 h**) |
| windows | 272 |
| agents | Kite, Pebble, Sprout, Timber |
| events | `tile.played`, `judge.verdict`, `tile.authored`, `tile.retired` |

**The ground truth comes from instruments outside the ledger.** If the labels
were cut from the ledger, the measurement would be circular: the detector
would be scored against the rows it reads. So the labels come from three
places that are not the ledger:

| class | source | what it is |
|---|---|---|
| `client_failure` | `bots.jsonl` | the world's clients reporting `reflex_unreachable`, `play_not_recorded`, `kicked` and their own errors — 117 events |
| `write_path_failure` | `bots.jsonl` | refused decisions whose cause is a failure: `IntegrityError: UNIQUE constraint failed: audit.id`, `ProgrammingError`, "the reflex did not answer in time" — 8,179 events |
| `incident_hang` | `docs/lab/incident-2026-11-01-jax-hang.md` | 2026-11-01T19:40Z–20:06Z |
| `incident_wedge` | `agent-world/docs/playtest-2026-11-01-reward.md` | 17:20Z–21:55Z |
| `incident_judge` | the same note | 20:06Z–21:45Z |
| `incident_judge_startup` | the same note | 06:25Z–09:10Z |
| `designed_yield` | `bots.jsonl` | **the negative control** — 2,217 refusals because the box was busy or another seat held the lease. The world yielding the box is the world behaving correctly, and a detector that alarms on it is wrong. |

Two of those windows were derived rather than copied, and the derivation is
worth stating because the notes use local time. The box's timezone is AKST
(UTC−9): `journalctl --list-boots` prints AKST, and the incident note's boot
id (`ea0658fc`) is the boot that ended at 10:49:53 AKST = **19:49:53Z**. The
note's "~10:45" and "~10:59" are therefore 19:45Z and 19:59Z, and the
playtest note's "~20:00 UTC; the world came back at 20:06" is the same event
in UTC from the other note. The world's ledger has a twenty-five minute hole
over exactly that stretch, which is the independent check.

**Nine labelled drift episodes**, 115 positive windows: three in the first
half of the run and six in the second.

**The box state when these numbers were taken.** The Thor, shared: the world
was *running* the whole time (this is a live ledger, read-only), the seat
that took the measurement was on the ProArt over ssh, and the numbers are
counts of what the world did, so they do not move with the load. The
measurements were CPU-only and small — the whole extraction is 1.8 s and the
whole calibration 7 s — so no lease was taken and no GPU was touched.

## 4. The protocol

1. **Split.** The run is cut in half by time: 05:40Z–16:55Z is the
   **calibration** half (11.25 h), 16:55Z–04:20Z is the **holdout** half
   (11.42 h). Thresholds *and baselines* are chosen on the calibration half.
2. **Leave-one-out.** The drift events on this world are *clustered* — a box
   reboot takes out the hang, the wedge and the judge's absence together —
   so a single time split leaves the calibration half with three episodes and
   cannot calibrate a threshold on its own. Each labelled episode is
   therefore also held out in turn: the threshold is chosen on the other
   episodes and the held-out one is scored. That is the generalisation
   estimate, and it has one row per episode.
3. **The pause budget.** The world may be in alarm for at most **a tenth of
   its windows** (27 of 272) without anything being wrong. This is what
   rules out a gate that is permanently on: such a gate is not worse on
   recall, it is worse on *time*, and time is what a pause costs.
4. **The metrics.** A detector is a *state*, so the unit is the **alarm
   episode** — a contiguous run of windows in alarm — not the raw count of
   transitions. The numbers are: the **recall** over labelled drift
   episodes; the **false alarm episodes**; the **false alarm windows** (the
   alarm windows that are not in a labelled episode); and the **onset
   latency** in windows.

**The baselines are frozen.** Every signal's baseline is the agent's own
reference over the reference period, and it does not follow the run: a
baseline that follows the drift becomes the new normal and the drift stops
being visible. In the calibration the reference is the calibration half.

## 5. The numbers

### The six signals, at the shipped thresholds, leave-one-episode-out

Mean over the nine folds. *fw* is the mean false-alarm windows, *aw* the mean
alarm windows.

| signal | rate gate | level gate | hybrid gate |
|---|---|---|---|
| **stall** | 2/9 episodes, fw 12.1, aw 48.2 | 2/9, fw 44.8, aw 95.3 | 1/9, fw 10.7, aw 45.4 |
| **success** | 2/9, fw 18.3, aw 20.9 | 0/9, fw 15.6, aw 83.2 | 2/9, fw 21.1, aw 64.9 |
| **errors** | 2/9, fw 3.3, aw **11.3** | 3/9, fw 28.2, aw **78.0** | 2/9, fw 24.8, aw 75.4 |
| **spend** | 3/9, fw 17.0, aw 30.1 | 3/9, fw 14.8, aw 21.0 | 2/9, fw 22.1, aw 45.6 |

### The combined detector

| | rate (shipped) | level | hybrid |
|---|---|---|---|
| calibration half, episodes detected | 2 / 3 | 1 / 3 | 2 / 3 |
| **holdout half, episodes detected** | **6 / 6** | 4 / 6 | 6 / 6 |
| holdout precision (windows) | 0.625 | 1.000 | 0.750 |
| **alarms per hour of world** | **1.63** | 0.71 | 1.63 |
| holdout alarms per hour | 2.37 | 1.05 | 2.45 |
| alarm windows per hour | 5.16 | 6.93 | 7.81 |
| holdout false-alarm windows | 28 | 35 | 45 |
| median onset latency | **−1 window** | −1 window | −1 window |

A **negative** onset latency is the alarm firing *before* the labelled episode:
the drift is visible in the ledger before the world's clients report it.

### Against the syzygy bar

The bar is "at matched recall the rate gate beats the level gate" — on true
cuts it cut the false alarms from 19.4 % to 6.9 % to 0 %, and at a matched
recall of 0.936 it spent 25 fires where the level gate spent 36.

The cleanest place to make that comparison here is the **world-scope** signal,
the refusal rate, because its ground truth is the sharpest (a decision model
that stops answering is unambiguous):

| at the shipped thresholds | rate gate | level gate |
|---|---|---|
| episodes detected (leave-one-out) | 2 / 9 | 3 / 9 |
| **alarm windows** | **11.3** | **78.0** |
| **false-alarm windows** | **3.3** | **28.2** |

**At the same recall the rate gate alarms for 11 windows where the level gate
alarms for 78 — 7× less alarm time — and its false alarms are a third of the
level gate's.** The reason is structural: the refusal rate is a *plateau*
(0 → 1 → 0), so a level gate latches on for the whole plateau and a rate gate
fires at the edges. The same shape holds on the stall signal: 48.2 alarm
windows against 95.3, and 12.1 false-alarm windows against 44.8, at the same
2/9.

**The bar is not met everywhere, and here is where it fails.** On the
**success** signal the level gate wins: 0/9 episodes against the rate gate's
2/9 — not because the level gate is better, but because the rate gate's
*input* is noisy. The success signal is a rate over a sample, and the gate
differences it, so differencing a noisy rate gives a noisy rate of change.
That is not a reason to prefer the level gate; it is a reason to widen the
sample before differencing it. The lab measured it: at five scored plays per
window the success signal's rate gate spent **150** false-alarm windows over
the run; at twenty it spent **18**, at the cost of detecting fewer episodes.
The shipped default is twenty.

### The negative control

**5 of the 12 windows in which the world *correctly* yielded the box were
alarmed on** (0.417). The mechanism is plain and it is not the detector's
fault: when the world yields because the box is busy, **it stops playing**,
and a world that stops playing is exactly what the stall signal is for. The
ledger records "the agent did not play" and not "the agent declined to play
because the box was busy", so the two are the same row.

This is the most actionable finding in the note: **the ledger needs one more
event.** A `drift.yield` event — the world's own admission rule refusing work
— would separate "could not act" from "chose not to act", and it is a two-line
change where the world writes its refusals. Until then the stall signal
cannot be trusted on a busy box, and the alarm rate above should be read with
that in mind.

### The auto-pause, concretely

The shipped rate detector raises **37 alarms over 22.67 hours, 1.63 per hour
of world** (`drift-dataset/pauses.json` has all 37 with their reasons). The
five real events in the run are all caught, at the right time:

| when | what the detector said | what it was |
|---|---|---|
| 06:20Z | tier — the decision model's refusal rate moved to 1.000 | the judge's first absence (the world ran on priors) |
| 17:55Z | tier — the refusal rate moved to 1.000 | the judge unreachable after the box came back |
| 19:40Z | tier — Pebble's worst gap jumped to 15× its median, Sprout's to 23× | **the box hang** (`incident-2026-11-01-jax-hang.md`) |
| 00:50Z | tier — Kite's worst gap jumped to **193×** its median | the world's write path broke (`audit.id` collisions) |
| 02:40Z | tier — the refusal rate moved to 1.000 | the judge refusing again |

So the mechanism works: the box went dark and the detector noticed in the
same five-minute window, because a stalled agent is a stall whether it is a
bug or a power cut.

## 6. The chosen defaults

`core/drift/config.py` holds them all; these are the ones the calibration
chose.

| parameter | value | why |
|---|---|---|
| `bucket_seconds` | 300 | §6.2 of the design note asks for a five-minute window |
| `stall_lookback_buckets` | 3 | 15 minutes of trailing gaps; 6 and 12 were measured and neither was better |
| `signal_lookback_buckets` | 3 | the success and spend signals are rates over a sample |
| `min_scored_plays` | 20 | five plays is noise, and differencing noise is noisier: 150 false-alarm windows at 5, 18 at 20 |
| `min_verdicts` | 5 | the refusal rate over five verdicts is stable |
| `stall` gate | enter 10.0, exit 6.0 | the trailing worst gap, in multiples of the agent's own median gap |
| `success` gate | enter 0.2, exit 0.12 | the fall in the win rate, against the agent's own reference |
| `errors` gate | enter 0.8, exit 0.48 | the rise in the refusal rate |
| `spend` gate | enter 0.5, exit 0.3 | the rise in the cost per decision, in multiples of the agent's own reference |
| `dwell_down` | 600 s | two windows: the band is what stops the flicker, the dwell is what stops a one-window spike |
| `tier_agents` | 2 | two agents at once is the world's problem, not one agent's |

The exit threshold is 0.6 × the enter threshold in every case: the band.

## 7. What is not verified, and what remains uncalibrated

* **Two of the six signals are not calibrated at all**, because the ledger
  cannot carry them. The violation path is wired and tested but has never
  fired on the world's own data; the build-drift path has no data at all.
* **The negative control fails** (0.417), and the cause is the ledger's, not
  the detector's (§5). Until the world writes its yields, the stall signal
  cannot be trusted on a busy box.
* **One day of world.** The ledger is 22.67 hours long and the drift events
  cluster in it, so the nine episodes are not nine independent samples. The
  leave-one-out folds are correlated with each other; the intervals are not
  stated because they would be misleading.
* **The spend signal is nearly redundant with the success signal.** It fires
  on the same episodes (3/9 for both at their shipped thresholds) because the
  cost per decision is flat and the *wins* are what move. It is kept because
  §3.4 asks for it and because a world with a hosted decision model would
  make it independent.
* **The `hybrid` gate did not earn its place.** It was built for the case
  where a drift is sustained and a rate gate forgets it, and on this ledger
  it did not beat the rate gate at the same recall (6/6 episodes but 122
  alarm windows against the rate gate's 88). It is kept in the code and
  documented, and it is the right mode for a signal that settles rather than
  wobbles.
* **The auto-pause is not wired to `thor-admit`.** The tier pause is
  computed and named; the demotion itself is not implemented, because doing
  it means touching the admission daemon and this build is the detector and
  its measurement.
* **The success signal's recall is the weakest** (2/9 leave-one-out). Its
  ground truth — the wedge — is a physical diagnosis from a probe bot, and
  the world's win rate only partly follows it: the scout's survey skill
  cannot produce a measurable win by design, so its win rate is ~0
  throughout and carries no signal at all.

## 8. Reproducing it

On the Thor, from the repo root:

```bash
# 1. the dataset: the live ledger, folded, plus the labels from the
#    instruments outside it. Writes three JSON files.
python3 tools/drift/extract.py --out docs/lab/drift-dataset

# 2. the calibration: the sweep, the leave-one-out, the time split, the
#    level-gate comparison. About seven seconds.
python3 tools/drift/calibrate.py \
    --dataset docs/lab/drift-dataset/dataset.json \
    --labels docs/lab/drift-dataset/labels.json \
    --out docs/lab/drift-dataset/calibration.json

# 3. the pause list: every alarm the shipped detector raises, with the
#    reason a human would read.
python3 tools/drift/pauses.py

# 4. the tests
~/lm-wt/core-api/.venv/bin/python -m pytest tests/drift -q
```

Step 1 reads a ledger that is still being written, so re-running it against
the live world gives a different (slightly longer) dataset; the committed one
is the snapshot whose hash is in §3. The other three steps are deterministic
against the committed dataset.

The knobs the calibration exposes, for anyone who wants to see the
sensitivity rather than the answer: `--pause-budget` (the tenth of the
world's windows), `--min-scored-plays`, `--stall-lookback`,
`--signal-lookback`, `--dwell-down`, `--tolerance`.

## 9. Files

| file | what it is |
|---|---|
| `core/drift/` | the detector: `signals.py`, `gate.py`, `detect.py`, `ledger.py`, `config.py` |
| `core/drift/README.md` | how to use it |
| `tools/drift/extract.py` | the ledger → the dataset, and the labels from the instruments |
| `tools/drift/calibrate.py` | the sweep, the holdout, the comparison |
| `tools/drift/pauses.py` | the alarm list |
| `tests/drift/` | 46 tests |
| `docs/lab/drift-dataset/` | the dataset, the labels, the calibration report, the pause list |
