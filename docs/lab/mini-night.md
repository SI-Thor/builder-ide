# The mini-night — the Prop-maker's batch, run for real

**Date:** 2026-10-31, 06:15–06:41 local (Alaska Daylight Time)
**Verdict: RAN AS PLANNED** — the first real night behind the core's
scheduler: **3 prop requests × 3 seeds, 18 prompts, 24 min 44 s end to
end, one load per model, zero overlapping prompts**; three assets in the
library with their provenance and licence rows; the morning names each
winner and what it beat.

The branch is `propmaker-batch` (`core/genbatch/`, its
[README](../../core/genbatch/README.md) has the design). The night's raw
record is in the worktree under `artifacts/mini-night/` (gitignored like
every lab raw result): `report.txt`, `report.json`, `report.html`,
`assets.json` and the night's own SQLite `ledger.db`.

---

## 1. What ran

The brief's item 4: *"a real mini-night: 3 prop requests × 3 seeds, timed
end to end, with the report."* The requests
([`examples/mini_night_requests.json`](../../examples/mini_night_requests.json)):
a weathered wooden crate, a dented brass lantern, a squat iron anvil —
each with the shape it was asked for, a 750 k-triangle budget, and a
seed anchor so the night replays.

The pipeline, entirely on the Thor, behind the core's night runner:

```
concept → SDXL base 1.0 (9 pictures, 1024², 12–26 s each)
picture → TRELLIS.2 512³ (9 meshes, 1:52–3:32 each, cold weights first)
mesh    → measured (glb.py, mesh.py) → judged (critic.py) → asset + licence row
```

The TRELLIS.2 environment (`~/lm-wt/trellis`) was **read, never
modified**: its two workflow templates (digests in every asset's
provenance), its ComfyUI service on `127.0.0.1:8188` started with
`--cache-none`, its `out/` directory for the files the night made.

**The box's state, beside the numbers** (the spike's rule — a wall-clock
without the load beside it is not comparable): load average 13.4 → 11.1
on 14 cores across the night (other seats' CPU jobs ran throughout;
one held ~10 cores at the start). The GPU was ours alone —
`nvidia-smi --query-compute-apps` showed no foreign compute process from
start to finish.

## 2. The numbers

End to end (the driver process, `/usr/bin/time -v`): **24:43.77** wall,
370 MB peak RSS. The night's own accounting, folded from its ledger:

| | |
|---|---|
| prompts | 18 (9 image + 9 mesh), **0 overlapping windows** |
| wall (sum of prompt windows) | 1,478 s |
| GPU lane | 549 s (**37 %**) |
| CPU lane | 917 s (**62 %**) — the mesh tail |
| unclassified | 0 s |
| model loads | `sd_xl_base_1.0: 1`, `trellis2: 1` (the load cap held) |
| GPU rail spent | 9.16 of 18.5 min (the ask was 26.1 min of wall; the night took 24.7 — **no overrun**) |
| tasks | 6 of 6 `kept`, 0 failed, 0 cut, 0 parked |
| status line (computed) | `ran as planned / nothing failed` |

Per stage — ask vs measured (the ask is the plan's price from the spike's
numbers; both are in the report):

| task | ask wall | measured wall | note |
|---|---:|---:|---|
| img:crate ×3 | 2.1 min | 0.66 min | SDXL warm from the smoke run |
| img:lantern ×3 | 2.1 min | 0.85 min | |
| img:anvil ×3 | 2.1 min | 1.19 min | |
| prop:crate ×3 | 6.6 min | 8.87 min | first mesh = the cold 13 GB weights |
| prop:lantern ×3 | 6.6 min | 7.02 min | |
| prop:anvil ×3 | 6.6 min | 6.04 min | box quietest here (load ~10) |

The lane split deserves its caveat: this seat's GPU lane is the samplers
**plus** the conditioning and VAE-decode stages, and the CPU lane
includes model loading — so 37/62 is a broader GPU lane than the spike's
samplers-only 16 s per 512³ prop. The direction is the spike's own: the
CPU mesh tail is most of a 512³ prop's cost, and it is the part that
swings with the box's load (our meshes ran 1:52 at load ~10 and 3:32 at
load ~26).

