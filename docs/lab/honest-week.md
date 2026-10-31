# The honest week — seven nights on the real core, real renders behind the rungs

**Date:** 2026-10-31, 08:28–08:38 local (AKDT) — three complete runs (two
headless, one pytest), all green
**Verdict: RAN AS PLANNED** — the melt week played **106/106 steps with
Infinigen 2.0 behind every render rung**: **14 real Cycles renders**
(the world bet's render and the landed order's preview, each night),
**3.4–6.0 s a render, the whole week in 1.3 minutes of the 120-minute
budget**, budgeted from the cost model before it ran — and **the melt
table reproduced exactly** on the real engine: questions 6 → 0, attention
16 → 2, night four the honest miss, evening seven the earned line.

Plan item 14 (M2's gate): *seven nights against the integrated core with
a real render behind the rungs; capability rows; two-line estimates
everywhere; standing exits in every branch set; the decision budget at
the queue; the morning status line computed from the log.* The driver is
`tests/acceptance/week/realweek.py` (headless) and
`tests/acceptance/week/test_week_engine.py` (the opt-in `-m engine`
module); the budget layer both share is `tests/acceptance/week/
weekbudget.py`. The fake-engine week stays the default suite, unchanged.

---

## 1. What ran

The same seven nights the melt week plays (`tests/acceptance/week/`),
on the same one ledger — with `BUILDER_ENGINE` pointed at the **v2 venv
on this box** (`~/lm-wt/v2-thor`, read-only), so the engine seam
(`core/engine`) serves real work at every rung that renders:

| rung | what it is | how many | engine |
|---|---|---|---|
| the bet's render | the night's edit, rung 2 (960×540, 16 spp) through `render_job` | 7 | Infinigen 2.0 `render_cycles`, Cycles on the GPU |
| the order's preview | the landed work order's evidence render, rung 2 | 7 | the same |

Everything else is the melt week's own real code (the spine, the recipe
seam, the cold-start gate and sealer, the queue's dam and admission) and
its two honest stubs — the scripted critic (`verdict@scripted` on its
face) and the stub engineer. The session performs the **explicit pin
edit** first (X R9): `SI-Thor/infinigen-thor@9f31c0e →
princeton-vl/infinigen@224598d4…` — one edit, touching only the pin, so
every stage key changed with it before the first render ran.

The subjects resolved exactly as the seam's rule says: the bet renders
name the night's entry path (`harbor.crates`, `wood.weathering`,
`harbor.racks`); the previews pass the work order's id, which the seam
resolves to the recipe's **first entry** (the crates chain, seed 42) —
the documented fallback, never a fuzzy guess. The generator names are
the M1 real-run's stand-ins (`storage_cabinet_with_door_rand` & co.),
recorded in the run's provenance; the day the fork's own generators
land, the table changes and nothing else does.

**The box's state, beside the numbers** (the standing rule): load
average **15.4 → 18.2** on 14 cores — an Infinigen seed sweep (the cost
model's own data source) rendered on the GPU throughout, plus ComfyUI
resident; the whole-box **VIN rail read 38–41 W** at the run's ends.
Our renders rode beside the sweep's — which is why the walls below match
M1's real-engine run (4.3–5.5 s at load 22–23) rather than beating them.

## 2. The budget, from the cost model

The brief's constraint — *each night small enough that the week runs in
under ~2 hours* — was checked **before the week ran**, as arithmetic
over the recorded bands (`weekbudget.py`, at p95, the model's own rule:
build the plan against the bad run). Each night's plan is three jobs —
the bet render, the preview, the scripted verdict — against the melt
driver's rails (130 GPU-min · 420 wall-min):

> **Tonight: 3 goals — 0.1 GPU-h of the 2.2 h bar · 0.1 wall-h of the
> 7.0 h · $0.00 hosted (local) · 14.1 kJ on the rails**
> **It fits, with 2.1 GPU-h to spare. Nothing is cut.**

All seven nights fit; nothing was cut on the GPU axis (the week's one
cut is night one's **decision-budget** cut at the queue — 7 of 12 ask
cards, the morning sitting exactly at 10, never over it). The whole
week's ask: 34.63 GPU-min, ~99 kJ on the rails — and the week actually
took **1.3 minutes of wall**.

**The gap between estimate and measurement is the finding, not a
failure:** the measured renders cost **0.14–0.18 GPU-min a night**
(1.171 GPU-min the week) against a 4.95 GPU-min p95 ask — the `rung.2`
band's 33 samples are the sweep's **scene** render stages, and this
week's renders are **object** renders at the same rung. The band stays
the estimate (conservative by ~29× here) until object-render samples are
recorded in the model; the table names the basis rather than smoothing
it over. The morning's `the box` section now quotes the measured render
walls from the ledger (`render.completed.timing`), so the slate's `[e]`
fields are replaced by measurements where measurements exist.

## 3. The numbers — per night

| night | what ran | cut | est (p95) | measured | renders (bet + preview) | status (computed) | dec | att |
|---|---|---:|---:|---:|---|---|---:|---:|
| 1 | bet render + preview, rung 2 | 7 | 4.95 | 0.170 | 5.2 s + 5.0 s | ran short | 10 | 16 |
| 2 | " | 0 | 4.95 | 0.184 | 5.1 s + 5.9 s | ran degraded | 3 | 9 |
| 3 | " | 0 | 4.95 | 0.142 | 3.6 s + 4.9 s | ran degraded | 2 | 4 |
| 4 | " | 0 | 4.95 | 0.168 | 4.5 s + 5.5 s | ran degraded | 2 | 4 |
| 5 | " | 0 | 4.95 | 0.163 | 3.9 s + 5.9 s | ran degraded | 2 | 2 |
| 6 | " | 0 | 4.95 | 0.184 | 6.0 s + 5.1 s | ran degraded | 2 | 2 |
| 7 | " | 0 | 4.95 | 0.160 | 4.9 s + 4.7 s | ran degraded | 2 | 2 |
| **the week** | **14 real renders** | **7** | **34.63** | **1.171** | **3.4–6.0 s each** | — | — | **16 → 2** |

GPU-minutes here are the engine's own measured render walls (the model's
convention for a render stage: the GPU lane is the wall). The night's
**bar** carries the same measured numbers — the fake run's scripted
75 GPU-min spend is gone; the bar reads the ledger. The engineer's
20 GPU-min estimate stays what it is on every run: a stub's price,
marked `[e]`, claimed and recorded as the same estimate so the gate's
budget audit compares like with like.

