# EXP — the hysteresis gate on real d1 traces: `core/hysteresis` gets its first caller

**Date:** 2026-10-31 (the hysteresis-d1 seat; CPU-only, no GPU, no server —
the traces were recorded on the Thor by the liquid study's §4.3)
**Verdict: THE FLICKER THE GATE EXISTS FOR IS REAL ON REAL TRACES — AT THE
TASK'S CALIBRATED τ THE RAW THRESHOLD FLICKERS 66 TIMES IN 240 TICKS ON THE
2B RECORDING, AND THE ADOPTED SHAPE (BAND 0.15, DWELL_UP 2, DWELL_DOWN 0)
LEAVES ONE, WITH THE RAW GATE'S CATCH AND AGREEMENT KEPT AND BOTH LATENCY
BOUNDS MET. E1'S τ = 0.5 NEVER FIRES ON THE 2B'S CONFIDENCE AT ALL — A GATE
AT A τ THE SIGNAL NEVER CROSSES IS NOT A GATE — AND THE CHOICE RULE HAD TO
BE GUARDED TWICE: FLICKER-MINIMISATION ELECTS THE SILENT GATE UNLESS τ IS
THE TASK'S AND THE SHAPE MUST KEEP THE RAW GATE'S WORK.**

---

## 1. The idea

Liquid-study Part 3, item 3: `core/hysteresis` is a mechanism built, tested
(13 tests) and measured (flicker removed, latency added — on synthetic
traces) with three call sites named in its README and **no caller**. E1
supplied the signal worth gating — the d1-2B's confidence, a per-tick
continuous reading whose raw threshold "would flicker straight into the
ledger" — and this experiment replays the study's own recorded traces
through the gate, sweeps (upper, lower, dwell), picks a configuration by a
stated rule, and wires it where the judgment drives a state that persists
across ticks: the escalation trigger of `core/judge`'s ladder.

## 2. The hypothesis

> The 2B's confidence is tick-noisy near a threshold, so a raw τ gate on it
> writes flicker facts to the log; a band and a dwell remove those flickers
> at a latency the loop can pay, without losing the gate's job — catching
> the judgments not worth acting on. The configuration is a measurement,
> not a taste.

## 3. The traces, and the setup

**The data.** `.traces/exp_c_trace_d1-2B.json` and
`.traces/exp_c_trace_d1-3B.json` — the liquid study §4.3 run on the Thor
(2026-10-31, one llama-server per model, box state in
`exp_c_hysteresis_*.json` beside them): **240 recorded decisions each**
(6 trials × 40 steps of the five-way sea-state task), each with the full
probability vector, the model's confidence, the wall time, and the ground
truth the study recorded (`truth`, the true condition; `shown`, what the
state presented — with probability 0.35 the decoy). Nothing here touches
the GPU; the whole experiment is a replay.

**The signal.** The recorded confidence column. The two models' columns are
*not the same scale* (L7's warning, now visible in behaviour): the 2B
(`lfm3-d1`) reports `max(probs)` — 0.522–0.997, p50 0.717; the 3B
(`lfm2-d1`) reports a normalised margin — 0.437–0.975, p50 0.748.

**The clock is the tick.** One tick, one decision; the gate steps
`(confidence, t)` with `t` the tick index, and the dwell comes out in
ticks — ≈ 32.2 ms of recorded decision time per tick on the 2B, ≈ 50.7 ms
on the 3B. A gate without the caller's clock cannot replay; the tick is
the caller's clock here, as it is in the loop this gate is for.

**The subject.** The escalation standing of the judge's first rung: `act`
on this tick's judgment, or `escalate` it. The gate resets at each trial
boundary (a fresh subject per recording — each trial's first ticks count
one standing change, the cold start earning `act`; the flicker count is
immune to it, and the cold start is part of what the gate measures).

**The metrics**, pooled over the six trials (480 ticks per model across
both traces' sweeps):

* **changes / flickers** — standing changes per 240 ticks; a change
  reversed within 2 ticks is a flicker (the `core.hysteresis.metrics`
  definition, in ticks);
* **drop / act latency** — ticks from a genuine crossing to the standing
  following, per direction (act→escalate is the drop);
* **agreement with the recorded ground truth, two ways** — against what
  the model was **shown** (the 32-of-240 misreadings on the 2B: the
  E1-style calibration question — is the confidence a usable gate signal?)
  and against `truth` (the study's own accuracy reading, which the
  perceptual noise moves: the model follows the decoy *confidently*, so no
  threshold on its confidence can catch those — §4.3 said so, and the
  traces confirm it). `catch` = wrong judgments escalated / all wrong;
  `tax` = right judgments escalated / all right.

**The controls.** Two, asserted identical in the harness: `core.judge`'s
current `ConfidencePolicy` applied per tick, and the single threshold (the
same gate with the band collapsed and no dwell). **They are the same
numbers — the current policy is a single threshold; that is the point.**

## 4. The numbers

### 4.1 The flicker is real, and E1's τ does not transfer

| raw τ gate | 2B changes | 2B flickers | 2B catch/shown | 3B changes | 3B flickers | 3B catch/shown |
|---|---|---|---|---|---|---|
| τ = 0.5 (E1's default) | 6 | **0 — never fires** | — | 64 | **41** | 0.04 |
| τ = 0.7 | 97 | **66** | 0.50 | 88 | **54** | 0.47 |
| τ = 0.8 | 94 | 63 | 1.00 | 84 | 56 | 1.00 |

Two facts, one per model. On the **2B**, the recorded confidence never
dips below 0.522: at E1's τ the gate is silent — `StandingGate`'s
shipped-until-now defaults (band 0.1, no dwell) are inert on this task's
trace, act on everything, catch nothing. On the **3B**, whose confidence
is the margin scale, τ = 0.5 flickers **41 times in 240 ticks** — every
one a fact written, withdrawn, written again. E1's number is a property of
T1's calibration, not a portable constant; the judge note's own stance
("the default stays 0.5 until a task's own calibration") is what the
traces confirm, and the per-task calibration is now a table lookup
(`results/hysteresis-d1-sweep.json` holds the full grid).

### 4.2 Where the calibration τ sits, and what no threshold can do

On the 2B, 32 of 240 ticks misread what they were shown. The confidence
orders them: every misreading sits below τ = 0.8 — but the raw gate there
acts on only 30 % of ticks, and **loses agreement to acting on
everything** (0.433 vs 0.867 all-act). At τ = 0.7: half the misreadings
caught, at 59 % act rate. The escalation standing must leave the rung
acting on most ticks — it holds the state through wobble, it is not a
cascade's drowning valve — so **τ\***, the traces' calibrated τ, is the
best-catch τ subject to acting on ≥ half the ticks: **0.7 on both
traces**. And the honest limit, stated once: on this task *no* confidence
threshold beats acting on everything — the perceptually-noised ticks are
confidently held. What the gate is for here is the flicker, not the noise.

### 4.3 The sweep at τ\* = 0.7 — the 2B (the rung the ladder runs)

Bounds of the rule: drop latency ≤ 2 ticks, act latency ≤ 3 ticks; the
shape must keep the raw gate's catch and agreement at the same τ.

| shape (band, dwell_up, dwell_down) | changes | flickers | act | catch/shown | agree/shown | drop max | act max |
|---|---|---|---|---|---|---|---|
| 0.0, 0, 0 — **the raw gate / current policy** | 97 | **66** | 0.592 | 0.500 | 0.592 | 0 | 0 |
| 0.10, 0, 0 — **shipped-until-now default** | 33 | 13 | 0.817 | **0.375 ↓** | 0.783 | 0 | 0 |
| 0.20, 0, 0 | 6 | **0** | 0.938 | **0.188 ↓** | 0.854 | 0 | 0 |
| 0.0, 2, 2 | 20 | 0 | 0.608 | **0.469 ↓** | 0.600 | 2 | 2 |
| 0.10, 2, 2 | 7 | 0 | 0.738 | **0.281 ↓** | 0.679 | 2 | 2 |
| 0.05, 2, 0 | 33 | 6 | 0.271 | 0.688 | **0.321 ↓** | 0 | 2 |
| **0.15, 2, 0 — adopted** | **19** | **1** | 0.592 | **0.562 ↑** | **0.608 ↑** | **0** | **2** |

Read the table as three measured sentences:

1. **The band alone is not enough and can be treacherous.** Band 0.1 with
   no dwell halves the flickers (66 → 13) and *loses the catch*
   (0.500 → 0.375): it holds the state through dips that carried
   misreadings. Band 0.2 wins flickers into silence and loses more.
2. **The dwell alone trades catch for latency.** Symmetric dwell 2/2 at
   band 0 kills every flicker but holds through short real drops — catch
   0.469, both latencies at the bound.
3. **The adopted shape is the one that keeps the work.** Band 0.15 with
   `dwell_up` 2 and `dwell_down` 0: the band holds the shallow wobble
   (27 of the 98 below-τ ticks ever fall as far as the exit line), the
   `dwell_up` earns `act` and filters the recovery flicker, and a real
   drop commits on its first below-exit reading. **66 flickers → 1, catch
   up (0.500 → 0.562), agreement up (0.592 → 0.608), agreement against
   `truth` up (0.317 → 0.525), drop latency 0, act latency ≤ 2 ticks.** It
   is the *only* shape in the grid that kills the flicker while keeping
   the raw gate's catch; the tie-break (fewest transitions, then widest
   band) picks 0.15 over the identical-numbered 0.10.

### 4.4 The 3B beside it — the same experiment, a different dip shape

At its τ\* = 0.7 the 3B's eligible set is one shape: band 0, dwell 2/2
(its dips are deeper — p5 0.44 against a 0.55 exit — so a wide band holds
through misreadings and fails the keep-work constraint; only the down-dwell
filters them). 54 flickers → **0**, catch 0.475 → 0.566, agreement
0.504 → 0.538, both latencies exactly 2 ticks. The 2B and the 3B disagree
on the shape because their noise shapes differ — **the configuration is a
parameter, and the adopted default is the rung-0 model's** (the 2B, per E1:
"the local rung of any cascade is the 2B").

## 5. The choice, and why

The rule, as implemented (the brief's "fewest flickers subject to a latency
bound", made honest by two guards the sweep itself forced):

> **τ is not the sweep's to choose.** Minimising flickers over τ elects
> the silent gate — measured here: band 0.2 at τ = 0.6 "wins" with zero
> flickers because the standing never leaves `act`. τ\* is the task's
> calibration: best catch of the model's misreadings subject to the rung
> still acting on ≥ half the ticks.
>
> **The shape must keep the raw gate's work.** At τ\*: fewest flickers
> subject to drop ≤ 2 ticks, act ≤ 3 ticks, and catch and agreement no
> worse than the raw gate's at the same τ; ties by fewer transitions,
> then least mean latency, then widest band.

A gate that never speaks looks exactly like a gate with nothing to say
(exp-hysteresis-gate §4.3); both guards are that sentence, made
mechanical.

**What ships:** `StandingConfig` = τ `DEFAULT_TAU` (E1's 0.5, until a
task's own calibration names another — the band and dwells are about the
signal's noise, τ is about the task), **band 0.15, dwell_up 2,
dwell_down 0**, the dwells in ticks of the caller's clock. It is the
default of `StandingGate` and the carrier of the wiring below; a caller on
the 3B or on a seconds clock passes its own, because that is what a
parameter with a default is for.

## 6. The wiring — the escalation trigger of the ladder

`Judge(standing=StandingGate())` in `core/judge`: the first rung's
act-or-escalate decision is the standing's word per question id (the
subject whose state persists across ticks), not the per-tick τ
comparison; later rungs stay gated by the policy's τ. The clock is
explicit — `judge(..., now=tick)` is required once a standing is wired,
because a standing without the caller's clock cannot replay. The standing's
word rides on every `judge.verdict` row and on `JudgeAnswer.standing_words`,
and `surfaced` follows the standing where it governed — a log that needs a
computation to say what governed is a log that lies by omission.

The brief's two behaviours, both through the ladder and both in the suite
(`tests/judge/test_standing_escalation.py`):

* **a wandering confidence no longer flips the standing state** — a
  confidence series that warms into `act` and then crosses τ every other
  tick (never below the exit): the raw gate flapped to the cloud rung on
  every sub-τ tick; the standing escalates only through its warm-up, then
  holds and the ladder never flaps;
* **a real drop still escalates within the latency bound** — after three
  confident ticks a sustained fall below the exit line reaches the next
  rung on the first below-exit reading with the adopted `dwell_down = 0`,
  and a configured 2-tick dwell still lands inside the bound (committed at
  latency 2.0, not past it).

And one rule the wiring needed that the brief's two tests flushed out: a
judgment with **no confidence** never passes and leaves the standing
untouched — a continuous gate takes no reading from a null.

## 7. What this does not say

- **One task, one seed family, 240 ticks per model.** The sea-state task
  is the study's §4.3 rig; the numbers are properties of these traces.
  What transfers is the method: replay the task's own trace, calibrate τ,
  then pick the shape under the guarded rule. The harness is the tool.
- **No threshold on this task's confidence beats acting on everything**
  (§4.2). The standing earns its keep where the signal is tick-noisy near
  its floor — here that is the 3B at E1's τ, and the 2B at its own
  calibration τ. A task whose confidence is quiet at its τ (the 2B at
  0.5) needs no gate and is harmed by none: the adopted shape is inert
  there, which the sweep also shows.
- **The kill criterion did not fire.** Part 3 item 3's kill was "the
  band+dwell removes no flaps on real traces" — it removed 65 of 66 on
  the 2B and all 54 on the 3B at their calibrated τ.
- **`core/hysteresis` itself is unchanged.** The mechanism was built and
  measured; this seat gave it its first caller, a measured default, and
  the record of both.

## 8. Reproducing it

```bash
cd ~/lm-wt/hysteresis-d1          # this worktree
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# the sweep: every number in §4 comes out of this, and the full grid
# (both models, every τ × band × dwell) lands in
# docs/lab/hysteresis-scripts/results/hysteresis-d1-sweep.json
PYTHONPATH=. .venv/bin/python docs/lab/hysteresis-scripts/replay_d1_traces.py

# the wiring and the adopted default
.venv/bin/python -m pytest -q tests/judge/test_gate.py \
                             tests/judge/test_standing_escalation.py
.venv/bin/python -m pytest -q tests/test_hysteresis.py tests/judge   # 90 tests
```

The traces are `.traces/exp_c_trace_*.json` (gitignored — the study's
recorded output, copied from `docs/research/liquid-study-scripts`' results;
the sweep JSON committed beside the harness *is* committed).
