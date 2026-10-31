# core.genbatch — the Prop-maker's generative batch

A night of props, made rather than modelled: a concept prompt goes through
the local image model, the picture goes through TRELLIS.2, and the mesh
that comes out is measured, judged, and recorded as an asset with its
provenance and its licence row. The best of N seeds is kept, and the
morning says which one won and what it beat.

This is the seat that answers the brief's *"the engineer also makes things"*
and *"the Thor is an iterator"*: the box's GPU and CPU are the workshop, and
the night's output is a catalogue of props rather than a render.

## What it is made of

| module | what it owns | needs a GPU? |
|---|---|---|
| `glb.py` | reading a GLB: the container, and the mesh primitive in it | no |
| `mesh.py` | measuring a mesh: watertightness, triangles, bbox, volume, area, centre of mass | no |
| `repair.py` | the repair stage: welding the seams the generator leaves, and undoing the self-crossings | no |
| `fidelity.py` | the silhouette IoU: how much of the prop a repair left alone | no |
| `critic.py` | the scripted critic — the judgement that picks the winner | no |
| `assets.py`, `licences.py` | the asset record: the file, the recipe, the licence row | no |
| `models.py`, `store.py` | the records, and where the night's output is kept | no |
| `workflow.py` | the two API workflows, patched from the TRELLIS.2 environment's own templates | no |
| `timing.py` | the per-node timings, and the lane each node's time belongs to | no |
| `schedule.py` | the night's staging plan, and the three scheduling rules | no |
| `comfy.py`, `executor.py`, `night.py` | the service, the job, and the night | yes |

Two thirds of the seat never touches the GPU, and that is the point: the
judgement can be tested without one, and the night can be rehearsed on a
fake box.

## Running it

The TRELLIS.2 environment has to be up. It is **read, never modified**:

```bash
~/lm-wt/trellis/scripts/serve.sh start --cache-none
```

Then a night:

```bash
python -m core.genbatch \
    --requests examples/mini_night_requests.json \
    --out artifacts/mini-night \
    --night-id mini-night
```

The night leaves behind, in `--out`:

| file | what it is |
|---|---|
| `report.json` | the whole morning, as data |
| `report.txt` | the morning, as text — the rules, the lanes, the winners |
| `report.html` | the core's own HTML morning |
| `core-report.txt` | the core's morning, as text |
| `assets.json` | every prop that was made, with its provenance and licence row |
| `ledger.db` | the night's log — the core's SQLite ledger |

The props themselves stay in the TRELLIS.2 environment's output directory
(`~/lm-wt/trellis/out/genbatch/`), and the asset records point at them.

`aiohttp` is needed for the ComfyUI client and the per-node timings. It
rides as an extra, so the core still installs without it:

```bash
pip install -e ".[propgen]"
```

Without it the night still runs — the lane split is simply unmeasured — but
the timing is worth having.

## The four scheduling rules

These are the TRELLIS.2 spike's findings, written as rules the scheduler
keeps (`schedule.py`), and the report says which ones ran:

1. **`batch_by_model`** — the GPU stages are batched by model. The night's
   queue is every image first, then every mesh, so TRELLIS.2 is loaded once
   for the night rather than once per prop. The core's own load cap (one
   load a night) is what enforces it: the executor declares a model to the
   core only when it is actually loaded, and the night line reads
   `model_loads: {sd_xl_base_1.0: 1, trellis2: 1}`.
2. **`cpu_mesh_tail`** — the mesh tail is charged to the **CPU lane**, not
   to the GPU's bar. The GPU lane's time is the sampling; the tail
   (remesh → decimate → unwrap → bake → GLB) is most of a prop's cost and
   it is CPU-bound. The lane rule is the spike's own: the GPU's own stage
   is `KSampler`, everything else is model loading or the tail. A node
   this seat has never heard of is left *unknown* rather than guessed into a
   lane.
3. **`no_overlap`** — one prompt at a time. The mesh tail of one prop never
   runs inside the sampling of the next. The spike measured a seven-fold
   swing when two props ran at once and their tails fought over the same
   cores; the price of the rule is that the GPU idles through every tail,
   and the report says how much.
