# night-v5: the third integrated night, with the library in it

**The brief** (`BRIEF.md` on the Thor, 2026-11-01 20:26): follow on from
`docs/lab/night-v4.md`. Find why the box's render server stopped answering,
fix it or work around it and record the cause; run the full night from the
one-command runner with all four seams, under `thor-admit` with honest peaks,
one lease above 30 GB at a time; write the Biographer's letter from the
ledger; and write this document, with the stage table against night-v4.

The owner goal is the one run D had: *a small courtyard with three props — a
weathered crate, a brass lantern, an iron anvil; make it feel lived-in.*

---

## 1. The facts the change stands on

**A group's score has a floor, and the ghost gate needs ten members to reach
it.** A prop's plausibility score is a rank inside the group it most
resembles, and a group of *n* members cannot score below `0.5 / (n + 1)`.
The ghost gate sits at **0.05**, so a group of nine can express a floor of
0.05 and no lower: the gate is unreachable until a group holds **ten**
members. On night-v4's fit the largest group held **7** (38 reference
members in 22 groups), so the gate could not fire on any prop — the prior's
sharpest instrument was silent by construction. Casey's answer (2026-11-01):
*the library may approve ten objects of one kind*. The library is ten
measured crates, and a crate group of ten has a floor of
`0.5 / 11 = 0.0455` — below the gate. The instrument can speak again.

**The library is measured, not drawn.** `build_library.py` rebuilds ten
crates from run F's own crate picture (`crate_s102_00004_.png`) at seeds
9000–9009, through the same TRELLIS.2 template, and repairs and measures
them exactly as the night's executor does: all ten watertight at ~699 k
triangles, repair fidelity ≥ **0.9998** (1,000,000 samples at 128² over
three views), wall **39.1 minutes**, prompt seconds **109.7–382.6**. It was
built once, before the night, and the night only reads it.

**The GPU's *used* bytes discriminate; tegrastats' `lfb` does not.** In run
F's own samples the successful bakes ran at ≤ 56.5 GiB used, and the wedge
sat at **60.49** and **61.06 GiB** used with `lfb 0.00` — the wall. The
bake's own jump was **47.6 → 60.5 GiB in 10 s** — the need. On the box at
20:31 the free-large-block figure read **0.02–0.17 GB** while **86 GB** of
RAM was free and **9.6 GiB** of GPU was in use. `lfb` is a figure about
contiguous blocks, not headroom, and a bar built on it would have stalled
every mesh of the night forever. The bar waits while the box's used GPU
(the per-process sum, the way the daemon counts it) is above
`61.5 − 13.5 = 48 GiB`, and records `lfb` beside every wait as a signal
without letting it gate.

**A ComfyError that says the server refused the connection is a wedged
server, not a busy one.** Run F's mesh stage died on
`the server refused the connection 121 times over 120 s` — a refusal
repeated, not a timeout. The night treats that shape as a wedge: stop
ComfyUI, keep its log beside the run, start it again, re-run the one prompt,
at most two restarts a night, each a `night.comfy_restart` row.

**The decision servers' honest peaks are small.** Measured under the night's
own request shapes (`measure_llama_gpu_under_load.py`): the d1-3B holds
**3.09 GiB** of GPU and **709–731 MB** of RSS, the d1-2B with its projector
**2.39 GiB** and ~910 MB. Six-GB leases cover both with margin, so the
**40 GB** heavy lease is the only lease above 30 GB — and it is held alone.

**The live view's scene export is two hours of CPU on this box.** The scene
is fixed: `room_livingroom_rand` at seed 42 — 200,606 base triangles,
**11,254,482** after subdivision. Generation is cheap (**20.5 s**). The glTF
export is not: Blender's exporter walks the 11 M triangles in Python, on the
CPU, with the modifiers applied. The same scene measured **115 min**
(2026-10-31, `world-stream-scratch/export2`: 11:56:36 → 13:52) and
**136 min** (`export1`: 11:34 → 13:51). The runner's first bound on that
step was **3600 s** — shorter than the work it was given.

---

## 2. Why the old way failed

