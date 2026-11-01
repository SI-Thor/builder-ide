# exp-critic-delegate — the hybrid's delegate, and a critic that answers with the next move

*Casey Digennaro's brief on branch `critic-delegate` (2026-10-31), run on the Thor.*

The brief had two halves.

1. **Swap the delegate.** The hybrid's delegate was the Thor's own Muse Glimmer
   30 B vision-language model. B2 forbids language models on the Thor, so that
   delegate was never allowed to run there in the first place. The brief asks
   for two replacements — **d1-2B with its multimodal projector** (local, on
   the box) and **clef-flash on Workers AI** (cloud, with the picture) — and
   for the reference-set bake-off to be re-run with each.
2. **Continuations, not only verdicts.** When the hybrid flags
   `floating_object`, the critic should also say what to do about it: the
   support surface below the thing and the distance to drop it, as a typed
   edit a builder can apply. The design doc calls this the anti-GAN: *a
   critic's output carries the next move* (`docs/design/three-minds.md`).

---

## 1. Headline

| # | Finding |
|---|---|
| 1 | **Neither decision model holds the band, and neither does the hybrid they are in.** The hybrid with d1-2B and the hybrid with clef-flash both score **TP 23 / FP 0 / FN 1 / TN 39** — the same row as the scripted checks alone. The old hybrid (the 30 B VLM) scored 24/0/0. |
| 2 | **The row does not move because of one member, not because of the models.** The miss is `mem_d5c1c6cc24413705` (coast-s6), whose **picture does not show a floating object**: the planted copy sits *on the sand*, with the beach under it. d1-2B says p(yes) = 0.041, clef-flash 0.020, the scripted check does not fire on it, and the 30 B VLM said "Yes" — which is the answer that carried the old row. |
| 3 | **The swap is still the right swap, on cost and on the rules.** The delegate's own call on a frame: **1.44 s median for d1-2B** (local, 241 ms per question) against **1.77 s for clef-flash** (cloud, 295 ms per question, of which 571 ms is the edge's own time) against **15.0 s per question for the 30 B VLM**. The hybrid's mean verdict: **1 217 ms with d1-2B**, **1 833 ms with clef-flash**, **3 450 ms with the 30 B**. And a 2 B decision model is not a language model, so B2 is satisfied by construction rather than by exception. |
| 4 | **The pick is the local one.** Same table row as the cloud one, cheaper by 1.2× on the model's calls and by 40× on the 30 B's, no network hop, no money, and no resident 17 GB. `d1-2B` is the hybrid's default delegate; the 30 B model is no longer anybody's default, and the `vlm` candidate cannot even be built without being told which model it is. |
| 5 | **The continuation works, and it is measurable.** The critic's typed edit (`lower_object`: the support surface below, the drop distance) is produced for every member where the hybrid flags `floating_object`, and applying it **clears the flag on the member whose defect is `floating_object`**: the scripted check's open space under the thing goes 0.1037 → 0.0000 frame heights, and the delegate's own p(yes) goes 0.954 → 0.395 (d1-2B) and 0.705 → 0.155 (clef-flash). On two other frames the *checks* fired on `floating_blob` while a different defect was planted; the continuation cleared one of those and not the other — the honest edge of a picture-domain probe (§6.4). |

---

## 2. The setup

### 2.1 The set — the same one, the same counting rule

The reference set is the one the first bake-off measured
(`core/critic/reference-set.json`): **30 members** over the overnight
Infinigen sweep's real renders — 21 in the **image** layer (6 clean controls
and 15 defective) and 9 in the **mesh** layer — with every defect planted
deterministically in `(base, seed)`.

