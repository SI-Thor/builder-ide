# `tools/drift` — the drift detector's measurement harness

Three scripts, and the dataset they make. The lab note that cites them is
[`docs/lab/exp-drift-detector.md`](../../docs/lab/exp-drift-detector.md).

## What is here

| script | what it does | how long |
|---|---|---|
| `extract.py` | the live world ledger → the dataset; the world's client logs and the incident notes → the labels | ~2 s |
| `calibrate.py` | the threshold sweep, the leave-one-episode-out, the time split, the level-gate comparison | ~7 s |
| `pauses.py` | every alarm the shipped detector raises, with the reason a human would read | ~1 s |
| `measure_twosided.py` | the shipped one-sided rate gate against the old two-sided one, on the committed dataset | ~15 s |

## The dataset and the labels

`extract.py` writes three files into `docs/lab/drift-dataset/`:

* `dataset.json` — the ledger folded into five-minute windows, with the
  ledger's sha256 so the numbers say what they were cut from;
* `labels.json` — the labelled drift events, **from instruments outside the
  ledger** (the bots' own log, and the two written incident notes), grouped
  by window so the file stays small;
* `calibration.json` — written by `calibrate.py`.

**The labels are not cut from the ledger on purpose.** A detector scored
against the rows it reads scores itself. The labels come from the world's
clients (`bots.jsonl`) and from the written records of the hang
(`docs/lab/incident-2026-11-01-jax-hang.md`) and of the wedge and the judge
(`agent-world/docs/playtest-2026-11-01-reward.md`).

One class of label is a **negative control**: `designed_yield` — the world
refusing work because the box is busy or another seat holds the lease. That
is the world behaving correctly, and a detector that alarms on it is wrong.

## Running them

```bash
python3 tools/drift/extract.py --out docs/lab/drift-dataset

python3 tools/drift/calibrate.py \
    --dataset docs/lab/drift-dataset/dataset.json \
    --labels docs/lab/drift-dataset/labels.json \
    --out docs/lab/drift-dataset/calibration.json

python3 tools/drift/pauses.py

# 4. the one-sided gate against the old two-sided one, on the committed
#    dataset. It patches the gate in this process and re-runs the same
#    calibration, so the "before" number is measured on the same data as
#    the "after" one.
python3 tools/drift/measure_twosided.py
```

CPU only, seconds, no lease and no GPU.

## The knobs

`calibrate.py` takes the sensitivity as arguments, so that the numbers are
an answer to a question rather than a preference:

| flag | default | what it changes |
|---|---|---|
| `--pause-budget` | 0.10 | the share of the world's windows that may be in alarm without a label. This is what rules out a gate that is permanently on. |
| `--min-scored-plays` | 20 (the config's) | the sample a success rate needs before it is a rate |
| `--stall-lookback` | 3 (the config's) | the windows the stall signal looks back over |
| `--signal-lookback` | 3 (the config's) | the windows the success and spend signals look back over |
| `--dwell-down` | 600 s (the config's) | how long the gate must hold a clear before it clears |
| `--tolerance` | 1 | how many windows either side of an episode still counts as covering it |

## A note on the ledger

The world ledger is **live** and is still being written while these scripts
read it. The extraction opens it read-only, so it never disturbs the world,
but re-running it gives a slightly longer dataset than the committed one.
The committed snapshot is the one whose sha256 is in `dataset.json` and in
the lab note.
