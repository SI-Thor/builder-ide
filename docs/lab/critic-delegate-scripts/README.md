# critic-delegate-scripts — the delegate bake-off's apparatus

The scripts for the **delegate swap**: the measurement that replaced the
hybrid's 30 B vision-language model with a decision model, and that checked
the critic's new continuation (a verdict that carries the next move). The
write-up is [`docs/lab/exp-critic-delegate.md`](../exp-critic-delegate.md);
this directory is the thing that produced its numbers.

The question had two halves:

1. **Which model answers for the class the checks miss?** The hybrid asks a
   delegate only about `floating_object`, the one class the scripted checks
   are out of band on. The delegate has to be a model that is allowed on the
   box (B2: no language models on the Thor), sees the frame, and is quick
   enough to sit in a verdict.
2. **Does the continuation clear the flag it was raised for?** When the
   hybrid flags a floating thing, the verdict carries a typed edit — the
   support surface below it and the distance to drop it. Applying that edit
   has to make the flag go away.

| file | what it is |
|---|---|
| `score_set.py` | score the reference set with one candidate (`--candidate scripted\|d1\|clef\|hybrid`), and write `results/<name>.json` |
| `run_bakeoff.sh` | the whole bake-off in order: the baseline, the two delegates, the hybrid with each, the tables side by side |
| `run_d1_stage.sh` | the local decision model's stage: start the server, score the set with it (alone and as the delegate), run the continuation test, stop the server |
| `start_d1.sh` | start the local decision model under the box's admission daemon, and **read the port back** (see below) |
| `worker/` | the throwaway Workers AI proxy that holds the AI binding — `wrangler dev --remote`, **nothing deployed** |
| `continuation_test.py` | apply the edit the verdict carries to every frame where the flag fired, and measure what happened |
| `scene_scale.py` | metres per pixel, from the geometry probe's camera, and what the scale does to a drop distance |
| `clef_latency.py` | where the cloud delegate's time goes: the edge's own work against the path to the edge |
| `report.py` | print every candidate's table side by side |

The **questions** are the ones the first bake-off asked, unchanged
(`core/critic/candidates/questions.py`). They were written before this
measurement and were not tuned against it: a question chosen after seeing
which members each model gets right would be tuning on the set the numbers
are measured on.

## The results

`results/` holds the raw measurements — one JSON per candidate, in the first
bake-off's harness shape (the members, the per-check outcomes, the
per-verdict timing, the folded table). The tables in the write-up are read
out of these files, so they can be checked without re-running the bake-off
on a shared, flaky box.

`results/*.log` are the run logs (the server's own log, the per-step logs),
and `results/*-edited.png` are the edited frames the continuation test
produced. The frames are derived images — the same kind of cache as the set's
own — so they are not committed; the numbers about them are.

## The box's rule

Every heavy step takes a lease from the box's admission daemon, and a model
server is served **once per box**:

```bash
# a heavy step: take a lease, then do the work
thor-admit run --tier live --peak 8G --label critic-delegate.d1-stage -- \
  bash docs/lab/critic-delegate-scripts/run_d1_stage.sh

# a model server: the daemon answers with the port if one is already up
thor-admit serve d1-2B --port 8131 -- llama-server -m ... --mmproj ...
```

The old shared flock (`~/lm-wt/heavy.lock`) is the **stopgap** for when the
daemon's binary is missing, not the default — see `~/lm-wt/MEMORY-RULE.md`.

**The port is read back, not assumed.** A model is loaded once per box, not
once per seat: if another seat already has `d1-2B` answering, the daemon
hands back *that* port and starts nothing. `start_d1.sh` writes the port the
daemon answered with to `results/d1.port`, and the stage talks to that one.
Two seats must not each start the same model — that was half of the box
running out of memory on 2026-10-31.

The consequence for a **latency** measurement is worth knowing: the numbers
belong to the server that answered. The write-up says which server the
numbers were taken with.

## Running it

The mesh half needs an interpreter with `bpy` — the Infinigen checkout's
virtualenv on the Thor:

```bash
export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
```

The scripts use **this worktree's own venv** (`.venv/bin/python`); set `PY`
to point somewhere else.

The cloud delegate needs the Worker running on the ProArt and its port
forwarded to the Thor:

```bash
cd docs/lab/critic-delegate-scripts/worker
npx wrangler dev --remote --port 8797
# and on the Thor:
ssh -L 8797:127.0.0.1:8797 proart-lan
```

The whole thing, in order:

```bash
# the bake-off: the baseline, the two delegates, the hybrid with each
bash docs/lab/critic-delegate-scripts/run_bakeoff.sh

# the continuation test: apply the edit, measure what happened
.venv/bin/python docs/lab/critic-delegate-scripts/continuation_test.py --delegate d1
.venv/bin/python docs/lab/critic-delegate-scripts/continuation_test.py --delegate clef

# the metric scale: metres per pixel, from the scene's camera
.venv/bin/python docs/lab/critic-delegate-scripts/scene_scale.py

# where the cloud delegate's time goes: the edge's own time against the path
.venv/bin/python docs/lab/critic-delegate-scripts/clef_latency.py --repeat 3

# the tables, side by side
.venv/bin/python docs/lab/critic-delegate-scripts/report.py
```

The first bake-off's harness (`docs/lab/critic-select-scripts/harness.py`) does
the loading, the scoring and the folding, so the rows here are comparable
with the rows there by construction: the same members, the same counting
rule, the same clock.
