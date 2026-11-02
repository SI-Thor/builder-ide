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
three changes, plus the scripts that carry them:

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