4. **`costs_from_the_model`** — what each stage costs is the **cost model's**
   number, not one typed in here (`core/night/cost`). The image stage is
   priced as `prop.image` (one 1024² picture) and the mesh stage as what the
   night actually runs at the request's resolution — `prop.mesh.512` or
   `prop.mesh.1024`: the generator's sampling **plus** the decode stages, the
   repair and the measuring, as mini-night 2's ledger measured them. (The
   stage used to be priced at the bare generator, `prop.512` — 3.4× low;
   `schedule.py` carries the story.) The task's **ask** is the model's p50
   and its **rail** the model's p95, the same convention the core's night
   runner uses, so a task means the same thing in both places.
   The executor's plan reads the same price (`plan.per_variant_cost`), or
   the night would cut the work it planned itself.

   The night still adds its own headroom to the rails it runs under
   (`_rails_for`): that is the night's policy, not a cost.

## The repair stage

Between TRELLIS.2 and the critic, the night **repairs** the mesh. The reason
is in the mini-night's record: every one of its nine props came back with
155 k-234 k boundary edges, and the critic's heaviest check scored zero for
every candidate.

**Those meshes were never open.** The UV unwrap gives a vertex two copies,
one per side of a seam, and the two copies sit at *bit-identical* positions.
The mesh is a closed solid; its *index buffer* just cannot see the closure.
The repair merges those vertices back together, and the boundary edges go -
every one of them, on all nine meshes - without moving a vertex:

| | before the repair | after |
|---|---|---|
| boundary edges | 155,312-326,800 | **0** |
| non-manifold edges | 0 | 0 (after the crossings are undone) |
| triangles | 698,184-699,824 | unchanged |
| area, volume | - | **identical to six decimals** |
| silhouette IoU against the original | - | **1.000000** |
| cost | - | 2.6-18.2 s per prop, at load 13-26 |

Three operations, all of them topological, all of them numpy:

1. **weld** - merge the vertices that sit at the same place;
2. **collapse** - take out the zero-volume flaps (a triangle the generator
   left in the mesh twice, once each way round);
3. **split** - give the pinched vertices a copy of themselves, which splits
   the edges the surface crosses itself on.

The repair is **part of the recipe**: `PropRequest.repair` says which method
ran and with what parameters, and the asset's provenance carries the
measurements - the wall-clock, the counts, and the fidelity.

So is the **weight dtype**: `PropRequest.weight_dtype` is what the mesh
workflow's UNETLoader is told to load the TRELLIS.2 weights as — `"default"`
(the checkpoint's own dtype, bf16 on this box, and the default until fp8
earns its place) or one of ComfyUI's `fp8_e4m3fn` / `fp8_e4m3fn_fast` /
`fp8_e5m2`. The builder writes it on the loader **outright**, even when the
template already says it: a request that asked for fp8 and silently got bf16
would be a lie, and the first fp8 grid ran every arm as bf16 exactly that
way (see [docs/lab/exp-fp8-real.md](../../docs/lab/exp-fp8-real.md)). A prop
made in fp8 is not the same prop as one made in bf16, so the dtype belongs
in the recipe either way; the executor records it in the asset's provenance.
Whether fp8 *keeps* the quality is the fp8 experiment's verdict, not an
assumption here.

**The asset's GLB is left as the generator wrote it**, and that is deliberate.
The file's geometry was never broken - only the index buffer's view of it
was - so rewriting it would buy nothing and cost the atlas: a naive weld
keeps the correct UV for only **84.6 %** of the surface area, because the two
sides of a UV seam need different atlas coordinates and a welded vertex has
only one. What the repair supplies is the *solid* the pipeline measures and
judges, plus the proof that it did not reshape the prop.

### The fidelity check

A repair that makes a prop watertight can still ruin it, so the repair
measures the prop's **silhouette IoU** against the mesh it was given
(`fidelity.py`): the overlap of the object's outline, seen from three
directions. The weld scores **1.000000** - the geometry is untouched - and
the number is in the report, so a repair that reshapes the prop is caught
rather than shipped.

The measure needed care to be worth anything: sampling the surface into a
pixel grid leaves the outline's boundary pixels flickering, and two meshes
with *identical* geometry scored an IoU of 0.51 before the grid was sampled
densely enough. Twenty samples per pixel fixes it; both the fix and the
check are in the tests.

### The alternatives, measured

The bake-off is in [docs/lab/exp-mesh-repair.md](../../docs/lab/exp-mesh-repair.md):
hole filling (trimesh) adds 146 k triangles and thousands of non-manifold
edges; a voxel remesh costs tens of seconds, rounds the silhouette and loses
the atlas; manifold3d does the job but needs the mesh welded first;
**MeshFix is AGPL-3.0 and is not a dependency**. The repair shipped here needs
**no new dependency at all**.

