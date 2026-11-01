# `judge-reversed-scripts` — the replay behind §7 of the calibration note

The scripts that produced
[`docs/lab/exp-judge-calibration.md`](../exp-judge-calibration.md) §7, "The
reversed replay": the 240 recorded sea-state steps asked again with **the two
named conditions swapped**, for d1-2B and d1-3B, and the five numbers the
brief asked for.

Two scripts, because there are two jobs:

| script | what it does | needs |
|---|---|---|
| `replay_reversed.py` | asks the 240 steps in both orders on the Thor and writes the argmax and the full probability vector of every reply | a served d1 model, a GPU |
| `measure_reversed.py` | reads those replies and the October trace and computes the positional share, the disagreement set, the two averages, the budgets and the latency | nothing but the two files |

`measure_reversed.py` makes **no model call** — the same split as
[`judge-calibration-scripts/`](../judge-calibration-scripts/), which replays
recorded vectors and never touches a server.

## Running it

On the Thor, with a d1 model served (`thor-admit` holds the lease; the box is
shared, so the run goes under one):

```bash
# the replay (240 steps x 2 orders, plus the latency probe)
python3 docs/lab/judge-reversed-scripts/replay_reversed.py \
  --model d1-2B --port 8094 --out docs/lab/judge-reversed-scripts/results/replay-d1-2B.json
python3 docs/lab/judge-reversed-scripts/replay_reversed.py \
  --model d1-3B --port 8320 --out docs/lab/judge-reversed-scripts/results/replay-d1-3B.json

# the analysis (CPU, no model)
python3 docs/lab/judge-reversed-scripts/measure_reversed.py
```

The analysis writes
`docs/lab/judge-reversed-scripts/results/reversed-measurement.json`.

Options: `--trace` (the October trace to replay), `--latency-steps` (how many
steps the latency probe measures, 120 by default, 0 disables it), `--timeout`,
`--out`, and for the analysis `--replay` and `--trace-dir`.

## What it reads

| file | from |
|---|---|
| `exp_c_trace_d1-2B.json`, `exp_c_trace_d1-3B.json` | `/home/caseydigennaro/lm-wt/liquid-study/results/` (the October recording) |

and one module, for its semantics rather than its data:

| module | why |
|---|---|
| [`core/judge/calibration.py`](../../../core/judge/calibration.py) | the τ semantics (the gate escalates when the confidence is **below** τ), the canonical confidence (`top_probability`), the AUC's tie rule, and the sweep and the bootstrap the analysis is pinned against |

## Three things the replay has to get right

**The swap is a swap of the two named conditions and nothing else.** A step's
state text is two sentences, one per named condition; the reversed prompt is
those two sentences the other way round. The question, its five criteria and
their letters, the ground truth (always the true condition, never the shown
one) and the call's shape are untouched. On the 43 steps where the prompt
named the *same* condition twice the two texts are byte-identical, so the
reversal is a no-op there — and those steps double as the run's determinism
control.

**The pair's order alternates.** Half the steps ask the original prompt first
and half ask the reversed one first, so "which condition the prompt named
first" and "which call came first in the pair" are not the same variable.

**The judgment is one judgment per step.** Every protocol in the analysis
gates the *original* order's answer: "right" means that answer named the true
condition. The reversed answer is not a second judgment to be scored; it is
the second reading the gate uses. That keeps the catch and the tax comparable
with the note's.

## What it does not do

It does not decide the protocol. It measures: what the reversed answers are,
how often they disagree with the original ones, what the two averages carry,
what the catch rate is inside a sane escalation budget, and what the two calls
cost. The recommendation that follows from those numbers is in the note.
