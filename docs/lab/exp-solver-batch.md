# EXP — batch the Architect's solver proposals (IDEAS round 4, #4)

**Date:** 2026-10-31 · **Seat:** `~/lm-wt/lab5` · **Author:** the lab seat
(zcode, round 5; finished by the round-5 handover seat after the first
seat's quota ran out).

**Status: DONE — the kill condition fired.** Accept-the-best changes the
annealer's output distribution (every seed, D = 0.8–1.0), and the second
variant, Boltzmann-sample, is *not* neutral either — at the annealer's own
temperatures it degenerates to near-best. The uniform-pick control passes,
which is what proves the harness measures the idea and not a bug. Verdict
and what survives are in §6.

---

## 1. The idea

`IDEAS.md` round 4 #4: the Thor's GPU scores solver candidates at ~48 M/s
(round 2), but Infinigen Indoors' constraint solver proposes **one candidate
per annealing step** (`propose_continous` / `propose_discrete` yield one
move at a time; `SimulatedAnnealingSolver.retry_attempt_proposals` applies
the first applicable one and hands it to the Metropolis decision). Change
the proposal step to emit **N candidates**, score them as a batch, and hand
the annealer the **best** (second variant: a **sample** from the scored
set), keeping the accept/reject decision sequential. Then the gate: the
annealer's output *distribution* must be unchanged — or the idea is dead
and the GPU number stays decorative.

**Scope decision (stated plainly):** the batch is scored on the **CPU**,
candidate-by-candidate through the real constraint graph
(apply → evaluate → revert each). Round 2 already measured the GPU scorer
in isolation; what it could *not* measure is whether batching changes the
annealer — that is solver-side, and that is what this experiment gates. The
CPU cost of the batch is measured here too, which is what bounds what a
free scorer would actually buy (§5.3).

## 2. Hypothesis

1. Batched proposals with **sample** picking leave the output distribution
   statistically unchanged; **best-of-N shifts it** (greedier kernel) — if
   so, that is the kill condition for "accept the best".
2. On the CPU the batch costs ~N× applies per step; **apply, not scoring,
   is the measured bottleneck**, so a free scorer alone does not make
   batching cheap — the win requires replacing the whole
   apply→evaluate→revert probe with hypothetical-pose scoring (the
   restructure round 2 predicted at a 64–256-candidate crossover).

Measured outcome: **both confirmed — and the first one worse than
hypothesised**: not only best, but the Boltzmann *sample* variant also
shifts the distribution (§5.4), because the annealer's temperature is cold
relative to the loss spread between candidates, so `exp(-Δloss/T)` is
effectively an argmin. Only the uniform pick (the control) is neutral, and
it buys nothing.

## 3. Setup

- **Machine state:** recorded beside every table (§5.1); the sweep shares
  the box with other seats (load 7–59, median ≈ 16 over the 35 runs; the
  other seat's forest seed-sweep ran throughout). Arms are interleaved by
  seed (round rule 4); absolute walls are ranges, not points.
- **Solver:** `~/src/infinigen-thor` (branch `thor-spike`), byte-identical
  in the changed file to the checkout the venv runs
  (`~/lm-wt/v2-thor/src/infinigen-upstream`, infinigen 2.0.0a3; verified by
  `diff`). Neither checkout is modified: the changed method lives in
  `scripts/solver_patch.py` here and is monkeypatched in at runtime.
- **Venv:** the v2 venv (`~/lm-wt/v2-thor/.venv`, Python 3.11, bpy 4.2.0),
  used read-only. It lacks the Indoors-only deps (`gin-config`,
  `scikit-learn`, `networkx`, `psutil`, `scikit-image`, …), which are
  installed **into `lab5/pylibs`** (`pip install --target`, `--no-deps`
  where the venv already provides the dep) and prepended via `PYTHONPATH`.
- **Scene:** `base_indoors.gin` + `fast_solve.gin` + `singleroom.gin`
  (solve_max_rooms=1 — one room, a bathroom on every seed here). Solve-only
  driver (`scripts/run_solve.py`): the `compose_indoors` solve stages in
  upstream order, no terrain/cameras/render/final population. **Seeds:** the
  upstream floor-plan solver crashes on some seeds with a degenerate
  shapely polygon (2, 3, 4 among those probed — logged in §7); every arm
  uses the same five surviving seeds **0, 1, 5, 6, 7**.
- **The change (batched proposals):** `retry_attempt_proposals` swapped for
  lab5's copy: draw up to N *applicable* candidates from the same generator
  (invalid-apply allowance = N × the upstream `max_invalid_candidates`),
  score each (apply → evaluate → revert), pick per mode, re-apply the pick,
  return it to `step()` whose Metropolis accept/reject is untouched.
  Stochastic-apply moves (Addition, Resample, ReinitPose,
  RelationPlaneChange) are re-scored after re-apply so state and score
  always agree; deterministic moves (Translate, Rotate, Deletion) reuse the
  batch score. The baseline arm runs the upstream method verbatim (timing
  probes only — re-verified against upstream this round).
- **Arms** (`scripts/sweep.py`), all same-steps (the upstream step count,
  N candidates scored per step):
  - **Gate arms** (`results/`): the **large-object stages only** at
    `solve_steps 15/0/0` — `baseg` (upstream), `b8bestg`, `b64bestg`,
    `b512bestg` (best-of-N), `b8sampleg`, `b64sampleg` (Boltzmann sample),
    `b8unifg` (uniform pick — a control whose proposal kernel provably
    matches baseline). Seeds 0,1,5,6,7 (N=64 sample: 0,1,5; N=512: 0,1 —
    the CPU cost of the wide batches on the seed-5 room is the §7 blowup).
  - **The today-anchor** (`results_full/`): `basefull` — upstream at the
    real fast_solve schedule (100/40/5), all stages, seeds 0,1,5,6,7. This
    is the wall the Architect waits today.
  - **Supplementary** (`results_quarter/`, `results_eq/`): a one-seed
    quarter-schedule run of the *full* stage set (25/10/5) — the first gate
    design, kept because it corroborates the gate on the medium/small
    stages too — and the equal-budget datapoint (steps ÷ N).
- **The gate:** two-sample KS (scipy) over placement scores, baseline vs
  each arm, plus Cliff's δ; per-seed final losses (the brief's literal
  ask), pooled per-stage losses (with an explicit pseudo-replication
  caveat: the second large stage is a no-op on this scene, and stages
  within a seed are sequential), the **paired-by-seed sign view** (the
  seed is the independent unit), and tie-quantised variants at the round-2
  tie scale (0.5 and 1.0). Violation counts reported alongside.

## 4. Reproduce

```bash
cd ~/lm-wt/lab5
# deps into lab5/pylibs (venv untouched; see §3)
~/lm-wt/v2-thor/.venv/bin/pip install --target pylibs gin-config \
  scikit-learn joblib threadpoolctl cloudpickle narwhals lazy_loader \
  networkx psutil scikit-image tifffile
python3 scripts/check_patch.py         # patch applies + compiles + self-attrs resolve
python3 scripts/smoke_patch.py         # the patched method runs (stub moves/state)
bash scripts/probe_seeds.sh 0 1 2 3 5  # which seeds survive the floor-plan solver
python3 scripts/sweep.py               # the full sweep (2 h 7 m measured, shared box)
python3 scripts/analyze.py             # tables + the KS gate  -> results/analysis.txt
# one run by hand:
env PYTHONPATH=pylibs ~/lm-wt/v2-thor/.venv/bin/python scripts/run_solve.py \
  --seed 0 --arm batch --N 64 --mode best --budget same-steps --stages large \
  --steps-override 15,0,0 --out /tmp/b64bestg_seed0.json
```

Raw per-run logs in `runs/`, JSONs in `results*/`, box snapshots in
`runs/box_*.txt`, per-run load in every JSON's `meta.load_start/end`.

## 5. Numbers

### 5.1 — the box, beside every number

| | sweep start | sweep end | analysis |
|---|---|---|---|
| time | 10:23 | 12:30 | 12:35 |
| loadavg 1 min | 24.5 | 23.1 | 17.9 |
| RAM used/total | 44/126 GB | — | — |
| GPU | idle, 2.8 W, 42 °C | idle | idle |
| top procs | 3 python (other seats) | | |

Kernel 6.8.12-1021-tegra, aarch64, 14 cores; all solve runs are pure CPU.
Across the 35 recorded runs load ranged 7.3–58.8 (median 16.4); arms were
interleaved by seed so drift spreads evenly.

### 5.2 — solve wall (s) and final placement score, per seed (gate config)

| arm | s0 | s1 | s5 | s6 | s7 | **median** | loss med (viol) |
|---|---|---|---|---|---|---|---|
| baseg (upstream) | 6.8 | 17.9 | 11.3 | 10.7 | 12.0 | **11.3** | 52.90 (28) |
| b8bestg | 70.9 | 63.6 | 61.0 | 126.4 | 73.8 | **70.9** | 50.00 (28) |
| b8unifg (control) | 80.0 | 34.6 | 67.8 | 191.2 | 51.1 | **67.8** | 52.19 (28) |
| b8sampleg | 59.7 | 50.1 | 45.4 | 82.3 | 40.9 | **50.1** | 49.42 (28) |
| b64bestg | 105.9 | 75.0 | 1875.8 | 114.3 | 87.7 | **105.9** | 50.37 (28) |
| b64sampleg | 56.3 | 66.7 | 2691.5 | — | — | **66.7** | 45.81 (31) |
| b512bestg | 204.4 | 135.3 | — | — | — | **169.8** | 49.39 (28) |

Final violation counts are 28 everywhere (the whole-graph viol on a
large-stages-only run is dominated by the never-run medium/small stages) —
the discriminating statistic is the per-stage loss, §5.4. The seed-5 N=64
walls (31 and 45 min) are real, not a fluke: that bathroom rejects most
large-furniture applies, so the N× invalid-apply allowance is spent on
expensive failed spawns every step (§7).

**The today-anchor** (`results_full/`, real fast_solve 100/40/5, all
stages): upstream wall **150–436 s, median 328 s** (5 seeds); stage split
median ≈ solve_small 44 %, solve_large 33 %, solve_medium 20 %. The
equal-budget datapoint (`results_eq/b8best_seed0`, steps ÷ 8): 69 s wall,
but only 33 objects placed vs the baseline's 71 — faster for the wrong
reason (8× fewer annealing decisions), the trap already documented in §7.
The quarter-schedule one-seed corroborations: `b8bestq` 22/22 stages lower
than `baseq` (loss 46.6 vs 49.4, wall 1683 s vs 55 s) — the shift is not a
large-stage artefact.

### 5.3 — where the batch's time goes (all gate seeds pooled)

| arm | attempts | ok | t_apply | t_eval | t_revert | ms/att |
|---|---|---|---|---|---|---|
| baseg | 146 | 58 | 27.1 s | 2.2 s | 1.2 s | 209 |
| b8bestg | 1484 | 503 | 295.6 s | 21.7 s | 28.6 s | 233 |
| b64bestg | 5955 | 1906 | 1769.9 s | 75.9 s | 350.5 s | 369 |
| b512bestg | 2873 | 2324 | 185.9 s | 84.3 s | 33.9 s | 106 |

- **apply is 61–90 % of every arm's probe cost** (baseline 90 %, N=512
  61 %); Addition alone is 93–99 % of apply time on every arm but N=512 —
  spawning the placeholder *is* the cost.
