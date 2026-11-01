# critic-select-scripts — the bake-off's apparatus

The scripts for the **critic bake-off**: the measurement that chose the
critic. The write-up is
[docs/lab/exp-critic-select.md](../exp-critic-select.md); this directory is
the thing that produced its numbers.

The question: **which critic should score a render?** The scripted checks
have a published FP/FN table (`core/critic/CALIBRATION.md`) — 8 of the 9
defect classes in band, `floating_object` out. Any model candidate has to
beat that table, and the comparison has to be *fair*: the same set, the same
counting rule, the same timing.

| file | what it is |
|---|---|
| `harness.py` | the shared harness — one place that loads the set, scores a candidate, times every verdict and folds the table, so no candidate is measured differently from the others |
| `score_set.py` | score the reference set with one candidate (`--candidate scripted\|vlm\|dino-probe\|jev\|hybrid`) |
| `run_candidate.sh` | the same, as a one-liner per candidate |
| `derive_set.py` | re-derive every image member from its base render and its recipe, and check the bytes against the manifest's sha256 — **21 of 21 match** |
| `caption_frames.py` | one neutral description per frame from the local VLM — the text Jev reads (Jev never sees a picture) |
| `run_dino.py` | the DINOv2-large probe, in its two heads (kNN, linear) and its two splits (leave-one-base-out, leave-one-member-out) |
| `plant_leak.py` | how far each plant moves the picture in DINOv2's embedding space — the cosine between a member and the base render it was planted on |
| `run_jev.py` | the Jev arms: `verify`/`classify` × measurements-only / description-only / description+measurements |
| `report.py` | print every candidate's table side by side, and write `core/critic/selection.json` |
| `figures.py` | print each candidate's table, latency spread and model time straight out of the result files — the write-up's numbers come from here, not from memory |
| `latency_split.py` | split the wall time by layer (the checks' 882 ms image verdict against its 21.8 s mesh verdict) and pull the per-question model time out of the verdicts |
| `run_dino_graph.py` | the DINOv2 forward, eager against graphed zero-copy, on the set's own 21 pictures — the graph's descriptor must be bit-identical |
| `start_vlm.sh` | start the local VLM (Muse Glimmer 30B, Apache-2.0, the Thor's own copy) on loopback:8123 |
| `run_vlm_stage.sh` | the VLM stage **under the box's shared heavy lock**: start the server, score the hybrid, make the captions, stop the server, capture the box's state |
| `stage_box.py` | the box's state beside the stage: peak memory and the whole-box power rails (context, not an attribution — the box is shared) |
| `run_rest.sh` | the rest of the bake-off in one go (captions, hybrid, Jev's four arms) |
| `boxstate.py` | the box-state sampler: load, GPU, tegrastats power rails, and the other seats' processes — the state that goes beside every number |
| `check_jev_description.py` | one member, one call — the check that Jev's description arm works before the whole arm is run |
| `check_publish_selection.py` | render the published file's selection section with a synthetic selection, so the formatting is checked before the real one exists |
| `check_no_key.py` | assert the Jev API key is in none of the artifacts (it never is) |

## The results

`results/` holds the raw measurements — one JSON per candidate, in the
harness's own shape (the members, the per-check outcomes, the per-verdict
timing, the folded table). The tables in the write-up are read out of these
files; the files are here so the numbers can be checked without re-running
the bake-off on a shared, flaky box.

`results/*.log` are the run logs (the server's own log, the per-step logs).
They are not committed: they are the noisy tail of a run, and the numbers
they carry are in the JSONs and in the write-up.

## Running it

The mesh half needs an interpreter with `bpy` — the Infinigen checkout's
virtualenv on the Thor:

```bash
export CRITIC_BLENDER_PYTHON=~/src/infinigen-thor/.venv/bin/python
```

The DINOv2 probe needs torch, in **this worktree's own venv** — the core
never depends on it:

```bash
python3 -m venv .venv-torch
.venv-torch/bin/pip install torch transformers pillow numpy
```

The whole bake-off, in order:

```bash
cd docs/lab/critic-select-scripts

.venv/bin/python derive_set.py                    # the set re-derives: 21/21
bash run_candidate.sh scripted                    # the baseline
bash run_vlm_stage.sh                             # the VLM stage, under the lock
.venv-torch/bin/python run_dino.py --head knn   --split base
.venv-torch/bin/python run_dino.py --head knn   --split member
.venv-torch/bin/python run_dino.py --head linear --split base
.venv-torch/bin/python run_dino.py --head linear --split member
.venv/bin/python run_jev.py --arm verify   --measurements
.venv/bin/python run_jev.py --arm classify --measurements
.venv/bin/python run_jev.py --arm verify   --captions results/captions.json
.venv/bin/python run_jev.py --arm classify --captions results/captions.json
.venv/bin/python report.py --write-selection
```

**Jev needs `TYPESAFE_API_KEY`** — from the environment or from
`~/.config/last-mile/secrets.env`. The key is never printed, never logged
and never written to a result file; `check_no_key.py` is the assertion that
this is true.

**The VLM stage is a heavy step** (a resident 17 GB model) and runs under
the box's shared lock:

```bash
flock ~/lm-wt/heavy.lock bash run_vlm_stage.sh
```

One model server per seat at a time, and it is stopped as soon as the stage
is done.