**Joules are not claimed.** The rails were read (38–41 W whole box), but
the sweep shared the box all week, so attribution would be false; the
estimate's 14.1 kJ a night stands as the only joule figure, on the
model's rails. The whole-box reading beside it is the honest context.

## 4. The melt, reproduced on real renders

The melt table folded from the ledger is **identical to the fake run's**
— the mechanism is engine-independent, which is the point of item 14's
"reproduced or falsified from the ledger alone":

```
NIGHT  EVE-QS  TASTE BETS SEALED AS         WORLD BET             STATUS        DEC  ATT
------------------------------------------------------------------------------------------
1           6  guess·0 obs + guess·0 obs    guess·0 obs → hit     ran short      10   16
2           6  guess·1 observation          low·1/1 hit → hit     ran degraded    3    9
3           2  low·2/2 kept                 guess·0 obs → hit     ran degraded    2    4
4           2  guess·1 observation          low·2/2 hit → miss    ran degraded    2    4
5           0  low·1/2 kept                 guess·0 obs → hit     ran degraded    2    2
6           0  guess·1 observation          guess·0 obs → hit     ran degraded    2    2
7           0  low·2/2 kept                 medium·2/3 hit → hit  ran degraded    2    2
```

Night one's queue cut is named on the report (7 ask cards, "the morning's
decision budget is 10"); night four is the honest miss (`wrong_scale`,
the owner keeps yesterday — the standing exit taken as a choice); evening
seven renders the earned line with its denominator ("This is a guess.
You keep weathered wood over clean-sanded — 2/2 kept"). The mid-week
fold check (a gate rebuilt from the ledger alone) agreed on every
builder × code. Both standing exits were on every morning's board.

## 5. What the real run exposed — three findings, one bug fixed

1. **The kJ on the owner's lines was a thousandth of the real figure.**
   The first budgeted evening printed "**0.0 kJ** on the rails" for a
   plan that draws 14 kJ on the measured 47.5 W VIN rail. The cost
   package's `joules` fields hold **kilojoules** (pinned by its own
   tests), and both display lines — the evening's two-line estimate and
   the morning's four-number line — divided by 1000 a second time. Fixed
   in `core/night/cost/estimates.py` and `core/night/report.py`, with
   regression tests pinning the rendered arithmetic to the rails
   (`tests/night/test_cost.py`, `tests/night/test_report.py`).
2. **The `rung.2` band is scene-scale.** Its p95 (2.47 min) over-prices
   this week's object renders (~0.09 min) by ~29×. Conservative is safe
   for admission, but a band whose basis is that far from the work it
   prices should say so: the missing piece is a recorded `rung.2.object`
   kind fed by runs like this one (the walls are in the ledger).
3. **The melt-week driver's honesty was fake-engine-shaped.** Its step
   labels hardcoded `fake:engine(...)` and its night bar scripted a
   75 GPU-min spend whatever engine sat behind the seam — honest under
   the fake, false the day a real one was pointed at it. Both now come
   from the engine seat and the ledger (the fake run's table is
   unchanged); `render.completed` carries a `timing` row the morning's
   box section quotes.
4. *(Named, not fixed — a physical limit.)* The scripted critic's
   `timing` row on the event (`812 ms`, "measured on the stub rung") is
   an **authored stand-in**: a payload cannot contain the duration of
   the transaction that persists it, so the genuinely measured verdict
   write (~1 ms) rides the run's own tables instead
   (`rec["critic_verdict_ms"]`), and the event's row keeps its label.

## 6. Honest limits

* **Previews are not promised byte-reproducible** (Cycles' GPU
  accumulation can move pixels by ±1 LSB); the bet renders' artifacts
  are content-hashed PNGs, 395–910 KB each, magic-checked by the test.
* **The critic and the engineer are still stubs** — the week's two named
  missing pieces, unchanged from M1; every verdict wears
  `verdict@scripted`, which is why six of seven status lines read
  "ran degraded" (honestly).
* **The renders are the objects, not the room**: rung 2 of the ladder at
  960×540/16 spp, one subject a render. The room-scale rungs (and the
  stage cache behind them) are the M3 path; the seam is the same one.
* **The two estimate lines are not yet a spine event** — the runner
  writes them into `night.started` on its own path; the week's evenings
  carry them in the run's record. A named gap, like the parked-task line.

## 7. How to reproduce

```sh
# the fake week — the default suite, no engine required
.venv/bin/python -m pytest tests/acceptance/week -q

# the honest week — the v2 venv on the box, ~1.5 min, real renders
.venv/bin/python tests/acceptance/week/realweek.py            # headless; prints everything
.venv/bin/python -m pytest tests/acceptance/week -m engine -q # the same run, asserted
```

The record lands in `tests/acceptance/week/run/engine/week.txt`
(gitignored): the step table with `real:engine(render)` on all fourteen
render steps, the melt table, the budget table with the two lines, the
engine's own pin, and the box states. Without the venv the run skips,
naming the missing piece.