- So a **free scorer (replacing evaluate only) recovers 6 % (N=8) to 28 %
  (N=512)** of the batched arm's wall. The remaining 72–94 % is
  Blender-side state mutation that no scorer removes.
- If the **whole probe** were replaced by hypothetical-pose scoring (round
  2's restructure — score N poses against static geometry, never mutate
  state), the measured floors become: b8bestg 70.9 → ~9 s, b64bestg
  105.9 → ~10 s, b512bestg 169.8 → ~18 s (wall − probe, per-run medians)
  — i.e. **N=512 best-of costs about the same wall as today's upstream
  baseline**, and would land strictly lower losses (§5.4). That is the
  shape of the win the GPU could buy, and it is conditional on the
  restructure, not on the scorer alone.
- The node-impl profile (`results_profile/`, baseline arm): all registered
  constraint-impl time is **1.20 s of an 11.1 s solve** (~11 %), split
  even between the rooms impl and the general bindings — the numeric
  kernels round 2 ported are a minority even of *scoring* time in this
  scene at this scale.

### 5.4 — THE GATE: is the output distribution unchanged?

Per-seed final loss KS (a), pooled per-stage KS (b, anti-conservative —
flagged as such), paired-by-seed sign view (b2, the valid unit), and the
tie-quantised pooled variant at the round-2 scale (c, q=0.5; q=1.0
identical). Full tables: `results/analysis.txt`.

