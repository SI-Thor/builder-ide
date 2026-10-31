# mini-night-2-scripts — the night's analysis

The scripts for **mini-night 2**: the same three requests as the first
mini-night, but behind the cost model's pricing and with the mesh repair in
the pipeline. The write-up is
[docs/lab/mini-night-2.md](../mini-night-2.md).

| file | what it is |
|---|---|
| `measure_repairs.py` | measures the repair on **every** prop the night made — nine, not just the three winners |

## Why a separate script

The night's own report carries the repair for the three winners, because the
winners are the assets the report keeps. The question the night has to
answer is wider: how many of the nine props were watertight before the
repair, how many after, and what did the repair do to each one's outline.

So this script walks the night's whole slate after the fact. It reads each
GLB the night wrote, measures the mesh the way the pipeline measured it
(`core.genbatch.mesh.measure_mesh`), runs the same repair with the same
recipe (`core.genbatch.repair.repair_mesh`), and measures again. The GLB is
the artefact; the recipe is the code; the measurement is reproducible.

## Running it

```sh
PYTHONPATH=. python docs/lab/mini-night-2-scripts/measure_repairs.py \
    --requests examples/mini_night_requests.json \
    --out artifacts/mini-night-2/repairs.json
```

It prints one line per prop — watertight before and after, the boundary
edge counts on both sides, the silhouette IoU, and the seconds the repair
took — and writes the whole record as JSON.

It picks each prop's GLB by name (`<request>_s<seed>_*.glb`) and takes the
most recent one, so re-running it after a later night would pick up the
later night's file; pass a different `--out-dir` to measure a different run.

## What it stubs

Nothing. It reads the night's own GLBs and calls the pipeline's own
measurement and repair code. The only judgement is the choice of the most
recent GLB per seed.
