# cascade-addendum — what lab-cascade should add in its next round

**From:** the `liquid-study` seat (`~/lm-wt/liquid-study`), 2026-10-31 · **To:** lab-cascade (`~/lm-wt/lab-cascade`)
**Read first:** `~/lm-wt/lab-cascade/exp-cascade.md` (the experiment and its verdicts), `~/lm-wt/lab-cascade/BRIEF.md`,
and `~/src/builder-ide/docs/lab/IDEAS.md` Part 0 / Part B for the box's settled facts.

**This does not repeat E1–E4.** E1 is the precision ladder, E2 the cleanup loop with escalation on low
confidence, E3 the cloud-written harness and calibration, E4 the cloud improver. Everything below is a
*different* measurement on a *different* axis, or a mechanism question their brief left open. Four
items below carry findings already established from this box, so lab-cascade can take them without
re-doing the work: **C1** is a box measurement (this seat's own run); **C2** and **C3** are facts read
out of the very build lab-cascade serves (`server-decision.cpp` at commit `2e0d86b`) and the GGUF
metadata already on disk; **C5**'s projector GGUFs are verified present. One correction to an earlier
draft: C6's box check **crashed before measuring anything** — see the note inside it.

**Two facts from reading `llama.cpp` that lab-cascade's design does not yet account for** — both are
mechanism, not opinion, and both came out of `~/llama.cpp-upstream` at commit `2e0d86b`:

> **1. The three d1 models are two different architectures.** `lfm2.decision.type` / `lfm3.decision.type`
> in the GGUFs resolve to `lfm2-d1` (d1-3B, d1-omni-600M, LFM2 backbone, 32k / 128k ctx) and
> **`lfm3-d1` (d1-2B, LFM3 backbone, 128k ctx)**. d1-2B is the LFM3 model, not an LFM2 one.
>
> **2. LFM3 d1 sets `no_batching`.** In `tools/server/server-decision.cpp`, `fill_task()` sets
> `task.decision.no_batching = is_lfm3_d1();` with the comment *"the short convs of lfm3 d1 have no
> memory to separate the sequences of a batch"*. So **d1-2B — currently lab-cascade's most accurate cell
> (0.985) — cannot be batched**, while the LFM2 cells can.

---

## C1 — Separate the two latencies, because they are different numbers

**What their E1 reports.** One latency per cell, measured per decision.

**The problem.** A d1 decision has two regimes and E1's number is whichever one the harness happened
to measure:
* a **standalone** decision re-reads a fresh state, so it pays the full prefill of
  (state + question + options) plus the option scoring;
* a **shared-prefix pack** asks several questions over one state, so the first question pays the
  prefill and every extra question pays only the marginal cost of its own suffix.

The chats' "d1-3B at 16 ms" is the *second* number. This seat measured the first on d1-3B Q8 on this
box — see `liquid-study.md` §4.1 and `~/lm-wt/liquid-study/results/exp_a_latency.json` for the
decomposition and the box state beside it.

**The experiment.** Add a *pack axis* to E1's harness: for one cell (not nine), ask the same items as
1, 2, 3 and 5 questions in a single request, and report total and marginal cost. Use
`llamacpp:prompt_tokens_cached_total` from `/metrics` to prove the prefix is shared rather than
re-read.

**Why it matters to them.** E2's cleanup loop asks *several questions about one state*. That is
exactly a pack. If the marginal cost per extra question is a small fraction of standalone, the E2
harness can be restructured to ask all its questions in **one** request and the whole cleanup loop
becomes nearly free. If instead the marginal cost is near standalone, E2's cost model needs revising
and the loop should be re-architected as a *single* multi-question decision.

**Kill criterion.** None — this is a measurement. But if the ranking of cells by latency changes
between the two regimes, **E1's latency column must be published as two columns**, and any conclusion
drawn from it re-checked.

---

## C2 — d1-2B is LFM3 and cannot be batched: measure the throughput side of the ladder

**The finding.** See the boxed note above. `is_lfm3_d1()` forces `no_batching` on every decision task.

**Why it matters to them.** Their ladder concludes *"size, not precision, decides"*, and the size that
wins (d1-2B, 0.985) is the one cell that cannot be served concurrently. On a shared box with several
seats, single-sequence serving of the best model has a very different throughput profile from batched
serving of the second-best — and lab-cascade's own numbers already show d1-3B at 0.880, which is close
to d1-2B's 0.985 in a way that may not survive a concurrency change.

**The experiment.** For d1-2B (LFM3) and d1-3B (LFM2), serve the same task with `--parallel N` and
`--cont-batching` for N ∈ {1, 4, 8} and measure per-item latency and items/s. Expect d1-2B's curve to
be flat (no batching) and d1-3B's to improve.

**The deliverable.** A second table: *accuracy vs achieved throughput*, per cell. The ladder's
conclusion becomes "**d1-2B is the accuracy ceiling; d1-3B is the throughput ceiling; which one is
right depends on how many decisions the night actually makes per second**" — a much more useful
sentence than "size decides".

**Kill criterion.** If d1-2B *does* batch (the flag may be conservative), report that too — it would
mean the constraint is a server-side policy, not an architecture limit, and can be worked around.

---

## C3 — The 600M's temperature is a knob, and nobody has turned it

**The finding.** `~/models/d1-2B/d1-2B-Q8_0.gguf` carries three metadata keys lab-cascade has not used:

```
lfm3.decision.temperature.noul    = 1.3373984
lfm3.decision.temperature.choice  = 1.3373984
lfm3.decision.temperature.score   = 1.3373984
```

The decision head's output distribution is temperature-scaled, and the scale is **per question type**.
llama.cpp reads these when the model type is `lfm3-d1` (the `d1_labels` / score path in
`tools/server/server-decision.cpp`).

**Two details that change how the sweep must be run** — both from `server-decision.cpp`:

* **The temperature key is bucketed by option count.** `get_temperature()` looks up
  `"{type}.{bucket}"` first and falls back to `"{type}"`, where the bucket is `n<=2 ? "2" :
  n<=5 ? "3_5" : n<=10 ? "6_10" : "11"`. The shipped GGUF only carries the *un-bucketed* fallback
  (`lfm3.decision.temperature.choice`), so the sweep must either write the bucketed keys
  (`lfm3.decision.temperature.choice.3_5`) for the option count actually used, or accept that the
  fallback applies to every bucket.
* **On the omni model, media questions ignore the model's temperature entirely.**
  `format_answer()` sets `temperature = has_media && type == LFM2_D1_OMNI ? 1.0f : get_temperature(...)`
  — *"image and audio answers are not calibrated"*. So the temperature knob is **dead for exactly
  the cell C5 proposes to add**. Do not expect C3 and C5 to interact.

**Why it matters to them.** Their sharpest finding is *"the 600M's confidence is uncalibrated, so it
cannot gate its own escalation"* — mean confidence 0.97 at 0.415 accuracy. A temperature on the logits
is exactly the knob that trades calibration against sharpness, and it is **per question type**, so the
`choice` tasks (T1 scenes, T3 tiles) can be tuned separately from `noul`.

**The experiment.** Sweep the temperature over {0.5, 0.75, 1.0, 1.337 (default), 1.5, 2.0, 3.0} for
each of the three d1 sizes, editing only the GGUF metadata key (a local copy, never the shipped
file). For each: accuracy, **ECE with reliability bins**, Brier score, and mean confidence.

**The deliverable.** A calibration table per size: *temperature × (accuracy, ECE, Brier)*. Plus the
answer to the question their E2 needs: **at what temperature does the confidence become usable as an
escalation signal**, and does the optimal temperature differ per task?

**Kill criterion.** If ECE is flat across the sweep — i.e. the model's errors are not a sharpness
problem but a ranking problem — then no temperature makes it calibratable, and E2's escalation must be
driven by something other than this model's confidence (a disagreement between models, or the
bandit's estimate, not the 600M's).

