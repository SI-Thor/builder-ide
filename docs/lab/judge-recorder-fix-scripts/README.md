# `judge-recorder-fix-scripts` — the recorder fixed at the source, and what it measures

The scripts behind §9 of
[`docs/lab/exp-judge-calibration.md`](../exp-judge-calibration.md): the
October recorder (`liquid-study/scripts/exp_c_hysteresis.py::make_trial`)
left the truth out of 82 of its 240 prompts (the decoy named twice on 43
of them, the decoy plus the truth's other neighbour on the rest). §8
fixed the prompt at replay time; this seat fixes the recorder and
re-records the trace it should have written.

## What each script is

| script | what it does | needs |
|---|---|---|
| `recorder.py` | the fixed builder: the truth and the drawn decoy, once each, in `core/judge/ordering`'s canonical order, on the October seed and stream; `old_make_trial` keeps the October builder verbatim; `prompt_faults` is the invariant; `main` audits old vs new (and an October file, `--october`) | CPU only |
| `rerecord.py` | asks the fixed recorder's 240 prompts on a served d1 and writes the trace in the October shape, with the fidelity check (on the prompts byte-identical to the recording, the reply must equal the recorded vector) and the determinism control | a served d1 model, a GPU |
| `measure_rerecord.py` | reads the two re-recordings and the October traces; accuracy by group, the positional tally, the AUC with its bootstrap interval, the τ gate (sweep, by group, budgets), the routing table, and what the re-record changed against §8's replay | nothing but the files |
| `route_end_to_end.py` | the routed cell through the shipped seam: `core.judge`'s `Judge` over `D1Backend`, the shipped `CALIBRATED_TAUS`, every attempt a `judge.verdict` row; reports the gate's words, the catch, the tax | a served d1 model, a GPU |

The regression suite is `tests/judge/test_recorder_fix.py` (runs on
`recorder.py` only; no files, no GPU): the invariant passes on the fixed
builder, fails on the old one with §8's counts (82 omitted / 43 doubled),
the order is canonical, the task equals the old builder's, the builder is
byte-deterministic.

## Running it

On the Thor, with a d1 model served (the box is shared; the runs go under
`thor-admit` leases, and the scripts run under a venv that has the
repository's dependencies — `~/lm-wt/core-judge/.venv` on the Thor):

```bash
# the audit (CPU; the numbers in §9's first paragraph)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/recorder.py \
  --october /home/caseydigennaro/lm-wt/liquid-study/results/exp_c_trace_d1-2B.json

# the re-recording (needs a served d1; under a lease, on a shared box)
~/lm-tools/thor-admit run --tier live --priority 1 --peak 1G \
  --label judge-recorder-fix.rerecord-d1-2B -- \
  ~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/rerecord.py \
  --model d1-2B --port 8094 --out docs/lab/judge-recorder-fix-scripts/results/rerecorded-d1-2B.json
# (the 3B the same way, on its own port)

# the analysis (CPU, no model)
~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/measure_rerecord.py

# the routed cell, end to end (needs the routed model served)
~/lm-tools/thor-admit run --tier live --priority 1 --peak 1G \
  --label judge-recorder-fix.routed-3B -- \
  ~/lm-wt/core-judge/.venv/bin/python docs/lab/judge-recorder-fix-scripts/route_end_to_end.py \
  --model d1-3B --port 8320 --out docs/lab/judge-recorder-fix-scripts/results/routed-end-to-end-d1-3B.json
```

`rerecord.py` takes a few minutes a model (240 calls plus the repeats);
`measure_rerecord.py` runs in seconds; `route_end_to_end.py` a few minutes
a model (240 asks through the seam). The audit is instant.

## What it reads

| file | from |
|---|---|
| `exp_c_trace_d1-2B.json`, `exp_c_trace_d1-3B.json` | `/home/caseydigennaro/lm-wt/liquid-study/results/` (the October recording) |
| `replay_fixed.py`, `measure_fixed.py` | the sibling [`judge-prompt-fix-scripts/`](../judge-prompt-fix-scripts/) — the wire machinery and the statistics, imported, one copy |
| `core/judge/ordering.py` | the order policy the fixed builder builds through |

and it writes, into `results/`:
`rerecorded-d1-2B.json`, `rerecorded-d1-3B.json` (every reply, the
fidelity and determinism checks, the box state, the trace in the October
shape), `recorder-fix-measurement.json` (every number in §9),
`routed-end-to-end-d1-2B.json`, `routed-end-to-end-d1-3B.json` (the seam's
rows and the gate's words).

## The one thing to know about the groups

On the fixed prompts the October groups (158 "truth presented", 82 "a
decoy presented", 43 of those naming one condition twice) describe the
task's noise process, not the prompt: the fixed recorder names the truth
and the drawn decoy on every step, in an order that does not know which
is true, so no group's prompt differs from another's. The groups are kept
so §9's numbers sit beside §8's; the honest reading of a group difference
after the fix is "none is expected".