| arm | (a) D / p | (b) D / p | (b2) seeds one side | (c) p |
|---|---|---|---|---|
| b8bestg | .60 / .36 | .60 / .052 | **5/5 lower**, p=.031 | .052 |
| b8unifg (control) | .60 / .36 | .40 / **.42** | 4/5, mixed, \|Δ\|≤4 | **.42** |
| b8sampleg | .60 / .36 | .60 / .052 | **5/5 lower**, p=.031 | .052 |
| b64bestg | .60 / .36 | .80 / **.002** | **5/5 lower**, p=.031 | **.002** |
| b64sampleg | 1.0 / **.036** | 1.0 / **.000** | 3/3 lower | **.000** |
| b512bestg | 1.0 / .095 | 1.0 / **.002** | 2/2 lower | **.002** |

Reading:

- **The control passes.** Uniform pick is kernel-preserving by
  construction and the gate agrees: pooled p=0.42, per-seed medians small
  and both signs. The harness measures the idea, not itself.
- **Accept-best fails the gate at every N** — pooled p ≤ 0.002 at N ≥ 64,
  and the paired view is **all seeds, one side, p=0.031** at every N (the
  per-seed KS (a) has no power at n=5 vs 5, as expected). The shift is
  *toward lower placement loss* (Δmedian −2.5 to −12), tie-quantisation
  does not dissolve it (round 2's ~17 % tie ambiguity is two orders below
  these deltas), and the mechanism is visible in the annealer's own stats:
  **best-of-N accepts 10/10 of its real proposals (baseline 5/14)** —
  Metropolis is turned into near-greedy descent. It also fills the room
  faster (53 vs 37 objects at the quarter schedule).
