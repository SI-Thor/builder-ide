# `docs/lab/tiles-retrieval-scripts/` — E1 on the tiles acceptance rig

The measurement script behind
[`docs/lab/exp-tiles-retrieval.md`](../../exp-tiles-retrieval.md).

## What it measures

**E1**, from `docs/research/pincher-fit.md`: *offline replay over the tiles
logs. Embedding fast path at ≥ 0.80, falling back to the bandit's logged
choice. It beats the bandit if it covers ≥ 30 % of contexts, its reward is
within ε of the bandit's, and p95 is under 50 ms.*

And the settling experiment it belongs to: bandit only, pincher-style
similarity only, retrieval then bandit — *win rate, latency, and how fast
each improves with use*.

## The rig

**The acceptance rig's own**, not a copy of its shape: the same
`ScriptedAuthor` and specs, the same registry, the same `contexts(600, 17)`,
and the same `(tile, bucket, play index)` sha256 draw. The bandit arm
therefore reproduces the published acceptance figure (479/600 = 0.7983),
which is the check that the rig is the rig. Every arm plays the identical
game, so a difference between arms is a difference between the policies.

Five arms: the bandit, retrieval-only, retrieval-bandit, the fast path, and
the always-matching reference (a policy that always plays a tile of the
requested style — the best class the game allows).

## Running it

```bash
cd ~/lm-wt/tiles-retrieval
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py
PYTHONPATH=. .venv/bin/python docs/lab/tiles-retrieval-scripts/measure_tiles_retrieval.py \
    --embedder hashing --out docs/lab/tiles-retrieval-scripts/results/tiles-retrieval-e1-hashing.json
```

Options: `--plays` (default 600), `--k` (the shortlist, default 3),
`--embedder {default,hashing}` (`default` is the local static model,
`hashing` is the no-model floor), `--out` (the results JSON).

## What it needs

numpy, the repo's own `core.tiles`, and — for the static embedder — the
`embed` extra (`pip install -e ".[embed]"`). **Without it the run falls back
to feature hashing and says so** in the results and on the console. No GPU,
no network beyond the one model download, no LLM call.

## What it writes

`results/tiles-retrieval-e1.json` (the static model) and
`results/tiles-retrieval-e1-hashing.json` (the floor). Each carries the
numbers, the box state they were measured on, and the per-context band
readings.

## What it does not do

It does not run on the Thor: the rig is arithmetic on a seeded world, and the
box's own acceptance run is the thing that would need the box. It does not
sweep K, and it does not measure a paraphrase-heavy request set — both are
named as open in the lab note.
