# RESEARCH — SLEEP: a sleep phase for continual learning (2026-11-01)

*Scope per `BRIEF.md`: find the paper/code (exact title, date, licence); write the
mechanism — what is replayed, what is consolidated, what is forgotten — and map it
onto our night (`core/night`), the precedent store, and the tiles-to-weights path.*

Everything below was read from the paper's own HTML (`arxiv.org/html/2606.03979v2`,
fetched 2026-11-01) and the Google Research blog post of 2026-10-27. No code was
run, no model was downloaded, nothing was installed.

---

## 0. The citation

| | |
|---|---|
| **Title** | **Language Models Need Sleep: Learning to Self-Modify and Consolidate Memories** |
| **Authors** | Ali Behrouz, Farnoosh Hashemi, Adel Javanmard, Vahab Mirrokni (Google) |
| **Where** | arXiv:2606.03979 [cs.LG] — <https://arxiv.org/abs/2606.03979> — DOI `10.48550/arXiv.2606.03979` |
| **v1** | 2026-06-02 17:56:55 UTC (2,961 KB) |
| **v2** | 2026-07-10 17:52:03 UTC — **the version read here** (`/html/2606.03979v2`) |
| **Licence** | **CC BY 4.0** — the licence shown on the arXiv abstract page |
| **Earlier** | "A version of this work has been publicly available from September 2025 on OpenReview" (the note on the arXiv abstract page; that version was not read) |
| **Blog** | *The sleep framework: A new way for LLMs to retain knowledge in continual learning*, research.google, **2026-10-27** |
| **Code** | **none linked.** Neither the paper nor the blog carries a repository URL — searched both pages on 2026-11-01. The blog's "Discover open-source code and collaborate with the community" is site-wide navigation boilerplate, not a release statement |

**The paper's architecture is not its own.** The model it sleeps is **Hope**, the
continuum-memory architecture from Behrouz et al. (2025), *Nested Learning: the
illusion of deep learning architectures* (NeurIPS 2025). This paper's contribution
is the **sleep paradigm** — the lifecycle — put on top of that architecture. The
baselines it compares against include Hope itself, so "Hope+consolidation beats
Hope" is the sharpest form of the claim, and the one that matters for us.

---

## 1. The mechanism

### 1.1 The lifecycle

> "for a continual learner, there is no train or test time. Instead, the model needs
> to periodically have two phases of being 'active' or 'Sleep'."

* **Wake (active):** the model receives new data. New information lands in the
  **high-frequency** (fast-updating) memory modules.
