# exp-drift-pause — the yield event, and the pause wired to action

**What was asked.** Two things the drift-detector build
(`exp-drift-detector.md`) left: close the ledger gap — the world writes
no `drift.yield` event, so the stall signal alarms on correct waits
(the negative control, 5 of 12) — and wire the pause ladder to action,
so a pause decision demotes the offending actor's thor-admit tier or
stops its new proposals, without ever killing a process, dry-run by
default.

**What was built.** The event, at the world's own admission seam
(`agent-world/reflex/agent_world_reflex/service.py`); the closed event
set opened for the drift group (`core/records.py`); the folding that
honours the event (`core/drift/ledger.py`); the ladder with a hand on
it (`core/drift/pause.py`, `tools/drift/enforce.py`). Twenty-four new
tests here and thirteen world-side checks in the agent-world repo.

**The short version.** The negative control goes from **5 of 12 to 3
of 12** on the same thresholds, with the holdout **unchanged at 6 of 6
episodes** and its false-alarm windows unchanged at 28. The honest
split: of the twelve designed-yield windows, six sit **inside** labelled
drift episodes, where an alarm is correct; of the six pure ones, one
was alarmed before and one is alarmed after — and that one is the
errors signal's onset catch of the judge's first absence, an alarm to
keep. The stall signal no longer alarms on any wait the world chose.
The pause writes a file the world reads (a soft pause holds one bot; a
tier pause stands the world aside) and demotes thor-admit presence
entries one tier; dry-run is the default and writes nothing.

---

## 1. The mechanism

**The event.** The world refuses work in one place: the reflex's
`_answer`, where `may_act()` applies the box's own rule ("keep 25 GB
free") to every batch. That refusal said `yielded: <why>` to the bots
and **nothing to the ledger** — so "the agent could not act" and "the
agent chose not to act" were the same silence, and a busy box was
indistinguishable from a stalled world. The world now writes one
`drift.yield` event per admission decision, every bot it covers in the
payload; a drift pause goes through the same door and says so in the
reason.

**The schema change.** The ledger's event types are a closed set
(`core/records.py`, §1.8 of core-spec). `drift.yield` joined it — and
so did `drift.rule_violation` and `drift.build_drift`, the two seams
the detector already read. **A correction, in writing:** the
drift-detector note claimed those two seams were "wired and tested, so
the day the world writes one, the path is live" (§2); the closed set
would have rejected both events — the write path was not live, and a
fixture could not see it because fixtures write through the same door.
The group is mirrored in `core/night/events.py` and
`core/recipe/events.py`, whose unions pin themselves against the
master set.

**The honouring.** The signal needs no new math; the excuse is applied
where the evidence is made, in the folding:

* a gap between two plays that has a yield point inside it —
  `(previous, at]`, the agent demonstrably tried — is **not in the
  gaps at all**;
* a window an agent spent standing aside (no plays, a yield inside)
  has its **idle excused**, not counted.

One yield is not a blanket amnesty: it excuses the gap it falls inside
and the window it falls in, and nothing else (that is tested). The
resume-gap after a busy stretch — the first play after a long yield,
whose gap spans the whole wait — was the false alarm waiting to
happen, and it is the one this kills.

**The pause.** §3.5's three levels, wired to the detector's *state*
(the alarm windows, not the fires — an alarm that holds is a pause that
holds, and a caller running every window renews the entry until the
state clears):

| level | the pause file (the world reads it) | the thor-admit door |
|---|---|---|
| soft | the named bot's decisions are refused politely; one `drift.yield` per hold | nothing — one agent is not the box's memory problem |
| tier | the whole world stands aside; every decision refused politely | the mapped labels demote one tier (live → preparation → practice → study) |
| hard | as tier, and the reason names the violation | the mapped labels also **disabled**: no new proposals |

No process is killed anywhere. The world's services stay up, keep
serving `/health` and `/skills`, and record a `drift.yield` for every
refusal — so a pause the detector ordered is itself invisible to the
stall signal, which is the point. On the thor-admit side a demotion
changes what starts **next**: running leases are untouched, and
`thor-admit reload` re-reads the presence file. Both doors are file
edits, so both are cheap to undo: an entry carries `until` (30 min by
default) and lapses on its own, and `--clear <actor>` resumes at once.

**Dry-run is the default.** `enforce.py` computes the actions and logs
every line prefixed `dry-run:`, writing nothing — not the pause file,
not the presence file, no reload. `--enforce` writes. The friction is
deliberate: an automated tier demotion is a decision a human should
watch a dry-run of first.

