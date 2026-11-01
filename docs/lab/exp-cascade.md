# EXP — lab-cascade: making small and low-precision models act like big ones, with decision models in the loop

**Date:** 2026-10-31, completed and extended 2026-11-01 · **Seat:** lab-cascade (`~/lm-wt/lab-cascade`) · **Box:** NVIDIA Jetson AGX Thor (aarch64, 122 GB unified, Blackwell GPU, CUDA 13.2), driver 595.78

**Casey's intuition (the thing to test):**
> "Decision models can be the key to making an FP4 model act like a higher-precision model,
> with quick back-and-forths to the decision model for cleaning up what was less precise.
> Experiment widely, with different decision models. … A system could use the larger decision
> models to calibrate and adapt the harnesses and settings (and for Liquid models, the internal
> state) so that the smaller and less precise models can be as good at specific tasks as the
> bigger and slower models, especially with cloud LLM calls periodically assessing and improving
> the elements around the model's loop."

This file is the experiment: the hypotheses, the setup, the matrices, the curves, how to
reproduce, and a verdict per hypothesis — plus a ranked list of what to build into builder-ide.

---

## 0. The short answer

**The shape of the answer, from E1 and the joules pass (both complete):**

1. **Precision is not a quality lever on this box.** Over 27 paired precision comparisons within
   a model size, **not one** is distinguishable from another (smallest p = 0.18), and on T1 all
   nine cells score *identically* to the fourth decimal. So the premise "a decision model in the
   loop can clean up what was less precise" has no referent here: **there is nothing about the
   quantisation to clean up.** The loop's value has to come from somewhere else, and it does.
2. **Precision is not a speed lever either.** Q4 is **1.30–1.51× slower** than BF16 for the two
   smaller models, and it costs **more joules per decision** (the 600M: 0.873 J at Q4 vs 0.581 J
   at BF16). 4-bit buys **memory** on this stack; it costs latency and energy. That is the same
   lesson IDEAS.md already recorded for FP4 on the tensor cores — "the dtype exists, the path
   does not" — now shown for the quantised *decision* path end to end.
3. **Size decides, precision does not, and the middle model wins.** d1-2B scores 0.985 on T1
   against d1-3B's 0.880 (22 discordant items to 1, p = 6×10⁻⁶) and the 600M's 0.415. The 3B
   is not only worse, it is *less reproducible*: its confidence moves by 1.6 % between two
   designs and 4 of its 200 predictions flip, while the 2B's are bit-identical.
4. **The loop works — but on the model's errors, not on its precision, and only where the
   proposer's confidence is honest.** A 600M-first cascade on T1 is not weak, it is **empty**:
   the gate fires on **0 of 200 items**, so even a perfect checker would add nothing. The same
   gate on the 2B catches **3 of 3 errors with 4 % of the traffic**. The difference is not the
   checker and not the task; it is the **proposer**.
5. **The loop's value is task-specific, and the reason is measurable in advance.** The *ceiling*
   of any loop — the gate plus a perfect checker — is computable from the E1 rows alone:
   1.000 on T1 (from 0.985), 0.706 on T2 (from 0.667) and 0.892 on T3 (from 0.450). On T2 the
   gate catches only 2 of the 2B's 17 errors, so **no checker can help there**; on T3 it catches
   53 of 66 but escalates two-thirds of the traffic. Which checker to buy, and whether to buy
   one at all, is decided by the gate's behaviour, not by the checker's quality.
6. **The cloud's job is to author the options, not to answer.** The server's decision endpoint
   cannot generate tokens at all (`/v1/chat/completions` answers 501), so the big d1 model
   *selects* among candidate harnesses rather than writing them, and the cloud LLM's edits are
   kept only when the paired score improves — the tiles contract applied to the harness.
7. **The big model's harness pick does not transfer down — it corrupts.** Letting d1-3B BF16
   choose the small model's wording and exemplars never helps (the oracle wording does not
   either) and on the 600M-defects cell it collapses 0.7308 → 0.1538 (p = 6×10⁻⁵). The
   exemplars teach the small model the big model's habits, and the small model cannot imitate
   them (§5, H6).