* **Sleep (offline):** the model takes no new input and turns its compute to
  consolidation and self-improvement. Two stages, in this order:
  1. **Memory consolidation** (the paper's NREM analogue) — the fragile
     high-frequency memories are distilled into newly unlocked capacity in the
     **low-frequency** (stable) modules.
  2. **Dreaming** (the REM analogue) — self-generated synthetic training, filtered
     and learned from, to improve the model further.

The order is the point, and the paper says why: consolidation first *stabilises* the
newly acquired knowledge in freshly expanded parameters, and only then does dreaming
modify the model further — "reducing the risk that iterative self-training overwrites
useful prior capabilities" (§A.4). Dreaming on a fixed model, by itself, is the thing
that erodes capability: they cite Kim et al. (2026) measuring up to **40 %**
out-of-distribution degradation, and Wang et al. (2026) / He et al. (2026) reporting
information leakage and training collapse from naively iterated self-distillation.

### 1.2 The schedule

Memory blocks have their own update frequencies `C^(1) < C^(2) < …`. Sleep fires
when the step count is divisible by `C^(ℓ) × b`. When a fast block updates ten
times for every update of a slower one, **consolidation from fast to slow happens
ten times** before the slow block's own update — the paper calls this multiple
consolidation "a critical bottleneck to unlock continual learning capabilities".

### 1.3 The consolidation protocol: compute → consolidate → update

Each MLP block is a sparse MoE with a router. Consolidation moves knowledge from a
faster block `ℓ*−1` into its immediate slower neighbour `ℓ*`:

**(a) Compute.** The sender's base-weight update is computed from its accumulated
gradients, giving prospective parameters `θ_new`. **It is not applied yet.**

**(b) Consolidate.** Two models are built:

| | what it is |
|---|---|
| **Teacher** `LM_θ` | the state *before* the base-weight update and before expansion — the receiver still on its original parameters plus its accumulated experts |
| **Student** `LM_θ_exp` | the state *with* the prospective `θ_new` applied, the sender's experts reset, and a **newly added low-rank expert** `A, B` in the receiver (`A ∈ R^{d×d_low}`, `B ∈ R^{d_low×d}`, `d_low ≪ d`) |

Only `A, B` are optimised. **Every other student parameter is frozen** — "This
ensures that the transferred knowledge does not interfere with the old knowledge,
causing catastrophic forgetting."

**(c) Update.** Only now: the base-weight update `θ → θ_new` is applied; the
sender's low-rank experts are **reset** ("synaptic pruning"); the new expert is
activated.

### 1.4 Knowledge Seeding — upward distillation

**Knowledge Seeding (KS)** is a distillation where the **smaller** model teaches the
**larger** one — the opposite of the usual direction. **Self-KS (SKS)** is the case
where the two are the same model at different stages. It is built on **GKD**
(Agarwal et al., 2024), so the objective mixes teacher-generated and
student-generated samples:

```
L(θ, θ_exp) = (1−λ)·E_D[ F(LM_θ ‖ LM_θ_exp)(y|x) ] + λ·E_x[ E_y[ F(LM_θ ‖ LM_θ_exp)(y|x) ] ]
```

with `λ ∈ [0,1]` the share of on-policy student-generated outputs. No gradient is
taken through the student's sampling distribution — for stability and speed.

The distillation is **not on the raw data**. The paper is explicit:

> "the memory consolidation step should not simply replay raw data; instead, it
> needs to explore and extract abstractions of knowledge acquired during active
> (waking) steps."

Two steps make that possible. The dataset `D` is **sampled from the teacher** — the
model's own generations. And **Learning to Imitate (LTI)** adds an RL term on top of
the distillation, because "despite having access to the knowledge, the student model
has not learned to use it and so weakly mimics the sampling and performance of the
teacher":

* the student completes a random prefix of a teacher dream;
* the reward is `r = γ·r_sem + (1−γ)·r_abs`, where `r_sem ∈ {0,1}` comes from a
  **frozen reward model** judging semantic equality, and `r_abs` is `1 −
  Levenshtein/max_len` if the Levenshtein distance is under a threshold `z₀`, else 0;
* the combined objective `L_KS = E[(1−α)·E[r(y)] − α·E[D(teacher‖student)]]`
  updates **only the newly expanded parameters**.

The paper's own theory section (§A.4) reads KS as a **structured low-rank
compression** problem: the model is not asked to copy every trace, but to find the
compact directions that preserve both its on-policy behaviour *and* the semantic
qualities the reward cares about.

### 1.5 Dreaming

Dreaming is built on **SEAL** (Zweiger et al., 2025) with three changes: SEAL's
SFT inner loop is expensive, so there can be only a few self-edits; iterative
self-improvement risks forgetting; and SEAL only samples inside the existing
knowledge space, whereas dreaming should explore new situations. The loop:

1. **Random expert selection** — during synthetic generation the MoE router
   activates non-standard experts, so the model mixes domains and finds directions
   it would not have found otherwise.
2. **Gradient-based selection** — the model generates candidate dreams and keeps the
   ones with the highest potential to improve.
3. **SFT on the top-rated dreams**, then an evaluation of whether the generation
   actually improved things.

### 1.6 The three questions the brief asks

| | what it is in SLEEP |
|---|---|
| **What is replayed** | **The model's own samples.** Consolidation samples a dataset `D` from the teacher and trains on it with the teacher's logits as feedback; dreaming generates synthetic training samples and filters them by gradient. **The raw training data is not replayed** — the paper explicitly refuses raw replay in favour of extracting abstractions |
| **What is consolidated** | Knowledge held in **high-frequency (fast) modules** is distilled into **low-frequency (stable) modules**, written into **newly unlocked low-rank MoE experts**, with the receiver's old parameters **frozen** during the transfer. The knowledge that survives is the abstraction, not the trace |
| **What is forgotten** | (i) the **sender's transient low-rank experts are reset** after consolidation — synaptic pruning, freeing capacity for the next cycle; (ii) the **higher-frequency memory is reset** once its abstraction sits in the stable parameters — the fragile trace goes, the abstract stays; (iii) in dreaming, everything the **gradient-based filter does not select** is not learned — the filter decides what is worth keeping; (iv) nothing is overwritten, because capacity is *added* rather than reused — which is the paper's diagnosis of why forgetting happens at all: "an inherent cause of model's limited capacity" |

### 1.7 What the authors report

Mathematical reasoning, average@16 (Table 2; AIME-24 / AIME-25 / HMMT-25):

| model | method | AIME-24 | AIME-25 | HMMT-25 |
|---|---|---|---|---|
| Qwen3-1.7B | Base (Instruct) | 49.8 | 34.5 | 25.7 |
| | SFT | 47.3 | 36.1 | 22.9 |
| | GRPO | 51.0 | 38.6 | 26.1 |
| | OPSD | 51.6 | 40.0 | 28.1 |
| | **Sleep** | **53.2** | **40.2** | **29.3** |
| Qwen3-8B | Base (Instruct) | 73.8 | 68.1 | 42.4 |
| | SFT | 75.5 | 66.4 | 43.7 |
| | GRPO | 76.4 | 68.1 | 44.9 |
| | OPSD | 76.6 | 67.4 | 45.1 |
| | **Sleep** | **79.2** | **69.0** | **46.1** |

Ablations (Table 1, Qwen3-8B): Sleep 79.2 / 69.0 / 46.1; **− Imitation Learning**
76.8 / 67.9 / 45.0; **− Semantic Reward** 78.9 / 69.2 / 44.5; **− Expansion**
78.2 / 67.9 / 44.9; OPSD 76.6 / 67.4 / 45.1; OPSD **+ Expansion** 77.9 / 68.2 / 45.9.

Knowledge incorporation (Table 3; single passage / continued pretraining n=200):
Base 31.9 / 31.9; no dreaming 33.4 / 32.0; SEAL 46.7 / 43.2; **Sleep (Transformer)
48.1 / 44.3**; Sleep (Transformer + four-level) 48.9 / 46.2; − gradient-based
selection 47.1 / 45.2; − random expert 48.0 / 44.7; **− Dreaming 35.7 / 36.2**.

Few-shot abstract reasoning (Table 4): ICL 0; TTT 10; SEAL 72.5; **Sleep 80**.

Efficiency (Appendix B.5): "With the same number of steps, SFT is 4x more efficient
than our method" — but to reach the *same score*, SFT needs **4.3× / 3.6× / 4.8×**
the wall-clock on AIME-24 / AIME-25 / HMMT-25. The claim is about cost *to a
target*, not per step.

Class-incremental learning (CLINC, Banking, DBpedia; Llama-3B and Llama3-8B): the
text says Hope-with-consolidation performs best across the three datasets, ahead of
ICL, EWC, InCA and Hope itself. The numbers are in **Figure 3**, which the HTML
does not carry as text — see §4. Continual translation of a novel language (Manchu,
Kalamang): ICL drops sharply, Hope retains, performance improves monotonically with
the number of consolidation stages, and Hope-3 nearly recovers single-language
performance (Figure 5, not read). BABILong: "almost perfect score in scaling to 10M
of tokens".

---

## 2. The map onto our night

### 2.1 `core/night` — the wake/sleep shape we already have

The night runner is already a two-state lifecycle, and the correspondence is close
enough to be worth stating precisely:

| SLEEP | ours | where |
|---|---|---|
| Wake: new data arrives, fast modules absorb it | the day: the builders work; the audit log accumulates `tile.played` rows | `core/night/runner.py`, `core/tiles/plays.py` |
| Sleep: turn the compute inward, consolidate | the night's tail: fold the plays → refit the chooser → rank → retire → feed the losers back | `core/tiles/retrain.py` (the design: `docs/design/tiles.md` §5) |
| The log is the durable memory; the weights are a fold over it | **the same**: "the statistics are a fold over the log, so a restart or a crash loses nothing and a replay gives the same answer" | `docs/design/core-spec.md` §1.0 |
| Consolidate into fresh capacity, freeze the old | **not ours yet**: the nightly refit **overwrites** the chooser wholesale | `core/tiles/chooser.py` |
| Prune the transient, keep the durable | **ours already**: tiles are retired, never deleted | `docs/design/tiles.md` §0.4 |

Two of SLEEP's four properties are already ours, and they are the two that are
cheap: the log is durable and append-only, and retirement is a prune. Two are not:
the consolidation **re-fits on raw events** (the play records), which is the thing
the paper explicitly refuses to do, and the chooser has **no expansion**.

The honest framing: **our night is SLEEP's lifecycle with the consolidation step
implemented as a raw replay.** Everything else about it — the schedule, the rail
budget, the morning report — is unchanged by the paper.

### 2.2 The precedent store

`docs/research/dsmc.md` proposes, as the second foundation: "**a precedent store
with a deterministic validator.** The LLM proposes a ruling; a rule engine checks it
against precedent."

Mapped onto SLEEP:

* The precedent store is the **low-frequency, stable memory in a non-parametric
  form** — append-only, never overwritten. A ruling is checked against what was
  ruled before, not against a parameter that has drifted.
* The **validator** is SLEEP's "old parameters frozen" implemented as a *rule*
  rather than as a gradient barrier. It protects the same thing.
* SLEEP's diagnosis lands on it directly: catastrophic forgetting is "an inherent
  cause of model's limited capacity" — **and the precedent store has no capacity
  pressure**, because capacity is added by appending. So the store already solves
  the half of the problem SLEEP solves with parameter expansion.
* What the store does **not** have is SLEEP's other half: **the selection of what
  is worth keeping**. The paper's filter is gradient-based, on the model's own
  samples. Our filter would be the validator plus the measure — the critic's
  verdict, the owner's keep-or-undo, or a sealed prediction that held
  (`docs/design/tiles.md` §0.6). That choice is the one SLEEP's dreaming ablation
  says matters most ("− Semantic Reward" costs 0.3 / −0.2 / −1.6 points on the maths
  benchmarks; "− Dreaming" costs 12.4 / 8.1 points on knowledge incorporation).
* Where our version of forgetting would live: not in a weight, but in **retrieval** —
  the store keeps the precedent but the lookup returns the wrong one. The place to
  measure it is `core/tiles/retrieval.py`, and the metric is the same one the
  precedent store was proposed to serve.

### 2.3 The tiles-to-weights path

> **SUPERSEDED (2026-11-01 19:25) - the map the brief asked for is in
> section 2.5.** The paragraph below says the file the brief points at does
> not exist. **That was wrong, and the brief was right.** The text is kept
> so the mistake is visible.

**A correction to the brief, in writing.** The brief points at
`docs/design/watching-teachers.md`. **That file does not exist** — not on this
branch, not on any branch (`git log --all --diff-filter=A -- "*watching-teachers*"`
returns nothing; `git ls-files | grep -i watch` returns only
`docs/research/googleidea3/06-crash-dump-and-watchdog.md`). The tiles-to-weights
path the brief means is **`docs/design/tiles.md` §5, "The learning loop — the
nightly retrain"**, implemented in `core/tiles/retrain.py`. Everything below is
about that path.

The path today, per night:

1. **Fold** the night's `tile.played` rows into play records.
2. **Refit** the chooser from them — a contextual bandit (`core/tiles/chooser.py`),
   whose state is per-context win counts.
3. **Rank** the tiles by win rate, **by measure**, with the denominator kept.
4. **Retire** the tiles that lost, with the reason and the plays they had.
5. **Feed the losers back** to the cloud author as a `FeedbackPacket`.

SLEEP's four properties against that list:

| SLEEP | the tiles-to-weights path today | the SLEEP-shaped change |
|---|---|---|
| Freeze the old, write the new into fresh capacity | the refit **overwrites** the previous parameters | keep the last night's chooser state frozen as a base; write the new night's fit into a **fresh block**, and let the chooser read both. For a bandit the "fresh block" is per-context — a context that has not been seen for a while keeps its old estimate instead of being re-fit to a shrunken denominator |
| Consolidate by abstraction, not by raw replay | the refit re-fits on **the whole log** | fit only the **unconsolidated** (recent) plays and carry the consolidated knowledge forward from the previous night; measure the divergence between the two fits |
| Prune the transient | retirement exists — but it prunes *tiles*, not *parameters* | prune the transient part of the chooser state, and keep the denominator with the retirement |
| Dream: self-generated, filtered, then learned | the "dreams" are the **feedback packets**, written by the **cloud** | SLEEP's order is the transferable part: **consolidate first, then dream**. Our cloud-authored tiles arrive after the refit, so the order is already right — but the risk SLEEP flags (iterative self-improvement eroding prior capability) applies to our loop *night → cloud → new tiles → library*, and **nothing in our system measures it** |

**The concrete hypothesis this leaves us.** The nightly refit over a growing log is
our catastrophic-forgetting shape, and it is measurable with our own code and our
own log: refit the chooser as of night *k*, then score the **old** contexts
(a) with that refit and (b) with the refit as of night *k+n*. If old-context
estimates drift as the log grows, we have SLEEP's problem in miniature and the fix
(freeze + expand + prune) is already sketched in the tiles design. That measurement
belongs to `core/tiles/ope.py` and the `exp-tiles-*` lab notes, not to this
document.

### 2.4 The map, in one table

| SLEEP | our nearest thing | status |
|---|---|---|
| Wake phase, fast modules absorb new data | the day; the log's `tile.played` rows | ours |
| Sleep phase, offline, no new input | the night's tail (the retrain) | ours |
| Durable log, weights as a fold over it | core-spec §1.0, the ledger | ours, and stronger than SLEEP's (no crash loses the night) |
| Expand capacity instead of overwriting | append-only ledger; tiles retired not deleted | ours for records, **not ours for parameters** |
| Freeze the old parameters | the validator, for rulings; **not** the chooser refit | missing |
| Distil on self-generated samples, not raw data | — | **missing**; our consolidation is a raw re-fit |
| Prune the transient | retirement | ours, for tiles |
| Dream: self-generated, gradient-selected, then SFT | feedback packets to the cloud | ours but **external** — a teacher, not a self |
| Imitation learning with a frozen semantic reward | the three measures (critic / owner / sealed prediction) | analogous, and the choice of one is already our rule |
| The whole ladder: demonstration -> tile -> weights | `docs/design/watching-teachers.md` | **section 2.5** - the brief's file, and the real tiles-to-weights path |

---

### 2.5 The tiles-to-weights path - `docs/design/watching-teachers.md`

**The correction, in writing.** At 17:16 I searched the reachable history for
the file the brief names and found nothing, and wrote in this note that
`docs/design/watching-teachers.md` did not exist. **It does exist.** The
commit is `dc99482` - *"design: watching teachers (the screen watcher as a
student; teaching moments = surprising action + good outcome; demonstration ->
tile -> weights; retire the teacher skill by skill) and the auto-play stack"* -
authored and committed at 15:03 AKST, an ancestor of `main` and **not** of the
`sleep-dreaming` branch, which was cut at `18ec1be`. The same command that
returned nothing at 17:16 finds it now, so the commit reached this clone's refs
during this session. The paragraph in section 2.3 is kept, marked superseded,
so the mistake is on the record. **The brief was right and I was wrong.**