## 2. The data, and the circularity named

The historical ledger carries no yield events (the world began writing
them this build), so the committed snapshot is re-folded with the
stand-asides **backfilled** from the clients' own decision log
(`bots.jsonl`: 2,217 decision records refused `yielded:`/`leased:`) —
the same records the `designed_yield` labels are cut from. Two
consequences, said plainly:

* on the backfilled dataset the negative control measures the
  **plumbing** — does an honoured yield stop the alarm — not an
  independent discovery;
* the independent checks are the ones whose labels come from other
  instruments: the holdout recall and the false-alarm windows.

The comparison is cut from the **same span of world** (22.67 h, ending
2026-11-02T04:20:00Z) with the `--until` flag added for the purpose —
the ledger is live and three hours longer than build #2's snapshot.
The "before" was re-run with the new code on the old dataset first: it
reproduces build #2 exactly (same chosen thresholds, same holdout,
same 5-of-12), so the before/after below differs only in the yields.

The box state: the Thor, shared, load ~23, 89 GB available, the world
running throughout; every measurement here is CPU-only and small (the
extraction ~4 s, each calibration ~6 s, no lease taken, no GPU
touched).

## 3. The numbers

On the thresholds the sweep chose — the same ones before and after
(stall 10.0, success 0.2, errors 0.8, spend 0.5):

| | before | after |
|---|---|---|
| negative control (designed yield) | **5 of 12** alarmed | **3 of 12** |
| — pure yield windows (nothing else wrong) | 1 of 6 | 1 of 6 |
| — yield windows inside drift episodes | 4 of 6 | 2 of 6 |
| holdout episodes detected | 6 / 6 | **6 / 6** |
| holdout alarm windows | 88 | 86 |
| holdout false-alarm windows | 28 | **28** |
| stall rate gate, leave-one-out false-alarm windows | 12.1 | **10.4** |
| alarms over the run | 37 (1.63/h) | 37 (1.63/h) |

**Exactly two stall alarm windows moved, and both moves are the
mechanism working:**

* **19:40Z, the hang.** The box was full enough that the world kept
  writing yields, so the gaps the stall signal caught there were
  yield-spanned and got censored. The alarm moved to **19:45Z** — the
  silence after the box went dark carries *no yields*, because the
  reflex itself was hung and could write nothing. An unexplained
  silence is exactly what the stall signal is for. The hang episode is
  still detected (onset one window later; its label runs to 20:06Z).
* **00:50Z, the write-path break.** Kite's 193× gap was yield-spanned.
  The episode stays detected through the errors signal, which covers
  21 of its 24 windows.

**A correction, in writing, of the earlier note's mechanism story.**
The drift-detector note's §5 said the control failed because "a world
that stops playing is exactly what the stall signal is for… the ledger
records 'the agent did not play' and not 'the agent declined to
play'". The second half is right (the ledger gap was real); the first
half is **not what the shipped detector did**: at the shipped
thresholds, no pure-yield window was ever alarmed by the stall signal
— the one pure-window alarm then and now is the **errors** signal
catching the judge's first absence at 06:20Z, one window ahead of its
label, an alarm to keep. The stall-vs-yield failure was real in the
leave-one-out folds (12.1 false-alarm windows) and in the two-sided
gate the same note measured (7 of 12), and it is those numbers the fix
moves; the headline 5-of-12 was counting alarms that were mostly
correct catches in windows that happened to yield. The negative
control now reports this split itself (`calibration.json`:
`pure_yield_windows` against `yield_windows_inside_positive_episodes`).

## 4. The pause, in action

Dry-run at the hang window, on the committed after-dataset:

```
$ python3 tools/drift/enforce.py --at 2026-11-01T19:45:00Z
dry-run: 2026-11-01T19:45:00Z:
dry-run:   tier: the world's work yields — drift in the world's own work
           (2 agents at once); Pebble, Sprout hold on their own branches
dry-run:   thor-admit: demote agent-world* one tier
would write ~/lm-wt/agent-world/runtime/drift-pause.json (world=tier)
dry-run: thor-admit: no presence entry matches agent-world — nothing to
         demote (the world's work runs outside the lease system today; …)
```