- **Boltzmann-sample is not the neutral variant it was hypothesised to
  be.** At the annealer's temperatures (T₀=3.0, ×0.53/step) against
  loss-spreads of ~10–30 between batch members, `exp(-Δloss/T)` is so
  peaked that the "sample" is near-argmin: it fails the gate *harder* than
  best at N=64 (D=1.0, p<10⁻³, Δmedian −22.5), and its final violation
  counts are slightly **worse** (31 vs 28) — the resampled realization the
  annealer judges can regress from the batch score that picked it.
- A batch-selection that *uses the scores* is a new proposal kernel;
  Metropolis' detailed balance was only ever valid for the upstream
  first-applicable kernel. The only kernel-preserving pick is uniform,
  which is indistinguishable from baseline — and buys nothing.

## 6. Verdict

**KILLED — as "the same annealer, faster."** The brief's kill condition is
met and said plainly: **accept-the-best changes the annealing output
distribution** (all 5 seeds one-sided, pooled p ≤ 0.002 at N ≥ 64, D up to
1.0, un-rescued by tie-quantisation), and the second variant,
**Boltzmann-sample, changes it too** (it degenerates to near-best at the
annealer's own temperatures). For the goal this gate protects — keep the
generator's distribution, spend GPU on it — the round-2 number (47.95 M
candidates/s) **stays decorative**.

What the kill leaves standing (for `IDEAS.md`, not for this brief):

1. **Batched-best is a *different, better-per-step* algorithm, not a
   faster instance of the same one.** Every N, every seed, lower placement
   loss (median −2.5 to −12; −13 at the quarter schedule's full stage
   set). If a future round wants a *better* solver and is willing to
   re-validate it as a new design (its own acceptance rule, its own
   distribution), the direction is measured and promising — but that is a
   different proposal from "the annealer, batched", and its viol-count
   regression at N=64 sample (31 vs 28) is a warning that loss is not the
   whole story.
