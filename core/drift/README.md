# `core/drift` — what "off track" means, measurably

The world's drift detector: the six signals of
`docs/design/vibecode-in-world.md` §3.4, each a **rate** gate with
hysteresis, and the three levels of auto-pause of §3.5.

The measurement that chose the defaults is
[`docs/lab/exp-drift-detector.md`](../../docs/lab/exp-drift-detector.md).

## What it is

```python
from core.drift import DriftConfig, DriftDetector, build_series

series = build_series("/home/caseydigennaro/lm-wt/agent-world/runtime/world-ledger.sqlite3")
detection = DriftDetector(DriftConfig()).run(series)

for alarm in detection.alarms:
    print(alarm.at, alarm.level, alarm.agent, alarm.reason)
```

`build_series` opens the ledger **read-only** and folds it into five-minute
windows. `DriftDetector.run` walks every signal's gate over those windows
and returns the alarms.

## What it owns

| module | what it owns |
|---|---|
| `ledger.py` | reading the world's ledger and folding it into windows |
| `signals.py` | the six signals, and which of them the ledger can carry |
| `gate.py` | the gate: the band, the dwell, and the level-against-rate choice |
| `detect.py` | the run, and the pause ladder |
| `pause.py` | the ladder wired to action: the pause file the world reads, and the thor-admit presence door |
| `config.py` | every number, with the reason it is that number |

## The six signals

| signal | scope | in the ledger? |
|---|---|---|
| stall time rising | per agent | yes |
| success rate falling | per agent | yes |
| error bursts | the world | yes |
| rule violations | per agent | **no** — the seam is wired, the ledger carries none |
| spend per productive decision | per agent | partly — the ledger's own cost fields |
| build drift | a branch | **no** — the world does not commit to the canon yet |

## The yields: a wait the world chose is not a stall

The world writes a `drift.yield` event every time it stands aside — the
box's admission rule (`may_act`: keep 25 GB free), or a drift pause —
naming the bots it told to wait (`agent-world/reflex/.../service.py`).
The folding honours it: **a gap with a yield inside it is not stall
evidence**, and a window an agent spent standing aside has its idle
excused. What is left is the silence nobody explained. The numbers are
in `docs/lab/exp-drift-pause.md`: the negative control 5 of 12 → 3 of
12 on the same thresholds, the holdout 6/6 unchanged.

## The pause, wired to action

`pause.py` turns one window of the detector's state into §3.5's three
levels, and carries it out through two doors, neither of which kills
anything:

* the **pause file** (`drift-pause.json` in the world's runtime) — the
  world reads it at its admission seam and yields politely: `soft`
  holds one bot, `tier`/`hard` stand the whole world aside. Every
  refusal is recorded as a `drift.yield`.
* the **thor-admit presence file** — `tier` demotes the mapped labels
  one tier (`live` → `preparation` → `practice` → `study`); `hard`
  also disables them (no new proposals). Running leases are untouched;
  a demotion changes what starts next.

An entry lapses when its `until` passes; `tools/drift/enforce.py
--clear <actor> --enforce` resumes at once. **Dry-run is the default**
— `enforce.py` computes and logs; `--enforce` writes.

## The gate, and the one decision it makes

Every signal produces a *badness* — a number where higher is worse — and
the gate compares it to a threshold in one of two ways:

* `mode=RATE` (the default, and what §3.4 asks for): fire when the badness
  **rose**. The rise is **one-sided**: only a rise is drift, a fall is
  recovery.
* `mode=LEVEL`: fire when the badness is bad now.

The band-and-dwell mechanism is `core/hysteresis`'s, reused as it is; the
detector adds one door to it, `reset_pending()`, so that a window with no
reading drops a pending transition instead of carrying it across the gap.

`mode=HYBRID` fires on the rise and holds while the level is bad. It is
there for a signal that settles instead of wobbling; on the world's current
signals it did not beat the rate gate, and the lab note says so.

## The pause ladder

| what happened | level | what it means |
|---|---|---|
| one agent's signal drifted | **soft** | that agent waits on its own safe branch |
| the world's own signal drifted, or two agents at once | **tier** | the world's work is demoted from `live` to `preparation` |
| a rule violation | **hard** | the doors close; nothing commits to `main` |

The hard signal is **not** scored with the others: no threshold, no band,
no dwell. One occurrence escalates immediately.

## The baselines are frozen

Each agent's baseline is its own reference over the reference period, and it
does not follow the run. A baseline that follows the drift becomes the new
normal and the drift stops being visible — which is the difference between a
detector and a mirror.

## Running it

```bash
~/lm-wt/core-api/.venv/bin/python -m pytest tests/drift -q    # 46 tests
```

The dataset, the calibration and the pause list are in
[`docs/lab/drift-dataset/`](../../docs/lab/drift-dataset/); the tools that
make them are in [`tools/drift/`](../../tools/drift/README.md).
