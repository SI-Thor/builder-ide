# `core/hysteresis` — a continuous signal, a discrete state, and no flicker

## What it is

The core has continuous confidences and discrete states side by side, and
it keeps converting between them: a builder's confidence in a claim, a
root's liveness, a tile's standing. Every one of those conversions is a
**threshold**, and a threshold on a noisy signal **flickers** — the signal
dips a hair below the line, the state flips, the signal comes back, the
state flips again. Each flip is a fact written to the log: a tile retired
and un-retired, a claim spoken and withdrawn.

This package is the gate that stops it.

## What it owns

| module | what it owns |
|---|---|
| `gate.py` | the gate: the levels, their bands, the dwell, and the step |
| `metrics.py` | the measurement: the flicker a gate removes and the latency it adds |

## The two numbers, and the clock

1. **Split thresholds.** Each level has an *enter* threshold and an *exit*
   threshold, and the gap between them is the state's **band**. To move up
   into a state the signal has to reach its enter threshold; to move down
   out of it, the signal has to fall below its exit threshold. A signal
   that wanders inside a band does not move the state at all.
2. **A minimum dwell time.** Even a split threshold flips if the signal
   crosses the band, wanders back, and crosses again. So a state change
   has to *want* to happen for a while before it happens. The cost is
   latency, and the cost is measured rather than argued about.

The dwell can be **asymmetric** — `dwell_up` and `dwell_down` are separate
— because a liveness signal should not be dropped by a momentary dip, and
should not be held past the point where it is clearly gone.

**The clock is the caller's.** The gate takes `(value, now)` and keeps no
time of its own, so a trace replays to the same answer.

## What it refuses, and what it reports

* a **pending** state is not a state: the gate reports the target
  separately, and the caller decides what a pending state means;
* the dwell has to be **served by the same target** — a target that
  changes resets the clock, because a signal that keeps changing its mind
  has not committed to anything;
* a dwell **longer than the signal's commitment loses the information**:
  measured, a four-second dwell on a signal that changes every few seconds
  never moves the state at all.

## Running it

```bash
.venv/bin/python -m pytest -q tests/test_hysteresis.py   # 13 tests
```

The measured numbers, the control, and the trade-off table are in
[`docs/lab/exp-hysteresis-gate.md`](../../docs/lab/exp-hysteresis-gate.md).

## How it connects to the core

This package is **the mechanism, not a policy**: the levels, their bands,
and the clock. What a level means belongs to the caller.

* **the WHY kernel** — a root's standing (`alive` / `unknown` / `dead`)
  from a continuous confidence. The kernel's own rule stands: liveness is
  external truth recorded in `att.txt`, never computed — this gate is for
  the *inferred* standing, which the kernel already treats as a candidate.
* **the tiles** — a tile's standing (`active` / `retired`) when the win
  rate sits near the retirement line. A tile that flaps is a tile that
  gets retired and un-retired every night.
* **the vocabulary gate** — a confidence level (`high` / `medium` / `low`)
  from a hit ratio.

None of those is wired up here: the module is measured and tested, and
the three call sites are named so the next seat knows where it goes.
