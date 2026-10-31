# Mini-night 2 — the cost model prices the slate, the repair makes solids

**2026-10-31, 09:00 → 09:32 AKDT on the Thor.** The same three requests as
the first mini-night, three seeds each, behind the core's night runner —
now with the cost model pricing the slate *before* it runs, and the mesh
repair in the pipeline.

The first mini-night's ledger said the props were not solids: nine props,
nine meshes with holes in them, the critic scoring them on everything else
while the one thing that makes a prop a prop was worth nothing. This night
repaired them before the critic saw them.

**What it found:**

1. **The repair works, completely.** 0 of 9 props were watertight before;
   **9 of 9 are watertight after**. The silhouette IoU against the mesh the
   generator handed over was **0.99992 – 1.00000** (the recipe's floor is
   0.98), and the repair cost **3.1 – 3.8 s** a prop.
2. **No winner changed** — and now I know why it *couldn't*: the repair
   adds the same thing to every variant, so it shrinks every gap by a
   factor of 12/13 and cannot flip one.
3. **The cost model's picture band is right to within 2 %.** Its prop band
   is **3.4× under**, and the reason is specific and fixable: the schedule
   prices the mesh stage as `prop.512` — the *bare generator*, from two
   spike runs — when the night's mesh stage is the generator **plus** the
   repair, the measurement and the judging. The model already has the right
   band (`prop.night`); the schedule does not use it.
4. **The GPU bar got tighter and the wall overrun got bigger.** The cost
   model's ask is 9.1 GPU-min smaller than the old policy's, and the night
   spent 80.1 % of the new bar. One bad night from cutting work.

---

## 1. What ran

| | |
|---|---|
| the night | `mini-night-2`, 6 tasks, 18 variants (9 image + 9 mesh), one prompt at a time |
| the driver | `python -m core.genbatch --requests examples/mini_night_requests.json`, the seat's own venv (`~/lm-wt/propmaker-batch/.venv`, read-only), `PYTHONPATH` pointing at this worktree |
| the generator | the TRELLIS.2 spike's ComfyUI service, `--use-pytorch-cross-attention --cache-none` |
| the rules | the night's own: `batch_by_model`, `cpu_mesh_tail`, `no_overlap`, `costs_from_the_model` |

**The box's state, beside the numbers** (the spike's rule — a wall-clock
without the load beside it is not comparable):

| | before | after |
|---|---|---|
| load average (14 cores) | **26.42 / 23.11 / 21.04** | 14.97 / 21.13 / 22.59 |
| GPU | 0 %, 2.76 W, 45 °C | 0 %, 2.36 W, 47 °C |
| memory | 30.5 GB used of 125.7 GB | — |
| on the GPU | only our ComfyUI (285 MB) | only our ComfyUI (285 MB) |

The seed sweep on the Infinigen side was running throughout, and it took
the CPU with it: **the box was twice as loaded as the night the cost model
was fitted on** (load 13.4 → 11.1 in mini-night 1). The GPU showed only
our ComfyUI at both ends of the night, but the CPU lane was not ours
alone. That difference is the whole story of the wall-clock, below.

## 2. The numbers

End to end (the driver process, `/usr/bin/time -v`): **30:42.78** wall,
403 MB peak RSS, 47.3 s user CPU. The night's own accounting, folded from
its ledger:

| | |
|---|---|
| prompts | 18 (9 image + 9 mesh), **0 overlapping windows** |
| wall (sum of prompt windows) | 1,808 s |
| GPU lane | 565 s (**31 %**) |
| CPU lane | 1,228 s (**68 %**) — the mesh tail |
| model loads | `sd_xl_base_1.0: 1`, `trellis2: 1` (the load cap held) |
| GPU rail spent | **9.42 of 11.76 min (80.1 %)** |
| wall rail spent | 30.13 of 37.73 min (79.9 %) |
| tasks | 6 of 6 `kept`, 0 failed, 0 cut, 0 parked |
| status line (computed) | `ran as planned / nothing failed` |

The ask, before the night ran:

> Tonight: 6 goals — 0.1 GPU-h of the 0.2 h bar · 0.3 wall-h of the 0.6 h ·
> $0.00 hosted (local) · 52.7 kJ on the rails
> It fits, with 0.1 GPU-h to spare. Nothing is cut.

Per stage — the ask is the cost model's p50 for the stage's kind, the
measurement is what the night actually spent:

