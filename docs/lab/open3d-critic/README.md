# open3d-critic — Open3D 0.20 against the critic's geometry checks

The scripts behind `docs/lab/exp-open3d-critic.md`: whether Open3D (MIT)
should be part of the prop critic's measurement path on the Thor.

## What is here

| file | what it does |
|---|---|
| `fetch_extra_samples.py` | picks and fetches 5 fresh SimReady packages (the prior never saw them) and converts them to GLB |
| `compare.py` | the per-mesh comparison: both stacks, identical arrays |
| `summarize.py` | the aggregates the report quotes, from `results/results.json` |
| `results/extra_samples.json` | the five fetched packages (triangles, primitives, conversion time) |
| `results/results.json` | the full per-mesh rows (45 meshes: 38 reference + 5 fresh + 2 analytic controls) |

## How to run

Everything runs on the Thor, CPU-only. Two venvs:

```bash
# 1. the five fresh samples (needs pxr; ~400 MB download, ~2 min)
~/lm-wt/mesh-repair/.venv/bin/python docs/lab/open3d-critic/fetch_extra_samples.py

# 2. the comparison (needs the worktree's .venv: open3d, numpy, scipy, pydantic)
cd ~/lm-wt/open3d-critic
uv venv .venv --python 3.12 && uv pip install open3d numpy scipy pydantic
.venv/bin/python docs/lab/open3d-critic/compare.py          # ~40 min at load ~21
.venv/bin/python docs/lab/open3d-critic/compare.py --quick  # first 3 meshes, ~7 min

# 3. the digest
.venv/bin/python docs/lab/open3d-critic/summarize.py
```

## What it needs

- the reference GLBs at `~/lm-wt/simready-survey/data/glb/` (38 files) and
  the five fresh ones at `~/lm-wt/simready-survey/data/glb-extra/`
  (written by step 1; the 379 MB of payloads live on `~/lm-cold`, never
  in the repo);
- `core/genbatch/simready-reference.json` (in the repo) and the survey's
  `repo_index.jsonl` (on the Thor) for the sample picker;
- open3d **0.20.0** — the only release with a cp312 aarch64 wheel
  (`manylinux_2_35`; the Thor's glibc is 2.39).

## Costs, as measured (2026-11-01, load ~21)

The full sweep over 45 meshes (7.41 M triangles) takes ~40 min wall, of
which ~38 min is Open3D's `is_self_intersecting` on the big meshes; peak
RSS 1.1 GB. The digest is ~1 min. The fetch is one-off.

Dataset: NVIDIA SimReady Assets, CC-BY-4.0, credited; five packages
sampled, never mirrored.
