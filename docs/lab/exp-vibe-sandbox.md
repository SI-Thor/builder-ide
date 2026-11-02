# exp-vibe-sandbox — the thin slice: prompt JSON to playtested room, on our stack

**Date:** 2026-11-01/02 · **Worktree:** `~/lm-wt/vibe-sandbox` (branch `vibe-sandbox`) · **Code:**
`tools/vibe-sandbox/` (README there is the run book) · **Results:** `docs/lab/vibe-sandbox-scripts/results/`
· **Claims table:** `docs/research/vibe-sandbox.md` §1 · **Push:** never.

## What was asked, and what was done

Casey's spec (`SPEC.md`) describes an end-to-end "vibecode a room, an agent playtests it" sandbox:
ProArt + Thor over 10 GbE, a Samba share watched for prompt JSONs, generation by "vLLM or LGM",
Blender bake, an engine hot-load, and "Aura Autopilot" as the tester. The lane brief asked for the
thinnest **real** version of that loop **on our stack**, measured — and a reality check on the spec
first.

The reality check is `docs/research/vibe-sandbox.md` §1 (14 rows). Four load-bearing verdicts: the
direct-cable fabric does not exist (the ProArt PX13 has no wired adapter; the Thor's four 10 GbE
ports have no link); guest-writable Samba is replaced by an inbox directory over ssh; vLLM is an
LLM server, not a mesh generator (build123d and TRELLIS.2 are ours and approved); and Autopilot is
real (Apache-2.0, 626 stars) but is a Windows/macOS editor plugin with an Aura account — not a
headless aarch64 tester. The playtester below is ours.

What was built is the loop itself, seven stages, every heavy one under a `thor-admit` lease
(tier `study`, honest peaks):

```
inbox/<prompt>.json            room spec JSON (the recipe; prompts/ holds the batch)
watch.py                       Python watchdog on the inbox (local dir over ssh — no Samba)
runner.py                      one room end to end: the gate and ≤2 retries
├─ generate.py                 build123d: spec → one STL per named object + scene.json
├─ blender_stage.py            system Blender 4.0.2 --background: import, decimate only
│                              over the 20k-tri budget, save .blend, export GLB
├─ critic_stage.py             the repo critic (core.critic probe + run_mesh_checks on the
│                              .blend) + Open3D 0.20 self-intersection on the shipped GLB
├─ outbox/                     manifest.json + <room>.glb, published by atomic rename
├─ viewer/                     three.js page polling the manifest — a new room hot-loads,
│                              no restart; reuses the agent-world viewer's three copy
└─ playtest.mjs                Playwright + headless Chromium: capsule walk over the
                               manifest's collision model + frame timing → qa_report.json
gate: pass → spec + reports committed under docs/lab/vibe-sandbox-scripts/results/<room>/
      fail → findings become deterministic generator repairs, ≤2 retries
```

One design rule carries the whole slice: **`scene.json` is the single collision/manifest model.**
The generator writes it from the spec; Blender, the critic's probe, the viewer and the playtest all
read the same numbers, so the QA agent and the critic judge the room the mesh was actually built
from. (What that costs is in "What was not verified".)

## The facts the slice stands on

- **Thor state during the runs:** load1 14.3–18.2, 107.5–107.7 GB memory available, the agent-world
  reflex and other seats' work resident; every number below was taken on that box, not an idle one.
- **Blender:** system 4.0.2 (apt, aarch64) assembles and exports; the critic's probe runs under the
  Infinigen checkout's bpy 4.2 interpreter (a 4.2 bpy reads a 4.0 blend). No Docker Blender worker
  was needed for any stage.
- **Chromium on aarch64:** the Playwright install's headless Chromium runs WebGL through
  SwiftShader (renderer string `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device …))`). This closes
  the "Playwright Chromium on aarch64" item the in-game-building survey left open.