The counting rule is unchanged (:func:`core.critic.critic.calibration_table`,
the cold-start seat's): a planted defect of class K that the check targeting K
does not fire on is a **false negative**; a check firing on a member carrying
a *different* class of planted defect is **excluded** from all four counts; on
a clean control, any firing is a false positive.

The harness is the first bake-off's own (`docs/lab/critic-select-scripts/harness.py`),
so the rows here are comparable with the rows there by construction: the same
members, the same fold, the same clock.

### 2.2 The candidates

| candidate | what it is | where it runs |
|---|---|---|
| `scripted` | the six image checks and the three mesh checks | the CPU lane, no model |
| `d1` | **d1-2B** (LFM3 decision model) **with its mmproj** — sees the frame, answers one typed yes/no question per class | the Thor's own GPU, `llama-server` on loopback, `POST /v1/systemone` |
| `clef` | **clef-flash** on Workers AI (9 B multimodal decision model) — the same questions, with the picture | a throwaway Worker under `wrangler dev --remote`; **nothing deployed** |
| `hybrid` | the scripted checks first, the delegate only on the class the checks are out of band on | both of the above |

**The questions are the same words for every delegate**
(`core/critic/candidates/questions.py`): the fixed per-class question the first
bake-off used, unchanged. They were written before this measurement and were
not tuned against it — a question chosen after seeing which members each model
gets right would be tuning on the set the numbers are measured on.

Two decision models answer a `noul` question with **the probability that the
answer is yes**, so the gate is a line at 0.5 and the distance from it is in
the verdict: `p(yes) = 0.954` is not the same answer as `p(yes) = 0.504`.

### 2.3 The box, beside the numbers

| | |
|---|---|
| Board | NVIDIA Jetson AGX Thor (Blackwell, sm_110), 122.8 GiB unified memory, 14 Neoverse cores |
| Kernel / arch | 6.8.12-1021-tegra / aarch64 |
| `MemAvailable` during the runs | 40.9 GiB (the d1 stage), 47.9 GiB (the scripted baseline), 48.9 GiB (the clef hybrid) — the memory rule's floor is 25 GiB |
| GPU | shared: another seat's Hunyuan generation held `~/lm-wt/heavy.lock` for the whole of the d1 stage, and three other d1-2B servers were resident (ports 8094, 8098, 8099) |
| The cloud half | Workers AI, a **Workers Paid** account (the clef-cascade seat's measurement), through a `wrangler dev --remote` proxy on the ProArt, reached from the Thor over an SSH forward |

Two consequences worth stating rather than hiding:

* **The d1-2B numbers are a contended measurement.** The 2 GB decision model
  ran while another seat's generation held the GPU. That makes the local
  delegate's latency an *upper* bound, so the comparison with the cloud
  delegate is conservative in the local delegate's favour.
* **The heavy lock was not taken for the d1 stage.** The lock is the box's
  rule for *heavy* steps (the 17 GB VLM, TRELLIS, Hunyuan). A 2 GB decision
  model is below that threshold, and the stage checks the memory rule's floor
  (≥ 25 GiB free) before it starts and prints the box's state beside the
  numbers.

---

## 3. The results

### 3.1 The comparison

| candidate | layers | TP | FP | FN | TN | FP rate | in band | median ms/verdict | mean ms/verdict |
|---|---|---|---|---|---|---|---|---|---|
| scripted (the baseline) | image, mesh | 23 | 0 | 1 | 39 | 0.0 % | no | 725 | 801 |
| d1-2B alone | image | 10 | 0 | 5 | 36 | 0.0 % | no | 1 447 | 1 271 |
| clef-flash alone | image | 9 | 0 | 6 | 36 | 0.0 % | no | 1 781 | 1 936 |
| **hybrid + d1-2B** | image, mesh | **23** | **0** | **1** | **39** | 0.0 % | no | 1 312 | **1 217** |
| hybrid + clef-flash | image, mesh | 23 | 0 | 1 | 39 | 0.0 % | no | 1 292 | 1 833 |
| *the old row: hybrid + Muse Glimmer 30 B* | *image, mesh* | *24* | *0* | *0* | *39* | *0.0 %* | ***yes*** | *696* | *3 450* |

The old row is in the table for comparison; it is **not available**: a 30 B
language model is exactly what B2 forbids on this box, and it cost 15.0 s per
question (107 s per verdict) against 241 ms for the local decision model.

### 3.2 Per class, the delegates alone

| class | members | d1-2B TP/FP/FN | clef-flash TP/FP/FN | the scripted checks TP/FP/FN |
|---|---|---|---|---|
| `black_frame` | 3 | 3/0/0 | 3/0/0 | 3/0/0 |
| `noise_fireflies` | 4 | **2**/0/2 | 1/0/3 | 4/0/0 |
| `missing_object` | 2 | 2/0/0 | 2/0/0 | 2/0/0 |
| `holes` | 2 | 0/0/2 | 0/0/2 | 2/0/0 |
| `texture_swap` | 2 | 2/0/0 | 2/0/0 | 2/0/0 |
| `floating_object` | 2 | 1/0/1 | 1/0/1 | 1/0/1 |
| **all (image layer)** | 15 | **10**/0/5 | 9/0/6 | 14/0/1 |

Both decision models are **quiet on the clean controls** (0 false positives
across the six, on every class) and both miss the `holes` class entirely. The
local one is never worse than the cloud one on any class, and better on
`noise_fireflies` (2 of 4 against 1 of 4).

### 3.3 The hybrid, per class

| class | members | hybrid + d1-2B | hybrid + clef-flash | who answered |
|---|---|---|---|---|
| `black_frame` | 3 | 3/0/0 | 3/0/0 | the checks |
| `noise_fireflies` | 4 | 4/0/0 | 4/0/0 | the checks |
| `missing_object` | 2 | 2/0/0 | 2/0/0 | the checks |
| `holes` | 2 | 2/0/0 | 2/0/0 | the checks |
| `texture_swap` | 2 | 2/0/0 | 2/0/0 | the checks |
| `floating_object` | 2 | **1/0/1** | **1/0/1** | the delegate |
| `wrong_scale` | 4 | 4/0/0 | 4/0/0 | the checks |
| `hollow_mesh` | 3 | 3/0/0 | 3/0/0 | the checks |
| `clipped_geometry` | 2 | 2/0/0 | 2/0/0 | the checks |
| **all** | | **23/0/1/39** | **23/0/1/39** | |

The hybrid is asked about one class on eight members (the two escalated ones
and the six clean controls), so its median verdict is the checks' median plus
a model call on a minority of the members — and its *mean* is where the
delegate's cost shows.

### 3.4 Latency

| | per request (6 questions) | per question | per verdict, hybrid | mean verdict, hybrid |
|---|---|---|---|---|
| d1-2B, local | **1 437 ms** median (min 573, max 1 697) | 241 ms | 1 312 ms | **1 217 ms** |
| clef-flash, cloud | 1 770 ms median (min 471, max 4 295), of which **571 ms** is the edge's own time | 295 ms | 1 292 ms | 1 833 ms |
| Muse Glimmer 30 B (the old delegate) | — | **15 000 ms** | 696 ms | 3 450 ms |

Two things the numbers say that the prose would not:

* **The picture is the cost.** One request carries the image once and scores
  every question against it, so the cost per *question* is a sixth of the
  cost per request. The cloud path pays the edge twice over — 571 ms of
  inference and 1.2 s of proxy and network — and its tail is wider
  (4.3 s against 1.7 s).
* **The old delegate's median was cheap and its mean was not.** The 30 B
  model's median verdict (696 ms) is *lower* than either decision model's,
  because the median member never reaches the model at all; its mean
  (3 450 ms) is 2.8× the local delegate's, because the eight members that do
  reach it each pay 17–53 s.

---

## 4. The pick

**The hybrid with d1-2B.**

By the table first: the two delegates are on the **same row** (23/0/1/39), so
the table does not separate them — and neither does it separate them from the
scripted checks. By latency then: the local delegate's request is 1.2×
cheaper than the cloud one's, its tail is 2.5× narrower, it costs no money
and no network hop, and its *mean* verdict is 1 217 ms against the cloud
hybrid's 1 833 ms.

The two reasons that are not latency:

* **B2.** A 2 B decision model is not a language model. The rule is satisfied
  by construction, not by an exception, and the box carries 2 GB of weights
  instead of 17 GB.
* **The delegate's answer is a probability.** `p(yes) = 0.954` on the member
  that shows a floater, `0.041` on the one that does not, and 0.002–0.112 on
  the six clean controls. The distance from the gate is in the verdict, so a
  night can see how close a call was instead of only whether it fired.

`core/critic/select.py` now names `d1` as the hybrid's default delegate
(`HYBRID_DELEGATE`), and `core/critic/candidates/vlm.py` has **no default
model**: the candidate cannot be built without being told which vision model
it is talking to, so the 30 B weights are never loaded by accident.

---

## 5. What the table does not move, and why

The miss is one member, and it is worth looking at rather than arguing about.

`mem_d5c1c6cc24413705` (coast-s6) is labelled `floating_object`. Its recipe
plants a copy of a rock cluster with the rule *"in a place where the frame has
open space below it"* — and the frame it landed in is a **beach**: the copy
sits on the sand, with the shoreline above it and the sand below. The plant's
own rule read the smooth sand under the copy as empty space; a person reading
the picture sees a rock cluster on a beach.

The four answers on that frame:

| who | answer |
|---|---|
| the scripted check | does not fire — the thing hangs in front of something busy (the shoreline), so the check skips it |
| d1-2B | p(yes) = **0.041** — no |
| clef-flash | p(yes) = **0.020** — no |
| Muse Glimmer 30 B (the old delegate) | **"Yes"** — and that answer is what carried the old hybrid's 24/0/0 row |

So the old row was carried by an answer on a frame that does not show the
defect its class names. The counting rule credits it as a true positive,
because the rule trusts the recipe, and the recipe says `floating_object`; the
pictures disagree with the recipe, and the models read the pictures.

**What this means for the set, not for the models.** With two members in the
class — one that visibly floats and one that does not — the class's row is a
coin-flip on the second member, whatever the delegate. The set needs a third
`floating_object` member that visibly hangs in empty space before the class's
row can mean anything.

**A second finding, about the checks.** The `floating_blob` check also fires
on the **clean** render of canyon-s4 — on the snow bank at the bottom of the
frame (a 1 386-px component with 0.122 frame heights of open space under it),
the same false positive the check is known for on smooth hillsides. It is
hidden on the derived member because the check takes the **first** qualifying
component, and the planted object comes first. canyon-s4 is not one of the
six clean controls, so the table never counted it. That is a latent false
positive in the checks, and it is now visible because the edit moved the
planted object out of the way.

---

## 6. The continuation: a verdict that carries the next move

The design doc's anti-GAN rule is that the critic's output carries the next
move, so the hybrid's verdict now carries a **continuation** beside its
findings.

### 6.1 The vocabulary (`core/critic/edits.py`)

The vocabulary is **closed**, because a builder changes recipes through a
closed, typed vocabulary and never by writing code:

```json
{
  "op": "lower_object",
  "target": "floating_blob",
  "box": [94, 70, 187, 181],
  "support": {"kind": "unknown", "label": "unknown", "row": 443, "source": "frame"},
  "drop_px": 262,
  "drop_frame_heights": 0.485185,
  "drop_m": null,
  "evidence": {"relief": 0.018862, "span": 0.681635, "support_row": 443.0}
}
```

* `op` — `lower_object`: put the thing that is floating down onto the surface
  below it. It is the only op today.
* `support` — **the support surface below the thing**: its row in the frame,
  its kind (`terrain`, `liquid`, `prop`, `unknown`) and which probe said so.
* `drop_px` / `drop_frame_heights` — **the drop distance**, in the frame's own
  units (both exact), plus `drop_m` in metres when a metric probe can reach
  the scene.
* `evidence` — the measured numbers the name came from, so a reader can see
  the measurement and not only the verdict.

The edit is a **proposal**. The critic never moves anything; the builder
makes the move.

### 6.2 The probe (`core/critic/surface.py`)

The support probe is the **frame domain**: it measures the picture the critic
was handed.

* **The thing.** The same component the scripted check fires on (the two
  share one selection, so they cannot disagree about what is meant). When the
  check did not fire but a model flagged the frame, the probe does a looser
  search and takes the thing with the **largest** open space under it.
* **The surface.** For each of the thing's columns, the row where the
  frame's structure resumes (the next detailed row). The surface's own row is
  the **median** of those: the minimum is one column's detail (a rock, an
  edge — the thing would come to rest on it and still hang over the slope
  beside it), and the maximum is a column with no detail at all until the
  frame's bottom (a smooth slope — the thing would be pushed out of the
  picture).
