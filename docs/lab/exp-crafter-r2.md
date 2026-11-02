# Task: Test Crafter teacher→student observation filter at bigger budget (round 2)

**Status:** complete. The matrix (96 runs) finished 2026-11-02 05:06 AKST (`logs/run_all.log`); every number below is re-derived from `results/summary.json` by `scripts/analyze.py` / `scripts/write_result.py` (verified vs. not: see "What is verified vs. measured"). Sections after the table were written by the CONTINUE seat after the run; nothing was re-run.

## Asked (round-2 brief, BRIEF.md md5 `9f6dec20826df0f64dba6af7cba6c5c0`)

Re-test the round-1 Crafter finding (Thor `~/lm-wt/crafter-lab`) at a bigger
budget **locally on the ProArt** (WSL, CUDA RTX 4050 6 GB, `free -g` checked
before each phase, keep the job under 3 GB):

1. copy the round-1 code/data from the Thor into `./r1`;
2. for each run emit **all-frames BC / teaching-moments BC / random-same-size
   BC**, 8 seeds per arm, evaluation on held-out seeds;
3. **round 1's limits to fix:** give each learner both a single-frame student
   and a memoryful student (4+ frames stack or small GRU); give each learner
   both **1x and 3x the gradient budget**; evaluate on the canonical
   **10,000-step** episodes instead of 1000;
4. detach the run (`setsid -f nohup`), poll every ~10 min, may run all night.

Deliverable: this report with the table and intervals, a verdict on **“which
frames to learn from”**, and a paragraph on what it changes in
builder-ide's `docs/design/watching-teachers.md`.

## Desk-needed

A definitive answer to the round-1 design question *“which frames of teacher
demonstrations should students learn from?”* — round 1 (one seed, one budget,
short episodes) said “teaching moments beat all frames, but a random subset of
the same size beat both”, which is too fragile a basis for the
watching-teachers design.

## Setup / configuration bookkeeping (round-2 differences from round 1)

