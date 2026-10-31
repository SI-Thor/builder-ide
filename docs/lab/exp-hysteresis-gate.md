# EXP — the hysteresis gate: a single threshold flickers, and the dwell is what stops it

**Date:** 2026-10-31
**Verdict: A SIGNAL THAT WANDERS ACROSS A THRESHOLD PRODUCES 56 STATE
CHANGES AND 55 FLICKERS IN TWENTY SECONDS, AND EVERY ONE OF THEM IS A FACT
WRITTEN TO THE LOG. THE SPLIT THRESHOLDS HOLD THE STATE STILL ON THAT
TRACE, AND THE DWELL IS WHAT FILTERS THE SPIKES — AT A LATENCY THAT IS
MEASURED, NOT ARGUED.**

---

## 1. The idea

The core has continuous confidences and discrete states side by side, and
it converts between them: a builder's confidence in a claim, a root's
liveness, a tile's standing. Every conversion is a **threshold**.

A threshold on a noisy signal flickers. The signal dips a hair below the
line, the state flips, the signal comes back, the state flips again. Each
flip is a fact in the log: a tile retired and un-retired, a claim spoken
and withdrawn, a root attested and un-attested.

The fix is two numbers and a clock: **split thresholds** (an enter and an
exit threshold per state, with the band between them) and a **minimum
dwell time** (a state change has to want to happen for a while before it
happens).

## 2. The hypothesis

> Split thresholds hold the state when the signal wanders inside the band,
> the dwell filters the spikes, and the price — the latency — is
> measurable and worth paying only where it buys something.

## 3. The setup

- `core/hysteresis/gate.py` — the gate: the levels, the bands, the dwell,
  the step. No dependency beyond the standard library.
- `core/hysteresis/metrics.py` — the measurement: the flicker a gate
  removes and the latency it adds.
- `tests/test_hysteresis.py` — 13 tests, no fixtures, no network.
- `docs/lab/hysteresis-scripts/measure_hysteresis.py` — prints every
  number below.

**The control** is the same gate with the band collapsed to a point: one
threshold per level. That is what the core does today, and the only
difference between the two is the width of the band.

| | |
|---|---|
| Machine | **the builder-ide sandbox** — x86_64 Linux, Python 3.12.14, pytest 9.2.0 |
| **Not** | the Thor: the gate is pure logic and the standard library |
| Levels | `dead` (enter 0.00), `unknown` (enter 0.40, exit 0.25), `alive` (enter 0.75, exit 0.60) |
| Trace 1 ("wobble") | 0.75 + 0.05·sin(2πt/0.7), 20 s at 0.1 s — wanders across the alive threshold |
| Trace 2 ("spikes") | mostly 0.2, with spikes to 0.9 of 0.3 s, 1.5 s, 3.0 s and 0.6 s |
| Flicker window | 1.0 s — a change reversed inside it is a flicker |

## 4. The numbers

### 4.1 The control flickers; the split thresholds hold

On the wobble trace, the signal crosses the alive threshold twice every
0.7 seconds:

| | changes | flickers |
|---|---|---|
| **single threshold (the control)** | **56** | **55** |
| **split thresholds** | **0** | **0** |

Fifty-six state changes in twenty seconds, fifty-five of them reversed
inside a second: fifty-five facts in the log that mean nothing. The
signal's lowest value is 0.70 and the alive band's exit threshold is
0.60, so with split thresholds the state never leaves `alive` at all.

### 4.2 The split thresholds alone are not enough

On the spike trace — where the signal goes all the way up and all the way
down, crossing both bands — the split thresholds change **nothing**:

| | changes | flickers |
|---|---|---|
| single threshold | 8 | 2 |
| split thresholds, no dwell | 8 | 2 |

**A band only helps near the threshold.** A signal that crosses the whole
range crosses every band, and there the only thing that filters it is the
dwell.