| task | ask GPU | measured GPU | × | ask wall | measured wall | × |
|---|---:|---:|---:|---:|---:|---:|
| img:crate | 0.699 | 0.697 | **1.00** | 0.834 | 0.820 | 0.98 |
| img:lantern | 0.699 | 0.683 | **0.98** | 0.834 | 0.795 | 0.95 |
| img:anvil | 0.699 | 0.776 | 1.11 | 0.834 | 0.878 | 1.05 |
| prop:crate | 0.804 | 2.871 | **3.57** | 5.328 | 9.735 | 1.83 |
| prop:lantern | 0.804 | 2.313 | **2.88** | 5.328 | 8.174 | 1.53 |
| prop:anvil | 0.804 | 2.081 | **2.59** | 5.328 | 9.727 | 1.83 |
| **total** | **4.508** | **9.421** | **2.09** | **18.487** | **30.129** | **1.63** |

Per variant, measured (from the ledger's own spend):

| | GPU (s) | wall (s) |
|---|---:|---:|
| the 9 images | 11.8 – 20.3 (median 14.0) | 13.3 – 22.2 (median 16.1) |
| the 9 props | 18.3 – 65.9 (median 54.9, mean 48.4) | 131.2 – 241.6 (median 180.5, mean 184.2) |

## 3. The morning

| request | winner | score | beat | the critic's reason |
|---|---|---:|---|---|
| crate | `prop:crate_r1_v1` (seed 1064508603) | **1.000** | `v2` (0.960), `v3` (0.979) | every check passed |
| lantern | `prop:lantern_r1_v1` (seed 424809304) | 0.939 | `v2` (0.924), `v3` (0.939) | `bbox_aspect`: 0.996:0.973:1.000 against 0.650:1.000:0.500 — 100 % off on z |
| anvil | `prop:anvil_r1_v2` (seed 64961400) | 0.918 | `v1` (0.910), `v3` (0.911) | `bbox_aspect`: 0.998:0.971:1.000 against 1.000:0.500:0.400 — 150 % off on z |

All three: **watertight**, 698,414–698,962 triangles, and the repair in the
provenance (`welded 95,636 – 122,563 coincident vertices, took out 2 – 8
zero-volume flaps, split 0 pinched vertices and 0 self-crossing edges; the
outline is 1.0000 of the original`).

## 4. The repair, on all nine

The night's report carries the repair for the three winners. The wider
question — how many of the nine were solids — is measured after the fact by
`docs/lab/mini-night-2-scripts/measure_repairs.py`, which reads each GLB,
measures the mesh the way the pipeline measured it, runs the same recipe,
and measures again:

| | before the repair | after the repair |
|---|---|---|
| watertight | **0 of 9** | **9 of 9** |
| boundary edges | 182,726 – 331,576 per prop | **0** |
| self-crossing edges split | — | 0 |
| pinched vertices split | — | 0 |
| silhouette IoU (floor 0.98) | — | **0.99992 – 1.00000** |
| the repair's cost | — | **3.1 – 3.8 s** a prop |

Not one prop lost its shape: the repaired silhouette is the original's to
within 0.008 %, which is what the fidelity floor is there to protect.

## 5. Why no winner changed

The critic's score is `Σ(weight × score) / Σ(weight)` over the checks that
apply. The repair changes the denominator: without it the fidelity check
does not apply, so the weights sum to 12; with it they sum to 13. And it
changes the numerator: watertight goes from 0 (weight 3) to full marks.

For two variants that failed the same weight `F`:

```
night 1:  (W − F) / 12          night 2:  (W − F + 1) / 13
```

The gap between them goes from `(F₂ − F₁)/12` to `(F₂ − F₁)/13` — **smaller,
but the same sign.** A repair that helps every variant the same amount
cannot reorder them. That is not a lucky outcome; it is arithmetic, and it
is why the same three seeds won.

| | night 1 | night 2 | Δ |
|---|---:|---:|---:|
| prop:crate | 0.749936 | 0.999937 | +0.250 |
| prop:lantern | 0.684319 | 0.939372 | +0.255 |
| prop:anvil | 0.660653 | 0.917528 | +0.257 |

The winners are the same three seeds in the same order, and the runner-ups
are the same variants behind them. What changed is the *floor*: a prop that
scores 0.92 because its aspect is wrong is a different thing from a prop
that scores 0.92 because it is a solid with a slightly wrong aspect.

## 6. What the cost model got wrong, and why

The image stage's band is excellent — `prop.image`'s p50 is 0.233 GPU-min
(14.0 s) and 0.278 wall-min (16.7 s); tonight's images measured a median
**14.0 s** GPU and **16.1 s** wall. Within 2 %.

The prop stage's band is not:

| band | p50 GPU | p50 wall | samples | tonight's prop median |
|---|---:|---:|---:|---|
| `prop.512` — **what the schedule used** | 16.1 s | 106.6 s | 2 | 54.9 s / 180.5 s → **3.4× / 1.7× under** |
| `prop.night` — the mini-night's own prop jobs | 41.5 s | 139.8 s | 9 | **0.86× / 0.76×** |

The cause is a kind mismatch, and it is specific. `core/genbatch/schedule.py`
prices the mesh stage with:

```python
MESH_KIND = "prop.512"
```

and `prop.512`'s two samples are the TRELLIS.2 spike's **bare generator**
runs (`512_bf16_a`, `512_bf16_b`: GPU 16.02 / 16.13 s, wall 114.77 / 98.35 s)
— the ComfyUI workflow and nothing else. But the night's mesh stage is not
the bare generator. It is the generator **plus**:

* the **repair** (3.1 – 3.8 s), and
* the **mesh measurement** and the **judging** that follow it.

The model already knows this shape of work — it is called `prop.night`, it
is priced from the mini-night's own nine prop jobs, and it was sitting in
`core/night/cost/data/recorded.json` the whole time. The schedule prices
the wrong band.

**The fix is one line** — for 512³, `MESH_KIND = "prop.night"`. For 1024³
the same shape is needed at a different resolution, so the honest fix is a
band for "the generator plus the measuring" *per resolution* rather than
the bare generator's band with the night's extra work left out of it.

Two smaller things the night showed:

* **The booked cost does not include the repair or the measurement.** The
  mesh task books the ComfyUI prompt's wall and GPU, and the repair and
  the measuring happen after the prompt returns. So ~3.6 s a variant —
  about 2 % of a prop, 30 s across the night — is work no rail can see.
* **The bar is now tighter than the box's variability.** The cost model's
  ask is 9.1 GPU-min smaller than the old hardcoded policy's, which moves
  the GPU bar from 18.5 min to 11.76 min. Tonight's spend was 80.1 % of
  it. The policy's 1.5× + 5 min headroom was sized against a bar that was
  57 % too big; against the model's own ask, one busy night cuts work.

## 7. What changed since mini-night 1

| | night 1 | night 2 | what it is |
|---|---:|---:|---|
| driver wall | 24:43.77 | **30:42.78** | +24 % |
| prompt wall | 1,478 s | 1,808 s | +330 s |
| GPU lane | 549 s (37 %) | 565 s (31 %) | **+16 s (+2.9 %)** |
| CPU lane | 917 s (62 %) | 1,228 s (68 %) | **+311 s (+34 %)** |
| GPU spend | 9.156 min | 9.421 min | +3 % |
| GPU bar | 18.5 min | **11.76 min** | the cost model's ask, not a typed number |
| wall overrun | 0 min | **11.64 min** | the night ran 12 min past its own ask |
| load average | 13.4 → 11.1 | **26.4 → 15.0** | the seed sweep |
| watertight winners | 0 of 3 | **3 of 3** | the repair |
| props watertight (all nine) | 0 of 9 | **9 of 9** | the repair |

The GPU lane grew by 16 s and the CPU lane by 311 s. **The entire
difference between the two nights is the CPU lane** — the mesh tail — and
the CPU lane is the part that moves with the box's load. The GPU did the
same work, to within 3 %, on a box carrying twice the CPU load.

The repair's own cost is inside that: 9 × 3.3 s = 30 s of CPU on a
1,808 s night, 1.7 %. It bought 9 solids.

## 8. Reproduce

```sh
# the night
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python -m core.genbatch \
    --requests examples/mini_night_requests.json \
    --out artifacts/mini-night-2 --night-id mini-night-2

# the repair on all nine, measured after the fact
PYTHONPATH=. python docs/lab/mini-night-2-scripts/measure_repairs.py \
    --requests examples/mini_night_requests.json \
    --out artifacts/mini-night-2/repairs.json
```

Raw output is under `artifacts/mini-night-2/` (gitignored): the report
(`report.json`, `report.txt`, `report.html`), the ledger, the night's own
log, `/usr/bin/time -v`, and the box's state before and after.

## 9. What it stubs

* **The cost model is unchanged.** This night *measures* it; it does not
  touch it. The band finding in §6 is a measurement and a recommendation.
* **The critic is unchanged.** The repair changed what the critic saw, not
  what it does.
* **The repair recipe is the seat's own** (`weld`, tolerance 1e-6,
  `split_non_manifold` on, floor 0.98) — the same recipe the mesh-repair
  seat merged.
* **One prop's aspect is wrong** (lantern and anvil, on the z axis) and
  stayed wrong. The repair does not reshape a prop, so it cannot fix a
  prop that was generated with the wrong proportions.