This is also the file that says what "the tiles-to-weights path" means, and it
is a better target than the retrain loop I mapped onto by mistake: the design
keeps a lesson **as data, then as a tile, then as weights** - a promotion
ladder from a demonstration to a skill to the student's own parameters.

The design, in short: the watcher asks each second whether to stay silent or
speak; turned around, the same machinery asks **is what I just saw worth
learning?** The student predicts the teacher's next action; when the teacher
does what the student would not have done *and the outcome is good*, that is a
teaching moment; the lesson is kept as a demonstration, then as a tile (a
cloud-written skill admitted **by replay against the recording** - the shadow
conductor gate), then, **if the skill recurs**, as weights (the student's
policy fine-tuned on the demonstrations); and when the student predicts the
teacher reliably for a skill, the teacher is retired for that skill - "silence
is the measure of trust".

#### SLEEP against the ladder

| watching teachers | SLEEP | what the comparison says |
|---|---|---|
| the teacher's recorded episodes (the demonstrations) | the wake phase's input | the teacher's own behaviour is the only signal the student may learn from |
| **tile**: a cloud-written skill, admitted **by replay against the recording** | **knowledge seeding**: the student reproduces the teacher's distribution on the teacher's own samples, into freshly unlocked parameters | the tile gate is a *check* that the student reproduces the teacher; knowledge seeding is the *write* that makes it reproduce the teacher |
| **weights**: the student's policy fine-tuned on the demonstrations | the sleep phase's parameter write | this is the write that can overwrite what the student already knew |
| retire the teacher for that skill | prune the transient expert; the freed capacity is the point | the design's retirement frees *budget*; SLEEP's pruning frees *capacity* |
| "if it recurs, as weights" | the frequency schedule: consolidate from the fast block to the slow one C^ℓ times | the design has the trigger but not the schedule; SLEEP's chunk lengths are the principled version of it |
| the measure: student-teacher agreement per skill, over time | the consolidation's own objective | the design already measures what SLEEP optimises - but afterwards, not as a gate on the write |

