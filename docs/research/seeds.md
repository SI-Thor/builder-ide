# seeds.md — the seed bank

Every distinct concept across the eleven source chats, kept or cut, with the reason.
Casey's brief (2026-10-31): "A lot is junk, but there are a lot of interesting concepts
that might not be completely right, but they can seed further R&D."

**120 entries.** Each one carries: the concept translated into our world; where it came
from (file and line); what is wrong with it as written; the kernel worth keeping (said
plainly when there is none); its status against the work already done; and, for new
seeds, the smallest experiment that would grow or kill it and the machine to run it on.

## How this was built

Read: all eleven `sources-*.md` documents in full; the library head start
(`library-small-acts-big.md`, 80 concepts) and the per-document extractions
(`library-new2.md`, `library-idea2.md`, `library-idea3.md`, `library-idea4.md`,
`library-idea5.md`); and the work already done — builder-ide `docs/research/liquid-study.md`,
`liquid-cascade-addendum.md`, `pincher-fit.md`, `jev.md`, `casey-ideas-fromgoogle5.md`,
`idea2.md`, `idea3.md`, `idea4.md`, `idea5.md`, `docs/lab/IDEAS.md`,
`docs/lab/exp-fp8-tensorcores.md`, `docs/lab/exp-fp4-path.md`,
`docs/lab/exp-fp4-models.md`, infinigen-thor `thor/THOR-MAKING-NOT-CONSUMING.md` and
`THOR-PERCEPTION-TO-GENERATION.md`, and the code in `core/tiles` (with OPE),
`core/hysteresis` and `core/genbatch/plausibility.py`.

The cascade addendum turned out to matter more than its title suggests: it is where the
measured facts live that decide whether half of this bank is live or dead — the 600M's
confidence, the three confidence formulas, the no-batching constraint on d1-2B, the
settled precision ladder, the MIG tooling gap, and the soft-label distillation route
that the chats were reaching for without a mechanism.

**The library head start was used, and its attributions were checked.** Of its 80
concepts, most sit where it says. Ten do not: its `#1 calibrated confidence`,
`#15 Brier score` and `#14 hysteresis barrier` are attributed to `fromgoogle4` but
actually live in `liquid1`/`liquid2`; `#38 somatic reflex arc`, `#47 myelination`,
`#50 retrograde signalling` and `#59 trace-guided self-optimisation` are attributed to
`fromgoogle4` but live in `liquid2`/`new1`/`new2`; `#53 viscous resonance` and
`#54 liquid attractor basins` are attributed to `fromgoogle4` but live in `new1`;
`#80 Aider as a second opinion` is attributed to `TEAM.md`, which is not one of our
source files. Every line reference below was re-derived from the source text rather
than taken from the library. The library's own meta-reading holds up: the concrete
concepts cluster around routing and memory, the metaphors around learning and safety.

**Names, models and repos were checked against the web and Hugging Face.** Results are
in §"Fact-check log" below. No code from the sources was run; nothing was measured on
the Thor.

**Clustering and the top ten were done with Groq** (`gq.py`): `gpt-oss-20b` for the bulk
proposal pass, `gpt-oss-120b` for the reconcile, the per-chunk assignment and the
second opinion on the top ten. Costs are logged in §"Groq cost log". The machine's
theme assignment was then hand-corrected where a second reading disagreed; every
correction is listed in the appendix so it is clear which assignments are the model's
and which are mine.

## How to read a status

- **already built** — the mechanism exists in the repo; the link says where.
- **already being tested** — a lab note is running it; the link says which.
- **killed by fact** — a measurement or a device-tree check has already closed it.
- **new** — nothing exists yet; the entry carries the experiment and the machine.

Nothing here is a verdict about an idea's value. Where a seed has no kernel, the entry
says so and stops.


---

## The seed bank


### A. Perception to generation: the measured set (`sources-fromminimax.md`)

#### A1 — Pixel distillation: train a small generator on ||A(G(y))-y||

- **The seed:** Pixel distillation: train a small generator on ||A(G(y))-y||, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:12`.
- **What is wrong as written:** The loss is degenerate: the round trip is satisfied by every point on the fiber, so the training signal says nothing about where on the fiber to land. Measured, not argued: 0.6053 off-manifold against 0.0551 for real data, eleven times worse, while the round trip itself looks perfect at 0.0621.
- **The kernel worth keeping:** Only the measurement survives: the obvious reconstruction loss is the wrong training signal. Keep as a negative result and as the reason our critic must check off-manifold geometry, not just consistency.
- **Status:** new.
- **Smallest experiment:** Retrain the student on the round-trip loss and measure the off-manifold score on the toy set; it has to come in under the 0.6053 the source measured, and it has to do it without the round trip looking perfect (numpy-only). **Machine:** numpy-only.

#### A2 — Consistency-only critic: score plausibility by comparing a frame to its own reconstruction

- **The seed:** Consistency-only critic: score plausibility by comparing a frame to its own reconstruction, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:13`.
- **What is wrong as written:** Consistency does not imply plausibility: a confident ghost passes every consistency check. Measured at 19x off-manifold.
- **The kernel worth keeping:** The negative result. A critic that only asks 'is this self-consistent' admits ghosts; plausibility has to come from a prior, separately.
- **Status:** new.
- **Smallest experiment:** Already measured to fail at 0.9925 off-manifold while passing every ghost frame. Do not build a consistency-only critic; if a critic is proposed without a plausibility side, this is the answer. **Machine:** Thor GPU.

#### A3 — Stochastic exact conditional: sample the inverse rather than solve it

- **The seed:** Stochastic exact conditional: sample the inverse rather than solve it, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:14`.
- **What is wrong as written:** Only tier measured to be both plausible and consistent (0.0530 off-manifold vs 0.0595 round trip). The sampling mechanism itself is not specified in the chat.
- **The kernel worth keeping:** Sampling the conditional instead of inverting it. The one tier of the four that survives its own measurement.
- **Status:** new.
- **Smallest experiment:** Implement stochastic exact conditional sampling on the toy set and confirm it holds off-manifold at or below 0.0530 while the round trip stays near 0.0595 (numpy-only). **Machine:** numpy-only.

#### A4 — Fiber-width gate: per-frame test of whether a deterministic inverse is even possible

- **The seed:** Fiber-width gate: per-frame test of whether a deterministic inverse is even possible, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:30`.
- **What is wrong as written:** AUC 0.809 overall but 1.000 on wide fibers: the gate is nearly perfect on the easy half and mediocre on the hard half, so it cannot be used as a general plausibility test.
- **The kernel worth keeping:** A cheap per-frame admissibility test that fires before the expensive comparison. The AUC-1.000-on-wide-fibers result says it should gate on geometry, not on the frame.
- **Status:** new.
- **Smallest experiment:** Score the fiber-width gate's AUC on the existing toy set and check it stays at 0.809 overall and 1.000 on wide fibers; if the wide-fiber number falls, the gate is not usable (numpy-only). **Machine:** numpy-only.

#### A5 — Two-sided critic band: consistency from perception plus plausibility from prior, with the 4.4e-5 gradient-scale gap handled explicitly

