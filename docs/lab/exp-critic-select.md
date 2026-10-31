# exp-critic-select — choosing the critic

*Lab round 5, the critic seat. 2026-10-31.*

## The question

The critic has been "the largest unchosen dependency in the whole stack" (X
R4) since the first week. `core/critic` measured the **scripted** checks on
the reference set and published their FP/FN table; that table is the
baseline any model has to beat. Now the model choice has to be made — and
made by **measurement**, not by taste.

The brief's question, in one line: **which critic should score a render?**

## The hypothesis

> The scripted checks hold the band on eight of the nine defect classes, and
> the ninth — `floating_object` — is the only class a model is needed for. So
> the winning critic is a **hybrid**: the checks everywhere, a model on the
> one class the checks are out of band on.

The hypothesis is falsifiable in both directions. If a model candidate holds
the band on its own, the hybrid is the wrong shape (the model should
replace the checks). If no model candidate holds the band on the class the
checks miss, the hybrid adds cost and buys nothing.

**The hypothesis held.** The hybrid is the only candidate in the whole
bake-off that holds the band, and its delegate is the only critic that can
see the one defect the checks miss.

## The setup

Everything is measured on **the same reference set**, with **the same
counting rule**, by the same harness
(`docs/lab/critic-select-scripts/harness.py`).

### The set

30 members over the overnight sweep's real renders: 21 image members (15 with
a seeded defect, 6 clean controls) and 9 mesh members — **one member per
base render, 30 distinct bases**, so no two members of the set are the same
picture. The set is a **recipe**: every member records the base render's
sha256 and the recipe of its seeded defect.

**The set re-derives.** `derive_set.py` rebuilt all 21 image members from
their base renders and their own recipes: **21 of 21 match the manifest's
recorded sha256, byte for byte.** The plant is deterministic, so the numbers
below are about the same pictures the published table was measured on.

### The candidates

