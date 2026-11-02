# rewind-select-scripts — the apparatus behind exp-rewind-select.md

The script that produced the numbers in
[`docs/lab/exp-rewind-select.md`](../exp-rewind-select.md): the cost per
hour of world of the rewind machinery, and the Bevy proof that the fork and
the replay agree.

| file | what it is |
|---|---|
| `exp_rewind_select.py` | the whole measurement: the world's ledger, one cherry-pick over a canon, and the Bevy fork |
| `results/rewind-select.json` | the numbers as the script wrote them, with the box state beside them |

## Running it

```bash
cd ~/lm-wt/rewind-select
export PATH=$HOME/last-mile/target/release:$PATH

.venv/bin/python docs/lab/rewind-select-scripts/exp_rewind_select.py \
    --ledger ~/lm-wt/agent-world/runtime/world-ledger.sqlite3 \
    --lm ~/last-mile/target/release/lm \
    --out docs/lab/rewind-select-scripts/results/rewind-select.json
```

**It needs**: the world's ledger (read read-only — it is live and is never
locked) and the `lm` binary from the `last-mile` repository. No GPU, no
model, no network: the Bevy world is a fixed-point simulation.

**It takes**: about a minute. Most of it is the world's ledger (91k rows,
124 MB) being read and selected over; the Bevy part plays and replays
three headless rounds, which is about a second of CPU.

**It writes**: one JSON file, with the box state (load average, CPUs,
available memory) beside the numbers, so a reader can tell how busy the box
was when the timings were taken.

**It changes nothing**: the world ledger is opened `mode=ro`; the Bevy
rounds and the canon are written into a temporary directory that is removed
when the script ends.
