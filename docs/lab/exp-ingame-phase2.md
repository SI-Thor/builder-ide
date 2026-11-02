# exp-ingame-phase2 — one day per tool with the phase-1 shortlist

*2026-11-01, on the thor (`~/lm-wt/ingame-phase2`), headless unless noted. Phase
1 shortlisted three tools in `docs/research/ingame-building.md` (see
`ingame-building/RESULT.md` and `docs/design/vibecode-in-world.md` §7 for the
full scan). This is phase 2: run each one hands-on, decide what we take, refuse
the rest — as the phase-2 brief demands, with real numbers and committed raw
output beside every recipe.*

Recipes and everything they produce live under
`docs/lab/ingame-phase2-scripts/`; nothing was installed system-wide; every
tool is an `/run --tier live` lease with `XLA_PYTHON_CLIENT_PREALLOCATE=false`
where GPU-ish work is involved (`thor-admit`, peak 2-3 GB).

| tool | licence | what it gave us |
| --- | --- | --- |
| topview-3d-builder | Apache-2.0 (its `add_library` assets are CC-BY-4.0, unused) | deterministic geometry pre-flight: grounded/floating/overlap/evaluate checks |
| build-world three.js kit | Apache-2.0 | the capture/pixel-gate CONTRACT (ready/pump/present/shot/fresh-page baseline/imagediff). No gizmos, no undo, no placement |
| Vibe3DScene (`bpy` scene) | Apache-2.0; its bundled `blender-mcp-vision` addon is MIT | real transactional execution: snapshot + scene-guard + rollback — and one deliberate no-rollback contrast |
| agent-world viewer (our copy) | ours | the prototype: the kit's contract, run against the live in-world renderer |

---

## 1. topview-3d-builder — the deterministic geometry pre-flight

Drove it headless on three scenes built from our own props. Full numbers and
analysis in `NOTES.md` (2026-11-01 20:05-20:45 entry); raw:
`results/topview-scenes/{steps,summary}.json`, recipe
`ingame-phase2-scripts/{prop_scenes.json,run_topview_scenes.py}`.

**Numbers.** 21.9 s of CLI wall for three scenes (all steps exit 0): per scene
`project init` 0.17 s, one atomic `node batch` (4-6 pieces + camera) median
**0.79 s**, `document validate` 0.15 s, `evaluate` 0.24 s, `inspect nodes`
median **1.07 s**, `inspect views` median **2.18 s**, `render` (960x540, frames
0, 24 + contact sheet) median **2.11 s**. `checksComplete: true`,
`checksBlockedBy: []` even with floating nodes present.

**The check vocabulary against our critic.** `inspect nodes` publishes
`groundTolerance: 0.02` and classifies each node from its mesh bounds
(grounded/floating/penetrating): it catches our deliberate floating lantern
(+0.15..+0.42) and ALSO flags the closed crate's lid at +0.232 — correct per the
definition (a lid that sits on the crate), wrong as a defect signal. Its
grounding/bounds work is a deterministic geometry pre-flight which runs before
any render; our `core/critic/` is a render-output critic (image channels +
`floating_blob`). Not rivals — consecutive gates.

**What to take into vibecode-in-world (§7).** (a) the *check vocabulary with
published tolerances* (`checksComplete`/`checksBlockedBy`, never
`checksFailed`) as the shape of the pre-flight verdict in the proposal step;
(b) grounding/overlap classification as the first deterministic gate in
timeline-check / wire-world-guard, keeping the "closed-lid" caveat documented
so a standing object is not reported as a defect; (c) `evaluate`'s per-frame
per-node booleans (finite, positiveScale, visible, inFrustum,
groundPenetration) as the cheap per-frame assertions minus its subjective
labels. Refuse: its camera schema (three rejections to learn the one accepted
shape — `CAMERA_VIEW_CONFLICT`, `CAMERA_SUBJECT_REQUIRES_CHARACTER`), its
contact-sheet "visualStatus: pending-model-review" as a *verdict* (ours stays
`?` until judged), and the character-node coupling.

---

## 2. build-world's three.js kit — what is worth keeping

Repo: `third_party/build-world` (Apache-2.0). The shortlist said the kit's
value is *capture and gates*, not authoring. Verified both sides.

**It has no authoring engine.** The kit's editor has no gizmos, no selection,
no undo, no placement tool (the word 'undo' hits only its bundled Unreal docs);
it loads whatever GLBs the host page puts in `assets/` and everything about
positioning lives in host code ("kit: gltfLoader …, placement: our code", raw:
`results/bw-glb/asset-report.json`). Confirming the phase-1 escape: warping the
kit into a gizmo editor is exactly what we refused to do.

