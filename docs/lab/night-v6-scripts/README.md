# night-v6-scripts

The runner for **night-v6** (`docs/lab/night-v6.md`), the exporter that
made the live view's source land inside a night, the ghost's second look,
and the scripts that write the morning's letter.

## What is here

| file | what it is |
|---|---|
| `run_night.py` | the night, end to end: one ledger, one runner, every layer real |
| `launch_night.sh` | launches the night and the finisher beside it, both detached (one ssh, no open connection) |
| `build_library.py` | the library's approved set: ten measured crates, one kind (built **once**, before night-v5; reused) |
| `approved-crate-library.json` | what `build_library.py` wrote; the runner reads it |
| `measure_llama_gpu_under_load.py` | the decision servers under the night's own request shapes — the numbers the 6 GB leases stand on |
| `courtyard_requests.json` | the three props the owner asked for |
| `export_scene.py` | the live view's source, decimated first: placeholder materials, subdivision capped, collapse-decimation over 5k base polygons — **75.2 s** on night-v5's own scene.blend where the old export ran 115-240 min |
| `render_prop_views.py` | a prop's GLB rendered from three orthographic views (Cycles CPU) — what the ghost's second look is shown |
| `second_look.py` | the ghost's second look: the renders to one DeepInfra VLM call (fixed question, temperature 0); both verdicts on one `night.ghost_second_look` row |
| `decision_counts.py` | the one counter of the night's decisions from the ledger — what the letter, the facts file and the measurements all speak |
| `write_letter.py` | reads `morning.json` **and the ledger beside it**, writes `letter.md` (at most 150 words); the letter's decision numbers equal the ledger's by construction |
| `facts_from_ledger.py` | transcribes the ledger into `letter-facts.json` (the same split) |
| `measure.py` | the night's own numbers and the diff against night-v5 |
| `finish_night.sh` | waits for the night to end, then measures it and writes its letter |

`run_night.py` is the night-v5 runner with the three changes the brief
asked for, and nothing else:

1. **The letter speaks the ledger** (the task-1 fix): the morning folds the ledger's own decision count
   (`decisions.ledger`, from `decision_counts.py` — one `judge.verdict`
   row per attempt, the routed cell's 240 probes and refusals included),
   the letter writer counts the ledger beside the morning when the block
   is absent, and `tests/night/test_letter_ledger.py` pins the letter's
   numbers to the ledger's.
2. **The ghost's second look, a parameter** — `--ghost-policy
   {second_look,drop,keep}`, default `second_look`: the prop's mesh is
   rendered (`render_prop_views.py`) and one DeepInfra VLM call answers
   the fixed question; the prop drops only if the cloud agrees. A second
   look that cannot answer is not agreement. Both verdicts ride one
   `night.ghost_second_look` row (`tests/night/test_ghost_policy.py`).
3. **The export that lands** — the committed `export_scene.py` with the
   measured flags (placeholder materials, subsurf 0, decimate-over 5k),
   the bound down from 4 h to 3600 s. The py-spy stack dump that found
   the real cost (the material node-tree search, not the triangles) is
   the story `docs/lab/night-v6.md` tells.

Everything night-v5 built is unchanged inside it: the GPU-pool bar
(48 GiB used, `lfb` recorded not gating), the wedge restart, the honest
peaks (6G/6G/40G→8G — the 40 GB heavy lease the only one above 30 GB,
held alone, phased down when the heavy phase ends), the library's ten
crates in the prior, the delegate's picture path.

## Running the night

    bash docs/lab/night-v6-scripts/launch_night.sh            # artifacts/night-v6

One command; it detaches the night and the finisher. The finisher writes
`measurements.txt/json` and `letter.md` when the night ends. Nothing else
should hold a >30 GB lease while the heavy phase runs.

## The probes worth re-running

    # the ghost's second look, on night-v5's own ghost
    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/second_look.py \
        --glb ~/lm-wt/trellis/out/genbatch/lantern_s1205_00008_.glb \
        --prompt "a brass lantern" --outdir /tmp/ghost-views

    # the export, from night-v5's own saved scene
    ~/lm-wt/v2-thor/.venv/bin/python docs/lab/night-v6-scripts/export_scene.py \
        --from-blend ~/lm-wt/night-v5/artifacts/night-v5/worldstream/export/scene.blend \
        --max-subsurf 0 --decimate-over 5000 --materials placeholder \
        --outdir /tmp/export-check

    # the decision count, from any night's ledger
    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/decision_counts.py \
        --ledger artifacts/night-v6/ledger.db