---

## C4 — The option set is the lever nobody is measuring

**The idea.** A decision model's accuracy on a K-way `choice` question depends on the **option set**,
not only on the state. The d1 head is a classifier over exactly the options you name; more options, and
options that are semantically closer together, are harder — and more expensive.

**Why it matters to them.** All three of their tasks use a fixed option count. If the option set is a
lever, then "make the vocabulary smaller and sharper" is a *model-side* win that costs nothing to
deploy — and it is the same idea as builder-ide's `core/tiles/door.py` (the tile vocabulary admits a
tile only if the words exist) expressed in model terms.

**The experiment.** Re-score one task (T3 tiles is the natural one — it already has K=5) at K ∈ {2, 3, 5}
by re-partitioning the ground truth, and measure accuracy and latency against K. Also measure the
**label-permutation sensitivity** of the same items: ask the same question with the option keys
permuted and see whether the model's answer follows the semantics or the position. llama.cpp's `choice`
questions take the options as a dict, and `d1_labels()` derives single-token label groups from the
keys, so a permutation is a one-line change in the request.

**The deliverable.** Accuracy-vs-K and accuracy-vs-permutation, per cell.

**Kill criterion.** If the model is permutation-stable and accuracy-vs-K is flat, the option set is not
a lever and the vocabulary work should stay in builder-ide's door rather than in the model's input.

