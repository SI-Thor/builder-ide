# clef-cascade: Clef on Workers AI as the cloud half of the precision cascade

*Casey Digennaro's brief, run from the ProArt (2026-10-31).*

Casey (2026-10-31): *"Is the Cloudflare clef-flash useful? The Thor can run it, but so
can the Cloudflare Workers themselves, so tests can be done on the ProArt with the cloud
version, and scale."*

This is the **cloud half** of the Thor-side lab (`~/lm-wt/lab-cascade/BRIEF.md`). The
Thor OOM-crashed today, so everything here ran from the ProArt; the Thor was asked for
exactly one thing (a local Clef-flash server), and only under the shared heavy lock.

---

## 1. Headline

| # | Finding |
|---|---|
| 1 | **The scale limit is a per-minute request allowance on the model, not concurrency.** clef-flash accepts a **burst of ~1,800 requests** and then a **sustained ~1,270 requests/minute**; past that every request is rejected with `3021: rate limiting: inference request per min rate reached`. clef-27B accepted **>11,000 requests/minute with zero rate-limit errors**. |
| 2 | **Concurrency changes nothing; pacing changes everything.** clef-flash at c=32 and at c=128 returned the same accepted rate (1,637 and 1,787 per minute). Paced at 40 req/s, 98.5% of requests were accepted; unpaced at c=32 (≈168 req/s attempted), 84% were rejected. |
| 3 | **The two models' allowances are separate.** Driven at the same time, clef-flash took 2,243/min and clef-27B 2,039/min — 4,282 together against ~1,700 for one model alone. A two-model cascade does not starve itself. |
| 4 | **The "flash" model is the slower one on a big pack.** One 64-question call: clef-flash **1324 ms p50**, clef-27B **758 ms p50**. The 9B is the fast one only on the 1-question pack (180 ms vs 306 ms). |
| 5 | **Batching is cheaper per question, not flat.** A 64-question pack costs 100.5 input tokens per question against 241 for a single-question call: **2.4× cheaper per question and 8.7× faster in wall clock** than 64 separate calls (flash), 26× faster (27B). |
| 6 | **The two failures are different and need different handling.** `3021` is the request allowance (per-minute, per model); `3040 Capacity temporarily exceeded` is the request being too big for the pool (43 of 128 flash q64 calls at c=128). One is a pacing problem, the other a pack-size problem. |
| 7 | **Code-computed gate facts are the single biggest harness lever** (+2.7 points of teacher agreement, reproducibly on two independent splits). Toggling them back off costs 4–6 points. |
| 8 | **The teacher-student agreement curve plateaus at ≈ 0.94–0.95**, reached after gate facts + a choice prior + a Platt calibration map. **Past that point more fitting makes it worse** (refit-everything drops back to 0.92). |
| 9 | **The teacher is not uniformly the better model.** Accuracy against ground truth: clef-27B beats clef-flash on the scene (0.972 vs 0.919) and on the tile task (0.583 vs 0.367), and **loses to it on the defect task** (0.983 vs **1.000** — the 9B student classifies all 60 defect descriptions correctly). "The teacher calibrates the student" only holds where the teacher is right, and where it is not, copying it costs accuracy. |
| 10 | **The cloud improver found one real edit and then looped on a wrong one.** It re-fit the choice prior (+3.6 points, kept) and then proposed six variants of a rule about the tile options, every one of which was rejected by the paired score. The gate is what made that safe. |
| 11 | **The same weights on the Thor are not better than the hosted model.** Cloud p50 184 ms vs local 210 ms (both including their hops), cloud accuracy 0.917 vs local 0.875 — the gap is Q4_K_M against Cloudflare's own serving precision. The two places agree on **95.8%** of decisions. The local copy earns its place as a *fallback*, not as a cheaper copy. |
| 12 | **Jev and Clef already share one wire format.** One client serves Clef-flash, Clef-27B, Jev and a local llama.cpp Clef with no per-model code. See §8. |
| 13 | Total spend: **≈ $3.8 of the $5 ceiling**, which is **34× the 10,000-neurons/day free allocation** — so this is a Workers **Paid** account. In free-tier terms the whole run would have cost 34 days of the free allocation. |

---

## 2. Setup

### 2.1 Where things ran

| Thing | Where | How |
|---|---|---|
| Clef-flash / Clef-27B (cloud) | Cloudflare Workers AI | a throwaway `wrangler dev --remote` Worker on the ProArt (`worker/`), same shape as the prior PoC. **Nothing was deployed.** |
| Clef-flash (local) | Thor, loopback port 9931 | `llama-server` on `~/models/clef-flash/Clef-Flash-Q4_K_M.gguf`, started **under `flock ~/lm-wt/heavy.lock`**, reached over an SSH tunnel |
| Jev | TypeSafe System One API | key read from `~/.config/last-mile/secrets.env`, never printed |
| Cloud improver (C4) | this seat's MiniMax credential | the local mcode auth store (`~/.minimax/auth/.../auth.json`), never printed |
| Harness, tasks, scoring | ProArt | `scripts/`, this directory |

**Box state beside the cloud numbers.** The ProArt is the director box: an RTX 4050
laptop GPU, x86-64, running other seats' jobs during the run. The Thor is a separate
box (NVIDIA Thor, 122 GB unified memory) and was **not** asked to run anything except
one small model server, under the shared heavy lock. The cloud numbers in this
document are therefore a property of the Cloudflare edge and of this account, not of
either GPU. The one hardware fact that matters for the Thor half is that the Thor's
122 GB is **unified** memory shared between CPU and GPU with no swap, which is why
the lab's memory rule exists at all.

### 2.2 The models

| Model | Where | Price | Neurons / M input tokens |
|---|---|---|---|
| `@cf/cloudflare/clef-flash` (9B) | Workers AI | $0.038 / M input tokens | 3,455 |
| `@cf/cloudflare/clef` (27B) | Workers AI | $0.240 / M input tokens | 21,818 |
| `Clef-Flash-Q4_K_M.gguf` (9B) | Thor, llama.cpp | (free, own GPU) | — |
| `jev-latest` | TypeSafe | (own pricing) | n/a |