**Night-v4's run F died in the mesh stage, and the seam it was there to
prove never answered.** The run reached TRELLIS's mesh stage at 18:02 and
died at 18:06:05 with the client's own diagnosis — ComfyUI refused the
connection 121 times over 120 s. Worse, all **eighteen** of the night's
`night.prop_delegate` rows carried the same error:
`FileNotFoundError: 'crate_s102_00004_.png'`. The store records the *name*
ComfyUI gave a picture; the delegate opened that name relative to the
night's working directory, where the picture is not. The delegate was
always right about the picture — it was never given one. That is fixed and
proved on the night's own crate (`docs/lab/night-v4-scripts/
test_delegate_picture.py`: `holes 0.510` fired, `missing_object 0.206`,
`texture_swap 0.057`, 2.17 s).

**The prior's ghost gate could not fire at all.** Largest group 7 against a
floor of 0.05 needs ten. The night's sharpest instrument was silent by
construction, and night-v4's letter asked for the library that would make
it speak.

**A bar on `lfb` would have stalled every mesh.** Near-zero `lfb` is this
box's normal state (44 MB with 86 GB of RAM free). Run F's successful bakes
ran at `lfb` 0.02–1.5 too. The bar had to move onto used bytes.

**And the live view's export could not fit in its own bound.** The runner
bounded a 115-minute export at 3600 s. Worse, `run_cmd` let the
`TimeoutExpired` through, so the bound did not even produce a recorded gap:
at **23:44:15** on 2026-11-01 the exception went out of `main` and the
night wrote no morning, no report and no letter — 78.0 minutes of job wall
and a whole ledger with nothing folded out of them.

---

## 3. What changed

The runner (`docs/lab/night-v5-scripts/run_night.py`) is night-v4's with
four changes, plus two bounds fixed after the first attempt of this night.

1. **The GPU-pool bar** — before every mesh prompt the night waits until the
   box's used GPU leaves room below the measured wall: 61.5 GiB is where
   run F's allocations stalled, 13.5 GiB is the bake's measured need, so the
   bar is 48 GiB used. Bounded at 45 minutes; every real wait is a
   `night.gpu_pool_bar` row with `lfb` recorded beside it.
2. **The wedge restart** — a `ComfyError` that says the server refused the
   connection is a wedge: stop ComfyUI, keep its log, start it again,
   re-run the one prompt, once — at most two restarts a night, each a
   `night.comfy_restart` row.
3. **Honest peaks** — the two decision servers start under 6 GB leases
   (measured: 3.09/2.39 GiB GPU + <1.1 GB RSS), so the 40 GB heavy lease
   is the one lease above 30 GB and it is held alone; the servers run
   `--ctx-size 4096 -ub 1024`, 1.8× faster on the delegate's picture
   questions.
4. **The library** — ten approved crates of one kind go into the prior as a
   labeled group, so the ghost gate can fire on that kind (`night.library`
   row).
5. **The export's bound** (`bec8973`) — `SCENE_EXPORT_TIMEOUT_S = 4 * 3600`,
   about twice the worst measured export, replacing a bound of 3600 s that
   was shorter than the work.
6. **A timeout is a gap, not a dead night** (`aadca19`) — `run_cmd` catches
   `subprocess.TimeoutExpired` and returns returncode 124 with the note in
   stderr, so the stage records what it could not finish and the night
   carries on to its morning. Proved on the box: `run_cmd(['sleep', '30'],
   timeout=3)` returns 124 after 3.0 s.

`launch_night.sh` (new) starts the night and the finisher detached, with
the redirections inside the script — the finisher's first launch on
2026-11-01 died because the redirect was set up before the `cd` took effect.
It refuses to start a second copy of the night.

---

## 4. The pre-run measurements (the four seams, on the box, before the night)

**The decision servers, under the night's own request shapes** (the probe:
`measure_llama_gpu_under_load.py`, raw outputs in `results/`): the night's
own flags hold **3.33 / 2.63 GiB** of GPU, and the shrunk flags
(`--ctx-size 4096 -ub 1024`) hold **3.09 / 2.39 GiB**; the delegate answers
the picture questions in **2.00 s** shrunk against **3.56 s** at the night's
flags. The shrunk flags are adopted, and they are what the 6 GB leases are
sized from.

**The library, built once before the night** (`build_library.py`, 39.1 min):
ten crates from run F's crate picture at seeds 9000–9009, all watertight at
~699 k triangles, repair fidelity ≥ 0.9998, prompt seconds 109.7–382.6.
Its ten members go into the prior as the kind `crate`.

**The box at the night's start** (23:48:39): load1 **14.43**, MemTotal
122.8 GB, MemAvailable **97.3 GB**. Two numbered lease lock files were
swept and none was stale. The night's three leases were all admitted in
**0 s**; after the two decision servers and ComfyUI were up, **89.1 GB**
was free.

---

## 5. The night itself

**How the run went, stage by stage.** The table reads left to right as the
night did: what each seam was asked for, what night-v4's run F got for it,
and what night-v5's run got. The run (23:48:39 → 04:37:13) ended with the
ledger's own verdict — **"ran as planned", reason "nothing failed"** — the
first integrated night to finish since run D. Wave 1 ran 39 jobs in 46.0
minutes of job wall (the dead first attempt had managed 24 jobs in 78
minutes before the export bound killed it).

| stage | night-v4, run F (17:22:39 → 18:06:05) | night-v5 (23:48:39 → 04:37:13) |
|---|---|---|
| the box | load1 5.52, MemAvailable 116.3 GB before; 105.9 GB after | load1 14.43, MemAvailable 97.3 GB before; load1 4.98, 98.1 GB after |
| the leases | three, all `thor-admit`, waited 0.0 / 0.1 / 0.1 s (total 0.2 s) | three, all `thor-admit`, peaks **6G / 6G / 40G** — the heavy lease the only one above 30 GB — waited 0.0 / 0.1 / 0.1 s (total 0.2 s) |
| the decision servers | two llama-servers, the d1-3B on :8295, the d1-2B on :8296 | same, started by the night as its own children under the two 6 GB leases |
| the routed decoy cell | asked on this box: accuracy **0.5208**, decoy-first 0.561, act 59 / escalate 0 / surfaced 181, p50 **0.046 s** | the same numbers on the same probe (0.5208 / 0.561, act 59 / escalate 0 / surfaced 181, p50 0.046 s) — the probe is a fixed replay, and it reproduced |
| the neutral order | the canonical order and the wire's own sorted-by-key order are the same six ids, `neutral: true` | same, checked against the wire's own order (`option_order_neutral: true`) |
| the prior | 38 reference members, 22 groups, largest holding **7** → the ghost gate **cannot fire** | 48 reference members, 2 groups — the library's ten crates the smallest (10), the largest 38 — gate **live** |
| the library | none — the letter asked for ten objects of one kind | ten measured crates, kind `crate`, one `night.library` row, gate live |
| the delegate | 18 calls, **18 failures** (`FileNotFoundError: 'crate_s102_00004_.png'`) — fixed after the run and proved on the crate | 18 calls, **0 failures**, ~1.1 s each; 10 of 18 fired `holes` (a vote about which sibling wins, not a rejection) |
| the GPU-pool bar | not there; run F's wedge killed the night instead | armed, **0 waits** — the box's used GPU stayed at 12–19 GiB all night, far below the 48 GiB bar |
| the wedge restart | not there; the run died on the wedge | armed, **0 restarts** — the mesh stage finished all 18 meshes without a refused connection |
| the heavy phase | never ended — no phase-down row | phased **40G → 8G** at 00:37:13 (wall 0.02 s), 90.7 GB free at the phase, and the night finished the light work under the smaller promise |
| the props | 0 kept, 14 rejected (the run died before a winner was confirmed) | **3 kept** (crate_r1_v3 at 1.00, lantern_r2_v1 at 0.94, anvil_r1_v1 at 0.94), 15 rejected — and the ghost gate **fired for the first time**: lantern_r2_v3, plausibility **0.0385** against the 0.05 gate |
| the live view | not reached | the deltas compiled; the export ran to its own 4 h bound and was killed still mid-walk — `scene.blend` written (145.7 MB), no `source.glb` — the gap recorded, and the night carried on |
| the morning | none — no `morning.json`, no report, no letter | `morning.json`, `report.html/json/txt`, `what-happened.txt`, `letter.md` — all written; the morning's 5 decisions: 1 local (p50 0.356 s), 4 escalated |

**The ghost, on the record.** lantern_r2_v3 is the prop the gate caught:
its occupied volume is **1.004** and its signed volume **1.003** — a solid
block filling its bounding box, not a lantern — and the scripted critic had
scored it **0.939** (only the aspect check off), so every check the night
had before the prior liked it. The prior ranked it **0.0385** inside the
crate group and named it a ghost. That is what night-v4's letter asked for:
an instrument that can say *this resembles nothing we know*, on a night,
with a receipt behind it.

## 6. The measurements, beside the box state

**The night's own numbers**, from the night's own ledger, measured by
`docs/lab/night-v5-scripts/measure.py` and written to
`artifacts/night-v5/measurements.txt` and `measurements.json`:

```
PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
    docs/lab/night-v5-scripts/measure.py \
    --night artifacts/night-v5 --against ~/lm-wt/night-v4/artifacts/night-v4
