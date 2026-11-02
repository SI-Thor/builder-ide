# critic-selfx-scripts — the reference re-run behind exp-critic-selfx.md

The scripts that measure what the critic's three adopted Open3D uses
change on the SimReady reference set.

## What is here

| file | what it does |
|---|---|
| `rerun_reference.py` | measures the 38 reference GLBs with the new signals off and on, judges both, records every flipped check |
| `results/rerun.json` | the full per-mesh rows, the verdict flips, and the 12 watertight-flip rows copied from the open3d-critic sweep |

## How to run

On the Thor, CPU only, from the worktree root:

```bash
cd ~/lm-wt/critic-selfx
.venv/bin/python docs/lab/critic-selfx-scripts/rerun_reference.py           # ~minutes
.venv/bin/python docs/lab/critic-selfx-scripts/rerun_reference.py --quick  # first 3 meshes
```

## What it needs

- the worktree's `.venv` with the `dev` and `o3d` extras
  (`uv venv .venv && uv pip install -e ".[dev,o3d]"`; open3d is pinned
  `==0.20.0`, the only cp312 aarch64 wheel);
- the reference GLBs at `~/lm-wt/simready-survey/data/glb/` (38 files,
  NVIDIA SimReady Assets, CC-BY-4.0; never in the repo);
- `docs/lab/open3d-critic/results/results.json` (in the repo) for the
  watertight-flip rows.

## What the request is

Every mesh is judged against one request with a non-binding triangle
budget: the budget verdict is identical before and after the change, and
the point of the run is the self-intersection and volume verdicts. The
old verdict is reconstructed exactly — signals-off measurement, the one
new check dropped from the judge's output, the weighted mean recomputed
— so the score deltas are the change and nothing else.

## Costs, as measured

See `docs/lab/exp-critic-selfx.md` — the run's wall time, peak RSS and
the box's load are recorded in `results/rerun.json`'s `meta` beside the
numbers.