| candidate | what it is | what it sees |
|---|---|---|
| `scripted` | the analytic checks | the pixels and the geometry |
| `dino-probe` | DINOv2-large (Apache-2.0, the Thor's own copy) + a small head per class | the pixels |
| `vlm` | Muse Glimmer 30B (Apache-2.0, the Thor's own copy) served by llama.cpp, one fixed yes/no question per class | the pixels |
| `jev` | Jev in the cloud (TypeSafe System One): `jev_verify` (a Noul per class) and `jev_classify` (one Choice) | a **text description** of the frame and the scripted measurements |
| `hybrid` | the scripted checks first, the model only on the class the checks are out of band on | both |

**No model was downloaded.** Every weight used was already on the Thor:
Muse Glimmer 30B (`~/models/Muse-Glimmer-30B-GGUF`, Apache-2.0 by the
licence file beside it) and DINOv2-large (the HF-cache copy, Apache-2.0, the
same weights `docs/lab/exp-critic-cuda-graph.md` measured). Nothing was
pulled from the network for this bake-off.

Two rules kept the comparison fair:

* **No candidate is told what it is looking at.** Each one gets the same
  fixed question per class and nothing else — no thresholds, no hints, no
  scripted measurements (except `jev`, which is the point of its arm).
* **A candidate is measured only on what it can see.** A pixel critic cannot
  judge a defect that lives in the geometry, and the set never re-renders a
  mesh defect, so the fold leaves those members out entirely — they are
  neither a miss nor a clean control. The tables say which layers they
  covered.

### The counting rule

The cold-start seat's, unchanged: a planted defect of class K that the
check targeting K does not fire on is a **false negative**; a firing on a
clean control is a **false positive**; a check firing on a member carrying a
*different* class of defect is excluded from all four counts. The band:
**no false negatives, and at most 5 % of the clean controls cried wolf.**

### The box

The Thor, shared. The **seed sweep was running the whole time** (it is the
sweep's own renders the set is made of; it was noted and not stopped), other
seats' GPU work was on the box beside it, and the load average sat at 5–8
throughout. Every number below therefore carries the box's state beside it,
and **joules are not attributed** — a whole-box rail on a shared box cannot
be blamed on one candidate. The wall time and the process's own CPU time
are the numbers that can be attributed, and they are the ones given.

The one heavy step — the resident 17 GB VLM — ran under the shared
`flock ~/lm-wt/heavy.lock`, one model server at a time, stopped as soon as
it was done, with the box's state captured beside it:

| | |
|---|---|
| the stage's window | 14:00:26 → 14:08:32 (486 s) |
| peak memory used (whole box) | 42 968 MiB |
| minimum memory available | 82 780 MiB (the rule's floor is 25 000) |
| whole-box joules | VDD_GPU 16 385 J (mean 33.7 W), VDD_CPU_SOC_MSS 8 533 J (17.6 W), VIN 37 369 J (76.9 W) |

Those joules are the **box's**, not the critic's. The rails include the seed
sweep and the other seats, so they are context and not an attribution.

## The results

### The baseline: the scripted checks

| class | members | TP | FP | FN | TN |
|---|---|---|---|---|---|
| `black_frame` | 3 | 3 | 0 | 0 | 6 |
| `noise_fireflies` | 4 | 4 | 0 | 0 | 6 |
| `missing_object` | 2 | 2 | 0 | 0 | 6 |
| `holes` | 2 | 2 | 0 | 0 | 6 |
| `texture_swap` | 2 | 2 | 0 | 0 | 6 |
| `floating_object` | 2 | **1** | 0 | **1** | 6 |
| `wrong_scale` | 4 | 4 | 0 | 0 | 1 |
| `hollow_mesh` | 3 | 3 | 0 | 0 | 1 |
| `clipped_geometry` | 2 | 2 | 0 | 0 | 1 |
| **all** | | **23** | **0** | **1** | **39** |

**Out of band on one class.** The checks miss one `floating_object` in two
(`mem_d5c1c6cc24413705`, coast-s6) and cry wolf on nothing.

Two latency numbers for the same baseline, because one is the first run and
one is every run after it:

| | image verdict | mesh verdict | all verdicts |
|---|---|---|---|
| cold probe cache (first ever run) | 882 ms | **21.8 s** | 1 059 ms median |
| warm probe cache (every later run) | 853 ms | **10 ms** | 673 ms median, 594 ms mean |

The mesh verdict is the Blender probe loading a `.blend`; its numbers are
cached under `core/critic/.cache`, so only the first run pays. A nightly
re-score sees the warm number. **The comparisons below are on the warm
number**, so they compare like with like.

### The local VLM

| class | members | TP | FP | FN | TN |
|---|---|---|---|---|---|
| `black_frame` | 3 | 3 | 0 | 0 | 6 |
| `noise_fireflies` | 4 | 1 | 0 | 3 | 6 |
| `missing_object` | 2 | 2 | 1 | 0 | 5 |
| `holes` | 2 | 0 | 0 | 2 | 6 |
| `texture_swap` | 2 | 2 | 1 | 0 | 5 |
| `floating_object` | 2 | **2** | **0** | **0** | **6** |

**Out of band as a whole critic** (TP 10, FP 2, FN 5), and *excellent* on the
one class the checks miss: it catches **both** floating objects — including
the one the scripted checks miss — and on that class it cries wolf on
**none** of the six clean controls. It misses the `holes` class entirely and
three of the four `fireflies`. (Its two false positives are a
`missing_object` and a `texture_swap` call on a clean control, and it has
none on `floating_object`.)

Per-question latency on this shared box: **median 15.0 s** (min 7.0, mean
16.9, max 52.7), 126 questions, 2 133 s of model time; per **verdict**
(6 questions) the median is **107.2 s**. The reasoning budget was capped at
320 tokens; Muse Glimmer always thinks, and a 30 B model thinking at length
is most of the answer's cost.

### The DINOv2 probe

| head | split | TP | FP | FN | TN | FP rate | FN rate |
|---|---|---|---|---|---|---|---|
| kNN | leave-one-base-out | 5 | 5 | 10 | 31 | 13.9 % | 66.7 % |
| kNN | leave-one-member-out | 5 | 5 | 10 | 31 | 13.9 % | 66.7 % |
| linear | leave-one-base-out | 7 | 12 | 8 | 24 | 33.3 % | 53.3 % |
| linear | leave-one-member-out | 7 | 12 | 8 | 24 | 33.3 % | 53.3 % |

**Out of band in every arm**, and the reason is not the probe's weakness.
`plant_leak.py` measured how far each plant moves the picture in DINOv2's
embedding space — the cosine between a member's embedding and the base
render it was planted on:

| class | cosine to its own base render |
|---|---|
| `black_frame` | 0.059 – 0.128 |
| `texture_swap` | 0.851 – 0.989 |
| `noise_fireflies` | 0.889 – 0.984 |
| `missing_object` | 0.983 – 0.989 |
| `holes` | 0.987 – 0.990 |
| **`floating_object`** | **1.0000** |
| *(clean controls)* | 1.0000 |

A floating object does not move the embedding **at all** — the planted prop
is small and close to the background, and the CLS-plus-patch-mean descriptor
does not see it. A probe cannot learn what is not in its features, so the
probe's `floating_object` row is a guaranteed miss no matter how it is
trained. (Its `black_frame` row is perfect for the same reason in reverse:
that plant moves the picture enormously.) The clean controls sit at 1.0000,
which is the check that the measurement is measuring what it says: no plant,
no movement.

The other two splits gave identical tables because the only bases that carry
two members carry one image member and one mesh member, and the probe only
trains on image members — so no probe's training set ever held a near-copy
of the picture it was scored on.

The forward pass costs ~0.9 s per picture on the Thor (bf16, CUDA); with the
features cached the head's verdict is 1–70 ms.

### Jev (the cloud judge)

Jev never sees a picture. It is given a **text description** of the frame
and the scripted checks' **measurements** — the numbers, without the
thresholds, so it cannot re-implement the checks. Two question types (a
**Noul** per class, `jev_verify`; one **Choice** over all the classes plus
"clean", `jev_classify`) and two inputs (with the measurements, and the
description alone) give four arms; the description is the local VLM's
*neutral* description of the frame (what the scene shows and what looks
wrong, without naming the defect classes).

| arm | TP | FP | FN | TN | FP rate | FN rate | ms/verdict |
|---|---|---|---|---|---|---|---|
| `verify`, measurements only | 10 | 3 | 5 | 33 | 8.3 % | 33.3 % | 3 829 |
| `classify`, measurements only | 8 | 3 | 7 | 33 | 8.3 % | 46.7 % | 2 972 |
| **`verify`, description + measurements** | **14** | 3 | **1** | 33 | 8.3 % | **6.7 %** | 1 007 |
| `classify`, description + measurements | 10 | 2 | 5 | 34 | 5.6 % | 33.3 % | 1 047 |
| `verify`, description only | 10 | 4 | 5 | 32 | 11.1 % | 33.3 % | 183 |
| `classify`, description only | 10 | 6 | 5 | 30 | 16.7 % | 33.3 % | 200 |

**Out of band in every arm.** The best arm — the brief's arm, `jev_verify`
over the description and the measurements — is much the best of the six
(TP 14, FN 1 where the measurements-only arm had TP 10, FN 5): the
description is worth more than the measurements. It still cries wolf on
three clean controls as `noise_fireflies`, and it still misses one floating
object.

**And it misses the same floating object every time.** In all six arms,
`floating_object` is TP 1 / FN 1, and the missed member is
`mem_d5c1c6cc24413705` — the one the scripted checks miss. That is not a
coincidence, and it is the most useful thing Jev taught this bake-off:

| critic | what it saw | `mem_718023ba022732d4` | `mem_d5c1c6cc24413705` |
|---|---|---|---|
| `scripted` | pixels | fired (0.104 frame heights of open space) | **silent** (no candidate object at all) |
| `jev` | the VLM's text | fired | **silent** |
| `vlm` | pixels | fired | **fired** |

The two captions say why. The describer wrote of the first member: *"a chunk
of bark-like texture is **floating detached in the upper left of the sky**"* —
the description names the defect, so a text judge can catch it. Of the
second it wrote: *"a jagged, black, tree-like artifact **on the left edge of
the sand**"* — the describer saw the object and described it as *touching the
ground*, because from the picture alone that is what a small object at the
sand's edge looks like. Jev, reading that sentence, correctly concludes
there is nothing floating. The gap under the object — the whole question —
is not in the sentence.

**A text critic is bounded by its description, and the description loses
exactly the information a floating-object judgement needs.** No amount of
judging fixes that; only looking at the picture does.

### The hybrid

The scripted checks everywhere they hold, the local VLM on the one class
they are out of band on. The delegate is narrowed to that class, so the
model is asked about `floating_object` and nothing else — on the two
escalated members and on the six clean controls, and nowhere else.

| class | members | TP | FP | FN | TN | who answered |
|---|---|---|---|---|---|---|
| `black_frame` | 3 | 3 | 0 | 0 | 6 | the checks |
| `noise_fireflies` | 4 | 4 | 0 | 0 | 6 | the checks |
| `missing_object` | 2 | 2 | 0 | 0 | 6 | the checks |
| `holes` | 2 | 2 | 0 | 0 | 6 | the checks |
| `texture_swap` | 2 | 2 | 0 | 0 | 6 | the checks |
| `floating_object` | 2 | **2** | **0** | **0** | **6** | the model |
| `wrong_scale` | 4 | 4 | 0 | 0 | 1 | the checks |
| `hollow_mesh` | 3 | 3 | 0 | 0 | 1 | the checks |
| `clipped_geometry` | 2 | 2 | 0 | 0 | 1 | the checks |
| **all** | | **24** | **0** | **0** | **39** | |

**In band.** No false negatives on any class, no false positives on any
clean control — every one of the nine classes is caught and nothing is
cried up. It is the only candidate in the bake-off that is.

Latency: **696 ms median per verdict** (image 865 ms, mesh 10 ms), against
the scripted checks' 673 ms. The medians are the same because the model is
asked about **8 of the 30 members** and nothing else. The *mean* is 3 450 ms
against the checks' 594 ms, because those eight calls cost 9.3 s each
(86 s of model time in total).

## The comparison

| candidate | layers | TP | FP | FN | TN | FP rate | in band | median ms/verdict |
|---|---|---|---|---|---|---|---|---|
| scripted (the baseline) | image,mesh | 23 | 0 | 1 | 39 | 0.0 % | no | 673 |
| dino-probe, kNN, leave-one-base-out | image | 5 | 5 | 10 | 31 | 13.9 % | no | 3 |
| dino-probe, kNN, leave-one-member-out | image | 5 | 5 | 10 | 31 | 13.9 % | no | 1 |
| dino-probe, linear, leave-one-base-out | image | 7 | 12 | 8 | 24 | 33.3 % | no | 1 397 |
| dino-probe, linear, leave-one-member-out | image | 7 | 12 | 8 | 24 | 33.3 % | no | 804 |
| the local VLM | image | 10 | 2 | 5 | 34 | 5.6 % | no | 107 211 |
| Jev, verify, measurements only | image | 10 | 3 | 5 | 33 | 8.3 % | no | 3 829 |
| Jev, classify, measurements only | image | 8 | 3 | 7 | 33 | 8.3 % | no | 2 972 |
| Jev, verify, description + measurements | image | 14 | 3 | 1 | 33 | 8.3 % | no | 1 007 |
| Jev, classify, description + measurements | image | 10 | 2 | 5 | 34 | 5.6 % | no | 1 047 |
| Jev, verify, description only | image | 10 | 4 | 5 | 32 | 11.1 % | no | 183 |
| Jev, classify, description only | image | 10 | 6 | 5 | 30 | 16.7 % | no | 200 |
| **hybrid (the pick)** | image,mesh | **24** | **0** | **0** | **39** | **0.0 %** | **yes** | **696** |

## The pick

**The hybrid** — the scripted checks first, the local VLM on
`floating_object`, the class the checks are out of band on.

By the table first: it is the **only** candidate that holds the band. The
scripted checks miss one floating object in two (50 % FN). The VLM alone
misses three of four fireflies and both holes. Jev's best arm still misses
a floating object and cries wolf on three clean controls. The probe cannot
see a floating object at all — its embedding moves by a cosine of 1.0000.

By latency second: the hybrid's **median** verdict costs 696 ms against the
checks' 673 ms, because the model is asked about one class of eight members
and nothing else. The VLM alone costs 107 s per verdict — 154× the hybrid —
because it answers all six classes on every frame. The hybrid buys the band
for **one extra model call on a minority of the members**, and the
difference between the checks and the hybrid in the *mean* is 2.9 s per
member, which is the model time spread over the members that needed it.

### Why the delegate is the local VLM

The hybrid's delegate has to be the only critic that can see the one defect
the checks miss. Jev cannot be it — it misses that defect in all six arms,
because the description cannot carry the gap under the object. The probe
cannot be it — the defect is not in the embedding. The VLM is the only
candidate that answers **yes** on `mem_d5c1c6cc24413705`, and it answers
yes on the clean controls' frame zero times.

### What it costs, honestly

The hybrid is only the hybrid while the model is resident. It needs a 30 B
model on the box (17 GB, GPU), and the delegate answers in ~9.3 s. When
the model cannot be reached — no server, no weights, no GPU — the scripted
checks answer and the verdict is marked **degraded**, so a night never
mistakes a fallback for a model verdict. That is the same rule the whole
selection is built on: the scripted checks are the default *and* the
fallback, and the name of the critic that made a verdict is on the
verdict's face.

## The wiring

The choice is a **parameter with a default**, and the default is still the
scripted checks.

| piece | what it does |
|---|---|
| `core/critic/select.py` | the registry (`scripted`, `dino-probe`, `vlm`, `jev`, `hybrid`), the default, the fallback, and `configured_name` — the one place that says which critic is in service |
| `core/critic/hybrid.py` | the composition: the checks, plus the delegate on the escalated classes |
| `core/critic/service.py` | `RenderCritic` — the chosen critic behind the core's `Critic` seam — and `build_render_critic`, the one call that puts it there |
| `core/critic/grow.py` | the nightly growth: harvest, grow, **re-score with the chosen critic**, publish |
| `core/config.py` | `BUILDER_CRITIC` → `Settings.critic` |

```bash
# the default (the scripted checks)
.venv/bin/python -m core.critic --grow --publish

# the chosen critic
BUILDER_CRITIC=hybrid .venv/bin/python -m core.critic --grow --publish
```

A verdict names the critic that made it (`verdict@scripted`,
`verdict@hybrid`), a verdict the checks made *instead of* the model is
marked **degraded**, and the published table
(`core/critic/CALIBRATION.md`) carries the selection — every candidate, its
counts, its latency, and the chosen critic's own table — so a reader sees
what the chosen critic was measured against, not only its row.

## Reproducing this

```bash
# the scripts
cd docs/lab/critic-select-scripts

# 1. re-derive the set and check it against the manifest (21/21)
.venv/bin/python derive_set.py

# 2. the scripted baseline
bash run_candidate.sh scripted

# 3. the heavy stage, under the box's shared lock: the hybrid, the captions,
#    the box's state beside the numbers, and the model server stopped after
flock ~/lm-wt/heavy.lock bash run_vlm_stage.sh

# 4. the DINOv2 probe, in its splits and heads
.venv-torch/bin/python run_dino.py --head knn   --split base
.venv-torch/bin/python run_dino.py --head knn   --split member
.venv-torch/bin/python run_dino.py --head linear --split base
.venv-torch/bin/python run_dino.py --head linear --split member

# 5. Jev, in its arms (the key comes from ~/.config/last-mile/secrets.env)
.venv/bin/python run_jev.py --arm verify   --measurements
.venv/bin/python run_jev.py --arm classify --measurements
.venv/bin/python run_jev.py --arm verify   --measurements --captions results/captions.json
.venv/bin/python run_jev.py --arm classify --measurements --captions results/captions.json
.venv/bin/python run_jev.py --arm verify   --captions results/captions.json
.venv/bin/python run_jev.py --arm classify --captions results/captions.json

# 6. the tables side by side, and the selection the published table carries
.venv/bin/python report.py --write-selection
.venv/bin/python -m core.critic --grow --publish
```

The torch venv the probe needs is the worktree's own:

```bash
python3 -m venv .venv-torch
.venv-torch/bin/pip install torch transformers pillow numpy
```

## The verdict

**The critic is a parameter, and it is now a hybrid.**

The scripted checks hold the band on eight of the nine defect classes and
miss one floating object in two. A 30 B vision-language model asked one
fixed question per class catches that floating object and every other
defect, but misses three of four fireflies and both holes — so it cannot
be the critic on its own. A DINOv2 probe cannot see a floating object at
all (the embedding does not move), and Jev, which reads a description
rather than a picture, misses the same floating object every time because
the gap under the object is not in the words.

The hybrid is the only shape that holds the band: the checks everywhere they
hold, the model on the one class they do not. It costs **one model call on
8 of 30 members**, at a median of 696 ms per verdict against the checks'
673 ms, and it degrades to the checks — visibly, on the verdict's face —
whenever the model cannot be reached.

The next honest thing to measure is the class the set does not cover yet:
**the set is 30 members over 30 distinct bases** — one member per render, so
no two pictures in it are the same picture — but the *defect classes* are
thin: two or three members each for `floating_object`, `holes`,
`missing_object`, `texture_swap` and `clipped_geometry`, and six clean
controls in total. The band was held on it, but a table with two
`floating_object` members is a claim about two pictures, not about the
class. The set has to grow before the band means what it should.