#### What the toy says about this ladder

The toy is in [`docs/lab/exp-sleep-dreaming.md`](../lab/exp-sleep-dreaming.md);
three of its findings land on the design directly.

**1. The weights path is the shared substrate, and the shared substrate is
where the knowledge goes.** The toy says that a frozen head under a plastic
trunk still loses the old task: put the trunk back and the sleep arm scores
0.970 on it against the baseline's 0.133. The design's "the student's policy
fine-tuned on the demonstrations" is **one policy, fine-tuned on many
demonstrations** - one shared substrate, which is exactly the trunk. If the
weights path is a single policy, the demonstration of a new skill erases the
old skills' behaviour, and no consolidation step puts it back. The design's own
words - *the student's policy* - are where the toy locates the loss.

**2. The tile gate is the right gate, and it is not enough on its own.** A tile
is admitted by replay against the recording: the new skill must reproduce the
teacher. The toy says a check that the *new* skill reproduces the teacher says
nothing about whether the *old* skills survived the write - and the toy also
says a consolidation step cannot undo the teacher's own interference. The
design already has the instrument for this (student-teacher agreement per
skill, over time); the finding is that it has to be a **gate on the weights
write**, not only a curve looked at afterwards.

**3. The design already keeps the demonstrations, so it already pays replay's
price.** "The canon keeps the demonstrations and the lessons": the old skill's
data stays in the training set, which is the replay arm - in the toy, the arm
that kept the old task (0.997) and paid with the new task's estimate (0.287).
The concrete question for the design is therefore: **when the policy is
fine-tuned on all the demonstrations, does the newest skill's behaviour
survive?** That is measurable from the recordings the design already keeps.