Nothing was written (the pause file did not exist afterwards; the
presence file's sha256 was unchanged). An `--enforce` pass on throwaway
copies wrote the entry (`world=tier`, lapsing 30 min out), demoted a
planted `agent-world.night` presence entry **live → preparation**,
and `--clear world --enforce` resumed it. The default label map
(`world=agent-world`) matches no presence entry on this box because
the world's services run outside the lease system
(exp-drift-detector §2) — the tool says "nothing to demote" rather
than pretending, and the door opens with no code change the day the
world's work registers under `thor-admit presence add`.

One more thing the demo made plain: a window chosen as "quiet"
(12:00Z) turned out to be in **sustained alarm** — two stall gates
latched. Enforcement acts on the state as it is, false alarms
included; that is why dry-run is the default and the TTL is short.

## 5. What is not verified

* **The world has not written a `drift.yield` event yet.** The code is
  committed in the agent-world repo, but the running reflex still
  executes the pre-change code, and the runtime's copy of builder-ide
  (`~/src/builder-ide`, main) does not have the closed-set change until
  this branch merges. The events begin when both land and the reflex
  restarts; the world-side behaviour (the yield write, the pause-file
  read, all three stand-asides) is verified by
  `agent-world/tests/test_drift_yield.py` (13 checks, run with
  `AW_BUILDER_IDE` pointed at this worktree), not against the live
  world.
* **The negative control on the backfill is plumbing, not discovery**
  (§2). The first *independent* negative control will be cut from a
  ledger that wrote its own events, against labels from the clients'
  log — the same instruments, but an input the labels did not produce.
* **The thor-admit door has never fired in anger.** No presence entry
  matches the default map today; the demotion path is exercised by
  tests and by the planted-label demo, not by a real demotion of a
  real seat. A first live use should be a watched `--enforce` on one
  labelled entry.
* **The pause file has never paused the live world** — for the same
  restart reason as above.
* The box hang's one-window-later onset is measured on one hang; one
  event is an anecdote, not a latency distribution.

## 6. Reproducing it

On the Thor, from the repo root (CPU-only, seconds; no lease, no GPU):

```bash
# 1. the after-dataset: the same span as build #2's snapshot, with the
#    yields backfilled from the clients' decision log
python3 tools/drift/extract.py --out docs/lab/drift-pause-dataset \
    --yields-from-bots --until 2026-11-02T04:20:00Z

# 2. the calibration on it (the "after" column above)
python3 tools/drift/calibrate.py \
    --dataset docs/lab/drift-pause-dataset/dataset.json \
    --labels docs/lab/drift-pause-dataset/labels.json \
    --out docs/lab/drift-pause-dataset/calibration.json

# 3. the "before": the same command against docs/lab/drift-dataset/
#    (build #2's committed snapshot); the re-run reproduces build #2

# 4. the alarm list at the shipped thresholds
python3 tools/drift/pauses.py \
    --dataset docs/lab/drift-pause-dataset/dataset.json \
    --labels docs/lab/drift-pause-dataset/labels.json \
    --calibration docs/lab/drift-pause-dataset/calibration.json \
    --out docs/lab/drift-pause-dataset/pauses.json

# 5. the pause, dry-run (default) and enforced
python3 tools/drift/enforce.py --at 2026-11-01T19:45:00Z
python3 tools/drift/enforce.py --enforce --pause-file /tmp/p.json \
    --presence-file /tmp/presence.json --no-reload

# 6. the tests (70), and the world's own 13 checks
~/lm-wt/core-api/.venv/bin/python -m pytest tests/drift -q
cd ~/lm-wt/agent-world && \
    AW_BUILDER_IDE=~/lm-wt/drift-pause runtime/venv/bin/python \
    tests/test_drift_yield.py
```

Step 1 re-reads a live ledger and a live clients' log: re-running it
later gives a longer dataset — pin it with `--until` (as here) to
compare against this note.

## 7. Files

| file | what it is |
|---|---|
| `core/drift/pause.py` | the ladder wired to action: `PauseFile`, `plan_from_state`, `apply`, `clear` |
| `core/drift/ledger.py` | `read_yields`, the censoring, `extra_yields`, `--until`'s door (`until=`) |
| `core/records.py` (+ `night/recipe` events) | the drift group in the closed set |
| `tools/drift/enforce.py` | the operator door: dry-run by default, `--enforce` writes |
| `tools/drift/extract.py` | `--yields-from-bots`, `--until` |
| `tools/drift/calibrate.py` | the negative control's pure/inside-episode split |
| `tests/drift/` | 70 tests (24 new in this build) |
| `docs/lab/drift-pause-dataset/` | the after-dataset, labels, calibration, pause list |
| `agent-world/reflex/.../service.py`, `ledger.py` | the world's side: the yield write, the pause-file read (that repo's own commit) |
| `agent-world/tests/test_drift_yield.py` | the 13 world-side checks |
