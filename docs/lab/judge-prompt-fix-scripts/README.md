# `judge-prompt-fix-scripts` — the fresh recording behind §8 of the calibration note

The scripts that produced
[`docs/lab/exp-judge-calibration.md`](../exp-judge-calibration.md) §8, "The
prompt fix": the same 240 recorded sea-state steps asked again under three
arms — the recording's own text, and the fixed pair (the true condition and
the decoy) in `core/judge/ordering.py`'s two neutral orders — for d1-2B and
d1-3B, and the numbers the brief asked for.

Two scripts, the same split as
[`judge-calibration-scripts/`](../judge-calibration-scripts/) and
[`judge-reversed-scripts/`](../judge-reversed-scripts/):

| script | what it does | needs |
|---|---|---|
| `replay_fixed.py` | asks the 240 steps in all three arms on the Thor and writes the argmax and the full probability vector of every reply, the fidelity check against the October recording, the determinism control and the per-arm latency | a served d1 model, a GPU |
| `measure_fixed.py` | reads those recordings and computes the accuracies by group, the AUCs with their bootstrap intervals, the τ gate's catch and tax by group, the brief's pass rows and the routing table | nothing but the recordings |

`measure_fixed.py` makes **no model call**.

## Running it

On the Thor, with a d1 model served (`thor-admit` holds the lease; the box
is shared, so the run goes under one):

```bash
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/replay_fixed.py \
  --model d1-2B --port 8094 --out docs/lab/judge-prompt-fix-scripts/results/fresh-d1-2B.json
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/replay_fixed.py \
  --model d1-3B --port 8320 --out docs/lab/judge-prompt-fix-scripts/results/fresh-d1-3B.json

~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-prompt-fix-scripts/measure_fixed.py
```

The analysis writes
`docs/lab/judge-prompt-fix-scripts/results/prompt-fix-measurement.json`.

Options: `--trace` (the October trace; default the model's own in
`/home/caseydigennaro/lm-wt/liquid-study/results/`), `--repeat-steps` (how
many leading steps the determinism control re-asks, 12 by default),
`--timeout`, `--out`; and for the analysis `--fresh` (which recordings to
read) and `--out`.

## The three arms

| arm | the state text it asks |
|---|---|
| `recorded` | the October recording's own text, verbatim — the control whose fidelity makes the instrument checkable and whose numbers are the "before" |
| `canonical` | the true condition and the decoy, in `core.judge.ordering`'s canonical order (sorted by the condition's own name) |
| `balanced` | the same pair, in the seeded balanced order (sha256 over the step's `(trial, t)` key) |

The fixed arms change the named pair on the noise steps on purpose: on
those steps the recorded prompt names the decoy and a neighbour of the
truth, so the truth is not in the prompt at all and no answer can be right
(§7.1's bound). Naming the truth and the decoy — the recorder's own
docstring's intent — is what makes the decoy-first steps answerable; the
neutral order is what stops the answer being readable off the position.

## What it reads

| file | from |
|---|---|
| `exp_c_trace_d1-2B.json`, `exp_c_trace_d1-3B.json` | `/home/caseydigennaro/lm-wt/liquid-study/results/` (the October recording) |

and two modules, for their semantics rather than their data:

| module | why |
|---|---|
| [`core/judge/ordering.py`](../../../core/judge/ordering.py) | the two neutral orders, the sentence splitter and the condition names — the policy the fixed arms ask under, shared with every caller |
| [`core/judge/calibration.py`](../../../core/judge/calibration.py) | the τ semantics (the gate escalates when the confidence is **below** τ), the canonical confidence (`top_probability`), the AUC's tie rule, and the sweep and the bootstrap the analysis is pinned against |

## Three things the replay has to get right

**The control is the recording.** The `recorded` arm asks the October text
byte for byte, and its live replies are compared with the recording vector
against vector: on the d1-2B the run's fidelity was exact (max abs diff
0.0, 43 of 43 no-op vectors identical); on the d1-3B the argmaxes matched
240 of 240 with the two-slot server's third-decimal vector differences.
If the control drifts, every number in the same run is suspect.

**The arms rotate.** The three calls of a step go in an order that rotates
with the step index, so "which arm went first" and "which arm is which"
are not the same variable.

**The determinism control.** After the main pass the first `--repeat-steps`
steps are re-asked in every arm; every repeat must return the vector it
returned the first time (36 of 36 in the recorded run, per model). The
difference between arms is the prompt, not the run.

## What it does not do

It does not decide the order mode by taste: both fixed arms are measured,
and the note's §8.2 picks canonical on the numbers (the only arm whose
d1-2B AUC interval clears the coin-flip line, tied elsewhere, no step key
to carry). It does not touch which conditions a caller's states name —
the fixed pair here is the lab's rebuild of the recorder's documented
intent, and `core.judge.ordering` only ever reorders what a state names.
