# LAB — exp-refit-drift: does the nightly whole-log refit drift the old contexts' value estimates (2026-11-01)

*Scope per BRIEF.md (the follow-up to
[exp-sleep-dreaming.md](exp-sleep-dreaming.md)): (1) does the nightly refit
over a growing log drift the old contexts' value estimates — measured with
`core/tiles/ope.py` on the six tiles the real nights authored; (2) the
watching-teachers question from `docs/design/watching-teachers.md`: when one
policy is fine-tuned on all the demonstrations, does the newest skill survive
and do the old ones degrade, reported in
[section 7](#7-the-watching-teachers-question-one-policy-many-demonstrations).*

**The verdict in one paragraph (part 1).** The whole-log refit does **not**
drift the old contexts' estimates: a bucket that received no new plays keeps
its estimate *exactly* (max move 0.0000, every night, in both arms that keep
the context definition fixed) because the refit is a fold over the same
counts; a bucket that did receive plays moves by the new information and
nothing else (mean |drift| 0.001–0.004, every interval containing zero).
Choices in old contexts flip at most 2.3 % a night. The off-policy estimator
is checked against a closed-form truth computed on the same data, and it
holds: 1.4–4.2 points of error at clip 10, shrinking as the effective sample
size grows from 89 to 1380. What *does* move is elsewhere, and both effects
are sized here: (a) the real loop's library churn (retire + author) changes
the **choice** in old contexts — 14–25 % of old buckets flip, and a third of
picks become tiles that have never been played, trusted on the 0.5 prior —
while the exact value on the old log stays put (0.000 ± 0.003); (b) **moving
the context definition** is the substrate risk the toy pointed at, and it is
the only thing that moves the old estimates en masse: on the one night the
definition moved, untouched buckets shifted by up to 0.411, 79.4 % of
choices flipped, and the OPE error tripled; it recovered within six nights.
So: **keep the whole-log refit** — it is the replay arm the toy says we need
and it costs the old contexts nothing; **version the context definition** —
changing one is a migration, not a config edit; and **watch the prior** —
when the library churns, old contexts are being served by tiles the prior
alone has endorsed.

**The verdict in one paragraph (part 2).** On crafter-lab's real teacher
frames (six skills, 3 seeds), sequential fine-tuning on the new
demonstrations is where the old skills die: the newest skill survives
(0.392) while the old five end at 0.318 on mean, down 0.029-0.059 from
their stage peaks, earliest-taught worst (0.11-0.14 for the second skill).
Half the stage budget replaying the old skills buys them back (old mean
0.428, per-skill loss <= 0.027) at no cost to the newest (0.411). Refitting
on the **whole** log at once - what the nightly refit actually does - shows
no forgetting at all and is the best student in the run (newest 0.457, old
0.495, overall 0.514, against 0.530 for crafter-lab's own well-trained
student). Per-skill heads isolate the skills perfectly but cost the single
policy. **Keep the whole-log refit**; stage with replay if the log ever
grows too big to hold; hold the heads as the fallback for a skill the
shared trunk provably cannot keep.

---

## 1. What was built, and what it is not

Three arms, all running the repo's own code (`core.tiles.chooser`,
`core.tiles.plays`, `core.tiles.retrain`, `core.tiles.ope`), 10 nights, 250
contexts a night, 24 seeds. Each night the chooser is refit on the whole log
so far — the nightly step — and then, at the end of the night, every old
(context bucket, tile) estimate is re-read and compared with what it was at
the end of the previous night, against the log **as it then stood** (the log
is fixed; only the policy moves).

| arm | the library | what else changes |
|---|---|---|
| `refit` | the six tiles the real nights authored, held fixed | nothing — isolates the refit |
| `refit_grow` | as `refit`, plus the retrain retires the tiles that lost and the cloud author writes new ones | the option set in every old bucket changes |
| `refit_moved` | as `refit` | at night 4 the **context definition** gains a feature (`builder`), so every old play is re-bucketed |

What is real, and what is a stand-in (stated, per the rules):

* **Real:** the six tile bodies (read out of the nights' own ledgers by
  `extract_real_tiles.py`), the vocabulary schema they are checked against,
  and all the chooser/ledger/retrain/OPE code.
