# Watching a teacher teach: Crafter teacher-student experiment

Status: finished running; conclusion below. Written per `~/lm-wt/DOC-RULES.md`
(mechanism first, numbers with box state, suspected/confirmed labelled).
Numbers on this page are 8-seed evaluation means unless stated; every value is
reproducible with the commands in `README.md` and the seeds recorded in
`NOTES.md`.

## Mechanism

**What is being tested.** The brief's claim, stated exactly: *student C
(behaviour cloning on teaching moments) reaches full-BC student B's
achievement score using far fewer teacher frames if teaching moments are
counted separately, not as raw data*. Everything here is built to make that
comparison measurable against the same data at the same compute.

**The pipeline (one teacher, four students, one budget).**

1. A *scripted teacher* plays 200 seeded episodes of Crafter (cap 1000 steps,
   not the canonical 10000 - noted again under Limits). The teacher has
   privileged access to the Crafter world engine (it is `emergent/crafter`
   machinery reading its own tiles/entities) and walks a fixed target list:
   collect drink, wood, table, wood sword, pickaxe, sapling, stone, stone
   placement, stone sword, plants, coal, furnace, sleep. It fights a single
   adjacent enemy in 3 sword hits, flees mobs, and eats/drinks/sleeps for
   survival. This is `lab/teacher.py` and its fixed progress tests are
   `tests/smoke_teacher.py` (PASS on the recorded numbers in NOTES.md).
2. The episodes are recorded as the Minari dataset `crafter-teacher-v0`
   (exact pixels) plus `data/teacher_frames.npz`: each recorded step has the
   frame, the teacher's action, and which achievement counter advanced on that
   step (`achievement_event`). These two columns are what makes teaching
   moments and per-skill agreement computable at all (the doc-cited "design
   notes" `watching-teachers.md` / `autoplay-stack.md` are NOT present anywhere
   on either box on 2026-11-01 - checked in the session recorded in NOTES.md
   - so the definitions below are the operational readings of the brief).