| | round 1 (Thor `crafter-lab`) | round 2 (this dir) |
|---|---|---|
| teacher data | `r1/data/teacher_frames.npz`, 51395 frames / 200 episodes (sha256 `4134f11e…7edbe5e`, **cross-checked byte-identical** by `scripts/prepare_data.py`) | regenerated locally as flat `data/{frames,actions,events,episodes}.npy` from the same npz |
| student | SB3 `CnnPolicy`, 6 obs stacked | `lab/policy.py` small NatureCNN (1 conv stage + 32k MLP head, **~160k params** — same roles as round 1's nets, own file, provenance header) **and** GRU student (same CNN + 128-unit GRU over a 16-frame window, hidden carried within the episode, **~213k params**) |
| eval episodes | 1000 steps (CONTRACT) | 10000 steps (CANON), 8 held-out seeds 7100–7107 |
| seeds | 1 per arm | 8 per arm (init + minibatch draw), shared across arms for paired contrasts |
| budgets | 1x page pass protocol | 1x and 3x in **target passes** (= supervised presentations; 524288 / 1572864; batch 256 Adam 2.5e-4 = round 1's budget exactly) |
| teacher baseline | 8.25/9.25 achievements (1000/2000 steps) | measured again at 10000 steps (`results/baselines/teacher.json`) |
| box | Thor (16 core CPU-only) | ProArt WSL2, RTX 4050 6 GB, torch 2.15.0+cu132; job RSS ~2.3 G at peak (`results/benchmarks.json`) |
| code | Thor commit `d8e73cd3a3c26383983481d1e5a6fee173a5a7c4` | this repo's commits; `r1/` kept as the read-only input snapshot |

Everything above is verified by files in this repo (hashes, `data/meta.json`,
tests).

## Method (mechanism first)

**The question.** A teacher episode is a sequence of 51395 frames; a BC
student pays weight updates for the frames it is shown. Which frames?

* **all** — every teacher frame (round-1 arm B): most data diversity per pass,
  but most passes spent on frames the teacher repeats;
* **teach** — round 1's “teaching moments”: frames right before the teacher
  unlocks something new, *further filtered* to frames where the current
  student disagrees with the teacher action (round-1 arm C, reproduced here
  as a **two-round procedure per student architecture and seed**: untrained
  student → round-1 set → student retrained on it → round-2 set; the union is
  the arm's data). Mechanism claims: fewest redundant frames + the
  discriminating “this is the moment that mattered” frames;
* **rand** — a uniform random subset of the same size (round-1 arm C'). Any
  gain of `teach` over `rand` must come from *which* frames, not from *how
  many*.

**Budget invariance.** All arms run the same optimizer state and the same
number of supervised presentations (= “passes”); only the frames repeated per
pass differ. A memoryful student pays extra compute per presentation (a
16-frame window through the recurrent stack instead of one frame); those are
not supervised targets and are recorded separately (`frame_passes_compute`),
so budget comparisons stay like-for-like while the report can show the compute
the memoryfulness costs.

**Why expected to run on this box.** Training is supervised on cached frames
(GPU matrix work; benchmarked 207 (single) / 18 (GRU) updates/s at batch 256)
and the evaluations are the only Crafter rendering (8 interleaved envs,
~325 steps/s aggregate). Night budget: 96 runs ≈ 2–5 s … tens of minutes each;
see `results/benchmarks.json` and NOTES.md.

## Round-1 finding under test (copied from the round-1 doc; not re-verified here)

| arm | frames | 1000-step episodes |
|---|---|---|
| A all-frames BC (pages sweep) | ~190 pages | 0.875 ± 0.9 |
| B training-passed BC | 51395 | 1.375 ± 0.75 |
| C teaching-moment BC | 3757 | 1.375 ± 0.83 |
| C' random-subset BC | 3757 parts | 2.25 ± 0.83 |
| scripted teacher | — | 8.25 ± 0.25 |

## Method detail: the arms

| arm | data | student | budget |
|---|---|---|---|
| `single-all-b{1,3}` | 51395 frames | GRU-less CNN | 524288 / 1572864 target passes |
| `single-teach-b{1,3}` | 2-round teaching set (~3.7k frames) | GRU-less CNN | same |
| `single-rand-b{1,3}` | random set of the same size | GRU-less CNN | same |
| `memory-{all,teach,rand}-b{1,3}` | idem | CNN + GRU (16-frame window) | same |

* **Teaching sets** (`data/sets/*.npz`, `results/sets/*.json`): round 1's
  definition kept exactly (disagreement ∧ good outcome in the window right
  before the achievement's first unlock), replicated per architecture × seed;
  round 1 added 409 "new_unlock moments"; round 2's union usually differs (see
  table below).
* **Random sets**: uniform draw of `len(teaching_idx)` from the same 51395
  frames, draw seed `20261101 + 1000*arch + seed`; shared with the 1x arm of
  the same seed so budget contrasts are paired on the data too.
* **Eval**: 8 episodes, held-out seeds 7100–7107, greedy policy, **canonical
  Crafter contract**: one episode of up to 10000 steps, death (terminated) or
  the cap (truncated) ends it; score = distinct achievements in the episode.
  Round 1's CONTRACT instead capped 1000-step windows that restart on death and
  counted achievements cumulatively across lives — a different score scale, so
  round-1 numbers are NOT directly comparable to round-2 numbers (the round-2
  comparison is internal: all 96 runs share one contract). The canonical
  contract also makes a full 8-episode evaluation cost seconds-to-a-minute per
  checkpoint instead of ~4 minutes (8 x 10000 env steps of restart-run), which
  is what makes 5-checkpoint curves x 96 runs affordable on this box.
* **Agreement** (dominant metric in the watching-teachers doc's terms):
  fraction of teacher frames where the greedy student argmax == teacher argmax,
  over all 51395 frames (and over the 3757 decisive frames) at the final
  pass, plus every checkpoint on a 1-in-10 subsample.

## What is verified vs. measured

* **Verified by files/tests:** data provenance (sha256 in `data/meta.json`,
  checks in `scripts/prepare_data.py`), exact target/frame-pass accounting and
  episode-clamped windows (`tests/smoke.py`, 15/15 checks), determinism of
  init/eval seeds, box configuration and throughputs (`results/benchmarks.json`).
* **Measured only (single measurement, intervals over seeds):** every
  achievement score, agreement number, and wall time below.

---

## Results

Source: `results/summary.json` (96 runs), `results/curves/*.csv`, `results/baselines/teacher.json`.
Intervals are **mean ± 95% CI over the 8 training seeds** (Student-t, df=7, t=2.365),
where each seed's number is itself the mean over the 8 held-out eval episodes
(seeds 7100–7107). Contrasts are **paired per training seed** (the same seed is
reused across arms), so each is "arm A minus arm B on the same seed", n=8.

Box state beside the numbers: the matrix ran 23:52→05:06 AKST (≈5.2 h wall,
96 runs + 16 set selections + teacher baseline, one GPU, single-process evals),
job RSS peak **2.29 G** (`results/benchmarks.json`) under the 3 G seat line;
WSL shared with 7 other seats. At report time `free -g` = 10/15 G available and
the RTX 4050 is idle (185 MiB / 6141 MiB).

### Main table (final checkpoint = full budget)

`frames` = unique training frames; `passes/frame` = supervised presentations per
unique frame at that budget (524288 / 1572864 target passes ÷ frames); `agr` =
student–teacher greedy action agreement over all 51395 teacher frames / over the
≈3.7k decisive frames (`agreement_*_full`, final checkpoint); `train s` = training
wall seconds. Untrained = the same architecture at 0 passes (a random policy
scored on the same eval).

| arm | frames | passes/frame | untrained | **achievements (mean ± 95% CI)** | steps | agr all / decisive | train s |
|---|---:|---:|---:|---:|---:|---:|---:|
| `single-all-b1` | 51395 | 10.2 | 0.391 | **0.438 ± 0.515** | 186.1 | 0.456 / 0.148 | 41 |
| `single-all-b3` | 51395 | 30.6 | 0.422 | **3.094 ± 0.575** | 176.7 | 0.832 / 0.769 | 54 |
| `single-teach-b1` | 3382 | 155.0 | 0.422 | **1.219 ± 0.156** | 173.3 | 0.154 / 0.989 | 39 |
| `single-teach-b3` | 3382 | 465.1 | 0.406 | **1.219 ± 0.108** | 170.8 | 0.163 / 0.999 | 53 |
| `single-rand-b1` | 3382 | 155.0 | 0.391 | **1.266 ± 0.560** | 179.2 | 0.415 / 0.213 | 40 |
| `single-rand-b3` | 3382 | 465.1 | 0.406 | **1.281 ± 0.453** | 185.0 | 0.484 / 0.224 | 57 |
| `memory-all-b1` | 51395 | 10.2 | 0.094 | **0.203 ± 0.316** | 194.6 | 0.496 / 0.135 | 170 |
| `memory-all-b3` | 51395 | 30.6 | 0.141 | **2.969 ± 0.674** | 213.2 | 0.940 / 0.981 | 452 |
| `memory-teach-b1` | 3565 | 147.1 | 0.109 | **1.203 ± 0.124** | 172.9 | 0.161 / 0.993 | 170 |
| `memory-teach-b3` | 3565 | 441.2 | 0.078 | **1.250 ± 0.097** | 176.0 | 0.167 / 1.000 | 460 |
| `memory-rand-b1` | 3565 | 147.1 | 0.094 | **0.812 ± 0.268** | 186.0 | 0.362 / 0.248 | 170 |
| `memory-rand-b3` | 3565 | 441.2 | 0.109 | **1.172 ± 0.330** | 185.7 | 0.493 / 0.235 | 461 |
| *scripted teacher* (reference) | — | — | — | **8.125** | 206.5 | — | — |

Reference context: the teacher itself (which hunts monsters and dies early by
design) scores 8.125 achievements in 206.5 steps/episode on the same 8 eval
seeds. The best student (3.094) reaches **38 % of the teacher** — a BC clone
gap consistent with round 1. The untrained baselines differ by architecture
(single students already walk into a few achievements at 0.39–0.42; the GRU's
deterministic untrained policy scores 0.08–0.14), so read the impacts as
contrasts, and treat cross-architecture absolute scores with care.

Satisfying the contract detail: the 10,000-step cap **never binds** — every arm's
mean episode length is 170–213 steps (death ends the episode). "Canonical
10,000-step episodes" therefore tests short-horizon skill replication, not
10000-step survival.

### Learning curves (mean achievements at each checkpoint fraction of the budget)

| arm | 0 | 25 % | 50 % | 75 % | 100 % |
|---|---:|---:|---:|---:|---:|
| `single-all-b1` | 0.39 | 0.00 | 0.00 | 0.02 | 0.44 |
| `single-all-b3` | 0.42 | 0.00 | 1.84 | 2.88 | 3.09 |
| `single-teach-b1` | 0.42 | 1.31 | 1.20 | 1.20 | 1.22 |
| `single-teach-b3` | 0.41 | 1.16 | 1.19 | 1.12 | 1.22 |
| `single-rand-b1` | 0.39 | 0.02 | 0.22 | 0.84 | 1.27 |
| `single-rand-b3` | 0.41 | 1.09 | 1.19 | 1.44 | 1.28 |
| `memory-all-b1` | 0.09 | 0.00 | 0.00 | 0.03 | 0.20 |
| `memory-all-b3` | 0.14 | 0.02 | 2.27 | 3.08 | 2.97 |
| `memory-teach-b1` | 0.11 | 1.17 | 1.14 | 1.22 | 1.20 |
| `memory-teach-b3` | 0.08 | 1.28 | 1.17 | 1.11 | 1.25 |
| `memory-rand-b1` | 0.09 | 0.00 | 0.17 | 0.95 | 0.81 |
| `memory-rand-b3` | 0.11 | 0.78 | 1.06 | 1.12 | 1.17 |

The two subset families reach their ceiling at **25 % of the budget** and stay
flat (the ceiling is ≈1.2, near round 1's 1.375/2.25 on its 1000-step scale);
`all` at 1x is still underfit at 100 % (0.44 / 0.20 ≈ untrained), while
`all` at 3x passes both subset ceilings between 25 % and 50 % of its budget and
finishes 1.7–1.9 points above them.

### Paired contrasts (same seed, achievements, mean ± 95% CI, n=8 pairs)

Frame selection at 1x (the round-1 question at its original budget):

| student | contrast | mean ± CI | reading |
|---|---|---|---|
| single | teach − all | **+0.781 ± 0.499** | subsets beat all frames (CI > 0) |
| single | rand − teach | +0.047 ± 0.556 | no difference (round-1 rand advantage does not replicate) |
| single | rand − all | +0.828 ± 0.798 | same direction; CI touches zero |
| memory | teach − all | **+1.000 ± 0.375** | subsets beat all frames (CI > 0) |
| memory | rand − teach | **−0.391 ± 0.303** | teach ≥ rand (CI < 0), i.e. the opposite of round 1 |
| memory | rand − all | **+0.609 ± 0.377** | subsets beat all frames (CI > 0) |

Frame selection at 3x (the same question with 3x the gradient budget):

| student | contrast | mean ± CI | reading |
|---|---|---|---|
| single | teach − all | **−1.875 ± 0.647** | all frames now win (CI < 0) |
| single | rand − all | **−1.812 ± 0.691** | all frames win vs random too |
| single | rand − teach | +0.062 ± 0.477 | the two subsets tie |
| memory | teach − all | **−1.719 ± 0.708** | all frames win |
| memory | rand − all | **−1.797 ± 0.583** | all frames win |
| memory | rand − teach | −0.078 ± 0.349 | the two subsets tie |

Gradient budget (3x − 1x, same student and selection):

| student/selection | contrast | mean ± CI | reading |
|---|---|---|---|
| single all | b3 − b1 | **+2.656 ± 0.708** | the only large, positive budget effect |
| memory all | b3 − b1 | **+2.766 ± 0.694** | idem |
| single teach | b3 − b1 | +0.000 ± 0.158 | three times the budget adds nothing |
| memory teach | b3 − b1 | +0.047 ± 0.111 | idem |
| single rand | b3 − b1 | +0.016 ± 0.431 | idem (noise) |
| memory rand | b3 − b1 | +0.359 ± 0.495 | idem (CI covers 0) |

Memoryful vs. single-frame student (memory − single, same selection and budget):

| selection/budget | memory − single (mean ± CI) |
|---|---|
| all 1x | −0.234 ± 0.313 |
| all 3x | −0.125 ± 0.542 |
| teach 1x | −0.016 ± 0.233 |
| teach 3x | +0.031 ± 0.122 |
| rand 1x | −0.453 ± 0.602 |
| rand 3x | −0.109 ± 0.595 |

All six intervals cover zero; the GRU costs 4x (39s → 170s at 1x) to 8.5x
(54s → 452s at 3x) training wall for no measurable score change.

### Agreement and per-skill spread

* Round 1's disagreement filter is nearly vacuous on this teacher: the round-1
  selection keeps 3713 of 3757 decisive frames (98.8 %), the round-2 pass adds
  4–16 (`results/sets/*.json`), and the arm's data is that union — ≈3.4–3.8k
  frames. The two selection arms differ by *which* frames only in a 0–1 % band.
* The `teach` students memorize their selection: agreement on the decisive
  frames is **0.989–1.000**, while agreement over *all* teacher frames stays
  **0.154–0.167** and the score stops at 1.2. The `all`-b3 students instead reach
  0.832 / 0.940 overall agreement with 3.09 / 2.97 achievements. Across the 12
  arms, overall agreement and score move together (Pearson r = 0.65; within the
  `all` family alone r = 0.97, n=4, driven by budget). Decisive-frame agreement
  alone is a memorization check, not a competence measure.
* Per-skill success rates (`results/curves/skills.csv`): `single-all-b3` collects
  11 distinct achievements (collect_wood 0.72, collect_drink 0.45, place_table
  0.44, collect_sapling 0.39, defeat_zombie 0.38, eat_cow 0.23, make_wood_sword
  0.22, …), `memory-all-b3` 10. The `teach` arms get exactly 3
  (collect_sapling **1.00**, eat_cow 0.12–0.16, defeat_zombie 0.06–0.12): near-
  perfect on one skill, absent on the rest — a selection this narrow teaches
  its own skill and nothing else.

### What made the run possible (mechanism, per DOC-RULES order)

Training is supervised on cached frames, so the GPU (RTX 4050, 207 updates/s
single, 18/s GRU at batch 256) was never the wall-clock limit; the wrapper's
8 interleaved Crafter envs at ~325 steps/s kept each full-arm eval at seconds
(`results/benchmarks.json`), which is what let 5 checkpoints × 96 arms fit in
~5.2 h on a seat shared with 7 others (RSS 2.29 G peak). The earlier eval
contract (restart-on-death 1000-step windows, cumulative achievements) would
have cost ~32 h of evaluator alone; the canonical contract made the matrix
affordable — the price is that round-2 scores are a different unit from
round-1's.

---

## Verdict: which frames to learn from

**1x budget — moments vs random vs all.** Both subsets beat all frames
(teach − all = +0.78 ± 0.50 single, +1.00 ± 0.38 memory; rand − all = +0.83 ±
0.80 / +0.61 ± 0.38), and moments are indistinguishable from a random subset of
the same size (rand − teach = +0.05 ± 0.56 single; −0.39 ± 0.30 memory, i.e.
slightly *favouring* moments). Round 1's "random beats both" is a one-seed
fluctuation: at the round-1 budget, **which frames you keep is worth almost
nothing; how many you keep is worth everything.**

**1x vs 3x budget — the ordering reverses.** With 3x the gradient budget all
frames beat both subsets by 1.7–1.9 achievements (every paired CI excludes 0),
and neither subset improves at all from 1x to 3x (teach: +0.00 ± 0.16 / +0.05 ±
0.11; rand: +0.02 ± 0.43 / +0.36 ± 0.50). The mechanism is presentations per
unique frame: 155 (subset, 1x) vs 10 (all, 1x) vs 31 (all, 3x). A subset is
fit to saturation after ~40 presentations per frame (curve flat from the 25 %
checkpoint on); extra passes repeat a set that no longer contains new
information. All frames are underfit at 10 passes/frame and absorb the 3x
budget productively. So: **subsets are a compute-limited regime effect, not
better frames.**

**Single-frame vs memoryful.** Nothing to choose: all six paired contrasts are
inside ±0.6 with CIs covering zero, and the GRU costs 4–8.5x training wall.
Under this contract (episodes effectively end at death after ~170–215 steps)
the partial observability a GRU would fix hardly matters, so this is "no
measurable value here", not "memory is useless" (unverified for long-lived
episodes).

**The one-sentence answer.** Learn from **all frames at the largest gradient
budget you can afford (≈30+ presentations per frame here)**; if the budget
forces subsampling, a **random** subset of ~3.5k frames is as good as the
teaching-moment filter and cheaper — the disagreement+good-outcome criterion
keeps 98.8 % of decisive frames anyway and teaches nothing beyond its own
selection. A memoryful student does not change any of this.

**Corrections to round 1, stated explicitly (DOC-RULES 5).** Round 1's claims:
(a) "teaching moments beat all frames" — holds only at the small budget, and
reverses at 3x; (b) "a random subset of the same size beat both" — did **not**
replicate (8 seeds: rand − teach ≈ 0 single, −0.39 ± 0.30 memory); (c) "the
mechanism is data reduction, not the criterion" — **replicated**, and is the
part of round 1 to keep. Round-1 numbers also remain a different score unit
(1000-step restarting windows vs. canonical episodes) and are not mixed with
the table above.

## What this changes in builder-ide `docs/design/watching-teachers.md`

Applied to `/home/proart/projects/builder-ide/docs/design/watching-teachers.md`
in a dated block ("Measured, 2026-11-02 (round 2)") that supersedes the round-1
caveat, old text kept visible under "Superseded". The four substantive changes:

1. **The caveat is resolved in one direction and confirmed in the other.**
   "Until a test at a larger budget, with a memoryful student, says otherwise…"
   (2026-11-01) is now that test: moments ≈ random at 1x, and **all frames win
   at 3x**. The "demonstration" ladder step should train on **all** frames when
   the fine-tune budget allows ≳30 presentations per frame; subsampling is a
   compute-saving shortcut for small budgets, not a way to pick better lessons.
2. **Drop surprise+good-outcome as a data *filter*; keep it as a *label*.**
   The filter retains 98.8 % of decisive frames and its own disagreeing frames
   are what its student memorizes (decisive agreement 0.989–1.000 while scores
   stall at 1.2). The loop step "notice surprise" still says *what mattered*;
   it should not decide *what the weights see*.
3. **Flip the measure.** "Score students on per-skill decisive frames, not
   overall agreement" (2026-11-01) is backwards: decisive-frame agreement is
   gameable (saturates at 1.0 while the student gains nothing), overall
   agreement tracked score (r = 0.65 across arms; 0.97 within the all-frames
   family). Use overall agreement as the competence proxy and decisive-frame
   agreement as a memorization alarm. Consequently "retire the teacher" must
   key on agreement over **held-out** frames (or the student's own visitation),
   never over the frames the student trained on — otherwise a memorizing
   student silences its teacher while still failing the task.
4. **The reflex can stay memoryless, and clone-ceiling remains.** A 16-frame
   GRU changed no score (unverified for long streams), so nothing in the ladder
   needs a recurrent student; and the best clone reaches only 38 % of the
   teacher (3.09 vs 8.125), which supports retiring the teacher *skill by skill*
   instead of expecting full distillation from recordings.

## Risks / narrowness / what's left

* **One teacher, one game, one criterion.** `r1`'s scripted Crafter teacher
  (which hunts monsters and dies at ~206 steps), 51395 frames, and round 1's
  teaching-moment definition. Other filters (value-weighted, novelty, success
  rate) and other teachers are untested.
* **Short-horizon contract.** The 10000-step cap never binds; every episode ends
  in death after 170–215 steps. The verdict covers skill replication at that
  horizon, not survival or long plans — exactly where a memoryful student would
  earn its keep. Not measured.
* **Two budget points.** 1x and 3x bracket the crossover but do not locate it;
  from the 25 %–50 % checkpoints the `all` arm overtakes the subset ceiling at
  roughly a 2x budget (estimate, not measured).
* **8 seeds / 8 eval episodes.** t(7) intervals include eval-episode noise; the
  subsets are seed-sensitive (`single-rand-b1` ± 0.56 with one seed at 2.25),
  which is exactly the fluctuation that fooled round 1 (that arm's per-seed
  values are 0.375–2.375).
* **Offline agreement proxy.** Agreement is computed on the teacher's own 51395
  states, not on the student's visitation; the students' on-policy state
  distribution is measured only through achievements.
* **Clone gap is BC-only.** No DAgger/on-policy correction, one CNN width, one
  GRU width (16-frame window, 128 units); larger models or corrected data may
  move every arm. Untested.
* **Units are internal to round 2.** Round-2 scores are canonical-episode
  scores and must not be averaged with round-1's restarting 1000-step scores.
* **Sets are per-seed** (teach and rand differ in content across seeds), so the
  selection contrasts are paired on the *procedure*, not on identical data.
* **Not done here:** nothing in this repo's results was re-run (the director's
  instruction); `RESULT.json`'s `ground_truth_sha256_of_report` holds this
  document's sha256 and is filled by hand after the write.