8. **Errors compound through the world, not through the prompt — and a drift-triggered
   keyframe beats a fixed one at the same spend.** On a sequential patrol task built from the
   same worlds, the 600M is at 0.98 with a clean history and **0.05** once its log carries one
   wrong action — and with the log removed from the prompt its 180 choices are *identical*.
   The wrong *move* corrupts the world; the log is ignored. A drift-triggered BF16 keyframe
   (τ tuned to the proposer's confidence range) reaches **0.8667 at 21.7 % BF16 spend**, where
   the fixed every-5 schedule gets 0.7444 at 20 % (§7, E5).
9. **The derivative is not faster than the level.** On the recorded d1 traces, a gate on
   d/dt of confidence or of disagreement fires **0 ticks earlier (median)** than the level
   gate with hysteresis on the events both catch; it buys catch only by escalating most of
   the traffic (§8, TIME-FIRST).

**The rest of this file is the evidence.**

---

## 1. Hypotheses

Each is stated so that a measurement can kill it.

| # | Hypothesis | Killed by |
|---|---|---|
| **H1** | **Precision buys quality.** A d1 model at Q4 makes more mistakes on the decision tasks than the same model at BF16, so a decision model in the loop can "clean up what was less precise". | The same model at 4/8/16 bits scoring the same accuracy on the same items. |
| **H2** | **Precision buys speed.** The 4-bit weights are faster on the Thor, so the loop can afford to ask them often. | Q4 measuring *slower* than BF16 at the same model size. |
| **H3** | **Size, not precision, is what decides.** A bigger d1 is a better decider than a smaller one on these tasks, and precision is a red herring. | A smaller model beating a bigger one, or equal accuracy across sizes. |
| **H4** | **A cleanup loop recovers the gap.** A small/low-precision proposer plus a bigger/higher-precision/cloud checker, escalating only on low confidence, closes the gap to the big model. | The loop's accuracy not exceeding the proposer alone, or the escalation rate being too high to pay for itself. |
| **H5** | **Confidence is a usable escalation gate.** The proposer's own confidence predicts its errors, so "escalate when unsure" selects the right items. | Errors concentrated in the *high*-confidence band, or a low-confidence band that is no worse than average. |
| **H6** | **The big model can calibrate the small one.** Letting d1-3B BF16 choose the small model's harness (wording, exemplars, gate) offline, then letting the small model run alone, brings it close to the big model. | The calibrated small model no better than the uncalibrated one, or the oracle-best wording no better either (i.e. the wording is not the lever). |
| **H7** | **The Liquid internal state is a lever.** A cached prefix state per task (the runtime's prompt cache) cuts the cost of a decision without changing the answer. | The cache not reused (zero cached prompt tokens), or no latency change. |
| **H8** | **The cloud improver compounds.** A cloud LLM reading the loop's failures and proposing harness edits — kept only if the paired score improves — walks the small model up over rounds. | The curve flat or falling, i.e. the cloud's edits do not survive the paired test. |
| **H9** | **Precision keyframes resync a drifting sequence.** Where state carries across steps, cheap Q4 steps with periodic BF16 keyframe steps (every N, or drift-triggered) recover much of the full-precision quality at a fraction of the cost. | Keyframed accuracy not rising with keyframe density, or the drift trigger not separating good states from bad. |
| **H10** | **The rate gate fires first.** Escalating on d/dt of confidence or of disagreement catches a model's misreadings earlier than the level gate, buying time for the checker. | The rate gate not firing earlier than the level gate on shared events. |

---

## 2. Setup

### 2.1 The models

Nine cells: 3 sizes × {Q4_K_M, Q8_0, BF16}. All weights are official Liquid AI Hugging Face
artefacts except one, which Liquid does not publish — see
[`models-inventory.md`](models-inventory.md) for the file-by-file list, the licence
and the disk accounting.

Licence, re-verified against the Hugging Face API on 2026-10-31 (not copied from the
prior seat's notes): all three repos report `license: other`, `license_name: lfm1.0`
— the **LFM Open License v1.0** — and none is gated.

| | Q4_K_M | Q8_0 | BF16 |
|---|---|---|---|
| d1-omni-600M | **local quant** from Liquid's F16 (Liquid ships no 600M Q4) | official | official |
| d1-2B | official | official (already on the box) | official |
| d1-3B | official | official (already on the box) | official |

**Disk:** 209 GB free before the downloads, 194 GB free after — **added: 15,537,197,216 bytes
(15.54 GB, 14.47 GiB) to `~/models/`**, file by file in
[`models-inventory.md`](models-inventory.md). The venv and the build tree live in
`~/lm-wt/lab-cascade` and are excluded from that figure. The box is shared and other seats
keep adding to it, so the *current* free space is **182 GB** (2026-10-31T16:52) — that number
moves; the number above is this seat's own delta and is the one that is reproducible.

### 2.2 Serving

The same llama.cpp build that already serves last-mile's d1 models —
`~/llama.cpp-upstream/build-up/bin/llama-server` (0.8.0-dev, build 50, commit 2e0d86b) — over
`POST /v1/systemone`, the protocol last-mile's agents and the TypeSafe Jev provider both
speak. This lab starts and stops **its own** servers on **its own** ports (8140+ E1, 8160+
joules, 8180+ E2, 8190+ E3, 8200+ E4, 8240+ E3c) and touches no other service on the box.

The vision projector is **not** loaded: all three tasks are text-only, and the server answers
`/v1/systemone` correctly with no projector (verified separately). One less variable.

`llama-quantize` was built from the same source tree into
`build/quantize/` (CPU-only, no system install) to make the 600M Q4 that Liquid does not ship.

**One fact about this build that shapes E3:** the d1 server exposes **only**
`POST /v1/systemone`. `/v1/chat/completions` and `/completion` both answer **501 Not
Implemented**. The big d1 model is therefore a *decision* model too: it can score a
candidate, but it cannot write one. E3 is built accordingly — the big model **selects**
the harness, it does not author it.

### 2.3 The three tasks

Each task has ground truth computed **from the data, never from a model**, and every cell
answers the *same* items, so every pair of cells is a paired comparison.

| | task | items | ground truth | where it comes from |
|---|---|---|---|---|
| **T1** | last-mile's paired game scenes | 200 | hide / advance / scout, by the stated rule | last-mile's own scene generator and rule (`~/last-mile/docs/research/poc/thor/e4b.py`), reimplemented in `scripts/tasks.py`; the "facts" condition (plain-language facts, no grid), because that is the condition last-mile measured |
| **T2** | the critic's defect classification | 51 | the planted defect class, or `none` | builder-ide's `core/critic/reference-set.json`: 21 image-layer members with a seeded defect + 30 clean bases as the `none` control. The state is **builder-ide's own critic measurements** (`core/critic/checks.py`), imported read-only |
| **T3** | a tile-choice task | 120 | the uniquely best scripted tile | a small simulated rig game: a context, K=5 scripted tiles, a payoff rule per tile. A case is kept only when the best tile is **strictly** better than every other, so the ground truth is never ambiguous. The options are tiles, the model is the local decision model, the score is the play's outcome — the tiles system's shape |
| **T4** | the patrol task (E5 only) | 6 worlds × 30 ticks | the same `action` rule, per tick, at the live state | the T1 worlds played as episodes: each tick the model sees the current facts plus a rolling K=5-tick log of what was chosen and whether an enemy was visible, and its choice *moves the agent*; enemies move on a per-world seeded script identical across arms, so arms differ only through their own actions |

**The ground-truth rule is last-mile's, verbatim** — `world()`, `los()`, `bfs()` and
`truth()` in `scripts/tasks.py` reproduce `e4b.py`'s behaviour, including the tie rule
(horizontal offsets win ties) and the 6-cell/10-step thresholds. The "facts" state string is
the one `e4b.py` builds. So T1 is last-mile's task, not a lookalike.

**Class balance — the baselines that matter:**

| task | majority class | uniform chance |
|---|---|---|
| T1 scenes (`action`) | 0.415 (83/200 advance) | 0.333 |
| T2 defects | **0.706** (36/51 are `none`) | 0.100 |
| T3 tiles | 0.250 (30/120 `repair_here`) | 0.200 |

T2's majority baseline is high and its classes are tiny: `black_frame` 3, `noise_fireflies`
4, and 2 each of `missing_object`, `holes`, `texture_swap`, `floating_object`. A model that
says `none` for everything scores 0.706 on T2 and 0 on every real defect class. That is the
number the defect task has to be read against.

### 2.4 The design that makes the numbers comparable

**What happened first.** The first E1 pass kept all nine ladder cells resident at once and
interleaved them item by item. With the seed sweep also on the box, the 122 GB of unified
memory filled and the Thor rebooted mid-run. The memory rule now in force says: at most
**one** model server per seat at a time, every heavy step under
`flock ~/lm-wt/heavy.lock`, at least 25 GB of free memory left after the step's peak, and
the step's peak recorded beside its numbers.

So the ladder was re-run as **E1b**: one cell at a time. The first pass is kept as **E1a**.

| | E1a (interleaved) | E1b (sequential) |
|---|---|---|
| servers resident | 9 at once | **1 at a time** |
| order | randomised within each item block | one cell fully, then the next |
| tasks | scenes + defects | scenes + defects + **tiles** |
| item order | shared block order | each cell's own seeded permutation |

What is *preserved* is the part the science needs: **every cell answers every item**, so any
two cells are a paired comparison (McNemar on the discordant pairs), not two independent
accuracies. What is *lost* is the guarantee that drift hits every cell equally — and that is
handled by measurement rather than by construction:

1. each cell walks the items in its own seeded random order, so a busy stretch of the sweep
   lands on a random subset of each cell's items;
2. the box's state is sampled every 25 items and the latency is published as a range
   (p50/p90/p95), never as a single mean, with the load range beside it (IDEAS.md rule 4);
3. **E1a and E1b are two different designs of the same experiment.** Where they cover the
   same task, two designs have to agree on every cell's accuracy. That agreement *is* the
   drift control.

Every cell is warmed before it is timed (the GPU idles at 315 MHz and ramps to 1575 MHz in
~1.4 s; a cold reading is 2.6× slow — IDEAS.md rule 3).

The whole run is reproducible from three seeds (`seed`, `scene_seed_base`, task seed) and
three **case digests** that hash the whole item set:

```
scenes  4294be06e06326f6
tiles   a7cb4bf3a4745c93
defects 1914cf7ce0dc1bb6
```

### 2.5 The prior art this repeats or contradicts

| Source | What it said | How this lab relates |
|---|---|---|
| last-mile **D62** (2026-10-29) | Over 200 fresh paired scenes, d1-2B was right on `action` 96% vs d1-3B 84% (26 vs 2 discordant); d1-2B keeps 91% coverage at 1.00 accuracy at conf ≥ 0.70; the 600M's confidence is uncalibrated, so a 600M-first cascade is rejected | T1 repeats the same measurement; E1b checks it on fresh scenes |
| last-mile **D71** | Escalate unsure answers to a second model: d1-2B alone 0.96, with clef-flash 0.98, 4% escalated, +25 ms; "two different models are rarely wrong together (2/200)" | E2 is this loop, with the checkers the brief names, on three tasks |
| last-mile **D62** | "Repeated calls to one model are deterministic, so self-consistency votes are useless" | So E2's checkers are always a *different* model or a different precision — never a second sample of the same one |
| last-mile **E4c** | On the "facts" condition: d1-3B 0.97 on `action`, the 600M 0.40, Jev (cloud) 1.00 | T1's facts state is the same one; the numbers below should land near these |
| builder-ide **IDEAS.md** (R1) | FP4 is a measured no on this stack: 13.69 TFLOPS, *slower* than dequantise-to-BF16-then-multiply | Predicts H2's outcome before the run: 4-bit is a memory lever here, not a speed lever |
| builder-ide **IDEAS.md** (rule 4) | On a shared box, interleave the variants and publish ranges | Adopted; §2.4 |
| builder-ide **IDEAS.md** (rule 6) | Joules: subtract the idle baseline; if the result is negative, report the wall time | Adopted; §E1 |

---

### 2.6 Which library concepts this lab tests, and where

The brief asks for the *concrete* routing and gating mechanisms from
`library-small-acts-big.md` to be used as arms, and for the *adaptation* claims to be treated
as hypotheses. The library has 80 concepts; these are the ones with a mechanism that can be
built and measured on this box. The numbers are in §4–§6.

| library | concept | what it would need | where it is tested |
|---|---|---|---|
| **#1** | calibrated confidence gating | a confidence that ranks errors | §3.6, §4.7 (Brier + reliability per arm) |
| **#2** | confidence-tiered escalation | three tiers, not one gate | §4.5 — the **tiered** arm |
| **#3** | local precision promotion (swap FP4→FP16 on ambiguity) | the same weights at two precisions | §4.3 — the **2B-BF16** arm; §4.5's middle tier |
| **#4** | cascaded edge tier (600M→3B) | a small model first, a big one for the unsure | §4.4 — the **3B-BF16** arm (600M proposes, 3B checks) |
| **#5** | FP4 noise rejection via an external decision head | a cloud checker | §4.3 — the **jev** / **jev-noul** arms; §4.5's bottom tier |
| **#6** | large-model state calibration | the big model picks the small model's harness | §5 — E3 |
| **#7** | cloud as prompt/weight-bias tuner | the cloud proposes harness edits | §6 — E4 |
| **#11** | single-forward-pass decision head | the server's own `/v1/systemone` path | §2.2, §3 |
| **#14** | hysteresis barrier (split bounds + temporal window) | a gate with two bounds and state | §4.6 — the **hyst** arm |
| **#15** / **#62** | Brier-score calibration tracking, Brier-gated loops | a score to gate on | §4.7 — the Brier score and reliability curve, per arm |
| **#17** | intent/entity cache | a cached prefix state per task | §5.2 — E3c |
| **#19** | Front Desk / Decision Maker / Back Office (role tiering) | the roles separated by cost | §4 — the arms are the tiers |
| **#80** | Aider: cache-prefix discipline, tile authorship | the harness written in pieces | §6 — E4's edits are kept win or lose, like tiles |
| **ADDENDUM** | precision keyframes (Casey, 2026-10-31) | state that carries across steps | §7 — E5, the T4 patrol task |
| **TIME-FIRST** | the rate gate (Casey, 2026-10-31) | d/dt of confidence or of disagreement | §8 — on the recorded d1 traces |

The rest of the library is either a metaphor with no data structure (attractors, solitons,
crystals, growth cones) or a mechanism this box cannot exercise (Cranelift, WASM synthesis,
RDMA, multi-LoRA). The library's own verdict — *"the plumbing is specified, the adaptation is
asserted"* — is treated here as the hypothesis under test, not as a finding.

**The adaptation claims this lab can actually kill**, because they are the ones with numbers
attached in the corpus: the library's only measured evidence is *negative* (MiniMax: pixel
distillation and consistency-only critics produce confident ghosts). §3.6 is the direct test of
that failure mode on a decision model — a confident model that is wrong — and §4.7 measures it
as a Brier score per arm.

---

## 3. E1 — the precision ladder: three sizes × {Q4, Q8, BF16}

**Box (pass B):** 2026-10-31T14:09:45-0800 · 6.8.12-1021-tegra · aarch64 · 14 cores ·
load [5.51, 5.81, 6.19] · mem avail 116 GB · NVIDIA Thor, 595.78, GPU 0 %
**Case digests:** scenes `4294be06e06326f6` · tiles `a7cb4bf3a4745c93` · defects `1914cf7ce0dc1bb6`
**Design:** one model server at a time; one cell after another; every cell answers every item,
each in its own seeded random order; the box's state sampled every 25 items; the latency
published as a range.

### 3.1 The matrix

**T1 — last-mile's paired scenes (200 items, the `action` question)**

| cell | accuracy | 95% CI | p50 ms | p90 ms | mean conf | enemy_visible | **action** | beacon_bearing | beacon_reachable |
|---|---|---|---|---|---|---|---|---|---|
| d1-omni-600M-Q4 | 0.4150 | [0.349, 0.484] | 41.91 | 46.79 | 0.973 | 0.680 | **0.415** | 0.210 | 0.450 |
| d1-omni-600M-Q8 | 0.4150 | [0.349, 0.484] | 37.53 | 41.54 | 0.955 | 0.690 | **0.415** | 0.200 | 0.745 |
| d1-omni-600M-BF16 | 0.4150 | [0.349, 0.484] | 27.78 | 31.43 | 0.959 | 0.675 | **0.415** | 0.185 | 0.740 |
| d1-2B-Q4 | 0.9850 | [0.957, 0.995] | 129.17 | 144.48 | 0.876 | 0.990 | **0.985** | 0.745 | 0.995 |
| d1-2B-Q8 | 0.9850 | [0.957, 0.995] | 114.78 | 129.05 | 0.892 | 1.000 | **0.985** | 0.725 | 1.000 |
| d1-2B-BF16 | 0.9850 | [0.957, 0.995] | 99.00 | 104.85 | 0.894 | 1.000 | **0.985** | 0.715 | 1.000 |
| d1-3B-Q4 | 0.8800 | [0.828, 0.918] | 134.25 | 142.62 | 0.630 | 0.970 | **0.880** | 0.615 | 0.985 |
| d1-3B-Q8 | 0.8800 | [0.828, 0.918] | 183.89 | 255.25 | 0.637 | 0.975 | **0.880** | 0.590 | 0.990 |
| d1-3B-BF16 | 0.8800 | [0.828, 0.918] | 146.30 | 153.36 | 0.642 | 0.975 | **0.880** | 0.595 | 0.990 |

**T2 — the critic's defect classification (51 items; the majority class is 0.706)**

| cell | accuracy | 95% CI | p50 ms | mean conf | macro-F1 |
|---|---|---|---|---|---|
| d1-omni-600M-Q4 | 0.6667 | [0.530, 0.780] | 34.63 | 0.747 | 0.267 |
| d1-omni-600M-Q8 | 0.6863 | [0.550, 0.797] | 32.33 | 0.731 | 0.210 |
| d1-omni-600M-BF16 | 0.6667 | [0.530, 0.780] | 21.76 | 0.743 | 0.171 |
| d1-2B-Q4 | 0.6667 | [0.530, 0.780] | 90.40 | 0.840 | 0.474 |
| d1-2B-Q8 | 0.6667 | [0.530, 0.780] | 78.19 | 0.823 | 0.483 |
| d1-2B-BF16 | 0.6667 | [0.530, 0.780] | 42.94 | 0.823 | 0.483 |
| d1-3B-Q4 | 0.5098 | [0.377, 0.641] | 133.92 | 0.719 | 0.404 |
| d1-3B-Q8 | 0.4902 | [0.359, 0.623] | 118.95 | 0.716 | 0.289 |
| d1-3B-BF16 | 0.4902 | [0.359, 0.623] | 59.47 | 0.715 | 0.289 |

**T3 — the tile-choice task (120 items; the majority class is 0.250)**

| cell | accuracy | 95% CI | p50 ms | mean conf |
|---|---|---|---|---|
| d1-omni-600M-Q4 | 0.2750 | [0.203, 0.361] | 25.53 | 0.466 |
| d1-omni-600M-Q8 | 0.2667 | [0.196, 0.352] | 23.58 | 0.347 |
| d1-omni-600M-BF16 | 0.2583 | [0.188, 0.343] | 16.13 | 0.354 |
| d1-2B-Q4 | 0.4500 | [0.364, 0.539] | 57.71 | 0.558 |
| d1-2B-Q8 | 0.4500 | [0.364, 0.539] | 51.98 | 0.547 |
| d1-2B-BF16 | 0.4417 | [0.356, 0.531] | 32.47 | 0.545 |
| d1-3B-Q4 | 0.2917 | [0.218, 0.378] | 83.62 | 0.387 |
| d1-3B-Q8 | 0.3333 | [0.255, 0.422] | 72.62 | 0.391 |
| d1-3B-BF16 | 0.3250 | [0.248, 0.413] | 44.53 | 0.389 |

Every cell answered every item: **0 errors in all 27 cell×task cells.**

### 3.2 Precision changes nothing. At all.

The paired test over the 27 precision-vs-precision pairs *within* a model size
(Q4 vs Q8, Q4 vs BF16, Q8 vs BF16, for each of the three sizes, on each task):

| | pairs | pairs with any discordant item | pairs significant at p < 0.05 |
|---|---|---|---|
| **within a model size (precision vs precision)** | 27 | 16 | **0** |
| **between model sizes** | 81 | — | **50** |

The smallest p-value over all 27 precision pairs is **0.18** (d1-3B Q4 vs Q8 on tiles, 7
discordant one way and 2 the other); the next is 0.34 (the same task, Q4 vs BF16, 7 vs 3). Over
all three sizes and all three tasks, **not one precision pair is distinguishable from another.**

The accuracy numbers are not merely close — they are *identical to the fourth decimal* on
T1 for all nine cells (0.4150 ×3, 0.9850 ×3, 0.8800 ×3). On T2 and T3 the cells differ by
one or two items out of 51 and 120, and never significantly.

> **H1 is killed.** There is no quality difference between a d1 decision model at 4 bits and
> at 16. Quantizing d1 costs nothing — so **there is nothing for a decision model to clean
> up.** The premise "clean up what was less precise" has no referent on this hardware.

### 3.3 The two passes agree on accuracy — and, for the cells that win, on everything

Pass A ran all nine cells resident at once, interleaved, with the seed sweep on the box
(load 15–27, GPU 96 %). Pass B ran one cell at a time on a quiet box (load 5.5, GPU 0 %).
They share 18 cell×task pairs:

**18 of 18 accuracy figures identical to the fourth decimal.**

This is the drift control (§2.4). Two completely different designs — different ordering,
different concurrency, different box load — produce the same number for every cell on every
task they share. The accuracy figures are properties of the model, not of the box.

The *latencies* are of course not comparable across passes (pass A was 2–4× slower because
the GPU was 96 % busy), which is exactly why the latency claim below is made **within**
each pass, on the ratios.

**But the confidence is a different matter, and the difference is not spread evenly.** Comparing
the per-item confidences of the two passes on T1:

| cell | mean \|Δ confidence\| | max | predictions that flipped |
|---|---|---|---|
| d1-omni-600M-Q4 | **0.00000** | 0.0000 | 0 |
| d1-omni-600M-Q8 | 0.00001 | 0.0020 | 0 |
| d1-2B-Q4 | **0.00000** | 0.0000 | 0 |
| d1-2B-BF16 | **0.00000** | 0.0000 | 0 |
| d1-3B-Q8 | 0.00881 | 0.0739 | 0 |
| d1-3B-Q4 | **0.01563** | 0.0821 | **4 of 200** |

The 600M and the 2B are **bit-identical** across the two designs — same predictions, same
confidences, to the last bit. The **3B is not**: its confidence moves by ~1.6 % on average, and
4 of its 200 predictions flip (two right→wrong, two wrong→right, so the accuracy happens to
come out the same). The four flips are near-ties, and they are the items where the 3B's
confidence is lowest:

| item | pass A | pass B |
|---|---|---|
| scene-1014 | hide (wrong), conf 0.1011 | scout (**right**), conf 0.0735 |
| scene-1041 | scout (right), conf 0.3038 | hide (wrong), conf 0.2420 |
| scene-1141 | advance (right), conf 0.0091 | scout (wrong), conf 0.0444 |
| scene-1142 | advance (wrong), conf 0.1547 | scout (**right**), conf 0.1115 |

The mechanism is not mysterious: pass A had nine cells resident and batched concurrently, so the
floating-point reduction order — and therefore the last bits of the logits — differed. The 2B
and the 600M are far enough from their decision boundaries that the perturbation never changed
anything. The 3B is not.

> **This matters for a gate, not just for a benchmark.** A confidence gate is a function of the
> confidence, so a confidence that moves by 1.6 % between two runs moves *which items the gate
> escalates*. The cells whose confidence is bit-stable are exactly the ones worth gating on, and
> the biggest model is the least reproducible one. This is a second, independent reason not to
> put d1-3B in the gate.

### 3.4 Precision is not a speed lever either — it is a slow-down

Within pass B (quiet box, the better conditions), the ordering by p50 on T1:

| model | BF16 | Q8 | Q4 | Q4 vs BF16 |
|---|---|---|---|---|
| d1-omni-600M | **27.78 ms** | 37.53 ms | 41.91 ms | Q4 is **1.51× slower** |
| d1-2B | **99.00 ms** | 114.78 ms | 129.17 ms | Q4 is **1.30× slower** |
| d1-3B | 146.30 ms | 183.89 ms | **134.25 ms** | Q4 is 0.92× (Q8's p90 of 255 ms shows this cell ran into contention) |

The same ordering holds in pass A, under load: the 600M's Q4 was 1.33× BF16 and the 2B's
was 1.15× BF16.

> **H2 is killed.** For the two smaller d1 models, 4-bit weights are **slower** end to end
> than 16-bit ones. The decision path is not matmul-bound: it is bound by the decision head,
> the launch overhead and the memory traffic of the state, none of which the quantisation
> touches. 4-bit buys **memory**, and on this stack it buys memory at the cost of latency.
>
> This is the same lesson builder-ide's IDEAS.md already recorded for FP4 ("the dtype exists,
> the path does not"), now shown for the *quantised* d1 decision path end to end.

### 3.5 Size, not precision, decides — and 2B, not 3B

On T1, d1-2B (0.985) beat d1-3B (0.880). The paired test: **22 items the 2B got right and
the 3B got wrong, against 1 the other way** (McNemar p = 6×10⁻⁶). That is an independent
replication of last-mile's **D62** (0.96 vs 0.84, 26 vs 2 discordant over 200 fresh paired
scenes) — a different seat, a different day, the same ordering and a similar margin.

The per-question columns say *why*: on the sub-questions the 2B is at or near ceiling
(`enemy_visible` 0.99–1.00, `beacon_reachable` 0.995–1.00) while the 3B is *worse* at the
hardest one (`beacon_bearing` 0.590–0.615 vs the 2B's 0.715–0.745). The 3B is not a better
reasoner here; it is a different, worse one. And the 600M is at the majority-class baseline
(0.415 = the 83/200 `advance` rate) with `beacon_bearing` at 0.185–0.210 — **below the
0.25 chance level**.

On T2 every cell is **at or below the 0.706 majority baseline**, and the macro-F1 tells the
real story: 0.17–0.48. The models do not read the critic's measurements as defect classes at
all; they mostly answer `none`. The FP/FN per class:

| class | support | 600M-Q4 F1 | 2B-Q4 recall | 3B-BF16 recall | 600M-Q4 recall |
|---|---|---|---|---|---|
| none | 36 | 0.79 | 0.694 | 0.472 | 0.889 |
| black_frame | 3 | 0.00 | **1.000** | **1.000** | 0.000 |
| noise_fireflies | 4 | 0.25 | **1.000** | **1.000** | 0.250 |
| holes | 2 | 0.50 | 0.500 | 0.000 | 0.500 |
| missing_object | 2 | 0.00 | 0.000 | 0.000 | 0.000 |
| texture_swap | 2 | 0.00 | 0.000 | 0.000 | 0.000 |
| floating_object | 2 | 0.00 | 0.500 | 0.500 | 0.000 |

Three of the six real defect classes (`missing_object`, `texture_swap`, and `holes` for the
3B) are **never** detected by any cell — the 2B finds `black_frame` and `noise_fireflies`
perfectly but pays for it with 12 false `floating_object` positives (precision 0.077).

> **H3 is confirmed, and refined.** Size decides, precision does not — and **the middle
> model wins.** The biggest model is not the best model.

### 3.6 The confidence gate: perfect for the 2B, useless for the 600M

This is the table that decides Casey's intuition. In each confidence band: how many items,
how many were right, and what share of *all* the model's errors fell in that band.

**d1-2B-Q4 on T1**

| confidence | n | accuracy | wrong | share of all errors |
|---|---|---|---|---|
| [0, 0.5) | 4 | 0.250 | 3 | **100 %** |
| [0.5, 0.7) | 14 | **1.000** | 0 | 0 % |
| [0.7, 0.9) | 62 | **1.000** | 0 | 0 % |
| [0.9, 0.995) | 120 | **1.000** | 0 | 0 % |

**Every single error the 2B makes is in the bottom confidence band. Above conf 0.5 it is
exactly right, 196 items out of 196.** A gate at conf < 0.5 catches **100 % of the errors
with 2 % of the traffic.**

**d1-3B-Q4 on T1**

| confidence | n | accuracy | wrong | share of all errors |
|---|---|---|---|---|
| [0, 0.5) | 71 | 0.718 | 20 | 83 % |
| [0.5, 0.7) | 33 | 0.970 | 1 | 4 % |
| [0.7, 0.9) | 49 | 0.939 | 3 | 13 % |
| [0.9, 0.995) | 47 | **1.000** | 0 | 0 % |

Informative, but expensive: you must escalate **35 % of the items** to reach 83 % of the
errors, and the escalated items are still 72 % correct.

**d1-omni-600M-Q4 on T1**

| confidence | n | accuracy | wrong | share of all errors |
|---|---|---|---|---|
| [0.5, 0.7) | 4 | **0.000** | 4 | 3 % |
| [0.7, 0.9) | 7 | **0.000** | 7 | 6 % |
| [0.9, 0.995) | 127 | 0.339 | 84 | **72 %** |
| [0.995, 1.01) | 62 | 0.645 | 22 | 19 % |

**The 600M's confidence is useless as a gate.** Its mean confidence is 0.973 with 0.415
accuracy — it is confidently wrong. **72 % of its errors sit in the [0.9, 0.995) band**,
where it looks *more* confident than anywhere else, and the band where it does best
(≥0.995) is its *highest*-confidence band. A gate on low confidence fires on 11 items and
catches 9 % of the errors.

> **H5 is answered, and it splits.** Confidence is a **perfect** escalation gate for the 2B
> and a **useless** one for the 600M. It is not a property of the task or the checker — it is
> a property of the *proposer*. So the loop works exactly when the proposer is well
> calibrated, and a loop built on the 600M cannot work at all.
>
> This independently confirms last-mile's **D62** rejection of a 600M-first cascade, and it
> sharpens it: the reason is not that the 600M is inaccurate, it is that the 600M's
> *uncertainty is not where its errors are*.

### 3.7 Joules

**The attribution rule (IDEAS.md rule 6).** The whole-box power rail carries every tenant —
the seed sweep is on the box and so is another seat's bake — so it is **not attributable**.
The rail that is attributable is **VDD_GPU**, and the idle baseline is measured **with our own
server resident but idle, in the same session**, so the other tenants' GPU work is inside both
windows and largely cancels. The rail is sampled continuously by `tegrastats` at 100 ms while
the cell is working, from a thread, so the sampling is not at the requests' pace. The joules
figure is the **difference** between the loaded rail and the idle baseline, times the measured
duration. If that difference comes out negative, the joules figure is meaningless and the wall
time stands (rule 6).

**What this measurement cannot do.** It cannot separate our model from another tenant's
render that happens to run at the same time; the subtraction removes the *constant* part, not
the *varying* part. The box's state is recorded beside every cell, and the GPU's power draw is
reported raw (baseline, loaded, delta) rather than only as a derived joules number, so the
reader can see how big the delta is against the noise.

**A note on the GPU clock.** IDEAS.md rule 3 says to record the clock beside the number. On
this box it is not observable: `nvidia-smi --query-gpu=clocks.sm` returns `[N/A]`, and this
`tegrastats` build prints no GR3D frequency field. The control is therefore the **warm-up
protocol** — every cell runs five warm-up decisions before the timed window, so the clock has
ramped (315 → 1575 MHz in ~1.4 s) before anything is measured.

**The measurement.** 2026-10-31T16:48:50 → 16:50:26 · 6.8.12-1021-tegra · aarch64 · 14 cores ·
load [5.73, 6.38, 7.07] → [4.93, 5.90, 6.83] · mem available 119 GB · 40 decisions per cell ·
one server at a time, the rail sampled every 100 ms while the cell worked.

| cell | ms/decision | p50 ms | idle VDD_GPU mW | loaded mW | **delta mW** | J (total) | **J/decision** | decisions/s | **average W** | peak mem GB |
|---|---|---|---|---|---|---|---|---|---|---|
| d1-omni-600M-Q4 | 43.36 | 42.69 | 3936 | 24062 | 20126 | 34.91 | **0.873** | 23.1 | 20.1 | 10.41 |
| d1-omni-600M-Q8 | 37.93 | 37.75 | 3936 | 24805 | 20869 | 31.66 | 0.792 | 26.4 | 20.9 | 10.49 |
| d1-omni-600M-BF16 | 30.46 | 29.54 | 3148 | 22225 | 19077 | 23.25 | **0.581** | 32.8 | 19.1 | 10.94 |
| d1-2B-Q4 | 137.31 | 138.67 | 4329 | 31001 | 26672 | 146.50 | **3.662** | 7.3 | 26.7 | 13.14 |
| d1-2B-Q8 | 125.58 | 125.27 | 4329 | 32281 | 27952 | 140.41 | 3.510 | 8.0 | 28.0 | 13.69 |
| d1-2B-BF16 | 105.85 | 102.11 | 4329 | 28318 | 23989 | 101.57 | **2.539** | 9.5 | 24.0 | 14.14 |
| d1-3B-Q4 | 137.03 | 136.88 | 4329 | 31878 | 27549 | 151.00 | 3.775 | 7.3 | 27.5 | 12.08 |
| d1-3B-Q8 | 148.16 | 145.10 | 4329 | 31157 | 26828 | 159.00 | **3.975** | 6.8 | 26.8 | 15.00 |
| d1-3B-BF16 | 156.75 | 151.12 | 4723 | 25894 | 21171 | 132.74 | 3.318 | 6.4 | 21.2 | 17.60 |

**Reading it.**

1. **The energy ranking is the latency ranking.** J/decision and ms/decision order the nine
   cells identically (Spearman ρ = 1 over the nine cells). That is the same fact as H2, in
   energy instead of wall time: on this decision path the 4-bit weights are *slower*, so they
   also cost *more* energy per answer. Q4 is the worst cell for the 600M (0.873 J) and for the
   2B (3.662 J); BF16 is the best for both (0.581 J and 2.539 J).
2. **The size difference is latency, not power.** The *average* power draw is nearly flat
   across the whole ladder — 19.1 W for the 600M at BF16, 21.2 W for the 3B at BF16, 24.0–28.0 W
   for the 2B. The 3B costs 3.32 J per decision against the 2B's 2.54 J, but it draws *less*
   power on average (21.2 W vs 24.0 W). Its extra energy is entirely the extra time it takes.
   So "the big model is more expensive" is true per decision and false per watt.
3. **BF16 is the best cell on this box**, on both axes at once: it is the fastest *and* the
   cheapest per decision for the 600M and the 2B. It is also the largest resident (14.1 GB vs
   13.1 GB for the 2B). Q4's only advantage is residency.
4. **The 3B-Q8 cell is the outlier** (3.975 J, the worst of the nine) and it is the cell whose
   p90 latency was 255 ms in the E1b ladder — it ran into contention. Its *median* latency is
   normal, so the joules figure, which is a mean over the whole window, is the one number that
   the contention shows up in.
5. **The idle baseline is the other tenants.** 3.1–4.7 kW with our own server resident and
   idle: that is the box's other work (another seat's Blender bake was running). The loaded
   rail is 22–32 kW, so the deltas are **5–9× the baseline** and the model dominates its own
   window. The subtraction is doing its job: the same bake is inside both numbers.
6. **Every cell's peak memory is recorded** and every one is under the 25 GB reserve (10.4 GB
   to 17.6 GB), so the memory rule held for this step.

> **The joules answer.** The precision ladder's energy story is the same as its latency story:
> **16-bit is cheaper per decision than 4-bit on this path**, because the decision path is not
> matmul-bound. And the biggest model is the worst deal on both axes — the 2B is both more
> accurate (§3.5) and cheaper per decision than the 3B.

---

## 4. E2 — the cleanup loop: propose → check → escalate

**The design.** A low-precision proposer answers every item; a checker answers the items that
*could* escalate; the gate decides which of those answers to use. Two properties make the
numbers exact rather than approximate:

1. **The proposer's answers do not depend on the checker.** They are asked once per
   (proposer cell, task) and reused across every arm. So every arm sees the same proposer
   output on the same items, and a difference between arms is a difference between *checkers*.
2. **The checker's answer does not depend on the threshold.** It is asked once, over every item
   whose proposer confidence is below the largest threshold on the curve (0.9). Every point of
   the curve is then read off that one pass. So the cloud bill is one pass, not one pass per
   threshold, and the curve's points are exact.

The **memory rule** holds: a cell is started, does every pass it owes, and is stopped before
the next cell starts. Inside a task the order is: the 2B-Q4 proposer, the 600M-Q4 proposer,
the 3B-BF16 reference (which is also the 3B checker), the 2B-BF16 checker, and then the two
cloud checkers, which need no local server at all.

**The arms.** The three the brief names, plus the two the library's concrete gating mechanisms
ask for, plus the two baselines:

| arm | proposer | checker | what it is |
|---|---|---|---|
| `none` | d1-2B-Q4 | — | the baseline the loop must beat |
| `3B-BF16` | d1-omni-600M-Q4 | d1-3B-BF16 | "a bigger d1" (library #4, the cascaded edge tier) |
| `2B-BF16` | d1-2B-Q4 | d1-2B-BF16 | "the same model at higher precision" (library #3, local precision promotion) |
| `jev` | d1-2B-Q4 | Jev `decide` (cloud) | "Jev's decide" (library #5, the external decision head) |
| `jev-noul` | d1-2B-Q4 | Jev `noul` (cloud) | the same cloud judge, asked as propositions instead of a ranking |
| `tiered` | d1-2B-Q4 | d1-2B-BF16 in the band, Jev `decide` below it | three tiers (library #2): local, promoted, cloud triage |
| `hyst` | d1-2B-Q4 | d1-2B-BF16 | two bounds and a temporal window (library #14) |

The `tiered` and `hyst` arms are **recomposed from the same cached calls** as the arms above,
so they cost no extra model time and no extra cloud calls: every checker's answers are a pure
function of the item, so a second gate over the same answers is a re-reading, not a re-asking.

**The `tiered` arm, precisely.** Confidence ≥ 0.90 → the proposer's answer stands. 0.60 ≤
confidence < 0.90 → the same weights at BF16 answer (precision promotion). Confidence < 0.60 →
Jev answers (cloud triage). The tiers are read off one 2B-BF16 checker pass and one Jev pass
over the same items.

**The `hyst` arm, precisely.** The gate is a state machine over the *order* of the items:
confidence < 0.60 escalates; confidence ≥ 0.90 does not; **in between, the gate keeps whatever
it decided last.** The window is how many in-between items stay escalated after the last hard
signal. Because the answer depends on the order, the same cached calls are replayed under five
seeded orders and the spread over orders is reported — the honesty of the number comes from
its spread, not from a single run.

### 4.1 The ceiling, before any checker runs

Before running a single checker, the E1 rows already say how much a checker could possibly be
worth: take the gate, and let the checker be **perfect** on every item it sees. This needs no
model run — it is arithmetic on the confidence and correctness already recorded — and it frames
every number in §4.2.

| proposer | task | n | proposer acc | gate | escalated | escalation rate | errors | errors caught | share caught | **ceiling** | max gain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| d1-2B-Q4 | T1 scenes | 200 | 0.9850 | 0.6 | 8 | 0.040 | 3 | 3 | **1.000** | **1.0000** | +0.0150 |
| d1-2B-Q4 | T2 defects | 51 | 0.6667 | 0.6 | 7 | 0.137 | 17 | 2 | 0.118 | 0.7059 | +0.0392 |
| d1-2B-Q4 | T3 tiles | 120 | 0.4500 | 0.6 | 80 | 0.667 | 66 | 53 | 0.803 | 0.8917 | +0.4417 |
| d1-omni-600M-Q4 | T1 scenes | 200 | 0.4150 | 0.6 | **0** | **0.000** | 117 | 0 | 0.000 | 0.4150 | **+0.0000** |
| d1-omni-600M-Q4 | T2 defects | 51 | 0.6667 | 0.6 | 17 | 0.333 | 17 | 10 | 0.588 | 0.8627 | +0.1961 |
| d1-omni-600M-Q4 | T3 tiles | 120 | 0.2750 | 0.6 | 91 | 0.758 | 87 | 69 | 0.793 | 0.8500 | +0.5750 |

Three things follow from the table alone, before any checker is asked anything:

1. **The 600M-first cascade on T1 is not weak — it is empty.** At gate 0.60 the 600M escalates
   **zero** of 200 items, so a perfect checker would add exactly nothing. The loop is not
   "not worth it" on that task; it cannot fire. This is the sharpest form of last-mile's D62
   rejection, and it is a property of the *gate*, not of the checker's quality.
2. **On T1 the 2B's gate is almost free and almost complete.** 8 items (4 %) carry all 3
   errors, so the ceiling is 1.000 against a proposer of 0.985. This is D71's shape — d1-2B
   alone 0.96, with the second model 0.98 at 4 % escalated — reproduced on fresh scenes.
3. **On T2 the gate barely works at all.** The 2B's 17 errors are spread across the confidence
   range: a gate at 0.60 catches **2 of them (12 %)**. So no checker — not Jev, not a bigger
   d1 — can help much on the defect task. The loop's problem there is the *proposer's
   uncertainty*, and the only fix for that is a better proposer or a different task.
4. **On T3 the gate works but is expensive.** 67 % of the items escalate to catch 80 % of the
   errors. The ceiling is +0.44, but at two-thirds of the traffic the loop is a different
   system, not an optimisation.

<!-- E2 RESULTS:START -->
**The headline.** The cleanup loop is real, but it is not a precision story and it is not a size story either — it is a *gate* story, and the gate only exists where the proposer's confidence predicts its errors.

| task | proposer alone | best cascade | gate | gain | escalated | big model alone |
|---|---|---|---|---|---|---|
| T1 scenes | 0.9850 | **1.0000** (`jev-noul`) | 0.6 | **+0.0150** | 4.0 % | 0.8800 |
| T2 defects | 0.6667 | **0.7451** (`jev-noul`) | 0.8 | **+0.0784** | 33.3 % | 0.4902 |
| T3 tiles | 0.4500 | **0.6667** (`jev`) | 0.9 | **+0.2167** | 96.7 % | 0.3250 |

The three results are not the same result:

1. **On T1 the loop is nearly free and complete.** 4 % of the traffic escalates, all three errors are caught, none are broken, and the loop lands exactly on the ceiling §4.1 computed in advance (1.0000). The cloud judge is the only checker that reaches 1.0000.
2. **On T2 the loop barely helps**, because the 2B's confidence does not predict its errors (ECE 0.2231, the confident half is *worse* than the unsure half). The 5 overrules that land are real (4 of 5 right) but there are only 5 to catch at any gate the proposer's confidence will open.
3. **On T3 the loop carries the task.** At gate 0.6 it reaches 0.6250 (p = 0.000508 vs the proposer) and at gate 0.9, 0.6667 — while the big model alone scores 0.3250. **The cascade beats the top of the ladder**, because it asks a better decider (the cloud) about the two-thirds of items where the local model has no idea. The price is that at its best gate the loop escalates 96.7 % of the traffic — on T3 the cascade is a different system, not an optimisation.

And one negative result that matters as much: **the precision promotion arm is a no-op at best and a regression at worst.** The 2B at BF16 checking the 2B at Q4 changes nothing on T1 and T2 at the gates that matter and loses 0.0083 on T3. The same weights at a higher precision produce the same answers (E1), so promoting precision in the loop buys nothing; what buys accuracy is a **different** model — local-bigger only when the bigger one is actually better (on these tasks it is not), cloud otherwise.
<!-- E2 RESULTS:END -->

### 4.2 The arms on the threshold curve

<!-- E2 TABLE:START -->
The full curve, for every arm that has a threshold. `none` is the baseline: the proposer alone, and the only arm that makes no checker call at all. The last column is the big model (d1-3B BF16) answering the same task alone.

| task | arm | checker | proposer alone | acc @0.0 | acc @0.2 | acc @0.4 | acc @0.6 | acc @0.8 | acc @0.9 | big model alone |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | none | none | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.8800 |
| T1 scenes (action) | 3B-BF16 | d1-3B-BF16 | 0.4150 | 0.4150 | 0.4150 | 0.4150 | 0.4150 | 0.4400 | 0.4700 | 0.8800 |
| T1 scenes (action) | 2B-BF16 | d1-2B-BF16 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.8800 |
| T1 scenes (action) | jev | jev | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.9950 | 0.9950 | 0.9950 | 0.8800 |
| T1 scenes (action) | jev-noul | jev-noul | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 1.0000 | 1.0000 | 1.0000 | 0.8800 |
| T2 defects | none | none | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.4902 |
| T2 defects | 3B-BF16 | d1-3B-BF16 | 0.6667 | 0.6667 | 0.6667 | 0.6471 | 0.6275 | 0.5882 | 0.4314 | 0.4902 |
| T2 defects | 2B-BF16 | d1-2B-BF16 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.4902 |
| T2 defects | jev | jev | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.4902 |
| T2 defects | jev-noul | jev-noul | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.7059 | 0.7451 | 0.7451 | 0.4902 |
| T3 tiles | none | none | 0.4500 | 0.4500 | 0.4500 | 0.4500 | 0.4500 | 0.4500 | 0.4500 | 0.3250 |
| T3 tiles | 3B-BF16 | d1-3B-BF16 | 0.2750 | 0.2750 | 0.2500 | 0.2750 | 0.3250 | 0.3333 | 0.3250 | 0.3250 |
| T3 tiles | 2B-BF16 | d1-2B-BF16 | 0.4500 | 0.4500 | 0.4500 | 0.4583 | 0.4417 | 0.4417 | 0.4417 | 0.3250 |
| T3 tiles | jev | jev | 0.4500 | 0.4500 | 0.4500 | 0.5333 | 0.6250 | 0.6583 | 0.6667 | 0.3250 |
| T3 tiles | jev-noul | jev-noul | 0.4500 | 0.4500 | 0.4500 | 0.5250 | 0.6083 | 0.6417 | 0.6417 | 0.3250 |

**What the curve says.** Only the cloud arms ever beat the proposer alone, and only on the tasks where the gate can fire:

- **`jev-noul` (cloud, propositions) fixes T1 outright.** 0.9850 → **1.0000** at gate 0.6, on 4 % of the traffic — all three of the proposer's errors caught, nothing broken. On T2 it is the only arm that helps: 0.6667 → **0.7451** at gate 0.8. On T3 it reaches 0.6417 at gate 0.9.
- **`jev` (`decide`) is the T3 arm.** 0.4500 → **0.6667** at gate 0.9 and 0.6250 at gate 0.6 (paired vs the proposer: McNemar p = 0.000508) — but it escalates 96.7 % of the traffic at 0.9 and 66.7 % at 0.6. The difference between the two cloud shapes is the question: `decide` ranks the options as one multiple-choice decision, `noul` judges one proposition per option. T3's five payoff-weighted tiles read as a ranking; T1's three safety labels do not.
- **`2B-BF16` (local precision promotion) is a no-op or a regression, never a win.** T1: 0.9850 → 0.9850 at every threshold — the checker is the *same weights* as the proposer, so when it disagrees with itself it is as often wrong as right. T3: 0.4500 → 0.4417 — slightly worse. T2: flat at 0.6667 at gate 0.6 and 0.9. This is E1's result (27 within-size precision pairs, 0 significant) arriving in the loop: promoting precision in the loop buys nothing; what buys accuracy is a **different** model.
- **`3B-BF16` over the 600M proposer is a trap.** T1: 0.4150 → 0.4700 at gate 0.9, on 5.5 % of the traffic (11 overrules, all 11 right — the checker works; the gate just never opens). T2: 0.6667 → **0.4314** at gate 0.9 — the bigger model actively destroys the answer on 60.8 % of the traffic. T3: 0.2750 → 0.3250, still below the 2B's 0.4500 alone.
<!-- E2 TABLE:END -->

### 4.3 Which checker works best, per task

<!-- E2 BEST:START -->
The best cell of every task's curve, and whether the win is statistically real. The paired test is McNemar's exact test on the same items at the default gate 0.60 — a different gate than the best cell where noted.

| task | best arm | gate | loop acc | proposer alone | gain | escalated | overruled | checker right | McNemar p (at 0.6) | big model alone |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | jev-noul | 0.6000 | 1.0000 | 0.9850 | 0.0150 | 0.0400 | 3 | 3 | 0.2500 | 0.8800 |
| T2 defects | jev-noul | 0.8000 | 0.7451 | 0.6667 | 0.0784 | 0.3333 | 5 | 4 | 0.5000 | 0.4902 |
| T3 tiles | jev | 0.9000 | 0.6667 | 0.4500 | 0.2167 | 0.9667 | 54 | 36 | 0.0005 | 0.3250 |

Three different answers, and the shape of the answer is what the ladder theory does not predict:

1. **T1 (scenes): the cloud fixes every error, almost free.** `jev-noul` reaches **1.0000** from 0.9850 — 3 of 3 errors caught, 0 correct answers broken, at **4 % escalation** (p = 0.25 at this n; the ceiling computation of §4.1 said 1.0000 was reachable and the loop reached exactly it). That is D71's shape (d1-2B alone 0.96 → 0.98 with a second model at 4 % escalated), reproduced on fresh scenes with a *different* second model: a cloud decision head, not another d1.
2. **T2 (defects): the cloud helps a little, and the gate is the reason it cannot help more.** 0.6667 → 0.7451 at gate 0.8: 5 overrules of which 4 right, on 33.3 % of the traffic. The ceiling at gate 0.60 was 0.7059 (§4.1: the gate catches 2 of 17 errors); the wider gate buys more. But the *proposer* is the weak link here (§4.7: its confidence does not rank its errors on this task), so no gate can fix T2.
3. **T3 (tiles): the cloud carries the task — past the big model.** 0.4500 → **0.6667** at gate 0.9 with the paired test at gate 0.6 giving McNemar p = 0.000508 (28 items the cascade gets right and the proposer misses, 7 the other way). The big model alone scores 0.3250, so the cascade beats the top of the ladder by +0.34 at its best gate — but it pays for it with 96.7 % escalation, which is a different system, not an optimisation. At the 0.6 gate it still holds 0.6250 at 66.7 % escalation.

**The big model alone never wins.** On all three tasks the d1-3B BF16 scores below the d1-2B Q4 proposer (T1 0.8800 vs 0.9850, T2 0.4902 vs 0.6667, T3 0.3250 vs 0.4500). The cascade's value is not that it reaches the big model; it is that it can go past it — by asking a *better* decider (the cloud) only where the local model is unsure.
<!-- E2 BEST:END -->

### 4.4 The 600M-first cascade, and what the gate costs

<!-- E2 600M:START -->
The 600M-first cascade: the small model proposes, and the d1-3B BF16 checks. This is library #4 — the cascaded edge tier — and it is the arm that decides whether the ladder can be walked from the bottom.

| task | proposer | arm | 600M alone | acc @0.6 | esc @0.6 | acc @0.9 | esc @0.9 | overruled @0.9 | right @0.9 | 3B alone |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | d1-2B-Q4 | none | 0.9850 | 0.9850 | 0.0000 | 0.9850 | 0.0000 | 0 | 0 | 0.8800 |
| T1 scenes (action) | d1-omni-600M-Q4 | 3B-BF16 | 0.4150 | 0.4150 | 0.0000 | 0.4700 | 0.0550 | 11 | 11 | 0.8800 |
| T2 defects | d1-2B-Q4 | none | 0.6667 | 0.6667 | 0.0000 | 0.6667 | 0.0000 | 0 | 0 | 0.4902 |
| T2 defects | d1-omni-600M-Q4 | 3B-BF16 | 0.6667 | 0.6275 | 0.3333 | 0.4314 | 0.6078 | 28 | 4 | 0.4902 |
| T3 tiles | d1-2B-Q4 | none | 0.4500 | 0.4500 | 0.0000 | 0.4500 | 0.0000 | 0 | 0 | 0.3250 |
| T3 tiles | d1-omni-600M-Q4 | 3B-BF16 | 0.2750 | 0.3250 | 0.7583 | 0.3250 | 0.9667 | 84 | 27 | 0.3250 |

**It does not work, and the reason is the gate, not the checker.**

- On T1 the 600M escalates **0 of 200 items** at gate 0.60. Its confidence is high and wrong: mean confidence 0.9733 against an accuracy of 0.4150, ECE **0.5583**. The loop cannot fire, so a perfect checker would add nothing. At gate 0.90 it opens on 5.5 % of the traffic and the 3B is right on all 11 overrules — the plumbing works; the gate just never opens where the errors are. This is D62's rejection of the 600M-first cascade, reproduced on a fresh set with the mechanism made explicit.
- On T2 the 600M's confidence *is* informative (it escalates 33.3 % at gate 0.6) but the outcome is still bad: 0.6667 → **0.4314** at gate 0.9. The 3B is a worse decider than the 600M on this task (0.4902 vs 0.6667), so putting it in the loop can only lose: 28 overrules, 4 right.
- On T3 the 600M-first cascade reaches 0.3250 at gate 0.9 — still below the d1-2B Q4's 0.4500 alone.

**So the smallest model cannot be the floor of the ladder.** The ladder has to start at the size that is right on the task, and the loop has to start at the size whose confidence is meaningful. A model whose confidence is uncalibrated is not a proposer; it is a source of confident noise that a gate cannot see.
<!-- E2 600M:END -->

### 4.5 The tiered gate: local, promoted, cloud

<!-- E2 TIERED:START -->
The tiered gate (library #2, #3, #5): confidence ≥ 0.90 the proposer stands; 0.60 ≤ confidence < 0.90 the same weights at BF16 answer (precision promotion); confidence < 0.60 the cloud answers. Recomposed from the same cached calls, so the numbers are exactly the arms above.

| task | proposer | promoted checker | low | high | tiers | loop acc | proposer acc | big acc | cloud calls | promoted calls | overruled | checker right | McNemar p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | {"local": 120, "promoted": 72, "cloud": 8} | 0.9950 | 0.9850 | 0.8800 | 8 | 72 | {"promoted": 0, "cloud": 2} | {"promoted": 0, "cloud": 2} | 0.5000 |
| T2 defects | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | {"local": 32, "promoted": 12, "cloud": 7} | 0.6667 | 0.6667 | 0.4902 | 7 | 12 | {"promoted": 0, "cloud": 0} | {"promoted": 0, "cloud": 0} | 1.0000 |
| T3 tiles | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | {"local": 4, "promoted": 36, "cloud": 80} | 0.6250 | 0.4500 | 0.3250 | 80 | 36 | {"promoted": 0, "cloud": 43} | {"promoted": 0, "cloud": 28} | 0.0005 |

**The tiered gate never beats the best simple gate, and the middle tier is the reason.**

- T1: 0.9950, against `jev-noul`'s 1.0000. The promotion tier took 72 of 200 items (36 %) and overruled **0** of them — the 2B BF16 is the same model as the proposer with the same answers (E1), so the tier is pure cost. The cloud tier did the only work: 8 calls, 2 overrules, both right.
- T3: 0.6250, against `jev`'s 0.6667. The promotion tier took 36 items and overruled 0; the cloud tier took 80, overruled 43, was right on 28. Every point of gain came from the cloud rung; the middle rung only delayed it.
- T2: 0.6667, no gain — the `decide` shape cannot be asked a 10-class question (§4.8), so the cloud tier of this arm never ran.

**The finding: a promotion tier is worth adding only when the thing it promotes to is measurably different.** On this stack the 2B at BF16 is not better than the 2B at Q4 — it is the same weights with the same answers (E1: 27 within-size pairs, 0 significant differences). The tiered gate spends up to 36 % of the traffic re-asking the same model, and only the cloud tier does work.
<!-- E2 TIERED:END -->

### 4.6 The hysteresis gate: two bounds and a window

<!-- E2 HYST:START -->
The hysteresis gate (library #14): two bounds and a temporal window. Confidence < 0.60 escalates; confidence ≥ 0.90 does not; in between the gate **keeps whatever it decided last**, and the window is how many in-between items stay escalated after the last hard signal. Because the answer depends on the order of the items, the same cached calls are replayed under **five seeded orders** and the spread over orders is reported — the honesty of the number comes from its spread, not from a single run.

| task | proposer | checker | low | high | window | acc mean | acc min | acc max | proposer acc | escalation rate | orders |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 1 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.0550 | 5 |
| T1 scenes (action) | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 3 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.0650 | 5 |
| T1 scenes (action) | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 99 | 0.9850 | 0.9850 | 0.9850 | 0.9850 | 0.0650 | 5 |
| T2 defects | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 1 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.1687 | 5 |
| T2 defects | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 3 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.1765 | 5 |
| T2 defects | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 99 | 0.6667 | 0.6667 | 0.6667 | 0.6667 | 0.1765 | 5 |
| T3 tiles | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 1 | 0.4417 | 0.4417 | 0.4417 | 0.4500 | 0.8650 | 5 |
| T3 tiles | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 3 | 0.4417 | 0.4417 | 0.4417 | 0.4500 | 0.9433 | 5 |
| T3 tiles | d1-2B-Q4 | d1-2B-BF16 | 0.6000 | 0.9000 | 99 | 0.4417 | 0.4417 | 0.4417 | 0.4500 | 0.9500 | 5 |

**The window moves the traffic and not the accuracy.**

- T3: the escalation rate climbs 0.8650 → 0.9433 → 0.9500 as the window grows from 1 to 99, while the accuracy stays at 0.4417 across all three windows and all five orders (min = max = mean). A wider window means *more* items are escalated, and since the checker is the same 2B, the extra escalations are extra opportunities to be wrong: the accuracy is 0.0083 **below** the proposer alone.
- T1: the escalation rate climbs 0.0550 → 0.0650 and the accuracy does not move at all (0.9850 at every window).
- T2: the same, 0.1687 → 0.1765 escalation, 0.6667 accuracy throughout.

**Hysteresis is a latency-and-cost instrument here, not an accuracy instrument.** Its measurable effect is the number of checker calls, and the direction is *more* traffic, not less: the window keeps the last decision alive across the items in between, and on these tasks the in-between band is where the errors are not. The spread over orders is exactly zero for the accuracy in every cell, which says the order-dependence is real but small compared with the gate's own effect.
<!-- E2 HYST:END -->

### 4.7 Is the proposer's confidence worth trusting?

<!-- E2 CALIB:START -->
The gate is only as good as the confidence that drives it. This is the proposer's own calibration, measured on the items it answered, for every proposer in the run. `confidence ranks` means the confident half of the items is more accurate than the unsure half — the property the gate needs.

| task | proposer | arm | accuracy | mean conf | Brier | ECE | acc (confident half) | acc (unsure half) | confidence ranks |
|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | d1-2B-Q4 | none | 0.9850 | 0.8755 | 0.0262 | 0.1229 | 1.0000 | 0.9700 | yes |
| T1 scenes (action) | d1-omni-600M-Q4 | 3B-BF16 | 0.4150 | 0.9733 | 0.5430 | 0.5583 | 0.6000 | 0.2300 | yes |
| T1 scenes (action) | d1-2B-Q4 | 2B-BF16 | 0.9850 | 0.8755 | 0.0262 | 0.1229 | 1.0000 | 0.9700 | yes |
| T1 scenes (action) | d1-2B-Q4 | jev | 0.9850 | 0.8755 | 0.0262 | 0.1229 | 1.0000 | 0.9700 | yes |
| T1 scenes (action) | d1-2B-Q4 | jev-noul | 0.9850 | 0.8755 | 0.0262 | 0.1229 | 1.0000 | 0.9700 | yes |
| T2 defects | d1-2B-Q4 | none | 0.6667 | 0.8396 | 0.2827 | 0.2231 | 0.6400 | 0.6923 | **no** |
| T2 defects | d1-omni-600M-Q4 | 3B-BF16 | 0.6667 | 0.7468 | 0.1981 | 0.1275 | 0.8000 | 0.5385 | yes |
| T2 defects | d1-2B-Q4 | 2B-BF16 | 0.6667 | 0.8396 | 0.2827 | 0.2231 | 0.6400 | 0.6923 | **no** |
| T2 defects | d1-2B-Q4 | jev | 0.6667 | 0.8396 | 0.2827 | 0.2231 | 0.6400 | 0.6923 | **no** |
| T2 defects | d1-2B-Q4 | jev-noul | 0.6667 | 0.8396 | 0.2827 | 0.2231 | 0.6400 | 0.6923 | **no** |
| T3 tiles | d1-2B-Q4 | none | 0.4500 | 0.5576 | 0.2195 | 0.1396 | 0.5500 | 0.3500 | yes |
| T3 tiles | d1-omni-600M-Q4 | 3B-BF16 | 0.2750 | 0.4661 | 0.2644 | 0.2339 | 0.3333 | 0.2167 | yes |
| T3 tiles | d1-2B-Q4 | 2B-BF16 | 0.4500 | 0.5576 | 0.2195 | 0.1396 | 0.5500 | 0.3500 | yes |
| T3 tiles | d1-2B-Q4 | jev | 0.4500 | 0.5576 | 0.2195 | 0.1396 | 0.5500 | 0.3500 | yes |
| T3 tiles | d1-2B-Q4 | jev-noul | 0.4500 | 0.5576 | 0.2195 | 0.1396 | 0.5500 | 0.3500 | yes |

**The confidence is usable on T1 and T3 and useless on T2 — and the ECE says so before the arm table does.**

- **d1-2B-Q4 on T1** is the best-calibrated cell in the whole lab: accuracy 0.9850, mean confidence 0.8755, Brier **0.0262**, ECE 0.1229, and the confident half is 1.0000 against the unsure half's 0.9700. This is why the gate fires on exactly the 3 wrong items.
- **d1-omni-600M-Q4 on T1 is the opposite**: accuracy 0.4150, mean confidence **0.9733**, ECE **0.5583**. It is confidently wrong. Its confidence does rank its items (confident half 0.6000 vs unsure half 0.2300) — but the *level* is so far above the accuracy that a gate at 0.60 never opens (0 of 200 escalated) and even at 0.90 it opens on 5.5 %. The problem is not the ranking, it is the offset.
- **d1-2B-Q4 on T2** has the worst calibration of the 2B cells: Brier 0.2827, ECE 0.2231, and the confident half (0.6400) is *worse* than the unsure half (0.6923) — `confidence ranks` is **false**. Its 17 errors are spread evenly across the confidence range, so the gate has nothing to select on. This is the mechanism behind the T2 result: not that the cloud is weak, but that the local model's uncertainty carries no information on this task.
- **d1-2B-Q4 on T3**: ECE 0.1396, ranks **true** (0.5500 vs 0.3500). The gate works — and the ceiling is high because 80 % of the errors sit in the low-confidence band.
- **d1-omni-600M-Q4 on T2** is the one cell where the 600M's confidence is genuinely useful: ECE 0.1275, ranks **true** (0.8000 vs 0.5385). But its accuracy is the same as the 2B's (0.6667), so there is nothing to gain from a better gate on that task.

**So the confidence gate is per (model, task), and both halves matter.** A gate needs the confidence to *rank* the errors (T2's 2B does not) and to sit at a *level* where a threshold can open (T1's 600M does not). Both properties are cheap to measure in advance — the Brier score and the reliability curve of the proposer's own answers — and any builder-ide gate should measure them before trusting a τ.
<!-- E2 CALIB:END -->

### 4.8 The cost of the round trip

<!-- E2 COST:START -->
Two costs: the cloud bill, and the round trip's latency.

**The cloud bill.** Every number is a measured pass, not an estimate. The bill is per *pass* because a pass is shared by the arms that read it off: the `jev` pass and the `jev-noul` pass on each task, taken once at the widest gate (0.9) and read at every threshold.

| task | cloud pass | calls | input tokens | output tokens | total tokens |
|---|---|---|---|---|---|
| T1 scenes (action) | jev | 80 | 51569 | 3920 | 55489 |
| T1 scenes (action) | jev-noul | 80 | 58449 | 5360 | 63809 |
| T2 defects | jev | 19 | 0 | 0 | 0 |
| T2 defects | jev-noul | 19 | 32891 | 4066 | 36957 |
| T3 tiles | jev | 116 | 109322 | 7772 | 117094 |
| T3 tiles | jev-noul | 116 | 120280 | 12644 | 132924 |

**Total for the whole E2 experiment: 430 cloud calls, 406,273 tokens** (372,511 in, 33,762 out).

**The round trip.** The checker is not free in latency either, and the two costs point in opposite directions:

| task | checker | proposer p50 (ms) | checker p50 (ms) | checker calls | arm wall (s) |
|---|---|---|---|---|---|
| T1 scenes (action) | jev | 124.3100 | 109.2600 | 80 | 10.6000 |
| T1 scenes (action) | jev-noul | 124.3100 | 108.6200 | 80 | 8.9000 |
| T2 defects | jev | 87.4400 | — | 0 | 0.0000 |
| T2 defects | jev-noul | 87.4400 | 117.8100 | 19 | 2.6000 |
| T3 tiles | jev | 57.5300 | 109.6000 | 116 | 13.6000 |
| T3 tiles | jev-noul | 57.5300 | 109.7700 | 116 | 13.5000 |

**What the cost buys.**

- The cloud checker costs **~110 ms** per item at the median (108.6–117.8 ms across the passes that ran), against the local proposer's 57.5–124.3 ms. So a checker call roughly doubles the per-item latency of the 2B proposer and is ~4× the 600M's cheapest cell (25–41 ms in E1).
- On T1 it buys **3 items out of 200** (1.5 %) — all three of the proposer's errors, at 4 % of the traffic. The best ratio in the lab.
- On T3 it buys **26 items out of 120** at gate 0.6 (0.4500 → 0.6250, p = 0.000508) for 66.7 % of the traffic, or 26 more at gate 0.9 (0.6667) for 96.7 %. Expensive — and worth it only where the alternative (a bigger local model) scores *worse* than the proposer, which is exactly the case on T3 (the 3B alone: 0.3250).
- The `jev` (decide) pass **cannot be asked the T2 question at all**: `jev_decide` accepts at most **6 candidates** and the defect task has **10 classes**, so the tool refuses (`Input validation error: ... candidates: Too big: expected array to have <=6 items`). That is why the T2 `jev` row has 19 calls and zero tokens, and why the T2 `tiered` arm (whose cloud tier is `decide`) shows no gain. `jev_noul` takes one proposition per candidate — up to 64 — and answers the same task fine. **A decision tool with a candidate-count limit cannot be the checker for a 10-way task, and the error is a refusal, not a wrong answer** — which the lab caught only because the client raises on tool errors instead of returning `None`. The first version of this experiment silently counted those refusals as disagreements and produced a checker that looked like it was overruling the proposer on all 19 defect items.
<!-- E2 COST:END -->

---

## 5. E3 — the big model calibrates the small one

**The design.** The brief asks the big model to tune the small model's harness offline — the
prompt and option wording, few-shot selection, temperature and sampling, confidence
thresholds, and (in E3c) the internal state — and then asks how close the small model gets,
per task.

**Why the big model *selects* rather than writes.** The d1 server exposes only
`POST /v1/systemone` (§2.2): `/v1/chat/completions` and `/completion` answer 501. The big
d1 model is a **decision** model — it can score a candidate but it cannot author one. So the
big model's job here is exactly the job it is good at: **score the candidate wordings and
pick one.** The candidates are fixed (the wording variants in `scripts/run_e3.py`), the big
model scores each on a calibration split, and the winner becomes the small model's harness.

This is a deliberately narrow test of Casey's intuition. It cannot test "the big model writes
a better harness" — the hardware cannot do that here — so it tests the part that *can* be
tested: does a bigger model's judgement of the harness transfer to a smaller model?

**The split.** Each task's items are split 50/50 by a fixed seed into a calibration split (the
big model chooses here) and a **held-out** split (the small model is scored here, and the big
model never sees it). The split is disjoint and deterministic, so the two runs are paired.

**The three numbers that decide it:**

| number | what it is | why it is in the table |
|---|---|---|
| **uncalibrated** | the small model, base wording, no exemplars, on the held-out split | the baseline |
| **calibrated** | the small model, the wording the big model picked, plus the big model's own confident-and-correct exemplars, on the held-out split | the treatment |
| **oracle** | the small model, the wording that *it* scores best on the calibration split, same exemplars, on the held-out split | the ceiling of this approach, for the small model |

The oracle is the important control. If the calibrated number does not beat the oracle, the
big model's choice was no better than chance and the mechanism has no referent. If the
calibrated number beats the uncalibrated one but does not reach the oracle, the big model
picks a *good* wording but not the *best* one.

**The exemplars.** Two, taken from the big model's calibration answers where it was right
*and* confident (≥ 0.8). The exemplars are the big model's, not the small model's: the point
is to hand the small model what the big model knows is right.

**The temperature knob.** The brief lists "temperature and sampling" among the knobs. On this
path the System One head is a single forward pass over the options, so the temperature is a
*server* setting and each value needs its own server. The sweep runs 0.0, 0.3, 0.7 and 1.0 on
the same items and compares the answers: **if the head is one forward pass, the temperature
cannot change anything and every answer will be identical.** That is the prediction, and the
sweep is the test.

<!-- E3 RESULTS:START -->
The E3 table, one per run. **uncalibrated** is the small model with the base wording and no exemplars, on the held-out split. **calibrated** is the small model with the big model's pick (wording *and* the exemplars the big model chose, taken from its confident-and-correct calibration answers). **oracle** is the small model with the wording that actually scores best *for the small model* — the ceiling of this approach. The big model's columns are its own accuracy with each wording.

**E3, 600M proposer** — small `d1-omni-600M-Q4`, big `d1-3B-BF16`, 100/100 calibration/held-out items:

| task | big model's pick | big cal (picked) | big held (picked) | big's best wording | big held (best) | small uncalibrated | small calibrated | small oracle | oracle wording | p (cal vs uncal) | p (cal vs oracle) | p (cal vs big) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | stepwise | 1.0000 | 0.9600 | stepwise | 0.9600 | 0.4000 | 0.3900 | 0.3900 | stepwise | 1.0000 | 1.0000 | 0.0000 |
| T2 defects | base | 0.5600 | 0.4231 | stepwise | 0.5000 | 0.7308 | 0.1538 | 0.1923 | stepwise | 0.0001 | 1.0000 | 0.0923 |
| T3 tiles | base | 0.2833 | 0.3667 | base | 0.3667 | 0.3333 | 0.3500 | 0.3500 | base | 1.0000 | 1.0000 | 1.0000 |

**E3, 2B proposer** — small `d1-2B-Q4`, big `d1-3B-BF16`, 100/100 calibration/held-out items:

| task | big model's pick | big cal (picked) | big held (picked) | big's best wording | big held (best) | small uncalibrated | small calibrated | small oracle | oracle wording | p (cal vs uncal) | p (cal vs oracle) | p (cal vs big) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | stepwise | 1.0000 | 0.9600 | stepwise | 0.9600 | 0.9900 | 0.9700 | 0.9800 | base | 0.5000 | 1.0000 | 1.0000 |
| T2 defects | base | 0.5600 | 0.4231 | stepwise | 0.5000 | 0.6538 | 0.4615 | 0.4615 | base | 0.0625 | 1.0000 | 1.0000 |
| T3 tiles | base | 0.2833 | 0.3667 | base | 0.3667 | 0.3833 | 0.2833 | 0.2833 | base | 0.0703 | 1.0000 | 0.3323 |

**E3b, 600M proposer, balanced exemplars** — small `d1-omni-600M-Q4`, big `d1-3B-BF16`, 100/100 calibration/held-out items:

| task | big model's pick | big cal (picked) | big held (picked) | big's best wording | big held (best) | small uncalibrated | small calibrated | small oracle | oracle wording | p (cal vs uncal) | p (cal vs oracle) | p (cal vs big) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | stepwise | 1.0000 | 0.9600 | stepwise | 0.9600 | 0.4000 | 0.3900 | 0.3900 | stepwise | 1.0000 | 1.0000 | 0.0000 |
| T2 defects | base | 0.5600 | 0.4231 | stepwise | 0.5000 | 0.7308 | 0.1538 | 0.1923 | stepwise | 0.0001 | 1.0000 | 0.0923 |
| T3 tiles | base | 0.2833 | 0.3667 | base | 0.3667 | 0.3333 | 0.3500 | 0.3500 | base | 1.0000 | 1.0000 | 1.0000 |

**E3b, 2B proposer, balanced exemplars** — small `d1-2B-Q4`, big `d1-3B-BF16`, 100/100 calibration/held-out items:

| task | big model's pick | big cal (picked) | big held (picked) | big's best wording | big held (best) | small uncalibrated | small calibrated | small oracle | oracle wording | p (cal vs uncal) | p (cal vs oracle) | p (cal vs big) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | stepwise | 1.0000 | 0.9600 | stepwise | 0.9600 | 0.9900 | 0.9700 | 0.9800 | base | 0.5000 | 1.0000 | 1.0000 |
| T2 defects | base | 0.5600 | 0.4231 | stepwise | 0.5000 | 0.6538 | 0.4615 | 0.4615 | base | 0.0625 | 1.0000 | 1.0000 |
| T3 tiles | base | 0.2833 | 0.3667 | base | 0.3667 | 0.3833 | 0.2833 | 0.2833 | base | 0.0703 | 1.0000 | 0.3323 |

**What the tables say, and it is not what H6 predicted.** The big model's pick never lifts the small model above its uncalibrated baseline, and twice it lands significantly below it (the 600M on defects: 0.7308 → 0.1538, McNemar p = 6.1×10⁻⁵). The oracle — the wording the *small* model itself scores best — is also never above the uncalibrated baseline. So the wordings are not the lever on these tasks at all, and the big model's exemplars actively hurt: they are drawn from the big model's own confident-and-correct answers, a distribution the small model cannot imitate, and on the defect task they teach it to name defects where the answer was `none`.

The balanced-exemplar runs reproduce the default runs' numbers exactly: the balanced filter selected the same exemplars, so they are a replication, not a variant.
<!-- E3 RESULTS:END -->

### 5.1 E3c — the Liquid internal state

The brief names "for Liquid, the internal state (e.g. a cached prefix state per task, prompt
or state caching in the runtime)" as a lever. On this stack the lever is the runtime's own
prompt/state cache, and it is off by default for decision models — the server log says so.
Four configurations, the same items, the same order:

| config | server options | what it turns on |
|---|---|---|
| `none` | — | nothing (the default) |
| `cache` | `--cache-ram 8192` | the runtime's prompt cache |
| `reuse` | `--cache-ram 8192 --cache-reuse 256` | KV shifting, so a repeated prefix is reused |
| `slot` | `--cache-ram 8192 --slot-prompt-similarity 0.5` | keep the slot whose prompt shares a long prefix |

The measurement that matters is not the latency — it is llama.cpp's own counters from
`/metrics`: `llamacpp:prompt_tokens_total` and `llamacpp:prompt_tokens_cached_total`. The
**cache hit rate** is the direct evidence that the prefix state was reused; the latency is the
consequence. And the accuracy must not change: a cache that changes the answer is not a
cache.

<!-- E3C RESULTS:START -->
**E3c — the Liquid internal state.** The runtime's own prompt cache, four configurations, the same items in the same order. The columns that were supposed to matter are `prompt tokens/call` and `cache hit rate`: llama.cpp's own counters (`llamacpp:prompt_tokens_cached_total` ÷ `llamacpp:prompt_tokens_total`), read from `/metrics` before and after each pass.

**scenes (200 items)** — cell `d1-2B-Q4`, task `scenes`:

| config | server options | n | errors | accuracy | p50 (ms) | mean (ms) | p95 (ms) | prompt tokens/call | cache hit rate | McNemar p vs none | server load (s) | wall (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | {} | 200 | 0 | 0.9850 | 126.3600 | 127.3977 | 143.1500 | 0.0000 | — | — | 1.0300 | 25.5100 |
| cache | {"cache_ram": 8192} | 200 | 0 | 0.9850 | 129.4600 | 129.9940 | 145.3000 | 0.0000 | — | 1.0000 | 1.5100 | 26.0300 |
| reuse | {"cache_ram": 8192, "cache_reuse": 256} | 200 | 0 | 0.9850 | 128.2200 | 126.8629 | 144.2900 | 0.0000 | — | 1.0000 | 1.5100 | 25.4000 |
| slot | {"cache_ram": 8192, "slot_prompt_similarity": 0.5} | 200 | 0 | 0.9850 | 129.6000 | 129.2907 | 145.0400 | 0.0000 | — | 1.0000 | 1.5100 | 25.8800 |

**tiles (120 items)** — cell `d1-2B-Q4`, task `tiles`:

| config | server options | n | errors | accuracy | p50 (ms) | mean (ms) | p95 (ms) | prompt tokens/call | cache hit rate | McNemar p vs none | server load (s) | wall (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | {} | 120 | 0 | 0.4500 | 57.8200 | 58.5320 | 62.4000 | 0.0000 | — | — | 1.5300 | 7.0400 |
| cache | {"cache_ram": 8192} | 120 | 0 | 0.4500 | 58.2000 | 59.2433 | 63.2000 | 0.0000 | — | 1.0000 | 1.5100 | 7.1300 |
| reuse | {"cache_ram": 8192, "cache_reuse": 256} | 120 | 0 | 0.4500 | 57.9600 | 67.9892 | 135.6400 | 0.0000 | — | 1.0000 | 1.0100 | 8.1800 |
| slot | {"cache_ram": 8192, "slot_prompt_similarity": 0.5} | 120 | 0 | 0.4500 | 57.9100 | 58.8887 | 63.0200 | 0.0000 | — | 1.0000 | 1.5100 | 7.0800 |

**The counters never moved.** `prompt_tokens_total` and `prompt_tokens_cached_total` read **zero at the start and zero at the end of every pass, in all four configurations, on both tasks** — the decision endpoint does not go through the prompt cache this build counts. The latency agrees: p50 126.4 → 129.5 ms on scenes and 57.8 → 58.2 ms on tiles across `none` → `slot`, all within the pass-to-pass noise. The answers are identical in every configuration (McNemar p = 1.0 against `none` everywhere), so nothing changed — which is what a no-op looks like, not what a cache that changes answers looks like.

**So H7 is killed *on this stack*, not in principle.** The lever the brief names — a cached prefix state per task — exists in the server (`--cache-ram`, `--cache-reuse`, `--slot-prompt-similarity`), and the server's own log says the prompt cache is *disabled by default for decision models*. Turning it on changes nothing measurable, because the decision path scores the prompt in one forward pass and never populates the counters the cache reports. What it would make possible, if the decision path ever grew a cached-prefix mode: the fixed world/task intro of every decision prompt is identical across calls (E5's patrol prompts share a fixed intro by construction), so a prefix cache would cut the scored tokens per decision by the length of that intro. That is a builder-side feature request, not a measured result of this lab.
<!-- E3C RESULTS:END -->

### 5.2 E3d — the temperature knob, and where it actually lives

The brief lists "temperature and sampling" among the knobs. On this stack the server's `--temp`
is **not** that knob, and knowing why matters more than the sweep does.

`tools/server/server-decision.cpp` (commit 2e0d86b) reads the decision head's temperature from
the **model's own GGUF metadata**, not from the server's sampling parameters:

```cpp
const std::string prefix_temp = prefix + "temperature.";
for (every metadata key that starts with prefix_temp) {
    temperatures[key + prefix_temp.size()] = strtof(value);   // the value's own string
}
```

and `get_temperature()` looks up `"{type}.{bucket}"` first and `"{type}"` second, where the bucket
is `n<=2 ? "2" : n<=5 ? "3_5" : n<=10 ? "6_10" : "11"`. The head's output is `softmax(scores / T)`.
The server's `--temp` applies to *sampled tokens*, and the decision path generates none.

What the shipped weights carry:

| cell | decision type | temperature keys in the GGUF |
|---|---|---|
| d1-omni-600M | `lfm2-d1-omni` | `choice.2` = 1.7465 · `choice.3_5` = 1.3999 · `choice.6_10` = 1.1751 · `choice.11` = 1.3725, and the un-bucketed fallbacks at 1.0 |
| d1-2B | `lfm3-d1` | `choice` = `noul` = `score` = **1.3373984** (the un-bucketed fallback, so it applies to every bucket) |
| d1-3B | `lfm2-d1` | **none** — its head always runs at T = 1.0 |

**What the temperature can and cannot change.** `softmax(z/T)` keeps the argmax for any T > 0, so
**the accuracy cannot move** — which is the sweep's own internal check, and a useful one. What
moves is the *confidence*, and therefore **which items the gate escalates**. So the experiment
answers the question E2 actually depends on: *at which temperature does the proposer's confidence
select the most errors per unit of traffic?*

The sweep patches that float32 metadata value **in a copy of the weights** (`scripts/patch_temp.py`
writes 4 bytes in place, so the file layout and every tensor offset are untouched) and serves the
copy. The shipped model files are never written.

<!-- E3D RESULTS:START -->
The sweep: the decision head's own temperature (patched in a copy of the GGUF metadata, §5.2), the same items, both gates' worth of statistics. `errors caught` is the share of the model's errors that a 0.6 gate would escalate — the number a *gate* cares about, since softmax(z/T) keeps the argmax and accuracy cannot move.

| task | T | n | accuracy | mean confidence | Brier | ECE | escalated @0.6 | errors caught @0.6 |
|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | 0.25 | 120 | 0.4083 | 1.0000 | 0.5916 | 0.5916 | 0.0000 | 0.0000 |
| T1 scenes (action) | 0.5 | 120 | 0.4083 | 0.9989 | 0.5895 | 0.5906 | 0.0000 | 0.0000 |
| T1 scenes (action) | 0.75 | 120 | 0.4083 | 0.9952 | 0.5826 | 0.5869 | 0.0000 | 0.0000 |
| T1 scenes (action) | 1.0 | 120 | 0.4083 | 0.9885 | 0.5711 | 0.5802 | 0.0000 | 0.0000 |
| T1 scenes (action) | 1.3373984 | 120 | 0.4083 | 0.9728 | 0.5475 | 0.5645 | 0.0000 | 0.0000 |
| T1 scenes (action) | 1.75 | 120 | 0.4083 | 0.9410 | 0.5059 | 0.5327 | 0.0333 | 0.0563 |
| T1 scenes (action) | 2.5 | 120 | 0.4083 | 0.8541 | 0.4122 | 0.4458 | 0.0667 | 0.1127 |
| T1 scenes (action) | 4.0 | 120 | 0.4083 | 0.6592 | 0.2719 | 0.2508 | 0.2000 | 0.2817 |
| T3 tiles | 0.25 | 120 | 0.2750 | 0.8638 | 0.5911 | 0.6170 | 0.1500 | 0.1264 |
| T3 tiles | 0.5 | 120 | 0.2750 | 0.7592 | 0.4832 | 0.5101 | 0.2833 | 0.2874 |
| T3 tiles | 0.75 | 120 | 0.2750 | 0.6614 | 0.3927 | 0.4287 | 0.3667 | 0.3793 |
| T3 tiles | 1.0 | 120 | 0.2750 | 0.5756 | 0.3273 | 0.3456 | 0.5167 | 0.5517 |
| T3 tiles | 1.3373984 | 120 | 0.2750 | 0.4811 | 0.2717 | 0.2482 | 0.7167 | 0.7701 |
| T3 tiles | 1.75 | 120 | 0.2750 | 0.3939 | 0.2356 | 0.1656 | 0.8667 | 0.8851 |
| T3 tiles | 2.5 | 120 | 0.2750 | 0.2892 | 0.2117 | 0.1033 | 0.9667 | 0.9655 |
| T3 tiles | 4.0 | 120 | 0.2750 | 0.1828 | 0.2114 | 0.1053 | 1.0000 | 1.0000 |

The sweep: the decision head's own temperature (patched in a copy of the GGUF metadata, §5.2), the same items, both gates' worth of statistics. `errors caught` is the share of the model's errors that a 0.6 gate would escalate — the number a *gate* cares about, since softmax(z/T) keeps the argmax and accuracy cannot move.

| task | T | n | accuracy | mean confidence | Brier | ECE | escalated @0.6 | errors caught @0.6 |
|---|---|---|---|---|---|---|---|---|
| T1 scenes (action) | 0.25 | 120 | 1.0000 | 0.9948 | 0.0010 | 0.0052 | 0.0000 | 0.0000 |
| T1 scenes (action) | 0.5 | 120 | 1.0000 | 0.9822 | 0.0032 | 0.0178 | 0.0083 | 0.0000 |
| T1 scenes (action) | 0.75 | 120 | 1.0000 | 0.9608 | 0.0067 | 0.0392 | 0.0083 | 0.0000 |
| T1 scenes (action) | 1.0 | 120 | 1.0000 | 0.9306 | 0.0119 | 0.0694 | 0.0083 | 0.0000 |
| T1 scenes (action) | 1.3373984 | 120 | 1.0000 | 0.8812 | 0.0226 | 0.1188 | 0.0250 | 0.0000 |
| T1 scenes (action) | 1.75 | 120 | 1.0000 | 0.8184 | 0.0416 | 0.1816 | 0.0417 | 0.0000 |
| T1 scenes (action) | 2.5 | 120 | 1.0000 | 0.7197 | 0.0854 | 0.2803 | 0.1000 | 0.0000 |
| T1 scenes (action) | 4.0 | 120 | 1.0000 | 0.5944 | 0.1681 | 0.4056 | 0.4833 | 0.0000 |
| T3 tiles | 0.25 | 120 | 0.4500 | 0.8978 | 0.4392 | 0.4478 | 0.0667 | 0.0758 |
| T3 tiles | 0.5 | 120 | 0.4500 | 0.7942 | 0.3424 | 0.3442 | 0.2000 | 0.2727 |
| T3 tiles | 0.75 | 120 | 0.4500 | 0.7061 | 0.2798 | 0.2561 | 0.3333 | 0.4394 |
| T3 tiles | 1.0 | 120 | 0.4500 | 0.6341 | 0.2433 | 0.1841 | 0.4667 | 0.5455 |
| T3 tiles | 1.3373984 | 120 | 0.4500 | 0.5576 | 0.2195 | 0.1396 | 0.6667 | 0.8030 |
| T3 tiles | 1.75 | 120 | 0.4500 | 0.4882 | 0.2114 | 0.0704 | 0.8000 | 0.9242 |
| T3 tiles | 2.5 | 120 | 0.4500 | 0.4069 | 0.2183 | 0.0759 | 0.9250 | 1.0000 |
| T3 tiles | 4.0 | 120 | 0.4500 | 0.3276 | 0.2418 | 0.1224 | 1.0000 | 1.0000 |
<!-- E3D RESULTS:END -->

---

## 6. E4 — the cloud improver: the tiles idea applied to the harness

**The design.** Every N rounds a cloud LLM reads the loop's failures and proposes **one**
harness edit — the wording, the escalation threshold, which checker, when to escalate. The
edit is applied, the calibration score is re-measured, and the edit is **kept only if the
paired score improves**. Every edit is kept in the record with its outcome, win or lose.

That is the tiles idea applied to the harness itself: the cloud is the author, the harness is
the tile, the measurement is the play, and the outcome is the label.

**What the cloud may touch.** Exactly four fields: `wording`, `escalate_threshold`,
`checker` (one of `none`, `3B-BF16`, `2B-BF16`, `jev`), and `few_shot`. An edit that leaves
the harness unchanged is not an edit and is rejected. The wording must stay faithful to the
stated rule — the cloud may restate it more clearly, step by step, or more tersely, but it
may not change what the rule says or the answer vocabulary.

**Two cloud improvers, because the brief says "experiment widely" — and one of them
is a measured dead end.** The same loop was pointed at two authors:

| | provider | model | what happened |
|---|---|---|---|
| A | MiniMax | MiniMax-M3.1-Flash | **every call answered `HTTP 401 token is required`** — 10 calls, both tasks, 0 usable edits. The credential lives in the seat's local auth store and the API rejects it; recorded, not retried |
| B | Groq | `gpt-oss-120b` | the working improver, on both tasks |

The Groq client reports the tokens, the seconds and the **dollar cost of every call**, and
the bill is written next to the curve it bought.

<!-- E4 RESULTS:START -->
**E4 — the cloud improver**, every run, including the ones whose credential failed. An edit is kept only if the paired calibration score improves; every proposal is recorded with its outcome, win or lose — the tiles contract applied to the harness itself.

| run | task | provider | model | edits proposed | kept | baseline held-out | final held-out | best seen | p (final vs baseline) | final harness wording (truncated) |
|---|---|---|---|---|---|---|---|---|---|---|
| scenes · MiniMax (credential dead) | scenes | minimax | MiniMax-M3.1-Flash | 5 | 0 | 0.9800 | 0.9800 | 0.9800 | — | Agent A's best action by this rule: hide if an enemy is visi… |
| tiles · MiniMax (credential dead) | tiles | minimax | MiniMax-M3.1-Flash | 5 | 0 | 0.5167 | 0.5167 | 0.5167 | — | Which scripted tile should the rig play now? Pick the one wh… |
| scenes · Groq gpt-oss-120b | scenes | groq | 120b | 5 | 1 | 0.9800 | 0.9900 | 0.9900 | — | Agent A's best action by this rule: hide if there exists an … |
| tiles · Groq gpt-oss-120b | tiles | groq | 120b | 5 | 1 | 0.5167 | 0.5667 | 0.5667 | — | Which scripted tile should the rig play now? Pick the one wh… |

**Every edit the cloud proposed.** `value` is the proposed harness change; `delta` is the paired calibration score after applying it.

| run | round | field | proposed value | score before | score after | kept | reason | cloud (ms) |
|---|---|---|---|---|---|---|---|---|
| scenes · MiniMax (credential dead) | 2 | — | — | 0.9800 | 0.9800 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| scenes · MiniMax (credential dead) | 4 | — | — | 0.9800 | 0.9800 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| scenes · MiniMax (credential dead) | 6 | — | — | 0.9800 | 0.9800 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| scenes · MiniMax (credential dead) | 8 | — | — | 0.9800 | 0.9800 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| scenes · MiniMax (credential dead) | 10 | — | — | 0.9800 | 0.9800 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| tiles · MiniMax (credential dead) | 2 | — | — | 0.5167 | 0.5167 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| tiles · MiniMax (credential dead) | 4 | — | — | 0.5167 | 0.5167 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| tiles · MiniMax (credential dead) | 6 | — | — | 0.5167 | 0.5167 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| tiles · MiniMax (credential dead) | 8 | — | — | 0.5167 | 0.5167 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| tiles · MiniMax (credential dead) | 10 | — | — | 0.5167 | 0.5167 | **no** | empty cloud response ({'stop_reason': None, 'raw_keys': [],  | 0.0000 |
| scenes · Groq gpt-oss-120b | 2 | — | — | 0.9800 | 0.9800 | **no** | did not improve the calibration score | 1160.0000 |
| scenes · Groq gpt-oss-120b | 4 | — | — | 0.9800 | 0.8200 | **no** | did not improve the calibration score | 1710.0000 |
| scenes · Groq gpt-oss-120b | 6 | — | — | 0.9800 | 0.9700 | **no** | did not improve the calibration score | 960.0000 |
| scenes · Groq gpt-oss-120b | 8 | — | — | 0.9800 | 0.9900 | yes | improved the calibration score | 1370.0000 |
| scenes · Groq gpt-oss-120b | 10 | — | — | 0.9900 | 0.7400 | **no** | did not improve the calibration score | 1470.0000 |
| tiles · Groq gpt-oss-120b | 2 | — | — | 0.5167 | 0.5667 | yes | improved the calibration score | 2490.0000 |
| tiles · Groq gpt-oss-120b | 4 | — | — | 0.5667 | 0.5333 | **no** | did not improve the calibration score | 2040.0000 |
| tiles · Groq gpt-oss-120b | 6 | — | — | 0.5667 | 0.5167 | **no** | did not improve the calibration score | 2210.0000 |
| tiles · Groq gpt-oss-120b | 8 | — | — | 0.5667 | 0.5333 | **no** | did not improve the calibration score | 2140.0000 |
| tiles · Groq gpt-oss-120b | 10 | — | — | 0.5667 | 0.5000 | **no** | did not improve the calibration score | 2160.0000 |

**The held-out outcome of each run's final harness.**

| run | task | baseline | final | McNemar p |
|---|---|---|---|---|
| scenes · MiniMax (credential dead) | scenes | 0.9800 | 0.9800 | — |
| tiles · MiniMax (credential dead) | tiles | 0.5167 | 0.5167 | — |
| scenes · Groq gpt-oss-120b | scenes | 0.9800 | 0.9900 | — |
| tiles · Groq gpt-oss-120b | tiles | 0.5167 | 0.5667 | — |

**What the four runs say.**

1. **The MiniMax credential is dead on this box.** All 10 calls across both tasks answered `HTTP 401 token is required`. The runs completed (the loop treats a failed proposal as a rejected edit) and their curves are flat at the baseline — 0.9850 on scenes, 0.5167 on tiles. Recorded as a dead end, not retried: the credential lives in the seat's local auth store and the API rejects it.
2. **The Groq improver (gpt-oss-120b) proposes real edits, and the paired gate rejects four of five on each task.** Scenes: 0.9850 → 0.9900 (one kept, discordant 1/0, p = 1.0); the rejected edits include a 0.99 → 0.74 collapse that the gate stopped. Tiles: 0.5167 → 0.5667 (one kept, discordant 4/1, p = 0.375); four rejected, the worst a 0.5667 → 0.50.
3. **Both kept gains are inside the noise at these n.** 100 held-out scenes, 60 held-out tile cases; a 1-in-100 and a 3-in-60 improvement are what one good edit buys, and neither reaches significance. The curve over rounds is a step (the one kept edit) followed by flat — not a climb.
4. **The mechanism the brief asked for is the part that worked.** The cloud read the failures, proposed plausible harness edits, the paired score arbitrated, and every edit is in the record with its outcome. H8's *compounding* is not supported at this n — two tasks, ten proposals — but the contract is: keep every edit with its result, and the harness can only ratchet.
<!-- E4 RESULTS:END -->

---

## 7. E5 — precision keyframes: cheap steps with periodic BF16 resyncs

**The brief's ADDENDUM (Casey, 2026-10-31):** "Where state carries across steps
(d1/LFM recurrent state across a sequence of decisions; a multi-step loop), run cheap steps
(Q4/FP4) with periodic BF16 'keyframe' steps that resync the state, every N steps or when
drift (confidence drop, disagreement with the last keyframe) triggers one. Report quality
vs N vs cost, and fixed vs drift-triggered."

**The task.** T4 "patrol" (§2.3): last-mile's grid world played as an episode. Each tick
the model sees the current facts plus a rolling 5-tick log of what was chosen and whether an
enemy was visible, and answers the same `action` question; the chosen action then **moves the
agent**, so a wrong action changes the world the later ticks are decided in — and the wrong
action itself is what the log carries. Two things carry across steps, and the experiment
separates them: the **harness state** (the log the later prompts are built from) and the
**world state** (the agent's position). The runtime's prompt cache — the *internal* state
lever — is on (`--cache-ram 8192`), and its counters are read; E3c already found they never
move on the decision path, and E5 inherits that finding.

**The arms.** The proposer is d1-omni-600M-Q4 (cheap, and wrong often enough for drift to
matter); the keyframer is **d1-2B-BF16** — not the 600M at BF16, because E1's 27
within-size precision pairs say the same weights at higher precision give the same answers,
so a same-model keyframe would be a no-op by construction. The keyframer must be the bigger
model for the arm to mean anything.

| arm | what answers each tick | BF16 share |
|---|---|---|
| `bf16-all` | 2B BF16, every tick (the reference) | 100 % |
| `q4-all` | 600M Q4, every tick (the drift case) | 0 % |
| `q4-nohist` | 600M Q4, every tick, **log removed from the prompt** (the control) | 0 % |
| `kf-10` / `kf-5` | 600M Q4, except every Nth tick: 2B BF16, whose answer is what the log records | 10 % / 20 % |
| `kf-drift@τ:drop` | 600M Q4 always asked; a 2B BF16 keyframe overrides when conf < τ (level) or conf falls by > drop in one tick (rate) | measured |

The memory rule holds throughout: one model server at a time, swapped whenever the model
that must answer the current tick changes (loads are counted; a load is ~1–2 s on this box).
Worlds advance in lockstep so the swap count is bounded; the enemies' script is seeded per
world and identical across arms, so arms differ only through their own actions.

**The scoring.** Per-tick accuracy against the rule at that tick's live state; accuracy on
ticks whose 5-tick history window carries no wrong action (**clean**) vs ticks it does
(**dirty**) — the compounding measure; mission outcomes (beacon reached, ticks in enemy
sight); and cost: BF16 calls per 100 ticks, wall time, server loads, and an energy figure
*derived* from E1's measured J/decision (0.873 J for 600M-Q4, 2.539 J for 2B-BF16), labelled
derived because this run did not re-measure the rail.

<!-- E5 RESULTS:START -->
**E5 — precision keyframes on T4 patrol.** Per arm: accuracy over all ticks; accuracy on ticks whose K-tick history window carries no wrong action (**clean**) vs ticks it does (**dirty**); the BF16 share of the ticks; loads (one model server at a time, swapped whenever the answering model changes); p50 ms/tick; the energy column is *derived* from E1's measured J/decision (0.873 J for 600M-Q4, 2.539 J for 2B-BF16), not measured in this run.

| arm | ticks | acc | acc clean | n clean | acc dirty | n dirty | BF16 share | keyframes/100 | loads | p50 ms/tick | wall (s) | J (derived) | beacon reached | ticks to reach |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bf16-all | 180 | 0.9778 | 0.9880 | 166 | 0.8571 | 14 | 1.0000 | 100.0000 | 1 | 82.2200 | 14.4000 | 457.0000 | 4 | 5.7500 |
| q4-all | 180 | 0.6833 | 0.9836 | 122 | 0.0517 | 58 | 0.0000 | 0.0000 | 1 | 70.2400 | 10.8000 | 157.1000 | 6 | 8.6700 |
| q4-nohist | 180 | 0.6833 | 0.9836 | 122 | 0.0517 | 58 | 0.0000 | 0.0000 | 1 | 23.9100 | 8.4000 | 157.1000 | 6 | 8.6700 |
| kf-10 | 180 | 0.7167 | 0.9836 | 122 | 0.1552 | 58 | 0.1000 | 10.0000 | 6 | 70.4300 | 23.1000 | 187.1000 | 6 | 9.0000 |
| kf-5 | 180 | 0.7444 | 0.9836 | 122 | 0.2414 | 58 | 0.2000 | 20.0000 | 12 | 71.5600 | 37.5000 | 217.1000 | 6 | 9.8300 |
| kf-drift@0.60:0.10 | 180 | 0.8667 | 0.9718 | 142 | 0.4737 | 38 | 0.2167 | 21.6700 | 52 | 71.2400 | 120.9000 | 256.2000 | 4 | 5.7500 |
| kf-drift@0.75:0.05 | 180 | 0.8833 | 0.9724 | 145 | 0.5143 | 35 | 0.3556 | 35.5600 | 58 | 74.9100 | 136.3000 | 319.6000 | 4 | 5.7500 |
| kf-drift | 180 | 0.9556 | 0.9675 | 154 | 0.8846 | 26 | 0.9389 | 93.8900 | 60 | 84.5300 | 154.6000 | 586.2000 | 4 | 5.7500 |

**Fixed keyframes, quality vs N vs cost.** Accuracy rises monotonically with the BF16 share — 0 %: 0.6833, 10 %: 0.7167, 20 %: 0.7444, 100 %: 0.9778 — but *sub-linearly*: a fifth of the BF16 spend buys a quarter of the gap (0.0611 of 0.2945). The mechanism is in the clean/dirty columns: the 600M is at 0.9836 on clean-history ticks and **0.0517** on dirty ones — one wrong action in the log and the next five ticks are nearly all wrong, because the wrong *move* put the world in a state the cheap model mishandles. A keyframe every N ticks buys exactly its window: dirty-window accuracy climbs 0.0517 → 0.1552 (N=10) → 0.2414 (N=5) as keyframes come twice as often.

**The carried state that matters is the world, not the log.** `q4-nohist` — the same arm with the history log *removed from the prompt* — is identical to `q4-all` on **all 180 choices** (the confidences differ on 174 of 180 ticks, so the prompts really did differ). The 600M's choice ignores the tick log entirely; its damage runs through its own *moves*. So the resync a keyframe must deliver is a better action — which the 2B BF16 keyframer supplies — and *not* a cleaner prompt, which on this model would be a no-op.

**Drift-triggered vs fixed.** The drift trigger is the TIME-FIRST pair (level: conf < τ; rate: conf falls by more than `drop` in one tick) applied to the proposer's own confidence, and the settings span its whole range. At τ = 0.90 it fires on 94 % of ticks (161 level + 109 rate triggers over 180 ticks) and the arm degenerates into `bf16-all` with extra steps: 0.9556 at a 0.939 BF16 share. Tuned to the proposer's actual confidence range, it does what the addendum hoped: `kf-drift@0.60:0.10` fires on 22 % of ticks and reaches **0.8667 at a 0.217 BF16 share — the same spend as `kf-5` (0.20) for +0.1223 accuracy**, and past `kf-10` (0.10 share, 0.7167) on both axes. `kf-drift@0.75:0.05` continues the frontier (0.8833 at 0.356). So the trigger *does* place keyframes where they matter — after a wrong move the 600M's confidence drops, the trigger fires, and the 2B resyncs the world; a fixed every-N schedule spends its keyframes blind. The caveat is the same one E2 found: the trigger works because on this sequence the proposer's confidence **does** separate its bad states from its good ones (unlike the 600M on isolated scenes, §3.6) — and τ must be tuned to where that separation actually sits (0.90 was 4× too generous).

**What a keyframe can and cannot do on this stack.** A same-model-higher-precision keyframe would be a no-op (E1: 27 within-size precision pairs, 0 significant), so the keyframer has to be the bigger model — and then the trade is ordinary cascade economics priced per tick: the 2B BF16 keyframer costs 2.539 J against the 600M Q4's 0.873 J per decision (E1's joules pass), so `kf-5` costs ~1.23 J/tick derived against `bf16-all`'s 2.54 and buys 0.7444 against 0.9778. The runtime prompt cache did not engage (the E3c finding holds here too: the counters read zero), so there is no *internal-state* resync to be had in this build — the keyframe resyncs the harness-level state only.
<!-- E5 RESULTS:END -->

---

## 8. The TIME-FIRST gate: level vs rate vs both, on the recorded d1 traces

**The brief (2026-10-31):** "compare core/judge's level gate (confidence < τ, with
hysteresis) against a rate gate (escalate when d/dt of confidence or of disagreement crosses
a band), and against both together. Measure catch, false alarms and how many ticks earlier
each one fires."

**The traces, imported read-only.** The 240-tick (6 trials × 40 steps) sea-state recordings
of d1-2B (builder-ide's committed distillation, `docs/lab/hysteresis-scripts/results/
d1-2B-ticks.json`) and d1-3B (the liquid study's raw `exp_c_trace_d1-3B.json`). Each tick
carries the recorded probability vector, the model's confidence, and the ground truth. This
is offline: no GPU, no server, no lock.

**The gates.** The level arm is builder-ide's own code, imported, not reimplemented:
`core.judge.gate.ConfidencePolicy` (what ships today) and `core.hysteresis.HysteresisGate`
at the shape the hysteresis sweep itself chose (τ* = 0.7 for both models; band 0.15, dwell_up
2 for the 2B; band 0, dwells 2/2 for the 3B). The rate arms are new: escalate while the
confidence falls faster than r per tick, or while successive recorded distributions move more
than b of probability mass (total-variation distance), each with a sustain window of 1–3
ticks. Their thresholds are chosen by the sweep's own rule mirrored — best catch of
misreadings subject to escalating at most half the ticks — and the grids were set from the
traces' measured dynamics (the confidence drops > 0.05 on ~35 % of ticks; the median TV
distance between successive predictions is 0.63–0.72, so a useful disagreement band starts
at half the distribution). "Both together" is measured as OR (the safety reading) and as AND
(the precision reading).

**The earliness metric.** A *misreading event* is a maximal run of ticks whose recorded
argmax disagreed with the shown letter — the same E1-style calibration question the
hysteresis sweep measured catch against. A gate's firing tick for an event is its first
escalation in [event start − 10 ticks, event end]; earliness is event start minus firing
tick, so positive means *before* the model was actually wrong. The number that answers the
brief is the pairwise comparison on the events both gates catch, because every gate here is
up often enough that a 10-tick window nearly always contains *some* escalation.

<!-- TIMEFIRST RESULTS:START -->
**The gates, per model.** `earliness` is measured against misreading events (maximal runs of ticks whose recorded argmax disagreed with the shown letter): a gate's firing tick is its first escalation in [event start − 10 ticks, event end], so positive earliness means it fired *before* the model was actually wrong. The pairwise table underneath is the one that answers the brief's question — on the events *both* gates catch, who fires first.

| model | gate | escalation | catch | false alarms | events caught | of | earliness mean (ticks) | earliness median | fired before the event |
|---|---|---|---|---|---|---|---|---|---|
| d1-2B | level-hyst (the sweep's choice) | 0.4083 | 0.5625 | 0.3846 | 20 | 22 | 5.6000 | 5 | 18 |
| d1-2B | rate-conf (chosen) | 0.4167 | 0.3438 | 0.4279 | 15 | 22 | 6.6670 | 6 | 14 |
| d1-2B | rate-dis (chosen) | 0.4792 | 0.2812 | 0.5096 | 15 | 22 | 6.3330 | 6 | 14 |
| d1-2B | rate-any (conf OR dis) | 0.6583 | 0.4688 | 0.6875 | 16 | 22 | 7.5000 | 10 | 15 |
| d1-2B | both-OR (level OR rate) | 0.8292 | 0.8438 | 0.8269 | 22 | 22 | 7.4090 | 10 | 20 |
| d1-2B | both-AND (level AND rate) | 0.2375 | 0.1875 | 0.2452 | 9 | 22 | 6.2220 | 6 | 9 |
| d1-3B | level-hyst (the sweep's choice) | 0.5167 | 0.5657 | 0.4823 | 36 | 38 | 6.6940 | 8 | 33 |
| d1-3B | rate-conf (chosen) | 0.4125 | 0.4040 | 0.4184 | 33 | 38 | 7.3030 | 9 | 30 |
| d1-3B | rate-dis (chosen) | 0.4875 | 0.4444 | 0.5177 | 36 | 38 | 7.1670 | 9 | 32 |
| d1-3B | rate-any (conf OR dis) | 0.6875 | 0.6970 | 0.6809 | 38 | 38 | 7.5260 | 9 | 34 |
| d1-3B | both-OR (level OR rate) | 0.8750 | 0.8788 | 0.8723 | 38 | 38 | 8.1320 | 10 | 36 |
| d1-3B | both-AND (level AND rate) | 0.3292 | 0.3838 | 0.2908 | 33 | 38 | 5.8180 | 6 | 28 |

| model | comparison (A vs B) | events both catch | A earlier by (mean ticks) | median | A earlier on | B earlier on | tie |
|---|---|---|---|---|---|---|---|
| d1-2B | rate-any vs level-hyst | 14 | 0.5000 | 0 | 6 | 5 | 3 |
| d1-2B | rate-conf vs level-hyst | 13 | -0.6920 | -1 | 3 | 7 | 3 |
| d1-2B | rate-dis vs level-hyst | 13 | -0.8460 | -1 | 6 | 7 | 0 |
| d1-2B | both-OR vs level-hyst | 20 | 1.5500 | 0 | 6 | 0 | 14 |
| d1-3B | rate-any vs level-hyst | 36 | 0.7220 | 0 | 11 | 15 | 10 |
| d1-3B | rate-conf vs level-hyst | 31 | -0.1290 | 0 | 11 | 15 | 5 |
| d1-3B | rate-dis vs level-hyst | 34 | 0.1470 | 0 | 11 | 14 | 9 |
| d1-3B | both-OR vs level-hyst | 36 | 1.3610 | 0 | 11 | 0 | 25 |

**The rate gate is not a time-first gate on these traces.** On the events both gates catch, the median first-firing difference between the rate signal and the level standing is **0 ticks** on both models, and the means are −0.85 to +0.72 ticks. The derivative of the confidence does not lead the level crossing by any usable margin on the sea-state dynamics.

**What the rate signal buys is coverage, and it pays for it in traffic.** Chosen under the same budget rule as the level gate's τ (best catch subject to escalating ≤ 50 % of ticks), each rate arm alone catches *less* than the level standing (2B: 0.34/0.28 vs 0.56; 3B: 0.40/0.44 vs 0.57). Composed (`rate-any`, level OR the two rate signals) catch rises to 0.47/0.70 — at 0.66–0.69 escalation. The full OR catches **every event on both traces** (22/22 and 38/38) at 0.83–0.88 escalation: a gate that always speaks catches everything, exactly the trap the hysteresis note warned about. The AND composition cuts escalation to 0.24–0.33 and loses more catch than it saves traffic (0.19 on the 2B).

**So the TIME-FIRST answer is: keep the level gate with hysteresis.** It is at the frontier of this trace's dynamics — no cheaper gate catches what it catches (0.56 at 0.41–0.52 escalation), and no more expensive gate buys time, only coverage. The one honest caveat: both traces are one task (sea-state) at 240 ticks per model; a task whose confidence decays *slowly* ahead of its argmax flips would favour the derivative, and that task is not in this corpus.
<!-- TIMEFIRST RESULTS:END -->

---

## 9. Verdict per hypothesis

Each hypothesis from §1, with the number that decides it. "Killed" means the measurement
contradicts the hypothesis; "confirmed" means the measurement supports it; "refined" means it
holds but the mechanism behind it is different from what was claimed.

| # | verdict | the number that decides it |
|---|---|---|
| **H1** | **killed** | 27 precision-vs-precision pairs within a model size: **0** significant at p < 0.05, smallest p = 0.18. On T1 all nine cells score *identically* to the fourth decimal. |
| **H2** | **killed** | Q4 is **1.30–1.51× slower** than BF16 for the 600M and the 2B on T1. 4-bit buys memory on this box, not speed. |
| **H3** | **confirmed, and refined** | The 2B beats the 3B on T1 (0.985 vs 0.880; 22 discordant one way, 1 the other, p = 6×10⁻⁶). Size decides — but **the middle model wins**, and precision does not decide at all. |
| **H4** | see below | §4 |
| **H5** | see below | §3.6, §4.7 |
| **H6** | see below | §5 |
| **H7** | see below | §5.1 |
| **H8** | see below | §6 |
| **H9** | see below | §7 |
| **H10** | see below | §8 |

### H1 — killed: there is nothing for a decision model to clean up

Casey's intuition is that a decision model in the loop can "clean up what was less precise".
For that to have a referent, the less-precise model has to be *worse*. It is not. Over 27
paired precision comparisons within a model size, **not one pair is distinguishable from another
at p < 0.05**, and on T1 the accuracy figures are identical to the fourth decimal across all
three precisions of all three sizes.

This is a negative result about the *premise*, not about the loop. The loop itself is measured
in §4, and it works — but it works on the model's **errors**, not on its **quantisation**.

### H2 — killed: 4-bit is a memory lever, not a speed lever

For the two smaller models, Q4 is **slower** end to end than BF16 (T1 p50: the 600M 41.91 ms
vs 27.78 ms, the 2B 129.17 ms vs 99.00 ms). The decision path is not matmul-bound; it is bound
by the decision head, the launch overhead and the memory traffic of the state, none of which
quantisation touches. The same lesson builder-ide's IDEAS.md already recorded for FP4 on the
tensor cores — "the dtype exists, the path does not" — now shown for the *quantised decision
path* end to end.

The corollary is the useful half: **precision buys memory, and memory buys residency.** The
BF16 cells cost 3.3–4.5 GB more resident than their Q4 twins (the 2B: 14.76 GB vs 11.49 GB;
the 3B: 16.59 GB vs 13.02 GB), which on a 122 GB box with no swap is the difference between
three models resident and five.

### H3 — confirmed, and refined: size decides, precision does not, and the middle model wins

The 2B beats the 3B on T1 by 22 discordant items to 1 (McNemar p = 6×10⁻⁶) — an independent
replication of last-mile's D62 (0.96 vs 0.84, 26 vs 2, over 200 fresh paired scenes). The
refinement is that the biggest model is not the best model: the 3B is worse on T1 *and* on T2,
and the 600M ties the 2B on T2 (0.667) while being the worst model on T1.

<!-- VERDICTS H4-H10:START -->
### H4 — refined: the loop recovers the gap only where the gate can fire, and it works on errors, not on precision

T1: 0.9850 → **1.0000** (`jev-noul`, gate 0.6, 4 % escalated, 3/3 errors caught, 0 broken) — the loop lands exactly on the ceiling §4.1 computed from the E1 rows alone. T3: 0.4500 → **0.6667** (`jev`, gate 0.9; p = 0.000508 at gate 0.6) while the big model alone scores 0.3250 — the cascade passes the top of the ladder. T2 is the counterexample: 0.6667 → 0.7451 is real but small, and §4.1 says why (the gate catches 2 of 17 errors at 0.60). And because H1 is killed — precision changes nothing — the loop's raw material is the model's *errors*, never its quantisation. **Where the proposer's confidence does not rank its errors, no checker can help (T2); where it does, almost any competent checker helps (T1), and a better decider can carry a whole task (T3).**

### H5 — refined, and it splits twice: by model *and* by task

The 2B on T1 is the perfect case: 100 % of its errors sit below confidence 0.5 (Brier 0.0262), so the gate catches all of them with 2 % of the traffic. The 600M on T1 is the dead case: mean confidence 0.9733 at 0.4150 accuracy (ECE 0.5583), the gate fires on 0 of 200 items. The 2B on T2 is the subtle case: the confidence *ranks* — but wrongly (confident half 0.6400 vs unsure half 0.6923), so no threshold helps. **Calibration is a property of (model × task), it is cheap to measure in advance (Brier + ECE + the halves), and it decides whether to build a loop at all.**

### H6 — killed: the big model's harness pick does not transfer down, and its exemplars hurt

Across four runs (2 small models × default/balanced exemplars), the big model's pick never beats the small model's uncalibrated baseline on the held-out split, and on the 600M-defects cell it lands far below it (0.7308 → 0.1538, p = 6.1×10⁻⁵). The oracle wording — the one the *small* model scores best — is also never above uncalibrated, so the wordings are not the lever on these tasks at all. The mechanism of the harm is visible: the exemplars come from the big model's own confident-and-correct answers, which the small model cannot imitate, and on defects they teach it to name defects where the truth is `none`. **Handing a small model a big model's habits is not calibration; on this evidence it is corruption.**

### H7 — killed on this stack: the decision endpoint does not use the prompt cache

With `--cache-ram 8192`, `--cache-reuse 256` and `--slot-prompt-similarity 0.5` all set, llama.cpp's own counters read zero before and after every pass, on both tasks, in all four configurations; the latency does not move (126.4 → 129.5 ms p50 on scenes); the answers are identical (McNemar p = 1.0 everywhere). The levers exist in the server, the server's log even announces the cache is off by default for decision models — and turning it on changes nothing measurable, because the one-forward-pass decision path never populates the cache counters. **The internal-state lever the brief names is a builder-side feature request, not a knob this build exposes.** E5's patrol prompts (a fixed world intro shared by every tick) are the workload that would benefit if it ever exists.

### H8 — the mechanism works, the compounding is not supported at this n

The MiniMax credential answered 401 on every call (both tasks, 10 attempts) — recorded, not retried. The Groq improver (gpt-oss-120b) proposed 10 edits across the two tasks; the paired gate kept 2 and rejected 8, including a 0.99 → 0.74 and a 0.5667 → 0.50 that would have shipped uncritically. The kept edits bought 0.9850 → 0.9900 (scenes, p = 1.0) and 0.5167 → 0.5667 (tiles, p = 0.375) — inside the noise at 100 and 60 held-out items. The curve over rounds is one step then flat. **The contract is the deliverable: every cloud edit kept with its outcome, kept only when the paired score improves — a harness that can only ratchet. Whether it compounds needs more tasks and more rounds, not a different design.**

### H9 (the addendum's keyframes) — confirmed and refined: compounding is real, drift-triggered beats fixed at matched cost, and the resync that matters is the action, not the log

On T4 patrol, the 600M Q4's accuracy splits 0.9836 (clean history) vs **0.0517** (history carries a wrong action): one wrong move corrupts the world for the whole window. Keyframes from the 2B BF16 raise accuracy with their frequency (10 %: 0.7167; 20 %: 0.7444; 100 %: 0.9778). The drift trigger is the winner: tuned to the proposer's measured confidence range (`kf-drift@0.60:0.10`) it fires on 22 % of ticks and reaches **0.8667 — +0.1223 over the fixed schedule at the same BF16 spend (0.217 vs 0.20)**, because after a wrong move the confidence drops, the trigger fires, and the keyframe lands where the sequence is already corrupted; a fixed every-N schedule spends its keyframes blind. The `q4-nohist` control is identical to `q4-all` on all 180 choices — the 600M ignores the tick log, so the damage and the rescue both run through the *moves*. **Keyframe the sequence when the proposer is right most of the time and cheap; prefer a drift trigger with τ tuned to the proposer's measured confidence range (τ = 0.90 was 4× too generous and fired on 94 % of ticks); and expect the trigger to work exactly when E2's gate works — where the confidence ranks the model's own trouble.**

### H10 (the TIME-FIRST gate) — killed as a time lever; it is a coverage lever that costs traffic

On the recorded 240-tick traces (both models), the rate signal — d/dt of confidence, or the TV distance between successive predictions, thresholds chosen under the level gate's own budget rule — does not fire earlier than the level+hysteresis standing on the events both catch (median 0 ticks, means −0.85 to +0.72). Alone it catches less than the level gate at the same budget; composed with it (OR) it catches every event on both traces at 0.83–0.88 escalation; composed with AND it loses more catch than it saves traffic. **Keep the level gate with hysteresis; buy coverage with a second gate only if you can afford the traffic, and do not buy the derivative for speed it does not have on this task's dynamics.**
<!-- VERDICTS H4-H10:END -->

## 10. What to build into builder-ide

The ranking is by **payoff per unit of engineering**, and every line is a consequence of a
number above, not a preference. Each entry names the Thor feature it leans on and the smallest
thing that would prove it in the product. The rules builder-ide already follows are respected:
no LLM on the Thor, the cloud is the author, the Thor is the player and the learner, and every
claim carries its number.

**1. Serve d1-2B as the fast decision tier, and keep d1-3B out of the gate.**
The 2B scores 0.985 on T1 against the 3B's 0.880 (22 discordant items to 1, p = 6×10⁻⁶) and
beats it on T2 as well; the 3B's *confidence* is also the least reproducible number on the box
(§3.3: it moves by 1.6 % between two designs and flips 4 of 200 predictions, where the 2B's is
bit-identical). The 3B also costs more energy per decision (3.32 J against 2.54 J at BF16) —
but it draws *less* power while doing it (21.2 W against 24.0 W), so its extra energy is
latency, not hunger. **The bigger model is worse, slower, less reproducible and no cheaper.**
builder-ide's `core/judge/gate.py` already starts its ladder at d1-2B; the change is to take
d1-3B out of the gate's rungs entirely and leave it, at most, as a writer of harnesses.
*Thor feature:* unified memory — the 3B's extra 3.5 GB of residency buys nothing here.
*Smallest proof in the product:* swap the ladder's rungs and re-run the paired-scene set; the
number must not move down.

**2. Make the gate's threshold per (model, task), and measure the proposer's calibration before
you trust the gate at all.**
The same 2B, the same gate, three tasks: on T1 a threshold of 0.5 catches **100 %** of its
errors with **2 %** of the traffic; on T2 the same gate catches **12 %** of them; on T3 it
catches 80 % but escalates **67 %** of the traffic. One τ cannot serve three tasks, and the
per-task answer is computable in advance (§4.1). And the gate is only as good as the confidence
under it: the 600M's confidence is *anti-correlated* with its correctness (§3.6). So the policy
should be — **measure the proposer's Brier score first; gate only if the confidence ranks its
errors.** That is the library's #15 and #62, and builder-ide's `core/judge/gate.py` already
takes τ per (backend, model, task): what it is missing is the calibration check that decides
*whether* to gate.
*Thor feature:* none — this is a policy, and it costs a counter.
*Smallest proof in the product:* record (confidence, correct) per decision per (model, task),
and have the gate refuse to fire when the recent Brier score says the confidence is not
informative.

**3. Spend the cloud's calls only where the local model is weak *and* the gate still works.**
On T1 the 2B's gate escalates 4 % of the items and the cloud judge is right on every one of
them — eight calls to fix three errors. On T3 the gate escalates two-thirds of the traffic, so
the local checker should take the band and the cloud should take the bottom. On T2 the gate
cannot find the errors at all, so **no** checker helps and the right answer is to fix the
proposer or the task, not to buy a bigger judge. That is the tiered gate: local, promoted to
higher precision, cloud triage (§4.5) — and it is the routing the library's #2, #3 and #5
describe, now with the prices attached.
*Thor feature:* the ladder in `core/judge/gate.py` is already the shape; what it needs is the
measurement of where each rung is worth its round trip.
*Smallest proof in the product:* give the ladder a per-task escalation budget and log what each
rung bought.

**4. Measure the 600M's temperature before deciding it is unusable.**
The 600M-first cascade is dead on T1 for a structural reason — its gate fires on **0 of 200**
items (§4.1) — and D62 rejected it for the same reason from the other direction. But the
600M's *decision temperature* is 1.3999 (the `choice.3_5` bucket) and the temperature is
exactly the knob that trades sharpness against calibration (§5.2). If some temperature makes
its confidence rank its errors, the cheapest model on the box becomes a usable first tier; if
not, it stays off the decision path and that is now a measured decision rather than a habit.
*Thor feature:* none; the knob is a float32 in the model's own metadata.
*Smallest proof in the product:* the temperature sweep of §5.2, on the 600M, on T1 and T3.

**5. Serve BF16 by default; reach for Q4 only to fit more models.**
BF16 is **faster** than Q4 on this path (the 600M 27.78 ms against 41.91 ms; the 2B 99.00 ms
against 129.17 ms) *and* it costs **less energy per decision** (0.581 J against 0.873 J; 2.539 J
against 3.662 J), because the decision path is not matmul-bound and the quantisation only adds
dequantisation work. The price is residency: 10.9 GB against 10.4 GB for the 600M, 14.1 GB
against 13.1 GB for the 2B, 17.6 GB against 12.1 GB for the 3B. On a 122 GB box with no swap,
**Q4 buys residency and nothing else** — so the choice is "how many models do I want resident",
not "which is faster".
*Thor feature:* unified memory with no swap; the 3B at BF16 is 17.6 GB peak, and two of them
fit.
*Smallest proof in the product:* serve the ladder at BF16 and count what stays resident.

**6. Turn the prompt cache on only where the prefix repeats.**
The runtime's prompt cache is **off by default for decision models** — the server says so, and
`--cache-ram` turns it on. Whether it is worth anything depends on whether the prefix is
shared between calls, which is a property of the harness, not of the model (§5.1).
*Thor feature:* `--cache-ram`, `--cache-reuse`, `--slot-prompt-similarity`, all already in the
build this box serves from.
*Smallest proof in the product:* read `llamacpp:prompt_tokens_cached_total` beside the
latency of the real decision path.

**7. Treat the harness as a tile: keep every cloud edit with its outcome, win or lose.**
The cloud's edits are proposals; the paired score is the play; the outcome is the label. A
harness that keeps its losses is a harness that can be evaluated, compared and rolled back —
the same contract `core/tiles/` already gives the scripts (§6).
*Thor feature:* none.
*Smallest proof in the product:* the edit log of E4, written where the tiles' outcomes are
written.

**8. Keyframe the sequence with the model that decides — drift-triggered, τ tuned to the
proposer's confidence — and resync the action, not the log.**
On the patrol task, one wrong cheap-model action collapses the next five ticks to 0.05
accuracy, and the keyframe's entire value is the better *action* it substitutes: with the
log removed from the prompt, the 600M's 180 choices are identical (§7). So for builder-ide's
multi-step loops (the builders' world sessions, the tiles players), the cheap model can run
the ticks and the 2B BF16 keyframes on a drift trigger: **0.8667 at 21.7 % BF16 spend**,
+0.12 over a fixed every-5 schedule at the same cost, because the trigger fires after a
wrong move exactly when the sequence is already corrupted. τ must be tuned to the
proposer's *measured* confidence range (the default 0.90 fired on 94 % of ticks and
degenerated into the reference arm) — the same calibration check as item 2, over a sequence.
*Thor feature:* unified memory — both models are cheap enough to swap per tick block
(a load is ~1–2 s; E5 never held two servers at once).
*Smallest proof in the product:* a builder session run at Q4 with a drift-triggered 2B BF16
keyframe, scored by the recipe's verdict against an all-BF16 session on the same seed.

**9. Do not buy the rate gate for earliness; the level gate with hysteresis is the frontier
on these dynamics.**
On both recorded traces the derivative of the confidence fires **0 ticks earlier (median)**
than the level+hysteresis standing on shared events, and every extra point of catch it buys
comes from escalating more of the traffic — up to catching 100 % of events at 0.83–0.88
escalation, which is the always-speaking gate (§8). `core/judge`'s current policy is already
the right default; the rate signal is worth keeping only as an optional coverage rung with
its price labelled.
*Thor feature:* none — this is a gate policy, measured on the traces the replay harness
already committed.
*Smallest proof in the product:* none needed to keep the current gate; if a coverage rung is
wanted, land it behind the escalation budget of item 3.

## 11. Reproduce

```bash
cd ~/lm-wt/lab-cascade
bash scripts/drive.sh          # every heavy step, one at a time, under the lock
python scripts/verify_t1.py    # T1 == last-mile's harness, scene for scene
python scripts/report.py --which e1b
.venv/bin/python scripts/fill_report.py   # render every results section of this file
```

The driver takes the shared lock **once per step**, not once for the whole
run, so other seats get the box between steps. Inside a step there is
exactly one model server resident at a time.

| step | command | writes |
|---|---|---|
| E1b | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e1b.py` | `results/e1b-matrix-sequential.json` |
| joules | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_joules.py` | `results/e1-joules.json` |
| E2 | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e2.py` | `results/e2-escalation.json` |
| E3 | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e3.py --small d1-omni-600M-Q4 --temp-sweep 0.0,0.3,0.7,1.0 --out e3-calibration-600M.json` | `results/e3-calibration-600M.json` |
| E3 | `… --small d1-2B-Q4 --temp-sweep 0.0,0.3,0.7,1.0 --out e3-calibration-2B.json` | `results/e3-calibration-2B.json` |
| E3c | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e3c.py --task scenes` | `results/e3c-internal-state-scenes.json` |
| E4 | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e4.py --task scenes` | `results/e4-improver-scenes.json` |
| E4 | `… --task tiles` | `results/e4-improver-tiles.json` |
| E4 | `… --task scenes --cloud-provider groq --cloud-model 120b` | `results/e4-improver-scenes-groq.json` |
| E4 | `… --task tiles --cloud-provider groq --cloud-model 120b` | `results/e4-improver-tiles-groq.json` |
| E3d | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e3d_temp.py --cell d1-omni-600M-Q4 --tasks scenes,tiles` | `results/e3d-temperature-600M.json` |
| E3d | `… --cell d1-2B-Q4 --tasks scenes,tiles` | `results/e3d-temperature-2B.json` |
| E5 | `flock ~/lm-wt/heavy.lock .venv/bin/python scripts/run_e5_keyframes.py` | `results/e5-keyframes.json` |
| TIME-FIRST | `.venv/bin/python scripts/run_timefirst.py` (offline: no GPU, no server) | `results/timefirst-gates.json` |

**E5's item set** is reproducible from its `patrol_digest` (`c01cd4fce71ab8f9` over the
world seeds, the enemy scripts and the arm parameters), the same way the three task digests
below pin T1–T3.

**The venv** additionally carries `pydantic`, which `run_timefirst.py` needs to import
builder-ide's `core.judge.gate` read-only (`pip install pydantic` into `.venv`; nothing is
installed system-wide).

**The seeds.** Every number comes from three seeds — `lab.DEFAULTS["seed"]`
(20261031), `scene_seed_base` (1000, last-mile's own base) and the task
seed (20261031) — and from the three **case digests** that hash the whole
item set. If a digest matches, the item set is the same and the numbers are
comparable:

```
scenes  4294be06e06326f6
tiles   a7cb4bf3a4745c93
defects 1914cf7ce0dc1bb6
```

**The boxes.** The model server is
`~/llama.cpp-upstream/build-up/bin/llama-server` (0.8.0-dev, build 50,
commit 2e0d86b), started with `--flash-attn on --ctx-size 8192 -ub 4096
-ngl 99`, **no `--mmproj`** (all three tasks are text-only). The vision
projector is not loaded and the server answers `/v1/systemone` correctly
without it.

**The cloud.** Jev is reached through `npx -y @jkudish/jev-mcp` (MIT) over
MCP stdio, with `TYPESAFE_API_KEY` read from
`~/.config/last-mile/secrets.env` into the child's environment (never
printed; `scripts/check_creds.py` reports only names and lengths). The
cloud LLM for E4 is MiniMax through this seat's own credential, in the
seat's local auth store — the same one the runtime itself uses.

**No key is ever printed.** `cloud.py` and `jev_mcp.py` read the key into
a variable and never log it; the reports quote only the credential's
*source*, never its value.

---
