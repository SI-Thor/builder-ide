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
| `pricing.py` | the **price**: a job kind as a task carries it — the ask (p50) and the rail (p95) |
| `admission.py` | the **admission check**: does tonight's plan fit, and what is cut, named |
| `estimates.py` | the **two lines** the owner reads this evening |
| `memory.py` | the **memory column**: how much memory a job kind takes, as the admission daemon measured it |
| `data/` | the measurements themselves — the sweep, the mini-night, the critic, the peaks |
| `measure_critic.py` | the one new measurement this package made |
| `extract_mini_night.py` | extracts the mini-night's lane splits from its ledger |
| `refresh.py` | re-pins the data when the box records something new |

## The job kinds, and where their numbers come from

Every kind is a set of **recorded samples**; the model turns them into a band
of `p50` (the median run) and `p95` (the bad one). Each band carries its
`basis` and its `source`.

| Job kind | What it is | Source | n |
|---|---|---|---|
| `prop.image` | one 1024² picture (SDXL base 1.0, 30 steps) | the mini-night's ledger | 9 |
| `prop.512` | one TRELLIS.2 prop at 512³ — **the generator alone**: the sampling and the mesh tail | `docs/research/trellis-spike.md` §4.2 | 2 |
| `prop.1024` | the same generator at 1024³ | the same two runs | 2 |
| `prop.night` | one prop as the *night* runs it: image → 3D → measured → judged | the mini-night's ledger | 9 |
| `prop.night.512` | one prop's **mesh stage** at 512³: the generator, the decode and the mesh tail | the second mini-night's ledger | 9 |
| `mesh.repair` | the repair stage on one mesh | the second mini-night's repairs | 9 |
| `prop.text` | the whole text path at 512³ (text → image → 3D) | the trellis spike §8 | 1 |
| `mesh.measure` | measuring one mesh — topology, winding, volume, area | `measure_critic.py` | 21 |
| `critic.verdict` | the critic's verdict on one variant | `measure_critic.py` | 21 |
| `rung.1` | the fast layout preview | `docs/research/warm-scene.md` §4.1 | 2 |
| `rung.2` | the mid still with lighting and materials | the sweep's render stage | 33 |
| `rung.3` | the full render (8192 spp, all passes) | `docs/research/spike-phase1.md` §3 | 1 |
| `infinigen.coarse` / `.fine` / `.render` | the Infinigen stages, **by scene type** | the seed sweep | 4–5 per cell |

Five kinds are **derived** rather than recorded: `prop.goal` (a picture, a
prop and a verdict, times the goal's depth), `scene.goal` (coarse, fine,
render), the two mesh-stage bands `prop.mesh.512` / `prop.mesh.1024` (below)
and `plan.intention` — an agent's proposal on the night's slate
(the world-mcp round): the proposal's own footprint, a slate row and the
owner's decision on it (the attention estimate, `basis: estimate`, marked
`[e]`; zero GPU, zero hosted cents). It prices the *proposal*, not the
work the proposal may seed — that work is priced by its own kind when the
night actually runs it, so a proposal cannot fatten the slate with work
it does not name.

### The mesh stage is the night, not the generator

`prop.mesh.512` is the band the prop seat's schedule prices the mesh stage
at, and it is **the second mini-night's own measurement of the whole stage**
— the prompt window (`prop.night.512`), plus the repair (`mesh.repair`) and
the measuring (`mesh.measure`).

It replaced `prop.512`, the spike's *bare generator*, and the difference
matters: the generator is the three KSamplers, while the night's mesh stage
also carries the decode stages, the mesh tail, the repair and the measuring.
The second night's ledger says the GPU lane of the stage is **3.4x** the
generator's, so pricing the stage at the generator's band sold the night's
rail three times too cheap. The regression test in
`tests/genbatch/test_schedule.py` holds the schedule to the night's number.