- **The seed:** Two-sided critic band: consistency from perception plus plausibility from prior, with the 4.4e-5 gradient-scale gap handled explicitly, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:16`.
- **What is wrong as written:** The gap between the two gradients is 4.4e-5, so a single summed loss silently lets the consistency term dominate. The chat does not say which side wins.
- **The kernel worth keeping:** Two critic heads with separate, explicitly scaled gradients, because the natural scales differ by five orders of magnitude. We already have two-sided scoring in the solver; this is the critic analogue.
- **Status:** new.
- **Smallest experiment:** Build the two-sided critic with separate gradient scales and measure that the consistency term cannot swamp the plausibility term at the 4.4e-5 gap (numpy-only first). **Machine:** numpy-only first, then Thor GPU.

#### A6 — Learned-score sampler: train a scoring net to imitate the plausibility score

- **The seed:** Learned-score sampler: train a scoring net to imitate the plausibility score, landing in critic / plausibility.
- **Source:** `sources-fromminimax.md:37`.
- **What is wrong as written:** Measured to fail: 1.8213 off-manifold against 0.0545 for exact comparison. The learned scorer is worse than the thing it imitates by 33x. The same shape appears elsewhere in the corpus as peer-judgement rules compiled into a tensor layer for the whole swarm to score at once, and it fails for the same reason: the rules are not linear in the state vector.
- **The kernel worth keeping:** The negative result that matters: a learned proxy for a geometric test is not worth it, whether it is a small sampler or a collective tensor layer. Use the geometric test, and check the linearity assumption before believing the collective form.
- **Status:** new.
- **Smallest experiment:** Already measured to fail at 1.8213 against 0.0545 for the exact test; do not train it. If anyone proposes it, the answer is the measurement in sources-fromminimax.md:37. **Machine:** Thor GPU.

#### A7 — Perception-to-generation round trip as a generation-time filter

- **The seed:** Perception-to-generation round trip as a generation-time filter, landing in Thor world engine.
- **Source:** `sources-fromminimax.md:18`.
- **What is wrong as written:** The chat uses the round trip as a training loss, and the measurement shows that loss is degenerate. Used as a filter at generation time it is a different proposition with a different cost, and the chat never makes that move.
- **The kernel worth keeping:** Generate, then re-perceive, then compare. As a post-hoc admissibility gate rather than a training signal.
- **Status:** new.
- **Smallest experiment:** Run the perception round trip on a batch of generated tiles and count how many confident ghosts it rejects; it must reject the known ghosts from sources-fromminimax.md without rejecting good tiles (Thor GPU). **Machine:** Thor GPU.

#### A8 — Perception and generation share one latent rather than two passes

- **The seed:** Perception and generation share one latent rather than two passes, landing in Thor world engine.
- **Source:** `sources-liquid2.md:340`.
- **What is wrong as written:** No mechanism: 'generate out of the perception map' says what the output should look like, not how it is computed.
- **The kernel worth keeping:** One shared representation. Worth one experiment: does a single backbone beat the two-pass chain on our assets?
- **Status:** new.
- **Smallest experiment:** Compare one shared backbone against the two-pass chain on the same tiles, judging only on plausibility; it wins if it matches the two-pass score at half the wall time (Thor GPU). **Machine:** Thor GPU.


### B. Decision models and the edge cascade (`sources-liquid1.md`, `sources-liquid2.md`)

#### B1 — Route on a calibrated confidence score, not on the answer itself

- **The seed:** Route on a calibrated confidence score, not on the answer itself, landing in tiles / decision models.
- **Source:** `sources-liquid2.md:802`.
- **What is wrong as written:** The thresholds (>=0.90 etc.) are asserted and no calibration procedure is given. Worse: our own measurement says the 600M means 0.97 confidence at 0.415 accuracy, and through the LFM2 formula 0.97 means p_max ~ 0.976 — nearly deterministic and mostly wrong. The signal is not merely uncalibrated, it is a different quantity per model.
- **The kernel worth keeping:** Confidence as the routing signal, recomputed from the probability vector under one stated definition. Our own reading of llama.cpp shows the three d1 sizes return confidence by three different formulas — a normalised margin for the LFM2 cells, the raw top probability for the LFM3 cell — so a confidence column that puts them side by side compares a margin against a probability. The hysteresis gate is built; the definition is not.
- **Status:** already being tested. `core/hysteresis` and the ambiguity gate; the desk's E1 in `docs/research/pincher-fit.md`. The confidence definition behind it is still open: the three d1 sizes return confidence by three different formulas, so the gate's bounds are not yet comparable across models

#### B2 — Confidence-tiered escalation: high confidence local, medium local-fallback plus async cloud audit, low cloud triage

- **The seed:** Confidence-tiered escalation: high confidence local, medium local-fallback plus async cloud audit, low cloud triage, landing in first mile / decision models.
- **Source:** `sources-liquid1.md:420`.
- **What is wrong as written:** The tier boundaries are invented, and the trigger itself is broken: the 600M's confidence cannot gate its own escalation (0.97 mean confidence at 0.415 accuracy). The async cloud audit on a Wi-Fi link also has no deadline and no failure path.
- **The kernel worth keeping:** A three-rung escalation with a hard deadline at each rung, and a measured cost-accuracy frontier rather than a single operating point. The deadline is the part worth keeping: it is what makes 'never wait' possible.
- **Status:** new.
- **Smallest experiment:** Run the ladder as a cascade and measure the cost-accuracy frontier: for escalation thresholds over the rung-0 confidence, plot (escalation rate, accuracy, seconds per item, calls per item). The deliverable is the frontier, not one operating point (ProArt). **Machine:** ProArt.

#### B3 — Cascaded edge tier: a 600M always-on model wakes a 3B model only on ambiguity

- **The seed:** Cascaded edge tier: a 600M always-on model wakes a 3B model only on ambiguity, landing in first mile / decision models.
- **Source:** `sources-liquid1.md:237`.
- **What is wrong as written:** The 600M/3B sizes are the marketing names, and the family is wider than the chat assumes: HF carries d1-3B, d1-2B, d1-Omni-2B and d1-omni-600M, and d1-ultra is API-only. The hard constraint the chat misses is that d1-2B cannot be batched at all — llama.cpp sets no_batching for lfm3-d1 — so the accuracy-winning rung is the one that cannot be served concurrently.
- **The kernel worth keeping:** Two resident models with a wake condition. Our boxes already hold two; the missing piece is the wake trigger and its cost.
- **Status:** new.
- **Smallest experiment:** Serve the same task from d1-2B and d1-3B with --parallel N and --cont-batching for N in {1, 4, 8} and measure per-item latency and items/s. The accuracy ceiling and the throughput ceiling are different cells, and which one is right depends on how many decisions the night makes per second (Thor GPU). **Machine:** Thor GPU.

#### B4 — Local precision promotion: keep an FP4 copy resident and swap in an INT8/FP16 copy when the FP4 lane is ambiguous

- **The seed:** Local precision promotion: keep an FP4 copy resident and swap in an INT8/FP16 copy when the FP4 lane is ambiguous, landing in decision models.
- **Source:** `sources-liquid1.md:1061`.
- **What is wrong as written:** The cited ~4ms to ~15ms TensorRT profile switch is invented, and the promotion it describes solves a problem that no longer exists: native NVFP4 through cuBLASLt measures 371-456 TFLOPS dense at K>=2048, at half FP8's joules and 3.55x smaller weights than BF16, so there is nothing to promote away from. The earlier 13.69 TFLOPS kill was a path artefact - torchao dequantises to BF16 and never touches the FP4 units - so it was a right measurement and the wrong conclusion about the hardware.
- **The kernel worth keeping:** Precision promotion as a mechanism: nothing. The promotion existed to escape a slow FP4 path, and the native path removes the reason for it. What replaces it is a shape gate rather than a precision switch: FP4 for the 5120-dim ff and attention-projection blocks and the long-K scorers, BF16 for the 320 and 640-dim blocks, where the library kernels still lose.
- **Status:** killed by fact.

#### B5 — FP4 noise rejection by an external calibrated decision head

- **The seed:** FP4 noise rejection by an external calibrated decision head, landing in decision models.
- **Source:** `sources-liquid1.md:225`.
- **What is wrong as written:** The premise was wrong when it was written - the FP4 lane was not usable at all - and is wrong now for a different reason: the native NVFP4 path is 371-456 TFLOPS at K>=2048 and half FP8's joules, so the argument is not that FP4 is unusable but that a 13.6% relative error needs a structural check, and a second model on a memory-tight box is a poor place to put it.
- **The kernel worth keeping:** Keep the shape and drop the premise: a cheap structural check over a quantisation-noisy output is still the right idea. The error it checks for is real - NVFP4 against a BF16 reference measures 0.1359 relative, the expected e2m1 error - and the check should be a rule over the packed codes rather than another model call.
- **Status:** new.
- **Smallest experiment:** Quantize a real block to NVFP4 and measure the relative error against the BF16 reference (the lab measured 0.1359), then check how much of that error a structural rule over the packed codes can catch before a second model is needed (Thor GPU). **Machine:** Thor GPU.

#### B7 — Cloud as prompt and weight-bias tuner: the cloud rewrites local prompts, cutoffs and biases from logged failures

- **The seed:** Cloud as prompt and weight-bias tuner: the cloud rewrites local prompts, cutoffs and biases from logged failures, landing in first mile / night.
- **Source:** `sources-liquid1.md:264`.
- **What is wrong as written:** Two different things are called a 'weights patch'; a prompt rewrite and a weight update have different blast radii and different rollback semantics.
- **The kernel worth keeping:** Separate the prompt plane from the weight plane, and give each a different promotion rule. This is the B2 cloud boundary.
- **Status:** new.
- **Smallest experiment:** Run jev_classify over the ladder's task set, keep the full probability vector rather than the argmax, and fine-tune the local d1 model on those soft labels. Then re-measure the local model's ECE: if the soft labels carry Jev's confidence structure, the local confidence becomes usable as a routing signal, which is the real version of cloud calibration (cloud plus one local training run). **Machine:** cloud.

#### B8 — Delta-weight patch plus atomic pointer swap: cloud returns a condensed weight delta, staged, then swapped in one cycle

- **The seed:** Delta-weight patch plus atomic pointer swap: cloud returns a condensed weight delta, staged, then swapped in one cycle, landing in night / stage cache.
- **Source:** `sources-liquid2.md:82`.
- **What is wrong as written:** 'Condensed weight delta' is not a thing you can pointer-swap; weights live in device memory and a swap needs two full copies.
- **The kernel worth keeping:** The double-buffer discipline is the kernel: one staging slot, one live slot, one atomic pointer flip, one cycle to revert. We already do this for tiles.
- **Status:** already being tested. the tile pointer swap in `core/tiles`; `docs/lab/IDEAS.md` Part A

#### B10 — Frozen backbone plus a detachable System-1 decision head (Blocks of Experts)

- **The seed:** Frozen backbone plus a detachable System-1 decision head (Blocks of Experts), landing in decision models.
- **Source:** `sources-liquid1.md:275`.
- **What is wrong as written:** The chat says a '40-million-parameter' head; the shipped JEV-27B trains 108.9M on a Qwen3.8-27B backbone, and the head is 24 slots, not a classifier.
- **The kernel worth keeping:** Freeze the big model, train a small typed-decision head beside it. Real and open (Apache-2.0), but the 27B backbone does not fit the Thor's budget alongside the world engine.
- **Status:** new.
- **Smallest experiment:** Load a JEV-27B-class model plus its adapter and measure the prefill cost of a typed decision; if the prefill dominates, the detachable head does not buy what the card claims (cloud). **Machine:** cloud.

#### B11 — Single-forward-pass decision head instead of token generation

- **The seed:** Single-forward-pass decision head instead of token generation, landing in decision models.
- **Source:** `sources-liquid1.md:55`.
- **What is wrong as written:** The O(1) vs O(T*N) argument is right in shape but the head still costs a full prefill. The idea is also already the product: d1 is a single forward pass returning typed answers with probabilities and zero generated tokens, and it runs on llama.cpp today.
- **The kernel worth keeping:** Typed decisions in one pass. Already the shape of every d1 decision we make. The prefill dominates, so the win comes from prompt discipline, not from the head.
- **Status:** already built. every d1 decision we make: typed answers with probabilities, zero generated tokens, one forward pass, served by llama.cpp's `server-decision.cpp`

#### B12 — Warp-shuffle argmax: resolve the decision in registers with shfl.sync and vote.ballot instead of a decode loop

- **The seed:** Warp-shuffle argmax: resolve the decision in registers with shfl.sync and vote.ballot instead of a decode loop, landing in decision models.
- **Source:** `sources-fromgoogle4.md:715`.
- **What is wrong as written:** The claimed ~8ns is an instruction-latency figure, not a model latency; it ignores the prefill entirely.
- **The kernel worth keeping:** In-register reduction for a small decision. Real CUDA, cheap, and it only matters if the head is on-device.
- **Status:** new.
- **Smallest experiment:** Implement the ballot reduction on a small decision and compare it against a shared-memory reduction at the same batch size (Thor GPU). **Machine:** Thor GPU.

#### B13 — Early-exit sub-network: exit at layer 12 if the intermediate head is confident

- **The seed:** Early-exit sub-network: exit at layer 12 if the intermediate head is confident, landing in decision models.
- **Source:** `sources-liquid1.md:482`.
- **What is wrong as written:** The 0.8ms vs 4.2ms figures are invented, and an early exit on an LLM's decoder is not the same as on a classifier.
- **The kernel worth keeping:** Exit-on-confidence for a small model. Plausible for a classifier head; unproven for a decoder.
- **Status:** new.
- **Smallest experiment:** Measure the early exit's accuracy drop against its latency saving on a fixed decision set; it survives only if the drop is under one point (Thor GPU). **Machine:** Thor GPU.

#### B14 — Hysteresis barrier: split confidence bounds plus a temporal-momentum window so confidence chatter cannot toggle discrete state

- **The seed:** Hysteresis barrier: split confidence bounds plus a temporal-momentum window so confidence chatter cannot toggle discrete state, landing in core/hysteresis.
- **Source:** `sources-liquid2.md:1520`.
- **What is wrong as written:** The 0.92/0.78 bounds and the 120ms window are asserted with no measurement.
- **The kernel worth keeping:** Already built: core/hysteresis (the gate). Measured. Keep as the reference implementation for every other gating claim in this bank.
- **Status:** already built. `core/hysteresis` (built and measured); the boundary itself is a PTX kernel in `sources-liquid2.md:1520`

#### B15 — Brier-score calibration tracking: measure whether the small model's confidence is honest, retune when it drifts

- **The seed:** Brier-score calibration tracking: measure whether the small model's confidence is honest, retune when it drifts, landing in decision models.
- **Source:** `sources-liquid2.md:1584`.
- **What is wrong as written:** The 0.18/0.08 drift thresholds are invented, and the chat never says what is retuned when the score drifts.
- **The kernel worth keeping:** Calibration drift as a monitored quantity with a retune trigger. This is the measurement that B14's thresholds need and do not have.
- **Status:** new.
- **Smallest experiment:** Recompute confidence for every decision cell directly from the probability vector the endpoint already returns, under all three definitions (top probability, normalised margin, entropy-normalised score), and publish ECE, Brier and the escalation rate at a threshold sweep. Kill: if no definition separates correct from incorrect at any threshold, the confidence carries no signal in any form and the router must use model disagreement or the bandit's estimate instead (numpy-only on exported vectors). **Machine:** numpy-only.

#### B16 — Generative rehearsal: mix new failure samples with a fixed baseline set so updates do not cause forgetting

- **The seed:** Generative rehearsal: mix new failure samples with a fixed baseline set so updates do not cause forgetting, landing in night / decision models.
- **Source:** `sources-liquid1.md:882`.
- **What is wrong as written:** A tri-chamber mix buffer is specified; the claim that it prevents catastrophic forgetting is asserted.
- **The kernel worth keeping:** Replay buffer for the fast-loop learner. Cheap, standard, and it is the missing half of the night: we audit but do not retain.
- **Status:** new.
- **Smallest experiment:** Run the nightly update with and without the rehearsal buffer over a week of logs; it survives if the forgetting is measurably smaller (Thor GPU). **Machine:** Thor GPU.

#### B17 — Intent and entity cache keyed by embedding so the small model never re-asks

- **The seed:** Intent and entity cache keyed by embedding so the small model never re-asks, landing in tiles / first mile.
- **Source:** `sources-new1.md:61`.
- **What is wrong as written:** Embedding similarity as the key is fine; the chat's 'never re-asks' is the load-bearing claim and is exactly what pincher-fit.md says the bandit is missing.
- **The kernel worth keeping:** A retrieval front over the tile library. The director's note already proposes this as next step 1; the desk's E1 is the experiment.
- **Status:** new.
- **Smallest experiment:** Replay the tile logs offline with an embedding fast path in front of the bandit; it wins if it covers 30% of contexts at the bandit's reward and p95 under 50 ms (ProArt). **Machine:** ProArt.

#### B18 — Nightly SOP rewrite: an auditor model reviews low-confidence logs and rewrites the small model's prompt and schema

- **The seed:** Nightly SOP rewrite: an auditor model reviews low-confidence logs and rewrites the small model's prompt and schema, landing in night.
- **Source:** `sources-new1.md:178`.
- **What is wrong as written:** The audit JSON, prompt append and schema constraint edit are specified as separate edits with no ordering or conflict rule.
- **The kernel worth keeping:** The night as an auditor. We have the night and the audit; the missing piece is the schema-constraint edit being separate from the prose edit.
- **Status:** new.
- **Smallest experiment:** Have the auditor rewrite one prompt and one schema constraint for a week and count how many of its edits had to be reverted; separately, test the soft-label route, which replaces prompt rewriting with a training signal (cloud plus ProArt). **Machine:** cloud.

#### B19 — Front desk / decision maker / back office: a fast model holds the line, a router decides, a slow model reasons

- **The seed:** Front desk / decision maker / back office: a fast model holds the line, a router decides, a slow model reasons, landing in first mile / tiles.
- **Source:** `sources-new1.md:192`.
- **What is wrong as written:** Roles are named but the routing policy has no thresholds.
- **The kernel worth keeping:** The three-role split with the hysteresis gate as the router. Directly comparable to pincher's three score bands.
- **Status:** new.
- **Smallest experiment:** Measure the three-role split on the first-mile task set: does the router at the decision-maker role beat a flat model at equal accuracy (ProArt). **Machine:** ProArt.

#### B20 — Conversational filler to mask latency: the small model speaks while the big one thinks

- **The seed:** Conversational filler to mask latency: the small model speaks while the big one thinks, landing in first mile.
- **Source:** `sources-new1.md:59`.
- **What is wrong as written:** Behavioural, not mechanical; it does not shorten the wait, it only hides it.
- **The kernel worth keeping:** Filler generation as a latency-hiding device for the first mile. Worth one line of code, worth a measured p95 before anyone believes it.
- **Status:** new.
- **Smallest experiment:** Measure p95 first-mile latency with and without filler; filler only earns its place if it holds the perceived wait below a stated threshold (ProArt). **Machine:** ProArt.

#### B21 — Liquid state-space O(1) memory: a fixed hidden state instead of a growing KV cache

- **The seed:** Liquid state-space O(1) memory: a fixed hidden state instead of a growing KV cache, landing in night / decision models.
- **Source:** `sources-liquid2.md:3`.
- **What is wrong as written:** The chat treats this as the property of Liquid's architecture; it is a property of state-space models generally, and it does not apply to a transformer backbone.
- **The kernel worth keeping:** Fixed-size state for long-running loops. The night is a long-running loop, so this matters even without a state-space model: bound the context instead of growing it.
- **Status:** new.
- **Smallest experiment:** Bound the context the night feeds its decision models and measure whether the long-tail job's quality survives the truncation (Thor GPU). **Machine:** Thor GPU.

#### B22 — Time-invariance: the same model runs at 10Hz or 200Hz by changing a dt parameter, with no reload

- **The seed:** Time-invariance: the same model runs at 10Hz or 200Hz by changing a dt parameter, with no reload, landing in decision models.
- **Source:** `sources-liquid2.md:11`.
- **What is wrong as written:** Only true for models with an explicit dt input; a transformer has no such parameter.
- **The kernel worth keeping:** Variable-rate execution without reload. For us: one resident model, several rates, decided by the scheduler rather than by the model.
- **Status:** new.
- **Smallest experiment:** Run one resident model at two rates and confirm the outputs at the two rates agree to tolerance (Thor GPU). **Machine:** Thor GPU.

#### B23 — Phase-locked resonance between peripheral models sharing a coordinate system

- **The seed:** Phase-locked resonance between peripheral models sharing a coordinate system, landing in tiles / decision models.
- **Source:** `sources-liquid2.md:390`.
- **What is wrong as written:** 'Resonance' is metaphor; the coupling equation is given but the training is not, so the coupling term is hand-set.
- **The kernel worth keeping:** A shared 64-byte state delta between co-operating models. The delta is the mechanism; the resonance is the story.
- **Status:** new.
- **Smallest experiment:** Have two models exchange a 64-byte delta and measure whether the receiving model's next output changes as intended (Thor GPU). **Machine:** Thor GPU.

#### B24 — Distillation to a smaller branch of the same backbone, with per-modality heads

- **The seed:** Distillation to a smaller branch of the same backbone, with per-modality heads, landing in decision models.
- **Source:** `sources-new1.md:6`.
- **What is wrong as written:** LFM3's six models branch from one base; the chat reads that as distillation, but shared pre-training is not distillation.
- **The kernel worth keeping:** One backbone, several heads. For us: one model that both chooses tiles and critiques them.
- **Status:** new.
- **Smallest experiment:** Train one backbone with two heads, one to choose a tile and one to judge it, and compare against two separate models at equal total parameters (Thor GPU). **Machine:** Thor GPU.

#### B25 — Omni single-backbone transduction: audio, vision and text through one 2B backbone, no ASR-to-LLM-to-TTS chain

- **The seed:** Omni single-backbone transduction: audio, vision and text through one 2B backbone, no ASR-to-LLM-to-TTS chain, landing in first mile.
- **Source:** `sources-liquid2.md:89`.
- **What is wrong as written:** The cited '50ms TTFT, 87x realtime' is a Liquid marketing figure from their own benchmark.
- **The kernel worth keeping:** One model for the whole voice loop. The first mile currently has three stages; this is the claim that they can be one. Worth measuring on the ProArt.
- **Status:** new.
- **Smallest experiment:** Replace the first-mile's separate ASR, language and speech stages with one LFM3-class model and measure p95 latency and the accuracy change (ProArt). **Machine:** ProArt.

#### B26 — Cross-modal latent fusion as a quality check: score a generated asset against the same state vector that perceived it

- **The seed:** Cross-modal latent fusion as a quality check: score a generated asset against the same state vector that perceived it, landing in critic / first mile.
- **Source:** `sources-liquid2.md:196`.
- **What is wrong as written:** The 'score primitive, 4ms' is invented.
- **The kernel worth keeping:** Score against the state that produced the thing. We have the vocabulary canon and the critic; this is the join between them.
- **Status:** new.
- **Smallest experiment:** Score generated tiles against the state vector that produced them and measure whether the score separates good from bad tiles (Thor GPU). **Machine:** Thor GPU.

#### B27 — Latent-space physics injection: bake gravity and tension into the state-space weights so assets are born stable

- **The seed:** Latent-space physics injection: bake gravity and tension into the state-space weights so assets are born stable, landing in Thor world engine.
- **Source:** `sources-liquid2.md:196`.
- **What is wrong as written:** No training procedure at all; 'born stable' is a metaphor for a constraint that would have to be enforced.
- **The kernel worth keeping:** Constraint at generation time rather than repair after. The wiki says our mesh repair is the expensive part; this attacks it upstream.
- **Status:** new.
- **Smallest experiment:** Baking gravity and tension into weights needs a training procedure that does not exist. The testable version is a constraint solver instead: place 100 axis-aligned boxes without overlap and record the violations (Thor GPU). **Machine:** Thor GPU.

#### B28 — Two-call action policy: the decision model picks the skill, C++ executes the trajectory

- **The seed:** Two-call action policy: the decision model picks the skill, C++ executes the trajectory, landing in tiles / motion.
- **Source:** `sources-liquid1.md:274`.
- **What is wrong as written:** The 10Hz JSON geometry and the MuJoCo reference are not our stack.
- **The kernel worth keeping:** Two-call split for motion: a model chooses, deterministic code executes. This is our motion-as-virtual-robotics shape already, and it is right.
- **Status:** already built. our motion-as-virtual-robotics split; `docs/lab/IDEAS.md` Part A

#### B29 — Direct RAM/engine ingestion: skip vision entirely, feed structured game state

- **The seed:** Direct RAM/engine ingestion: skip vision entirely, feed structured game state, landing in first mile.
- **Source:** `sources-liquid1.md:281`.
- **What is wrong as written:** The Doom reference is not our product.
- **The kernel worth keeping:** Structured state instead of pixels, where we can get it. The night already has structured state; the first mile does not.
- **Status:** new.
- **Smallest experiment:** Feed structured state instead of pixels into the first-mile model on the voice task set and measure the accuracy and latency difference (ProArt). **Machine:** ProArt.


### C. Shifting the processing burden (`sources-fromgoogle4.md`)

#### C1 — Hardware vector-mesh pipeline: thousands of agents inject lines and votes with atomics, no database queries

- **The seed:** Hardware vector-mesh pipeline: thousands of agents inject lines and votes with atomics, no database queries, landing in Thor world engine.
- **Source:** `sources-fromgoogle4.md:366`.
- **What is wrong as written:** An application design (a wireframe city) mistaken for a hardware mechanism. The atomics are real; the 100,000-agent claim has no measurement.
- **The kernel worth keeping:** Atomic accumulation in a shared buffer instead of a database round trip. The mechanism is ours already: the stage cache and the recipe ledger are append-only, not queried.
- **Status:** already being tested. the append-only stage cache and recipe ledger

#### C2 — Zero-allocation execution: once initialised, the loop runs entirely in pre-allocated arrays

- **The seed:** Zero-allocation execution: once initialised, the loop runs entirely in pre-allocated arrays, landing in Thor world engine.
- **Source:** `sources-fromgoogle4.md:367`.
- **What is wrong as written:** 'Entirely within registers' is wrong: pre-allocated device memory is not registers.
- **The kernel worth keeping:** Pre-allocate and never allocate in the loop. This is a real constraint for the night: allocation in the hot path is what makes a batch stall.
- **Status:** already being tested.

#### C3 — Unified interface layer: the CPU reads the exact pointer the GPU is writing

- **The seed:** Unified interface layer: the CPU reads the exact pointer the GPU is writing, landing in core/engine.
- **Source:** `sources-fromgoogle4.md:368`.
- **What is wrong as written:** Coherent UVM is real on Thor; the claim that the CPU can read at any point without a fence is the part that needs care.
- **The kernel worth keeping:** One allocation, read by both sides. We have this finding already: zero-copy is a design constraint, not an optimisation (IDEAS.md rule 2).
- **Status:** already built. `core/engine`; `docs/lab/IDEAS.md` rule 2 (zero-copy is a design constraint)

#### C4 — GPUDirect RDMA / GDS: network and disk land straight in GPU memory without touching the CPU

- **The seed:** GPUDirect RDMA / GDS: network and disk land straight in GPU memory without touching the CPU, landing in Thor world engine.
- **Source:** `sources-fromgoogle4.md:575`.
- **What is wrong as written:** Thor has no 100 GbE cage on this devkit (killed by fact), so the RDMA half is unavailable; GDS over NVMe may still be.
- **The kernel worth keeping:** GDS for the night's texture and mesh IO. The RDMA half dies with the network claim.
- **Status:** new.
- **Smallest experiment:** Measure whether GPUDirect Storage for the night's texture and mesh IO beats the current path; the RDMA half is unavailable because there is no 100 GbE cage on this devkit (Thor GPU). **Machine:** Thor GPU.

#### C5 — Warp-level agent coordination: threads in a warp pass data with shfl instead of shared memory

- **The seed:** Warp-level agent coordination: threads in a warp pass data with shfl instead of shared memory, landing in tiles.
- **Source:** `sources-fromgoogle4.md:581`.
- **What is wrong as written:** Real CUDA, but 'the same warp' is an implementation constraint the chat never respects at the algorithm level.
- **The kernel worth keeping:** In-warp reduction for per-tile scoring. Cheap, and it pairs with the C12 seed.
- **Status:** new.
- **Smallest experiment:** Move a per-tile scoring step into a warp reduction and compare against the shared-memory version at the same occupancy (Thor GPU). **Machine:** Thor GPU.

#### C6 — Atomic collisions as structural locks: two agents writing the same coordinate use atomicAdd and atomicOr

- **The seed:** Atomic collisions as structural locks: two agents writing the same coordinate use atomicAdd and atomicOr, landing in tiles / core/tiles.
- **Source:** `sources-fromgoogle4.md:582`.
- **What is wrong as written:** Atomicity prevents torn writes; it does not prevent two agents from making different, individually valid, conflicting edits.
- **The kernel worth keeping:** Atomic claim-and-apply for the tile ledger. Our vocabulary door already refuses invalid tiles; this is the finer-grained version.
- **Status:** new.
- **Smallest experiment:** Let two workers claim the same tile slot and confirm the atomic claim produces one winner and one clean rejection (Thor GPU). **Machine:** Thor GPU.

#### C7 — Ring-buffer arena for the event stream: the pointer advances instead of deleting

- **The seed:** Ring-buffer arena for the event stream: the pointer advances instead of deleting, landing in core/events.
- **Source:** `sources-fromgoogle4.md:595`.
- **What is wrong as written:** Correct for a fixed-size stream; it assumes the consumer never needs a gap.
- **The kernel worth keeping:** Bounded event log with a sliding window. The night wants a bounded log anyway.
- **Status:** new.
- **Smallest experiment:** Replace the event log's growth with a sliding ring and measure the memory ceiling over a night (Thor GPU). **Machine:** Thor GPU.

#### C8 — Dense bit-field packing of agent state into 16-byte registers

- **The seed:** Dense bit-field packing of agent state into 16-byte registers, landing in core/events.
- **Source:** `sources-fromgoogle4.md:655`.
- **What is wrong as written:** The exact bit allocation (10/10/10/2, then 8/8/8/8) is invented; at 20 SMs the register file cannot hold 100,000 of them.
- **The kernel worth keeping:** Fixed-width record layout. Worth having as a schema: a fixed-width state record is what makes a ring buffer and an SSE delta cheap.
- **Status:** new.
- **Smallest experiment:** Fix the state record's width and measure the event log's bytes per record against the current variable-length encoding (Thor GPU). **Machine:** Thor GPU.

#### C10 — Tensor-core slice as an on-chip encoder compressing the sim loop into a latent vector for the cloud

- **The seed:** Tensor-core slice as an on-chip encoder compressing the sim loop into a latent vector for the cloud, landing in night.
- **Source:** `sources-fromgoogle4.md:636`.
- **What is wrong as written:** Dedicated-slice encoding implies a hardware encoder; on Thor the tensor cores are shared and this competes with the render.
- **The kernel worth keeping:** Compress the night's telemetry to a small latent before it goes up. Cheap to measure on the bandwidth we actually have.
- **Status:** new.
- **Smallest experiment:** Compress a night of telemetry to a small latent and measure the bandwidth against the 9.3 MB/s link budget the idea5 chat cites for our cluster; it survives if the upload fits the window (Thor GPU). **Machine:** Thor GPU.

#### C12 — Brier-gated agent mutation loop: the agent retunes when calibration drifts, verified in a MIG sandbox

- **The seed:** Brier-gated agent mutation loop: the agent retunes when calibration drifts, verified in a MIG sandbox, landing in night.
- **Source:** `sources-liquid2.md:783`.
- **What is wrong as written:** The sandbox premise assumes a MIG partition that is still a preview and whose profiles are not what the docs say (verified: only 2g.0gb+gfx + 1g.0gb+me work).
- **The kernel worth keeping:** A closed loop where the agent proposes a parameter change, a sandbox validates it, and calibration drift is the trigger. The loop is the seed; the MIG sandbox is a detail that has to be rebuilt on the one working profile pair.
- **Status:** new.
- **Smallest experiment:** Run the mutation loop for one night with a sandboxed candidate and a verified install, and count how many candidates the sandbox rejected before one passed (Thor GPU). **Machine:** Thor GPU.

#### C13 — Markdown manifests as the agent-facing surface: WHY.md and ECOLOGY.md compiled to 64-bit masks

- **The seed:** Markdown manifests as the agent-facing surface: WHY.md and ECOLOGY.md compiled to 64-bit masks, landing in core/why.
- **Source:** `sources-liquid2.md:551`.
- **What is wrong as written:** Text IDs compiled to masks: the compiler is specified but the mask semantics and the conflict rule are not.
- **The kernel worth keeping:** Human-readable source of truth compiled to a bitmask the runtime loads. This is close to our vocabulary canon, and the compile step is the missing piece.
- **Status:** new.
- **Smallest experiment:** Compile WHY.md into a mask and measure whether the runtime can load and check it in under a millisecond (Thor GPU). **Machine:** Thor GPU.

#### C14 — Vibe-coding parameter injection: the cloud LLM compiles natural language to a JSON float payload written into UMA

- **The seed:** Vibe-coding parameter injection: the cloud LLM compiles natural language to a JSON float payload written into UMA, landing in first mile / cloud.
- **Source:** `sources-fromgoogle4.md:505`.
- **What is wrong as written:** 'Vibe coding' as a control path is the opposite of our closed vocabulary; the JSON schema is the only safe part.
- **The kernel worth keeping:** Cloud-to-Thor parameter plane with a schema and a bounds check. The schema is the mechanism; the natural-language part is the risk.
- **Status:** new.
- **Smallest experiment:** Take a fixed set of parameter edits, route them through the JSON schema and bounds check, and confirm that every rejected edit was one a human would have rejected (cloud). **Machine:** cloud.

#### C19 — Trace-guided self-optimisation: feed execution traces back to the compiler for dead-code elimination

- **The seed:** Trace-guided self-optimisation: feed execution traces back to the compiler for dead-code elimination, landing in night.
- **Source:** `sources-new1.md:1406`.
- **What is wrong as written:** The attribution is to the wrong file (it is in liquid2/new1/new2), and the Cranelift pass is not specified.
- **The kernel worth keeping:** Trace feedback into a compiler pass. Real but far from our stack; a seed for much later.
- **Status:** new.
- **Smallest experiment:** Feed a recorded execution trace into a compiler pass and measure whether dead code is actually removed and the result still passes its test (ProArt). **Machine:** Thor GPU.

#### C20 — Multiverse timeline simulation: fork state, test thousands of futures, collapse the winner

- **The seed:** Multiverse timeline simulation: fork state, test thousands of futures, collapse the winner, landing in night.
- **Source:** `sources-new1.md:1044`.
- **What is wrong as written:** 'Test thousands' is unbounded; no pruning or budget is given.
- **The kernel worth keeping:** Fork-and-collapse as a search over candidate worlds. The night already forks; the seed is scoring the forks, not making them.
- **Status:** new.
- **Smallest experiment:** Fork the night's state into a small number of candidates and measure whether the collapsed winner beats the single run (Thor GPU). **Machine:** Thor GPU.

#### C21 — Permission tokens: if the big model is slow the small loop halts safely rather than waiting

- **The seed:** Permission tokens: if the big model is slow the small loop halts safely rather than waiting, landing in core/tiles.
- **Source:** `sources-liquid2.md:1772`.
- **What is wrong as written:** The token values are invented; a stale permission token is a liveness bug unless expiry is enforced.
- **The kernel worth keeping:** Deadline-carrying permission tokens: the never-wait policy as an explicit artefact. We have the policy; the token is the enforcement.
- **Status:** new.
- **Smallest experiment:** Write a permission token with an expiry, let the producer stall past it, and confirm the consumer halts rather than waits (ProArt). **Machine:** Thor GPU.

#### C22 — Golden immutable core plus a dynamic liquid layer, with a one-cycle revert

- **The seed:** Golden immutable core plus a dynamic liquid layer, with a one-cycle revert, landing in core/tiles.
- **Source:** `sources-liquid1.md:1068`.
- **What is wrong as written:** 'ASIL-D flash vs Context Beta' are DriveOS terms that do not exist on Jetson; the real split is the ASIL-D lane vs the mutable lane.
- **The kernel worth keeping:** A frozen, validated core with a mutable layer beside it, and a single-cycle revert. The discipline is right; the safety vocabulary is wrong.
- **Status:** new.
- **Smallest experiment:** Split the tile vocabulary into a frozen validated core and a mutable layer, and confirm the revert is one cycle (ProArt). **Machine:** Thor GPU.

#### C23 — Offline telemetry batching: accumulate failures offline, upload in one batch, return one verified delta

- **The seed:** Offline telemetry batching: accumulate failures offline, upload in one batch, return one verified delta, landing in night.
- **Source:** `sources-liquid1.md:1072`.
- **What is wrong as written:** 'One verified delta' hides the whole verification problem.
- **The kernel worth keeping:** Batch the night's telemetry upload. The 9.3 MB/s link budget the idea5 chat cites for our cluster makes batching a real constraint, not a nicety.
- **Status:** new.
- **Smallest experiment:** Batch a week of telemetry into one upload and measure the wall time against the same data sent unbatched (Thor GPU). **Machine:** Thor GPU.

#### C24 — Cache hint operators (.lu) to control L2 residency explicitly

- **The seed:** Cache hint operators (.lu) to control L2 residency explicitly, landing in Thor world engine.
- **Source:** `sources-fromgoogle4.md:759`.
- **What is wrong as written:** The PTX cache-hint operators are real; the claimed benefit is asserted with no measurement.
- **The kernel worth keeping:** Explicit cache-residency hints for the night's hot buffers. Cheap to try, easy to measure on a bandwidth-limited box.
- **Status:** new.
- **Smallest experiment:** Add cache-residency hints to the night's hot buffers and measure the bandwidth effect on the same workload (Thor GPU). **Machine:** Thor GPU.


### D. The quilt-pincher reflex engine (`sources-new1.md`, `sources-new2.md`)

#### D1 — Embedding match with score bands: embed the trigger, take the top K, act by band

- **The seed:** Embedding match with score bands: embed the trigger, take the top K, act by band, landing in tiles / first mile.
- **Source:** `sources-new1.md:211`.
- **What is wrong as written:** The bands (0.80 / 0.55) are pincher's defaults, not ours.
- **The kernel worth keeping:** Retrieval front over the tile library, with the hysteresis gate holding the bands. The director's note proposes it as next step 1 and the desk gives the experiment.
- **Status:** new.
- **Smallest experiment:** Replay the tile logs with pincher-style similarity only, the bandit only, and retrieval-then-bandit; measure win rate, p95 and how fast each improves with use (ProArt). **Machine:** ProArt.

#### D2 — Signed portable .nail bundles: each reflex publishes script, embedding, capability manifest and signature

- **The seed:** Signed portable .nail bundles: each reflex publishes script, embedding, capability manifest and signature, landing in core/tiles.
- **Source:** `sources-new1.md:269`.
- **What is wrong as written:** A signing scheme needs a key story that the chat does not give.
- **The kernel worth keeping:** A signed, portable tile bundle that runs on the ProArt, the Thor and in a Worker. The portability is the point.
- **Status:** new.
- **Smallest experiment:** Sign a tile bundle, load it on the ProArt and on the Thor, and confirm both refuse a bundle whose signature does not match (ProArt and Thor GPU). **Machine:** ProArt.

#### D3 — Veto with a capability manifest and a WASM/Landlock sandbox before anything touches the world or the host

- **The seed:** Veto with a capability manifest and a WASM/Landlock sandbox before anything touches the world or the host, landing in core/tiles.
- **Source:** `sources-new1.md:310`.
- **What is wrong as written:** Landlock is a Linux LSM; the chat does not say which side runs it or what it covers.
- **The kernel worth keeping:** A capability check before a tile touches the host. We have the vocabulary door for the world; this is the host-side equivalent.
- **Status:** new.
- **Smallest experiment:** Run a tile that tries to touch the filesystem inside a sandbox and confirm the capability manifest blocks it before any side effect (ProArt). **Machine:** ProArt.

#### D4 — Modular traits so each tier swaps its embedder, guard and runner

- **The seed:** Modular traits so each tier swaps its embedder, guard and runner, landing in core/tiles.
- **Source:** `sources-new1.md:441`.
- **What is wrong as written:** A design pattern, no defect.
- **The kernel worth keeping:** Trait-based ports for the tile runtime. Cheap and it makes the ProArt/Thor/cloud split testable.
- **Status:** new.
- **Smallest experiment:** Split the tile runtime behind the embedder, guard and runner traits and confirm each can be swapped without touching the caller (ProArt). **Machine:** ProArt.

#### D6 — User-scoped vs global caches with a promotion rule

- **The seed:** User-scoped vs global caches with a promotion rule, landing in core/tiles.
- **Source:** `sources-new1.md:186`.
- **What is wrong as written:** The promotion rule is named but not specified.
- **The kernel worth keeping:** Personal tiles stay personal until validated. Our authorship model (A1/A5) is exactly this.
- **Status:** new.
- **Smallest experiment:** Promote a personal tile to global and measure how often it is later retired; if the promotion rate is much worse than the personal rate, the rule needs a tighter gate (ProArt). **Machine:** ProArt.

#### D7 — Interruption token: barge-in or a world change cancels the in-flight cloud compile and rolls back the fork

- **The seed:** Interruption token: barge-in or a world change cancels the in-flight cloud compile and rolls back the fork, landing in core/night.
- **Source:** `sources-new1.md:65`.
- **What is wrong as written:** 'Rolls back the fork' implies a transactional store we do not have.
- **The kernel worth keeping:** Cancellation as a first-class path in the night. A cancelled night job must leave no partial artifact; that is a real requirement today.
- **Status:** new.
- **Smallest experiment:** Cancel an in-flight night job from a world change and verify that no partial artifact survives in the stage cache (Thor GPU). **Machine:** Thor GPU.

#### D8 — Fork, prune, commit: run a candidate in a structurally shared fork with fuel metering, commit only the winner

- **The seed:** Fork, prune, commit: run a candidate in a structurally shared fork with fuel metering, commit only the winner, landing in core/night.
- **Source:** `sources-new1.md:260`.
- **What is wrong as written:** Structurally shared fork plus fuel metering in one sentence, with no mechanism.
- **The kernel worth keeping:** Fork-and-keep as the night loop, with an explicit budget. We have predict/render/keep-or-undo; the fuel budget is the addition.
- **Status:** new.
- **Smallest experiment:** Run a candidate tile in a fork with a fuel budget and confirm the budget stops a runaway and that only the safe winner is committed (Thor GPU). **Machine:** Thor GPU.

#### D9 — Program synthesis with gas metering and hot swap for frequently used tiles

- **The seed:** Program synthesis with gas metering and hot swap for frequently used tiles, landing in core/tiles.
- **Source:** `sources-new1.md:1409`.
- **What is wrong as written:** Synthesis from a fault log at runtime is a big claim with no training data story.
- **The kernel worth keeping:** Synthesis of a hot tile when a fault repeats. Worth one experiment: does a synthesized tile beat a hand-written one on the same fault class?
- **Status:** new.
- **Smallest experiment:** On one fault class, compare a synthesized tile against a hand-written one on the same logs; the synthesis wins if it fixes the fault and passes the veto (ProArt). **Machine:** Thor GPU.

#### D10 — Telemetry ingestion from /proc: loadavg, meminfo and fd count into a typed SystemState

- **The seed:** Telemetry ingestion from /proc: loadavg, meminfo and fd count into a typed SystemState, landing in Thor world engine.
- **Source:** `sources-new2.md:26`.
- **What is wrong as written:** Correct and unglamorous.
- **The kernel worth keeping:** Host telemetry as a typed record the scheduler reads. thor-admit already reads MemAvailable and the load; this is the generalisation.
- **Status:** already being tested. thor-admit, the Rust admission daemon

#### D11 — Virtualised host primitives: guest WASM calls get_cpu_load or trigger_state_reset against a fake state

- **The seed:** Virtualised host primitives: guest WASM calls get_cpu_load or trigger_state_reset against a fake state, landing in core/tiles.
- **Source:** `sources-new2.md:86`.
- **What is wrong as written:** WASM guests calling a host API is a normal ABI; the 'fake state' is the interesting half.
- **The kernel worth keeping:** A tile that touches the host runs first against a simulated host. This is the dry-run the night wants.
- **Status:** new.
- **Smallest experiment:** Run a tile that reads host load against a fake host state and confirm the tile cannot see the real one (ProArt). **Machine:** ProArt.

#### D12 — Cranelift JIT of a validated trace, hot-swapped via memfd_create and mmap

- **The seed:** Cranelift JIT of a validated trace, hot-swapped via memfd_create and mmap, landing in core/tiles.
- **Source:** `sources-new1.md:1357`.
- **What is wrong as written:** Premature: our tiles are vocabulary scripts, not native code. The director's note says so.
- **The kernel worth keeping:** A seed for much later, not now. The mechanism (compile, map, flip) is sound; the workload is wrong.
- **Status:** new.
- **Smallest experiment:** Deferred. Compile a trace with Cranelift, map it, and measure the flip; it is worth a day only after tiles can carry native code at all (ProArt). **Machine:** ProArt.

#### D13 — A reactive cell DAG with StableGraph, link_dependency and a BFS cascade

- **The seed:** A reactive cell DAG with StableGraph, link_dependency and a BFS cascade, landing in core/engine.
- **Source:** `sources-new2.md:553`.
- **What is wrong as written:** The chat's own link_dependency has no cycle check, though its comment says one must happen there; a 1->2->1 edge would deadlock or double-fire.
- **The kernel worth keeping:** A dependency DAG for tiles. The director's note: the same shape as our stage cache's dirty set. The cycle check is the thing to specify.
- **Status:** already being tested. the stage cache's dirty set, `core/engine/DIRTY.md`

#### D14 — Double-buffered atomic mailbox: write the inactive slot, sfence, release store

- **The seed:** Double-buffered atomic mailbox: write the inactive slot, sfence, release store, landing in core/tiles.
- **Source:** `sources-new2.md:1775`.
- **What is wrong as written:** Correct inside one machine's shared memory; false across ProArt to Thor, which share no memory (they are on Wi-Fi).
- **The kernel worth keeping:** The mailbox inside the Thor, from render buffer to critic. Sound, and it matches our zero-copy finding.
- **Status:** already being tested. the render-buffer to critic handoff; `docs/lab/exp-unified-memory.md`

#### D15 — A lock-free ring event loop with a 1024-slot mpsc queue and a task per event

- **The seed:** A lock-free ring event loop with a 1024-slot mpsc queue and a task per event, landing in core/events.
- **Source:** `sources-new2.md:292`.
- **What is wrong as written:** Standard; the claim of a 1024 slot is a default, not a result.
- **The kernel worth keeping:** Lock-free intake for the first mile's events. Boring and worth it.
- **Status:** new.
- **Smallest experiment:** Replace the blocking intake with a lock-free ring and measure the intake latency under burst (ProArt). **Machine:** ProArt.

#### D16 — A per-cell logic slot with a static, WASM or JIT strategy per cell

- **The seed:** A per-cell logic slot with a static, WASM or JIT strategy per cell, landing in core/tiles.
- **Source:** `sources-new2.md:3`.
- **What is wrong as written:** A strategy table; the cost model that chooses between the three is missing.
- **The kernel worth keeping:** Per-tile execution strategy: interpreted, sandboxed, or compiled. The chooser already picks tiles; this picks how to run them.
- **Status:** new.
- **Smallest experiment:** Let the chooser pick among static, sandboxed and compiled execution for the same tile and measure the crossover (ProArt). **Machine:** ProArt.

#### D17 — JIT jump trampoline compiling a direct call target

- **The seed:** JIT jump trampoline compiling a direct call target, landing in core/tiles.
- **Source:** `sources-new2.md:698`.
- **What is wrong as written:** The trampoline calls call_indirect with a no-argument, no-return signature, so the calling convention is undefined for any target with arguments.
- **The kernel worth keeping:** Merge with D12. The calling-convention gap is the concrete defect to write down.
- **Status:** new.
- **Smallest experiment:** Give the trampoline a target with arguments and confirm the calling convention is defined and works (ProArt). **Machine:** ProArt.

#### D18 — PID attenuation of the reality/dream blend to damp feedback blowup

- **The seed:** PID attenuation of the reality/dream blend to damp feedback blowup, landing in night.
- **Source:** `sources-new2.md:1945`.
- **What is wrong as written:** A named PID with no gains; without gains it is not a controller.
- **The kernel worth keeping:** A real controller on the night's render-versus-reality blend. We blend; the question is whether the blend oscillates.
- **Status:** new.
- **Smallest experiment:** Give the reality/dream blend a real controller: log the blend coefficient and the output for a night, and check whether it oscillates; the sources' named failure modes are resonant catastrophe and over-steering (Thor GPU). **Machine:** Thor GPU.

#### D19 — State-vector version stamping: reject a cloud delta computed against a stale world snapshot

- **The seed:** State-vector version stamping: reject a cloud delta computed against a stale world snapshot, landing in night.
- **Source:** `sources-new2.md:1956`.
- **What is wrong as written:** 'Geometric distance threshold' as a staleness test is a proxy; the exact test is a version counter.
- **The kernel worth keeping:** Version-stamp every cloud-returned delta against the canon. Cheap, and it prevents the worst failure mode of a cloud patch.
- **Status:** new.
- **Smallest experiment:** Version-stamp a cloud delta against the canon and confirm a delta computed against a stale snapshot is rejected (Thor GPU). **Machine:** Thor GPU.

#### D20 — A phylogenetic registry: nightly .nail patches to a central sieve, one unified bundle back to the fleet

- **The seed:** A phylogenetic registry: nightly .nail patches to a central sieve, one unified bundle back to the fleet, landing in core/tiles.
- **Source:** `sources-new2.md:1988`.
- **What is wrong as written:** The 24h cycle and the sieve are asserted; 'unified bundle' has no conflict rule.
- **The kernel worth keeping:** A fleet-wide promotion of verified tiles with a single bundle. The registry needs a merge rule for two valid but conflicting tiles.
- **Status:** new.
- **Smallest experiment:** Merge two nightly bundles that each changed the same tile, and define the conflict rule that resolves them (cloud). **Machine:** cloud.

#### D22 — Skeletal remodelling: the cloud dissolves obsolete safety invariants and calcifies new ones

- **The seed:** Skeletal remodelling: the cloud dissolves obsolete safety invariants and calcifies new ones, landing in core/tiles.
- **Source:** `sources-new1.md:762`.
- **What is wrong as written:** Metaphor over an actual edit to an HSM table; the edit protocol is not given.
- **The kernel worth keeping:** Editing a validated invariant under version control with a revalidation step. The interesting version is the audit trail, not the bone metaphor.
- **Status:** new.
- **Smallest experiment:** Edit a validated invariant under version control and measure the revalidation cost (cloud). **Machine:** cloud.

#### D23 — Gas-metered sandbox: fuel consumption is the fitness signal for synthesized code

- **The seed:** Gas-metered sandbox: fuel consumption is the fitness signal for synthesized code, landing in core/tiles.
- **Source:** `sources-new1.md:1409`.
- **What is wrong as written:** Fuel is a cost bound, not a fitness function; the two are conflated.
- **The kernel worth keeping:** A budget for a synthesized or candidate tile, used to bound a search rather than to score it.
- **Status:** new.
- **Smallest experiment:** Give a candidate tile a fuel budget and confirm the budget halts a runaway before it takes the box down; fuel is a bound, not a fitness function (ProArt). **Machine:** ProArt.

#### D24 — Hot-swap via memfd_create and mmap into a running process

- **The seed:** Hot-swap via memfd_create and mmap into a running process, landing in core/tiles.
- **Source:** `sources-new1.md:1419`.
- **What is wrong as written:** A full mapping is given; the pointer flip and the instruction-cache invalidation are not.
- **The kernel worth keeping:** Code hot-swap without a restart. Same shape as the tile pointer swap, and the same missing step: the flip.
- **Status:** new.
- **Smallest experiment:** Hot-swap a tile's code into a running process with memfd_create and mmap and measure the swap cost against a restart (Thor GPU). **Machine:** ProArt.

#### D25 — Barrier-mapped mailbox with a 64-byte header and an atomic toggle

- **The seed:** Barrier-mapped mailbox with a 64-byte header and an atomic toggle, landing in core/tiles.
- **Source:** `sources-new2.md:1834`.
- **What is wrong as written:** The writer ends with a Release store, but the CUDA reader dereferences the flag as a plain `const unsigned int*` — not volatile, not an acquire load, and with no threadfence between the flag read and the data read. The GPU has no ordering guarantee between the flag and the payload it points at.
- **The kernel worth keeping:** The double-buffer handoff itself: one writer, one reader, one atomic flag, and a fence on each side. The CPU side has the Release; the GPU side is missing its acquire. This is a testable defect in a mechanism we want.
- **Status:** new.
- **Smallest experiment:** Add an acquire (volatile plus a threadfence, or ld.acquire) on the GPU side of the flag read and check whether the payload read that follows is now ordered against it; without it the GPU can read the flag and the payload independently (Thor GPU). **Machine:** Thor GPU.

#### D30 — An ageing scalar per reflex: execution density mapped against age, used to demote cold reflexes

- **The seed:** An ageing scalar per reflex: execution density mapped against age, used to demote cold reflexes, landing in core/tiles.
- **Source:** `sources-new2.md:1982`.
- **What is wrong as written:** The scalar is defined (execution density against age) but the promotion threshold is not, and the two are conflated: age is not importance.
- **The kernel worth keeping:** A scalar per reflex that decides whether it stays hot. We have tile scores and retirement; the seed is that a reflex is aged by use, and one scalar is simpler than both.
- **Status:** new.
- **Smallest experiment:** Give each tile a single ageing scalar, promote and demote on it, and measure whether the hot set predicts the tiles that actually get used (ProArt). **Machine:** ProArt.

#### D31 — Multi-version timeline with rkyv diffs and a simulation engine (nexosim, dtasm)

- **The seed:** Multi-version timeline with rkyv diffs and a simulation engine (nexosim, dtasm), landing in night.
- **Source:** `sources-new1.md:1109`.
- **What is wrong as written:** Both referenced repos exist (verified) but the chat uses them as names, not as a design.
- **The kernel worth keeping:** Fork-and-collapse over world versions, with rkyv diffs as the storage. The repos are real; the integration is unspecified.
- **Status:** new.
- **Smallest experiment:** Store world versions as rkyv diffs and measure the size of a diff against a full snapshot for a one-room change (Thor GPU). **Machine:** Thor GPU.

#### D34 — Retrograde signalling: real hardware metrics fed backward to retune simulator thresholds

- **The seed:** Retrograde signalling: real hardware metrics fed backward to retune simulator thresholds, landing in night.
- **Source:** `sources-new1.md:1359`.
- **What is wrong as written:** Concrete-ish: the direction is right, the thresholds are not given.
- **The kernel worth keeping:** Close the loop from measured night outcomes back into the thresholds that produced them. This is the closest thing in the corpus to what the night already does, one level up.
- **Status:** new.
- **Smallest experiment:** Feed the night's measured outcomes back into the thresholds that produced them and measure whether the next night needs fewer corrections (Thor GPU). **Machine:** Thor GPU.

#### D40 — Myelination and JIT hardening: frequently used paths compiled to native code after an execution-count threshold

- **The seed:** Myelination and JIT hardening: frequently used paths compiled to native code after an execution-count threshold, landing in core/tiles.
- **Source:** `sources-new1.md:1352`.
- **What is wrong as written:** The attribution in the library head start is wrong (it is in new1/new2, not fromgoogle4).
- **The kernel worth keeping:** Promote a hot path to a faster implementation after N calls. This is exactly D12 with a trigger attached, and it is the honest version of it.
- **Status:** new.
- **Smallest experiment:** After a tile passes its execution-count threshold, compile its hot path and measure the speed-up; the trigger is the interesting part (ProArt). **Machine:** ProArt.


### E. Enhancement and optimisation (`sources-idea2.md`, `sources-idea3.md`, `sources-idea4.md`)

#### E1 — DLSS-5 weight extraction and a WGSL reimplementation, running cooperative matrices in the browser

- **The seed:** DLSS-5 weight extraction and a WGSL reimplementation, running cooperative matrices in the browser, landing in viewer / first mile.
- **Source:** `sources-idea2.md:32`.
- **What is wrong as written:** 1 to 2 seconds per frame in the browser via WebGPU, against under 2 ms on native tensor cores (sources-idea2.md:32); and what it is called a 'reimplementation' is a browser-side model download, not a reimplementation.
- **The kernel worth keeping:** Extract a temporal-upscaler and run it where the pixels are. On the ProArt the RTX 4050 is idle during the night; that is where it belongs.
- **Status:** new.
- **Smallest experiment:** Run the extracted temporal upscaler on the ProArt's idle GPU during a night and measure whether the rendered frame time drops (ProArt). **Machine:** ProArt.

#### E2 — Kernel fusion and barrier-free dispatch: fuse 71 blocks and chain them in VRAM

- **The seed:** Kernel fusion and barrier-free dispatch: fuse 71 blocks and chain them in VRAM, landing in core/engine.
- **Source:** `sources-idea2.md:402`.
- **What is wrong as written:** 72ms to 2.7ms is an invented measurement.
- **The kernel worth keeping:** Chain the night's kernels without host round trips. This is the same finding as our CUDA Graph work: a graph is the reproducible way to measure GPU work.
- **Status:** already being tested.

#### E3 — Zero-copy UMA handoff: allocate the frame in the unified pool and bind it directly

- **The seed:** Zero-copy UMA handoff: allocate the frame in the unified pool and bind it directly, landing in core/critic.
- **Source:** `sources-idea2.md:271`.
- **What is wrong as written:** The 'no CPU copy' claim assumes the binding path avoids a driver-side staging copy, which must be measured, not assumed.
- **The kernel worth keeping:** Bind the render buffer and the critic input to the same allocation. We have the zero-copy finding; this is its application to the world engine.
- **Status:** already built. `docs/lab/exp-unified-memory.md`

#### E4 — NVFP4 and FP8 per-layer quantization with a calibration set

- **The seed:** NVFP4 and FP8 per-layer quantization with a calibration set, landing in core/critic.
- **Source:** `sources-idea2.md:227`.
- **What is wrong as written:** FP8 weights-only measured 50-88% slower on TRELLIS.2's samplers and never faster; a diffusion-shaped GEMM chain measured 0.95x, because the chain pays a cast of every activation plus a scale allocation per GEMM. FP8 as a drop-in for the critic cost 15-22% output error. The separate native NVFP4 path through cuBLASLt is much faster and is not what these numbers measure.
- **The kernel worth keeping:** Per-layer precision, shape-gated rather than precision-gated: FP4 for the big-K blocks and the long-K scorers, BF16 for the small ones. The sharp part is the library, not the silicon — TN layout only, K a multiple of 64, M a multiple of 8, scale and packed-code buffers padded to 128-row tiles or the GEMM returns garbage, and CUBLASLT_ORDER_ROW on the FP4 D layout silently returns wrong values.
- **Status:** already being tested. `docs/lab/exp-fp4-path.md` and `docs/lab/exp-fp4-models.md` measured it: NVFP4 through cuBLASLt TN at 371-456 TFLOPS dense for K>=2048, and the model-side finding that QAT is mandatory for FP4 decision and policy models because PTQ flips about 29% of tile choices. FP8 stays dead as a drop-in — 50-88% slower, a diffusion chain at 0.95x, 15-22% output error

#### E5 — Feed a perfect procedural G-buffer: camera matrices, depth and instance IDs so the small net does not guess

- **The seed:** Feed a perfect procedural G-buffer: camera matrices, depth and instance IDs so the small net does not guess, landing in core/critic.
- **Source:** `sources-idea2.md:50`.
- **What is wrong as written:** The chat calls this a 'perfect motion vector' source; optical flow from a rendered G-buffer is exact only for a static scene with a known camera.
- **The kernel worth keeping:** Give the critic the instance IDs and the camera matrices instead of a frame. Instance IDs are exact; motion vectors are a claim about the renderer.
- **Status:** new.
- **Smallest experiment:** Give the critic the renderer's camera matrices, depth and instance IDs instead of a frame, and measure whether the plausibility score becomes stable across frames (Thor GPU). **Machine:** Thor GPU.

#### E6 — Instance-ID temporal consistency: use segmentation IDs as a hard logical rejection to kill ghosting at object boundaries

- **The seed:** Instance-ID temporal consistency: use segmentation IDs as a hard logical rejection to kill ghosting at object boundaries, landing in core/critic.
- **Source:** `sources-idea2.md:109`.
- **What is wrong as written:** Requires the renderer to produce stable instance IDs, which procedural generation does not guarantee across frames.
- **The kernel worth keeping:** Hard rejection on identity where identity is known. The strongest anti-ghosting constraint available, and it is free if the renderer can emit IDs.
- **Status:** new.
- **Smallest experiment:** Render a sequence with stable instance IDs and confirm the hard rejection kills a ghost at an object boundary that a pixel comparison missed (Thor GPU). **Machine:** Thor GPU.

#### E7 — Draft track and generative track split: physics at 480p flat-shaded, upscale asynchronously

- **The seed:** Draft track and generative track split: physics at 480p flat-shaded, upscale asynchronously, landing in Thor world engine.
- **Source:** `sources-idea2.md:485`.
- **What is wrong as written:** No numbers and no claim of what the upscale is.
- **The kernel worth keeping:** Two-resolution rendering with the cheap tier interactive. The world's ghost preview in fromgoogle5 is the same idea at a different granularity.
- **Status:** new.
- **Smallest experiment:** Render the draft at 480p flat-shaded and upscale asynchronously; it survives if the interactive frame time drops and the final frame is unchanged (Thor GPU). **Machine:** Thor GPU.

#### E9 — Coordinate-driven procedural noise computed from world coordinates instead of stored textures

- **The seed:** Coordinate-driven procedural noise computed from world coordinates instead of stored textures, landing in Infinigen engine.
- **Source:** `sources-idea2.md:487`.
- **What is wrong as written:** A formula is given but the sampling cost and the seam behaviour are not.
- **The kernel worth keeping:** Noise as a function of position, evaluated on the GPU. This is what our procedural generator already does; the seed is the caching question.
- **Status:** already being tested. `docs/lab/exp-warp-terrain.md`

#### E11 — Front desk / back office rhythm: a fast UI model and a slow background model, human-rest scheduling

- **The seed:** Front desk / back office rhythm: a fast UI model and a slow background model, human-rest scheduling, landing in first mile.
- **Source:** `sources-idea2.md:590`.
- **What is wrong as written:** No thresholds.
- **The kernel worth keeping:** Two speeds of model in one system. Same family as B19; merge the two into one seed.
- **Status:** new.
- **Smallest experiment:** Measure the first-mile p95 with the fast model alone and with the fast-plus-slow split; the split only earns its place if it holds p95 while the slow model improves accuracy (ProArt). **Machine:** ProArt.

#### E12 — Compile-time target sm_100 for a Thor build

- **The seed:** Compile-time target sm_100 for a Thor build, landing in core/engine.
- **Source:** `sources-fromgoogle4.md:666`.
- **What is wrong as written:** Thor is compute capability 11.0, sm_110 (verified against NVIDIA's own Jetson skill table and Modular's target list). sm_100 is Blackwell datacenter. sm_100 code will not run on the Thor.
- **The kernel worth keeping:** The trap the brief warned about, made concrete. Every .target sm_100 in liquid1, liquid2 and fromgoogle4 is wrong for our box.
- **Status:** killed by fact. `docs/lab/IDEAS.md` Part B (and the brief's own warning)

#### E15 — DLA offload for a vision path

- **The seed:** DLA offload for a vision path, landing in decision models.
- **Source:** `sources-idea3.md:14`.
- **What is wrong as written:** There is no NVDLA on this SoC (killed by fact, confirmed in the device tree).
- **The kernel worth keeping:** None. Recorded so it is not re-proposed.
- **Status:** killed by fact. `docs/lab/IDEAS.md` Part B: no NVDLA on this SoC

#### E16 — NVDEC / NVJPG hardware intercept: route raw image and video streams into Thor's Media Engine instead of the CPU

- **The seed:** NVDEC / NVJPG hardware intercept: route raw image and video streams into Thor's Media Engine instead of the CPU, landing in Thor world engine.
- **Source:** `sources-idea3.md:23`.
- **What is wrong as written:** There are no cameras on this devkit (killed by fact), so the decode path has no input; the Media Engine itself is real.
- **The kernel worth keeping:** None as written. The encoder half is used, the camera half is not available.
- **Status:** killed by fact. `docs/lab/IDEAS.md` Part B: no cameras on this devkit

#### E17 — Stream raw logits over the inter-chip link instead of tokens

- **The seed:** Stream raw logits over the inter-chip link instead of tokens, landing in decision models.
- **Source:** `sources-idea3.md:30`.
- **What is wrong as written:** The claim assumes NVLink-C2C between the laptop and the Thor; there is no C2C link to the ProArt.
- **The kernel worth keeping:** None as written for ProArt-to-Thor. Same idea inside one box is just a device read.
- **Status:** killed by fact. `docs/lab/IDEAS.md` Part B: no NVLink-C2C to the ProArt

#### E19 — Static pools: pre-allocate the KV cache and reuse it

- **The seed:** Static pools: pre-allocate the KV cache and reuse it, landing in decision models.
- **Source:** `sources-idea3.md:107`.
- **What is wrong as written:** Pre-allocation is right; the static 4 MB block size is invented.
- **The kernel worth keeping:** Static KV allocation so the night never fragments or reallocates mid-job. The allocation-in-the-hot-path constraint is real.
- **Status:** new.
- **Smallest experiment:** Pre-allocate the KV pool for the night's decision models and measure the fragmentation and allocation stalls it removes (Thor GPU). **Machine:** Thor GPU.

#### E22 — Green Contexts to split 2,560 cores between a patient render and an interactive lane

- **The seed:** Green Contexts to split 2,560 cores between a patient render and an interactive lane, landing in night.
- **Source:** `sources-idea3.md:856`.
- **What is wrong as written:** The partition is real on the chip and absent from our tooling: our nvidia-smi has no mig subcommand at all and reports MIG mode Disabled, while the datasheet line describes the chip's capability rather than the devkit's. NVIDIA documents a JetPack 7.2 preview for Jetson Thor, and enabling MIG changes the GPU mode and needs the box idle and a reset, so it is a planned window rather than a seat experiment.
- **The kernel worth keeping:** Two lanes on one GPU with a real boundary between them. On the chip the boundary is MIG, not Green Contexts. On our box it is currently unreachable: the tooling exposes no mig subcommand, so the first experiment is whether the JetPack 7.2 preview packages give us the commands, and only then whether a partition helps.
- **Status:** new.
- **Smallest experiment:** First check whether the JetPack 7.2 MIG preview gives us the commands our nvidia-smi lacks; if it does, create the pair and measure the interactive lane's p99 under a saturated batch lane. If it does not, measure the same thing with CUDA Green Contexts, which partition SMs only (Thor GPU). **Machine:** Thor GPU.

#### E23 — Coherent UVM: the GPU reads memory the CPU wrote with no copy

- **The seed:** Coherent UVM: the GPU reads memory the CPU wrote with no copy, landing in core/engine.
- **Source:** `sources-idea3.md:832`.
- **What is wrong as written:** True on Thor, and the coherence is what makes the two-sided pipeline possible.
- **The kernel worth keeping:** One coherent buffer across CPU and GPU. The finding is settled; the seed is using it for the tile ledger.
- **Status:** already built. `docs/lab/exp-unified-memory.md`

#### E24 — Partial scene splice: reuse unchanged geometry instead of a full rebuild

- **The seed:** Partial scene splice: reuse unchanged geometry instead of a full rebuild, landing in core/engine.
- **Source:** `sources-idea4.md:977`.
- **What is wrong as written:** Matches our own 2.3-2.5x partial-splice claim, so it is a restatement rather than a new idea.
- **The kernel worth keeping:** Partial recipe splices instead of cold rebuilds. Already built in the stage cache.
- **Status:** already built. the stage cache; `docs/lab/exp-trellis-graph.md`

#### E25 — Content-addressed stage cache keyed by recipe hash

- **The seed:** Content-addressed stage cache keyed by recipe hash, landing in core/engine.
- **Source:** `sources-idea4.md:775`.
- **What is wrong as written:** True and already ours.
- **The kernel worth keeping:** Already built: the stage cache is content-addressed.
- **Status:** already built. `core/engine`, content-addressed stage cache

#### E26 — Warp SDF mesher as the mesh path, bit-identical to the CPU terrain port

- **The seed:** Warp SDF mesher as the mesh path, bit-identical to the CPU terrain port, landing in Infinigen engine.
- **Source:** `sources-idea4.md:13`.
- **What is wrong as written:** The sources cite our own measured 3.9x; our lab records 44-56x on a different comparison, and the two are different measurements of different things.
- **The kernel worth keeping:** Warp SDF meshing. Already being tested (exp-warp-mesher-sdf.md).
- **Status:** already being tested. `docs/lab/exp-warp-mesher-sdf.md`

#### E27 — In-place glTF quantization plus meshopt, emitting a compressed delta

- **The seed:** In-place glTF quantization plus meshopt, emitting a compressed delta, landing in viewer.
- **Source:** `sources-idea4.md:1173`.
- **What is wrong as written:** A real technique; the delta size depends entirely on the geometry change.
- **The kernel worth keeping:** Quantize in place and ship a delta over SSE. The delta channel is the transport; the sizes are ours to measure.
- **Status:** new.
- **Smallest experiment:** Quantize a mesh in place with meshopt and measure the byte size and the render-time difference against the original (Thor GPU). **Machine:** ProArt.

#### E28 — An SSE delta channel: broadcast a binary geometry patch to the viewer

- **The seed:** An SSE delta channel: broadcast a binary geometry patch to the viewer, landing in viewer.
- **Source:** `sources-idea4.md:1405`.
- **What is wrong as written:** The 629 B figure is our own table-move measurement being reused as a geometry-delta size.
- **The kernel worth keeping:** A binary delta channel to the viewer. The transport is boring and right; the size claim needs re-measuring.
- **Status:** new.
- **Smallest experiment:** Push a binary geometry delta over SSE to the viewer and measure the end-to-end time from a mesh change to a pixel change (ProArt). **Machine:** ProArt.

#### E29 — Anticipatory generation: pre-generate adjacent rooms while the user is looking at one

- **The seed:** Anticipatory generation: pre-generate adjacent rooms while the user is looking at one, landing in Thor world engine.
- **Source:** `sources-idea4.md:776`.
- **What is wrong as written:** The chat's justification is a prediction of where the user will move, which we cannot know.
- **The kernel worth keeping:** Predictive adjacency. The night already does speculative work; the seed is doing it in the room graph rather than in the recipe graph.
- **Status:** new.
- **Smallest experiment:** Predict the next room in the graph and pre-generate it; measure the hit rate against the actual next room the user opens (Thor GPU). **Machine:** Thor GPU.

#### E30 — Stream priority: separate CUDA streams with different priorities for meshing and rendering

- **The seed:** Stream priority: separate CUDA streams with different priorities for meshing and rendering, landing in core/engine.
- **Source:** `sources-idea4.md:199`.
- **What is wrong as written:** Stream priority is real; it does not preempt, and the chat's 30%/70% SM split does not follow from it.
- **The kernel worth keeping:** Two priorities, one box. The night render is patient, the interaction is not. Priority ordering is the cheap version of the fence.
- **Status:** already being tested.

#### E31 — manifold3d for real-time topological repair of generative output

- **The seed:** manifold3d for real-time topological repair of generative output, landing in core/mesh repair.
- **Source:** `sources-idea4.md:1705`.
- **What is wrong as written:** TRELLIS.2's non-watertight output is a real observation (the model exists on HF as microsoft/TRELLIS.2-4B), but 'real-time' repair of a 4B model output is a cost claim with no number.
- **The kernel worth keeping:** Mesh repair after generative steps. The repair is needed; the question is where it goes and what it costs.
- **Status:** already being tested. `docs/lab/exp-mesh-repair.md`

#### E32 — Take absolute control of memory management: a custom virtual block page allocator from day one

- **The seed:** Take absolute control of memory management: a custom virtual block page allocator from day one, landing in core/engine.
- **Source:** `sources-idea3.md:322`.
- **What is wrong as written:** The 4 MB block size is invented; the claim that the default allocator should be replaced is the point.
- **The kernel worth keeping:** A custom allocator so the night's memory is predictable and eviction is ours to define. Standard, and it makes eviction predictable.
- **Status:** new.
- **Smallest experiment:** Pre-allocate the night's buffers as fixed blocks and measure the eviction rate against the allocator's current behaviour (Thor GPU). **Machine:** Thor GPU.

#### E33 — Explicit ARM core affinity: lock the world-mcp listener and the glTF daemon to cores 11-13

- **The seed:** Explicit ARM core affinity: lock the world-mcp listener and the glTF daemon to cores 11-13, landing in core/engine.
- **Source:** `sources-idea4.md:325`.
- **What is wrong as written:** Real mechanism (pthread_setaffinity_np), but pinning to specific cores on a shared box assumes the box is ours.
- **The kernel worth keeping:** Affinity for the listener and the serialiser, so the interactive cores stay free. On a shared box this becomes a fairness question.
- **Status:** new.
- **Smallest experiment:** Pin the listener and the serialiser to specific cores and measure the interactive cores' jitter with and without pinning (Thor GPU). **Machine:** Thor GPU.

#### E34 — A recipe ledger: recipes, not objects, are the unit of record

- **The seed:** A recipe ledger: recipes, not objects, are the unit of record, landing in core/engine.
- **Source:** `sources-idea4.md:1267`.
- **What is wrong as written:** The 629 B analogue is our own measurement reused as a bound.
- **The kernel worth keeping:** Recipes as the record, objects as a cache of them. The stage cache already does this; the ledger makes it durable.
- **Status:** already built. the recipe ledger; `docs/research/stage-cache-thor.md`

#### E36 — A hardware-bound scheduler in a shared library

- **The seed:** A hardware-bound scheduler in a shared library, landing in core/engine.
- **Source:** `sources-idea4.md:579`.
- **What is wrong as written:** 'libthordeo_ux.so' and the module names are invented; the scheduling job is real.
- **The kernel worth keeping:** One scheduler that owns the box's GPU lanes. The box is shared, and right now nothing owns it.
- **Status:** new.
- **Smallest experiment:** Measure how much of the box's wall time goes to work nobody scheduled; a single owner should recover it (Thor GPU). **Machine:** Thor GPU.


### F. The swarm contract (`sources-idea5.md`)

#### F1 — A conductor that assigns one score and arbitrates, rather than letting agents negotiate

- **The seed:** A conductor that assigns one score and arbitrates, rather than letting agents negotiate, landing in night.
- **Source:** `sources-idea5.md:20`.
- **What is wrong as written:** The score has no definition and no tie-break rule.
- **The kernel worth keeping:** A single arbiter with a score for the night. We have the tile chooser; the seed is applying the score to workers, not to tiles.
- **Status:** new.
- **Smallest experiment:** Give the night a single arbiter with one score, and measure whether the score predicts the kept artifact better than per-worker local scores do (Thor GPU). **Machine:** Thor GPU.

#### F2 — MIG as a physical fence: partition by bandwidth sensitivity rather than compute

- **The seed:** MIG as a physical fence: partition by bandwidth sensitivity rather than compute, landing in night.
- **Source:** `sources-idea5.md:32`.
- **What is wrong as written:** The partition is real on the chip and absent from our tooling. Our nvidia-smi has no mig subcommand at all and reports MIG mode Disabled, where a chip without the feature reports [N/A], so the datasheet line describes the GPU and the devkit does not expose the partitioning. NVIDIA documents a JetPack 7.2 preview for Jetson Thor, and enabling MIG changes the GPU's mode and needs the box idle and a reset, so it is Casey's call in a planned window rather than a seat experiment.
- **The kernel worth keeping:** Partition the box into a latency lane and a batch lane with a hard boundary, chosen around bandwidth sensitivity rather than FLOPs. On the chip the boundary is MIG rather than Green Contexts. On our box it is currently unreachable, so the first experiment is whether the preview packages give us the commands we lack.
- **Status:** new.
- **Smallest experiment:** First check whether the JetPack 7.2 MIG preview gives us the mig subcommand our nvidia-smi lacks; if it does, create the pair and measure the interactive lane's p99 under a saturated batch lane. If it does not, measure the same thing with CUDA Green Contexts, which partition SMs only (Thor GPU). **Machine:** Thor GPU.

#### F3 — Schedule with hierarchy: tell the scheduler who is whose subagent

- **The seed:** Schedule with hierarchy: tell the scheduler who is whose subagent, landing in core/engine.
- **Source:** `sources-idea5.md:44`.
- **What is wrong as written:** TensorRT-LLM's agent_hierarchy and subagent_affinity_id are real vLLM/TensorRT-LLM features, but they are model-server features, not OS scheduling features.
- **The kernel worth keeping:** A parent/child relation in the scheduler, so a child's deadline does not compete with its parent's. Cheap to add to our scheduler and it matches the conductor model.
- **Status:** new.
- **Smallest experiment:** Add a parent-child tag to the scheduler and measure whether a child's deadline is met when its parent is also queued (Thor GPU). **Machine:** Thor GPU.

#### F4 — The consistency contract: a shared committed history, and evidence routed into each worker's context

- **The seed:** The consistency contract: a shared committed history, and evidence routed into each worker's context, landing in night / core/store.
- **Source:** `sources-idea5.md:52`.
- **What is wrong as written:** ConsistWorld is a real paper (evidence routing, pose-conditioned retrieval, visibility-gated peer sharing) and Gamma-World is real (Sparse Hub Attention, 24 FPS), but neither runs on our box and neither is about procedural geometry.
- **The kernel worth keeping:** One committed history that every worker reads from. The vector-DB canon is the natural implementation; the seed is the routing rule.
- **Status:** new.
- **Smallest experiment:** Route a canonical slice into each worker's context and measure whether two workers generating adjacent chunks agree on the shared geometry (Thor GPU). **Machine:** Thor GPU.

#### F5 — Shared world-state registers instead of shared chatter

- **The seed:** Shared world-state registers instead of shared chatter, landing in night / core/store.
- **Source:** `sources-idea5.md:58`.
- **What is wrong as written:** WorldWeaver's name is wrong: the paper is WorldWeave (WorldWeave: Growing Persistent Geometric Worlds for Video Generation). A shared register is the right shape for procedural work; the paper's method is for video.
- **The kernel worth keeping:** A small shared register of world state that workers read and write, rather than passing messages. This is the cheap version of F4 and fits our stage cache exactly.
- **Status:** new.
- **Smallest experiment:** Have every worker read and write one small shared register and measure whether they stay consistent without messaging (Thor GPU). **Machine:** Thor GPU.

#### F7 — Engagement rules and budgets: the swarm contract

- **The seed:** Engagement rules and budgets: the swarm contract, landing in core/engine.
- **Source:** `sources-idea5.md:60`.
- **What is wrong as written:** The rules are named, not specified.
- **The kernel worth keeping:** Per-agent budgets in the scheduler. The night needs a way to say 'this job gets 20 minutes of the box'.
- **Status:** new.
- **Smallest experiment:** Give each night job a stated budget and measure whether the budget is respected and whether the useful work still fits (Thor GPU). **Machine:** Thor GPU.

#### F8 — Three-layer swarm: MIG fence, conductor score, consistency contract

- **The seed:** Three-layer swarm: MIG fence, conductor score, consistency contract, landing in night.
- **Source:** `sources-idea5.md:69`.
- **What is wrong as written:** A synthesis; the layers are individually unproven.
- **The kernel worth keeping:** The synthesis is the thesis of this document. Its three parts are F2, F1 and F4.
- **Status:** new.
- **Smallest experiment:** The synthesis depends on F2, F1 and F4; test those three first, and this one is the summary. **Machine:** Thor GPU.


### G. The thin-client split and the inversion ideas (`sources-fromgoogle5.md`)

#### G1 — The ghost preview pass: stream a voxelised structural blueprint to the laptop while the heavy render queues overnight

- **The seed:** The ghost preview pass: stream a voxelised structural blueprint to the laptop while the heavy render queues overnight, landing in viewer / first mile.
- **Source:** `sources-fromgoogle5.md:7`.
- **What is wrong as written:** 'Instantly' has no budget, and a voxelised bounding-box layout is not yet a preview the user can act on; the more serious problem is that the chat never says what happens when the night produces something the preview did not promise.
- **The kernel worth keeping:** The split, not the voxelisation: a cheap structural stand-in that the first mile shows immediately, and the real render that lands later. This is our draft-track idea with the transport specified.
- **Status:** new.
- **Smallest experiment:** Measure the preview path end to end: generate the structural blueprint for a room and time both the blueprint generation and its transport to the ProArt, against the cost of the full render it stands in for. It survives if the preview is inside the first-mile latency budget (Thor GPU). **Machine:** Thor GPU.

#### G2 — State-space serialization: the day's edits become a dependency graph that the night compiles

- **The seed:** State-space serialization: the day's edits become a dependency graph that the night compiles, landing in night / core/engine.
- **Source:** `sources-fromgoogle5.md:107`.
- **What is wrong as written:** No schema, no version, and no reconciliation against the canon; and the 'system cron-task triggers the full pipeline' assumes a clean cut between day and night, which is false on a box other seats share.
- **The kernel worth keeping:** A graph, not a script. The day's interactions compile into the night's recipe rather than being re-derived from scratch. It is the recipe ledger with an authoring path on the front of it.
- **Status:** new.
- **Smallest experiment:** Take one day of real edits, serialize them into the recipe graph the night already consumes, and check that the night's output matches what the day implied. If the two diverge, the serialization is losing something and the schema needs a version and a reconciliation rule (Thor GPU). **Machine:** Thor GPU.

#### G3 — The morning reveal: the session opens on what the night built, and the diff is the product

- **The seed:** The morning reveal: the session opens on what the night built, and the diff is the product, landing in viewer / night.
- **Source:** `sources-fromgoogle5.md:20`.
- **What is wrong as written:** A presentation idea dressed as an architecture one; it says nothing about how the night decides what changed, or how the user learns what to look at.
- **The kernel worth keeping:** The night is only legible if the morning shows what it did. A diff against yesterday's room is the cheapest product surface we have not built, and it is the natural output of the recipe ledger.
- **Status:** new.
- **Smallest experiment:** Render last night's room and the room before it and diff them. The deliverable is the diff a user can read in a second: which tiles changed, which geometry was rebuilt, what the night spent its time on. If the diff cannot be produced from the recipe ledger, the ledger is not carrying enough provenance (ProArt). **Machine:** ProArt.

#### G4 — Real-world geometry as the constraint space: your desk becomes the bounds for generation

- **The seed:** Real-world geometry as the constraint space: your desk becomes the bounds for generation, landing in Thor world engine.
- **Source:** `sources-fromgoogle5.md:49`.
- **What is wrong as written:** 'Absolute mathematical algebraic geometry boundaries' is an overreach; the mechanism is 'measure the room, then constrain the solver', and the measurement needs cameras this devkit does not have.
- **The kernel worth keeping:** Take a measured environment as a constraint input rather than a reference image. The mechanism is the constraint solver we already have; the input is new.
- **Status:** new.
- **Smallest experiment:** Take a known box (our ProArt's own dimensions are known) and constrain a generation to it: generate a room bounded by those measurements and check the solver honours them exactly. The camera is not needed to test the constraint path (Thor GPU). **Machine:** Thor GPU.

#### G5 — Invert the optical flow accelerator: motion vectors become force-field modifiers on the procedural lattice

- **The seed:** Invert the optical flow accelerator: motion vectors become force-field modifiers on the procedural lattice, landing in Thor world engine.
- **Source:** `sources-fromgoogle5.md:84`.
- **What is wrong as written:** A 2D motion field driving a 3D lattice is underspecified, and the whole path needs the camera array this devkit does not have; the '60 FPS' claim has no measurement behind it.
- **The kernel worth keeping:** Treat a motion field as a deformation input to the generator rather than as something to track. A physically real input to the solver, which is the shape the constraint theory work wants anyway.
- **Status:** new.
- **Smallest experiment:** Take a recorded motion field and feed it to the generator as a deformation input, then check that the output geometry changes in the direction the field points. The camera is not needed to test the mechanism (Thor GPU). **Machine:** Thor GPU.


---

## R&D themes, ranked by expected payoff

The 95 new seeds cluster into nine themes. The clustering is the Groq assignment
(120b, in chunks of 15 against a closed id list, with retries) with my corrections
applied; the ranking is the 120b second opinion, adjusted where it leaned on a
hardware claim we do not have.

The ranking criterion is payoff for the product, weighted by how much of the work
already exists. A theme whose payoff rests on an unverified hardware claim is marked
blocked and ranked lower until the fact is measured.


### 1. One GPU, many jobs: the shared Thor

The Thor is one shared SoC doing meshing, rendering, judging and deciding at once; the work is in owning it, fencing the lanes and making the schedule fair to other seats.

- **New seeds:** 19 — B12, B22, B23, B24, C4, C5, C6, C10, C24, D11, E19, E22, E32, E33, E36, F2, F3, F7, F8
- **Already built / tested / killed:** 13 — B4, C1, C2, C3, E2, E3, E4, E12, E15, E16, E17, E23, E30
- **Second opinion (120b):** payoff 9/10, ease 4/10. Blocked: yes: Jetson AGX Thor lacks pre‑emptive compute kernel scheduling, making fair multitasking uncertain
- **120b's smallest experiment:** Thor GPU: launch two CUDA streams (meshing and rendering) with different priority flags (E30) and measure interference, stall time, and any missed deadlines (≤1 day).

### 2. From a generated mesh to a usable world

The path from raw generative output to something a person can look at: repair, quantise, delta, stream, and keep the interaction responsive while it happens.

- **New seeds:** 7 — B26, E1, E5, E6, E7, E27, E28
- **Already built / tested / killed:** 5 — E24, E25, E26, E31, E34
- **Second opinion (120b):** payoff 9/10, ease 8/10. Blocked: yes: current USB/PCIe bandwidth from Jetson to ProArt limits streaming of >10 M‑vertex meshes at interactive rates
- **120b's smallest experiment:** Thor + ProArt: generate a mesh with the Warp SDF mesher (E26), repair it with manifold3d (E31), stream it over USB, and measure end‑to‑end latency to render on the laptop (≤1 day).

### 3. Confidence routing, escalation and reflex bands

Route on a calibrated score, hold the score steady with hysteresis, and never wait: every rung of the ladder has a deadline and a fallback.

- **New seeds:** 8 — B2, B5, B13, B15, B21, C12, C21, F1
- **Already built / tested / killed:** 3 — B1, B14, B28
- **Second opinion (120b):** payoff 8/10, ease 7/10. Blocked: yes: calibrated confidence scores are not yet available for all local decision models
- **120b's smallest experiment:** Thor GPU: feed a decision model a set of queries, record its raw confidence, apply the hysteresis barrier (B14) and escalation policy, and measure fallback activation rate and latency (≤1 day).

### 4. Tile execution: what a tile may do and how it runs

A tile is a script the cloud wrote once; the questions are what it may touch, how it is sandboxed, when it is compiled and when it is retired.

- **New seeds:** 15 — C19, C22, D2, D3, D4, D9, D12, D15, D16, D17, D23, D24, D25, D30, D40
- **Already built / tested / killed:** 2 — D13, D14
- **Second opinion (120b):** payoff 8/10, ease 7/10. Blocked: no
- **120b's smallest experiment:** Thor GPU: execute a synthetic tile that attempts an illegal memory write; verify that the double‑buffered atomic mailbox (D14) blocks the write and that the system remains stable (≤1 day).

### 5. First mile: a laptop that answers in a breath

The ProArt is the interface; most requests should cost nothing, near-misses should be one line of confirmation, and misses should become reflexes that are free next time.

- **New seeds:** 9 — B3, B17, B19, B20, B25, B29, C14, D1, E11
- **Already built / tested / killed:** 0 — none
- **Second opinion (120b):** payoff 8/10, ease 4/10. Blocked: yes: typical round‑trip network latency to the cloud LLM exceeds 200 ms, breaking the breath‑time goal
- **120b's smallest experiment:** ProArt: issue a representative user query to the cloud LLM, measure total latency (including any reflex‑band cache warm‑up), and compare to a 200 ms target (≤1 day).

### 6. Cloud-local update loop

The cloud proposes, the box verifies, the box installs: a closed loop for prompts, weights and schemas in which a remote change never becomes an unverified one.

- **New seeds:** 9 — B7, B10, B16, C23, D6, D19, D20, D22, D34
- **Already built / tested / killed:** 2 — B8, B11

### 7. Plausibility and consistency critic

The critic must judge whether a generated thing could exist, not only whether it agrees with itself; the measured failures show a consistency-only critic admits confident ghosts.

- **New seeds:** 11 — A1, A2, A3, A4, A5, A6, A7, A8, B27, C20, D31
- **Already built / tested / killed:** 0 — none
- **Second opinion (120b):** payoff 7/10, ease 3/10. Blocked: yes: lack of labeled plausibility dataset for training/evaluating a critic
- **120b's smallest experiment:** ProArt: run a CLIP‑based plausibility scorer on a batch of generated tiles, compare scores to a small human‑rated sample to see if the scorer can reject obviously impossible objects (≤1 day).

### 8. State, events and the shape of a night

The night is a long-running, bounded, observable job: its event log, buffers, forks and state records all have fixed shapes so the run is predictable and its failures are readable.

- **New seeds:** 13 — B18, C7, C8, C13, D7, D8, D18, E29, F4, F5, G1, G2, G3
- **Already built / tested / killed:** 1 — D10
- **Second opinion (120b):** payoff 6/10, ease 5/10. Blocked: no
- **120b's smallest experiment:** ProArt: run a full‑night generation, capture the event log and system state buffers, then repeat the run to check that shapes and ordering are identical across runs (≤1 day).

### 9. World generation as a constrained physics problem

Assets are born stable rather than repaired after: the constraint enters the generation, the room graph carries the rules, and the world itself is the data structure.

- **New seeds:** 2 — G4, G5
- **Already built / tested / killed:** 1 — E9
- **Second opinion (120b):** payoff 6/10, ease 3/10. Blocked: yes: no efficient differentiable physics solver available for Jetson AGX Thor
- **120b's smallest experiment:** Thor GPU: implement a tiny constraint solver that places axis‑aligned boxes without overlap using CUDA, run it on a 100‑item scene and record solve time and constraint violations (≤1 day).

### Why this order

**1. One GPU, many jobs.** The Thor is one shared SoC and the box is shared with other
seats. Every other theme's experiment has to run somewhere, and the interesting
constraint is that they all want the same 2,560 CUDA cores and the same LPDDR5X
bandwidth. The measured numbers are unforgiving on bandwidth — 166 GB/s eager and
about 220 GB/s graphed against a 273 GB/s datasheet figure — and they have just
changed on precision: native NVFP4 through cuBLASLt measures 371-456 TFLOPS dense at
K of 2,048 and above, at half FP8's joules per GEMM and 3.55x smaller weights than
BF16, while the library kernels lose to BF16 at K of 1,280 and below. So the box has
a real FP4 tier and it is shape-gated, and the earlier 13.69 TFLOPS figure that
suggested otherwise was a dequantise fallback rather than the hardware. The hardware fact that makes this theme tractable is MIG, and the
fact that makes it delicate is that our tooling does not expose it: `nvidia-smi` on
this box has no `mig` subcommand at all and reports MIG mode `Disabled`, where a chip
without the feature reports `[N/A]`. The datasheet line "Multi Instance GPU (MIG) with
10 TPCs" describes the GPU; the devkit does not expose the partitioning. NVIDIA ships
a JetPack 7.2 preview for Jetson Thor, and enabling MIG changes the GPU's mode and
needs the box idle and a reset, so it is Casey's call in a planned window rather than a
seat experiment.

**2. From a generated mesh to a usable world.** The highest ease in the set: the stage
cache, the content addressing, the recipe ledger and the Warp mesher all exist. What is
missing is the last mile of it — repair, quantise, delta, stream — and the delta
channel is the transport that makes the whole thing feel live. Cheap to measure, and
every measurement lands on an asset someone will actually look at.

**3. Confidence routing, escalation and reflex bands.** The hysteresis gate is built and
measured, which makes this theme unusually cheap. What is missing is the calibration
underneath it, and our own measurement says the problem is sharper than the sources
imagine: the 600M reports 0.97 mean confidence at 0.415 accuracy, and the three d1
sizes return "confidence" by three different formulas — a normalised margin for the
LFM2 cells, the raw top probability for the LFM3 cell — so a threshold on confidence
is not even the same quantity across models. Recomputing confidence from the
probability vectors the endpoint already returns, under one stated definition, is the
cheapest high-value measurement in the bank. Also the theme that the first-mile and
tile themes both depend on.

**4. Tile execution.** We know exactly what a tile may do — the vocabulary door is
stricter than the sources' veto — but not how it runs or when it is retired. The
defects here are concrete and checkable: a missing cycle check, an undefined calling
convention, a misaligned second buffer.

**5. First mile.** The retrieval front over cached intents is the highest-leverage
single change available, and the director has already proposed it. It is ranked fifth
because the theme also carries the cloud round trip, which is outside our control and
slow.

**6. Cloud-local update loop.** Real and worth doing, but it is an amplifier of the
other themes rather than a capability of its own, and it carries the security question
(there is no hardware root of trust on the Thor to verify a weight delta).

**7. Plausibility and consistency critic.** The sources' only measured set, and the
measurements are negative: pixel distillation at 0.6053 off-manifold and
consistency-only at 0.9925 both produce confident ghosts, while stochastic exact
conditional holds at 0.0530. That is a strong starting point and a weak
implementation. Ranked seventh because the geometry side is a research project, not a
week's work.

**8. State, events and the shape of a night.** Mostly hygiene, and mostly
already-in-the-code ideas. Worth doing, not worth a quarter.

**9. World generation as a constrained physics problem.** The most speculative. The
idea that assets should be born stable rather than repaired after is the right
direction, but no source gives a procedure, and the seed with the clearest kernel
(baking constraints into generation) needs a training story that does not exist yet.


---

## The top ten new seeds, and what we would do about each

The list is the 120b second opinion's ranking, with my corrections: it put B11 and
B12 first because they are cheap, and I moved them down because neither changes what
the product can do on its own — the wake-up and the plumbing are worth doing inside
other themes rather than as a plan of their own. What survives is the set that unlocks
a capability the product does not have, and that one small experiment can kill.


### 1. D1 — The retrieval front: embedding retrieval over the tile library, with the hysteresis gate holding the bands

*sources-new1.md:211. Landing in tiles / first mile. Kernel: The bands (0.80 / 0.55) are pincher's defaults, not ours.*

The tile library is content-addressed and the chooser is a contextual bandit that
learns from outcomes, but the chooser can only choose from tiles it has been given. Put
an embedding retrieval front in front of it: embed the game state, take the top K by
meaning, then let the bandit choose among those K. The sources' version of this is
pincher's, and its numbers are ours to re-measure. The smallest experiment is already
written down in `docs/research/pincher-fit.md` as E1: replay the tile logs offline with
the embedding fast path at 0.80 and the bandit's logged choice as the fallback, and see
whether it covers 30% of contexts at the bandit's reward with p95 under 50 ms. Run it on
the ProArt, numpy-only if the embeddings can be exported, since the whole point is that
the fast path costs nothing. The reason it is first is that every other theme's
throughput depends on it: the first mile, the night and the swarm all need a way to
answer "what should I do" without a model call.

There is a second lever in the same place, and it is free. A decision model's accuracy
on a K-way choice question depends on the option set, not only on the state, and our
tile vocabulary is a choice set. The tile door already admits a tile only if the words
exist; the model-side version of that is to make the vocabulary smaller and sharper,
which costs nothing to deploy. The measurement is to re-score one task at K in {2, 3, 5}
by re-partitioning the ground truth, and to permute the option keys and see whether the
model's answer follows the semantics or the position. If accuracy is flat in K and the
model is permutation-stable, the option set is not a lever and the vocabulary work
stays in the door.

### 2. B15 — Brier-score calibration tracking, and one definition of confidence to compute it against

*sources-liquid2.md:1584. Landing in decision models. Kernel: The 0.18/0.08 drift thresholds are invented, and the chat never says what is retuned when the score drifts.*

The hysteresis gate is built and measured, and the sources give it thresholds
(0.92 and 0.78) with nothing behind them. Our own measurement says the problem is
worse than "uncalibrated": the 600M reports 0.97 mean confidence at 0.415 accuracy,
and through the LFM2 formula that is (p_max − 0.2)/0.8, so p_max ≈ 0.976 — nearly
deterministic and mostly wrong. Worse, the three d1 sizes return confidence by three
different formulas, so a threshold on "confidence" is not even the same quantity from
one model to the next, and any cross-size confidence column is comparing a margin
against a probability.

The experiment costs no new model runs. The endpoint already returns the full
probability vector for every answer, so the same week of logs can be re-scored three
ways — top probability, normalised margin, entropy-normalised score — and published as
accuracy, ECE with reliability bins, Brier score and mean confidence per cell per
definition, with the escalation rate at a threshold sweep. The question that matters
is not which number is best but whether any of them, at any threshold, would have
fired the right number of escalations. If none does, the 600M's confidence carries no
signal in any form, the escalation ladder must be driven by model disagreement or the
bandit's estimate instead, and that is a firmer and more useful statement than
"uncalibrated".

### 3. F2 — MIG as a physical fence: split the Thor into a latency lane and a batch lane, and choose the split by bandwidth sensitivity

*sources-idea5.md:32. Landing in night. Kernel: The partition is real on the chip and absent from our tooling. Our nvidia-smi has no mig subcommand at all and reports MIG mode Disabled, where a chip without the feature reports [N/A], so the datasheet line describes the GPU and the devkit does not expose the partitioning. NVIDIA documents a JetPack 7.2 preview for Jetson Thor, and enabling MIG changes the GPU's mode and needs the box idle and a reset, so it is Casey's call in a planned window rather than a seat experiment.*

The sources treat MIG as a partitioning convenience. It is closer to a fence, and the
fence is what a shared box needs: a render, the critic and the decision models each
get a fenced slice that cannot starve the others, which is stronger than Green Contexts
(SMs only) or thor-admit (admission only).

The hardware supports it. The chip has 20 SMs and NVIDIA documents a JetPack 7.2
preview for Jetson Thor whose supported pairing is profile 83 (`2g.0gb+gfx`, 12 SM,
1,536 CUDA cores) with profile 78 (`1g.0gb+me`, 8 SM, 1,024 CUDA cores) — 12 plus 8
equals 20, and 1,024 cores at 128 per SM is the arithmetic that closes. The 12 SM
instance is the AI and graphics partition and the 8 SM one is for control, perception
and safety-critical work, so the lane assignment is not free: the render and the
meshing want the 12, and the interactive reflex wants the 8.

Our tooling is the problem, and that is what the experiment has to establish first.
Our `nvidia-smi` has no `mig` subcommand at all, and reports MIG mode `Disabled`
rather than `[N/A]`, which is what a chip without the feature would say. So the
datasheet line describes the GPU and the devkit does not expose the partitioning. The
first check is therefore whether the JetPack 7.2 preview packages give us the commands
we lack; only then is the partition worth testing. If it does, the measurement is the
interactive lane's p99 with the fence up against the same load with no fence. If it
does not, the same measurement with CUDA Green Contexts tells us whether a software
fence is worth building, and the scheduler has to carry the guarantee alone.

### 4. E6 — Instance-ID temporal consistency: reject a ghost at an object boundary using segmentation IDs, not pixels

*sources-idea2.md:109. Landing in core/critic. Kernel: Requires the renderer to produce stable instance IDs, which procedural generation does not guarantee across frames.*

The perception-to-generation chat's measured failures are all ghosting: a frame that
is consistent with itself and impossible as an object. A pixel comparison cannot catch
that, because the ghost is locally coherent. An instance ID can: if the renderer emits
stable per-object IDs across frames, then an object that changes identity between two
frames is wrong regardless of how the pixels agree. This is a hard logical rejection
rather than a score, which is why it is worth having — a score can be traded off
against another score, a rejection cannot. The precondition is the real work: the
procedural generator does not currently promise stable instance IDs across frames, so
the experiment has to establish that first. On the Thor, render a short sequence with
IDs carried across frames, then take the known ghosts and check that the ID transition
rejects them where the pixel comparison passed them. If the renderer cannot hold IDs
stable, the seed does not fire and the effort goes into the renderer.

### 5. A7 — The perception round trip as a generation-time filter, not as a training loss

*sources-fromminimax.md:18. Landing in Thor world engine. Kernel: The chat uses the round trip as a training loss, and the measurement shows that loss is degenerate. Used as a filter at generation time it is a different proposition with a different cost, and the chat never makes that move.*

This is the corpus's only measured result, and the measurement is negative in a way
that is useful. Training a generator on `‖A(G(y)) − y‖` pins it to some point on the
fiber `F(y) = {x : A(x) = y}` and says nothing about which point: off-manifold 0.6053,
eleven times the real data, while the round trip looks perfect at 0.0621. A
consistency-only critic is worse still, 0.9925 off-manifold, and passes every frame of
both ghosts. The same round trip used as a filter at generation time is a different
thing with a different cost: generate, re-perceive, compare, and reject what cannot be
re-perceived into the same object. The experiment runs on the Thor over a batch of
generated tiles and counts the ghosts rejected, with the requirement that it rejects
the known ghosts without rejecting good tiles — the measured failure modes from
`sources-fromminimax.md` are the test set.

### 6. D19 — Version-stamp every cloud-returned delta against the canon, and reject the stale ones

*sources-new2.md:1956. Landing in night. Kernel: 'Geometric distance threshold' as a staleness test is a proxy; the exact test is a version counter.*

The sources propose a cloud loop that patches local weights, prompts and manifests,
and one of them proposes a geometric distance threshold as the staleness test. A
distance threshold is a proxy for the thing we actually want, and the thing we actually
want is a version counter: the delta names the world snapshot it was computed against,
and if that snapshot is not the current one the delta is refused. This matters more
than it looks, because the failure it prevents is silent. A stale patch applied to a
changed world does not crash; it produces a plausible artifact that is wrong, and the
night will happily keep it. The experiment is small and needs no new machinery: take a
real cloud delta, stamp it, change the world underneath it, and confirm the stamp
rejects it; then confirm the same delta with a current stamp applies. Run it on the
Thor against the stage cache.

### 7. D7 — The interruption token: a cancelled night job leaves no partial artifact

*sources-new1.md:65. Landing in core/night. Kernel: 'Rolls back the fork' implies a transactional store we do not have.*

The night is long, the world changes under it, and a user can barge in. The sources
treat cancellation as a token and a rollback; the part worth keeping is the
requirement it implies, which we do not currently meet: a cancelled job must leave
nothing behind. Today a cancelled night can leave a half-written stage in the cache,
and a half-written stage is worse than a missing one because it looks complete. The
experiment is on the Thor and it is a property test rather than a benchmark: cancel a
night job at a random point, run it a few hundred times, and assert that the stage
cache holds no artifact whose recipe is incomplete and no partial write. The
interruption token is how the cancel signal reaches the worker; the property is what
we are actually buying.

### 8. E27 — In-place glTF quantization with meshopt, so the geometry delta is a binary patch rather than a file

*sources-idea4.md:1173. Landing in viewer. Kernel: A real technique; the delta size depends entirely on the geometry change.*

The viewer gets its geometry over SSE today, and the transport is the bottleneck
rather than the generation. The mechanism is well understood: quantize the vertex data
in place where the mesher wrote it, run meshopt over it, and emit only the difference
between the new mesh and the one the viewer already has. The interesting number is not
the compression ratio but the delta size, and the sources reuse our own 629-byte
table-move measurement as if it were a geometry figure, which it is not. The experiment
is on the Thor: take a real mesh pair from two adjacent rooms, measure the in-place
quantized delta size against a full re-send, and measure the CPU cost of the
quantization and meshopt steps on a reserved core. If the delta is not dramatically
smaller than the mesh, this is a transport problem with a different solution.

### 9. F4 — The consistency contract: one committed history, and evidence routed into each worker's context

*sources-idea5.md:52. Landing in night / core/store. Kernel: ConsistWorld is a real paper (evidence routing, pose-conditioned retrieval, visibility-gated peer sharing) and Gamma-World is real (Sparse Hub Attention, 24 FPS), but neither runs on our box and neither is about procedural geometry.*

Two workers generating adjacent chunks of the same room each start from their own
context and can disagree about the shared geometry. ConsistWorld's answer — evidence
routing from a committed multi-agent history, with pose-conditioned retrieval and
visibility-gated peer sharing — is a paper about video world models, and it will not run
on our box. The transferable part is the shape: there is one committed history, and each
worker gets routed the slice of it that bears on the chunk it is making, rather than
each worker holding its own idea of the world. We already have the committed history:
the vector-DB canon. What is missing is the routing rule, which is a product decision
we have not made. The experiment is on the Thor: give two workers the same canon and
the same routing rule, then generate adjacent chunks and measure whether they agree on
the shared geometry, against the current situation where they do not.

### 10. E1 — Run the temporal upscaler on the ProArt's idle GPU during the night

*sources-idea2.md:32. Landing in viewer / first mile. Kernel: 1 to 2 seconds per frame in the browser via WebGPU, against under 2 ms on native tensor cores (sources-idea2.md:32); and what it is called a 'reimplementation' is a browser-side model download, not a reimplementation.*

The sources propose extracting a DLSS-class temporal upscaler and running it in the
browser, and they note it takes one to two seconds per frame there, which is correct
and is the reason it was not adopted. The proposal never asks the obvious question:
what is the ProArt's GPU doing while the Thor works overnight? Nothing. The upscaler's
cost is a problem when it competes with the interface and a non-problem when it does
not. The experiment is on the ProArt and it is a measurement, not an implementation:
take the last real night's output, replay it through an available upscaler on the idle
GPU, and measure the frame time and the quality against the current path. If the
quality is not there, this closes and the sources' own 1-2 second figure stands. The
seed is worth a day because the cost of being wrong is one day.

---

## Ten checkable questions for the source agents

Each targets a seed whose answer we can verify on the box or against a document, and
each names what a passing answer looks like.

---

### Q1 (to the `liquid1`/`liquid2` author) — about the cascade and the FP4 lane

Your three-rung cascade runs the 600M always-on model, escalates to a 3B model on
ambiguity, and offloads to the cloud on failure. Two things we need pinned down.

**First, the escalation thresholds.** You give confidence levels but not the calibration
that produces them. Question: what is the calibration procedure for the confidence score
that triggers each rung, and what happens to the score when the model is asked a
question outside its training distribution — does it report low confidence, or does it
report high confidence and fail downstream?

**Second, what the number actually is.** On our box the 600M reports 0.97 mean
confidence at 0.415 accuracy, and reading llama.cpp's `server-decision.cpp` we find the
LFM2 cells return a *normalised margin*, `(p_max - 1/K) / (1 - 1/K)`, not a
probability — so 0.97 means p_max of about 0.976. The LFM3 cell returns the raw top
probability instead, and the `score` question type uses a third formula again. Question:
when you say "confidence", which of these three quantities did your thresholds apply to,
and is the routing in your design comparing like with like across model sizes?

**Third, the FP4 lane.** Your precision-promotion path swaps an FP4 resident for an
INT8/FP16 resident when the FP4 output is ambiguous, and you quote a TensorRT profile
switch from about 4 ms to about 15 ms. On our Thor, an NVFP4 matmul measured 13.69
TFLOPS and was *slower* than dequantising to BF16 and multiplying — but that was
through the `torchao` path, which dequantises and never touches the FP4 units; native
NVFP4 through cuBLASLt runs 371-456 TFLOPS dense on the same chip. Question: was your
FP4 resident in the 4-bit path that engages the tensor cores, or in the fallback path
that dequantises?

*Verifiable by:* recomputing confidence from the probability vectors we already have,
under all three definitions, which needs no new model runs; and one GEMM benchmark
through the native NVFP4 path against the 13.69 TFLOPS fallback figure.

---

### Q2 (to the `fromminimax` author) — about the two-sided critic band

Your result is that a consistency-only critic passes every ghost frame, and that the
fix is a band with consistency from the perception stack and plausibility from the
prior. The band's gradient-scale gap is 4.4e-5, and the two sides therefore do not
train at the same rate.

**Question:** in the band as you implemented it, is the two-sided objective a weighted
sum of two separate losses with one scale, or two separate objectives with their own
scales? If it is a weighted sum, what weight makes the two terms contribute equally
given a 4.4e-5 gradient-scale difference, and did you measure the weight or choose it?

*Verifiable by:* the answer determines whether the gap needs an explicit normalisation
term or a loss weight. Either way it is a checkable claim about our own critic
implementation, and the numpy-only toy set is enough to test it.

---

### Q3 (to the `fromgoogle4` author) — about the warp-level coordination

Your agents coordinate inside a warp with `shfl.sync` and `vote.ballot.b32`, so no
thread writes to shared memory to see its neighbours' state, and the model is described
as 100,000+ agents on a 128 GB pool.

**Question:** with 32 threads per warp, what is the actual population of a warp in your
model — do all 32 lanes hold distinct agents that are spatial neighbours of each other?
And if so, how is that neighbour relationship maintained as agents move, given that a
warp's lanes are assigned by thread index and not by position?

*Verifiable by:* the answer decides whether this mechanism can be used at all for a
tile-scoring workload, where the lanes would hold tiles rather than agents. If the
lanes' contents are spatially arbitrary, the mechanism is a scheduling coincidence rather
than a design.

---

### Q4 (to the `liquid2` author) — about the hysteresis gate's boundaries

Your kernel implements the hysteresis boundary at sub-millisecond frequency with a
hardware clock counter tracking the duration of a confidence dip, and the intermediate
zone is given as 0.79 to 0.91.

**Question:** are those two numbers the same thresholds we should be using, and were
they measured or chosen? Specifically, what was the confidence distribution the bounds
were fitted to, and what happens to the gate when the confidence signal is bimodal
rather than unimodal — does the 0.79 to 0.91 zone become a place where the gate sits
forever?

*Verifiable by:* the numbers map directly onto our own `core/hysteresis` gate, whose
measured bounds we can compare against ours. We would also like to know whether the
dwell-time counter is a monotonic clock read or a cycle counter, because that decides
whether the behaviour survives a frequency change.

---

### Q5 (to the `new2` author) — about the mailbox's memory ordering

Your double-buffered mailbox is the shape we want: one writer on the ProArt, one reader
on the Thor, one atomic flag, two payload buffers, and the writer flips the flag with
an `Ordering::Release` store after an `_mm_sfence()`. The CPU half of the protocol is
right.

**Question:** the GPU half is not. In `blend_mailbox_reality_into_dream` the flag is
read as a plain dereference of `const unsigned int*` — not `volatile`, not an acquire
load, and with no `__threadfence()` between reading the flag and reading the payload
it selects. As written, the GPU has no ordering guarantee between the flag and the
buffer it points at, and the compiler is free to hoist the flag read out of the loop.
Was an acquire intended on the device side, and if so where did it go?

**Second, smaller question:** the writer chooses its target buffer by sampling
`active_buffer_index` and writing to the other one, and the prose in the same section
says the Thor's read kernel "swaps its input memory pointer" — which reads as though
the Thor also flips the flag. Which side actually owns the flip?

*Verifiable by:* a one-line `__threadfence()` after the flag load, and an assertion that
only one writer touches the flag. This is the mechanism we want for the render-buffer
to critic handoff inside the Thor, so its one ordering gap is worth resolving before
we adopt it.

---

### Q6 (to the `new2` author) — about the cell graph's cycle check

Your `link_dependency` has a comment saying that internal loop checking must happen
there, and the implementation does not do it.

**Question:** does a 1 -> 2 -> 1 link deadlock the BFS cascade, or does it double-fire
cell 2? And is the intended fix a cycle check at link time, or a visited set in the
cascade?

*Verifiable by:* a two-line test on our own cell graph, which has the same shape as our
stage cache's dirty set. The answer decides whether we need to check at insert time or
only at traversal time, which matters because our graph is updated during a night while
other jobs read it.

---

### Q7 (to the `idea5` author) — about the MIG fence

Your fence divides the Thor's 2,560 cores into a latency slice and a batch slice, and
you name the 12 SM / 1,536 CUDA core profile as the latency-sensitive instance.

**Question:** did you check the assignment against NVIDIA's own intended use of the two
instances? NVIDIA documents the 12 SM instance as the AI and graphics partition and the
8 SM instance as the one for robotics, control, perception and safety-critical work —
which would put the control and reflex workloads on the *smaller* instance, not the
larger one.

**And a second one, which is the one that decides whether any of this is reachable for
us:** is your MIG partition memory-partitioned as on datacenter GPUs, or SMs only?

*Verifiable by:* the NVIDIA documentation and our own board. Our answer from the
hardware side, which is the part you cannot know: our box's `nvidia-smi` has **no `mig`
subcommand at all**, and reports MIG mode `Disabled` rather than `[N/A]` — so the chip
has the feature and our tooling does not expose it. NVIDIA ships a JetPack 7.2 preview
for Jetson Thor, and enabling MIG changes the GPU's mode and needs the box idle and a
reset. Before any partition experiment, the first check is whether the preview packages
give us the commands; the answer decides whether this seed is a one-day experiment or a
planned window.

---

### Q8 (to the `idea4` author) — about the 629-byte delta

Your geometry delta channel is described as emitting a "tight binary patch" and the
number 629 bytes appears, on the analogy of our own table-move measurement.

**Question:** is 629 bytes an actual measurement of your glTF delta output, or an
analogy carried over from our table-move number? If it is a measurement: what scene
was it measured on, and what were the before and after states?

*Verifiable by:* we can measure our own delta on a real adjacent-room pair in an hour.
The question is whether the number we should compare against is a mesh delta at all,
which changes the whole transport design.

---

### Q9 (to the `liquid1` author) — about the JEV-27B decision head

Your decision model is described as a 40-million-parameter System-1 adapter on a frozen
backbone, with 45 ms latency, and you cite AutoTrust's JEV-27B-VL and GEV-26B-Decide.

**Question:** which number is which? The published JEV-27B card says 108.9 M trained
parameters on a frozen `Qwen3.8-27B` backbone, with a 24-slot head and a LoRA at r=16,
at 137 ms median per decision on a B200 and 4.2 ms batched at 128; the 45 ms figure
belongs to GEV-26B-Decide's System 1 on a different backbone, `gemma-4-26B-A4B-it`. Is
your "40 million" a third number, and if so for which model?

*Verifiable by:* the Hugging Face model cards for `autotrust/JEV-27B`,
`autotrust/JEV-27B-VL` and `autotrust/GEV-26B-Decide`. The answer decides whether the
head fits in a 128 GB box alongside the world engine, because 27B of backbone does not.

---

### Q10 (to the `idea3`/`idea4` author) — about the compile target

Your build files target `sm_100` and describe it as the Blackwell architecture.

**Question:** was this ever compiled and run, or only written? The Jetson Thor is
compute capability 11.0, `sm_110`; `sm_100` is Blackwell datacenter (B100, B200).
A binary built for `sm_100` will not run on the Thor.

**Second question, the same family:** your Green Context split assigns 70% of the
streaming multiprocessors to the render and 30% to the interactive path. Do the
proportions refer to SMs, to CUDA cores, or to the MIG instances? On Thor the two
things people call "the GPU partition" are different objects with different
granularity, and the MIG profile set on JetPack 7.2 is not the seven-instance
datacenter model.

*Verifiable by:* `nvidia-smi mig -lgip` and `cudaGetDeviceProperties` on the board, and
the CUDA target list, which puts Thor at `sm_110` and `sm_110a` and Blackwell
datacenter at `sm_100`/`sm_100a`. The answer determines whether the whole code path in
those chats is a starting point or a rewrite.


---

## Fact-check log

Names, models and repositories the sources cite, checked against the web and Hugging
Face on 2026-10-31. Nothing from the sources was run.

**Confirmed to exist and usable.**

| Cited | Checked | Result |
|---|---|---|
| `LiquidAI/d1-omni-600M` | HF API | Exists, `image-text-to-text`, 20,466 downloads |
| `LiquidAI/LFM3-1.7B` | HF API | Exists, 32,933 downloads, 256K context |
| `openai/gpt-oss-20b`, `openai/gpt-oss-120b` | HF API | Both exist; 6.1M and 2.6M downloads |
| `microsoft/TRELLIS.2-4B` | HF API | Exists, 2.8M downloads (the sources say "TRELLIS.2"; the repo is `TRELLIS.2-4B`) |
| `microsoft/TRELLIS-image-large` | HF API | Exists — the *older* TRELLIS, not TRELLIS.2 |
| `princeton-vl/infinigen` | GitHub | Exists (622 forks, 7.4k stars, BSD-3) |
| `SI-Thor/infinigen-thor` | GitHub | Exists — the Thor fork the sources cite |
| `superinstance/pincher` | GitHub | Exists |
| `asynchronics/nexosim`, `siemens/dtasm`, `ndebuhr/sim` | GitHub | All exist; cited as named dependencies for the simulation and WASM work |
| `maanHimself/OpenDLSS-NR`, `NODIX-TECH/DLSS-5-MANAGER` | GitHub | Exist; cited for the DLSS weight-extraction idea |
| `andyrewlee/awesome-system-one`, `Frank-ZY-Dou/awesome-jev` | GitHub | Exist; the sources' reading lists |
| `autotrust/JEV-27B`, `autotrust/JEV-27B-VL`, `autotrust/GEV-26B-Decide` | HF model cards | Exist, Apache-2.0. JEV-27B: frozen `Qwen3.8-27B` backbone, 108.9 M trained parameters (LoRA r=16 plus a 24-slot head), 137 ms median per decision on one B200, 4.2 ms batched at 128, 256K native context, about 65 KB of KV per token |
| Liquid LFM3-1.7B benchmarks | Vendor page and card | LFM3-1.7B scores 38.42 on WebArena-Verified against Qwen3.5-9B's 28.94, and 41.29 on AutomationBench against 15.10 — but 43.40 on SWE-bench Verified against 51.20, and 65.56 on RULER 128K against 87.11. The sources cite only the wins |
| γ-World (Gamma-World) | NVIDIA research page, arXiv 2605.28816 | Real. Simplex Rotary Agent Encoding, Sparse Hub Attention, 24 FPS rollouts, distilled block-causal student |
| ConsistWorld | Paper listing | Real. "Evidence Routing for Consistent Multi-Agent World Models" |
| WorldWeave | Paper listing | Real — and the sources call it **WorldWeaver**, which is the wrong name |
| NVIDIA NemoClaw | GitHub, docs.nvidia.com | Real; an OpenShell-backed reference stack for sandboxed agents |
| NVIDIA OSMO | NVIDIA docs | Real; orchestration for Physical AI with hardware-in-the-loop |
| TensorRT-LLM `agent_hierarchy`, `subagent_affinity_id` | TensorRT-LLM docs | Real scheduling parameters |
| Jetson AGX Thor / T5000 | NVIDIA datasheet DS-11945-001 v1.5 | 2070 FP4 TFLOPS (sparse), 1035 dense; 128 GB LPDDR5X; 2560 CUDA cores; 10 TPCs; Neoverse V3AE; MIG supported |
| MIG on Thor (JetPack 7.2) | NVIDIA forum, release notes, JetPack 7.2 docs | 20 SMs total; only `2g.0gb+gfx` (12 SM, 1,536 CUDA cores) plus `1g.0gb+me` (8 SM, 1,024 CUDA cores) is a supported pair. `nvidia-smi`'s SM column is wrong — known issue 6162096; `cudaGetDeviceProperties` reports 8 for the small instance. The 12 SM instance is the AI and graphics partition; the 8 SM one is for robotics, control, perception and safety-critical work |
| Thor compute capability | NVIDIA Jetson skill table; Modular target list | **11.0, `sm_110`** (also `sm_110a`). `sm_100`/`sm_100a` is Blackwell datacenter. Every `.target sm_100` in `liquid1`, `liquid2` and `fromgoogle4` is wrong for our box |

**Corrected in the seeds.**

- The sources say "a ~40-million-parameter System-1 adapter" (liquid1:275). The
  published figure for JEV-27B is 108.9 M trained parameters; the 40 M figure belongs to
  JEV-9B. The 45 ms latency belongs to GEV-26B-Decide's System 1 on a
  `gemma-4-26B-A4B-it` backbone, not to JEV-27B's 137 ms on a B200.
- The sources say "WorldWeaver" (idea5:58). The paper is **WorldWeave**.
- The sources attribute the 45 ms and the 40 M adapter to the same model; they are two
  different models on two different backbones.
- `sources-idea3.md` and `sources-idea4.md` disagree with each other on the compute
  capability (10.0 versus 11.0). The correct answer is 11.0, and `idea4` has it right.
- The library head start attributes the hysteresis barrier, the Brier score, the
  calibrated-confidence routing, the somatic reflex arc, myelination, retrograde
  signalling, trace-guided self-optimisation, viscous resonance and the attractor
  basins to `fromgoogle4`. They are in `liquid1`, `liquid2` and `new1`/`new2` instead.
  Every line reference in this bank was re-derived from the source text.

**Found in the material that landed while this was being written**, and folded into the
entries above:

| Fact | Source | Where it lands |
|---|---|---|
| The 600M reports 0.97 mean confidence at 0.415 accuracy; through the LFM2 formula 0.97 = (p_max − 0.2)/0.8, so p_max ≈ 0.976 | our own `docs/research/liquid-cascade-addendum.md` C3, C11 | B1, B2, B15 |
| The three d1 sizes return "confidence" by three different formulas — normalised margin (LFM2), raw top probability (LFM3), a third for `score` | `server-decision.cpp`, `get_decision_confidence()`, read in the same addendum | B1, B15 |
| d1-2B sets `no_batching` in llama.cpp's `fill_task()`, so the accuracy-winning cell cannot be served concurrently | same addendum, C2 | B3, E13 |
| The precision ladder is settled: precision changes no d1 accuracy (0 of 27 pairs significant) and 4-bit is not faster | same addendum | B4 — killed by fact |
| Native NVFP4 via cuBLASLt 13.4.1 on sm_110 runs 371-456 TFLOPS dense at K>=2048 (1.6-2.2× FP8, 2.5-4.3× BF16), at half FP8's joules per GEMM, TN layout only, no MXFP4 and no mixed operands from cuBLASLt; CUTLASS 4.4.1 on sm_110a runs MXFP8×MXFP4 mixed at 96 TFLOPS untuned | `docs/lab/exp-fp4-path.md` (measured 2026-10-31, box: 14 cores, 122.80 GiB unified, MAXN, driver 595.78, CUDA 13.2.86, cc 11.0, 20 SMs, load 5-18) | B4, E4, theme 1 |
| The FP4 tier is shape-gated: BF16 wins at K<=1280, and the practical rule is FP4 for the 5120-dim ff and attention-projection blocks and long-K scorers, BF16 for 320 and 640-dim blocks | same | E4 |
| FP4 library constraints, all measured: TN layout only, K a multiple of 64, M>=8 and a multiple of 8 (M=1 computes garbage), scale and packed-code buffers padded to 128-row tiles, `CUBLASLT_ORDER_ROW` on the FP4 D layout returns wrong values silently | same | E4 |
| QAT is mandatory for FP4 decision and policy models: PTQ flips about 29% of tile choices, QAT holds quality at 3.55x smaller weights | `docs/lab/exp-fp4-models.md` | E4 |
| The measured dense FP4 ceiling is 456 TFLOPS, 22% of the 2,070 sparse datasheet figure; schedule against 450, and only for K>=2048 | `docs/lab/exp-fp4-path.md` §7, `docs/lab/IDEAS.md` Part B | B4, E4 |
| TRELLIS fused FP8 measured 7-31% slower than BF16 and failed quality | `library-idea5.md` prompt | E4 |
| fromgoogle5's "Thor's entire 2,070 TFLOPS of FP4/FP8 compute" — 2,070 is the *sparse* FP4 figure; the measured dense ceiling is 456 TFLOPS, and it is an FP4 figure, not an FP8 one | `docs/lab/exp-fp4-path.md` §5.1 | G1, B4 |
| fromgoogle5's "100 Gbps network I/O (4x 25 GbE)" and "up to 20 camera feeds" / "ten 4K streams at 60Hz" — the silicon is real, the cage is not, and the devkit has no camera stack; the network is a purchase, not a dependency | `docs/lab/IDEAS.md` Part B, `docs/research/liquid-study.md` §H17 | G5, G6 |
| Our `nvidia-smi` has no `mig` subcommand and reports MIG `Disabled` (a chip without the feature reports `[N/A]`); JetPack 7.2.1 | builder-ide `docs/research/idea5.md`, `liquid-study.md` §H6 | F2, Q7 |
| d1-2B, d1-Omni-2B, d1-3B, d1-omni-600M are on Hugging Face; d1-ultra is API-only | HF API, Liquid docs | B3 |
| The d1 family is a single forward pass returning typed answers with probabilities and zero generated tokens; d1-3B runs at about 16 ms on a Jetson AGX Thor | `awesome-system-one` (cited in `sources-liquid1.md`), Liquid docs | B11 |
| `d1-omni-600M` can see images on the same `/v1/systemone` endpoint; the critic's defect classification is currently measured on a text proxy | addendum C5; `core/critic/CALIBRATION.md` | A7, A8 |
| A context snapshot (`--cache-ram N`, `--slot-save-path`) is a KV-and-recurrent-state blob, not an export of hidden activations | addendum C6, `server-context.cpp` | B21, B30 |
| The 600M's decision temperature is a per-question-type knob in the GGUF metadata (`lfm3.decision.temperature.choice = 1.3373984`), and is ignored entirely on the omni model for media questions | addendum C3, `get_temperature()`, `format_answer()` | B15 |
| The option set is a lever on a K-way choice question, and is the same idea as `core/tiles/door.py` in model terms | addendum C4 | D1, D3 |

**Out of scope, and why.** The `lib-*.md` SuperInstance repos and the
`library-si-constraints*.md` extractions of them landed in this directory while this was
being written. They are a separate brief's material — constraint theory, the beam-quilt
design study, the SuperInstance repo map — and not the `sources-*.md` chats this brief
names, so they are not seeded here and the bank stays inside the 60-120 range. They were
read for fact corrections, and two facts from them are folded in above (the native NVFP4
numbers and the MIG hedging). Their own clearest finding is worth recording here
because it generalises: reading the repos, the pattern is that the Thor changes the
constant for ideas that were throughput-bound and does nothing for ideas that were
correctness-bound — a consensus guarantee, a convergence rate or a parity claim is
whatever it is on any hardware.

**Could not be verified.**

- `qwen3.8-27b` is listed in the brief's Groq alias table as `qwen`. The HF model id
  `Qwen/Qwen3.8-27B` did not resolve, although `Qwen/Qwen3-8B` and `Qwen/Qwen3-32B` do,
  and the AutoTrust card names `Qwen/Qwen3.8-27B` as the JEV backbone. The alias is
  used by our own tooling, so it may be a Groq-side id rather than an HF one; we did not
  call it, because the brief says not to run their code.
- `nmd2k/research-daily-update` redirects (301); its contents were not inspected.
- "Liquid d1-3B" is cited in `liquid1:370` alongside a link to `d1-omni-600M`. The 600M
  checkpoint exists; the 3B checkpoint was not found under that name.
- The `LiquidCodec` "87× realtime" and "50 ms TTFT" figures are Liquid's own marketing
  numbers and were not independently confirmed.

---

## Groq cost log

All classification and second-opinion work went through `~/lm-ops/gq.py`. Every call's
tokens, latency and cost are in `_work/groq_log.json`.

| Purpose | Model | Calls | Cost |
|---|---|---|---|
| Whole-corpus classify, one shot (superseded) | `gpt-oss-20b` | 1 | $0.00069 |
| Bulk theme proposal, chunked (4 chunks of 30) | `gpt-oss-20b` | 4 | $0.00070 |
| Per-chunk assignment, first pass (unbalanced, superseded) | `gpt-oss-20b` | 8 | $0.00134 |
| Theme reconcile, first attempt (truncated at the token cap) | `gpt-oss-120b` | 1 | $0.00359 |
| Theme reconcile, retry with a larger budget | `gpt-oss-120b` | 1 | $0.00144 |
| Seed-to-theme assignment, chunked (8 chunks of 15) | `gpt-oss-120b` | 9 | $0.00349 |
| Seed-to-theme assignment, final pass (8 chunks of 15) | `gpt-oss-120b` | 8 | $0.00359 |
| Theme payoff ranking, first attempt (superseded) | `gpt-oss-120b` | 1 | $0.00066 |
| Theme payoff ranking, final | `gpt-oss-120b` | 1 | $0.00194 |
| Top-ten second opinion | `gpt-oss-120b` | 1 | $0.00303 |
| **Total** | | **35** | **$0.0210** |

Well under the $2 ceiling. Three findings worth recording for the next time.

gpt-oss-20b hallucinated seed IDs when asked to place 135 seeds at once — it returned
240 placements for 135 seeds and invented ids that do not exist (`C27` to `C40`, and
others). The assignment was redone in chunks of 15 against a closed id list, with the
ids validated in code and gaps retried. The chunked version still came back unbalanced
(one theme with 2 seeds, another with 27), so the final assignment was redone with
gpt-oss-120b on the same chunk size, which was balanced.

gpt-oss-120b's first reconcile pass hit the 5,000-token cap mid-JSON and had to be
reissued with a 9,000-token budget.

Two runs' cost lines were lost when their scripts crashed before writing the log, so
`_work/groq_log.json` was reconstructed from their stderr output and now accounts for
all 35 calls.

---

## Appendix: the hand-corrections to the machine's theme assignment

The theme assignment is the model's, with these changes applied after a second read.
Each line says why the model's placement was wrong.


- **A1** — From a generated mesh to a usable world -> Plausibility and consistency critic: pixel distillation is a critic finding, not a mesh-delivery step
- **A7** — Tile execution: what a tile may do and how it runs -> Plausibility and consistency critic: the perception round trip is a critic filter
- **A8** — Tile execution: what a tile may do and how it runs -> Plausibility and consistency critic: a shared perception/generation latent is a critic design
- **B17** — Cloud-local update loop -> First mile: a laptop that answers in a breath: an intent cache keyed by meaning is the first mile's cache
- **B19** — Confidence routing, escalation and reflex bands -> First mile: a laptop that answers in a breath: front desk / decision maker / back office is the first-mile role split
- **B20** — Confidence routing, escalation and reflex bands -> First mile: a laptop that answers in a breath: a voice latency-hiding device is a first-mile mechanism, not a routing rule
- **B21** — State, events and the shape of a night -> Confidence routing, escalation and reflex bands: a bounded state is a routing concern: it bounds what the router must read
- **B22** — State, events and the shape of a night -> One GPU, many jobs: the shared Thor: variable-rate execution is a scheduling property
- **B23** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: co-operating models on the GPU is a scheduling property
- **B25** — One GPU, many jobs: the shared Thor -> First mile: a laptop that answers in a breath: one backbone for the whole voice loop is a first-mile design
- **B27** — World generation as a constrained physics problem -> Plausibility and consistency critic: baking physics into weights is a critic-prior question
- **B29** — Cloud-local update loop -> First mile: a laptop that answers in a breath: structured state instead of pixels is a first-mile input decision
- **B3** — Confidence routing, escalation and reflex bands -> First mile: a laptop that answers in a breath: a resident always-on model with a wake condition is a first-mile tiering
- **B4** — not placed by the model -> One GPU, many jobs: the shared Thor: FP4 as a precision tier on the shared box belongs with the GPU-side work, and the chat's promotion mechanism is obsolete rather than live
- **B5** — not placed by the model -> Confidence routing, escalation and reflex bands: a structural check over a quantisation-noisy decision output is a routing-quality question
- **C10** — From a generated mesh to a usable world -> One GPU, many jobs: the shared Thor: an on-chip encoder is a GPU-scheduling idea
- **C13** — First mile: a laptop that answers in a breath -> State, events and the shape of a night: the manifest compiles to a mask the runtime loads: a state artefact
- **C14** — Cloud-local update loop -> First mile: a laptop that answers in a breath: the cloud-to-laptop parameter plane is the first mile's control path
- **C15** — Plausibility and consistency critic -> World generation as a constrained physics problem: agent personality is a world-generation property
- **C17** — Plausibility and consistency critic -> World generation as a constrained physics problem: the personality bit-fields are a world-generation property
- **C18** — World generation as a constrained physics problem -> Tile execution: what a tile may do and how it runs: the veto as an unrepresentable state is a tile guard
- **C19** — From a generated mesh to a usable world -> Tile execution: what a tile may do and how it runs: trace feedback into a compiler is a tile-execution idea
- **C2** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: zero-allocation loops are a GPU-scheduling constraint
- **C20** — State, events and the shape of a night -> Plausibility and consistency critic: forking worlds is the critic's search over candidates
- **C23** — State, events and the shape of a night -> Cloud-local update loop: batched telemetry upload is the cloud link
- **C3** — Cloud-local update loop -> One GPU, many jobs: the shared Thor: coherent UVM is a GPU fact, not an update loop
- **C4** — Cloud-local update loop -> One GPU, many jobs: the shared Thor: GDS is a GPU IO path
- **C5** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: warp-level coordination is a GPU-side mechanism
- **C6** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: atomic claims are a GPU-side mechanism
- **C8** — Tile execution: what a tile may do and how it runs -> State, events and the shape of a night: a fixed-width state record is a state-layout idea
- **C9** — Plausibility and consistency critic -> One GPU, many jobs: the shared Thor: a learned scorer is a GPU-acceleration idea
- **D1** — Confidence routing, escalation and reflex bands -> First mile: a laptop that answers in a breath: the retrieval front over cached intents is the first mile's fast path
- **D11** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: virtualised host primitives are a sandbox idea
- **D12** — One GPU, many jobs: the shared Thor -> Tile execution: what a tile may do and how it runs: the JIT of a validated trace is a tile-execution mechanism
- **D17** — One GPU, many jobs: the shared Thor -> Tile execution: what a tile may do and how it runs: the trampoline is part of the JIT story
- **D18** — Plausibility and consistency critic -> State, events and the shape of a night: damping the reality/dream blend is a night-loop stability concern
- **D2** — Cloud-local update loop -> Tile execution: what a tile may do and how it runs: a signed bundle is a tile artifact
- **D20** — World generation as a constrained physics problem -> Cloud-local update loop: a nightly fleet promotion is the update loop
- **D22** — World generation as a constrained physics problem -> Cloud-local update loop: editing an invariant is the update loop
- **D23** — Plausibility and consistency critic -> Tile execution: what a tile may do and how it runs: fuel is a sandbox budget, which is a tile-execution property
- **D24** — Cloud-local update loop -> Tile execution: what a tile may do and how it runs: memfd hot-swap is tile code replacement
- **D3** — World generation as a constrained physics problem -> Tile execution: what a tile may do and how it runs: the capability manifest is a tile guard
- **D30** — World generation as a constrained physics problem -> Tile execution: what a tile may do and how it runs: hot/cold tiering of reflexes is a tile-lifetime rule
- **D31** — State, events and the shape of a night -> Plausibility and consistency critic: multi-version world state is what makes consistency checkable
- **D33** — One GPU, many jobs: the shared Thor -> State, events and the shape of a night: self-routing memory topology is a state-structure idea
- **D4** — One GPU, many jobs: the shared Thor -> Tile execution: what a tile may do and how it runs: swappable traits are a tile-runtime idea
- **D40** — One GPU, many jobs: the shared Thor -> Tile execution: what a tile may do and how it runs: promoting a hot path to native code is a tile-execution idea
- **D6** — One GPU, many jobs: the shared Thor -> Cloud-local update loop: user-scoped promotion is a cloud-local promotion rule
- **D7** — Cloud-local update loop -> State, events and the shape of a night: the interruption token is the night's cancel path
- **D8** — Cloud-local update loop -> State, events and the shape of a night: fork, prune, commit is the shape of a night job
- **E10** — World generation as a constrained physics problem -> First mile: a laptop that answers in a breath: the codebase as a room is an interface idea
- **E11** — Confidence routing, escalation and reflex bands -> First mile: a laptop that answers in a breath: the fast-UI/slow-background split is the first-mile latency budget
- **E16** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: camera path: already a hardware trap
- **E17** — Cloud-local update loop -> One GPU, many jobs: the shared Thor: the inter-chip link: already a hardware trap
- **E19** — Confidence routing, escalation and reflex bands -> One GPU, many jobs: the shared Thor: static KV pools are a memory-management idea for the shared box
- **E2** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: kernel fusion is a GPU execution constraint
- **E23** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: already built
- **E29** — World generation as a constrained physics problem -> State, events and the shape of a night: anticipatory generation is a state-graph idea
- **E3** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: already built
- **E32** — Tile execution: what a tile may do and how it runs -> One GPU, many jobs: the shared Thor: fixed buffer blocks are a GPU memory constraint
- **E34** — State, events and the shape of a night -> From a generated mesh to a usable world: already built
- **E4** — From a generated mesh to a usable world -> One GPU, many jobs: the shared Thor: the FP8/FP4 precision question is a GPU-path question
- **E7** — World generation as a constrained physics problem -> From a generated mesh to a usable world: the draft/generative split is a render-pipeline split
- **F2** — Confidence routing, escalation and reflex bands -> One GPU, many jobs: the shared Thor: MIG is a GPU-lane fence
- **F3** — Confidence routing, escalation and reflex bands -> One GPU, many jobs: the shared Thor: hierarchy is a scheduling tag
- **F4** — Plausibility and consistency critic -> State, events and the shape of a night: the committed history is a state store
- **F7** — Confidence routing, escalation and reflex bands -> One GPU, many jobs: the shared Thor: per-agent budgets are a scheduling property
- **F8** — Confidence routing, escalation and reflex bands -> One GPU, many jobs: the shared Thor: the synthesis spans themes
- **G1** — not placed by the model -> State, events and the shape of a night: a ghost preview streamed to the client is a state-and-delivery split, and the preview is the cheap half of the world's data
- **G2** — not placed by the model -> State, events and the shape of a night: the day's edits serialized into the night's graph is the shape of a night
- **G3** — not placed by the model -> State, events and the shape of a night: the morning reveal is what makes a night's output legible
- **G4** — not placed by the model -> World generation as a constrained physics problem: a measured environment as a constraint input belongs with constrained world generation
- **G5** — not placed by the model -> World generation as a constrained physics problem: a motion field as a deformation input is a constraint on generation
- **G6** — not placed by the model -> State, events and the shape of a night: the laptop-as-window split is a state-placement decision

Everything else is the machine's placement, unchanged.

## Appendix: concepts that had no kernel, and why they are still here

A short list, so the next reader does not spend time on them again. These are the
passages where the source gives a metaphor with no mechanism behind it: the viscous,
wave, crystal-lattice, superfluid, soliton and living-tissue descriptions
(`new1.md`, `sources-new1.md:801`, `:849`, `:921`, `:957`); the growth cones
(`sources-new1.md:1335`); the liquid attractor basins (`:575`); the symmetric
bureaucracy and organic expressionism (`:83`); the personality bit-fields (`:655`);
the axiomatic veto as geometry (`:526`); and the crystalline phase transition as
hysteresis memory (`:849`), which is the one that most deserves a second look, because
the mechanical version — the hysteresis gate — already exists and is measured.

They are recorded rather than deleted because the brief asked for every distinct
concept, and because a metaphor with no mechanism is a signal that something is wanted
and nobody has said what. The one place that is worth a little money is the trio of
named self-tuning failure modes in `sources-new2.md:1964`: resonant catastrophe,
unattenuated telemetry-to-JIT loops, and stochastic dampening derivatives. Those are
not metaphors; they are three names for three ways a self-tuning loop goes wrong, and
writing down what each one looks like in a log would be a small piece of work with a
clear payoff.
