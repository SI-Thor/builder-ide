# night-v6: the ghost gets a second look, and the live view lands

**The brief** (`BRIEF.md` on the Thor, 2026-11-02 06:53): four things.
Fix the Biographer letter's miscount (it said "1 of 5 decisions answered
locally" while the run recorded 251 decisions, 245 on the local d1-3B)
and test that the letter's numbers equal the ledger's; give the ghost a
second look in the cloud (one DeepInfra VLM call, drop only if it agrees,
as a parameter); find a cheaper export path so a `source.glb` lands
inside a night; run the full night from the one command under
`thor-admit` with honest peaks, one lease above 30 GB at a time, and
write this document and the letter.

The owner goal is unchanged: *a small courtyard with three props — a
weathered crate, a brass lantern, an iron anvil; make it feel lived-in.*

---

## 1. The facts the change stands on

**The letter and the measurements counted different things, and both were
honestly derived.** The night-v5 letter said "1 of 5 decisions answered
locally (4 went to the cloud)"; the same morning's measurements said 251
decisions, 245 on the local d1-3B. The letter read `morning.json`'s
`decisions` block, which the runner folds from the JudgeSeat's in-memory
list — one entry per decision the seat itself finished. The routed decoy
cell's 240 verdicts (asked through the probe's own `Judge`, never the
seat), the two refused attempts, and the local half of every escalated
decision never reached it. The ledger's `judge.verdict` rows are one row
per **attempt** — refusals included — and that is what `measure.py`
counts. Two units, one word ("decisions"), and a letter that disagreed
with its own receipts.

**The ghost's degeneracy is in the mesh, not the picture.** Night-v5's
ghost — `prop:lantern_r2_v3`, plausibility 0.0385 against the 0.05 gate —
was meshed from `lantern_s1205_00007_.png`, a well-formed brass hurricane
lantern picture (verified on the desk, 2026-11-02). The mesh's occupied
volume is 1.004: a solid block filling its bounding box. A second look at
the *picture* would have praised it; the second look has to see the
*mesh* — so the prop's GLB is rendered (three orthographic turntable
views, Cycles CPU, 640 px) and the renders are what the cloud model is
shown.