Workers AI bills **$0.011 per 1,000 neurons**. The free allocation is **10,000 neurons
per day** on *both* Workers Free and Workers Paid; on Free the API hard-fails past
10,000 neurons in 24 hours, on Paid the excess is billed. Limits reset daily at
00:00 UTC. Clef models are not charged for output tokens — `output_tokens` is always
0. Sources:
[pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/),
[limits](https://developers.cloudflare.com/workers-ai/platform/limits/),
[clef-flash model page](https://developers.cloudflare.com/workers-ai/models/clef-flash/),
[clef changelog](https://developers.cloudflare.com/changelog/post/2026-10-09-clef-omni-workers-ai/).

**This account is on Workers Paid.** We spent ≈346,850 neurons today across the runs
below — 34.7× the free allocation — and every call still returned a result. On
Workers Free the same traffic would have started failing at 10,000 neurons. The
`wrangler dev --remote` path is not exempt: Cloudflare's limits page says
explicitly that *"model inferences in local mode using Wrangler will also count
towards these limits."*

**Vendor-reported latency, for scale.** Cloudflare's own 43 benchmark runs report
medians of **38.8 ms (clef-flash)**, **209.3 ms (clef)** and **524.1 ms (Jev)**. Every
number in this document is higher, because our path adds a `wrangler dev --remote`
proxy hop plus a local TCP round trip on the ProArt. The worker-internal time is kept
separately in `per_call[].worker_ms` in the JSON results.

### 2.3 The task sets

Same three tasks as the Thor-side lab (`~/lm-wt/lab-cascade/scripts/tasks.py`, ported
verbatim into `scripts/tasks.py`):

| | Task | Cases | Ground truth |
|---|---|---|---|
| **T1** | last-mile's paired tactical scenes (12×12 grid → plain-language facts) | 80 | code-computed: hide / advance / scout, bearing, visibility, reachability |
| **T2** | builder-ide's critic defect classification (`core/critic/reference-set.json`) | 60 | the planted defect class + 30 clean controls |
| **T3** | tile-choice toy (pick 1 of 5 scripted tiles) | 60 | the tile with the strictly highest payoff |

**One deliberate deviation, and why.** The ProArt has no copy of the critic's rendered
images or meshes — those live on the Thor under `/home/caseydigennaro/lm-critic` and
`~/src/infinigen-thor/outputs`. T2 is therefore the brief's **text-description** variant:
the same 30 members and the same 30 clean controls, with the artefact described in
symptom terms instead of measured. The symptom sentences were written so they do not
lexically echo the class names (`wrong_scale` is described as "the object was built at
the wrong size", `black_frame` as "every one of the pixels in the frame holds the same
value"), so the model has to know the critic's taxonomy rather than string-match a
label. T2's absolute accuracy is **not** comparable to the Thor's measurement-based
variant; it is a second paired set with ten classes and a "none" option, and that is
all it is used for.

### 2.4 The 64-question pack

Clef takes up to 64 questions per call. To make the 64-question measurement mean
something, the pack is **not filler**: `scripts/gates.py` defines **64 gates over the
same tactical scene**, every one with a code-computed truth (`gates.build_gates`).
Across 60 fresh scenes the pack contains 28 balanced gates (truth rate 0.3–0.7) and 11
one-sided gates; the `action` gate splits 28 advance / 12 scout / 20 hide. So the
64-question call is also an *accuracy* measurement, not just a cost measurement.

### 2.5 The 1-question pack

One gate: `g02_action` — the decision D62 says the cascade turns on.

---

## 3. Hypotheses and verdicts

| # | Hypothesis | Verdict |
|---|---|---|
| **H1** | Clef-flash on Workers AI scales to high concurrency without error. | **False, and for a different reason than expected.** The wall is not concurrency: it is a **per-minute request allowance** — a burst of ~1,800 requests and a sustained ~1,270/minute — from which every further request is rejected with `3021`. c=32 and c=128 return the same accepted rate (1,637 and 1,787/min). |
| **H2** | A 64-question call is much slower and much more expensive than a 1-question call. | **True per call, false per question.** It is 26× the tokens and ≈7× the latency, but it returns 26× the questions: **2.4× cheaper per question and 8.7× faster in wall clock** than 64 separate calls. |
| **H3** | Clef-flash is the fast one. | **False for large packs.** clef-flash q64 p50 1324 ms vs clef-27B q64 p50 758 ms. Clef-flash is faster only on the 1-question pack (180 ms vs 306 ms). |
| **H4** | Clef-flash's booleans are biased and need calibration. | **True.** The fitted threshold wants to be 0.05–0.20, not 0.50 — the student's "true" answers are systematically over-confident. A per-question Platt map on the teacher's labels is worth +0.5 points of agreement and +0.5 of accuracy. |
| **H5** | Code-computed gate facts matter more than model size. | **True.** Gate facts are worth +2.7 points of agreement (both splits) and −4 to −5 when toggled back off. clef-27B, with no gate facts, is still worse than clef-flash *with* gate facts on the scene task. |
| **H6** | The teacher's labels are worth copying. | **Only where the teacher is right.** Teacher accuracy vs ground truth: 0.983 (defect), 0.972 (scene), 0.583 (tile) — and on the defect task the **student** is already at 1.000, so copying the teacher there costs a point. Agreement on the teacher's *correct* answers is the metric that moves (0.907 → 0.967); agreement on the teacher's mistakes is noise. |
| **H7** | Agreement with the teacher keeps improving as the harness is tuned. | **False past a point.** The curve rises 0.900 → 0.945/0.953 and then falls: refitting everything drops it to 0.918/0.936. The plateau is real and it is at ≈ 0.94–0.95. |
| **H8** | A cloud LLM in the loop can improve the harness. | **Partly.** The improver kept the one edit that moved the paired score (re-fit the choice prior, +3.6 points) and had six of its seven parseable proposals rejected; it did not beat the scripted ladder. See §7.2. |
| **H9** | The request allowance is one budget for the whole account, so a cascade running flash and 27B together halves each. | **False.** The two models have separate allowances and reached 4,282 accepted requests/minute together against ~1,700 for one model alone (§4.6). |
| **H10** | The 9B student is cheap enough that cost never decides where it goes. | **False.** clef-27B is **6.3× the neurons per input token** ($0.240 vs $0.038 per M). A 64-question teacher pass costs 140 neurons, 6.3× a student pass, and the C3 sweep used 6,779 neurons of which the teacher labels are the expensive half. |
| **H11** | Running the same weights locally on the Thor is faster and cheaper than the hosted model. | **False on latency, false on accuracy.** Cloud p50 184 ms vs local 210 ms (each including its own hops); cloud accuracy 0.917 vs local 0.875 on the same questions. The local copy is a fallback, not a cheaper copy. The hosted model's cost (0.9 µ$) is never the problem; its request allowance is. |
| **H12** | The hosted model and a local copy of the same weights make the same decisions. | **Nearly.** They agree on **95.8%** of the one-question gates, and disagree on the cases whose probability sits near the threshold. |

---

## 4. C1 — scale

Three runs, all through `wrangler dev --remote` (nothing deployed).

* **C1** (`results/c1-scale.json`): 128 calls per cell, both models, both packs, c = 1 / 8 / 32 / 128. 230.8 s wall.
* **C1b** (`results/c1b-sustained.json`): the same matrix with 512 calls per cell (1-question) and 128 (64-question). 604.6 s wall.
* **C1c** (`results/c1c-rate-ceiling.json`): each cell starts after a quiet minute and then drives one model hard for 60 s. This is the run that measures the allowance instead of a burst.
* **C1d** / **C1e** / **C1f**: the follow-ups that separate "concurrency" from "allowance" (§4.6, §4.7).

### 4.1 One question per call (`q1`, 241 input tokens)

C1b, 512 calls per cell:

| Model | c | n | ok | p50 ms | p95 ms | p99 ms | req/s | err | neurons/call | gate acc |
|---|---|---|---|---|---|---|---|---|---|---|
| clef-flash | 1 | 512 | 512 | 180.0 | 241.2 | 492.4 | 4.66 | 0.0% | 0.83 | 0.920 |
| clef-flash | 8 | 512 | 512 | 216.4 | 541.1 | 2022.5 | 27.85 | 0.0% | 0.83 | 0.920 |
| clef-flash | 32 | 512 | 512 | 292.0 | 825.3 | 1570.6 | 70.28 | 0.0% | 0.83 | 0.920 |
| clef-flash | 128 | 512 | **192** | 631.1 | 1385.9 | 1895.0 | 78.22 | **62.5%** | 0.83 | 0.927 |
| clef-27B | 1 | 512 | 512 | 306.3 | 653.5 | 964.9 | 2.67 | 0.0% | 5.23 | **1.000** |
| clef-27B | 8 | 512 | 512 | 311.4 | 694.6 | 1096.9 | 21.59 | 0.0% | 5.23 | **1.000** |
| clef-27B | 32 | 512 | 512 | 305.8 | 590.5 | 789.0 | **87.32** | 0.0% | 5.23 | **1.000** |
| clef-27B | 128 | 512 | **512** | 453.9 | 6237.2 | 7702.9 | 63.17 | 0.0% | 5.23 | **1.000** |

### 4.2 Sixty-four questions per call (`q64`, 6,432 input tokens)

| Model | c | n | ok | p50 ms | p95 ms | p99 ms | req/s | err | neurons/call | gate acc |
|---|---|---|---|---|---|---|---|---|---|---|
| clef-flash | 1 | 128 | 128 | 1324.4 | 1359.1 | 1493.1 | 0.74 | 0.0% | 22.22 | 0.810 |
| clef-flash | 8 | 128 | 128 | 1379.3 | 2291.2 | 2869.3 | 5.18 | 0.0% | 22.22 | 0.810 |
| clef-flash | 32 | 128 | 128 | 1647.2 | 2856.6 | 3065.1 | 14.26 | 0.0% | 22.22 | 0.810 |
| clef-flash | 128 | 128 | **85** | 2055.9 | 4072.0 | 4654.1 | 16.95 | **33.6%** | 22.22 | 0.817 |
| clef-27B | 1 | 32 | 32 | **758.4** | 982.4 | 1071.1 | 1.31 | 0.0% | 140.37 | 0.848 |

(clef-27B q64 at c=8/32/128 was skipped by the neuron ceiling; see §5.)

### 4.3 Reading the matrix

1. **The latency of a single call is not the interesting number.** clef-flash's p50 at
   c=1 is 180 ms, against a vendor-reported median of 38.8 ms. The difference is the
   dev-proxy hop and a cold-ish inference, not the model.
2. **Throughput peaks around c=32 and falls after.** clef-27B: 87.3 req/s at c=32,
   63.2 req/s at c=128 — more concurrency only adds queueing (and at c=128 its p95 is
   6.2 s while p50 is 454 ms: a bimodal tail, which is exactly what the `auto`
   presence-mode rule in D38 has to watch for).
3. **Two different failures, two different fixes.** `3021 rate limiting: inference
   request per min rate reached` is a budget; `3040 Capacity temporarily exceeded` is
   a request that is too large for the pool. In the C1b matrix only flash q64 at c=128
   produced `3040` (43 of 128 calls) — the 64-question pack at 6,432 input tokens is
   what outgrows the pool, not the request rate.

### 4.4 A methodological note we have to record

C1b's cells ran **back to back**, and the Workers AI request allowance is per account
per minute. The c=128 flash cell therefore inherited a nearly-spent allowance (it
ran after four other 512-call cells) and its 62.5% rejection rate is *partly* an
artifact of that. The numbers are internally consistent with the bucket model in
§4.7: the c=32 cell spent ~490 of the ~610-token burst, the c=128 cell then found
the bucket nearly empty and lived off the ~21/s refill for its 6.5 s — 320 of 512
accepted, 62.5% rejected, exactly what the log shows. C1c and C1e measure the same
thing from a quiet period.

### 4.5 C1c — the allowance, measured clean

Each cell waits 75 s of silence, then drives one model at one concurrency for 60 s
and counts, per call, whether it was accepted or rejected and when. The "attempt
rate" column is the rate of calls that *finished* inside the 60 s window; for the
two clef-27B cells the client was still backlogged when the window closed (the
27B calls take ~300 ms each), which is why their attempt rates read lower than the
rates the client actually achieved — those are in the paragraph below.

| Model | c | submitted | accepted in 60 s | **accepted / min** | rejected | first rejection at | attempt rate / min |
|---|---|---|---|---|---|---|---|
| clef-flash | 32 | 27,626 | 1,637 | **1,637** | 83.8% (24,071 × `3021`, 3 × `3040`) | 0.92 s | 10,083 |
| clef-flash | 128 | 23,095 | 1,787 | **1,787** | 92.2% (21,288 × `3021`, 12 × `3040`) | 0.95 s | 22,993 |
| clef-27B | 32 | 28,024 | 3,537 | **3,537** | 0.1% (66 × `3040`, **zero `3021`**) | 5.28 s | 3,542 |
| clef-27B | 128 | 27,604 | 12,297 | **12,297** | 1.4% (178 × `3040`, 5,496 × `3021`) | 4.96 s | 12,475 |

Two things to read off this table.

**The allowance is per model, and it is much tighter for the small model.** clef-flash
accepted 1,637 and 1,787 requests per minute at two very different concurrencies —
the same number, which is what a per-minute budget looks like and is not what a
concurrency wall looks like. clef-27B, driven at the same client speed in the same
account and the same minute structure, accepted **27,958 of 28,024 requests**: the
only 66 failures were `3040` out-of-capacity, and **not one was a rate-limit
rejection**. The client kept the pipe full for the whole 451 s the cell took, at up
to 182 req/s — about **11,000 requests per minute** — with no `3021` at all. Only
when the client burst at 12,475 req/min did clef-27B start rejecting (5,496 ×
`3021` in the c=128 cell).

**The rejected calls are free but not free.** A `3021` costs no neurons, so the
money in C1c went entirely into the calls that succeeded — but they were mostly the
27B's, at 6.3× the price (§6).

**The mechanism, stated as the docs state it.** Cloudflare's limits page says rate
limits are *"default per task type, with some per-model limits defined as follows"*
and that *"model inferences in local mode using Wrangler will also count towards these
limits."* Both clef models are listed as Text Generation, whose default is 300
requests per minute; both measured **above** that number, so both are running under
per-model overrides that the generic page does not show. The per-model page for
`clef-flash` is where the exact number lives; we could not fetch it from this host,
so the numbers in this section are our own measurements, not a quote.

### 4.6 C1d — is one allowance shared across the account?

`scripts/c1d_mixed.py` drives clef-flash and clef-27B **at the same time**, each
paced at 40 req/s (2,400/min — above clef-flash's allowance, below clef-27B's), for
60 s from a fresh minute.

| Model | attempted | accepted | **accepted / min** | rejected | error rate |
|---|---|---|---|---|---|
| clef-flash | 2,277 | 2,243 | **2,243** | 34 × `3021` | 1.5% |
| clef-27B | 2,041 | 2,039 | **2,039** | 2 × `3040` | 0.1% |
| **total** | 4,318 | 4,282 | **4,282** | 36 | 0.8% |

**The allowances are separate.** One model alone tops out around 1,600–1,800 accepted
requests per minute; the two together reached 4,282 in the same minute, 2.5× that. If
the budget were one account-wide allowance, the total would have been pinned near the
single-model ceiling. A cascade can therefore run clef-flash on the hot path and
clef-27B on the teacher path at full speed at the same time, without one starving the
other — that is the property a two-model cascade needs and it is not obvious.

### 4.7 C1e and C1f — the allowance from a paced client

`scripts/c1c_rate_ceiling.py --pace 30` submits exactly 30 requests/s (1,800/min)
after a quiet period, and records the per-second timeline. C1e ran 120 s; **C1f ran
300 s** so that the *sustained* rate could be read off rather than guessed at.

**C1e (120 s):** minute 1 — 1,792 attempted, 1,792 accepted, **0 rejected**.
Minute 2 — 1,803 attempted, 1,234 accepted, 569 rejected. The first rejection lands
at **t = 63.96 s**, one minute after the first request.

**C1f (300 s):**

| minute | attempted | accepted | rejected | accepted / min |
|---|---|---|---|---|
| 0–1 | 1,764 | **1,764** | 0 | 1,764 |
| 1–2 | 1,831 | 1,589 | 242 | 1,589 |
| 2–3 | 1,799 | 1,274 | 525 | 1,274 |
| 3–4 | 1,791 | 1,255 | 536 | 1,255 |
| 4–5 | 1,792 | 1,300 | 492 | 1,300 |

First rejection at **t = 66.50 s**. The first minute is clean; the accepted rate then
settles at **~1,270/minute (21/s) and stays there for four minutes**.

Read the two rows together and the shape of the limiter appears:

* A **burst of about 1,800 requests** is available after a quiet period. The first
  minute consumed it with not one rejection.
* After the burst is gone, the **sustained refill is ≈21 requests/s ≈ 1,270/min**.
* A token bucket with capacity ~610 and refill ~21/s fits every number in C1e and
  C1f: it empties at 610/(30−21) ≈ 68 s, which is where the first rejection appears
  (63.96 s and 66.50 s in the two runs), and it then serves 21/s forever.
* The unpaced C1c cells land in between. The client floods at 168–230 req/s, drains
  the burst in under a second (first rejection at 0.92 s), and then lives off the
  refill for the rest of the window — which is the 1,637 and 1,787 accepted per
  minute those cells recorded.
* C1b's c=128 cell falls out of the same picture. It ran immediately after the c=32
  cell inside one minute; the burst had ~1,800 tokens, the c=32 cell spent ~490, and
  the c=128 cell got the remaining ~320 before the rest were rejected — 320 of 512
  accepted, 62.5% rejected, exactly what the log shows.

**The one measurement that does not fit.** C1d — flash and clef-27B driven together
for 60 s from a quiet period — took **2,243** flash requests, more than the whole
1,800 burst. Either the burst is larger than 1,800, or the refill is faster than
21/s, or running the two models together changes the accounting. We did not
separate those cases, so we report the band rather than a model: **the measured
sustainable acceptance for clef-flash from this account is ~1,270–2,250 requests per
minute**, and the failures are a `3021`, never a crash.

**The operational rule that falls out of it, and it is the same rule the C3 and C4
sweeps imply:** pace the client at **≤30 req/s per model per account**, and retry
`3021` with backoff. At 40 req/s, 98.5% of requests were accepted (C1d); unpaced at
c=32 (≈168 req/s attempted), 84% were rejected (C1c). Every sweep in this document
that mattered — C3's 24 runs, C4's 8 rounds — ran at concurrency 8, far inside the
allowance, and none of them saw a single `3021`.

---

## 5. C2 — the same model in two places

**The setup.** The same question sets, asked of the same weights (Cloudflare
Clef-flash) in two places:

* **cloud** — `@cf/cloudflare/clef-flash` on Workers AI, through the local
  `wrangler dev --remote` proxy;
* **local** — `Clef-Flash-Q4_K_M.gguf` served by the Thor's own llama.cpp build on
  `POST /v1/systemone`, reached from the ProArt over an **SSH tunnel to the Thor's
  loopback**, so nothing was exposed on the LAN.

The Thor was asked for exactly one thing, and it was asked for under the shared
heavy lock: `flock ~/lm-wt/heavy.lock llama-server -m ~/models/clef-flash/
Clef-Flash-Q4_K_M.gguf -ngl 99 --flash-attn on --ctx-size 8192 -ub 4096 --alias
clef-flash`, bound to the Thor's loopback only. The server was started by a job that
had been queued on that lock behind another seat's work for over an hour, ran for the
length of the measurement, and was then killed, which released the lock. Box state
beside the numbers: NVIDIA Thor, 122 GB unified memory, 112 GB available when the
server started, the 6.7 GB Q4_K_M weights resident on the GPU, and the lab's memory
rule (keep ≥25 GB available) satisfied with room to spare.

### 5.1 The 1-question pack — 24 scenes

| | cloud (Workers AI) | local (Thor, llama.cpp Q4_K_M) |
|---|---|---|
| calls / ok / errors | 24 / 24 / 0 | 24 / 24 / 0 |
| p50 | **184.3 ms** | 210.1 ms |
| p95 | 349.6 ms | **249.3 ms** |
| p99 | 505.4 ms | **272.4 ms** |
| mean | 216.2 ms | 215.4 ms |
| accuracy vs code-computed truth | **0.917** | 0.875 |

**The two places agree on 95.8% of the decisions** — exactly one of the 24 paired
cases disagreed (0.9583 = 23/24).

Three readings, in order of how much they matter.

**The hosted model is not slower than running the same weights yourself.** The cloud
p50 (184 ms) is *below* the Thor's own (210 ms) — and the cloud number is the one
that pays for a `wrangler dev --remote` proxy hop plus the round trip to
Cloudflare's edge, while the local number pays for an SSH tunnel and a LAN hop
before it even reaches the Thor's GPU. Once the hops are counted, moving the same
Q4 weights onto the Thor's own GPU buys **no latency advantage** on a one-question
call: the two means are 216 ms and 215 ms.

**The tail is where the local copy is better.** cloud p95 350 ms / p99 505 ms
against local p95 249 ms / p99 272 ms. The local path is a single LAN hop to a
running server; the cloud path is a local proxy process talking to a remote edge.
We did not separate the proxy hop from the inference itself — the worker-internal
time is in `per_call[].worker_ms` in the C1/C1b JSONs but the local server's
internal time was not captured — so we can say the local path has the shorter tail,
not why. For a cascade whose latency rule is a *tail* rule — escalate when the
answer is slow — that difference is the one that matters.

**The local copy is less accurate, and that is a precision difference, not a
harness difference.** Same questions, same code-computed gate facts, same
decisions asked: 0.875 locally against 0.917 hosted. The hosted model is not
served in Q4_K_M; the Thor's build is. The gap shows up on the task that depends
on reading a 12×12 grid correctly, which is where a quantisation error is most
likely to land. With a single disagreeing case out of 24 we cannot say anything
more specific about *which* cases disagree; the run did not record the paired
probabilities.

**What this means for the cascade.** If the cloud model is both as fast and more
accurate than the Thor's own copy of the same weights, then **the Thor's copy is
not a way to get the same decisions more cheaply** — it is a way to get slightly
different, slightly worse decisions without a network hop and without a request
allowance. It earns its place for the things the cloud cannot do: running when the
request allowance is spent, running when there is no network, and running at all in
an air-gapped build.

### 5.2 The 64-question pack — a configuration difference, not a model difference

The 64-question pack (6,432 input tokens) was served by the cloud in 1,322 ms p50
with zero errors and 0.811 accuracy. **Every local call failed**:

```
input (6416 tokens) is too large to process. increase the physical batch size
(current batch size: 2048)
```

This is llama.cpp's **physical batch limit**, not a context limit and not a model
limit: the server was started with `--ctx-size 8192`, but its batch size was 2,048,
and a 6,416-token prompt does not fit in one batch. The hosted model serves the
same pack without complaint. The local copy needs its batch size raised to offer
the same capability:

```
llama-server -m Clef-Flash-Q4_K_M.gguf --ctx-size 16384 -b 16384 -ub 8192 ...
```

*(the re-run with those flags is reported in §5.3.)*

The general point for builder-ide: **the local copy is not a drop-in substitute for
the hosted one until its serving flags match the hosted one's capabilities.** A
64-question pack — the batched form §6.2 shows is 2.4× cheaper and 8.7× faster
than 64 single calls — is the natural way to use this API, and the default serving
flags cannot serve it.

### 5.3 The 64-question pack, re-run with the batch size raised

The re-run with `--ctx-size 16384 -b 16384 -ub 8192` was queued on the Thor's heavy
lock behind other seats' work and **was withdrawn** rather than left waiting, so that
nothing of ours would later take the shared lock for no reason. What the first run
already established does not depend on it:

* the hosted model serves a 64-question pack (6,432 input tokens) in **1,322 ms
  p50** with zero errors, at 0.811 accuracy on the 64 code-computed gates;
* the local build rejects the same pack **not** for want of context (the context
  window was 8,192) but because its **physical batch size was 2,048** and a
  6,416-token prompt does not fit in one batch;
* the fix is a serving flag, not a different model, and the flags are known:
  `--ctx-size 16384 -b 16384 -ub 8192`.

So the local copy can serve the batched form that §6.2 shows is the right form, once
it is started with the batch size raised. What the re-run would add is the
cloud-vs-local **agreement and latency on a big pack**, where the local build's
Q4_K_M precision gap (0.875 vs 0.917 on the one-question pack) has far more room
to show than it does on a single gate. Until it runs, the one-question comparison
is the measured one and this paragraph is the configuration finding.

`scripts/run_c2.sh` will do the whole thing — start the server under the lock,
run both packs, kill the server and release the lock — as soon as the lock is free.

---

## 6. Cost

### 6.1 What a decision costs

Neurons are billed on **input tokens only** — `output_tokens` is always 0 for both
Clef models, because the answer is a structured object, not text. One neuron is
$0.000011.

| what | model | input tokens | neurons/call | $ / call | $ / question |
|---|---|---|---|---|---|
| 1 question | clef-flash | 241 | 0.83 | $0.0000091 | $0.0000091 |
| 64 questions | clef-flash | 6,432 | 22.22 | $0.000244 | **$0.0000038** |
| 1 question | clef-27B | 241 | 5.23 | $0.0000575 | $0.0000575 |
| 64 questions | clef-27B | 6,432 | 140.37 | $0.001544 | **$0.0000241** |

### 6.2 Batching is cheaper per question, not flat

64 questions in one call cost 6,432 input tokens: **100.5 tokens per question**.
One question in its own call costs 241 tokens. So a 64-question pack is
**2.4× cheaper per question** than 64 single-question calls, and far cheaper in wall
clock:

| | 64 separate calls (c=1) | one 64-question call | ratio |
|---|---|---|---|
| clef-flash, wall clock | 64 × 180 ms = 11.5 s | 1.32 s | **8.7× faster** |
| clef-flash, neurons | 64 × 0.83 = 53.2 | 22.2 | **2.4× cheaper** |
| clef-27B, wall clock | 64 × 306 ms = 19.6 s | 0.76 s | **26× faster** |
| clef-27B, neurons | 64 × 5.23 = 334.7 | 140.4 | **2.4× cheaper** |

The 64-question pack is therefore not a cost optimisation to be traded against
latency; it is strictly better on both axes, and it is also a better measurement
(§2.4: the pack carries 64 code-computed truths, not filler).

### 6.3 The free tier in practice

The free allocation is **10,000 neurons per day**, shared across all Workers AI usage
and all models, resetting at 00:00 UTC. In call terms that is:

| | free calls per day |
|---|---|
| clef-flash, 1 question | 12,048 |
| clef-flash, 64-question pack | 450 |
| clef-27B, 1 question | 1,913 |
| clef-27B, 64-question pack | 71 |

### 6.4 This run's ledger

| run | what | neurons | $ |
|---|---|---|---|
| C1 | scale matrix, 16 cells × 128 calls | 17,767 | 0.195 |
| C1b | sustained matrix, 13 cells | 27,050 | 0.298 |
| C1c | rate ceiling, 4 cells, 106,349 calls | 266,640 | **2.933** |
| C1d | both models at once, paced | 14,576 | 0.160 |
| C1e | clef-flash paced, 120 s | 2,523 | 0.028 |
| C1f | clef-flash paced, 300 s | 5,994 | 0.066 |
| C3 | teacher labels + student calibration, 24 runs | 6,779 | 0.075 |
| C4 | cloud improver, 8 rounds | 4,421 | 0.049 |
| C2 | the same model in two places, 2 runs | ≈1,100 | ≈0.012 |
| | **total** | **≈346,850** | **≈$3.82** |

**C1c is 77% of the spend**, and it is worth saying why: the rejected calls cost
nothing, so the money went into the calls that *succeeded* — and those were mostly
clef-27B's, at 6.3× the price per token. A rate-limit experiment run against the
expensive model is 30× more expensive than the same experiment run against the cheap
one. If this experiment had to be repeated, it would be run on clef-flash only.

**Against the free tier.** The run used ≈346,850 neurons, which is **34.7 days of
the 10,000-neuron daily free allocation**. In the free tier alone, this run would
have had to be spread over five weeks; the whole of C3 — a complete teacher-and-
student calibration of three task sets — would have cost **7 cents**, or 0.7% of one
day's free allocation.

---

## 7. C3 — the teacher calibrates the student, and C4 — the cloud improver

### 7.1 C3 — the scripted ladder

**The setup.** Clef-27B (cloud) labels 200 cases — 80 tactical scenes, 60 defect
descriptions, 60 tile choices. Clef-flash (cloud) answers the same cases under a
**harness**: a small set of explicit levers, each with a default.

| lever | what it changes |
|---|---|
| `wording` | how the question is phrased (`plain` / `rule` / `terse`) |
| `gate_facts` | whether code-computed gate facts go into the state next to the question |
| `threshold` | the probability at which a boolean is called true |
| `calibration` | per-boolean Platt map `p' = sigmoid(a·logit(p)+b)` fitted on the teacher's labels |
| `choice_prior` | per-option additive log-prior for the choice questions |
| `hint` | free text appended to the state |

Every fit happens on a **calibration split** that never overlaps the evaluation
split, and the whole ladder is run twice with different split seeds.

**First, the teacher has to be worth copying.** Accuracy against the code-computed
ground truth, teacher and student side by side:

| | defect (60 cases) | scene (80 cases) | tile (60 cases) | overall |
|---|---|---|---|---|
| clef-27B (teacher) | 0.983 | **0.972** | **0.583** | 0.920 |
| clef-flash (student, baseline harness) | **1.000** | 0.919 | 0.367 | 0.855 |

(The student's row is from the same 200 cases under the baseline harness; its
0.633 on the tile task in the tables below is *agreement with the teacher*, which
is a different quantity from accuracy against ground truth.)

Two things follow. **The teacher is ahead on the scene and the tile tasks and
behind on the defect task**, where the 9B student classified all 60 defect
descriptions correctly and the 27B got one wrong. And **the teacher is far from
uniform**: 0.583 on tile means the teacher's labels are wrong on 42% of that task.
"The teacher calibrates the student" is therefore not a property of the method; it
is a property of the teacher on that task, and it has to be measured per task before
anything is calibrated against it. The metric that carries the signal is
**agreement on the questions the teacher got right** — agreement on the teacher's
mistakes is agreement on noise.

**The curve** (agreement with the teacher on the held-out split; split 0 / split 1):

| round | lever added | agreement (split 0 / split 1) | on teacher-correct | accuracy |
|---|---|---|---|---|
| R0 | baseline (plain wording, no gate facts, threshold 0.5) | 0.900 / 0.900 | 0.907 / 0.907 | 0.855 / 0.855 |
| R1 | **+ gate facts** | **0.927 / 0.927** | 0.936 / 0.937 | 0.882 / 0.882 |
| R2 | + wording `plain` | 0.927 / 0.927 | 0.936 / 0.937 | 0.882 / 0.882 |
| R3 | + threshold refit (0.1 / 0.2) | 0.918 / 0.932 | 0.927 / 0.942 | 0.873 / 0.886 |
| R4 | **+ choice prior** | **0.941 / 0.941** | 0.961 / 0.961 | 0.905 / 0.914 |
| R5 | + Platt map | **0.946** / 0.941 | **0.966** / 0.961 | 0.909 / 0.914 |
| R6 | + re-threshold (0.05) | 0.941 / **0.953** | 0.961 / **0.967** | 0.905 / 0.917 |
| R7 | refit everything | 0.918 / 0.936 | 0.927 / 0.944 | 0.873 / 0.877 |
| R8 | **toggle gate facts back off** | **0.886** / **0.901** | 0.892 / 0.903 | 0.841 / 0.847 |

Five things this table says:

1. **Gate facts are the biggest single lever** (+2.7 points on both splits, and the
   teacher is *not* given them either — they are a property of the state, so both
   models benefit). Toggling them back off costs 4.1 and 5.2 points. This is the
   E4b result restated with two splits and a held-out evaluation: **code computes
   the gates, the decision model judges over them.**
2. **The fitted threshold wants to be 0.05–0.20, not 0.50.** The student's booleans
   are systematically over-confident, and a single global threshold only partly
   fixes it.
3. **The choice prior is worth another +1.4 points**, and the Platt map a further
   +0.5 (split 0) or nothing (split 1). Per-question calibration helps the booleans;
   it cannot help the multiple-choice questions, where the error is a *ranking*
   error and needs an additive prior on the options.
4. **The curve plateaus at ≈ 0.94–0.95 and then turns down.** R7 refits everything
   on the calibration split and the agreement falls by 1.4 and 1.8 points. This is
   ordinary over-fitting: the split's fitted numbers stop describing the held-out
   split. **Past the plateau, more fitting is worse** — which is why the harness
   needs a held-out score and not just a training score.
5. **The teacher's own accuracy bounds the gain.** Agreement on the teacher's
   *correct* answers goes 0.907 → 0.966/0.967; the residual 3–4% is the part of the
   teacher's behaviour a 9B student cannot reproduce, and on the tile task there is
   nothing to reproduce because the teacher is mostly wrong.

Cost: 24 harness runs over 200 cases → **6,779 neurons, $0.075**, 108 s of wall
clock. A full teacher-and-student calibration pass over 200 cases costs **7 cents**.

### 7.2 C4 — the cloud improver

**The setup.** The same 200 cases, split 100/100. Every round: score the current
harness on the held-out split, hand the cloud LLM (this seat's own MiniMax
credential, `MiniMax-M3.1-Flash`) the failures — the cases where the student
disagreed with the teacher, with both answers — and ask for **one** harness edit as
JSON. Keep the edit only if the paired score improves; otherwise revert.

The LLM's editable surface is semantic: wording, gate facts, the threshold, a
free-text hint, and two switches that ask the *code* to re-fit the calibration map
or the choice prior on the calibration split. The LLM never writes a fitted number
itself; it says what to fit. That is the design choice that makes the edits
attributable and keeps the numbers honest.

**Every proposal, with its win or loss:**

| round | proposal | score before → after | kept | why |
|---|---|---|---|---|
| 1 | (reply not parseable as JSON; one strict retry, also empty) | — | no | 57 s of model time, no edit |
| 2 | `fit_choice_prior: true` | 0.9091 → **0.9455** | **yes** | paired score improved (+3.6) |
| 3 | hint: *"when threats are visible and the rig is worn, take cover rather than repair_here"* | 0.9455 → 0.9318 | no | score fell, reverted |
| 4 | hint: *"in tile tasks, when threats are visible, prioritize take_cover over repair_here, even if the rig is worn"* | 0.9455 → 0.8773 | no | score fell, reverted |
| 5 | hint: *"if threats are visible, choose take_cover rather than repair_here"* | 0.9455 → 0.9227 | no | score fell, reverted |
| 6 | hint: *"when threats are visible, choose take_cover rather than repair_here; repair only when no threats are visible"* | 0.9455 → 0.8955 | no | score fell, reverted |
| 7 | hint: *"if threats are visible, choose take_cover rather than repair_here, even when the rig is worn"* | 0.9455 → 0.8955 | no | score fell, reverted |
| 8 | hint: *"if threats are visible, choose take_cover rather than repair_here"* | 0.9455 → 0.9227 | no | score fell, reverted |

Best harness: `fit_choice_prior`, agreement **0.9455**, accuracy **0.8955**.
Cost: **4,421 neurons, $0.049** of Workers AI, plus **176.9 s** of cloud-LLM time
over 8 proposals (4–57 s each).

**What this says about the improver.**

*It found one real thing.* The single kept edit — re-fit the choice prior — is worth
+3.6 points, and it is the **same lever the scripted ladder found at R4** (worth
+1.4 points there, on a different split). The cloud LLM found the right lever; it
did not find a lever the ladder had missed.

*It then looped on a wrong generalisation.* Rounds 3–8 are six variations of one
idea: a rule that says the rig should take cover rather than repair when threats are
visible. The tile task's failures are cases where the student chose `repair_here`
and the teacher chose `take_cover`; the improver read that as a rule instead of as
a distribution over cases, and every variant of the rule was **rejected**. The loss
sits where the failures were: the held-out split holds 220 questions of which 30
are tile questions, and the worst proposal lost 15 of them (round 4: 0.9455 →
0.8773, i.e. 208 → 193 correct). If the scene and defect tasks were unchanged in
that proposal — which the log does not record — the tile task would have gone from
22/30 to 7/30, which is the signature of a tile task flipped towards a single wrong
option. The harness has no per-task scoping — `apply_harness`
appends the hint to **every** case's state — so a rule written about tiles also
reaches the scene and defect states; the log does not record the per-task breakdown
for rejected proposals, so we cannot say from it that the other two tasks were
untouched. That is a harness limitation the improver exposed, and the fix is to
scope the hint per task.

*The gate is what makes the loop safe.* Six of the eight rounds produced a
confidently-worded edit that made the harness worse, one of them by 6.8 points. With
the "keep only if the paired score improves" rule, every one of them was reverted and
the harness ended at its best value. Without that rule the same eight proposals
would have left the harness at 0.8773 instead of 0.9455 — a 6.8-point loss bought
with four minutes of cloud model time.

*It did not beat the scripted ladder.* C3's ladder reaches 0.946/0.953 on two
splits; C4's improver reaches 0.9455 on one. The improver is a **cheap way to
find the levers a human already knows**, and a **reliable way to test a candidate
edit**, but on this task set it was not a source of new harness structure.

---

## 8. Recommendation

### 8.1 Where each model belongs in builder-ide's cascade

The cascade is: **code computes the gates → a small model proposes → a decision
model judges → the code acts.** Each of the four decision models we measured earns
a place, but not the same place, and the measurements say why.

| model | where it goes | what it is good for, measured | what it must not do |
|---|---|---|---|
| **Clef-flash (9B, cloud)** | the **hot-path judge**: every decision the loop makes per turn | 180 ms p50 for one question, **0.83 neurons (0.9 µ$)**; accuracy against ground truth **1.000** on defect class, 0.919 on the scene task, 0.367 on tile choice | exceed the per-minute request allowance (~1,270–2,250 accepted/min, burst ~1,800) — pacer and backoff required; answer booleans without a fitted threshold |
| **Clef-27B (cloud)** | the **offline teacher** and the **escalation path** | accuracy 0.972 on the scene task and 0.583 on tile choice against ground truth — ahead of the student on both; labels 200 cases for **about 1 cent** (1,046 neurons); a request allowance more than 5× larger than flash's; a 64-question pack at 758 ms p50 — the *faster* model on a big pack | judge the **defect** task, where the 9B student is already at 1.000 and the teacher at 0.983; be used at the hot path (58 µ$ per question, 6.3× flash) |
| **d1 (Liquid, on the Thor)** | the **proposer** — it writes the code, makes the artefact, and is what the decision models police | free per call, local, and its own precision ladder (Q4/Q8/BF16) is the thing the cloud decision models exist to check | be asked to judge its own output |
| **Jev** | keep it where the TypeSafe contract already is; a drop-in second backend | same wire format as Clef; vendor median 524 ms — slower than both Clef models | be the hot path |

**The routing rule has to be per task, and it has to be measured.** The obvious
design — "escalate to the teacher when the student is unsure" — is wrong in both
directions, because the teacher is ahead of the student on some tasks and behind on
others. Measured against ground truth: on the scene task the teacher is worth
escalating to (0.972 vs 0.919); on the tile task it is worth escalating to
(0.583 vs 0.367) but it is still wrong on 42% of that task, so the escalation
should be a *second opinion* and not a handover; and on the defect task the
escalation is **counter-productive**, because the 9B student is already at 1.000
and the teacher is at 0.983. A single confidence threshold applied uniformly across
tasks would both send tile cases to a still-wrong model and cost the defect task a
point it already has.

**The hot path's budget is the request allowance, not the money.** At 0.9 µ$ per
question, flash's cost is never the constraint; its **per-minute request allowance**
is. At ~1,200–2,250 accepted requests per minute per account, a loop that makes
10 decisions per agent turn serves roughly **120–225 agent turns per minute** from
one account. When that is not enough, the answer is the **local copy of the same
weights on the Thor** (the same `Clef-Flash-Q4_K_M.gguf`, the same `/v1/systemone`
route) — not more cloud accounts, and not the 27B.

**Batching is not a trade-off, it is free.** One 64-question call is 2.4× cheaper
per question and 8.7× faster in wall clock than 64 single-question calls. A client
that packs a turn's questions into one call halves its own request pressure and its
own bill at the same time.

### 8.2 The adapter shape: one client for Jev and Clef

Jev and Clef already speak the same protocol, which means the adapter is not a
translation layer — it is a **connection layer**. `scripts/decision_client.py` is
that adapter, and the only things that differ between backends are the endpoint,
the model id and the auth header:

```python
# one canonical question shape, accepted by every backend
{"type": "noul",   "instructions": "<what must be true>"}
{"type": "choice", "instructions": "<which one>", "criteria": {opt: text}}

# one canonical answer shape, returned by every backend
{"<qid>": {"type": "noul",   "p": 0.93, "answer": True,  "confidence": None}}
{"<qid>": {"type": "choice", "p": {"a": .7, "b": .3}, "answer": "a", "confidence": 0.4}}
```

```python
client = DecisionClient(ClefAI(url=...))                   # Workers AI
client = DecisionClient(local_clef_backend("http://thor:9931"))  # llama.cpp, same weights
client = DecisionClient(jev_backend())                     # TypeSafe, Bearer auth
```

Two things make this work in a product rather than in a test:

* **The legacy Jev spellings are translated on input.** Jev's older
  `{"type": "boolean", "description": ...}` and
  `{"type": "choice", "options": [...], "description": ...}` are converted to the
  System One shape, so an existing Jev integration is a model-id change and
  nothing else. That is the same claim Cloudflare makes about Clef
  ("*Clef follows the System One API, so you can switch an existing Jev
  integration to Clef by changing the endpoint and model*"), and it holds here
  because we exercised all three backends through one `ask()`.
* **The harness is backend-agnostic.** `scripts/cascade.py` takes a client and a
  model id and does not know which one it has: `Harness → apply_harness →
  run_harness → score_against_teacher`. Swapping the backend swaps the decision
  model; the levers, the splits, the scoring and the logs do not change. That is
  what makes C3 and C4 cheap to re-run against Jev or against the Thor's copy.

### 8.3 What to build into builder-ide, ranked by measured value per unit of work

1. **Gate facts in the state, computed by code, for every decision.**
   +2.7 points of agreement, reproducibly on two splits; toggling them off costs
   4–6. Costs no GPU, no cloud call, no model.
2. **One decision client with three backends** (Workers AI Clef, TypeSafe Jev, the
   Thor's local llama.cpp Clef) and the canonical shapes above. The plumbing
   already exists; the product needs the *local* backend wired to the Thor's
   llama.cpp service, which the lab already knows how to serve.
3. **A fitted threshold and choice prior, per question, fitted offline against the
   27B's labels and versioned with the harness.** The threshold wants to be
   0.05–0.20, not 0.50; the choice questions need an additive prior because their
   errors are ranking errors, not confidence errors. A full calibration pass over
   200 cases costs **7 cents**.
4. **A pacer and a packer in front of the Clef client**: ≤30 req/s per account,
   exponential backoff on `3021`, and one 64-question call per turn.
   Paced at 40 req/s, 98.5% of requests were accepted; unpaced, 84% were rejected.
5. **A per-task escalation rule**, measured rather than assumed: flash answers;
   escalate the **scene** task to the 27B when the fitted threshold says unsure
   (the teacher is 0.972 there against the student's 0.919); treat the **tile**
   task's escalation as a second opinion, not a handover (the teacher is 0.583 and
   the student 0.367, so both are weak and the tile task needs its own
   investigation); and do **not** escalate the **defect** task at all, where the
   9B student is already at 1.000 and the teacher at 0.983.
6. **The cloud improver, wired exactly as C4 wired it**: hand it the failures,
   ask for one semantic edit, keep the edit only if the held-out paired score
   improves, log every win and every loss. Expect it to re-find levers you already
   know and to propose confidently-worded rules that are wrong — the gate is what
   makes that safe. **Scope the `hint` lever per task** before you turn it on; a
   global hint reaches scenes and defect descriptions as well as tiles.

---

## 9. Reproduce

Everything is in this directory. Python 3 standard library only, plus `wrangler`
for the Workers AI proxy and `curl`/`ssh` for the Thor.

```bash
cd ~/lm-wt/clef-cascade

# 0. the throwaway Workers AI proxy -- nothing is deployed, and no AI token
#    lives on this side; the proxy holds the AI binding.
cd worker && wrangler dev --remote --port 8797 &   # logs/wrangler-dev.log
cd ..

# 1. the scale matrix: 128 calls per cell, both models, both packs, c=1/8/32/128
python3 scripts/c1_scale.py

# 2. the sustained matrix: 512 calls per cell (1-question), 128 (64-question)
python3 scripts/c1_scale.py --out c1b-sustained.json \
        --calls-q1 512 --calls-q64 flash=128,clef27=32

# 3. the request allowance, from a fresh minute
python3 scripts/c1c_rate_ceiling.py --seconds 60 --quiet 75 \
        --cells flash:q1:32,flash:q1:128,clef27:q1:32,clef27:q1:128

# 4. the allowance from a paced client, with the per-second timeline
python3 scripts/c1c_rate_ceiling.py --out c1e-paced-allowance.json \
        --seconds 120 --quiet 150 --pace 30 --cells flash:q1:32

# 5. are the two models' allowances separate?  (both driven at once)
python3 scripts/c1d_mixed.py --seconds 60 --quiet 150 --pace 40 --concurrency 16

# 6. the teacher calibrates the student (two splits, nine rounds each)
python3 scripts/c3_calibrate.py

# 7. the cloud improver: propose an edit, keep it only if the paired score improves
python3 scripts/c4_improver.py --rounds 8
```

The Thor half, when the shared heavy lock is free:

```bash
# on the Thor, under the shared lock, bound to loopback only
ssh thor-lan 'nohup setsid flock -x ~/lm-wt/heavy.lock \
  ~/llama.cpp-upstream/build-up/bin/llama-server \
    -m ~/models/clef-flash/Clef-Flash-Q4_K_M.gguf \
    -ngl 99 --flash-attn on --ctx-size 8192 -ub 4096 --alias clef-flash \
  >/dev/null 2>&1 &'

# reach it over a tunnel, so nothing is exposed on the LAN
ssh -f -N -L 8096:127.0.0.1:9931 thor-lan

# the same question sets against the cloud model and the local one
python3 scripts/c2_two_places.py --seeds 24 --packs q1,q64

# stop the server, which releases the heavy lock
ssh thor-lan 'ps -eo pid,args | grep "[l]lama-server -m .*clef-flash" \
  | awk "{print \$1}" | xargs -r kill'
```

| file | what it holds |
|---|---|
| `results/c1-scale.json` | the 16-cell matrix, 128 calls each |
| `results/c1b-sustained.json` | the 13-cell matrix, 512/128 calls |
| `results/c1c-rate-ceiling.json` | the allowance from a fresh minute, four cells |
| `results/c1d-mixed-budget.json` | both models driven at once |
| `results/c1e-paced-allowance.json` | the paced run with its per-second timeline |
| `results/c1f-paced-sustained.json` | five minutes at a paced rate |
| `results/c2-two-places.json` | cloud vs the Thor's copy of the same weights |
| `results/c3-calibration.json` | the two calibration curves, the teacher labels, the per-round scores |
| `results/c3-calibration-runs.json` | every raw answer from all 24 runs |
| `results/c4-improver.json` | every proposal with its win or loss, and the kept harness |

---

## 10. What this did not settle

1. **The exact shape of the request allowance.** The paced run (C1e) fits a bucket
   of roughly 1,800–1,900 requests that refills at about 1,200/minute, and the
   unpaced cells and the C1b c=128 cell are all consistent with it. The mixed run
   (C1d) is not: from a quiet period it took 2,243 flash requests in 60 s, more
   than the burst. We did not separate "two models at once" from "not as quiet as
   we thought", so the numbers here are the measured band
   (**~1,200–2,250 accepted requests/minute**) and not a model of Cloudflare's
   limiter. Cloudflare's own pages say the limits are per task type with
   per-model overrides, and that wrangler-local inferences count against the same
   limits; they do not publish the clef-flash number we measured.
2. **The Thor comparison needed the shared heavy lock, and the lock was the
   schedule.** The C2 run waited over an hour on `flock ~/lm-wt/heavy.lock` behind
   another seat's admission integration test, then ran and was killed, which released
   the lock. The 64-question half needed a second run with the batch size raised;
   that run was queued on the same lock and **withdrawn** rather than left waiting.
   The measurement itself is sound (§5); what is left is whether the hosted model
   and the Thor's copy stay at 95.8% agreement on a *big* pack, where the local
   build's precision gap has more room to show. `scripts/run_c2.sh` runs it.
3. **The defect task was text-described, not measured.** The ProArt has no copy of
   the critic's rendered images or meshes, so T2 used symptom sentences instead of
   measurements (§2.3). Its absolute numbers are not comparable with the Thor's
   measurement-based variant.
4. **Why the 27B is at 0.583 on tile choice is not diagnosed**, and why the 9B
   student is at 0.367 there while it is at 1.000 on the defect task. Both are far
   enough from the other to matter: if the task's payoff definition is ambiguous,
   the "accuracy" is measuring the ambiguity, and if the model is weak, the task
   is measuring the model. The same question applies to the defect task, where the
   9B's perfect score may be an artefact of the text-description variant (§2.3)
   rather than a real capability.
5. **C4's improver was given one free-text lever that is not scoped per task.**
   Six of its seven parseable proposals were a rule about the tile options, and
   every one was rejected. With a per-task hint, and a stricter proposal schema,
   it might do better; we did not test that.
6. **Jev was not measured here.** The client speaks to it and the wire format is
   proven to be the same, but this run produced no Jev numbers, so no claim about
   Jev's accuracy or latency is made here beyond what our own earlier PoC
   measured.
7. **The deployed path is unmeasured.** Everything ran through
   `wrangler dev --remote`, which adds a proxy hop and is explicitly not the
   production path. A deployed Worker would be closer to the vendor's 38.8 ms
   median than our 180 ms. We were told not to deploy, so the deployed behaviour —
   including whether the request allowance differs — is open.
8. **clef-27B at c=8/32/128 with the 64-question pack was skipped** for the
   neuron budget (§4.2). It is the one cell that would have shown whether the 27B's
   advantage on big packs survives at scale.