## The critic

The brief's three checks, and SolidCraft's oracle set
(`docs/research/solidcraft.md`):

| check | weight | what it says |
|---|---:|---|
| `watertight` | 3 | closed, consistently wound, positive volume - measured on the **repaired** mesh |
| `repair_fidelity` | 1 | the repair left the prop's outline alone (the silhouette IoU) |
| `triangle_budget` | 2 | inside the triangle budget the request set |
| `bbox_aspect` | 2 | the proportions are the ones asked for (only when the request states a shape) |
| `solid_volume` | 2 | it fills its own bounding box like a solid, not like a shell |
| `surface` | 1 | a closed solid cannot have less surface than a sphere of the same volume |
| `centre_of_mass` | 1 | the mass sits inside its own box, and near the middle of it |
| `degenerate` | 1 | no triangles of no area |

Every check is **graded** from 0 to 1, not passed or failed. Three props that
all fail the same check would otherwise score zero each and the "winner"
would be whichever the loop happened to see first.

`bbox_aspect` only runs when the request states an `expected_aspect`,
because TRELLIS.2 normalises a prop's size away - the largest horizontal
extent comes out as one unit - so the absolute size is the caller's
business and the *proportions* are the generator's.

`repair_fidelity` only runs when the repair stage ran. A repair that did not
succeed fails the `watertight` check outright: a prop that was not repaired
cannot be called a solid.

## The licence

Two rows, and both are checked (docs/research/trellis-spike.md §6):

* **TRELLIS.2** — MIT, ungated. The DINOv3 encoder's attribution and
  end-use limits travel with the weights, and ComfyUI (GPL-3.0) is the
  *host*, kept as a separate service and never linked.
* **SDXL base 1.0** — OpenRAIL++-M, for the image stage only.

A prop made from a prompt carries the first; a prop made from a prompt
also went through the second, and the asset's file list names the source
picture.

## The tests

```bash
python -m pytest tests/genbatch -q
```

Everything that does not need a GPU is tested, including the whole night
driven end to end against a fake ComfyUI that writes a real GLB. The tests
never open a socket.

## The mini-night, run for real

On 2026-10-31 the night above ran against the real TRELLIS.2 environment:
3 requests × 3 seeds, 18 prompts, **24 min 44 s end to end**, one load per
model, zero overlapping prompts, all six tasks kept, the night inside its
own ask (24.7 min of wall against a 26.1-min estimate). Three assets
entered the library with MIT licence rows and full provenance; the
morning names each winner, its score, and the two variants it beat.

Two findings the night itself paid for. Every prop came back **~cubic**
whatever aspect was asked (100–150 % off on the missing axis — the aspect ask
has to reach the image prompt, not the mesh). And TRELLIS.2's remeshed output
came back with **155 k–234 k boundary edges**, so the heaviest check failed
for every candidate and the graded scores were what still produced a ranked
winner. The full numbers, with the box's load beside every one, are in
[docs/lab/mini-night.md](../../docs/lab/mini-night.md).

**The second finding has since been overturned**, and the repair stage is
what overturned it: those props were **closed solids all along**, with the
vertex buffer split at the UV seams, so the edge-counting check could not
tell a solid from a hole. Welding the seams closes every boundary edge on
all nine meshes, leaves the area and the volume untouched to six decimals,
and keeps the prop's outline at an IoU of **1.000000**. The evidence is in
[docs/lab/exp-mesh-repair.md](../../docs/lab/exp-mesh-repair.md).

## What it stubs, and how it joins the rest

* **The TRELLIS.2 environment** (`~/lm-wt/trellis`) is read for its two
  workflow templates and written to for its outputs; it is never modified.
  The templates' digests go into each asset's provenance, so a prop made
  from a changed template is visible in the record.
* **The core's night runner** does the queueing, the rails, the load cap,
  the iterator and the morning report. This seat supplies the executor, the
  variant source, the critic and the plan — the seams the core defines.
* **The core's cost model** (`core/night/cost`) says what each stage costs,
  so this seat's numbers are the box's measured ones and not its own.
* **The core's ledger** is where the night is written, so the morning can
  be folded out of the log without anybody's memory of it.