- **three.js:** the viewer imports the agent-world viewer's copy (0.128.0, `GLTFLoader` from its
  `examples/jsm`) — no second download, and the page is the same stack the Minecraft world's 3D
  view uses.

## The numbers

### Per-stage latency, attempt 1 (ms, lease included)

| room | generate | blender | critic | playtest | wall (all attempts) | verdict (attempts) |
|---|---|---|---|---|---|---|
| clean-a | 2 698 | 1 283 | 1 530 | 4 394 | 9 970 | pass (1) |
| clean-b * | 2 670 | 1 240 | 1 621 | 4 091 | 9 657 | pass (1) |
| float-a | 2 713 | 1 224 | 1 565 | 4 410 | 19 607 | pass (2) |
| block-a | 2 590 | 1 271 | 1 627 | 4 085 | 19 174 | pass (2) |
| pocket-a | 2 548 | 1 224 | 1 446 | 4 082 | 9 335 | fail (1) |
| scale-a | 2 728 | 1 276 | 1 572 | 3 937 | 19 227 | pass (2) |
| selfx-a | 2 632 | 1 228 | 1 518 | 4 170 | 9 578 | fail (1) |

\* measured by the **watcher seam**: the prompt was dropped into the inbox while `watch.py` ran
detached, and the room flowed to a commit with no human in the loop. Watch pickup added ≤ 1 s.

Medians: generate ≈ 2.7 s, blender ≈ 1.2 s, critic ≈ 1.5 s, playtest ≈ 4.1 s; **≈ 9.6 s wall per
attempt**. The wall includes lease acquisition per stage (four leases per attempt) — the build123d
geometry itself builds in well under a second; most of "generate" and a good part of "playtest" is
process and lease overhead, which is the honest price of the no-unleased-work rule and is shown as
such. A repaired room costs two attempts ≈ 19.2–19.6 s.

### The artefacts

A one-room GLB is **60.8 KB**, 13 named objects, **3 148 triangles** (before decimation; the budget
gate never had to fire on these rooms). The QA agent's frame timing on that scene, software
rendered: **19.6 ms mean / 27 ms p95** — the number is the Thor's CPU raster path, not a GPU budget,
and is labelled that way in every report.

### The catch matrix — what the QA agent catches that the critic does not

Seven rooms: two clean controls, five with one seeded fault each.

| seeded fault | critic (scripted + Open3D) | playtest agent (QA) |
|---|---|---|
| crate floating 55 cm (`float-a`) | — | **caught** (`floating_object`, z=0.55) |
| crate standing in the door gap (`block-a`) | — | **caught** (`blocked_door`) |
| interior walls sealing a 2×4 m corner (`pocket-a`) | — | **caught** (`unreachable_area`, 94.4 % reachable) |
| crate at 7.5× its family's median (`scale-a`) | **caught** (`scale_bounds`, crate.003@7.5x) | — |
| two un-unioned boxes in one prop (`selfx-a`) | **caught** (`self_intersection`, Open3D) | — |
| clean rooms ×2 | no false positive | no false positive |

The division is the finding: **the critic is per-object geometry and blind to placement; the QA
agent is placement and navigation and blind to within-object faults.** Floating, door-blocking and
sealed-off floor are facts about *where* objects stand — no per-mesh check can see them — and the
7.5× outlier and the passing-through shells are facts about single objects a capsule walk never
notices. Neither stage fired on a clean room.

### The gate and the retry loop

- **Pass rate:** 5 of 7 rooms passed. The two clean rooms passed on attempt 1; the three repairable
  faults (`float-a`, `block-a`, `scale-a`) each failed once, were repaired from their findings, and
  passed on attempt 2. The two remaining failures (`pocket-a`, `selfx-a`) are the seeded faults v1
  has no repair for — the gate reports them instead of retrying into the same wall, which is the
  intended honesty.
