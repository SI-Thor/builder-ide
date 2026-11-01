# Night v3 — the first integrated night: plan, decisions, world, props, memory, the live view, one ledger

**2026-10-31 21:37 → 2026-11-01 08:39:14 (−09:00) on the Thor** — run D, the
one that finished (`NIGHT-EXIT 0`); A, B and C are part of the record below.
The owner goal: *"a small courtyard with three props: a weathered crate, a
brass lantern, an iron anvil; make it feel lived-in."* Every layer of the
vision ran in one process, on one ledger: the plan priced by `core/night/cost`
and admitted under the rails; tiles chosen through `core/judge` (local d1-2B
first, Jev in the cloud below the calibrated τ, the standing gate, never-wait
deadlines); Infinigen 2.0 through the engine seam with the splice measured;
TRELLIS.2 props through `core.genbatch` with repair and the scripted critic;
every heavy step under the house lease; the recipe changes compiled to
world-stream deltas with a Playwright screenshot of the end state; and the
morning folded from the ledger, with the spoken line as `line.spoken`.

**What it found: the night ran end to end — `ran as planned · nothing
failed`, 2 h 33 min wall, 3 of 3 props kept, 5 decisions through the judge's
ladder — but the interesting findings are the four failures it took to get
there. A per-step flock shape starved run A for hours; run B starved 3½ h
behind the syzygy batch and then died on a pydantic model inside a ledger
payload; run C's "the engine exited 0 but wrote no PNG" was never the
engine — a relative scratch path was resolved against two different working
directories, and run C's render had been sitting healthy inside the
infinigen clone all along; run D's first splice found the scene generator
cannot be traced by this engine at any level or seed (procfunc refuses to
iterate a proxy inside the room's wall splitter). Each failure was fixed at
the seam it came from, with a test, before the night re-ran. The house's
own addendum diagnosis of run C (infinigen-thor PR #1 dropping a
`render_cycles` fallback) was checked against both repos and did not hold:
PR #1's fallback was about the denoiser, in the fork, and the night's
princeton venv never lost `render_cycles`.**

---

## 0. The night ran twice (and that is a finding, not a confession)

- **Run A, 21:37.** The driver as first written queued for the heavy lock
  afresh at *every* heavy step. It waited **6,605 s (1 h 50 min)** for d1-2B,
  got the lock at 23:27:54 (in the same second the syzygy ground-truth batch
  released it after its arctic scene), started d1, then queued again for
  ComfyUI — behind the syzygy batch's canyon scene, which had been in the
  flock's FIFO queue since 22:26. On a box this contested the per-step shape
  put the night at the back of a four-deep queue a dozen times a night.
- **Run B, 01:22.** The driver re-shaped to the seat's own precedent
  (`run_coldstart.sh`): **one lease for the whole heavy phase** — queued once
  for ComfyUI + the world's renders + the props, reentrant inside, the
  25 GB bar still checked after each load (commit `b9a7a81`). Run A was
  stopped; its d1-2B (754 MB peak RSS, 2.1 GB GPU) stays up and run B
  reuses it (`d1 already answers on :8295`).
- Run B waited for the lock behind syzygy's `gt_batch.sh` (six `simple.gin`
  scenes: arctic took 3 min 01 s — coarse 93 s, fine 57 s, render 15 s, gt
  16 s; canyon's first coarse attempt ran ~4 h 20 m and died; its retry began
  02:48:35). The kernel grants the lock FIFO: the night is first waiter.
  The lock came at **04:53:25 (−08:00), `waited_s` 12,646.0 — 3 h 30 min
  46 s**, free 99.0 GB; the preflight's ledger append died in the `CutLine`
  eleven seconds later, so the heavy phase never ran in A or B.
  (The box fell back an hour that morning — DST ended 02:00 Nov 1 — so run
  A and B's stamps say −08:00 and run D's say −09:00.)