**4. No dreaming here.** SLEEP's second stage has no counterpart in this
design, because the demonstrations come from real teachers and the tiles are
written by the cloud, not by the student. The toy's dreaming result (it eroded
the old task) is a warning about our *other* self-generated loop - the night
feeding the cloud and the cloud returning new tiles - not about this design.

## 3. What does not carry over

* **The stakes.** Their forgetting is in 3B and 8B LLMs; ours would be in a
  contextual bandit's per-context counters. The mechanism transfers; the magnitude
  does not.
* **The expansion substrate.** Their capacity is parameters in a sparse MoE; ours
  would be rows in a log. Ours is easier and more honest — appending is not
  forgetting.
* **The frequency argument.** Their schedule is in gradient steps, and the
  multiple-consolidation bottleneck is a real cost they name. Ours is in nights. We
  have no analogue of "consolidate ten times before the slow block's own update",
  and we should not pretend otherwise.
* **The dreamer is not us.** SLEEP dreams with itself. Our dreams are written by a
  cloud model, which is a teacher: the "Learning to Imitate" half of the paper has
  no counterpart, and our own LLM-free rule (B2, "No LLMs on the Thor") means the
  self-generated-dream half is not reachable here at all.
* **We cannot run their experiment.** The Thor holds no LLM, so the paper's
  experiment is not reproducible on this box by us. The substitute is a toy, and a
  toy measures the mechanism, not the result — see
  [`docs/lab/exp-sleep-dreaming.md`](../lab/exp-sleep-dreaming.md).

---

## 4. What we did not verify

* **Figure 3** (class-incremental learning on CLINC / Banking / DBpedia),
  **Figure 4** (the level-count and long-context effects), **Figure 5** (CTNL) and
  **Figure 6** (BABILong) are figures; their numbers are not in the HTML text, so
  every claim about them here is the paper's own prose, not a number we read.
* **Appendix B.1 (datasets) was not read**, so the exact splits and sizes are
  unknown to us.
* **No code exists to check against.** No repository is linked from the paper or the
  blog, so every mechanism statement above is the authors' description. Where this
  document paraphrases, the paper's words are quoted.
* **The OpenReview version** (public since September 2025) was not read. It may
  differ from v2.
* **Nothing was run.** No model, no benchmark, no number of ours appears in this
  document. The only numbers here are the paper's.
* The blog's own framing ("the model unlocks pre-allocated MoE memory blocks") is
  the authors' summary; the paper's implementation note adds that the parameters can
  be pre-allocated and **masked** rather than added, which is what makes the
  expansion practical without changing tensor shapes.