```

```
status      ran as planned — nothing failed
wall        288.57 min (the goal bar was 4.0 wall-h; the export's 4 h bound is most of the over)
GPU         14.66 min of the 60-minute rail
jobs        39, in 46.0 min of job wall
leases      three thor-admit (peaks 6G / 6G / 40G), waits 0.0 / 0.1 / 0.1 s
phase       40G → 8G when the heavy phase ended (0.02 s, 90.7 GB free)
decisions   251 rows — 245 on the local d1-3B (mean 0.0481 s), 4 on Jev (0.2332 s), 2 unattributed
gates       181 surfaced / 66 act / 2 escalate
morning     5 decisions — 1 local (p50 0.356 s), 4 escalated
props       3 kept (crate_r1_v3 1.00 · lantern_r2_v1 0.94 · anvil_r1_v1 0.94), 15 rejected
ghost       1 of 18 — lantern_r2_v3, plausibility 0.0385 (gate 0.05)
delegate    18 of 18 answered, ~1.1 s each; 10 fired `holes`
box         before load1 14.43 / MemAvailable 97.3 GB; after load1 4.98 / 98.1 GB
```

**The diff against night-v4's run F**, the same script with `--against`
(its label still reads "run D" — a legacy wording from night-v4's own
tables; the artifacts it read are night-v4's run F):

```
  wall minutes           288.57  vs run F — (run F died at 43.4 min)
  GPU-minutes            14.6567  vs 12.2879
  lease wait (s)         0.2  (the same)
  lease kinds            ['thor-admit']  (the same)
  decisions (rows)       251  (the same)
  decisions by rung      {'judge@d1:d1-3B': 245, 'judge@jev:jev-latest': 4, '?': 2}  (the same)
  decisions by gate      {'surfaced': 181, 'act': 66, 'escalate': 2}  (the same)
  props kept             3  vs 0
  props rejected         15  vs 14
  status                 ran as planned / nothing failed  vs — (died in the mesh stage)
```

`artifacts/` is not in git: the ledger, the morning, the report and the
letter are the night's own artifacts and stay on the Thor. This document and
`docs/lab/night-v5-scripts/` are the record.

## 7. The morning's letter

The letter is at `artifacts/night-v5/letter.md`, written by
`docs/lab/night-v5-scripts/write_letter.py`, which **refuses to write over
150 words** and prints the count. It is written from the night's own
`morning.json` — the morning the runner folds out of the ledger — so every
number in it has a receipt behind it. The surprise and the question are
chosen by rule from the night's own measurements, not written in advance:
tonight the rule found ghosts, so the surprise is the gate's first firing
and the question is the decision it leaves open. **104 words.**

> Casey —
>
> The night kept 3 props (crate, lantern, anvil) in 288.57 minutes. The judge's decision model is the d1-3B now, the options go to it in the neutral order, and 1 of 5 decisions answered locally (4 went to the cloud). The library's 10 approved crates are in the prior, so its ghost gate can reach below 0.05.
>
> What surprised the night: the plausibility prior called 1 of 18 props ghosts.
>
> One question for you: what should the night do with a prop the prior calls a ghost — drop it, or send it to the cloud for a second look?
>
> The night,

## 8. What it makes possible

- **The prior's ghost gate spoke, on a night, for the first time.** The
  library gave the crate kind a group of ten, and a group of ten's floor is
  `0.5 / 11 = 0.0455` — under the gate at 0.05. On night-v4 the largest
  group held 7, so the prior's sharpest instrument was silent by
  construction. Tonight it named lantern_r2_v3 a ghost at 0.0385 — a solid
  block the scripted critic had scored 0.939. A prop that resembles nothing
  in its kind can now be named, with a receipt.
- **The delegate answered for the night's own pictures, in a night, for the
  first time.** Night-v4's eighteen calls were eighteen failures on a path;
  the fix was proved on a single crate and never ran inside a night. Tonight
  all eighteen calls answered, ~1.1 s each, and ten fired `holes` — the
  crate's plank gaps and the lantern's openings, read as holes by render
  wordings. The vote is a signal about which sibling wins; it did not reject
  a picture.
- **The lease phased down in anger, and the night still finished.** The
  heavy lease promised 40 GB while ComfyUI and TRELLIS were resident; when
  the heavy phase ended at 00:37:13 the night gave the memory back (the
  phase took 0.02 s, with 90.7 GB free) and promised 8 GB for the light
  work. Night-v4 never got past the heavy phase; tonight the row exists and
  the morning happened under it.
- **A seat can start a night and walk away.** `launch_night.sh` detaches it,
  the finisher waits and measures, a stage that runs out of time leaves a
  recorded gap instead of taking the night down, and a wedged render server
  would be restarted with the one prompt re-run. This night was launched by
  one command, left alone for 4.8 hours on a box whose load touched 71 from
  other seats' work, and wrote its own morning — which is what a night is
  for.
- **The live view is a seam with a measured cost — and tonight's number says
  the bound is still short.** The deltas compiled in seconds; the export ran
  240 minutes at 100% of one core and was killed by its own 4 h bound still
  mid-walk. The cost is now a number a night can be scheduled with, and the
  number says a busy box needs more than 4 hours, or a cheaper export.

## 9. What was not verified

- **Why ComfyUI stops answering in the mesh stage is still not verified.**
  Night-v4's finding stands: the log's last write is in the middle of the
  remesh, the daemon's log has no guard or watchdog event against that pid,
  the journal has no OOM kill, and the only thing the box can name is the
  neighbour — another seat's hog allocating 32 GB at a time in the same
  minutes. Tonight ComfyUI never wedged, so the night added no new evidence
  either way. The runner works around the shape (a refused connection is a
  wedge: stop the server, keep its log, start it again, re-run the one
  prompt, at most twice a night) and says nothing about the cause.
- **The two workarounds have never fired in a night.** The GPU-pool bar
  recorded **0 waits** and the wedge restart **0 restarts** tonight — the
  box's used GPU stayed at 12–19 GiB and ComfyUI never refused a connection.
  Both are exercised by the runner's own tests and the numbers they stand on
  (48 GiB bar, the 121-refusals diagnosis), but neither has been proven in
  anger inside a night. A night where they fire is still ahead.
- **The delegate's questions are still render wordings.** On the prop
  pictures they read a crate's plank gaps as `holes`. The delegate's vote is
  a signal about which sibling wins the picture round, not a rejection, and
  a wording for the single-object domain is still needed before it may
  reject a picture outright.
- **The library is one kind.** Ten crates, so the crate kind's group can
  express a score below the gate; every other kind's group is unchanged, and
  the gate still cannot speak about them. The letter's question is the one
  the firing leaves open: what to do with a ghost.
- **The export's bound is still shorter than the work on a loaded box.**
  115 and 136 minutes were measured on 2026-10-31 on a quieter box; tonight
  the export ran 240 minutes at 100% of one core (the box's load touched 71
  from other seats' work) and was killed by the 14 400 s bound still
  mid-walk, with `scene.blend` written and no `source.glb`. The live-view
  seam has still never produced a glb inside a night; whether a quieter box
  fits in 4 hours, or the export needs a cheaper path, was not measured.
- **`courtyard.room` is still excluded.** The engine refuses to trace it
  ("procfunc proxy iteration under trace") and the splice measures
  `courtyard.crates` and `courtyard.weathering` instead, recording the
  exclusion. That is the same exclusion night-v4 recorded; the fix belongs
  to the v2 engine, not to the night.
- **The first attempt of this night is kept, not folded in.** It died on the
  export bound (`artifacts/night-v5-cut-2344`); its ledger is whole and its
  morning does not exist. Its numbers are not in the tables above, which are
  the re-run's.