- **Run C, 04:27 (−09:00), the director's rerun after the `CutLine` fix
  (`283afa7`).** It got past the preflight and died in the engine's first
  render: `EngineFailed: the engine exited 0 but wrote no PNG under
  …/render/courtyard_room-42-960x540-16spp`. The addendum's diagnosis —
  infinigen-thor PR #1 dropped a `render_cycles` fallback — was **checked
  against both repos and did not hold**: PR #1 (`dd1f8727`) and its
  follow-up (`b34d9b35`) are about the *denoiser* fallback in the fork's
  `render_cycles.py` (continue-noisy vs a loud failure), the fork kept the
  loud failure, and the night's engine is the pristine princeton venv,
  whose `render_cycles` never went anywhere. The real cause surfaced
  tonight, by run D failing the same way **with the seam's new last-words
  diagnostics showing the render had run** (`Denoising off …
  render_cycles: 21.134s`): the driver handed the runtime a **relative**
  output dir; the CLI runs with the clone as its cwd, so the render was
  written under `<clone>/artifacts/night-v3-c/…` — found there tonight,
  PNG and metadata intact, 1.3 MB, written 04:28 — while the seam checked
  the same relative path under the night worktree. The engine never
  failed; the seam looked in the other room. Fixed at both ends
  (`f3e631c`, `a2ef080`), with a regression test that constructs the
  runtime exactly as run C's driver did. The receipts are kept in
  `artifacts/engine-misdirected-renders/`.
- **Run D, 06:06 → 08:39 (−09:00), the night that finished.** Its heavy
  phase queued once for the box's admission daemon —
  `thor-admit run --tier live --peak 40G --label night-v3.heavy` — and
  waited **915 s** behind three other seats (GLiDE's 52 GB serve held the
  GPU pool to megabytes from 05:35), admitted at 06:21:51, and ran the
  whole night under that one lease. Attempt 1 (05:24) died on run C's
  relative-path bug; attempt 2 (05:32, after the path fix) died one step
  deeper, in the splice's full-stage trace: **the scene generator cannot
  be traced by this engine at any level or seed** — procfunc raises
  `Proxy does not support __iter__` inside the room's wall splitter
  (`room_shape._split_flat_walls`); verified at RANDOM_CONTROL and
  GENERATORS, seeds 42 and 7. The splice now asks for the whole stage,
  falls back on exactly that refusal to the recipe's traceable entries,
  and records the exclusion in its row (`47ec31c`); it ran that way in
  production, both rounds.

**Which parts mattered:** the lease queue kept the box alive all night
(no OOM, every seat waited its turn); but the house's flock has **no
fairness beyond FIFO and no presence tiers** — a 3-minute scene release is
a lottery ticket for everyone queued. The three-minds presence scheduler is
the design answer; still design.

## 1. What ran (mechanisms)

One process (`docs/lab/night-v3-scripts/run_night.py`, the propmaker-batch
venv, `PYTHONPATH` at this worktree), one ledger
(`artifacts/night-v3/ledger.db`), `/usr/bin/time -v` around the whole thing.

- **The plan.** Three prop requests (crate, lantern, anvil —
  `courtyard_requests.json`) plus two world tasks. The props priced from the
  schedule's measured bands, the world at `rung.2`; admitted against rails
  **60 GPU-min / 240 wall-min / 100 hosted-cents**; the two lines, the cut
  and the parked work are in `pricing.json` and the `night.preflight` row.