* **The kind.** A surface that carries **relief** (the local detail over the
  band is above the check's smooth threshold) is broken ground — `terrain`.
  A surface that measures flat is a plane, and a picture cannot say which
  plane it is: a lake, a beach and a snowfield all measure flat. So a flat
  surface is reported as `unknown` rather than guessed at, and the measured
  relief travels with the edit.

### 6.3 Applying it (`core/critic/edits.py`)

`edits.apply_edit` is what "applying the edit" means in the frame's domain:
the thing is **cut** out of the frame (against the row's own background model,
so its silhouette comes out whole and the sky between its branches stays
sky), the space it leaves is **filled** with the frame's own colour for those
rows, and the thing is **pasted** lower so that its bottom lands on the
support surface.

### 6.4 The test

`docs/lab/critic-delegate-scripts/continuation_test.py` takes every member
where the hybrid flagged `floating_object`, applies the edit the verdict
carries, and measures what happened. Both delegates were run; the table is
the same for both, because the flag on these three members is the same flag.

| member | who raised the flag | the edit | the checks' open space | the delegate's p(yes) | flag cleared |
|---|---|---|---|---|---|
| `mem_718023ba022732d4` (canyon-s4, `floating_object`) | **the delegate**: p = 0.954 (d1-2B) / 0.705 (clef-flash) | drop 262 px onto the surface at row 443 | 0.1037 → **0.0000** | 0.954 → **0.395** (d1-2B), 0.705 → **0.155** (clef-flash) | **yes** |
| `mem_65684b3ca047a1ae` (missing_object) | the scripted check (the delegate is not asked about a member carrying another class) | drop 113 px onto terrain at row 479 | 0.1796 → **0.0000** | — | **yes** |
| `mem_307101c469654adf` (holes) | the scripted check, for the same reason | drop 273 px onto terrain at row 355 | 0.1259 → **0.6407** | — | **no** |

Read plainly:

* **On the member whose defect is `floating_object`, the edit clears the
  flag.** The scripted check's open space under the thing goes to zero, and
  both delegates' answers go below the gate. That is the brief's test, and it
  passes.
* **On the two frames where the *checks* fired on `floating_blob` while a
  different defect was planted**, the continuation is a guess about which
  thing is meant, and the guess is sometimes wrong: on the `holes` member the
  probe pointed at a thing that was not the one the check had in mind, the
  edit made the open space under *that* thing larger, and the flag stayed.
  Those two members are excluded from the table's counts (the counting rule
  excludes a firing on a member carrying another class of planted defect), so
  they do not move the table — but they are the honest edge of the
  mechanism: **the critic can name a thing, and the picture alone cannot
  always say which thing a finding was about.**