The 1024³ band is derived: the 512³ band plus the generator's own measured
resolution scaling (`prop.1024` − `prop.512`). The night's *other* work is
assumed not to scale, which is generous — the spike's per-node table shows
the decode stages do scale (4–5x) — so the 1024³ GPU lane is a **lower
bound**, and the band says so.

Both nights' GPU lanes were measured on a box shared with the seed sweep, so
they read high against a quiet box; the spike's quiet numbers read low
against a busy one. The bands are what the box actually did.

## The price: a kind as a task carries it

A task is not a job kind. `pricing.py` is the join between them:

```python
from core.night.cost import price_job

priced = price_job("prop.image")           # one picture
priced.ask    # Rail(gpu_minutes=0.233, hosted_cents=0, wall_minutes=0.278) — the p50
priced.rail   # Rail(gpu_minutes=0.397, hosted_cents=0, wall_minutes=0.427) — the p95
priced.basis  # "measured" — and priced.source says where it came from
```

* the **ask** is the p50: what the work usually costs.
* the **rail** is the p95: the ceiling the task is held to. The seat stops the
  work when it passes it (§5.5), so it is the *bad* case, not the usual one.
* the count is the night's: `price_job("prop.image", count=3)` is three p50s.

One rule on top: **the rail is never below the ask** (`hold_to`). An owner who
files their own number is held to *their* number, not to the model's, so an
override cannot smuggle work past the ceiling it is measured against.

**Who reads the model now.** The model's numbers are the only numbers:

| Caller | What it asks the model for |
|---|---|
| the plan slate (`core/svc/tasks.py`) | each goal's ask — its kind's p50 — and the bar (the spec's 360 GPU-min / 560 wall-min) |
| the night's start (`core/svc/nights.py`) | the same bar, and the two lines it writes into `night.started` |
| the prop seat's schedule (`core/genbatch/schedule.py`) | the image stage as `prop.image`, the mesh stage as the TRELLIS.2 kind for the request's resolution |
| the prop seat's executor (`core/genbatch/executor.py`) | the same price, so its plan and the task's ask are one measurement |

## The numbers this package found

* **The mini-night costs what the model says it costs.** Three props, three
  seeds each: the model prices the night at 10.3 GPU-minutes and 30.0 wall
  minutes; the second mini-night's own ledger records **9.421** and
  **30.129**. The model is within a tenth of the night that actually ran.
  The first mini-night's ledger records 9.156 and 24.640 — the same work,
  measured on a quieter box, and the model's band sits between the two.
* **The critic's verdict is free.** ~21 microseconds. The mesh *measurement*
  it reads is ~0.28 s — 13 000 times the verdict itself.
* **The spec's "about a minute" for rung 2 is the measured number** (63 s),
  not an estimate.
* **The mesh tail does not scale with resolution.** 512³ → 1024³ quadruples
  the GPU sampling (16.1 s → 65.9 s) and leaves the CPU tail alone
  (83.9 s → 91.3 s). The tail is ~80 s per prop, always.
* **The night's mesh stage is 3.4x the bare generator** (54.9 s of GPU lane
  against 16.1 s), because the night's job also carries the decode stages,
  the repair and the measuring. Pricing the stage at the generator's band
  sold the night's rail three times too cheap.

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
# ["Tonight: 1 goal — 0.1 GPU-h of the 6.0 h bar · 0.4 wall-h of the 9.3 h · $0.00 hosted (local) · 67.0 kJ on the rails",
#  "It fits, with 5.9 GPU-h to spare. Nothing is cut."]
```

Line one is the ask, in the owner's units. Line two is the verdict, and when
the plan does not fit it **names** what falls off the end. The night runner
writes both into `night.started`, so the morning can put them beside what
actually happened — and so does the API's night start, which is the other
door into the same night.

The **plan slate** shows them too, before the night starts: `/v1/slate` carries
the two lines, each goal's ask with where it came from (the kind it was
priced as, the model's marking, and whether the owner overrode it), and the
verdict with the cut named. A slate that does not fit is **refused** at the
door, with the cut named — the slate is left as it was, so the recovery is a
trim and a try again, not a night half spent.

## Running the tests

The repo's own venv, by the repo's convention (`INTEGRATION.md`):

```bash
.venv/bin/python -m pytest -q tests/night/test_cost.py tests/night/test_refresh.py
```

This branch was developed against the **integrated suite's** venv, which has
the same dependencies:

```bash
~/lm-wt/integrate-core/.venv/bin/python -m pytest -q tests/night/test_cost.py tests/night/test_refresh.py
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