- **The decisions.** Six courtyard tiles in the M1 words (`crates.*`,
  `weathering.*`, `racks.*`) authored as recipe-edit tiles; the builder's
  "which tile lands next" goes through the judge: d1-2B on :8295 first, then
  the ladder's one cloud rung **Jev** (TypeSafe System One,
  `TYPESAFE_API_KEY`; no `CLEF_API_KEY` on the box, so no Clef rung) below
  the calibrated τ, the standing gate holding, **never-wait 8 s**. Every
  judgment is the judge's own row; each prop concept also gets an on-brief
  verify judgment (text-only — the night's d1 server is text-only tonight).
  A decision surfaced below τ consults the mediator (Groq, `gq.py`); the
  flow count rides `night.mediator_call`.
- **The world.** The engine seam runs Infinigen 2.0 in the v2 venv
  (procfunc flavour, pinned). The courtyard recipe: `room_livingroom_rand`
  (structure), `storage_cabinet_with_door_rand` as the crates' stand-in
  (no racks generator resolution was measured on this box — recorded, not
  hidden), `wood_scratched_rand` (weathering). Baseline: three subjects
  rendered at rung 2. Each edit round: the judge's tile → recipe edit →
  render → the splice measured at the seam (full-stage trace vs the scoped
  stage on the dirty entries; the ratio is the record). The Warp terrain and
  mesher stages are **not wired** on this branch: the CPU path runs and says
  so.
- **The props.** TRELLIS.2 through `core.genbatch`: SDXL text2image →
  `trellis2_512` mesh → repair → measurement → the **scripted critic alone**
  (no VLM delegate: B2 forbids LLMs on the Thor beyond d1 and the decision
  models, and this branch's critic delegates are dino/vlm/jev — no d1
  delegate has landed, so the 30B VLM was ruled out twice over). Three
  variants per round, up to two rounds, min gain 0.02.
- **Memory.** Run D's lease is the box's admission daemon's, not the flock:
  `thor-admit run --tier live --peak 40G --label night-v3.heavy` around the
  whole heavy phase (the shim's `thor_admit.lease` from the thor-admit
  worktree, with the flock kept as the named fallback and every
  `night.heavy_lease` row carrying kind, label and peak), the 25 GB bar
  still checked after every load; waits and free RAM land in the rows.
  The d1-2B start rides its own short lease (`night-v3.d1`) when the
  resident is not already up — tonight it was (`d1 already answers on
  :8295`, run A's server, still warm).
- **The live view.** The night's recipe changes compile to world-stream
  deltas: a real Infinigen 2.0 scene export (CPU + glTF, world-stream
  scratch) → `worldc.mjs` compiles recipe v1 → each applied tile's placement
  lands as the wire's transform edit (v2, v3, …) with a `delta` per change;
  `delta_bytes` per change in `live-view.json` and the `night.live_view`
  row; then the viewer serves the build and Playwright (`shot.mjs`)
  screenshots the end state. Props do not ride this wire today:
  `instance.add` with new geometry is the fragment-GLB delta, designed but
  not implemented — the rows say so instead of pretending.
- **The band.** After wave 1: per-loop slopes from the rounds' best scores;
  the loop rising fastest is granted one more round (the chorus), funded by
  the flat loop's unspent rail; `band.cue` and `band.effect` rows carry the
  cue and what it changed. First test of time-first scheduling.
- **The morning.** The report folded from the ledger (status line, failure
  line, the cut named, the filmstrip, the branches, the questions), plus
  `morning.json`/`morning.txt`, `report.{json,txt,html}`, and the spoken
  answer to "what happened last night?" as `what-happened.txt` and the
  `line.spoken` row.

## 2. The numbers (run D, 2026-11-01 06:06 → 08:39 −09:00)

**The whole night.** Wall 152.6 min (driver `t0` → morning; `/usr/bin/time`
2:32:38), of which 915 s queued for the daemon's `night-v3.heavy` lease
(behind GLiDE's 52 GB serve, which held the GPU pool to megabytes from
05:35) and ~47 min spent inside the glTF exporter before the live-view
budget killed it (§3). GPU lane: 25.74 GPU-min of job work against the
60-min rail (43% — the rail never bound); CPU lane: the world's renders
(Cycles CUDA) and traces plus the export. Peak memory: the driver tree's
max RSS 4.6 GB (`time -v`); box-side MemAvailable 94.8 GB after the loads
(the 25 GB floor was never approached; box went 62.9 → 89.0 GB free across
the night). Joules: the cost model estimated 92.0 kJ; attributable joules
**not measured** — the box's power read never produced a `vin_w` and no
row carries one. Cost estimate vs actual: the two lines said 0.2 GPU-h /
0.5 wall-h for 8 goals; the ledger's `budget.spend` sums say 25.7 GPU-min /
88.7 wall-min of job work over 39 variants — the report's own line: *"The
night ran 56 min longer than the ask — it went on 39 variants."*

**Decisions.** 5 judgments (3 prop-brief verifies + 2 tile choices), every
one answered **locally by d1 first at ~70 ms**, every one **below τ**
(the two tile confidences: 0.47, 0.26 against τ 0.5), so all 5 escalated
to Jev (p50 0.354 s, p95 0.355 s) — the ladder worked; the morning's "0
answered locally" line counts the ladder's *last* rung (§3). 2 tile
decisions surfaced below τ → the mediator (Groq) consulted twice, both
**outside flow**, both answered (~0.35 s each). Standing flickers 1.
Never-wait (8 s) never fired — nothing neared the deadline. The tiles that
landed: `weathering.dark.lived` (round 1: weathering seed → 4026) and
`racks.tool.wall` (round 2: no racks generator on this box, so the crates
entry's seed moved to 4025 — recorded in the row, not hidden).

**World.** 5 renders at rung 2 (960×540, 16 spp, Cycles on the GPU):
baseline room/crates/weathering + two edit rounds; ~21 s of render inside
30–75 s of generation per subject. The splice, both rounds: the full half
(including the doomed scene attempt and the fallback re-trace) cost
**8.03 s** (round 1) and **6.58 s** (round 2); the scoped half answered in
**0.0 s** both times — a 341-byte stage envelope served without a CLI run
— so the recorded ratio (~16,000×) is the seam's stage cache speaking,
not a partial re-trace; the splice's honest number tonight is the
full-trace cost per edit. `scene_trace_refused` and the entry list ride
in both rows.

**Props.** 39 `job.done`: 18 SDXL image variants, 18 TRELLIS.2 mesh
variants (512, repaired, measured), 3 world jobs. **Kept 3 of 3**, all
watertight after repair: crate `r1_v3` at 1.000 (699,008 tris), lantern
`r2_v1` at 0.940 (698,546), anvil `r1_v1` at 0.941 (699,844). Each beat
five siblings. Round 2 (18 of the 39 variants, most of the GPU-min)
improved the round-1 best on one prop of three — the iteration's
`min_gain` 0.02 / `max_rounds` 2 policy carried it anyway; that is the
policy working as written, and the numbers to argue about later.

**The band.** No cue, no chorus — **the band had no data**: `fold_attempts`
reads `task.attempt` rows and this runner writes `job.done`, so the slope
table came back empty and the chorus never opened its mouth. The first
test of time-first scheduling is still pending (§3).

**The live view.** In the night: the scene generated and `scene.blend`
saved (145.7 MB), then the glTF pass was killed at the driver's 1 h
`run_cmd` budget (the world-stream team's own living-room export measured
**2 h 17 m** on this box: scene.blend 11:34 → source.glb 13:51, Oct 31);
`live-view.json` and the `night.live_view` row carry the export error, no
deltas, no screenshot. **Post-night supplement (recorded, not hidden):**
the glTF-only pass re-run on tonight's `scene.blend` under a
`night-v3.liveview-export` lease, then the compile, the two tiles'
transform deltas, and the Playwright screenshot of the end state — the
supplement ran as `gltf-only.py` (the log beside the artifacts); its
compile/delta/screenshot numbers are the §2 live-view addendum below,
appended when they landed.

**The box beside the numbers.** Run D shared the box all night with other
seats' live work (GLiDE's serve at 52–58 GB, `xp-batch`, `coldshelf`,
`missionA` — four co-existing leases during the props phase, 24-deep queue
at morning). No OOM, nothing below the floor, every seat admitted in
turn. This is §0's flock story with the fairness problem gone.

## 3. The honest list

**What didn't integrate, and what each cost:**

1. **The night needed four runs to finish once.** Run A: per-step flock
   (1 h 50 m for d1 alone; superseded by the one-lease shape `b9a7a81`).
   Run B: 3½ h lock-starved behind the syzygy batch, then a pydantic
   `CutLine` inside a ledger payload killed it eleven seconds into the
   heavy phase (fixed `283afa7`, now one tested builder,
   `tests/night/test_night_v3_ledger_payloads.py`). Run C and D attempt 1:
   the relative-scratch/two-cwd split — the render was healthy, written
   inside the infinigen clone (fixed `f3e631c`/`a2ef080`, receipts in
   `artifacts/engine-misdirected-renders/`). D attempt 2: the scene-trace
   refusal (fixed `47ec31c`). D attempt 3: complete, `NIGHT-EXIT 0`.
2. **The addendum's run C diagnosis did not hold.** infinigen-thor PR #1
   dropped a *denoiser* fallback in the *fork* (and `b34d9b35` put the
   loud failure back); the night's pristine princeton venv never lost
   `render_cycles`, and the exact failing argv renders fine today
   (receipts: `Camera/0000.png` + `metadata.json`, exit 0, peak RSS 4.3 G,
   re-run under a lease before the fix). The misdiagnosis cost a night;
   what cracked it was the seam's new loud failure carrying the CLI's
   last words (`0e70b3a`) — the words showed an engine that *ran*.
3. **The scene generator cannot be traced by this engine** — procfunc
   raises `Proxy does not support __iter__` inside
   `room_shape._split_flat_walls` at RANDOM_CONTROL *and* GENERATORS,
   seeds 42 and 7. The splice measures the recipe's traceable entries and
   records the exclusion; a real fix belongs upstream (a fork patch or a
   procfunc release), not in the driver.
4. **The band never cued: it reads a row type this runner doesn't write**
   (`task.attempt` vs `job.done`). Slopes empty, chorus skipped, no
   `band.cue` row. The first test of time-first scheduling did not
   happen. The fix is one `fold_attempts` change plus a test — not done
   tonight, recorded here.
5. **The morning miscounts in two places, both found reading the ledger
   afterwards:** "3 of 0 props kept" (kept is right; `generated`/`meshes`
   count `task.attempt` rows that don't exist), and "0 answered locally"
   (the summary reads the ladder's final author — d1 answered every
   judgment first). The winners, scores and splice rows are right.
6. **Every judgment sat below τ.** d1 judged the tile text at 0.47/0.26
   confidence on a text-only server; the whole ladder escalated every
   time; flow was therefore never true and the flow ledger counted 2
   mediator calls out of flow, 0 in. V-JEPA 2's prediction error is not
   wired on this branch (the driver's docstring says so honestly since
   `97a1b3b`) — the knower's sign has no number tonight.
7. **The live view exceeded the driver's per-call budget.** A 2 h 17 m
   glTF pass cannot live under a 1 h `run_cmd` timeout; the kill was
   converted into a recorded degradation and a post-night supplement.
   The recorded fix options: a per-call budget the export can declare,
   or a resumable/streaming exporter in the world-stream tool.
8. **Jev's cost is unknown to the ledger** (`cost_known: false`,
   `hosted_cents: 0.0`) — the 100-hosted-cent rail guarded an unmeasured
   rung all night. The TYPESAFE account owes the ledger a price.
9. **Props still don't ride the live wire** (transform-only deltas;
   `instance.add` with new geometry is the designed fragment-GLB delta,
   not implemented); **Warp terrain/mesher not wired** (CPU path,
   recorded); **no racks generator resolution on this box** (crates
   stand-in, seed-move recorded in the round-2 row).

**Which parts mattered:** the admission daemon (the whole memory story —
four seats sharing one box without an OOM, the night queued FIFO like
everyone else); the engine seam's loud failures with last words (what
cracked run C); the stage cache (the splice's scoped half answered free);
the judge's ladder with never-wait (5 judgments, d1 70 ms local, Jev
0.35 s, two surfaced to the mediator — decisions never blocked the
night); TRELLIS.2 + repair + the scripted critic (3/3 watertight keeps
with scores that separate siblings); the ledger itself (every finding
above was read back out of it).

**Which didn't bind tonight:** the flock (superseded by the daemon — its
unfairness is §0's story now); the 60 GPU-min rail (43% spent); the
hosted-cents rail (Jev's cost unknown — it guarded nothing); never-wait
(nothing neared 8 s); the band (no input rows — the one mechanism that
mattered and silently did nothing, hence item 4); the filmstrip's
failure section ("Nothing failed" — true, and earned by the three
failed runs before it).