* **Stated stand-in:** the outcome. A tile's win probability against a
  context is 0.85 (its style matches the one the context asked for), 0.40
  (right family, wrong look) or 0.15 (other family) — the tiles seat's
  acceptance-run numbers, with the middle level added. The consequence is
  that the truth of every estimate, and of the OPE value, is computable in
  closed form, so the estimator can be checked rather than trusted.
* **Stated stand-in:** which contexts the night sees. A real night works on a
  subset of the context space; here each night works on 4 of the 12 buckets.
  That is what makes the question "did the *quiet* old contexts move?"
  answerable.
* **Stated stand-in:** the cloud author. It is the repo's own
  `ScriptedAuthor`, writing vocabulary-legal tiles in the losing family's
  word, cycling styles.

## 2. The refit, isolated (`refit`)

The library is fixed at the six real tiles. The question the sleep-dreaming
toy left open: does the refit over a growing log move the old contexts'
estimates?

| night | untouched max move | touched mean move (95 % CI) | choice flip rate (CI) | OPE value, clip 10 | OPE drift, clip 10 (CI) | exact value drift (CI) | OPE error vs truth | eff. n (of plays) |
|---|---|---|---|---|---|---|---|---|
| 2 | **0.0000** | −0.0022 [−0.0153, +0.0110] | 0.0000 | 0.7758 | +0.0242 [+0.0217, +0.0268] | +0.0227 [+0.0209, +0.0244] | 0.0418 | 89 (of 500) |
| 3 | **0.0000** | −0.0039 [−0.0119, +0.0042] | 0.0104 [−0.0111, +0.0320] | 0.7662 | +0.0009 [−0.0005, +0.0023] | +0.0025 [−0.0023, +0.0074] | 0.0350 | 205 (of 750) |
| 4 | **0.0000** | −0.0027 [−0.0092, +0.0039] | 0.0182 [−0.0034, +0.0398] | 0.7548 | +0.0011 [−0.0025, +0.0048] | +0.0017 [−0.0011, +0.0045] | 0.0272 | 346 (of 1000) |
| 5 | **0.0000** | +0.0028 [−0.0045, +0.0101] | 0.0094 [−0.0041, +0.0229] | 0.7474 | −0.0006 [−0.0019, +0.0007] | +0.0025 [−0.0014, +0.0064] | 0.0183 | 502 (of 1250) |
| 6 | **0.0000** | −0.0030 [−0.0087, +0.0027] | 0.0168 [+0.0005, +0.0330] | 0.7517 | +0.0034 [−0.0008, +0.0077] | +0.0044 [−0.0021, +0.0109] | 0.0176 | 666 (of 1500) |
| 7 | **0.0000** | −0.0033 [−0.0067, +0.0002] | 0.0228 [+0.0057, +0.0399] | 0.7507 | +0.0017 [−0.0040, +0.0074] | +0.0001 [−0.0031, +0.0033] | 0.0182 | 847 (of 1750) |
| 8 | **0.0000** | −0.0010 [−0.0064, +0.0043] | 0.0107 [−0.0015, +0.0230] | 0.7481 | +0.0009 [−0.0012, +0.0030] | +0.0023 [−0.0010, +0.0055] | 0.0146 | 1030 (of 2000) |
| 9 | **0.0000** | +0.0022 [−0.0032, +0.0075] | 0.0142 [+0.0005, +0.0279] | 0.7522 | +0.0046 [−0.0004, +0.0095] | +0.0051 [−0.0014, +0.0117] | 0.0150 | 1202 (of 2250) |
| 10 | **0.0000** | −0.0017 [−0.0061, +0.0026] | 0.0000 | 0.7534 | 0.0000 | 0.0000 | 0.0141 | 1380 (of 2500) |