---

## C5 — Put the pixels in: d1-omni-600M can see, and no cell in the ladder does

**The finding.** Their own harness notes: *"all three tasks are text-only, and the server answers
`/v1/systemone` correctly with no projector (verified separately). One less variable."* That is a
good discipline, but it means **the vision model in the ladder never sees an image**. The
`lfm2-d1-omni` decision type supports images on the same endpoint — llama.cpp's own test suite covers
`POST /v1/systemone` with `images: [base64]`, and `decision.can_use_images()` gates it.

**Why it matters to them.** T2 is *the critic's defect classification* — and builder-ide's critic exists
because a render can be wrong in ways that text cannot describe. Every number in the ladder is
therefore measured on a proxy of the task. The `mmproj` GGUFs are already on disk
(`~/models/d1-omni-600M/mmproj-d1-omni-600M-*.gguf`).

**The experiment.** Add a **T2-vision cell**: the same 51 reference-set members, with the render
passed as an image and the defect class as the `choice` question. Compare against the scripted
checks' published FP/FN table (`core/critic/CALIBRATION.md`) — the model becomes a *second opinion on
the critic*, and the agreement table is the deliverable.

**Why this is the highest-value item in this addendum.** It is the one experiment that makes the d1
ladder's numbers mean something in builder-ide's own terms: not "the model is good at text about
defects" but "the model agrees with the critic on pixels". It is also cheap — one cell, one projector,
one existing reference set.

**Kill criterion.** If agreement with the scripted checks is no better than the 0.706 majority-class
baseline, the vision d1 does not gate the critic and the golden-core idea (this seat's route R2) dies
with it.

---

## C6 — The "cached prefix state per task" has a mechanism: use it

**What E3 asks for.** *"For Liquid, the internal state (e.g. a cached prefix state per task, prompt or
state caching in the runtime)"*.

**The mechanism, established from source.** llama.cpp's server has it, in two forms — both read out
of the tree this box serves from (`tools/server/`, commit `2e0d86b`):