**What we ran with OUR assets** (`run_bw_glb.sh`, raw `results/bw-glb/`). The
kit's viewer loaded our box (`box_long_a08.glb`, 4,924 tris, `bottomOffset`
-0.154) and our 5.8 M-tri room (`books_room.glb`, 132 meshes / 5,799,560 tris,
`bottomOffset` -0.109) in **610 ms**, one page, 134 calls / 104 textures at the
shutter (960x540). Probe and per-frame `__RENDER_INFO__` counts come back
faithfully at our scale.

**The pixel gate on our own scene.** `baseline.mjs` twice (a fresh page per
shot, 1920x1080 default, `settle=90`) then `imagediff.mjs`:

* run 1 vs run 2 — **bit-identical**: `identical: true`, 0 of 1,036,800 pixels
  changed, `maxDelta 0`, and the diff PNG shows a black (zero) residual;
* run 1 vs `?lightdim=1` (deliberate change — the page dims the key light) —
  `changed%` 88.54 (box-wide) / 92.06 (box-detail), `maxDelta` 60 / 63. The
  gate's `withinEpsilon` threshold is `changedPct < 0.05 %` with `maxDelta <= 2`
  (when `identical` is `false`, `0.05 %`); the deliberate change misses by 6
  orders of magnitude — in the other direction.

**The shutter-vs-pump lesson (ours, not the kit's).** `capture.mjs` times out
*screenshotting* the 5.8 M-tri page (`page.screenshot: Timeout 30000ms
exceeded`) on **both** 90- and 24-frame settles, while `baseline.mjs` with the
same page screenshots fine. `bw-glb-scene/framecost.mjs` splits the two costs:
per-shot `__PUMP__` render time is 0.6-2 ms per frame (the scene is 5.8 M tris
but 134 calls), and the **long** shutter (180 s) succeeds in 43 ms. The 30 s
timeout is not a slow frame: software GL rasterises lazily and the screenshot's
`readPixels` must first consume the whole *unflushed frame backlog* (deltas: 5
pumped frames → 43 ms; 48 pumped frames → >30 s). Chip hint in the page log
itself (`"GPU stall due to ReadPixels"`). So the kit contract's real lesson
extends: not just `frame(); present(); screenshot`, but **the pump depth IS part
of the shutter cost** under software GL — cheap writes, expensive readback.

**Kept recipe round-trip:** `run_bw_glb.sh` covers
probe → capture → framecost → baseline×3 → imagediff gates and every step's
exit code lives in `results/bw-glb/exits.txt`. Raw numbers above are committed
next to the recipe.

**What to take into vibecode-in-world (§7).** The whole capture contract: per
shot `__SHOTS__`/`__APPLY_SHOT__(name)` (idempotent), `__PUMP__(n)`/`__PRESENT__(n)`
as *observable page state* (one exhaustible clock word, vg.js D2), a
`__READY__` that is a frame count over drawn frames (D6) and not a wall-clock
timeout, `__RENDER_INFO__` as the per-shot telemetry receipt, fresh-page-per-shot
baselines (isolation; the kit's own lesson re learned-on-a-shared-page: 10 of
11 differed), and `imagediff.mjs`'s gate shape (`identical`, `withinEpsilon`,
`changedPct`, `maxDelta`, bbox, `...diff.png`). Refuse: its kit editor UI, its
example scene as anything but a fixture, and screenshot-as-verdict on heavy
pages without the internal ground truth (`__RENDER_INFO__`) beside it.

---

## 3. Vibe3DScene, transactional execution against headless Blender

`bpy` spec fetched in phase 1 (`research/vibe3d.md`); run today as
`run_vibe_transactions.py` against headless Blender **4.0.2** with the bundled
`blender-mcp-vision` addon (MIT; the Vibe3DScene tree itself is Apache-2.0).
Raw: `results/vibe-transactions/records.json`; working scene in
`third_party/vibe-transactions/` (snapshots, `state.json`). Six edits — well
beyond the asked three — and every one of them is a *designed* outcome,
including the failure paths:

| # | label | outcome | executed/committed | rolled back? | wall |
| --- | --- | --- | --- | --- | --- |
| 1 | `clean-edit` | ok, `crate placed` | yes/yes | no | 0.003 s |
| 2 | `guard-violation-rollback` | error: `Scene guard validation failed after execute_code: object_location_outlier: crate (rollback succeeded)` | — | **yes**, `state_restored: true` | 0.008 s |
| 3 | `exec-error-rollback` | error: `Code execution error: mid-edit failure (rollback succeeded)` | — | **yes**, `state_restored: true` | 0.007 s |
| 4 | `raw-delete-refused` | error: `Raw object deletion via execute_code is disabled. Use delete_objects(...mode=...) for hierarchy-safe deletion.` | never ran | refused up front | 0.000 s |
| 5 | `guard-violation-no-rollback` | error: `... object_location_outlier: crate (rollback not requested)` | — | **NO** — `state_restored: false`, the teleport stands | 0.001 s |
| 6 | `safe-mode-off` | ok, committed | yes/yes | no snapshot (`available: false`) | 0.000 s |