The estimate error against the truth stays at 0.099–0.105 all the way (the
prior's shrinkage), and no (bucket, tile) pair collapses to the prior in
either arm that keeps the definition fixed.

Read: the untouched rows are the invariant — a refit is a fold, so a bucket
with no new plays re-derives the identical posterior, and the measurement
confirms it to exactly zero, not to noise. The touched rows carry all the
drift, and the drift is the new information: the mean is 0.001–0.004 in
either sign. The one night that looks like drift, night 2's +0.023, is the
**exploration rate decaying**: the night-1 snapshot still carries
ε ≈ 0.24, the night-2 snapshot less, so on the same old log the second
chooser is greedier and better. It is an improvement, not a loss — and after
night 3 every exact drift is within ±0.005 with the interval over zero.

## 3. The real loop (`refit_grow`)

The refit plus the churn: the retrain retiles the families that lost, and
the author writes a new tile into them, so a tile with **no history** enters
every old bucket.

| night | option set changed in | choice flip rate (CI) | picks that are a new tile | OPE value, clip 10 | exact value drift (CI) | OPE error vs truth | eff. n |
|---|---|---|---|---|---|---|---|
| 2 | 3.2 buckets/night | 0.1250 [+0.0487, +0.2013] | 0.0833 | 0.7758 | +0.0227 [+0.0209, +0.0244] | 0.0418 | 89 |
| 3 | 5.0 | 0.2244 [+0.1540, +0.2948] | 0.1962 | 0.7592 | +0.0009 [−0.0057, +0.0075] | 0.0449 | 197 |
| 4 | 5.4 | 0.1711 [+0.1185, +0.2236] | 0.2840 | 0.7391 | +0.0007 [−0.0031, +0.0046] | 0.0402 | 340 |
| 5 | 5.5 | 0.1241 [+0.0809, +0.1672] | 0.3070 | 0.7390 | +0.0013 [−0.0006, +0.0032] | 0.0351 | 493 |
| 6 | 9.5 | 0.2504 [+0.1987, +0.3020] | 0.3460 | 0.7353 | +0.0005 [−0.0019, +0.0029] | 0.0284 | 659 |
| 7 | 4.8 | 0.1652 [+0.1055, +0.2249] | 0.3463 | 0.7275 | +0.0004 [−0.0005, +0.0013] | 0.0257 | 832 |
| 8 | 6.2 | 0.2005 [+0.1374, +0.2637] | 0.3499 | 0.7225 | 0.0000 | 0.0216 | 1010 |
| 9 | 6.3 | 0.1812 [+0.1214, +0.2411] | 0.3557 | 0.7189 | 0.0000 | 0.0194 | 1197 |
| 10 | 4.4 | 0.1379 [+0.0866, +0.1893] | 0.3409 | 0.7216 | −0.0003 [−0.0009, +0.0003] | 0.0219 | 1374 |

(untouched max move is 0.0000 here too; means over 24 seeds.)

Read: the **estimates** do not drift (same invariant as section 2, same
touched magnitudes). The **choice** is what changes: with 3–9 buckets a
night getting a new option, 14–25 % of old buckets end the night picking a
different tile than the previous night's chooser did, and by night 3 a third
of old-context picks is a tile that has never been played — it won on the
0.5 prior alone, against incumbents some of whom sit at 0.15 in that bucket.
The exact value on the old log does not move (0.000 ± 0.003), so the churn
buys no drift and loses none in this world; what it does is make the old
contexts' behaviour depend on tiles the prior endorsed, not the log. By
night 10 the OPE estimate of this churned chooser sits ≈3 points below the
fixed-library chooser's (0.722 vs 0.753), and the truth says ≈0.4 of that is
real — the rest is the estimator's own error, which is ~50 % larger in this
arm (0.022 vs 0.014 at night 10) because the target now points at tiles the
logger rarely played, so the weights lean on the clip.

## 4. The moved definition (`refit_moved`)

Arm `refit`, except that at night 4 the bucketing gains a feature
(`builder`). Every old play is re-bucketed; the counts that were under one
bucket are split across two, and each new bucket sits nearer the prior.

| night | untouched max move | touched mean move (CI) | pairs collapsed to prior | choice flip rate (CI) | error vs truth (old view) | OPE error vs truth |
|---|---|---|---|---|---|---|
| 3 (before) | 0.0000 | −0.0039 [−0.0119, +0.0042] | 0 | 0.0104 [−0.0111, +0.0320] | 0.1075 | 0.0350 |
| **4 (the move)** | **0.4110** [+0.4002, +0.4218] | +0.1511 [+0.1305, +0.1717] | 45.3 [+42.6, +48.0] | **0.7940** [+0.7641, +0.8240] | **0.2802** | **0.0736** |
| 5 | 0.0000 | −0.0003 [−0.0057, +0.0050] | 0 | 0.0389 [+0.0172, +0.0606] | 0.1177 | 0.0456 |
| 6 | 0.0000 | −0.0033 [−0.0077, +0.0012] | 0 | 0.0325 [+0.0121, +0.0529] | 0.1147 | 0.0338 |
| 7 | 0.0000 | −0.0034 [−0.0063, −0.0005] | 0 | 0.0225 [+0.0077, +0.0373] | 0.1134 | 0.0214 |
| 8 | 0.0000 | −0.0007 [−0.0033, +0.0018] | 0 | 0.0054 [−0.0008, +0.0115] | 0.1128 | 0.0185 |
| 10 | 0.0000 | −0.0016 [−0.0045, +0.0013] | 0 | 0.0071 [−0.0015, +0.0157] | 0.1121 | 0.0149 |

Read: this is the substrate risk from the toy, measured. One night, and the
old estimates are wrong by 0.28 instead of 0.11 (against the truth, read in
the old definition's view), 45 of the old pairs have no arm at all, and the
chooser flips 79.4 % of its old-bucket choices even though the option set
did not change. And the quiet buckets moved too — 0.411 at most — because
"quiet" was defined under the old definition; under the new one their counts
were halved into fresh buckets. The system does repair: the nights refill
the new buckets, the error is back to 0.0456 within two nights and to the
steady 0.015 by night 10. The cost of a definition change is not a one-time
blip, it is **several nights of the old history being worth half**, and
everything read off the log in the meantime (retirements, authoring
feedback, OPE reports) is read against buckets that moved.

## 5. The OPE estimator, checked

`core.tiles.ope`'s SNIPS estimate (clip 10) is scored against the closed-form
truth on the very same records, every night, both arms:

* error vs truth: 0.042 → 0.014 over the ten nights (the `refit` arm),
  0.042 → 0.022 (`refit_grow`), spiking to 0.074 on the moved-definition
  night and back to 0.015 by night 10;
* the effective sample size behind each number grows with the log (89 →
  1380 of the plays), and the report carries it next to every value;
* the per-seed 95 % intervals of the OPE value are wide early (the union over
  seeds spans 0.18–1.0 at night 2) and narrow with the log; the paired
  drift (same records, two snapshots) is the tighter number, and its
  intervals are the ones quoted above.

Clip 10 was chosen on the diagnostics, not the error: at 10 the effective
sample size passes a third of the plays once the logger has converged, and
the largest weight is ten.

## 6. Recommendation

1. **Keep the whole-log refit.** It is the replay arm the toy says the old
   knowledge needs, and the measurement says the old contexts cost nothing:
   quiet buckets move exactly zero, touched buckets move by their new
   information, and the estimator that reports it is accurate to 1.4–2.7
   points with a sample size that grows with the log.
2. **Version the context definition.** The refit is safe; the definition is
   not. A move re-buckets the whole history, halves the counts, invalidates
   45 pairs a night and 79 % of the choices for the duration of the
   transition. A definition change must be a migration (two definitions
   side by side until the new one has its counts), not a parameter edit.
3. **Watch the prior when the library churns.** Churn does not drift the
   old estimates, but it does hand a third of the old contexts' choices to
   tiles that the 0.5 prior endorsed and the log has not. If the churn is
   to stay in the loop, the price to watch is not drift — it is what those
   untested tiles actually do.

## 7. The watching-teachers question: one policy, many demonstrations

**The question (BRIEF part 2).** The design's weights path is "the
student's policy fine-tuned on the demonstrations" - one policy, many
demonstrations, arriving skill by skill. When the newest skill's
demonstrations are trained in, does the newest skill survive and do the old
ones degrade? Measured on the real data the brief named: crafter-lab's
recorded teacher frames.

**Setup.** The six skills with the most demonstrations, in the order the
teacher taught them - `collect_drink`, `collect_wood`, `collect_sapling`,
`collect_stone`, `eat_cow`, and newest `defeat_zombie` (969, 817, 186, 303,
232, 328 demonstrations); a fixed split (seed 20261101; per-skill held-out
eval capped at 1000 frames, a 2000-frame whole-trajectory sample); 3 seeds;
262144 gradient passes per stage; the repo's SB3 student on CPU. The metric
is student-teacher agreement on held-out frames, with the env-achievements
score (four 1000-frame episodes) beside it. Four arms:

| arm | what is trained |
|---|---|
| `seq` | skill by skill in teaching order, no replay - "fine-tune on the new demos" as it stands |
| `seq_replay` | same, but half of each stage's budget replays earlier skills' demos |
| `whole` | one training pass over **all** the demonstrations - what the nightly whole-log refit does |
| `per_skill_heads` | a shared trunk on all the demos (half the budget, then frozen) plus one linear head per skill on that skill's demos only |

**Calibration, so the agreement can be read** (`_diag_calib.py`, table in
`results/calib_budget.log`): the *untrained* policy agrees at 0.104-0.197
(overall 0.192) - at or **below** the constant-action baseline (0.208-0.323
per skill); crafter-lab's own well-trained student B agrees at 0.352-0.443
(overall 0.530). `_diag_budget.py`: at our per-stage budget a single-skill
student scores 0.382 on wood (0.260 at 16384 passes, its constant
baseline). Every arm in the table is a weak student between those two
references; a 1000-frame eval carries about 1.5 points of standard error.

**The result** (final per-skill agreement, 3 seeds each; min-max (mean)):

| arm | newest (`defeat_zombie`) | old mean | overall (trajectory) | old-skills forgetting | env achievements |
|---|---|---|---|---|---|
| `seq` | 0.382-0.405 (0.392) | 0.311-0.324 (0.318) | 0.324-0.344 (0.333) | 0.029-0.059 (0.044) | 2.00-3.00 |
| `seq_replay` | 0.386-0.431 (0.411) | 0.424-0.434 (0.428) | 0.450-0.462 (0.456) | 0.007-0.013 (0.010) | 1.00-2.75 |
| `whole` | 0.455-0.459 (0.457) | 0.489-0.502 (0.495) | 0.510-0.521 (0.514) | 0 (one batch) | 1.50-3.00 |
| `per_skill_heads` | 0.429-0.442 (0.435) | 0.458-0.476 (0.465) | 0.468-0.510 (0.489) † | 0.006-0.011 (0.009) † | - (no single policy) |

† the heads arm has no single policy. "Overall" is the shared base
policy on the trajectory, not the heads; "forgetting" compares each head
with the trunk-stage reading of the same skill (the heads are never
retrained, so nothing later writes them - the isolation is by
construction); the env score is unmeasurable because the design does not
name which head answers the environment. The script records that rather
than papering over it. Env ranges pool the three attempts: the env
episodes are not deterministic, the agreement numbers are, and every
attempt reproduced them bit for bit.

Per-skill finals in `seq`, where the forgetting is visible (3-seed means),
against each skill's stage peak: drink 0.316 (peak 0.33), sapling 0.371
(0.40), stone 0.286 (0.33), wood 0.265 (0.39), eat_cow 0.354 (0.36), and
the newest, zombie, 0.392. Wood, the second skill taught, loses
0.108-0.139 - the largest single loss in the run.

**What each arm says.**

1. *`seq` - the newest skill survives; the old ones degrade, earliest
   worst.* The skill trained last ends above every old skill's final value
   while the old five drop 0.029-0.059 on mean from their peaks. Last
   writer wins on a shared substrate; nothing in the loop writes the old
   behaviour back.
2. *`seq_replay` - half the budget replaying the old demos buys them
   back.* Old mean 0.318 to 0.428, per-skill forgetting <= 0.027, newest
   0.392 to 0.411, overall 0.333 to 0.456. The cheapest insurance a staged
   pipeline can buy.
3. *`whole` - no forgetting, and the best student in the run.* One pass
   over everything: every skill at its best per-skill value (0.457-0.537)
   and within 2 points of crafter-lab's own student B on the overall
   measure.
4. *`per_skill_heads` - zero interference, zero single policy.* Each head
   keeps 0.428-0.507 and is never touched again, and every head lands
   within 3 points of the trunk's own reading of its skill, mostly a hair
   below; but no policy can act in the environment, routing is the design's
   open question, and the partition is not a policy.

**Recommendation (part 2).** **Keep the whole-log refit.** The nightly
refit that retrains on the entire log is the `whole` arm; it is the best
student measured and it has nothing to forget - the same verdict as part
1's, since the refit *is* the replay arm the toy said we need. Sequential
fine-tuning on the new demonstrations is the arm that loses the old skills;
if the log ever grows too big to refit whole, stage it **with replay** -
`seq_replay` is the measured fix and it cost the newest skill nothing
here. Per-skill heads are the fallback for a skill the shared trunk
provably cannot hold; this measurement did not need that fallback, and the
price - the single policy, and with it the "task success with the student
alone" score - is real.

**The run.** 12 runs (4 arms x 3 seeds), 6-10 min each, CPU torch under a
2 GiB thor-admit practice lease: the heads arm 00:41-00:59 AKST, the three
policy arms 01:24-02:47 AKST, 2026-11-02; box at start: load
5.6/12.1/19.7, 97 GiB available of 122.8, 14 cores, GPU 0 % for the job
(three other seats' llama servers idle on the GPU, ~12 GiB). The first two
attempts both crashed in `per_skill_heads` (NOTES.md, 21:58 and 00:40
entries) and lost their end-of-run JSONs; the agreement numbers are
deterministic and reproduced bit-identically across attempts, and the
scripts now save the JSON after every run, so the two recorded JSONs plus
the per-seed summary lines in the four logs are the complete record.

## 8. What was not verified

The outcome model is a stated stand-in; the tiles, the vocabulary and the
code are real, the 0.85/0.40/0.15 win rates are the tiles seat's
acceptance numbers with a stated middle level. The bandit is the first rung
of the chooser ladder, not the learned ranker behind it — the mechanism
measured (fold, prior, re-bucketing) is the one every rung shares through
`TileChooser`, but a learned ranker could drift in ways a posterior mean
cannot. The contexts are 4 of 12 buckets per night, and the cloud author is
scripted. The truth is closed-form **because** the outcome model is known;
that is the strength of the measurement and its limit.

Part 2's unverified parts. The students are weak by calibration: the
agreements of 0.32-0.52 sit between the untrained policy (0.19 overall, at
or below the constant-action baseline) and crafter-lab's student B (0.53
overall), so the per-arm gaps are directionally robust but the last point
is not. The env score is four 1000-frame episodes and it is not
deterministic (1.00-3.00 achievements across three attempts of the same
arm) - a coarse instrument, reported beside the agreement, not instead of
it. The `whole` arm is one batch over all the demonstrations, which is the
nightly refit's job, but it is not a growing-log time series: it measures
what retraining on everything achieves, not how the estimates move night by
night (part 1 measures that, for the tiles). The `per_skill_heads` arm has
no environment score because the design does not name which head answers
the environment - a cost of the design, recorded. One teacher, one
environment, 3 seeds, and the reference is the teacher's own play, so a
student matching it may still be off from optimal play.

## 9. Reproduce

```bash
cd ~/lm-wt/refit-drift
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "numpy>=1.26" "pydantic>=2.7,<3"
.venv/bin/python docs/lab/refit-drift-scripts/extract_real_tiles.py \
  --out docs/lab/refit-drift-scripts/real_tiles.json
.venv/bin/python docs/lab/refit-drift-scripts/exp_refit_drift.py \
  --seeds 24 --out docs/lab/refit-drift-scripts/results/refit_drift.json
```

About 64 s on the Thor (2026-11-01 19:38:02–19:39:06 AKST), under a
thor-admit practice lease, 24 seeds × 3 arms × 10 nights, no model loaded.
Box at the run: load 5.41/5.21/8.71, 114.4 GiB available of 122.8, 14 cores,
GPU at 0 % for this job (one other seat's server on the GPU, 2.7 GiB).
The recorded run, every row, is
`docs/lab/refit-drift-scripts/results/refit_drift.json`; the box state is in
it.

Part 2 needs the crafter-lab venv and its teacher frames (about 90 min for
the three policy arms, about 20 min for the heads arm; run under a
thor-admit lease):

```bash
cd ~/lm-wt/refit-drift/docs/lab/refit-drift-scripts
PY=/home/caseydigennaro/lm-wt/crafter-lab/.venv/bin/python
$PY exp_watching_teachers.py --seeds 3 --passes-per-stage 262144 \
  --arms seq,seq_replay,whole --out results/watching_teachers.json
$PY exp_watching_teachers.py --seeds 3 --passes-per-stage 262144 \
  --arms per_skill_heads --out results/watching_teachers_heads.json
$PY _diag_calib.py   > results/calib_budget.log
$PY _diag_budget.py >> results/calib_budget.log
```

Recorded: `results/watching_teachers.json` (the three policy arms),
`results/watching_teachers_heads.json` (the heads arm),
`results/calib_budget.log` (the calibration table), and the four summary
logs `watching_teachers.log`, `.run2.log`, `.run3.log`, `.run4.log`. The
box state is inside each JSON. See the directory's README for the crash
history and why the first two attempts are summary lines, not JSONs.