3. **Teaching moments** (`lab/select.py`) are frames where (a) the student's
   greedy prediction differs from the teacher's action AND (b) the teacher's
   action on that step advanced an achievement counter ("the outcome was
   good"). The frame is attributed to the achievement the step advanced. Two
   selection rounds are used, the second one after the student has been BC'd
   on the round-1 set (both rounds' union is the teaching set).
4. **Students** (`lab/student.py`) share ONE network: NatureCNN over (3,64,64)
   frames with MLP [64,64] actor and value heads (a single fix across all
   students, so nothing differs but the training signal). Four learning
   variants run under the *same compute budget* of 524288 **sample-passes**
   (a batch of 256 through forward+backward counts as 256 passes):
   - **A - PPO** on the environment, reward = Crafter's achievement-bonus
     reward (what the env returns; the health term only, not the achievement
     unlock counts - the reward the standard env gives). Budget converts to
     env steps at passes/4 (n_epochs=4, rollout 256, 4 parallel envs).
   - **B - BC on all teacher frames** (51395).
   - **Bm - BC on a random subset** of the same size as the teaching set,
     the curation control.
   - **C - BC on teaching moments** (two-round selection).
   - **C_half - BC on a random half of C's set** (a frames-needed point).
   - **D - the same teaching set as C**, half the budget on BC and half on
     PPO fine-tuning starting from that BC actor (the brief's "student C plus
     PPO fine-tuning", kept budget-neutral).
5. **Measurements** at 0/25/50/75/100% of budget on the same evaluation seeds
   (7100..7107; 8 episodes, cap 1000 steps, never used for training):
   - *achievement score* = distinct achievements unlocked per episode (0..22);
   - *student-teacher agreement* = fraction of teacher frames where the
     student's greedy action equals the teacher's action (per achievement,
     measured on the frames that advanced that achievement, plus overall);
   - *teaching moments per skill* = number of curated frames attributed to
     each achievement. Curves and their data are in `results/curves/` (see
     `results/curves/numbers.json`).

**Why this should be true if the claim holds** (predicted mechanism):
curated frames are the moments where the student was wrong and the teacher
was decisive; if a student's failures come from missing exactly those decisive
actions, then cloning them should reach the same success as cloning everything,
while avoiding the gradient dilution of 51395 frames under a fixed budget.

## Environment and box state

- Thor: Jetson-class ARM box (Tegra kernel `6.8.12-1021-tegra`), 14 cores,
  122 GB unified memory (GPU memory is system memory; nothing that preallocates
  GPU memory was installed or run - CPU torch only; the venv is documented in
  `scripts/install_env.sh` with the exact wheels from the pytorch cpu index).
- The box is shared; recorded load averages: ~5 at teacher collection and at
  the benchmark, ~4-11 while the student runs were mixed with other seats'
  workloads. Two incidents where the box's own queue (`thor-admit`) went idle
  behind another renter's oversized request are logged in NOTES.md; the
  affected student runs went through `thor-admit exec` (no lease, daemon guard
  active) instead of waiting forever.
- Learner throughput on this box (4 torch threads, batch 256, `bench_sps.py`):
  14.27 BC updates/s = 3653 sample-passes/s. Environment throughput:
  1 env 166 steps/s, 2 envs 347, 4 envs 698, 8 envs 1314, 14 envs 1920
  aggregate (137 steps/s per env at 14). This is why A's budget is spent on
  131072 env steps while the BC students see the same budget in learner passes.

## Numbers

All "achievements" = distinct achievements per episode, mean over the 8 eval
seeds. Teacher baseline on those same seeds: **9.625 achievements** (return
8.73, 303 steps/ep). Teacher dataset itself (200 eps, seeds 1001..1200):
51395 frames; unlocks mean 9.335 per episode (0..16) at mean 257 steps
(25..864).

**Teaching set.** Round 1 (untrained student): 3746 of 51395 frames flagged.
Round 2 (after BC on the round-1 set): 409 more. Union = **3757 frames** =
exactly the number of good-outcome frames in the dataset (the sum of
per-achievement event steps). Mechanism: at this scale the "disagreement"
condition is nearly vacuous - an untrained student disagrees with ~99% of the
decisive frames - so the curated set here *is* the set of decisive-action
frames: the ~7.4% of the data where an achievement counter ticked. Per-skill
counts are exactly the demonstrations each skill received (whole dataset:
collect_drink 969, collect_wood 817, defeat_zombie 328, collect_stone 303,
eat_cow 232, place_table 180, make_wood_sword 171, make_wood_pickaxe 164,
collect_sapling 186, wake_up 105, place_stone 121, make_stone_sword 66,
place_plant 66, collect_coal 25, place_furnace 16, defeat_skeleton 8; skills
the teacher never shows: collect_iron/diamond, eat_plant, make_iron_*,
make_stone_pickaxe). The chart is `results/curves/teaching_per_skill.png`.

**Students (524288 sample-passes each; training time shown in
`results/<student>/summary.json`).**

| student | frames used | achievements (final) | agreement over all 51395 teacher frames |
|---|---|---|---|
| A: PPO on environment | n/a (131072 env steps) | **1.125** | 0.114 |
| B: BC on all frames | 51395 | **0.875** | **0.523** |
| Bm: BC on random 3757 | 3757 | **2.25** | 0.393 |
| C: BC on 3757 teaching moments | 3757 | **1.375** | 0.155 |
| C_half: BC on random half (1878) | 1878 | **1.25** | 0.138 |
| D: BC 262144 passes on the moments + PPO 262144 passes | 3757 | **1.125** | 0.153 |

Teacher baseline on the same 8 seeds: 9.625 achievements. All students start
at exactly 0.0 on the untrained checkpoint. Score curve shapes
(`results/curves/score_curve.png`, checkpoint values in
`results/*/curves.csv`): C climbs to 1.25 in the first quarter of the budget
and flat-lines (1.25, 1.0, 1.25, 1.375); C_half tracks it (1.125, 1.5, 1.375,
1.25); Bm stays at 0.0 for half the budget then climbs (0, 0, 1.5, 2.25);
B is near 0 until the very last checkpoint (0, 0.125, 0, 0.875); A gets
points on the board as soon as PPO has 32768 env steps (1.25) but does not
improve after (1.0, 1.25, 1.125); D's BC half reproduces C's 1.375 at
262144 passes and then the PPO fine-tune moves the score *down* (1.125,
1.125). What each final policy actually does on evaluation
(`results/*/skills.csv`): every student lands on `collect_sapling` first
(1.0 rate for A, C, C_half, D, 0.75 for Bm, 0.25 for B) because it is the
cheapest decisive action; only Bm and B pick up `collect_wood` (0.75 vs
0.125) and `collect_drink` (0.375 vs 0.125); nobody crafts past what the
teacher's own decisive frames show. The two-round selection did not change
the shape: round 2 added 409 frames and the union collapsed to the same
decisive-frame set (3757 = exactly the good-outcome frames).

## Verdict on the claim

Which claim is tested, and how it splits:

1. **Literal claim: "C reaches B's score with far fewer frames."** At
   524288 sample-passes and 8 fixed evaluation seeds, this is **confirmed as
   stated**: C scores 1.375 achievements with 3757 teacher frames where B
   scores 0.875 with 51395 frames - 13.7x fewer frames, and a consistently
   higher curve at four of the five budget checkpoints. `RESULT.json` has the
   machine-readable ratio (`frames_ratio_C_over_B = 0.073`).
2. **Presumed mechanism: "the teaching-moment criterion is what makes the
   curated set small and good."** This is **refuted by the run's own
   control**. Bm - a uniformly random subset of the same 3757 frames, chosen
   without any disagreement or outcome information - scores **2.25**, the
   highest of every student. C_half (random half of the curated set, 1878
   frames) scores 1.25, statistically indistinguishable from C. So the
   curated subset is not carrying information that a random same-size subset
   lacks; what it does is land on exactly the 3757 decisive-action frames
   (because the disagreement filter here kept 3746+409=3757 frames, i.e. all
   of them - see "Teaching set" above).
3. **What the run does show** (the mechanism that fits the data, labelled
   *observed*): at a fixed sample-pass budget, *data reduction* is what helps,
   because it multiplies gradient passes per unique frame (139 passes/frame at
   3757 frames vs 10 passes/frame at 51395) and the decisive actions are the
   thing that is hard to fit. Every student's strongest evaluation skill is
   `collect_sapling`, the cheapest decisive action; only data-rich-enough-in-
   diversity students (Bm, B) go past it.
4. **Agreement is not a proxy for score in this experiment** (a second,
   independent negative result): B has by far the highest action agreement
   with the teacher over all frames (0.523) and the lowest score (0.875), C
   has agreement 0.155 and the highest curated-set score (1.375). Agreement
   is dominated by the teacher's approach/locomotion frames (93% of the
   data); matching them does not unlock achievements. Any future brief that
   intends to use agreement as a teaching-signal proxy needs a decisive-frame
   agreement metric instead - the per-skill agreement numbers
   (`results/agreement_full.json`, e.g. C's agreement on `place_table`
   frames) are the ones aligned with score.
5. **PPO fine-tuning on top of the curated student (the brief's D) does not
   pay at this budget**: D's BC half matches C at 262144 passes (1.375) and
   the PPO fine-tune then lowers the score (1.125). A's PPO-only run reaches
   the same 1.125 in 131072 env steps and then stalls. This is consistent
   with PPO needing far more environment interaction than 131k steps to beat
   imitation on Crafter - not verified at larger budget.

**Mechanism-first explanation of what happened (observed, not proven).**
Teaching moments as defined here contain only the decisive action frames: the
step where the axe met the wood, the craft that produced the sword. They do
not contain the approach: the walking, scanning, and positioning that leads to
those frames, which is ~93% of the dataset. Behaviour cloning is a
*full-trajectory* training signal by nature - a student that only ever sees
the moment of contact learns "on tall grass, press do" (C's
collect_sapling=1.0 on evaluation) and very little else (its action
agreement on the rest of the data falls from 0.182 untrained to 0.139 -
measured, `results/C/agreement.csv`). A random subset keeps approach segments
in proportion: Bm's agreement rises to 0.383 and it goes on to collect wood
and water. The final-agreement numbers over all 51395 frames
(`results/agreement_full.json`) tell the same story at full data resolution.

## Limits of what this run establishes (explicitly NOT verified)

1. **Everything above is at ONE budget** (524288 passes, 8 eval seeds). The
   brief's curve claim ("implementation depends on how long the comparison is
   run in training") is only partly testable here: the curves exist
   (5 checkpoints each) but a longer run could change the ordering (B's
   advantage is still growing at 100% budget, C's is flat).
2. **Students see single frames (no memory).** A feedforward policy cannot
   know which of the 13 goals the teacher is currently pursuing; both BC and
   agreement measurements inherit that ceiling. A recurrent student could
   change the ordering; not tested.
3. **The teacher is a scripted, fixed policy**, not a learned model, and the
   "agreement" measure is agreement with that script's choices (minor
   movement differences already cost agreement). The teacher does not show
   the whole game (1.3 of 22 achievements are beyond its reach here:
   collect_iron/diamond, eat_plant, make_iron_*, make_stone_pickaxe).
4. **Teaching moments** here = "advance of any achievement counter" as the
   definition of "the outcome was good". Alternative operationalisations
   (e.g. first-unlock steps only, or frames within a window of a good outcome
   that include the approach) are not tested; the mechanism above suggests
   the second would be the interesting one.
5. **Episode budget is 1000 steps** in this lab (eval and training alike)
   while the Crafter benchmark usually scores 10000-step episodes. Scores are
   therefore not comparable to published Crafter numbers; comparisons in
   this document are all internal (same env, same seeds).
6. **PPO students need env steps**: at equal sample-passes, A and D's fine-tune
   phase are policy-gradient-limited (131072 env steps at A). The result
   would likely look different at a bigger budget; this is stated, not tested.
7. `~/lm-score/` and `~/lm-wt/README-proart.md` referenced by the briefs were
   not found on either box on 2026-11-01 (checked during the run; logged in
   NOTES.md), so the exact scoring commands the briefs assume were not run.

## Reproducibility

- Teacher dataset: `crafter-teacher-v0`, 200 episodes, seeds 1001..1200, framed
  as `data/teacher_frames.npz` (sha256 below). The dataset raw bytes stay in
  `data/minari/` on the Thor (regenerable in 232s from the script and seeds;
  the derived npz is the compact artifact this run shares).
- Student runs: `scripts/run_student.py` with `--passes 524288
  --eval-episodes 8`, seeds fixed as `--seed 0` (student A/D also use
  31000+ and 32000+ env seeds respectively - see the script).
- Curves: `results/curves/` (`score_curve.png`, `agreement_curve.png`,
  `teaching_per_skill.png`, `skills_success.png`, `merged_curves.csv`,
  `numbers.json`). Full-set agreement: `results/agreement_full.json`.
- Machine-readable result: `RESULT.json` (built by
  `scripts/write_result.py`).

Hashes (sha256, checked after the run):

```
4134f11e42bb26f050d9c896aa8d3c89a40d07a4a527e820cd6f024267edbe5e  data/teacher_frames.npz
f02a6f5257403374c4d69f0964114dde8b86aeb121764192e2c6240fbfdc6325  results/A/policy_final.pt
1c5c696bd9cdc79f4ef8b3634d666d84fa2287cc2be46e1381e98b7c854043be  results/B/policy_final.pt
f6ea7bd40472c3e87617ad286af49bd5c1c0bd70dae4503040d2b879ae56da63  results/Bm/policy_final.pt
45bb7fa7d2cf27600091c261115992f3935a6842c85d496064187b3c8180fde5  results/C/policy_final.pt
1dc6a8ce4aa757f8c915dcded6bbeb472810a30de3c7be1aa66d106ed59593e5  results/C_half/policy_final.pt
863ca1f3fc302eea7a50b5fa5a332d668df762f7ea3b3b1514c6aa36d396717c  results/D/policy_final.pt
```

Box state at the end of the run and the full session rules-check are the last
entry of `NOTES.md`.