**The live view's export never failed on triangles. It failed on
Infinigen's material node graphs.** The standing explanation — Blender's
exporter walking 11 M evaluated triangles — does not survive measurement
(on this box, 2026-11-02, all against night-v5's own saved `scene.blend`):

* the scene holds **2,899,618 base polygons** in 110 mesh objects, and
  **2.65 M of them — 91 % — are three `cushion_throw_pillow_rand` objects
  at 884,736 polygons each, with no modifiers at all**; 28 Subdivision
  Surface modifiers (levels up to 6) ride the rest. Capping subdivision
  cannot touch the pillows.
* the density curve: one cushion, alone in a scene, exported with the
  night's own kwargs — decimated to 5,000 polygons it exports in
  **36 s** (645 KB); held at 50,000 polygons it ran **past 6 minutes**
  without finishing. The extractor's cost blows up with density, not
  linearly.
* the stall: two full-scene runs (subdivision capped; then capped and
  decimated at 50k) both went silent after the small meshes — 15 and 34
  minutes at 100 % of one core. A **py-spy** stack dump put the process
  inside `gltf2_blender_search_node_tree.__search_from_socket`, recursing
  through **Infinigen's procedural material node graphs**. The exporter
  walks each material's node tree to find its textures; that search —
  not the triangles — is the 115/136/240 minutes every previous night
  paid.

**The cheap path, measured end to end.** Placeholder materials (a default
material; no node-tree search) + subdivision capped at the saved cages +
a collapse Decimate modifier on every mesh over 5,000 base polygons:
**`source.glb` 22,826,792 B in 75.2 s of export wall** on night-v5's own
scene, 12 objects decimated, 28 subdivision caps, the trade recorded on
`export_stats.json`.

**The second look costs seconds and cents, once per ghost.** On
night-v5's own ghost (`lantern_s1205_00008_.glb`, 698,897 triangles):
renders 7.3 s, one DeepInfra call (Qwen/Qwen3-VL-30B-A3B-Instruct,
temperature 0, 1,306 prompt + 19 completion tokens) 8.1 s, **$0.0002**.
The answer: *"No. The object is a solid cube with no openings or features
resembling a brass lantern."* — the cloud **agrees** with the prior.

**Two box facts, both found the hard way.** This box's bpy (the v2 venv)
segfaults — or hangs — during interpreter teardown after a Cycles render
or a long export, with every file already written (rc −11 measured; the
final export measurement had to be killed by hand at exactly that point).
And a v2-python child spawned from the propmaker-venv python with the
parent's environment segfaults the Cycles render itself; the child needs
a scrubbed environment.

## 2. Why the old way failed

**The letter's unit was the seat's, not the ledger's.** A letter that
says "1 of 5" beside a measurements file that says "251" is a letter that
cannot be trusted on any number — the count was honest and the unit was
unnamed. And the bug had a second face in `facts_from_ledger.py`: its
"local" counted every attributed row (`author != '?'`), which includes
the cloud's four, and its "surfaced" read a `gate` key the verdict
payload does not carry (the gate lives on each judgment inside
`judgments`) — it always counted 0.

**The ghost was dropped on the prior's word alone.** Night-v5's letter
asked what to do with a ghost; the run had already answered by behaviour
(score 0.0, the prop gone) — an instrument that can end a prop with no
second opinion and no parameter to soften it. A rank against a group of
ten measured crates is sharp, and sharp instruments get a second look in
every other part of this system (the judge escalates, the delegate
votes); the ghost had none.

**The export's bound was moved twice and the cost was never measured.**
Night-v5 raised the bound from 3600 s to 4 h after the first bound killed
the night (a `TimeoutExpired` that took the whole run down — itself
fixed in v5 to record a gap instead); the re-run then spent 240 minutes
at the bound and was killed mid-walk, `scene.blend` written, no
`source.glb`. Both repairs were honest and neither asked *why* the export
cost two hours — so the seam stayed a gap that was written down rather
than a wire that ran.

## 3. What changed

The runner (`docs/lab/night-v6-scripts/run_night.py`) is night-v5's with
the brief's three changes, plus two repairs the night itself forced, and
the scripts that carry them:

1. **The letter speaks the ledger** — `decision_counts.py` is the one
   counter (the `measure.py` split factored out: local / cloud / refused
   by author, gates from `judgments[*].gate`). The runner folds the
   ledger's own count into the morning (`decisions.ledger`); the letter
   writer counts the ledger beside the morning (`--ledger`, default
   `<out>/ledger.db`) when the block is absent, and only a letter
   written before a night ran falls back to the morning's block.
   `tests/night/test_letter_ledger.py` pins the letter's numbers to the
   ledger's — a synthetic ledger in the v5 shape (245 d1 + 4 cloud + 2
   refusals) with a morning still claiming "1 of 5", and the real
   night-v5 pair as a regression anchor.