2. **The economics are apply-bound, not scoring-bound.** Even a free
   scorer recovers only 6–28 % of the batched arm's wall; apply (Blender
   placeholder spawning, 61–90 % of probe cost) dominates. The 48 M/s
   becomes relevant only if the whole apply→evaluate→revert probe is
   replaced by hypothetical-pose scoring against cached geometry — round
   2's restructure — which the floor projection puts at N=512 ≈ the
   baseline's wall (§5.3). That port is the real cost of the idea, and it
   is not a one-day change on this codebase.
3. **The upstreamable artefact is the inert knob, not a default change.**
   `patch/solver-batch.patch` lands `batch_size=1, batch_mode="best"` as
   gin-configurable parameters — behaviour-identical by default, validated
   by `scripts/check_patch.py` + `scripts/smoke_patch.py`. The
   scheduler-side knob (builder-ide's side) is one gin override,
   `SimulatedAnnealingSolver.batch_size = N`, exactly how
   `solve_steps_large` is already driven — a load knob: 1 under GPU
   contention, raised when idle (see `patch/README.md`).

## 7. Failures that stayed

- **The venv does not run Indoors out of the box** — it is the v2
  (procfunc) engine; `gin-config`, `scikit-learn`, `networkx`, `psutil`,
  `scikit-image` (+ small deps) are missing. Fixed read-only via
  `pip install --target lab5/pylibs`; documented in §3.
- **`init.apply_scene_seed` parses the seed as hex** — an int argument
  crashes (`int(seed, 16)`); the driver passes the seed as a string.
- **The upstream floor-plan solver crashes on some seeds** — degenerate
  shapely polygon (`A linearring requires at least 4 coordinates`) on
  seeds 2, 3, 4 (probed). All arms use the five surviving seeds;
  `probe_seeds.sh` re-finds them. Not worked around — it is upstream's
  bug, reported here.
- **Equal-budget batching is a trap**: scaling steps by 1/N keeps the
  candidate *budget* but collapses the annealing *decisions* (8× fewer
  accepted moves — 33 objects placed vs the baseline's 71, 69 s vs 328 s
  for the wrong reason). Same-steps is both the natural upstream change
  and what a free scorer buys; kept as a one-run datapoint (`results_eq/`).
- **A suspected upstream bug in `Deletion.revert` was the first seat's own
  misreading** — the broken-looking tail belongs to `reassignment.py`'s
  `RelationTargetChange`. `Deletion.revert` is fine; no workaround shipped.
- **The first draft of the upstreamable patch called `self._revert(...)`,
  which does not exist** (upstream has `_move` but no `_revert`).
  `py_compile` passes that bug; the runtime would not. Caught by writing
  `scripts/check_patch.py` (static self-attr resolution over the patched
  method) and fixed to `move.revert(state)`; `scripts/smoke_patch.py` now
  also *runs* the patched method on stub moves (lexicographic best,
  cached-vs-rescored apply paths, invalid-budget cap).
- **The inherited analysis script crashed in its own gate section** —
  `sum(numpy_scalar)` is a TypeError — and its Cliff's δ was silently
  wrong (`(#{a>b}+#{a<b})/(n·m) − 1` is minus-the-tie-fraction and returns
  0 at *both* extremes). Both fixed; the gate tables in §5.4 are from the
  corrected script. The chain that was supposed to run the analysis never
  got there on its own: its `pgrep -f "python3 scripts/sweep.py"` wait
  matched the *launcher shell's* argv (which still contained that string
  after the sweep had exited) — the chain was deadlocked on a stale
  process name. Killed the inert launcher; the chain then ran the profile
  and analysis unmodified.
- **The gate's first design over-ran the day**: the quarter schedule
  (25/10/5, all stages) costs ~28 min per N=8 batched run; the sweep was
  re-centred on the large stages at 15 steps (identical schedules across
  arms, the dominant real placement work), with the quarter kept as a
  one-seed corroboration. The price of wide batches showed up anyway on
  seed 5: its bathroom rejects most large-furniture applies, so N=64 arms
  spent their N× invalid-apply allowance on failed spawns every step
  (31–45 min per run, vs 1–2 min on the other seeds). That bimodality is
  a property of the N× allowance design — worth knowing before anyone
  upstreams it: the allowance, not N, should be capped.