---

## 7. What this makes possible, and what it does not

* **The delegate can be a small local model.** The old delegate needed 17 GB
  resident on the box and 15 s per question; the new one needs 2 GB and
  241 ms. That is the difference between a delegate that only runs on a
  quiet box and one that can stay resident while other work happens.
* **The critic can answer with a move.** A verdict that carries a typed edit
  is something a builder can apply without understanding the critic, and the
  edit is measurable: the support surface and the drop distance come from a
  probe, and the test says what happened when it was applied.
* **The reference set now has a hole in it.** The `floating_object` class has
  two members, one of which does not show the defect, and the class's row
  cannot be read until the set has a third member that visibly floats. The
  set needs that before the class can decide anything.
* **The checks have a latent false positive** on the clean render of
  canyon-s4, hidden behind the first-match rule. It is not in the table
  because canyon-s4 is not a clean control member.

---

## 8. Reproduce

```sh
# the local decision model: the Thor's own copy, loopback only, port 8131
bash docs/lab/critic-delegate-scripts/start_d1.sh

# the cloud delegate: a throwaway Worker on the ProArt, nothing deployed
#   cd worker && npx wrangler dev --remote --port 8797
#   and forward the port to the Thor (ssh -L 8797:127.0.0.1:8797 proart-lan)

# the bake-off: the baseline, the two delegates, the hybrid with each
bash docs/lab/critic-delegate-scripts/run_bakeoff.sh

# the continuation test: apply the edit, measure what happened
.venv/bin/python docs/lab/critic-delegate-scripts/continuation_test.py --delegate d1
.venv/bin/python docs/lab/critic-delegate-scripts/continuation_test.py --delegate clef

# the tables, side by side
.venv/bin/python docs/lab/critic-delegate-scripts/report.py
```