2. **The ghost's second look, a parameter** — `--ghost-policy
   {second_look,drop,keep}`, default `second_look`. drop is night-v5's
   behaviour; keep records and keeps the score; second_look renders the
   prop's mesh (`render_prop_views.py`: three orthographic turntable
   views, Cycles CPU) and asks one DeepInfra VLM call a fixed question
   (`second_look.py`, temperature 0) — **the prop drops only if the
   cloud agrees**. A second look that cannot answer (no key, wire down,
   no GLB) is not agreement: the prop stays, degraded, with the error on
   the row. Both verdicts ride one `night.ghost_second_look` row
   (registered in the three closed event sets); the prior's note carries
   the policy and the outcome. `tests/night/test_ghost_policy.py` drives
   the real `_score_mesh` branch through all six outcomes.
3. **The export that lands** — the committed `export_scene.py`
   (`--materials placeholder --max-subsurf 0 --decimate-over 5000`, each
   threshold's measurement in its `--help`), called by the runner in
   place of the scratch exporter, the bound down from 4 h to **3600 s**
   (~15× the worst measurement). The trade is recorded, not hidden: the
   live view's source is geometry at ≤5k polygons per object with
   placeholder materials, and the transform deltas the seam exists to
   measure are unaffected.

The two repairs the night forced (both committed with their evidence,
`3b3c344` and `dc12048`): the wedge-restart loop now honors the budget
its own design states (two restarts, not one — the first launch died on
the second of two wedges twelve minutes apart), with a 60 s quiet between
a restart and its re-run; and `serve_model` waits out a loaded box (900 s
health window) and no longer leaks the llama-server child it spawned when
it gives up.

`launch_night.sh` and `finish_night.sh` are v5's retargeted to this
worktree (`artifacts/night-v6`, the diff against night-v5's artifacts);
`measure.py`'s diff label no longer calls night-v5 "run D".

## 4. The pre-run measurements

* **The second look, on night-v5's own ghost** (above): renders 7.3 s,
  one call 8.1 s, $0.0002, the cloud agreeing — a ghost the policy would
  still have dropped, now with two receipts instead of one.
* **The export, on night-v5's own scene** (above): 75.2 s, 22.8 MB,
  12 decimations, 28 caps. The three dead runs that ruled out the
  cheaper-looking paths (cap-only: 34 min stalled; cap + decimate-50k:
  15 min stalled; both killed) are the numbers that say the materials
  were the cost.
* **The letter fix, on the real pair**: the night-v5 morning + ledger
  through the v6 writer — "245 of 251 judgments answered locally (4 went
  to the cloud, 2 were refusals)", 107 words.
* **The suites**: 6 letter tests, 6 ghost-policy tests, 17 ledger tests
  (the three closed sets pin equal), all passing before the night
  launched.
* **The dry run**: the full wiring on the fake engine and judge; the
  morning holds `decisions.ledger` and `critic.ghost_policy`.

## 5. The night itself

Three launches, one night. The first (08:08) wedged ComfyUI twice in
twelve minutes — the first wedge was survived exactly as designed (the
first `night.comfy_restart` ever rowed in anger: stopped, log kept, back
in 38 s), the second escaped a retry loop one restart short of its own
stated budget and killed the night at 08:23. The second (08:37) died at
start on a box a neighbour's 40 GB run held (`scenebloom-eval.bedroom`,
load1 14.7): the d1-3B's model load did not finish inside the 360 s
health window. Both dead runs are kept beside the live one
(`artifacts/night-v6-wedged-0823`, `artifacts/night-v6-unhealthy-0841`)
— a night that dies on a held box is a night that taught its runner two
repairs. The third (09:32:01 → 11:01:27, 89.44 min) ended **"ran as
planned — nothing failed"**.

| stage | night-v5 (23:48:39 → 04:37:13) | night-v6 (09:32:01 → 11:01:27) |
|---|---|---|
| the box | load1 14.43, MemAvailable 97.3 GB before; load1 4.98, 98.1 GB after | load1 7.77, MemAvailable 98.3 GB before; load1 5.71, 102.1 GB after |
| the leases | three thor-admit, peaks 6G / 6G / 40G, waits 0.0 / 0.1 / 0.1 s | three thor-admit, peaks 6G / 6G / 40G — the heavy the only one above 30 GB — waits 0.0 / 0.1 / 0.1 s |
| the decision servers | two llama-servers, the night's own children | same, both healthy on the first ask |
| the routed decoy cell | accuracy 0.5208, decoy-first 0.561, act 59 / escalate 0 / surfaced 181, p50 0.046 s | the same numbers on the same fixed replay (0.5208 / 0.561, act 59 / surfaced 181), p50 0.151 s on the loaded box |
| the prior | 48 reference members, 2 groups (10 / 38), gate live | same fit, same gate |
| the delegate | 18 calls, 0 failures, ~1.1 s each; 10 fired `holes` | 18 calls, 0 failures, p50 1.72 s; 10 fired `holes` |
| the GPU-pool bar | armed, 0 waits | armed, 0 waits |
| the wedge restart | armed, 0 restarts | armed, 0 restarts — after the first launch's two wedges put the budget fix in |
| the heavy phase | 40G → 8G at 00:37:13 (0.02 s) | 40G → 8G at 10:59:58 (0.01 s, 95.5 GB free) |
| the props | 3 kept (1.00 / 0.94 / 0.94), 15 rejected | **3 kept** (crate 1.00, lantern 0.946, anvil 0.947), 15 rejected — the owner's goal, again |
| the ghost | fired once (lantern_r2_v3, 0.0385), dropped on the prior's word alone | fired once (**the same** lantern_r2_v3, 0.0385 — the plan is deterministic) — **dropped after the second look agreed** |
| the second look | did not exist | renders 7.2 s + one call 19.6 s inside the night, 1,372 tokens, $0.0002; the cloud: "a plain cube with no openings, parts, or details resembling a lantern" |
| the live view | export killed at its own 4 h bound, mid-walk, no source.glb | **source.glb 22,826,792 B in 85.2 s inside the night** (generate 17.1 s + export 66.3 s); 2 deltas of 676 B each compiled and applied |
| the morning | written; the letter said "1 of 5" | written; the letter says **"245 of 251"** |
| the wall | 288.57 min | **89.44 min** |

**The ghost, both verdicts on the row.** The night's ledger holds
`night.ghost_second_look` for `prop:lantern_r2_v3`: the prior's 0.0385
beside the cloud's "plain cube" — `cloud_ghost: true`,
`outcome: dropped_after_second_look`. The prop that ended night-v5 as an
open question ended tonight as a decision with two receipts. That the
same variant is the ghost two nights running is the plan's determinism
doing its job: the seam is testable because the night is repeatable.

## 6. The measurements, beside the box state

From the night's own ledger and morning, measured by
`docs/lab/night-v6-scripts/measure.py` and written to
`artifacts/night-v6/measurements.txt` / `.json`:

```
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v6-scripts/measure.py \
    --night artifacts/night-v6 --against ~/lm-wt/night-v5/artifacts/night-v5