**Numbers worth keeping.** The `clean-edit` transaction shows the shape of the
guard: `object_count` 2 → 3 (`delta: 1`), `scene_bbox_max_dimension` 2.0 → 3.0,
`location_outlier_count: 0`, `invalid_numeric_count: 0`, and — importantly —
the **thresholds themselves are in the record** (`max_coord_abs 5000`,
`max_scene_growth_ratio 100`, `max_object_count_delta 1000`).
Each commit also writes a rewind artefact: `snapshots/snapshot_000001.blend`.
The violation in #2/#5 is ours (`crate.location.x = 9999.0`)
`object_location_outlier: crate` — and the row #5/#2 pair is the whole
argument in one line: **the same guard failure restores the scene iff the
transaction asked for the right to roll back.**

**What to take into vibecode-in-world (§7).** (a) the transaction is
`select snapshot → execute → guard → commit|rollback`, which maps 1:1 onto the
design's `draft → proposal → pre-flight → commit`; (b) the guard's before/after
metrics WITH the thresholds visible in the record — that is the pre-flight
receipt, and the design's wire-world-guard and `check timeline plausibility`
already agree on it; (c) the per-commit rewind artefact backs the design's
"each commit returns an askable visual artefact": for the live world the
artefact we can produce is not a `.blend` but the *recorded action path* plus a
full state diff — and (d) the `rollback not requested` case is the failure mode
the design must forbid outright: a commit with no rewind data is an
*irreversible* step and has to be labelled as one (GC E's "why did you change
that?" includes "because a tool did it"). Refuse: `safe_mode: off` (it silently
skips the rewind artefact — exactly what we must never do), delete via raw
`execute_code` (already refused by the tool for hierarchy-safety; our action
paths are the equivalently structured endpoints), and treating a `.blend`
snapshot as the artefact SET in the viewer loop.

---

## 4. The prototype: the contract on the live viewer

One piece is worth keeping from the kit, so it goes onto *our* GL: the capture
contract, standing up on `agent-world/world/viewer/` — the live in-world
renderer, with the world that a player (here: a second spectator bot
`Watcher2gw`) actually walks. `run_aw_gate.sh` copies the viewer into
`third_party/aw-viewer/`, injects `aw-viewer-gate/gate-shim.js` into the copy's
page (`window.__READY__ = false` only until the first rendered frame, ...) and
points the kit's `capture.mjs`/`baseline.mjs`/`imagediff.mjs` at it. Raw all in
`results/aw-viewer-gate/`; the copy is killed at the end (trap + `jheadstop`),
world untouched.

**The seam problem first (release-notes material).** Three.js's `window.__THREE__`
is the *revision string* (its multi-instance marker), not the namespace: the
bundle exposes no THREE handle, no chunk registry, nothing to wrap
`WebGLRenderer.prototype.render` on. The shim therefore instruments at the
seams that ARE public: the page's WebGL context (draw calls, triangles,
programs, buffers) + a `requestAnimationFrame` wrap for frame bounds + the
viewer's own OrbitControls input for posing the camera (this bundle's
OrbitControls has no damping and no pointer capture, so a drag lands on the
exact spherical pose one frame later). Shots are absolute `(orbit px, orbit px,
dolly notches)` tuples so applying one twice is idempotent — the contract's
rewind safety at the input seam instead of the object seam.

**Diagnostics say it works.** `shim-diag.json` for one page: ready after 3
drawn frames, cumulative `calls 50268`, `triangles 67.6 M`, `programs 3`,
`buffers 4652`, `textures 68` — the shim sees the real world stream.

**Three runs, one finding each.** (1) free-running page: 93.9 % run-vs-run drift
on the shot over the streamed world (the kit's isolation/lockstep lesson, in our
teeth). (2) lockstep + a `settleWorld` quiet barrier: `roped in` far better
(0.14-0.15 %) but the far-chunk shot still drifts 26.4 % — total buffers differ
per page, 3756…4370+: our world STREAMS and its total stream set is not fixed
by wall-clock quiet alone. (3) final: `?capture=1` also hides the viewer's own
DOM banner (an on-screen notice that FADES with wall time, invisible in the GL
counters), `settleWorld` asks for 30 quiet frames AND 8 s of wall clock. Then:

| gate | result |
| --- | --- |
| run 1 baselines vs run 2 baselines (same shots, fresh pages) | drift **0.034 %** (watcher-wide), **0.313 %** (watcher-detail), **0.373 %** (watcher-tilt); `maxDelta` 207-224 in localized bboxes (e.g. `{x:493,y:368,w:468,h:172}`) |
| run 1 vs `?tilt=1` (deliberate camera change, every shot) | **98.9 / 99.2 / 99.3 %** pixels, `maxDelta` 245-253, full-frame bbox |

So: the same frame twice lands within 0.4 % of pixels (and the *bboxes* say
where the residual lives — world streaming seeds + time-animated pixels), and a
real camera change moves the other 98-99 % of the frame. A separation of
**~300x** between "noise floor" and "deliberate change" is a working pixel gate;
the residual is not nondeterminism in the contract, it is the one thing the
contract cannot pin by itself and must carry: the world's own state.

**What to take into vibecode-in-world (§7), concretely.**
1. Port the contract as-is at the page seam: `__READY__` (3 drawn frames),
   `__PUMP__(n)`/`__PRESENT__(n)`, `__SHOTS__`/`__APPLY_SHOT__(name, settle)`
   (idempotent), `__RENDER_INFO__` (calls, triangles, programs, buffers,
   frames, drawnFrames) — the vg.js `D6`/`R` words spelled out.
2. `?lockstep=1` is not optional for the gate: without it the loop races the
   shutter (documented lesson: 48 pumped frames cost >30 s under software GL
   readback, the page's own log says `ReadPixels` stall).
3. **`D1` has to pin the world manifest**: the residual 0.03-0.37 % is exactly
   unloaded/streamed chunks and animated pixels. The proposal step's snapshot
   response must include the world manifest + resource pack pinning (the
   design's render pins already name the manifest; the gate proves those pins
   must be enforced, not merely named).
4. The DOM is part of the pixels: any banner/notice/coordinates overlay must be
   off or canonisable under `?capture=1` — the viewer copy's shim hides all
   non-canvas DOM for capture.
5. The camera can be unreachable: the contract must be implementable at the
   input seam (OrbitControls) and still satisfy `report.residualDeltas` with the
   *reason-labelled* min/zeros rule (rewind, proven-unchanged, promised-blocked,
   promised-preview, sanctioned-drift) — `unreachable camera` is not an excuse
   for silently different frames.

**Prototype-standard compliance, honestly (pre-release check).** mostly yes:
blocks (`aw-viewer-gate/gate-shim.js` `:1-300` roughly)
multi-level-parameter-drafting no (no clients asked), JSON-not-XML N/A,
fronts-before-leaves no (inbox-first N/A at page seam; capture order is
wide→detail→tilt as listed), tool-result-truncation yes (every step writes JSON
to `results/`; the log tails are shell only), infrastructure-config-as-ok no
(GC D fixture-inline exception OPEN — `?tilt=1` lives in the shim), success-
path-sized-bubble yes, one-way-information no (nothing is swallowed),
implementation-correctness yes.

---

## Verdict table

| tool | keep | refuse |
| --- | --- | --- |
| topview-3d-builder | grounding/overlap pre-flight vocabulary with published tolerances (`checksComplete`/`checksBlockedBy`) as an early deterministic gate | its camera schema, `pending-model-review` as a verdict, character-node coupling |
| build-world kit | the capture contract + pixel gate (`ready/pump/present/shot/RENDER_INFO`, fresh-page baselines, imagediff shape), plus the pump-depth-is-shutter-cost lesson | any authoring/UI ambitions (no gizmos, no undo, no placement to build on) |
| Vibe3DScene | `snapshot → execute → guard(metrics+thresholds) → commit\|rollback`, per-commit rewind artefact, `rollback not requested` as the ONE explicitly-irreversible class | `safe_mode: off`, raw deletes, `.blend` snapshot as the artefact set |
| our viewer prototype | the port contract above (5 items), and `D1` pin-the-world-manifest as the gate's precondition | pretending the pixel gate is a verdict on the world — it is a verdict on the contract |

## Open risks

* The residual 0.03-0.37 % on the viewer gate: one more file of numbers on a
  *pinned* (manifest-tight) world would separate "streaming seed" from
  "animated pixels" properly. Next: build the tight-manifest fixture (the
  `KEEP-it` shot set) and rerun.
* `imagediff`'s timeout `--tol` untested (we used `tol 0`); the 0.05 % threshold
  needs to be derived per scene before it means anything beyond 300x here.
* `run_bw_glb.sh`'s `capture.mjs` step is expected to fail its shutter on the
  5.8 M-tri page (`exits.txt` says `capture exit=1`) until the queue-drain fix
  lands upstream — recorded, not hidden.

*next: readonly-first sweep (gentle): unify these contracts into the
vibecode-in-world `moments` spec — the page contract, the pre-flight receipt
and the residual-delta rule are now all three empirically paid for.*