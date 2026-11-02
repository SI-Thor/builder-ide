# vibe-sandbox — the thin slice: prompt JSON → room GLB → critic → hot-load → playtest → gate

The lane's build of `SPEC.md`'s loop on our stack (the claims table that
checked the spec is `docs/research/vibe-sandbox.md` §1; the measured run is
`docs/lab/exp-vibe-sandbox.md`). Linux-only v1; the Windows engine is later.

```
inbox/<prompt>.json          a room spec JSON (the recipe — see prompts/)
  └─ watch.py                watchdog on the inbox (local dir over ssh, no Samba)
      └─ runner.py           one room end to end, with the gate and ≤2 retries
          ├─ generate.py     build123d: spec → one STL per named object + scene.json
          ├─ blender_stage.py  system Blender 4.0.2 --background: import, decimate
          │                   only over the 20k-tri budget, save .blend, export GLB
          ├─ critic_stage.py the repo critic (probe + scripted mesh checks on the
          │                   .blend) + Open3D 0.20 self-intersection on the GLB
          ├─ outbox/         manifest.json + <room>.glb, published atomically
          ├─ viewer/         three.js page (the agent-world viewer's three copy),
          │                   polling the manifest — a new room hot-loads, no restart
          └─ playtest.mjs    Playwright + headless Chromium: capsule walk over the
                              manifest's collision model + frame timing → qa_report.json
gate:  pass → the room's spec+reports are committed (docs/lab/vibe-sandbox-scripts/results/)
       fail → findings go back to generate.py as deterministic repairs, ≤2 retries
```

Every heavy stage runs under a `thor-admit` lease (tier `study`, honest peaks);
every stage writes a row to `artifacts/vibe-sandbox/ledger.sqlite3` with its
wall time and the box's load/free memory.

## What it needs (all already on the Thor)

- the lane venv: `uv venv .venv --python 3.12 && uv pip install build123d watchdog open3d trimesh numpy` (open3d 0.20 is the only cp312 aarch64 wheel; the uv cache already holds it)
- system Blender 4.0.2 (`/usr/bin/blender`), a bpy-capable interpreter for the
  critic probe (`~/src/infinigen-thor/.venv/bin/python`, read-only)
- Node 24.22.2 (`PATH=$HOME/.nvm/versions/node/v24.22.2/bin:$PATH`) and the
  Playwright install at `~/lm-tools/playwright` (the runner symlinks its
  node_modules here for `playtest.mjs`)
- the agent-world viewer's three.js copy (`~/lm-wt/agent-world/viewer/node_modules/three`),
  read-only — reuse, not a second download

## How to run it

```bash
cd ~/lm-wt/vibe-sandbox/tools/vibe-sandbox

# one room, end to end (watcher bypassed):
.venv/bin/python runner.py --spec prompts/clean-a.json --commit-on-pass

# the watcher seam (the spec's phase-2 shape, on our terms):
setsid nohup .venv/bin/python watch.py > ../../artifacts/vibe-sandbox/watch.log 2>&1 &
cp prompts/clean-b.json ../../artifacts/vibe-sandbox/inbox/   # and watch it flow

# the measured batch:
.venv/bin/python run_batch.py            # every prompt, serially; writes results/batch.json
```

The viewer alone: `node viewer/server.js` → `http://127.0.0.1:8129/` (it shows
whatever the outbox's manifest points at).

## What v1 stubs or simplifies (said plainly)

- **The collision model is the authored one** — the same scene.json the mesh
  was built from (prop bboxes, not per-triangle collision). A playtest that
  walks the shipped triangles is the first v2 item.
- **Frame time is software-rendered** (SwiftShader WebGL in headless
  Chromium): it measures the Thor's CPU raster path, not a GPU budget.
- **Repairs are deterministic rules**, not a model: snap-to-floor, nudge-off-
  door, move-toward-centre, clamp-to-family. Self-intersection and sealed
  pockets have no v1 repair — the gate fails them honestly instead.
- **The prompt is a structured spec**, not free text; an LLM writing this JSON
  (cloud, or the leased VLM) is the natural v2 seam and changes nothing
  downstream.
- **TRELLIS.2 props** run through the same generator seam under a ComfyUI
  lease (proven in `docs/lab/physag-lite/`); the batch measures the build123d
  arm, the cheaper one.
- Artifacts (STLs, .blend, GLBs, ledger, reports) live under
  `artifacts/vibe-sandbox/` (gitignored). A passing room commits its spec and
  reports plus the few-KB GLB as the acceptance record — meshes are caches,
  but the acceptance evidence is not.