* **in memory** — `--cache-ram N`. For decision models the prompt cache is **off by default**
  (`server-context.cpp`: *"decision model: prompt cache disabled by default, use `--cache-ram N` to
  enable it"*), and when enabled it restores the decision model's state — the log prints
  *"found better prompt with f_keep = 1.000"*.
* **on disk** — `--slot-save-path`, then `POST /slots/{id_slot}?action=save|restore` with a body of
  `{"filename": "..."}`.

**One correction to this addendum's earlier draft.** It said this seat had *verified* both forms on
d1-3B Q8 (citing §4.2 of `liquid-study.md` and `results/exp_b_state.json`). That run **crashed
before producing any number** — a one-line bug in the probe script, hit seconds after its server
came up; `exp_b_state.json` does not exist. What stands is the source reading above. What is
**not** measured, and what C6's experiment should treat as open: that a restore is bit-exact on
this box's d1 probabilities, the bytes per snapshot, and what `--cache-ram` actually buys. The
fixed, arity-checked script ships in `~/lm-wt/liquid-study/scripts/exp_b_state.py` — running it is
about five minutes under the heavy lock, and `liquid-study.md` §4.2 records the whole story.

Note the important distinction for calibration purposes: this is a *context* snapshot (KV + the
recurrent state), **not** an export of hidden activations. The only numeric output of a decision is the
per-option score vector. If E3's "calibration" needs numbers, the score vector and the ledger entry
are the transportable ones; the blob is for *replaying* a context, not for reading a model.

**The experiment.** For each task, after the shared state prefix is processed, save the slot; for each
subsequent item, restore it before asking. Measure the latency saved versus a cold prompt, and
confirm the answers are bit-identical to the unrestored ones.

**Why it matters to them.** E3 currently has to *guess* what a cached prefix state would buy. This
turns it into a measurement with a known-correct mechanism, and it produces the artefact (a saved
slot per task) that E3's harness can consume directly.

---

## C7 — d1-ultra exists, and the ladder's top rung may be stale

**The finding.** Liquid AI's public model line-up includes **"Open d1: Edge decision models for text,
vision, and audio"** (2026-10-07) and **"d1-ultra: the world's best decision model"** (2026-10-15).
Liquid's model page describes decision models as *"purpose-built models for classification, routing,
and scoring. One API call returns calibrated probabilities across a fixed set of outcomes."*

The ladder's three sizes (600M / 2B / 3B) predate d1-ultra.

**The experiment.** Check HuggingFace for a d1-ultra GGUF (or an official quantisation) and, if one
exists, add it as a new top rung: accuracy and latency on T1/T2/T3, with the same interleaved-block
design. If no GGUF exists, record that as a finding — it means the ceiling of "what a local decision
model can do" on this box is currently d1-2B, which is a useful boundary to state plainly.

**Kill criterion.** None — it is a coverage question. But do **not** let it delay C2, C3 or C5; the
first three change what the ladder means, this one only extends it.

---

## C8 — Fix the box-state record so the next round's absolutes are comparable

**The finding.** IDEAS.md rule 4 says: *"on a shared box, interleave the variants and publish ranges"*.
lab-cascade's E1 does interleave. But the box on 2026-10-31 made this sharper than usual: during the
window this seat ran, the box carried a lab-fp4 FP4 sweep holding `~/lm-wt/heavy.lock`, GPU
utilisation at 96–98 %, load average 7–20, and `nvidia-smi` unable to report GPU memory or SM clocks
at all (`memory.used = [N/A]`, `clocks.current.sm = [N/A]` — the fourth and fifth confirmation in
IDEAS.md).

**What this means practically.** GPU clock is not observable on this box, so the "warm the clock before
timing" rule (IDEAS.md rule 3) has to be enforced by a **burn-in** rather than by reading a clock:
keep a decision loop running for ~3 s before each timed block, and record the warm-up's request count
in the result file. This seat's `scripts/d1lab.py` does exactly that and is copyable.

**The experiment.** No experiment — a recording change. Add to each timed block: (a) the warm-up
request count, (b) `MemAvailable` before and after, (c) the VDD_GPU rail in milliwatts from
`tegrastats` (the attributable rail; the whole-box rail carries every tenant), (d) load average. Then
report medians **with the box-state range beside them**, and keep reporting the interleaved ratios,
which is what actually holds.

---

## C9 — The escalation ladder should be local-model → local-model → cloud, and the rung order is measurable

**The finding.** `exp-cascade.md` already carries Jev (cloud) as the top rung of the ladder (Jev scores
**1.00** on the `action` condition, against d1-3B's 0.97 and the 600M's 0.40), and `scripts/jev_mcp.py`
already speaks to it. `docs/research/jev.md` in builder-ide says the same thing from the other side:
Jev's twelve tools return **typed verdicts with probability distributions and a confidence**, at
150–500 ms per call — which is **the same shape as d1's** (`choice` / `score` / `noul`, probabilities plus
confidence, zero generated tokens).