## 3. The morning

The winner, its score, and what it beat (the runner-up rows are the
core's own `IterationCard`):

| request | winner | score | beat | the critic's reason |
|---|---|---:|---|---|
| crate | `prop:crate_r1_v1` (seed 1064508603) | 0.750 | v2 (0.707), v3 (0.727) | watertight failed only |
| lantern | `prop:lantern_r1_v1` (seed 424809304) | 0.684 | v2 (0.668), v3 (0.684) | watertight + aspect |
| anvil | `prop:anvil_r1_v2` (seed 64961400) | 0.661 | v1 (0.652), v3 (0.654) | watertight + aspect |

The three winners are in the asset library: 698–699 k triangles, 44–48
MiB GLBs with the full PBR set, `spdx: MIT` with the DINOv3 and
ComfyUI-host terms in `dependency_terms`, and provenance carrying the
prompt, the model, the weights revision, all four seeds, the resolution,
both workflow digests and every sampler knob.

### What the critic found — three honest findings

1. **Nothing was watertight.** All nine meshes: 155 k–234 k *boundary*
   edges, **0 non-manifold** edges. TRELLIS.2's remeshed 512³ output is
   simply not a closed solid at this template — so the heaviest check
   (weight 3) scored zero for every candidate, and the winner was picked
   by the rest. That is exactly why the checks are *graded*: a
   pass/fail critic would have scored all nine zero and "picked" the
   first one it saw. The morning says the failure in plain words on
   every card. *(Follow-up worth a night: a post-process pass — the
   template's `RemeshMesh` sign modes, or a voxel re-mesh — or accepting
   "open shell" as a class of prop.)*
2. **Everything came out ~cubic.** Extent ≈ 1:1:1 on all nine meshes,
   whatever the ask: the crate's 1:1:0.8 passed within tolerance, the
   lantern's 0.65:1:0.5 and the anvil's 1:0.5:0.4 came back 100–150 %
   off on the z axis. The bounding-box check measured what it should:
   image-conditioned TRELLIS.2 controls *proportions* only weakly, and
   the aspect ask has to reach the *image* prompt if it is to reach the
   mesh. The check did its job — it named the miss per axis.
3. **The triangle budget is nearly a constant.** 698 234–698 930
   against the 750 k budget on all nine — the template's
   `DecimateMesh` target doing its job. The check stays (a drifted
   template would break it loudly), but it will rarely discriminate
   between seeds.

The image stage's own critic scored every picture 1.0 — made, and the
size the mesh stage conditions on. A tie, broken by seed order; measuring
a picture's *content* is a vision critic's job, and until one is
calibrated (§1.9's calibration record), the report says only what was
measured.

## 4. How to reproduce

```sh
~/lm-wt/trellis/scripts/serve.sh start --cache-none   # the service, unmodified
python -m core.genbatch --requests examples/mini_night_requests.json \
    --out artifacts/mini-night --night-id mini-night
python -m pytest tests/genbatch -q                     # the whole night, on a fake box
```

The seeds are derived from each request's `base_seed`, so the same
requests replay the same variants (the meshes themselves are not
byte-reproducible — the spike's §5, which is why every asset carries its
recipe instead).

## 5. What it changes

- **The three scheduling rules held under a real night**, and the report
  proves each: one load per model (the load cap never bit because the
  batching made it unnecessary), the CPU lane measured at 62 % of the
  night, and zero overlapping prompt windows on a box that was otherwise
  busy — at the cost of the GPU idling through every tail, which is the
  price the spike said the rule was worth.
- **The night fits its own ask.** 24.7 min of wall against a 26.1-min
  ask computed from the spike's per-prop prices — the estimates are now
  measurements, and the morning's `the_box` table shows both for every
  task.
- **The graded critic is the right shape.** A night where the heaviest
  check fails for every candidate still produced a ranked, reasoned
  winner — and the two real defects (open shells, cubic proportions)
  are findings about the *generator*, surfaced per-axis on the card,
  not noise in a score.
- **What is still missing for a production night**: a calibrated vision
  critic (the image stage cannot rank its own pictures), a watertight
  post-process or an open-shell asset class, and aspect control pushed
  into the image prompt. All three are named by the night itself.