- **The repairs applied:** snap-to-floor (`floating_object` → z=0), clear-door-strip
  (`blocked_door` → the culprit prop's y set past 1.9 m), clamp-to-family (`scale_bounds` → dims ×
  0.2, back to 1.0× the family median on re-measure).

## One dead end, kept on the record

`block-a`'s first batch run burned all three attempts without changing the room: `blocked_door` is
a room-level finding and carries no prop name, and the repair path silently dropped nameless
findings — so the loop rebuilt the identical room three times and failed identically three times
(29.5 s). The pre-fix code was never committed. The fix — the culprit is the prop whose bbox
intersects the door strip, inferred from the spec's own geometry — is in `generate.py` as committed
(`6e0cc22`), and `block-a`'s re-run with it passed on attempt 2 (19.2 s). Lesson written into the
repair path's shape: a gate that feeds a repair loop must decide what to do with *anonymous*
findings before the loop runs, or the retries are theatre.

## What it makes possible

- The lane's loop exists end to end on the box we actually have, at a cost point (≈ 9.6 s/attempt,
  ≈ 60 KB/room) that makes a nightly batch of hundreds of rooms trivial, and every room leaves a
  ledger row per stage with its timing and the box state.
- The outbox manifest is the wire format the v2 Windows/Godot client can poll unchanged (spec
  phase 4), and the QA harness is the local counterpart of the v2 streamed-VLM tester (phase 5)
  without needing any video path yet.
- The QA/critic complement measured here is the argument for keeping both gates in the loop rather
  than trusting either one — it is the same shape as the hybrid critic's band argument
  (`core/critic/CALIBRATION.md`): different critics see different defect classes.

## How to reproduce

```bash
cd ~/lm-wt/vibe-sandbox/tools/vibe-sandbox
# prerequisites are all on the Thor already; the venv:
export PATH=$HOME/.local/bin:$PATH
uv venv .venv --python 3.12 && uv pip install build123d watchdog open3d trimesh numpy

.venv/bin/python runner.py --spec prompts/clean-a.json --commit-on-pass   # one room, ~10 s
.venv/bin/python run_batch.py                                            # the batch, ~1 min
.venv/bin/python - <<'PY'                                                # the ledger
import sqlite3, json
c = sqlite3.connect("../../artifacts/vibe-sandbox/ledger.sqlite3")
for row in c.execute("select at,room,attempt,stage,status,ms from events order by rowid desc limit 12"):
    print(row)
PY
```

Costs: one room ≈ 10 s wall, four `study`-tier leases (4–6 GB peaks each; actual peaks are far
lower — build123d and Blender on these rooms sit under 1 GB, the peaks are ceilings, not usage),
no GPU minutes (the TRELLIS arm would add them; see v2 plan).

## What was not verified

- **The collision model is authored, not derived from the shipped mesh.** The playtest walks
  bboxes from `scene.json`; a GLB whose triangles disagreed with its manifest would pass QA. The
  mesh-side walk (raycast/trimesh collision in-page) is the first v2 item. Within this batch the
  two cannot disagree — the same spec produced both — but that is an artefact of the build, not a
  property of the loop.
- **Frame time is SwiftShader**, i.e. the Thor's 14 Neoverse cores rasterising WebGL, not a GPU;
  it is comparable across rooms and nothing more.
- **`prop_unreachable` never fired in the batch** (its natural trigger, the sealed pocket, was
  covered by `unreachable_area`), so that one check's false-positive behaviour is unmeasured.
- **The critic stage runs the scripted checks only** — the hybrid/d1 model critic scores renders,
  and no render was made; a render-and-judge stage is v2 work, not silently claimed here.
- **One room shape:** rectangular rooms, one north door, axis-aligned interior walls, five prop
  kinds. Non-rectangular rooms, multiple doors and TRELLIS-generated organic props are untested.
- **Lease overhead was not isolated**: stage times include lease acquisition; no run was made
  with the lease wrapper removed to split the two.