**What that means.** The escalation ladder is not "small model → bigger model → bigger model". It is:

| rung | model | where | cost | note |
|---|---|---|---|---|
| 0 | d1-omni-600M | Thor | tens of ms | fast, **uncalibrated** (0.97 confidence at 0.415 accuracy) |
| 1 | d1-2B / d1-3B | Thor | tens of ms | 0.985 / 0.880 on the action gate |
| 2 | Jev | cloud | 150–500 ms + per-call cost | 1.00 on the action condition |

**The experiment.** Run the ladder as a *cascade* and measure the **cost-accuracy frontier**: for
escalation thresholds θ over the rung-0 confidence, plot (escalation rate, accuracy, seconds per
item, calls per item). The deliverable is the frontier, not a single operating point.

**The question this answers that E2 does not.** E2 asks whether escalation *recovers the gap*. It does
not ask **which rung to escalate to**, and the answer is not obvious: the 600M's confidence is useless
as a trigger (C3 may fix that), and d1-3B may not be the right rung-1 because of C2's no-batching
constraint.

**Kill criterion.** If the cascade never beats "always rung 1" on the cost axis, the ladder collapses
to a single local model plus a cloud fallback — which is a perfectly good outcome and worth saying
plainly.

---

## C10 — Soft-label distillation from Jev into a local d1 model: the real version of "cloud calibration"

**The finding.** `docs/research/jev.md` describes exactly this, already: *"Tiles: labelling play
outcomes — `jev_classify` in batches … These are the training labels for the local decision models,
**with the probability kept as a soft label**."* And *"Tiles: the shortlist — `jev_rerank` pre-ranks a
large library down to the few candidates the local decision model chooses among at play time."*

**Why this is the research route the chats were groping for.** The chats wanted "hidden-state
snapshots for cloud calibration" — ship something to the cloud, get calibration back. The mechanism
that actually works is the other way round: **the cloud model produces a probability distribution per
item, and that distribution is the training signal for the local model.** It needs no hidden state
export (the runtime does not expose one — §4.2), no wire format for activations, and no GPU-to-cloud
tensor plumbing. It needs one batch of `jev_classify` calls and a training run.

**The experiment.**
1. Take the ladder's three task sets. Run `jev_classify` (or `jev_decide`) over every item, once.
   Keep the **full probability vector**, not the argmax — that is the soft label.
2. Report the **agreement** between Jev's argmax and each local d1 model's argmax, per task, per size.
   This is a free, informative table they do not currently have: it tells you how much of Jev's
   judgement each local model has already absorbed.
3. Where agreement is low, that is the distillation set: fine-tune the local d1 model on the soft
   labels and measure whether its argmax agreement with Jev rises.
4. Re-measure the **calibration** (ECE) of the distilled local model. If the soft labels carry Jev's
   confidence structure, the distilled model's confidence becomes usable — which is exactly what C3
   tries to buy with a temperature, and probably a better buy.

**Why this is worth a round.** It is the only item on this list that could make the *local* models
good enough that the cascade (C9) rarely has to reach rung 2 — which is where the money is, since rung
2 costs 150–500 ms and a per-call fee.

**Kill criterion.** If Jev's argmax and the local model's argmax already agree on ~everything, there is
nothing to distil and the local models are already at the ceiling. If they disagree everywhere, Jev's
judgements do not transfer to the local architecture and the cloud must stay in the loop.

---

## C11 — The three d1 models report "confidence" as three different quantities

**The finding.** From `tools/server/server-decision.cpp`, `get_decision_confidence()`:

| model | decision type | confidence returned |
|---|---|---|
| d1-omni-600M | `lfm2-d1-omni` | `decision_confidence_choice(probs)` = **`(p_max − 1/K) / (1 − 1/K)`** — a *normalised margin*, not a probability |
| d1-3B | `lfm2-d1` | same as above |
| d1-2B | `lfm3-d1` | **`max(probs)`** — the raw top probability |

(The `score` question type uses a third formula, `decision_confidence_score`: the mean distance to the
mode, relative to a uniform distribution around its centre.)

**Why this matters to them, immediately.** The ladder's finding *"the 600M's mean confidence is 0.97
at 0.415 accuracy"* is a real and alarming result — but read it through the LFM2 formula and it is
even sharper than it looks: for K = 5, `0.97 = (p_max − 0.2)/0.8`, so **p_max ≈ 0.976**. The 600M is
not merely overconfident, it is nearly deterministic and mostly wrong. That is worth stating in those
words.

But the *cross-size comparison* is not sound: d1-2B's 0.97 means something completely different from
d1-3B's 0.97, because the two are computed by different formulas over differently-shaped
distributions. A mean-confidence column that puts the three sizes side by side is comparing a margin
against a probability against another margin.

**The experiment.** Recompute confidence for every cell **directly from the probability vector that
`/v1/systemone` already returns** (`answers.<qid>.probabilities`), under one stated definition — the
top probability, the normalised margin, and the entropy-normalised score — and publish all three.
Then answer the question the ladder actually needs: **which definition, at which threshold, would have
fired the right number of escalations?**

**The deliverable.** A calibration table per cell × per confidence definition, with ECE and the
escalation rate at a sweep of thresholds. This is the table C3 and C9 both depend on, and it is
free — no new model runs beyond re-reading vectors the harness already has.

**Kill criterion.** If no definition separates correct from incorrect decisions for the 600M at any
threshold, then the 600M's confidence carries no signal **in any form**, and the escalation ladder
(C9) must not use it — which is a firmer statement than "its confidence is uncalibrated", and a more
useful one.

---

## What lab-cascade should *not* spend the next round on

* **The precision ladder again.** It is settled: precision changes no d1 accuracy (0 of 27 pairs
  significant; on T1 the nine cells are identical to the fourth decimal), and 4-bit is not faster.
  Re-running it is a duplicate, not a replication.
* **Escalation driven by the 600M's confidence.** It cannot work: mean confidence 0.97 at 0.415
  accuracy. C3 changes this by changing the calibration, not by escalating on an uncalibrated number.
* **A ring buffer or an external shelf for telemetry.** The box's external FUSE shelf already "stalled
  and took I/O down with it" once (IDEAS.md Part 0). The ledger is the source of truth; measure its
  write rate at the decision rate instead.
* **Anything resting on `tcgen05`, MIG, MMIO register programming, NVLink-C2C, NVMedia capture, or
  DriveOS 7.** All false for this box — see `liquid-study.md` §1.1.1 for the local evidence for each.

---

## The one-paragraph version

The precision ladder is settled and should be retired; what is left is the **decision quality** axis
and the **cost** axis. The three measurements that would most change the project's conclusions are
**the pack-vs-standalone latency decomposition** (C1, already measured by this seat — E1's latency
column may be measuring the wrong regime), **the LFM3 no-batching constraint on the accuracy-winning
cell** (C2, which turns "size decides" into a two-axis trade), and **the per-question-type temperature
already sitting in the GGUF metadata** (C3, which is the cheapest available attack on the
"confidently wrong 600M" finding). Two items change what the ladder is *for*: **C9**, the local →
local → cloud cascade frontier, which replaces a single escalation rule with a cost-accuracy curve; and
**C10**, soft-label distillation from Jev, which is the version of "cloud calibration" that actually has
a mechanism behind it. Above those, **C5 — putting the pixels into one cell of the ladder** is the one
experiment that would make the d1 numbers mean something to builder-ide's critic.
