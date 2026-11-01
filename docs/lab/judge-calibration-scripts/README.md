# `judge-calibration-scripts` — the measurement behind the calibration note

The script that produced
[`docs/lab/exp-judge-calibration.md`](../exp-judge-calibration.md): it
replays **recorded probability vectors** through
[`core/judge/calibration.py`](../../../core/judge/calibration.py) and
writes every number in the note.

**No model runs.** No GPU, no server, no cloud key, no network. The seed's
promise was that the endpoint already returned the full probability vector
for every answer, so the same week of logs can be re-scored three ways.
That is all this does.

## Running it

```bash
.venv/bin/python docs/lab/judge-calibration-scripts/measure_calibration.py
```

It writes
`docs/lab/judge-calibration-scripts/results/calibration-measurement.json`:
every cell's numbers (accuracy, Brier, ECE, mean confidence, the
reliability curve, the escalation sweep under all three definitions), the
fitted scales, the held-out before/after, the AUCs, the machine state, and
the two mechanism measurements (the prompt breakdown behind the inverted
confidence, and the lopsidedness of Clef's booleans).

Options: `--out` (the output path) and `--bins` (the reliability bins,
default 10).

## What it reads

| file | from |
|---|---|
| `exp_c_trace_d1-2B.json`, `exp_c_trace_d1-3B.json` | `/home/proart/lm-wt/liquid-study/results/` |
| `judge-tiles-coldstart.json` | `docs/lab/judge-scripts/results/` |
| `hysteresis-d1-sweep.json` | `docs/lab/hysteresis-scripts/results/` |
| `c3-calibration-runs.json` | `/home/proart/lm-wt/clef-cascade/results/` |

and two modules, for their own semantics rather than their data:

| module | why |
|---|---|
| `docs/lab/judge-scripts/measure_tiles_coldstart.py` | the rig's constants, its tile set and its seeded draw — imported so the replay cannot drift from the rig |
| `docs/lab/clef-cascade-scripts/cascade.py` | `build_all(80, 60, 60)`, the ground truth the teacher saw |

The clef results live on another machine's worktree. Copy them in, or
point the script at that path.

## Two things the replay has to get right

**The tiles rig's outcomes.** That arm wrote its distributions but not its
play rows, so the outcome is recomputed from the rig's own seeded draw —
`sha256(tile|bucket|play_index)` against the match/miss chance of the
tile's style against the context's wanted style. The replay reproduces
the rig's published judge-only win rate exactly (0.6900 over 600 plays),
which is the check that it is the same game.

**The liquid traces' ground truth.** The options are the sea states in
order, so the truth's option is `"ABCDE"[truth]`, and the model's answer
is the **argmax of the vector** — not the trace's `shown` field, which is
the state the *prompt* named first. The study's own published numbers
(d1-2B accuracy 0.525, d1-3B 0.3292) are the argmax rule; this
reproduces them.

## What it does not do

It does not call the judge, and it does not read a ledger: it builds the
calibration samples directly from the recorded vectors, because the
rig's arms wrote their traces rather than ledger rows. The fold over
ledger rows — the scope join, the outcome sources, the nightly job — is
exercised by `tests/judge/test_tracking.py` instead.
