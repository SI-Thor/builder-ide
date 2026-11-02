# night-v5-scripts

The runner for **night-v5**, the third integrated night
(`docs/lab/night-v5.md`), the script that builds its library, and the
scripts that write the morning's letter.

## What is here

| file | what it is |
|---|---|
| `run_night.py` | the night, end to end: one ledger, one runner, every layer real |
| `build_library.py` | the library's approved set: ten measured crates, one kind (built **once**, before the night) |
| `approved-crate-library.json` | what `build_library.py` wrote; the runner reads it |
| `measure_llama_gpu.sh` | one llama-server's GPU at rest, under the night's flags and smaller ones (inherited from the stopped seat; superseded by the probe below) |
| `measure_llama_gpu_under_load.py` | the same servers under the night's own request shapes — the numbers the night's flags and lease peaks stand on |
| `courtyard_requests.json` | the three props the owner asked for |
| `write_letter.py` | reads `morning.json` (or the ledger), writes `letter.md` (at most 150 words) |
| `facts_from_ledger.py` | transcribes the ledger into `letter-facts.json` |
| `measure.py` | the night's own numbers and the diff against night-v4's run F |
| `finish_night.sh` | waits for the night to end, then measures it and writes its letter |
| `results/` | the probe's raw outputs (server logs and stdout) |

`run_night.py` is the night-v4 runner with the changes the brief asked
for, and nothing else. The diff against
`docs/lab/night-v4-scripts/run_night.py` is the change:

1. **The GPU-pool bar** — before every mesh prompt the night waits until
   tegrastats' `lfb` (the largest free *contiguous* block of the GPU
   allocation pool, the same number the daemon's samples read) clears
   4 GB. Bounded at 45 minutes; every real wait is a `night.gpu_pool_bar`
   row.
2. **The wedge restart** — a `ComfyError` that says the server refused
   the connection (121 times over 120 s is the diagnosis run F left) is a
   wedged server, not a busy one: stop ComfyUI, keep its log beside the
   run, start it again, re-run the one prompt, once — at most two
   restarts a night, each a `night.comfy_restart` row.
3. **Honest peaks** — the two decision servers start under 6 GB leases
   (measured: 3.09/2.39 GiB GPU + <1.1 GB RSS), so the 40 GB heavy lease
   is the one lease above 30 GB and it is held alone; the servers run
   `--ctx-size 4096 -ub 1024` (same class of GPU, 1.8x faster on the
   delegate's picture questions).
4. **The library** — ten approved crates of one kind go into the prior
   as a labeled group, so the ghost gate (0.05) can fire on that kind
   (`night.library` row).

## How to run it

The library first (once, about 25-40 minutes):

```bash
cd ~/lm-wt/night-v5
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v5-scripts/build_library.py
```

Then the night (about 2.5-3 hours on a quiet box; `--dry-run` runs the
whole wiring on the fake engine in about a second):

```bash
cd ~/lm-wt/night-v5
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v5-scripts/run_night.py --out artifacts/night-v5
```

Then the letter and the measurements:

```bash
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v5-scripts/write_letter.py --out artifacts/night-v5
```

## What it needs

- **The Thor.** The v2 render, ComfyUI, TRELLIS.2 and the two decision
  servers all run here. Nothing reaches the network except the Jev rung
  and the mediator.
- **The models**: `~/models/d1-3B/d1-3B-Q8_0.gguf` and
  `~/models/d1-2B/d1-2B-Q8_0.gguf` with `mmproj-d1-2B-Q8_0.gguf`.
- **A lease.** The night takes its own: a 6 GB lease for each decision
  server's start and one 40 GB lease for the whole heavy phase, phased
  down to 8 GB when the heavy phase ends. The flock is the fallback only.
- **`XLA_PYTHON_CLIENT_PREALLOCATE=false`** in the environment of
  anything that starts a framework: on this box the GPU memory is system
  memory.

## What it writes

Into `--out` (the same set as night-v4, plus the wedge logs if the
restart ever fires): `morning.json`, `report.*`, `morning.txt`,
`what-happened.txt`, `decoy-cell.json`, `letter.md`, `ledger.db`,
`run.log`, `world/`, `worldstream/`, `comfy-wedge-*.log`.

`artifacts/` is not in git. The lab record (`docs/lab/night-v5.md`)
carries the numbers, and this directory carries the scripts that
produced them.