### 4.3 The dwell filters the spikes, and the latency is the price

The same spike trace, with the dwell turned up:

| dwell | changes | flickers | mean latency | worst |
|---|---|---|---|---|
| 0.00 s | 8 | 2 | 0.000 s | 0.000 s |
| 0.25 s | 6 | 1 | 0.300 s | 0.300 s |
| 0.50 s | 6 | 1 | 0.567 s | 0.600 s |
| **1.00 s** | **4** | **0** | 1.100 s | 1.100 s |
| 2.00 s | 2 | 0 | 2.050 s | 2.100 s |
| 5.00 s | 0 | 0 | — | — |

Three measured facts, and the third is the one to remember:

1. **The dwell is what removes the flicker**, and the removal is not
   gradual: at 0.5 s one flicker is left, at 1.0 s none are. The spike
   that survives a half-second dwell is 0.6 s wide — **a dwell shorterens
   the excursion; it does not remove the flicker.**
2. **The latency is the dwell**, plus one sampling interval. A one-second
   dwell costs 1.100 s of latency on a clean signal, because the state
   has to wait for the whole dwell after the signal changed its mind.
3. **A dwell longer than the signal's commitment loses the information.**
   At 5.0 s the state never moves at all: the spikes are 0.3 s to 3.0 s
   wide, and none of them is ever held long enough. A gate that is too
   slow is a gate that never speaks, and it looks exactly like a gate that
   has nothing to say.

### 4.4 A clean signal, and what the dwell costs it

A signal that steps up at t=5, down to the middle at t=12, and down again
at t=16:

| dwell | changes | mean latency | worst |
|---|---|---|---|
| 0.00 s | 3 | 0.000 s | 0.000 s |
| 1.00 s | 3 | 1.067 s | 1.100 s |
| 4.00 s | **1** | 4.100 s | 4.100 s |

At four seconds the dwell is longer than the middle state lasted, so the
state **never reaches `unknown`** — it is still `alive` when the signal
says `dead`, and the pending target resets when the signal moves on. The
state machine is right; the information is gone.

### 4.5 The dwell can be asymmetric

`dwell_up=4.0, dwell_down=0.0` on the same signal:

* the signal steps up at t=5.0; the state moves at **t=9.2**;
* the signal steps down at t=16.0; the state is dead by **t=16.1**.

A root that has just been attested alive is not dropped by a dip, and a
root that has just been found dead does not wait to say so.

## 5. The failure this experiment caught

The first version of the dwell **reset the pending clock only when the
target changed**, and the test that caught it was the "the dwell has to be
served by the same target" one — a signal that keeps changing its mind
must not accumulate dwell time towards a target it has already abandoned.

A second, smaller one: the trade-off table was first measured on a trace
whose spikes were 0.5 s apart, where the *pending* target of one spike
overwrote the pending target of the next and the counts were not the ones
the trace suggested. The traces are now separated, so each spike is a
clean decision for the dwell.

## 6. What this does not say

- **The traces are synthetic.** A real confidence signal is not a
  sinusoid, and the right dwell depends on how noisy the real signal is
  and how long its excursions last. The mechanism is measured; the number
  to put in it is the box's to choose.
- **Nothing is wired up.** This branch is the mechanism and its
  measurement. The three call sites are named — the WHY kernel's inferred
  standing, a tile's standing near the retirement line, the vocabulary's
  confidence level — and none of them is changed here.
- **The flicker window is a parameter** (1.0 s here). A change reversed
  inside it is a flicker; one reversed later is a real excursion. The
  window is a judgement about how long a state was going to last anyway.

## 7. Reproducing it

```bash
cd ~/lm-wt/tiles
.venv/bin/python -m pytest -q tests/test_hysteresis.py        # 13 tests
PYTHONPATH=. .venv/bin/python docs/lab/hysteresis-scripts/measure_hysteresis.py
```

Every number in §4 comes out of that script.
