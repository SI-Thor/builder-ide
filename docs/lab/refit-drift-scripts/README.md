# refit-drift-scripts

The scripts behind `docs/lab/exp-refit-drift.md`. Two experiments, all CPU,
no model downloads: the nightly whole-log refit measured on the repo's own
tile ledger (part 1), and the watching-teachers question on crafter-lab's
teacher frames (part 2).

## Part 1: does the nightly whole-log refit drift the old contexts

```bash
cd ~/lm-wt/refit-drift
uv venv --python 3.12 .venv          # once
uv pip install --python .venv/bin/python "numpy>=1.26" "pydantic>=2.7,<3"
.venv/bin/python docs/lab/refit-drift-scripts/extract_real_tiles.py \
  --out docs/lab/refit-drift-scripts/real_tiles.json
.venv/bin/python docs/lab/refit-drift-scripts/exp_refit_drift.py \
  --seeds 24 --out docs/lab/refit-drift-scripts/results/refit_drift.json
```

About 64 s. `real_tiles.json` is read from the nights' own ledgers; the run
rebuilds the tiles' bandit chooser over growing log prefixes and scores the
old contexts each night. Diagnostics for its estimator:
`_diag_drift.py`, `_diag_ope.py`.

## Part 2: one policy, many demonstrations (watching teachers)

Needs the crafter-lab venv and its teacher frames:

```bash
cd ~/lm-wt/refit-drift/docs/lab/refit-drift-scripts
PY=/home/caseydigennaro/lm-wt/crafter-lab/.venv/bin/python
# full run: 4 arms x 3 seeds, about 2 h on the Thor under a thor-admit lease
$PY exp_watching_teachers.py --seeds 3 --passes-per-stage 262144
# single arm (how the per_skill_heads arm was re-run after the fixes):
$PY exp_watching_teachers.py --seeds 3 --passes-per-stage 262144 \
  --arms per_skill_heads --out results/watching_teachers_heads.json
```

`exp_watching_teachers.py` trains a student on crafter-lab's teacher frames
(`~/lm-wt/crafter-lab/data/teacher_frames.npz`), six skills in the order the
teacher taught them, under four arms: `seq` (skill by skill, no replay),
`seq_replay` (skill by skill, half the stage budget replays earlier skills),
`whole` (one pass over all the demonstrations), `per_skill_heads` (shared
trunk, one linear head per skill, trunk frozen). The JSON is written after
every run, so an interrupted run leaves what it had.

Calibration table for reading the agreements (untrained policy, the
constant-action baseline per skill, and the crafter-lab student B beside
them; plus how the agreement scales with the passes budget):

```bash
$PY _diag_calib.py
$PY _diag_budget.py
```

A few minutes. The recorded table is `results/calib_budget.log`.

## Results

- `results/refit_drift.json` — part 1, every row, box state inside.
- `results/watching_teachers.json` — part 2, `seq`/`seq_replay`/`whole`.
- `results/watching_teachers_heads.json` — part 2, `per_skill_heads`.
- `results/watching_teachers.log`, `.run2.log`, `.run3.log`, `.run4.log` —
  the summary line per arm/seed, in order; the first two attempts crashed in
  `per_skill_heads` (see the NOTES.md entries) and lost their end-of-run
  JSON; the agreement numbers are deterministic and the later attempts
  reproduce them bit for bit.
- `results/calib_budget.log` — the calibration table.

Known history: `HeadStudent` needed `latent_dim_pi` for the installed SB3,
and the heads arm must not measure a skill through a head that is not
trained yet (it reports `None`). Both fixes are in the committed script.
