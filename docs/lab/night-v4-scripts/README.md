# night-v4-scripts

The runner for **night-v4**, the second integrated night
(`docs/lab/night-v4.md`), and the script that writes the morning's letter.

## What is here

| file | what it is |
|---|---|
| `run_night.py` | the night, end to end: one ledger, one runner, every layer real |
| `courtyard_requests.json` | the three props the owner asked for |
| `write_letter.py` | reads `morning.json`, writes `letter.md` (at most 150 words) |

`run_night.py` is the night-v3 runner with the four changes the brief
asked for. The diff against `docs/lab/night-v3-scripts/run_night.py` is the
change, and nothing else.

## How to run it

On the Thor, from the night-v4 worktree, in the propmaker-batch venv:

```bash
cd ~/lm-wt/night-v4
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v4-scripts/run_night.py --out artifacts/night-v4
```

`--dry-run` runs the whole wiring on the fake engine and the fake judge:
no services, no props, no live view. It takes about a second.

Then the letter:

```bash
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v4-scripts/write_letter.py --out artifacts/night-v4
```

## What it needs

- **The Thor.** The v2 render, ComfyUI, TRELLIS.2 and the two decision
  servers all run here. Nothing in the night reaches the network except the
  Jev rung (the cloud judge, reached only when the local model is below
  τ) and the mediator.
- **The models**: `~/models/d1-3B/d1-3B-Q8_0.gguf` (the night's decision
  model) and `~/models/d1-2B/d1-2B-Q8_0.gguf` with
  `~/models/d1-2B/mmproj-d1-2B-Q8_0.gguf` (the critic's delegate, which
  has to see pictures).
- **A lease.** The night takes its own: `thor-admit` with a 40 GB peak for
  the heavy phase, phased down to 8 GB when the heavy phase ends. The
  flock is the fallback only, and the row says which one held.
- **`XLA_PYTHON_CLIENT_PREALLOCATE=false`** in the environment of anything
  that starts a framework: on this box the GPU memory is system memory.

## How long it takes

About 2.5 hours of wall time on a quiet box (run D: 152.6 minutes, 30
minutes of which were the props' TRELLIS runs and the rest the world's
two v2 renders). The lease's own wait is the box's business and is
recorded in the ledger (`night.heavy_lease`, `waited_s`).

## What it writes

Into `--out`:

| file | what |
|---|---|
| `morning.json` | the morning, folded from the ledger |
| `report.json`, `report.txt`, `report.html` | the core's report |
| `morning.txt` | the morning as text |
| `what-happened.txt` | the line the night would say out loud |
| `decoy-cell.json` | the routed cell, asked on this box |
| `letter.md` | the Biographer's letter (written by `write_letter.py`) |
| `ledger.db` | the ledger: every decision, every lease, every row |
| `run.log` | the log |
| `world/`, `worldstream/` | the world's renders and the live view's build |

`artifacts/` is not in git. The lab record (`docs/lab/night-v4.md`) carries
the numbers, and this directory carries the scripts that produced them.
