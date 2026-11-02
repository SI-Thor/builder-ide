# sleep-dreaming-scripts

The scripts behind [`docs/lab/exp-sleep-dreaming.md`](../../lab/exp-sleep-dreaming.md).

## What is here

| file | what it is |
|---|---|
| `exp_sleep_dreaming.py` | the experiment: a two-phase class-incremental toy (classes 0-4, then 5-9), five arms, the forgetting measured per seed |
| `boxstate.py` | an unmodified copy of the lab's shared box-state meter (`docs/lab/lab3-scripts/boxstate.py`) — the load, the power mode, the GPU clock and the other tenants of the box, beside every number |
| `results.json` | the output of the recorded run: every row, the summary, the config, the box state |

## What it needs

Python 3.12 and `torch`. **The CPU build is enough** — this experiment never
touches the GPU, and on this box the GPU's memory *is* the system memory.

```bash
cd ~/lm-wt/sleep-dreaming
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "torch==2.15.0+cpu" \
  --index-url https://download.pytorch.org/whl/cpu
```

No model, no dataset, no network at run time.

## How to run it

Under a lease, as the memory rule says:

```bash
cd ~/lm-wt/sleep-dreaming
~/lm-tools/thor-admit run --tier practice --peak 2G --label sleep-dreaming.exp -- \
  .venv/bin/python docs/lab/sleep-dreaming-scripts/exp_sleep_dreaming.py \
    --seeds 8 --out docs/lab/sleep-dreaming-scripts/results.json
```

`--peak 2G` is honest for this job: the model is a 16-32-10 MLP, the batches
are 64 rows, and the process is torch on the CPU. The measured peak is in the
lab note; if the daemon's own history says otherwise, use `--peak auto` once it
has three runs.

The script prints one line per (arm, seed) and the summary table, and writes
`results.json` with every row, the summary, the config and the box state.

## The knobs

| flag | default | what it is |
|---|---|---|
| `--seeds` | 8 | seeds per arm, from `--seed0` |
| `--steps` | 400 | gradient steps in each wake phase (A and B) |
| `--sleep-steps` | 200 | the post-phase budget `T`: replay steps, consolidation steps, or the extra wake steps in `seq_extra` |
| `--dream-steps` | 200 | the dreaming budget in `sleep_dream` |
| `--seed0` | 3 | the first seed |
| `--out` | `results.json` | where the JSON goes |

Every arm gets the same number of gradient steps; only the *direction* of the
budget differs. That is what makes the comparison fair, and the lab note says
what is still not matched (the parameters updated per step).

## The two settings

The script runs every arm in **two settings** and the rows are keyed by
`setting/arm`:

* `shared_trunk` — the trunk keeps training on task B (the ordinary case);
* `frozen_trunk` — the trunk is frozen from the start of phase B.

Every row also carries `a1_trunk`: the accuracy on task A after the trunk is
put back where it stood at the end of phase A. It says how much of A's loss was
the shared representation moving, rather than the head being overwritten.

## Two things that went wrong, and the fixes

1. **The train and the test split drew different class centres** (different
   seeds), so the model memorised the training set at zero loss and scored at
   chance on the test set. The centres now come from one seed and the samples
   from another.
2. **The dream phase diverged.** At the shared learning rate (0.05) with
   momentum, on a single-sample loss, it produced NaN weights on one seed and
   the run died on a multinomial over `inf`. The dream phase now has its own
   learning rate (`DREAM_LR = 0.01`) and a gradient clip (`GRAD_CLIP = 1.0`),
   and the consolidation clips too. The dead ends are in `NOTES.md`.
