# critic-shells-scripts — the critic's fill ratio, measured on real objects

The apparatus for the **shells** measurement: the critic's `fill_ratio`
divides a mesh's *signed* volume by its bounding box, and a real object is
a shell — so the measure read the volume of the material in the wall
instead of the space the object takes up. The write-up is
[`docs/lab/exp-critic-shells.md`](../exp-critic-shells.md); this directory
is the thing that produced its numbers.

The two questions:

1. **What should the fill ratio measure?** The space the object occupies,
   measured three ways — and which one is right is a measurement, not a
   preference.
2. **What should the prior be fitted on?** A prior over *real* objects
   cannot be fitted on generated props alone: the generated ones are
   solids, and every real object read as a ghost.

| file | what it is |
|---|---|
| `validate_occupancy.py` | the three measures against five shapes whose volume is known (a cube, a sphere, a hollow mug, a plate, an L-bracket) — which measure agrees with the known number |
| `measure_fill.py` | the fill ratios of the 38 sampled real assets under every measure, with the triangles, the box, the occupied volumes and the wall clock each one cost |
| `make_reference.py` | measure the sample with the critic's own pipeline and write `core/genbatch/simready-reference.json` — the reference set the prior is fitted on, with its provenance |
| `refit_prior.py` | the confusion table, before and after: the ghost's score, how many real assets are flagged, and the same with each real asset held out of the fit |

## The results

`results/` holds the raw measurements, and every one of them carries the
box state it ran under — the machine, the kernel, the load and the
memory — so a number can be read against the box that produced it.

| file | what it holds |
|---|---|
| `results/occupancy_validation.json` | the three measures against the known volumes |
| `results/fill.json` | per asset: the triangles, the first-primitive share, the signed volume, each candidate's occupied volume and fill ratio, and the seconds each cost |
| `results/confusion.json` | the before/after table, and the leave-one-out reading |
| `results/refit.json` | the k-means sweep over cluster counts and seeds, and what each fit did to the gates |

The tables in the write-up are read out of these files, so they can be
checked without re-running the measurement on a shared box.

## The data lives outside the repository

The GLBs are the survey's own conversions, verified against their USD
sources and read back with builder-ide's reader
(`docs/research/simready.md` §4.3). The sample is **113.9 MiB** across 38
packages, so the path is a parameter (`--glb-dir`) and the default points
at the survey worktree:

```
/home/caseydigennaro/lm-wt/simready-survey/data/glb
```

The meshes are the **NVIDIA SimReady Assets** (`nvidia/simready-assets` on
Hugging Face), CC-BY-4.0, credited. They are read and sampled, never
mirrored.

## What is stored, and what is not

`core/genbatch/simready-reference.json` is the **recipe**: 38 rows of six
numbers each, plus the provenance — the dataset and its licence, the
measure and its resolution, the prior's cluster count and seed, and the
box state of the run that measured them. The meshes are the cache; the
numbers are the source of truth, and a rebuild from the same meshes gives
the same numbers. The features are written to **12 significant digits**,
because the prior's score is a rank and coarse rounding moves the ranks
of the borderline assets.

## Running it

The scripts use the mesh-repair virtualenv, which has numpy and scipy:

```bash
cd ~/lm-wt/critic-shells
PY=~/lm-wt/mesh-repair/.venv/bin/python

# the measures against known volumes
$PY docs/lab/critic-shells-scripts/validate_occupancy.py

# the fill ratios over the 38 assets (about 15 s)
$PY docs/lab/critic-shells-scripts/measure_fill.py --resolutions 64

# the reference set the prior is fitted on
$PY docs/lab/critic-shells-scripts/make_reference.py

# the confusion table, before and after
$PY docs/lab/critic-shells-scripts/refit_prior.py
```

**Nothing here needs a GPU or an admission lease.** The measurement is
numpy and scipy over meshes that are already on disk, and it ran at load
8–10 on a box shared with the night's work.

The **toy** the prior is compared against — 200 synthetic features with
known kinds — is not duplicated here: it is the test set's own
(`tests/genbatch/test_plausibility.py`), so the approved set the prior is
fitted on is the one the tests use, and the numbers cannot drift apart
from it.