The scripts are in `docs/lab/critic-delegate-scripts/` and the results they
wrote are in `docs/lab/critic-delegate-scripts/results/`. The mesh half needs
an interpreter with `bpy`:

```sh
export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
```

---

## 9. The verdict

**The delegate is now a 2 B decision model that sees the frame, and the 30 B
vision-language model is gone from every default.** The swap was measured on
the same set, with the same counting rule, against the same two questions the
first bake-off asked: d1-2B and clef-flash land on the **same row**
(TP 23 / FP 0 / FN 1 / TN 39), the local one is 1.2× cheaper per call and
1.5× cheaper per verdict in the mean, and neither of them cries wolf on a
clean frame.

**The band is still not held, and the reason is the set, not the models.** The
one miss is a member whose picture shows a rock cluster on a beach; the
decision models read the picture and say no, the scripted check skips it, and
the 30 B VLM said yes. The set needs a third `floating_object` member that
visibly hangs in empty space before that row can be read at all.

**The critic now answers with the next move.** When the hybrid flags a
floating thing, the verdict carries a typed edit — the support surface below
it and the distance to drop it — and applying that edit clears the flag on the
member that shows the defect. On two frames where the *checks* fired on
`floating_blob` over a different planted defect, the continuation named the
wrong thing, which is the honest edge of a picture-domain probe: it can point
at a thing, but it cannot always say which thing a finding was about.
