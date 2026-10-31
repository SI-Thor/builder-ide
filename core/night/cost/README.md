# The night's arithmetic

The measured cost table, and the two questions the owner asks before a night
starts: **what will tonight cost**, and **does it fit**.

Plan item 17 (*`docs/plan.md`*, draft 2) is what this package is for: the
night's budget stops being a set of typed-in numbers and becomes arithmetic
over measurements taken on this box.

## What it holds

| Piece | What it answers |
|---|---|
| `records.py` | the recorded measurements, and where each one came from |
| `model.py` | the **cost model**: what each job kind costs, p50 and p95 |
| `admission.py` | the **admission check**: does tonight's plan fit, and what is cut, named |
| `estimates.py` | the **two lines** the owner reads this evening |
| `data/` | the measurements themselves — the sweep, the mini-night, the critic |
| `measure_critic.py` | the one new measurement this package made |
| `extract_mini_night.py` | extracts the mini-night's lane splits from its ledger |

## The job kinds, and where their numbers come from

Every kind is a set of **recorded samples**; the model turns them into a band
of `p50` (the median run) and `p95` (the bad one). Each band carries its
`basis` and its `source`.

| Job kind | What it is | Source | n |
|---|---|---|---|
| `prop.image` | one 1024² picture (SDXL base 1.0, 30 steps) | the mini-night's ledger | 9 |
| `prop.512` | one TRELLIS.2 prop at 512³ — the sampling and the mesh tail | `docs/research/trellis-spike.md` §4.2 | 2 |
| `prop.1024` | the same generator at 1024³ | the same two runs | 2 |
| `prop.night` | one prop as the *night* runs it: image → 3D → measured → judged | the mini-night's ledger | 9 |
| `prop.text` | the whole text path at 512³ (text → image → 3D) | the trellis spike §8 | 1 |
| `mesh.measure` | measuring one mesh — topology, winding, volume, area | `measure_critic.py` | 21 |
| `critic.verdict` | the critic's verdict on one variant | `measure_critic.py` | 21 |
| `rung.1` | the fast layout preview | `docs/research/warm-scene.md` §4.1 | 2 |
| `rung.2` | the mid still with lighting and materials | the sweep's render stage | 33 |
| `rung.3` | the full render (8192 spp, all passes) | `docs/research/spike-phase1.md` §3 | 1 |
| `infinigen.coarse` / `.fine` / `.render` | the Infinigen stages, **by scene type** | the seed sweep | 4–5 per cell |

Two kinds are **derived** rather than recorded: `prop.goal` (a picture, a
prop and a verdict, times the goal's depth) and `scene.goal` (coarse, fine,
render).

## The numbers this package found

* **The mini-night costs what the model says it costs.** Three props, three
  seeds each: the model prices the night at 8.3 GPU-minutes and 23.5 wall
  minutes; the mini-night's own ledger records **9.156** and **24.640**. The
  model is within 10 % of the night that actually ran.
* **The critic's verdict is free.** ~21 microseconds. The mesh *measurement*
  it reads is ~0.28 s — 13 000 times the verdict itself.
* **The spec's "about a minute" for rung 2 is the measured number** (63 s),
  not an estimate.
* **The mesh tail does not scale with resolution.** 512³ → 1024³ quadruples
  the GPU sampling (16.1 s → 65.9 s) and leaves the CPU tail alone
  (83.9 s → 91.3 s). The tail is ~80 s per prop, always.

## The units

* `gpu_minutes` — the GPU lane. The scarce axis (§5.5): a cheap CPU-lane
  hour does not eat the GPU bar.
* `cpu_lane_minutes` — the CPU lane. Free, but not free to *run*.
* `wall_minutes` — the wall time the job owns, end to end.
* `hosted_cents` — money spent outside the box. Zero for every local model;
  the axis exists so a hosted engine can be priced honestly.
* `joules` — the energy, from the board's **measured power rails**:
  the whole-box `VIN` rail (47.5 W) over the job's wall time.
  `joules_above_idle` is the other reading — above the box's 26.5 W idle
  floor — and it comes out `None` when the work is too small to dominate the
  box, in which case the wall time is the number to read
  (`docs/lab/IDEAS.md` #17).
* `iterations` — how many iterations of the kind one goal costs.

**The rails themselves** (`docs/lab/exp-engines.md` §4.4): `VIN` 47.5 W
(whole box), `VDD_GPU` 20.85 W, `VDD_CPU_SOC_MSS` 8.27 W, `VIN_SYS_5V0`
8.69 W. The board's own I²C sensors and `tegrastats` agree to within 0.1 %.

## The one estimate

`attention_minutes_per_decision` (15 min) is an **estimate**, and it is the
only estimated number in the model. Nobody has measured how long a decision
takes the owner yet; the page marks it `[e]` and it stays marked until a
morning measures it.

## The admission check

```python
from core.night.cost import NightPlan, PlannedJob, admission_check
from core.night.models import Rail

plan = NightPlan(jobs=[
    PlannedJob(id="prop:crate", intention="prop a crate",
               ask=Rail(gpu_minutes=8.3, hosted_cents=0, wall_minutes=23.5)),
])
check = admission_check(plan, Rail(gpu_minutes=360.0, hosted_cents=0, wall_minutes=560.0))
check.fits            # True
check.cut_names       # [] — and when it does not fit, the names are here
```

It is the same arithmetic the night runner does when it admits a job, in the
same order, with the same reasons — so a plan that says it fits and a night
that then cuts something are the same fact told twice, and they cannot
disagree.

Three outcomes: **admitted**, **cut** (a rail cannot cover it; it is
re-queued for another night and the reason names the ask and what was left),
**parked** (the model it needs has hit its load cap; it waits for the model
to drain).

## The two lines

```python
from core.night.cost import owner_estimate

estimate = owner_estimate(plan, rails)
estimate.lines()
# ["Tonight: 1 goal — 0.1 GPU-h of the 6.0 h bar · 0.4 wall-h of the 9.3 h · $0.00 hosted (local) · 0.4 kJ on the rails",
#  "It fits, with 5.9 GPU-h to spare. Nothing is cut."]
```

Line one is the ask, in the owner's units. Line two is the verdict, and when
the plan does not fit it **names** what falls off the end. The night runner
writes both into `night.started`, so the morning can put them beside what
actually happened.

## Running the tests

The repo's own venv, by the repo's convention (`INTEGRATION.md`):

```bash
.venv/bin/python -m pytest -q tests/night/test_cost.py
```

This branch was developed against the **integrated suite's** venv, which has
the same dependencies:

```bash
~/lm-wt/integrate-core/.venv/bin/python -m pytest -q tests/night/test_cost.py
```

The tests check the model against the recorded files, against the documents
the numbers came from, and against the one night that actually ran. The
p50 and p95 are checked against the *record* rather than against the model,
so a percentile that quietly became a median fails the suite.

## Re-deriving the data

```bash
# the critic's verdict, timed on the mini-night's own assets
.venv/bin/python -m core.night.cost.measure_critic \
    --repeats 7 > core/night/cost/data/critic_verdict.json

# the mini-night's per-job lane splits, out of its ledger
.venv/bin/python -m core.night.cost.extract_mini_night \
    > core/night/cost/data/mini_night.json
```

The sweep snapshot in `data/infinigen_sweep.tsv` is copied verbatim from
`~/src/infinigen-thor/outputs/sweep/sweep.tsv`. **The sweep was still running
when the snapshot was taken**, so the file carries its row count and its
checksum in `data/recorded.json`; refresh both together when the sweep
finishes.
