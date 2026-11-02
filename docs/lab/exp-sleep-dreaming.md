# LAB — exp-sleep-dreaming: a sleep phase, measured on a toy (2026-11-01)

*Scope per BRIEF.md: the smallest honest experiment at the practice tier - a
tiny continual-learning task, with and without the sleep phase - measuring
forgetting; and a verdict for the night pipeline. The paper it tests is read in
docs/research/sleep.md.*

**The verdict in one paragraph.** SLEEP's mechanism - freeze the old
parameters, write the new knowledge into fresh ones, distil it on the model's
own samples, prune the transient - does **not** reduce forgetting in the toy,
and the reason is worth keeping: it protected exactly the parameters it froze
(put the trunk back and the sleep arm scores 0.970 on the old task against the
baseline's 0.133) and could not protect the shared representation underneath
them; and where the substrate was frozen too, it faithfully consolidated the
teacher's own interference. The arm that kept the old task was **replay** -
keeping the old task in the loss - and our nightly refit is already that
shape. So: do not adopt the machinery; take the substrate rule; and measure
what replay costs us in the new contexts, which the toy says is real.

**The toy, in one line.** A two-phase class-incremental task: an MLP with a
shared trunk and a shared 10-way head learns classes 0-4, then classes 5-9; the
forgetting is the drop in accuracy on the first task.

---

## 1. What was built, and what it is not

The arms, all with the **same number of gradient steps**:

| arm | phase B | the budget after phase B |
|---|---|---|
| `seq` | everything trains | nothing |
| `seq_extra` | everything trains | T more steps on B - the compute-matched control |
| `replay` | everything trains | T steps replaying A's stored samples **with their true labels** |
| `sleep` | the **head is frozen**; a transient expert carries B | T steps of **consolidation**: prune the transient expert, add a fresh one, train **only it**, on the **teacher's own samples** |
| `sleep_dream` | as `sleep` | as `sleep`, then T steps of **dreaming**: the model generates its own samples, a gradient filter keeps the best, and they are trained on |

Two settings, because the first one alone cannot say *why*:

* `shared_trunk` - the trunk keeps training on B (the ordinary case);
* `frozen_trunk` - the trunk is frozen from the start of phase B, so the old
  task's features cannot drift.

Every arm also carries one diagnostic: **a1_trunk**, the accuracy on A after
the trunk is put back where it stood at the end of phase A. It says how much of
A's loss was the *shared representation* moving underneath the head.

### What was kept from SLEEP, and what was dropped

| SLEEP | in the toy | dropped |
|---|---|---|
| freeze the stable parameters | the head is frozen through phase B | - |
| expand into fresh parameters | a fresh low-rank expert per sleep | - |
| distil on the model's own samples | the teacher's distribution on prompts + the labels the teacher samples for itself | the paper's RL imitation term, its reward model, its frozen semantic reward |
| prune the transient | the transient expert is reset to zero at the boundary | - |
| the compute-consolidate-update order | the teacher is taken before the prune, the prune and the fresh expert happen together | the deferred base-weight update (the toy has no deferred update) |
| dreaming | generate, select by gradient, train | SEAL's self-edit inner loop, the random-expert routing |
| MoE blocks, frequency schedule, the continuum memory hierarchy | - | **all of it** |
| the LLM | a 16-32-10 MLP | **all of it** |


## 2. The run

| | |
|---|---|
| when | 2026-11-01, 18:42 AKST (the recorded run; lease #39) |
| box state | load 21.59 / 23.71 / 26.87, `NV Power Mode: MAXN`, GPU 0 % used by this job, MemAvailable 112 415 MiB of 122.8 GiB |
| other tenants | the box was carrying other seats' work (load average 21-27 throughout); this job used no accelerator |
| admission | `thor-admit run --tier practice --peak 1G --label sleep-dreaming.exp`, queued and granted at 18:42:46 with no wait |
| measured peak | 317 MiB resident (`rusage`), 324 MiB sampled by the daemon - the 1 GiB promise was ~3x the truth |
| accelerator | **none.** CPU-only torch (`torch==2.15.0+cpu`), `CUDA_VISIBLE_DEVICES=""`, `XLA_PYTHON_CLIENT_PREALLOCATE=false` |
| seeds | 8 per arm per setting (3..10), 80 runs |
| wall clock | 18 min 24 s for the 80 runs (1 658 s of CPU, 154 %), 10-28 s per run |

`a0` is the accuracy on A right after phase A (1.000 everywhere: the task is
learned). `a1` is the accuracy on A at the end. `a1 trunk put back` is the same
model with the trunk restored to its post-phase-A weights. `forgetting` is
`a0 - a1`. The average is `(a1 + b1) / 2`, the usual continual-learning score.
Ranges are min-max over the 8 seeds.

### shared_trunk - the ordinary case, the trunk keeps learning on B

| arm | a0 | a1 (A kept) | a1 trunk put back | b1 (B learned) | forgetting | average |
|---|---|---|---|---|---|---|
| `seq` | 1.000 | 0.003 [0.000, 0.013] | 0.133 [0.000, 0.363] | 1.000 [0.997, 1.000] | 0.998 [0.987, 1.000] | 0.501 [0.498, 0.507] |
| `seq_extra` | 1.000 | 0.003 [0.000, 0.013] | 0.133 [0.000, 0.363] | 1.000 [1.000, 1.000] | 0.998 [0.987, 1.000] | 0.501 [0.500, 0.507] |
| `replay` | 1.000 | 0.997 [0.990, 1.000] | 0.591 [0.327, 0.743] | 0.287 [0.057, 0.567] | 0.003 [0.000, 0.010] | **0.642** [0.528, 0.783] |
| `sleep` | 1.000 | 0.078 [0.003, 0.237] | **0.970** [0.777, 1.000] | 0.970 [0.770, 1.000] | 0.922 [0.763, 0.997] | 0.524 [0.502, 0.583] |
| `sleep_dream` | 1.000 | 0.035 [0.000, 0.237] | 0.951 [0.680, 1.000] | 0.965 [0.743, 1.000] | 0.965 [0.763, 1.000] | 0.500 [0.385, 0.618] |

### frozen_trunk - the trunk cannot drift, so only the head can be blamed

| arm | a0 | a1 (A kept) | a1 trunk put back | b1 (B learned) | forgetting | average |
|---|---|---|---|---|---|---|
| `seq` | 1.000 | 0.041 [0.000, 0.203] | 0.041 [0.000, 0.203] | 0.997 [0.993, 1.000] | 0.959 [0.797, 1.000] | 0.519 [0.497, 0.600] |
| `seq_extra` | 1.000 | 0.040 [0.000, 0.203] | 0.040 [0.000, 0.203] | 0.998 [0.993, 1.000] | 0.960 [0.797, 1.000] | 0.519 [0.498, 0.600] |
| `replay` | 1.000 | 0.995 [0.980, 1.000] | 0.995 [0.980, 1.000] | 0.083 [0.000, 0.313] | 0.005 [0.000, 0.020] | **0.539** [0.493, 0.657] |
| `sleep` | 1.000 | 0.012 [0.000, 0.097] | 0.012 [0.000, 0.097] | 0.993 [0.987, 1.000] | 0.988 [0.903, 1.000] | 0.502 [0.493, 0.542] |
| `sleep_dream` | 1.000 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.943 [0.760, 0.997] | 1.000 [1.000, 1.000] | 0.472 [0.380, 0.498] |

---

## 3. What the numbers say

### 3.1 The freeze worked; the forgetting did not go away

In the `shared_trunk` setting the sleep arm kept A at 0.078 against the
baseline's 0.003 - a real difference, and small. The diagnostic says where the
rest of A went: **put the trunk back and the same model scores 0.970 on A**,
against the baseline's 0.133 with the same repair. The frozen head rows were
still good; the shared representation had moved underneath them.

So SLEEP's "freeze the old parameters" did what it says on the parameters it
froze. What it cannot do is protect a piece of knowledge that is only half in
the frozen parameters. In this toy, A's knowledge was half in the head and half
in the trunk, and the trunk is plastic by construction.

### 3.2 Freeze the substrate and the sleep phase still does not save the old task

The `frozen_trunk` setting removes the trunk as an excuse: the features cannot
move, the head is frozen, and the old task is still gone (0.012, against the
baseline's 0.041 - no better).

The reason is in the mechanism, not in the toy: during the wake phase the
cross-entropy on B pushes A's logits down, and the only thing free to move is
the transient expert - so the transient expert learns to *suppress A*. The
consolidation then distils **the teacher**, and the teacher already suppresses
A. Consolidation preserves the teacher faithfully, including the teacher's
interference. **A consolidation step cannot restore what the wake phase taught
the model to do.**

### 3.3 The thing that kept the old task was keeping the old task in the loss

`replay` is the only arm that held A (0.997 and 0.995), and it paid for it
with B (0.287 and 0.083 against the sleep arm's 0.970 and 0.993). It also had
the best average accuracy in both settings (0.642 and 0.539). Not because
replay is clever - because replay puts the old task's data back into the loss,
and the old task's data is the only thing in the toy that carries the old task.

`seq_extra` - the same budget spent on more waking instead - changed nothing
(0.003 against 0.003, 0.040 against 0.041): more steps on B is not a way to
keep A. The compute-matched control is doing its job.

### 3.4 Dreaming, in the toy, was the thing that broke it

`dreaming` is self-generated training: the model samples its own labels, a
gradient filter picks the candidates, and they are trained on. In the toy it
**eroded the old task** (0.035 and 0.000) while keeping the new one
(0.965 and 0.943), and it lowered the average in both settings (0.500 against
0.524; 0.472 against 0.502).

This is the opposite of the paper's ablation, where removing dreaming cost 12.4
points on knowledge incorporation. We did not reproduce their dreaming benefit.
What we did reproduce is the risk they name in the same breath - "iterative
self-improvement in a continual learning setup ... might cause catastrophic
forgetting" - and, at the first attempt, the literal version of it: the first
run of this experiment died with NaN weights at learning rate 0.05 with
momentum, on a single-sample loss (see `NOTES.md`).

---

## 4. The verdict for the night pipeline

**Do not adopt SLEEP's mechanism as the night.** In the toy it is a worse way
to keep the old task than the thing we already do, and the reason is
structural rather than a matter of tuning.

**What we already do is the replay arm.** Our nightly retrain refits the
chooser over the **whole log**, so the old contexts' plays stay in the fit.
That is replay-shaped, and the toy says what replay-shaped costs: the old task
survives (0.997) and the new task's estimate is squeezed (0.287). We have been
assuming the new contexts get their estimates; the toy says the old contexts
take the budget. **That price is now measured, and it is worth measuring in our
own system before we spend the night on it.**

**What is worth taking from SLEEP is the substrate rule, not the machinery:**
*the old knowledge has to live in parameters that nothing else touches.* For
the chooser that is nearly free - the per-context counts are append-only and
per-context, exactly the "frozen receiver" the paper needs. But the context
*buckets* are the shared substrate, and the toy's finding transfers directly:
if a bucket's definition moves, its counts move with it, and no consolidation
step can put them back. **A context definition is a versioned thing, and
changing one invalidates what was counted under it.**

**What to measure next, in our own code:** does the nightly refit over a
growing log drift the *old* contexts' estimates? That is the SLEEP-shaped risk
in our system, and it is answerable with `core/tiles/ope.py` and our own log.
The toy says the answer depends on one thing only - whether the context
definition was stable over the period being refitted.

**What to watch in the cloud loop.** Our version of dreaming is not
self-generated - the cloud writes the tiles - so the toy does not condemn it.
But the mechanism it shares is the same one the toy broke on: training on
material the system produced itself, and finding the old task eroded. The
`night -> cloud -> new tiles -> library` loop has never been scored on whether
it preserved the old contexts. That is a measurement we could take from the log
we already keep.

**And what it says about `docs/design/watching-teachers.md`** (the design
whose tiles-to-weights path the brief names; read in
[`docs/research/sleep.md`](../research/sleep.md) section 2.5): that design
keeps a lesson as **data, then as a tile, then as weights** - the student's
policy fine-tuned on the demonstrations. The toy's first finding lands on it
directly. **One policy fine-tuned on many demonstrations is one shared
substrate**, which is the toy's trunk: the demonstration of a new skill can
erase the old skills' behaviour, and no consolidation step puts it back. If
the weights path is a single policy, the old skills are the thing at risk -
and the design already has the instrument (student-teacher agreement per
skill), which needs to become a gate on the write, not only a curve.

**And one thing SLEEP does that we have not thought about:** the order.
Consolidate first, then dream. Our night already does the first (the retrain
is the last thing) and the cloud's new tiles come after, so our order is
already right. It was worth checking.


## 5. What we did not verify

* **The paper's experiment was not run, and could not be.** It needs a 3B or 8B
  LLM, and this box has no LLM (B2, "No LLMs on the Thor"). Everything said
  about the paper here is what its authors wrote.
* **The toy is not the paper.** No MoE, no frequency schedule, no continuum
  memory hierarchy, no RL imitation term, no reward model, no deferred
  base-weight update, no LLM. The RL imitation term is replaced by
  cross-entropy on the labels the teacher samples for itself - the same signal
  without the RL machinery. The toy therefore tests the *mechanism in the
  abstract*, not the paper's system.
* **The consolidation's prompts are the inputs the model has seen.** SLEEP's
  consolidation generates its own sequences; the toy reuses the training inputs
  as prompts and generates only the *labels* itself. A real system would have
  to generate the prompts too.
* **Eight seeds on one synthetic task.** One data-generating process, one
  architecture, one learning rate. The ranges are reported so the spread is
  visible, but eight seeds of a toy is a weak estimate of anything beyond this
  toy.
* **Three invocations, and the published rows are from the third.** The first
  died on a NaN in the dream phase; the dream phase was given its own learning
  rate and a gradient clip, and that run's rows were discarded, not merged.
  The second completed, but a duplicated main guard in the script made it run
  the whole experiment twice, so its rows were taken from the first of the two
  passes and the script was fixed. The third invocation is a single clean pass
  from the committed script, and it **reproduces the second invocation's
  numbers exactly** (0 of the 60 summary means differ).
* **Figures in the paper were not read** (the class-incremental, CTNL and
  BABILong numbers are figures, not text) - see the research note.
* **Nothing about the night pipeline was changed.** This lab note is a
  measurement and a verdict; no code in `core/` was touched.

## 6. How to reproduce

```bash
cd ~/lm-wt/sleep-dreaming
~/lm-tools/thor-admit run --tier practice --peak 1G --label sleep-dreaming.exp -- \
  .venv/bin/python docs/lab/sleep-dreaming-scripts/exp_sleep_dreaming.py \
    --seeds 8 --out docs/lab/sleep-dreaming-scripts/results.json
```

About 18 minutes on the Thor (80 runs), CPU only, 317 MiB of resident memory (the lease
asked for 1 GiB). The scripts and their README are in
[`docs/lab/sleep-dreaming-scripts/`](sleep-dreaming-scripts/); the raw rows are
in `docs/lab/sleep-dreaming-scripts/results.json`.