# a night's per-job lane splits, out of its ledger
.venv/bin/python -m core.night.cost.extract_mini_night \
    > core/night/cost/data/mini_night.json

.venv/bin/python -m core.night.cost.extract_mini_night \
    --ledger ~/lm-wt/mini-night2/artifacts/mini-night-2/ledger.db \
    --night mini_night_2 --doc docs/lab/mini-night-2.md \
    > core/night/cost/data/mini_night_2.json
```

And the **refresh path** (`refresh.py`), which is the one to use when the box
has recorded something new — it copies the recording into `data/`, re-pins it
by md5 and row count in `data/recorded.json`, and patches the index in place
so a refresh is a changed number and not a reformatted file:

```bash
# re-pin the sweep snapshot (the default origin is the sweep's own path)
.venv/bin/python -m core.night.cost.refresh --sweep

# re-extract a night's lane splits from its ledger
.venv/bin/python -m core.night.cost.refresh --ledger ~/path/to/ledger.db

# has the recording moved on since the snapshot was pinned?
.venv/bin/python -m core.night.cost.refresh --check
```

The sweep snapshot in `data/infinigen_sweep.tsv` is copied verbatim from
`~/src/infinigen-thor/outputs/sweep/sweep.tsv`. **The sweep is still running**,
so the file is a snapshot of a moment, not the finished sweep: it carries its
row count and its checksum in `data/recorded.json`, and `--check` says
whether the recording has moved on since. Refresh it whenever the sweep has
recorded new timings, and the model's numbers follow.

## The memory column

The model answers *what a job costs*. The box runs out of **memory**, so the
model also needs to answer *how much memory a job takes* — and nobody had
measured that. The admission daemon (`tools/thor-admit`) does: every lease
records the peak resident set it reached, and writes one JSON line per
lease.

`memory.py` reads those lines and turns them into the same band the model
already speaks — a p50 and a p95, with the number of samples and the source
beside them — using the same percentile convention, so a number here and a
number in the model mean the same thing.

```python
from core.night.cost import default_memory_column

column = default_memory_column()
peak = column.peak_for("hog.4g")
peak.p50_bytes, peak.p95_bytes, peak.samples
```

**Where the numbers come from.** The daemon writes the live history to
`~/.local/state/thor-admit/peaks.jsonl` (or wherever `THOR_ADMIT_PEAKS`
points). `data/peaks.jsonl` is the snapshot kept in this package, so the
model's numbers all have a source in the repo:

| Label | What it is | Peak (bytes) | Source |
|---|---|---|---|
| `hog.4g` | the synthetic memory hog, 4 GiB asked for | 4 296 847 360 (4.0016 GiB) | 3 runs, `rusage` |
| `hog.8g` | the same hog, 8 GiB asked for | 8 591 884 288 (8.0017 GiB) | 1 run, `rusage` |
| `seat.py` | a plain Python seat process | 9 830 400 (9.4 MiB) | 1 run, `rusage` |

The hog is the daemon's own test instrument, not a production workload: the
real job kinds get their peaks as the seats take leases. The numbers above
are here to show the column works and to pin the convention; the rows for
`prop.*`, `rung.*` and `infinigen.*` arrive when those seats lease.

**Re-deriving it.** The snapshot is the daemon's own history file, copied:

```bash
cp ~/.local/state/thor-admit/peaks.jsonl core/night/cost/data/peaks.jsonl
```