```

```
status      ran as planned — nothing failed
wall        89.44 min (night-v5: 288.57 — the export is the difference)
GPU         21.91 min of the 60-minute rail (night-v5: 14.66)
jobs        39, in 84.95 min of job wall (night-v5: 46.0)
leases      three thor-admit (peaks 6G / 6G / 40G), waits 0.0 / 0.1 / 0.1 s
phase       40G → 8G at 10:59:58 (0.01 s, 95.5 GB free)
decisions   251 rows — 245 on the local d1-3B (mean 0.0477 s), 4 on Jev, 2 refusals
gates       181 surfaced / 66 act / 2 escalate
props       3 kept (crate 1.00 · lantern 0.946 · anvil 0.947), 15 rejected
ghost       1 of 18 — lantern_r2_v3, plausibility 0.0385 (gate 0.05)
second look 1 call — the cloud agreed; renders 7.2 s, call 19.6 s, $0.0002
delegate    18 of 18 answered, p50 1.72 s; 10 fired `holes`
live view   source.glb 22,826,792 B in 85.2 s (generate 17.1 + export 66.3)
box         before load1 7.77 / MemAvailable 98.3 GB; after load1 5.71 / 102.1 GB
```

`artifacts/` is not in git: the ledger, the morning, the report, the
letter and the dead launches' artifacts stay on the Thor. This document
and `docs/lab/night-v6-scripts/` are the record.

## 7. The morning's letter

`artifacts/night-v6/letter.md`, written by the finisher
(`docs/lab/night-v6-scripts/write_letter.py`), **115 words**, every
decision number counted from the ledger beside the morning:

> Casey —
>
> The night kept 3 props (crate, lantern, anvil) in 89.44 minutes. The judge's decision model is the d1-3B now, the options go to it in the neutral order, and 245 of 251 judgments answered locally (4 went to the cloud, 2 were refusals). The library's 10 approved crates are in the prior, so its ghost gate can reach below 0.05.
>
> What surprised the night: the prior called 1 of 18 props ghosts, and the cloud's second look agreed on 1 of them.
>
> One question for you: the cloud agreed on every ghost tonight — should the second look also see the props the prior passed, or stay a second look only?
>
> The night,

## 8. What it makes possible

- **A prop can now be dropped with two receipts instead of one.** The
  prior's sharpest instrument — a rank that says *this resembles nothing
  we know* — no longer acts alone: the prop's own mesh is rendered, the
  cloud looks, and the drop lands only when both agree. Tonight they
  agreed on the one ghost they were shown, and the row carries both
  verdicts. When they first disagree, the row will carry that too, and
  the question of who to trust will be a number instead of a feeling.
- **The live view is a wire that runs.** Four nights paid 115–240 minutes
  at an export that never finished; tonight the source landed in
  **85 seconds**, and the mechanism that made the difference is named
  and measured — the material node-tree search, not the triangles. The
  trade (5k-poly objects, placeholder materials) is on the stats file,
  and the way back to real materials is a named problem, not a mystery.
- **The night fits in a night again.** 89.44 minutes wall against v5's
  288.57 — the export was three of those hours. A seam that runs in
  minutes changes what a night can hold: tonight's whole margin (the
  60-minute GPU rail at 21.9 used, the 4-hour wall bar at 1.5 used) is
  headroom the owner can spend on more props, more rounds, or a second
  kind in the library.
- **The letter can be trusted on its numbers.** The morning, the letter,
  the measurements and the test all speak the one ledger count. The unit
  is named (a judgment row, one per attempt, refusals included), the
  counter is one file, and the regression anchor is a real night.
- **The workarounds have now fired in anger.** The wedge restart rowed
  its first real restart (and survived it); the crash it could not
  survive found the loop one restart short of its design, and that is
  fixed with the dead run kept as evidence. A night that dies on a held
  box now leaves a shorter, cleaner corpse: the model-start window waits
  out the box, and no leaked child holds the port for the next seat.

## 9. What was not verified

- **The second look has only ever agreed.** One ghost, one agreement —
  tonight and the desk probe. The disagreement path (the cloud overrules
  the prior, the prop stays) is tested in the unit tests but has never
  fired in a night; until it does, "both verdicts on the row" is a
  promise kept once.
- **The second look's question and model are first drafts.** One fixed
  wording, one VLM (Qwen3-VL-30B-A3B), greedy decoding, three
  orthographic views. No calibration against a labelled set of good and
  degenerate props has been done — the wording was written once and
  agreed with the only ghost it has been shown.
- **The export's placeholder materials are a real loss.** The source.glb
  carries geometry and default materials; anything downstream that needs
  Infinigen's actual surfaces (a viewer that looks right) does not have
  them. The mechanism to attack is named (the node-tree search); whether
  baked textures or a patched search gets them back is not measured.
- **The wedge's cause is still unknown.** Tonight's first launch wedged
  ComfyUI twice in twelve minutes during a neighbour's 40 GB run;
  night-v4's §9 finding stands (the log ends mid-load, no OOM, the
  neighbour is the only name the box can offer). The runner survives the
  shape up to its budget; it still says nothing about the cause.
- **The three-launch story is one night's evidence.** The budget fix and
  the model-start window have each been exercised exactly once (the
  second launch's death), and the third launch never needed either. The
  wedge restart's second restart, and the 900 s window's patience, are
  untested in anger.
- **`courtyard.room` is still excluded** (the engine's "procfunc proxy
  iteration under trace"); the splice measures the same two subjects it
  always has, and the fix belongs to the v2 engine.
- **The morning's `props.attempts` list is empty** — the fold reads a key
  the runner never wrote (`generated` and `meshes` both 0, on v5's
  morning too). `measure.py` reads the job rows instead, which is where
  the doc's prop numbers come from. Pre-existing, cosmetic, and now
  said: a known gap, not a hidden one.
