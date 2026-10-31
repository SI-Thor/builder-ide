# PLAN — builder-ide: the plan for the best user experience

Written 2026-10-31, **draft 2**. This is the plan Casey reads. It is a
synthesis, not a new invention: every claim below cites the document it came
from, and where the documents disagree, this plan chooses and says why. The
plan is organised the way the product is lived: **the experience first, then
the milestones and the weeks that deliver it** (BRIEF.md; rnd-plan.md round 3).

**Citation key.** **V** = `docs/vision.md` · **C** = `CLAUDE.md` · **S** =
`docs/design/core-spec.md` · **U** = `docs/understanding.md` · **I** =
`INTEGRATION.md` · **X** = `docs/research/rev-ux.md` (its items are C1–C13
contradictions, G1–G10 gaps, R1–R20 reality checks, S1–S15 spine moments,
D1–D6 owner decisions) · **G** = `docs/research/gaps.md` · **RS** =
`docs/research/rev-spec.md` (patch list P1–P20) · **P** =
`docs/research/split.md` · **RT** = `docs/research/rev-tech.md` (contradictions
C1–C9, risks R1–R16, spike order §5) · **B** = `docs/research/bakeoff.md` ·
**D** = `docs/research/ux-day.md` · **T** = `docs/research/ux-trust.md` ·
**3D** = `docs/research/res-3d.md` · **R** = `docs/research/res-cad.md` ·
**SP** = `docs/research/spike-phase1.md` (phase 1 on the Thor) · **E** =
`docs/research/ig2-procfunc.md` (the engine decision) · **F** =
`docs/research/forks.md` · **MQ** = `docs/research/maquette.md` · **CE** =
`docs/research/cogeco.md` · **LC** = `docs/research/landscape.md` · **SC** =
`docs/research/solidcraft.md` · **LAB** = `docs/lab/` (the experiments and
`IDEAS.md`).

**Three worktrees, still running, measured but not yet reported.** Their
numbers are in this plan because they were taken on the box with its state
beside them, but their written reports are still to land: **L3** =
`~/lm-wt/lab3/` (lab round 3: `exp1_engines`, `exp2_batched`,
`exp4_equilibrium`, `exp5a_cudagraphs`; `exp3_lora` **failed** — a
`peft` attribute error, and it stays failed) · **WS** =
`~/lm-wt/warm-scene/` (the warm scene server: `results/bench-trial.json`,
`bench-hr-trial.json`, `durability.json`, `memgrowth-fixed.json`) · **TR** =
`~/lm-wt/trellis/` (TRELLIS.2 on the Thor; `README.md` and `results/`).

**Timing convention** (G §intro, from X §4 and 3D §8): `[b]` marks a latency
**budget** — the UI must meet it and a test can check it. `[e]` marks an
**estimate that did not come off this box** and is therefore not a promise.
`[M]` marks a **measurement** taken on this box; the box's state sits beside
it. A number that is not `[M]` and not a budget is a placeholder and says so.

---

## What changed since draft 1 (changelog)

Draft 1 (2026-10-30) was written when the engine was a hope and the core was
a spec. One day later the box has answered most of the plan's open questions,
and the plan moves as follows.

| # | Change | Why |
|---|---|---|
| 1 | **M0 is done.** The plan's largest single uncertainty — "does Infinigen run on the Thor at all?" — is answered: **yes**, and the numbers are in §2 M0. | The bpy 4.2 wheel was built from source on the Thor, Hello Room and Hello World both render, and Cycles on the GPU is **7.1× the CPU** (SP §1–5). Draft 1 called this "the plan's largest single uncertainty"; it is no longer one. |
| 2 | **M1 is re-scoped to the real state.** The core is no longer "to be built" — it is **integrated on `main` with 831 tests green** (I). The M1 session (30 steps) and the melt week (105 steps) both play end to end, and are now being rewired onto the real core instead of stand-ins. M1's remaining work is the **stub/real tally and the engine rung**, not the skeleton. | I §"Final state"; the acceptance READMEs' own stub lists. The work moved down the list, not up. |
| 3 | **The engine decision is woven in.** The plan now builds on **Infinigen 2.0 + procfunc**, with our **Warp terrain as a v2-native stage** (E). Draft 1 assumed a 1.x port with rewrites around it; the study says 2.0's architecture *is* the warm-scene, stage-cache and recipe shape we designed, and that our fork is already on 2.0. | E §3 (options A/B/C, the comparison table, and the four falsifiers). |
| 4 | **The confirming experiment is a gate, not a hope.** `~/lm-wt/v2-thor` is running E's experiment. **Step 1 has already passed**: a v2 `room_livingroom_rand` + `render_cycles` on the Thor, 435 s wall, GPU 98 % util, 78.5 W peak, 3.5 GB peak RSS, PNG out. Steps 2–5 (graph stability, single-node edit, warm second scene, denoiser/numpy) are still to land. | E §"The first experiment that would confirm it"; the run's own `logs/s1-render-seed0.summary`. |
| 5 | **The iterator principle is now in the night.** V's "The Thor is an iterator" is a budget, not a slogan: the night's rails are spent in **iterations per goal**, and the quality gained per iteration **and per joule** decides how deep a loop goes. Lab round 3 measured the pieces (warm start saves 1.43–1.55× the iterations; batching 64 agents costs about what 1 does; joules per fixed point ≈ 2.33 J). | V §"The Thor is an iterator"; L3 `exp4_equilibrium`, `exp2_batched`, `exp5a_cudagraphs`. |
| 6 | **The lab results moved into the rewrite ladder.** Draft 1's ladder said "the rewrite is not theoretical". Now it is measured, rung by rung: the Warp terrain port is **bit-identical and 44–56×** the CPU path; FP8 is **1.6–1.7×** and halves resident weights; **FP4 is a measured no**; unified memory is **zero-copy**; the solver's GPU win exists but only after the algorithm is restructured. | LAB `exp-warp-terrain-port`, `exp-fp8-tensorcores`, `exp-unified-memory`, `exp-solver-scoring`. |
| 7 | **New first three weeks, from today.** §3 now runs Nov 1 – Nov 21, 2026, and its items are the real ones: finish the m1-real rewire, land the v2 gate, put a real render behind the render rung, and turn the measured engine numbers into the night's budget. | Draft 1's weeks 1–3 assumed the bpy wheel was still building. It is not. |
| 8 | **The measures are mostly real numbers now.** Of the six "spike-dependent facts" U §3.3 listed as unknown, **three are now measured** (Cycles GPU throughput, the stage timings, and whether bpy lands at all), a fourth is **deleted by the engine decision** (the headless-EGL risk, because v2's ground truth is Cycles-based), and the last two are partly measured — peak RSS per warm scene, and sustained power under a full night's load. | SP; E §3 comparison table; the lab files; WS and TR results. |
| 9 | **§4 is now a separate, condensed sheet.** The eighteen draft-1 decisions became `docs/decisions-for-casey.md`: **twelve open items** — the "just say yes" ones separated from the real choices, each with what happens if he doesn't decide — plus the ten draft-1 decisions that are now closed, listed so none is silently dropped. | BRIEF §2. |
| 10 | **Two facts changed the plan's shape.** The external cold shelf is **offline** — a D-state wedge that needs a physical replug and an ext4 reformat, and it becomes a decision of its own (B7). And the plan's "no GPU-acceleration nugget anywhere" is now confirmed as a *fact*, not a search result: four of our biggest ideas are unclaimed, so they are ours to write. | LAB `exp-nvme-bandwidth` §5; F §0. |

---

## 1. The experience we are building

One paragraph, before the table. Casey and Magnus are building a world
(**Fjellvik**) with a crew of builders that work while they sleep. The promise
of the product is a loop, not a feature: **plan together in the evening, let
the crew bet sealed predictions overnight, wake to an honest report and a
cheap decision** (V; D §1–3). Everything the person lives through belongs to
one of three clocks, and the deepest rule in the whole plan is honesty about
what is measured: no line the builders speak without a denominator (T §"The
'I think you'll like this' utterance"), no card without an artifact (D §2), no
speed number that did not come off this box (X §4, 3D §8), no silent model
swap (T §"Research transfer"), no fake progress ever (D §2 02:07).

The spine below merges rev-ux's fifteen moments (X §5) with the gap designs
(G §§1–4). Screens are D's six: *in-world view* (the ProArt client, [later]),
*plan slate*, *night feed*, *morning report*, *work-order board*, *asset
library* — plus the *kid panel*, which is the most accessible surface in the
product (G §4.2). "Honest version" states what ships when the technology
cannot yet keep the promise. **Bold** marks a cell that changed since draft 1
because a fact landed.

| # | Moment | Clock · budget | Screen | The honest version |
|---|---|---|---|---|
| 1 | **Cold open — night one, empty ledger.** "First night. I have nothing on you — 0 of 0. Four ways to start; pick one and I'll learn from what you keep." Four seed chips, each with its seed on its face. | Talk · ≤ 2 s from open `[b]` | Plan slate (empty) | Holds now as text. No world streams in — there is no stream promise to break (X R1); the first render is also the box's first measurement (G §1 19:58–20:04). **The opener is computed from the real ledger today** (core-cold-start, merged into `main`; I). |
| 2 | **The recognized return** (from night 3 on). "The north jetty stayed; the spiral stairs went. That's 1 of 2 on the line I read as straight and weathered — two more like that and I'll call it taste." Recognition with a count, never longing or absence-duration. | Talk · ≤ 2 s from app open `[b]` | In-world view [later]; a panel line [now] | The **line** holds always — it is a ledger read, instant by construction. The world behind it loads unnamed until a stream time is measured (X S2, R1). |
| 3 | **Cold-start questions.** "Deep joints, or flush?" — two crops side by side; one tap writes a taste note. ≤ 6 in the first session, strictly one at a time, any question skippable (a skip writes nothing). | Talk · ≤ 1.5 s per answer `[b]` | Plan slate / report | Cold start *is* taste acquisition, not a special case (X G1; G §1 20:12). **The gate and the ask-mode policy are built and tested** (core-cold-start; the melt week measures the 6 → 0 decay from the ledger alone). |
| 4 | **Point-and-say chips (Casey).** A spoken intention becomes an editable chip where he pointed. Ambiguity is asked about, never guessed: "The slope, or the whole east shore?" | Talk · ≤ 1.5 s per chip `[b]` | In-world [later]; map+click [now] | The never-guess rule is code, not prompt (S §3.1.2). Chips are first-class records before any night exists (RS P11). |
| 5 | **Magnus taps.** Chips only — no mic, no free text, no keyboard — each with a Magnus badge and an `author: magnus` row. "Tower. Big or small?" — two chips over two silhouettes. | Talk · ≤ 1.5 s per chip `[b]` | Kid panel | Structured data from the first second: no free text to leak, because there is no free text (X C7/D4; T §"Magnus at the controls"). |
| 6 | **The plan slate.** One screen: intentions with owner, predicted cost, the builder's one-line take; one budget bar with counters underneath; **work-order time as its own line**; every estimate marked `[e]` until measured. | Workshop · transaction ≤ 30 s, no cancel (the night has not started; before the night a slow decision is free) | Plan slate | One bar for the owner ("8 h wall · 2.0 h lane `[e]` · $0.00 hosted (local)"), four counters for the scheduler (X C9; G §1 20:31). |
| 7 | **The limit, said aloud.** The Architect: "Swing isn't in my hands yet — 0 built. Creaky loose planks: yes." A capability row on her face, so the claim is a record, not decoration. | Talk · ≤ 2 s | Plan slate / work-order board | Capability rows cite vocabulary use counts (X C12; RS P18). |
| 8 | **The one-line work order.** "Computer, I want rope bridges that swing." → compile with progress and cancel ≤ 20 s `[b]` → a **question XOR a confirm**: "CONFIRM: rope bridge, south span, hempen, 8 planks; passes the analytic load check at 2×; build/verify ~40 min `[e]`, generate/test ~1.5 h `[e]`; reversible at ver_0192. Go?" | Workshop ≤ 20 s → Talk · confirm readable ≤ 5 s `[b]` | Work-order board | Two prices, never one (X R16); acceptance is a scripted analytic computation, not "the sim" — no physics engine exists (X R11; RS P5). **The node registry that lets an ambiguous order resolve to a question now exists in the merged recipe store** (I §1). |
| 9 | **The pre-flight.** Ten seconds after "Start the night": "PREFLIGHT: lane free · queue 2 items · client detach: on close or 22:00 timeout, whichever first." If the lane is busy it proposes (start late / start degraded / cancel); it never decides. | Watch · ≤ 10 s | Plan slate | The timeout is the fix for the client that never detaches (X R19; RS P10). **Built and covered by the four-mornings suite** (core-night-runner). |
| 10 | **The handoff.** "Two small bets tonight. Both sealed as guesses — zero priors. Morning: what we kept, what we guessed, and this box's first real numbers." The night is silent by construction. | Workshop · ≤ 30 s | Plan slate → night feed | Sealed guesses are legal on night one — the gate forbids pretending to a view, not betting (G §1 20:44). |
| 11 | **The sealed bet (no screen — the ledger).** edit → predict → **seal** (hashed, committed before the render job exists) → preview → checks → keep or revert. Recipe diffs are hundreds of bytes. **And now: edit → *N variants* → score → keep the best → refine from it → up to K rounds.** | Night; the feed is the only user-visible surface | (ledger; night feed cards) | Previews are priced as batched lane-minutes `[e]`, never "38 seconds" (X R3); automated verdicts read `verdict@scripted` until a critic is chosen and calibrated (X R4/S6; G §1). **The iteration seams (variant source, critic, power meter, depth policy) are built and shipped in `core.night.iterate`** (core-night-runner). |
| 12 | **The 2 a.m. peek.** Join cold, understand who did what, kept or reverted; rewind free; **never fast-forward of live work**; one stop button, always visible. | Watch · join ≤ 5 s; card legible ≤ 5 s; stop ≤ 2 s `[b]` | Night feed | The feed is the log, not a stream — kill -9 the server and it re-renders from the ledger alone (D §2 02:07; S §5.4). **The kill -9 test passes against the real ledger** (M1 session, 30/30). |
| 13 | **The morning report opens — before the world.** First the status line (`ran as planned / ran short / ran degraded / did not run` + one-line reason), then the failures, then the numbers **with the cut named**, then the filmstrip, branches, parked questions, landed work orders, per-claim-type tallies with denominators. No single "prediction score" — it is theatre (X C2). **And: the winner *and what it beat*.** | Watch · first paint ≤ 3 s; digestible ≤ 2 min `[b]` | Morning report | A static page over the ledger: fast forever. Dark ≠ asleep ≠ busy, stated in words under the picture (G §2; X G2/G5). **Measured: the whole fold + HTML + text build is 0.2 ms against a 3 s budget; the status line alone is 0.052 ms** (LAB `morning-report-clock`). |
| 14 | **The branch flip and apply.** A/B/C pre-rendered overnight, plus the two standing exits present from night one: **keep yesterday** and **back to the plan**. Magnus points at C: "that one" — it becomes a proposal; Casey confirms (a branch is a recipe pointer, a real edit). | Watch · flip ≤ 2 s → Workshop · apply ≤ 10 s; re-stream ≤ 15 s `[unmeasured: M5 spike]` | Morning report → in-world [later] | Flip/apply are pointer moves, always fast (S §1.2). **Measured: flip 0.69 ms, apply 0.94 ms, both fsynced** (LAB `core-recipe-branch-flip`). The re-stream number is measurement-gated and each option's scene manifest is pre-baked by the night (X S11; RS P14). |
| 15 | **The parked question — or the assumption that replaced it.** One tap to answer; a taken assumption sits on the same card. Top three shown, the rest counted ("31 more, none blocking"); at most 3 blocking questions may exist — the fourth parks the *task*. | Talk · ≤ 2 s `[b]` | Morning report | Both are ledger reads; the dam is at night, not at breakfast (X S12; G §4.5). |
| 16 | **Magnus's morning.** "You asked for a tower. It is by the water. Casey kept the north jetty." Presence-continuity is his trust; no scores, no percentages — counts out of five only when asked. | Talk · ≤ 2 s | Kid panel | His first three keeps are `pending_ratification` and invisible to the builders' gates until Casey answers one question: "Does he know what *keep* means?" (G §3). |
| 17 | **"Why?" in one tap.** Prompt, seed, model id, weights revision, licence **including dependency terms**, sampler, environment revision, critic note, who decided. | Talk · ≤ 1 s `[b]` | Anywhere | **Holds fully — the best-supported promise in the corpus** (X R8), because the technology requires exactly this record. "Regenerate" with a different model is labelled **"reinterpreted"** (X R9). |
| 18 | **The growth beat.** "I can do rope now. North span too?" — the new capability announced in one sentence at the moment it becomes useful. Model changes are announced too, in character, at the next report. | Talk · ≤ 2 s | In-world [later] / report [now] | Promotion is one core transaction (S §2.3); the notice rule costs nothing and prevents the Replika-shaped betrayal (T §"Research transfer"). |
| 19 | **The ledger line that reaches the artifact.** Not a dashboard: "Architect had 14 of 18 right on shadow counts; this one is in that run. Its last miss was a double pier, three weeks ago." | Talk · ≤ 1 s | Report / asset library | One tally-read API away (RS P20). |
| 20 | **The three-number morning line.** "5.3 h of your Thor · $0.00 hosted (local) · 2 h of your attention." A morning may ask for **≤ 10 decisions**; a night that would need more is cut at the queue, and the report says where. **And, when the box's rails are spent: joules, and how many iterations bought them.** | — (report footer) | Morning report | The attention number is the one nobody measures and the one that decides whether the owner comes back (X G6; G §4.3). **The joules line is now measurable from two agreeing sources** (L3 `exp1_engines`: tegrastats and the INA current sensors agree within 2 %). |
| 21 | **Sharing a night.** "Share this night" builds a recipe + provenance bundle: licence manifest on the first page, thumbnails, author-scoped rows excluded by default, labelled **"recipe — re-render may differ."** | Watch · bundle build ≤ 30 s `[e]` | Morning report | The recipe is kilobytes; the pictures are not — and the label says which is which (X G3/R15; G §4.1). |
| 22 | **The world in the room** `[later]`. Arrival beats, ghost work-order previews against the *current* commit, point-and-say chips in-world, voice (unevaluated — no TTS was researched; X R14). One rule: **the client is a viewer of a named commit, never a holder of state.** | Watch/Workshop (budgets above) | In-world view | The ghost/LOD glTF export makes the ProArt the renderer (P §2.3-4, move #3); the Thor's GPU stays for models and previews. Live video streaming is **not** this moment — see §5. **The LOD bake that makes this moment exists already, written and measured, in someone else's fork** (MQ §2; F §7 item 6). |

**Reading of the spine.** The evening (1–10) is where every human decision
happens and is nearly free of GPU cost. The night (11–12) is machine time and
legibility. The morning (13–20) is pure UI over cached artifacts and therefore
fast forever. The loop closes (18–19) with the ledger, the only thing that
grows. If only three moments can be made great first, they are **12 (the
peek), 13 (the report), 14 (the branch flip)** — A's own pick (D §4) built
with B's rules inside (X §5 closing).

---

## 2. Milestones that each deliver a lived experience

Each milestone is something Casey (and Magnus) can *live through*, not a
component. Every one of them runs on the `[now]` surfaces (panels over the
ledger) except M5, which is the `[later]` half. Acceptance is a session script:
if the session cannot be played end to end, the milestone is not done.

### M0 — "The box tells the truth" ✅ **DONE** (2026-10-31)

- **Lived:** Casey opens one page and sees his own machine's first honest
  numbers: Hello Room and Hello World rendered on the Thor, CPU vs GPU timed,
  the patches tracked, the spike report written with the box's state beside
  every number (B WO-1; C §Status; `infinigen-thor`'s `thor/SPIKE.md`, and
  SP here).
- **What landed** (SP; branch `thor-spike`, commits unpushed): Blender 4.2's
  `bpy` module **built from source for aarch64** — no prebuilt wheel exists
  for Linux ARM64 at any version — in ~70 wall-clock minutes and 5 small
  patches. Hello Room: coarse **534 s**, GPU render **1 307 s** at 8 192 spp /
  1280×720 with 15 ground-truth passes, GPU 98 % util, ≤ 56 GB system RAM.
  Hello World: coarse **214 s**, populate + fine terrain **57 s**, GPU render
  **48 s** — about **5.5 min** total against a desktop's ~10 min.
  Cycles, same frame, 256 spp, 1280×720: **CPU 450.1 s → GPU 63.4 s = 7.1×**,
  with PNG byte-size within 0.001 % (the same converged image).
- **The finding that reshapes the plan:** generation is **not CPU-bound** —
  the coarse stage runs at ~225 % CPU, about 2 of the 14 cores. The box has
  12 idle cores while the GPU renders, so the day/night split is a real
  property of the machine, not a slogan (SP §"Phase 2 recommendation").
- **Acceptance, met:** `bpy` imports; the Cycles kernels show **sm_110**;
  both scenes complete; two PNGs (CPU, GPU) with timings and the power mode
  beside them; `run-timed.sh` prints
  `gpuMem=unavailable(unified-memory)`, never a false zero (B WO-4; RT C9b).
- **What M0 did not answer, and where it went:**
  - *No aarch64 OptiX, ever* — Cycles on the Thor is CUDA-only. It is plenty
    (7.1× over 14 cores), so the ceiling is now known, not feared.
  - *The external cold shelf died.* The 1.9 TB NTFS/fuseblk drive D-stated
    a run for 30+ min and is still offline pending a physical replug; every
    runtime artefact moved to NVMe. It is also a **repeat-offender failure
    mode**, so the plan now asks for it to be re-formatted ext4 and used
    strictly as a cold shelf (LAB `exp-nvme-bandwidth` §5).
  - *`nvidia-smi` cannot report memory on this box* (`[N/A]`), so residency
    accounting comes from `/proc/meminfo` + `tegrastats` — a rule, now
    written into the scheduler's design.

### M1 — "One evening, one night, one morning, one builder, one room" (weeks 1–3, re-scoped)

- **Lived:** the crate night, in its cold-start form (S §6.1 + G §1). Casey
  creates a project, gets the zero-denominator opener and four seeds, answers
  ≤ 6 two-chip questions, puts two small bets on a slate with a budget bar,
  says "Go" to one honest work order (crates gain lids and rope handles), goes
  to bed. In the morning: status line, failures first, the numbers with the
  cut, two branches plus keep-yesterday and back-to-the-plan, one landed work
  order with a preview and evidence, "why?" in one tap, and the tally saying
  *"2 sealed · 1 hit · 1 miss — not taste yet; that is a start."* **And: the
  night tried several ways and kept the best, and the morning says which it
  beat.**
- **What is real now** (I; the acceptance suites' own READMEs): the core is
  **integrated on `main` — 831 tests, one green suite**, seven seats merged
  (core-api, core-recipe, vocab, why-kernel, night-runner, cold-start,
  usd-backbone), every stand-in replaced. The M1 session plays **30/30
  steps** and the melt week **105/105**, and both are being **rewired onto
  the integrated core** on branch `m1-real` (the spine's own ledger and
  recipe store, no sibling-branch materialisation). The overnight **status
  line** is computed from heartbeats, not narrated; the **iterator loop**
  (variants → critic → keep best → refine, with a depth policy inside the
  rails) ships as `core.night.iterate`.
- **What M1 still owes, exactly** (the stub/real tally, item by item):
  1. **The render rung.** Still a deterministic stub. It now has a real
     engine to point at: the Thor runs Infinigen (SP), and v2 renders on the
     Thor (E's confirming experiment, step 1 passed). The rung needs an
     **engine adapter** with the recipe on one side and the render on the
     other — so a recipe written today survives the v1 → v2 change underneath
     it (E §"What would make this recommendation wrong", first falsifier).
  2. **The scripted critic.** `verdict@scripted` on its face until a vision
     critic is chosen from calibration numbers (X R4/S6; RS P15). The
     reference set's first members run nightly, sized to the unused lane.
  3. **The engineer seat.** A stub behind the merge gate. The bake-off is
     designed but **unrun** — no contender has executed a work order yet
     (U §2.6). Until it runs, the "cost per accepted hard order" number
     behind the hosted-engineer decision does not exist.
  4. **The USD backbone.** Written and merged (recipe → layered USD,
     build123d → STEP → GLB, byte-identical re-emission), but **not
     materialized** in the M1 run: it needs the `usd-core` / `build123d`
     wheels, and M1's render rungs are the stub by design. It plugs in at
     the same seam.
  5. **The taste model.** Still a concept (U §3.3). M1 needs the first real
     taste rows, not a model.
- **Acceptance script (session), unchanged in shape but harder in fact:** on
  a fresh project it must pass S §6.1's slice gates — (a) the kill -9 test:
  kill the feed server mid-night, reopen, the feed renders from the ledger
  alone; (b) the two-referent test: an order with two plausible referents
  returns a question, never a plan; (c) a sealed prediction exists with
  `sealed_at` strictly before its render job's enqueue; (d) the report
  renders with zero panel-side state; plus the cold open test (first line has
  a zero-denominator, no adjective about the owner, one offer of four seeds)
  and the question budget (≤ 6, strictly sequential, every row with a reason
  code and an artifact ref) (G §7 tests 1–4) — **and now (e) the render rung
  produces a real image with a real artifact hash, and (f) the night ran the
  iteration loop at least once, so the report can name the winner and what it
  beat.**
- **Risks / what changes:** the bpy risk is **dead** — the wheel is built.
  The live risks are (i) the **v1 → v2 engine change underneath the
  recipes**: mitigated by putting our own recipe schema *above* the engine,
  so an upstream change is one adapter, not every recipe (E's first
  falsifier); (ii) **render cost**: a Hello Room coarse is 534 s, so a night
  that re-solves a room per task is not affordable — the stage cache is not a
  M3 nicety, it is what makes M1's night fit the rails; (iii) **the cold
  shelf is offline**, so everything runs on NVMe (343 GB free) until it is
  replugged and re-formatted.

### M2 — "The honest week" (weeks 2–4)

- **Lived:** seven nights against the real owner or a simulated one. The
  cold-start rules melt mechanically — questions 6 → 0, `confidence: guess`
  → real claims per reason code as denominators pass two, capability rows stop
  reading 0, and by evening seven the Companion earns the corrected return
  line of spine moment 2 (G §1.9). Every one of the four mornings is
  survivable: a power cut, a foreign job on the GPU all night, a client that
  never detached, and no plan at all each produce the correct status line and
  a one-tap plan recovery. The morning report carries "The box" section — the
  machine's own growth beat — where the night's `[e]` estimates are replaced
  by measurements.
- **Acceptance script:** the four-mornings suite (G §7 test 6: power cut /
  foreign job / never-detached / no plan → correct status line, one-tap
  recovery, zero fabricated work); the melt test (seven simulated nights →
  questions → 0 and guesses → gone per-code exactly as denominators pass two);
  the gate test (no rendered line ever claims below two observations); honest
  estimates (every confirm shows both price lines; every `[e]` on the slate is
  a marked field the morning replaces); decision budget (a night that would
  ask > 10 decisions is cut at the queue and the report says where). **The
  melt week already plays 105/105 against a simulated owner; M2 is the same
  seven nights with a real engine behind the render rung.**
- **Technical work:** pre-flight + heartbeat + computed status line (G §2) —
  built; capability rows (X C12); the calibration batch — a fixed reference
  set of ~30 renders with seeded defects through scripted checks, publishing
  false-positive/false-negative rates (X S6; RS P15); watertightness before
  the critic (RS P7); graduated throttling + kill switch at full strength and
  the **per-model load cap** enforced at batch admission (S §5.5; RS P3);
  actor-scoped chips and Magnus-safe endpoints (RS P8); taste export/erase
  via tombstone events (RS P9); the share bundle (G §4.1); the tally read API
  (RS P20). Engine side: the port graduates from Hello Room to a seeded room
  variant good enough to be "one room" — **with per-stage timings now known
  to be real numbers** (coarse 534 s, render 1 307 s at 8 192 spp).
- **Risks / what changes:** if the calibration batch shows the scripted checks
  cannot catch seeded defects, critic selection is pulled forward and becomes
  the milestone's blocker (X R4). If stage timings show the solver is worse
  than the x86 paper's ~38 min on ARM, room-scoped re-solving moves from
  "nice" to "the only way the Architect ever works at day" — **but note the
  measured Thor coarse stage (534 s) matches the desktop's ~8 min
  expectation, so this risk is smaller than draft 1 feared; the number to
  watch is the *solver inside* the coarse stage, which SP did not isolate.**

### M3 — "The crew, and the vocabulary that grows" (weeks 4–7)

- **Lived:** the full crew — Architect, Landscaper, Prop-maker, Critic,
  Companion — works a night on one room and its slope. The evening includes
  the limit beat ("real rope isn't in my hands yet") and a real WO-14-style
  order that lands in the morning as a preview with evidence; keep promotes
  `bridge.rope` and the Architect says "I can do rope now." The morning has a
  filmstrip of cached renders, three pre-rendered branches that flip in ≤ 2 s,
  per-claim-type tallies with denominators, and model-change notices. Generated
  props (TRELLIS.2, batched) sit in the room with provenance and licences.
- **Acceptance script:** run the ux-day evening→night→morning arc of D §1–3
  end to end on the Thor with the merged rules from X (failures-first report,
  no single score, the cut named, interruptions vs narrations split); every
  automated keep is a `verdict` write and every taste row an owner write (X
  C5); the promotion transaction flips the word `coming-soon → active` with
  provenance and the character is notified (S §2.3); evidence opens ≤ 1 s.
- **Technical work:** the rest of the crew + full vocabulary (S §6.2.4);
  taste-ledger surfaces (S §6.2.5); adapter hardening + hosted engineers
  (`claude-code`) behind the same seam with a hard cents cap (S §6.2.1);
  scheduler tiers with provenance stamping and the CPU lane (S §6.2.2);
  the recipe → USD/glTF compiler with deterministic emission (S §6.2.3; R §8);
  **the warm scene server** (P §6 move #1; RS P4) and the **recipe-hash stage
  cache + partial regeneration with the dirty-set contract and pinned engine
  config** (P §6 move #2; RS P13); generative stations: TRELLIS.2 via
  ComfyUI native + TripoSR baseline behind a thin HTTP service of modly's
  shape (RT C3's composition; RT spike 4; RS P12), textures via TRELLIS.2's
  shape-conditioned texturing plus StableMaterials/SDXL, and ambience via
  ACE-Step (RT spike 5 — Apache-2.0 and OpenRAIL, both licence-verified);
  critic selection gated on the M2 calibration numbers. **Plus the fork
  harvest**: the four pipeline files that are a working prototype of the
  builders layer, and the LOD bake that is the day-view wire (MQ §3; F §7).
- **Risks / what changes:** TRELLIS.2's on-box throughput is **measured now**
  — 512³ in **101 s** and 1024³ in **194 s** wall, peak RAM 55 GB and 68 GB
  of the 122 GB pool, GPU rail 74 W and 79 W — so props-per-night is a
  calculation, not an estimate; if the memory dip threatens residency, props
  become library-first with generation as the exception (3D §4.1). The
  engine's alpha churn is the standing risk (E's first falsifier), mitigated
  by our own schema above the engine. The engineer seat may change: if
  Claude Code's measured median cost per accepted hard order exceeds ~$2 or
  its budget cap leaks, Seat A moves to OpenCode (B §4.2).

### M4 — "Magnus's Sunday" (weeks 5–8, can start earlier — it is [now]-shaped)

- **Lived:** Magnus's first session is a **five-chip guided world**: tap one
  of five nouns ("Tap one. It gets built tonight."), see the chip land with
  his badge ≤ 1.5 s, hear the limit said to a kid ("Swing isn't in
  my hands yet — 0 built. Creaky planks: yes."), pick "ask the Computer" and
  see "waiting for Casey." His lane is reserved and capped ("1 item · ends
  21:30 · inside the birch batch"). His morning is one sentence: "You asked
  for a tower. It is by the water." His preview survives seven nights
  verbatim. Casey is asked exactly once whether he understands what keep
  means.
- **Acceptance script:** kid first contact (fresh kid profile → ≤ 6 tappables,
  no reachable text input, tap → card ≤ 1.5 s, one action deletes every
  `author: magnus` row); ratification (his pre-ratification rows appear in no
  prompt any builder reads); lane discipline (his unfinished item parks with a
  kid-readable card and never rolls into Casey's night) (G §7 tests 11–12).
- **Technical work:** the kid panel (chip grid + counts), two-queues-one-lane
  scheduling with the reserved slice inside the warm batches (X G10; G §4.7),
  actor-scoped apply-as-proposal (RS P8), ratification gate, presence without
  surveillance (lane counts, never contents).
- **Risks / what changes:** almost none technically — this is the
  lowest-risk milestone in the plan and the one that most shapes what the
  product *is*. If Casey wants Magnus earlier, it slots after M1 with a
  five-chip panel over the same queue.

### M5 — "The world in the room" `[later]` (weeks 8+, gated on measurements)

- **Lived:** the spine's [later] half: the ProArt renders the live LOD world;
  point-and-say chips land where he pointed; the computer's work order lands
  as ghost scaffolding against the current commit; branch flips happen
  in-world; the morning filmstrip plays as pre-encoded clips.
- **Acceptance script:** initial world-load ≤ 8 s warm and re-stream ≤ 15 s —
  both **measurement-gated**, promoted from `[unmeasured]` only by the LOD
  spike (X R1; RS P14); per-edit deltas ≈ KB over the wire (P §2.3-4); the
  client shows a named commit and says "12 commits behind — re-attach" when
  the night moved (G §4.6).
- **Technical work:** the ghost/LOD glTF exporter (P §6 move #3) with
  `since_version` deltas (RS P14) — **the pipeline is already written in the
  maquette fork (`dedup → instance → simplify → quantize → draco` plus a
  `scene_lod.json` manifest), BSD-3, so M5 is port-and-measure, not
  build-from-nothing** (MQ §2.2; F §7 item 6); the 5 GbE RJ45 + NVENC clip
  channel (P §6 move #4); the thin client itself; voice only after a TTS is
  actually evaluated (X R14).
- **Risks / what changes:** if initial-scene export or the 4050's rendering
  cannot hold the clocks, the day half stays on panels and the world stays a
  morning-and-peek experience — the loop of M1–M4 is complete without it.

### The rewrite ladder — where porting stops and Thor-native begins

Casey's standing instruction: everything here is open source, so the plan may
heavily rewrite Infinigen, Blender stages and generators for this specific
chip — unified memory, the Blackwell GPU, the hardware engines, the 14
Neoverse cores — not just port them (CLAUDE.md; BRIEF addendum; V
§"The pieces" #1). Draft 1 said this "is not theoretical". **It is now
measured, and the ladder below is rewritten with the numbers.** Every rung
keeps the recipe as the source of truth — a rewrite that changed what a recipe
means would break the one guarantee the whole experience stands on (R §8;
S §7.11).

The build rule every rewrite inherits is unchanged: `-arch=native` +
`cuobjdump --list-elf` before trusting any produced `.so` (RT C6/R1) —
though note the spike's own terrain build **passes** the check, with native
sm_110 SASS and no PTX (LAB `exp-warp-terrain-port` §6), so rev-tech's "nvcc
defaults to sm_75" is a default, not a wall.

| Choice point | Port as-is (current plan) | The Thor-native rewrite option | The experiment that proves it — **and what it measured** | Decided at |
|---|---|---|---|---|
| **The engine: 1.x vs 2.0** | Run Infinigen 1.x as the ported engine: bpy built from source, terrain patched to sm_110 | **Build on 2.0 + procfunc**, with our Warp terrain re-expressed as a v2/procfunc primitive. 2.0's single-process, in-memory generation *is* the warm-scene shape; the tracer's DAG is the missing half of the stage cache | **E §3, decided on the evidence**: 2.0 has the right architecture, no solver (which we would rewrite anyway), no terrain (which we own in Warp), no mesh export (which we must write). Its GT path is Cycles-based, so the untested headless-EGL risk **disappears**. Falsifiers named: alpha churn, rebuilding declarative layout, the mesh-export gap, numpy 1.x vs 2.x. **Confirming experiment running in `~/lm-wt/v2-thor`; step 1 (a v2 room + Cycles GPU render on the Thor) passed: 435 s wall, GPU 98 %, 78.5 W peak, 3.5 GB peak RSS, PNG out** | **M1** |
| **The scene / render path** | Port Infinigen's per-task Blender relaunch and `scene.blend` round-trip to aarch64 | **Retire the `.blend` hand-off entirely**: the resident scene service owns an in-memory scene graph other stages call into — the warm scene server taken to its conclusion (P §2.3-1) | **Measured, and it is a partial no**: on the real Hello Room the warm path's edit→preview p50 is **3.31 s against the batch path's 3.28 s** — no win, because the render dominates. The win is elsewhere and real: **builder wait p50 is 1.24 s lower warm**, and **kill -9 recovery reproduces the exact state digest** with no `.blend` in the recovery path (WS `results/`; report pending). On a synthetic scene warm does win outright (p50 0.42 s vs 0.49 s). 1000 edits grew RSS by **3.4 MiB** (3.2 KiB/edit) — but the recipe file is rewritten whole each time, a **550× write amplification** that must be fixed | M3 |
| **The constraint solver** | run the pure-Python annealer as a night job, room-scoped by day (RS §2.3) | batch-vectorise the greedy/SA inner loop on the 14 cores; score candidate moves on the Blackwell GPU | **Measured, and it is a conditional yes**: the GPU scoring port is **3 394× the Python path** at 16 384 candidates (47.95 M cand/s) — but at the solver's *actual* call pattern (one candidate per annealing step) **the restructured CPU wins** (0.04 ms vs 0.30 ms). The restructuring is the finding, not the port (LAB `exp-solver-scoring`) | M2→M3 |
| **Fine terrain (camera-aware octree SDF mesher, C++)** | run the existing CPU path | move SDF sampling and meshing to the GPU in **Warp** | **Measured, a breakthrough**: Infinigen's `mountains` element in Warp is **bit-identical** over 16 M points (max abs diff 0.0) and runs **44–56× the CPU path, 6× Infinigen's own CUDA kernel** — because that kernel copies through `cudaMalloc`/`cudaMemcpy` on every call, and on unified memory that copy is avoidable (LAB `exp-warp-terrain-port`). The next rungs are the remaining terrain elements and the OcMesher's SDF evaluation | **M1** (terrain is in scope from day one — E's §3: treat it as a follow-on and we spend months with no terrain) |
| **Preview rendering** | Cycles-CUDA low-spp (16-spp 480p is a config knob, P §2.1) | a Thor-native fast preview pass, or previews on the ProArt through the LOD export | **Measured**: the GPU is **7.1×** the CPU on the same frame (SP §5) — a 256-spp 1280×720 frame is 63.4 s on the GPU against 450.1 s on the 14 cores — and the whole Hello World scene renders in **48 s** (SP §4). Fast enough for a preview loop, per SP's own reading | M1→M3 |
| **Hot-tier models (companion LLM, critic, prop models)** | fp16 + SDPA attention (the sm_110-safe default, RT C3) | **FP8 quantisation** of the resident models — halving the resident bytes | **Measured**: FP8 on this stack is **1.6–1.7× FP16** on large GEMMs (177–183 TFLOPS vs 106–113) and **halves** the resident size of every weight matrix (3.73 GB vs 7.45 GB for a 4 B model). **FP4 is a measured no** — 13.69 TFLOPS, and *slower than dequantizing to BF16 and multiplying*. Do not schedule against NVIDIA's 2 070 TFLOPS FP4 figure (LAB `exp-fp8-tensorcores`). The remaining problem is the **activation cast**: weights-only FP8 gives 0.95× on a realistic chain, so the flag is worth testing for real now (RT R9) | M2→M3 |
| **The scheduler's residency model** | tiers (hot/warm/cold) over `nvidia-smi` memory | **tiers over unified memory with zero-copy hand-offs** — the same bytes seen by NumPy, PyTorch and a CUDA kernel | **Measured, a breakthrough**: a NumPy buffer is a **valid device address**; a kernel mutates NumPy's pages in place; PyTorch and CuPy share one buffer through DLPack with identical pointers; zero-copy costs no bandwidth (100.87 vs 100.93 GB/s). The win is 2.15× on the copy+read path **and the second 4 GB allocation disappears** (LAB `exp-unified-memory`). Consequence: never `.cpu()` a large tensor into pageable memory, and account residency from `/proc/meminfo` + `tegrastats`, because `nvidia-smi` cannot report it | M2→M3 |
| **Many agents, one pass (batching)** | one job per agent, serially | batch the crew through one resident model; the night's rails become iterations per goal | **Measured**: on the FP8 path the step time stays at ~10–12 ms from N=1 all the way to N=256 — so throughput rises from **101 items/s at N=1 to 12 345 at N=128 and 21 118 at N=256**, and the joules per item fall from 0.72 to **0.0048**. Batching is nearly free until the launch overhead dominates (L3 `exp2_batched`; the box was contended during the run, so the true number is better) | M2→M3 |
| **The critic's input** | render → PNG → read → critic | hand the critic the render buffer directly (zero-copy) | **Measured**: the PNG round trip is 48.5 ms at 480p and 293 ms at 1080p — 10× to 63× the critic's own forward pass, and **88 % of it is the PNG encoder**, not the disk (a faster disk solves nothing; the file write and read together are 1.5 ms even at 4K). Zero-copy from the render buffer is 2.9–3.5× faster and the saving grows with resolution (LAB `exp-critic-png-roundtrip`) | M2→M3 |
| **Hardware engines** | NVENC for filmstrip clips; PVA unused | NVENC/NVDEC for world-state latents between frames; PVA as a vision accelerator; CUDA Graphs in the hot loop | **Measured, and the roster is half poetry**: the Thor has **PVA v3 (9 contexts), NVENC and NVDEC**, and a full INA current-sensor set — and **no NVDLA at all** and **no OFA device node**. The joules metric is real: tegrastats and the INA sensors **agree within 2 %**. CUDA Graphs give **5.3×** on a hot small-kernel loop but only 1.06–1.15× on a real model stack (L3 `exp1_engines`, `exp5a_cudagraphs`) | M3 |
| **Background removal for image-to-3D** (`rembg`/ONNX aborts natively on Tegra CPU, RT R6) | the documented NumPy/SciPy patch or mesh-only with pre-cut alpha | do the alpha cut GPU-side in the prop service's own torch process (unified memory makes this copy-free), or a small CUDA kernel | run 10 images through both paths in the TRELLIS.2 spike: whichever never aborts and is faster wins; record peak RSS beside it | W2 |
| **Asset realization** (per-object sequential in `populate`) | sequential, cached by stage hash | parallel placeholder realization across the 14 cores, determinism preserved because stages already seed by `int_hash((seed, stage))` | populate wall-time vs object count from the stage timings; a parallel prototype on one room, byte-comparable outputs | M3 |
| **Filmstrip/timelapse delivery** | pre-encoded NVENC clips (P §6 move #4) | — (no further rewrite sought; PVA exists but has no load-bearing job yet) | the 10-min 1080p60 playback check of P §6-4 | M5 |

The ladder is climbed in cost order and every rung keeps the recipe as the
source of truth. **The four rungs with no prior art anywhere** — the GPU/Warp
terrain, the aarch64 port beyond the mechanical fixes, the warm scene server,
the stage cache, and the solver's GPU batching — are genuinely unclaimed (F
§0). That is the point of this project, not a risk: it is where the Thor-native
work is.

---

## 3. The first three weeks, in detail

**What exists now** (2026-10-31): the Thor is dedicated to the project, with
skald/last-mile services stopped and disabled at boot (C); the **bpy 4.2
wheel is built** and **Infinigen runs natively** (SP); the **engine decision
is made** — 2.0 + procfunc, Warp terrain as a v2-native stage (E) — and its
**confirming experiment is running** (`~/lm-wt/v2-thor`); the **core is
integrated on `main` with 831 tests green** (I), with the M1 session (30/30)
and the melt week (105/105) being **rewired onto it** (`~/lm-wt/m1-real`); the
Thor is at **MAXN**, connected by **2.4 GHz Wi-Fi only** (the 5 GbE port has
no cable), with the **external cold shelf offline** after a D-state wedge and
343 GB free on the internal NVMe.

Owners are seats, per the house way of working (C §"How work is done"): **Claude
(the director session)** reviews and commits; **zcode / mcode** run briefs in
tmux (bulk); **pi + aider on the local Qwen3-Coder-30B** is the free local
lane (needs the model server started — a Casey decision, §4); **Claude Code**
takes hard orders on a hosted budget; **Casey** decides, plugs the cable, and
plays the human baseline in the bake-off (B §3.5).

### Week 1 (Nov 1 – 7) — finish the rewire; land the engine gate

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 1 | **Finish the m1-real rewire.** Bring the M1 session (30 steps) and the melt week (105 steps) onto the integrated core: every step that can run on real code does, and each remaining stub is listed with the exact missing piece. Fix what the real run exposes, in the core, with tests. | seat + director | The stub/real tally before and after, published in the acceptance READMEs; the full suite green at the end (currently 831). **M1's core gate.** |
| 2 | **Land the v2 gate.** Finish `~/lm-wt/v2-thor`: trace the graph at seed 0 and seed 1, check byte-stability across two runs at one seed, edit one `choice` node's `chosen_idx` and re-execute, time a second scene in the same resident process, and settle `denoise_mode=NONE` vs OIDN and numpy 1.x vs 2.x for Warp. | v2 seat | E's four questions answered with numbers: (1) v2 renders on the Thor — **already yes**; (2) `graph.json` byte-stable and diffable across seeds; (3) a single-node edit materialises a targeted variant; (4) the warm-process number vs cold. **The engine gate.** |
| 3 | **The engine adapter behind the recipe.** A thin seam with the recipe on one side and the engine on the other, so a v1 → v2 change is one adapter rather than every recipe (E's first falsifier). Our own recipe schema sits *above* procfunc. | seat | A recipe written today survives an engine swap under it; the adapter is the only thing that changes. |
| 4 | **The render rung, real.** Point M1's stub render at the engine; produce a real image with an artifact hash, provenance and the license row. | seat | The M1 session's render steps serve `real:` and the report shows a real artifact. |
| 5 | **Plug the 5 GbE cable** (Casey's cable) and `iperf` it; **replug the external drive** and re-format it **ext4** for cold caches only. | Casey + director | A real link rate beside the 2.4 GHz Wi-Fi figure; the shelf mounts read-write and survives a heavy write. |
| 6 | **The cheap fork harvest** (hours, near-zero risk): the two `#include` fixes upstream has not merged, the Boolean EXACT solver commit that can otherwise hang a night, and the `sdf_from_mesh` empty-mesh GPU fix in the path we are about to port. | seat | Each is cherry-picked with a regression test; the Boolean fix has a degenerate-geometry test (F §7 items 1–3). |
| 7 | **The bake-off, finally run** — round 1 on the cheap, high-signal orders, then Claude Code vs OpenCode head-to-head on the hard one. | Casey (baseline) + director (scoring) | Blinded review; medians and spread; **the "cost per accepted order" number exists** — the input to the hosted-engineer decision. |

### Week 2 (Nov 8 – 14) — one honest night, end to end, on the real engine

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 8 | **The first real night.** The M1 session played live against the integrated core with a real render behind the render rung: a sealed bet, a real preview, a scripted verdict, a keep or revert, and a morning report that names the winner and what it beat. | Casey + director | The M1 session script of §2 passes end to end on a fresh project, with every render step `real:`. **M1 gate.** |
| 9 | **The stage cache and partial regeneration.** Key on `(recipe hash, engine pin, stage)`; "edit one room" re-solves only the touched room. The dirty-set contract written down before the first line of it. | seat | "Edit one room" end-to-end vs full regeneration, with per-stage timings; cache hit rate per night reported; cache keys ⊆ (recipe hash, engine pin, stage). **This is what makes a 534 s coarse stage affordable in a night.** |
| 10 | **The iteration loop, on real numbers.** Run the night as a loop: N variants per goal, score with the critic, keep the best, refine from it, up to K rounds or until the gain falls below ε. Measure **joules per fixed point** from the rails and report it in the morning. | seat + director | The report shows the winner, what it beat, and the round it came from; joules per fixed point is a measured number with the box's state beside it; the depth policy is inside the rails, not outside them. |
| 11 | **TRELLIS.2 matrix, completed and written up.** (the first two runs are already measured — TR `results/`) 512³ and 1024³ wall-clock, peak `MemAvailable` dip, BF16 vs FP8 on the same seed, GLB structure and PBR set. | trellis seat | RT spike 2's pass/fail: CUDA true, capability (11,0), a GLB with PBR out, timings and the memory dip recorded. **Props-per-night becomes a calculation.** |
| 12 | **The critic's calibration set, first members.** A fixed reference set of ~30 renders with seeded defects through scripted checks; publish false-positive/false-negative rates. | seat | The FP/FN table publishes its first row; verdicts stay `verdict@scripted` on their face until the numbers say otherwise (X S6). |
| 13 | **The fork harvest, the valuable part.** Port the four pipeline files that are a working prototype of the builders layer (≈1.5k LOC, BSD-3), re-targeted at a local model rather than a hosted one; and the LOD bake for the day-view wire. | seat | The builders layer runs against our own closed vocabulary; the LOD bake emits a GLB plus a `scene_lod.json` manifest (MQ §2; F §7 items 5–6). |

### Week 3 (Nov 15 – 21) — the honest week, and the first daytime world

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 14 | **The honest week on the real core.** Seven nights against the integrated core with a real render behind the rungs; capability rows; two-line estimates everywhere; standing exits in every branch set; the decision budget at the queue. | seat + director | The melt table reproduced or falsified **from the ledger alone**, on real renders rather than stubs; attention cost falling 16 → 2 across the week. **M2 gate.** |
| 15 | **The warm scene server, decided.** The measured numbers say the win is builder wait and crash recovery, not edit→preview latency — so the server's job is defined as *holding the scene and surviving a kill*, and the recipe store's whole-file rewrite is fixed (550× write amplification). | seat | 1–2 Blender starts per night instead of one per task; kill -9 recovery reproduces the exact state digest; the write amplification is gone. |
| 16 | **The ghost/LOD export measured** on the ProArt: export time and bytes per scene, the 4050's fps and VRAM, and one measured cold and warm client stream. | seat + Casey | The 8 s / 15 s numbers leave `[unmeasured]` or get re-planned (X R1). |
| 17 | **The night budget, from the rails.** Turn the measured engine numbers into the night's arithmetic: GPU-minutes, hosted-cents, wall-minutes, iterations per goal, and joules. Replace every `[e]` on the slate with a measured field the morning can quote. | director + seat | The slate shows no unmoved estimate on the main path; the morning's three-number line has a fourth, joules, and it is measured. |
| 18 | **FP8 for real.** Test `--fp8_e4m3fn-unet` on a real model — the flag that keeps activations in FP8, not just the weights — and measure quality held against latency. | seat | Either the 1.6–1.7× survives with quality held, or it does not and the scheduler stays FP16 with the reason written down (LAB `exp-fp8-tensorcores` §6). |
| 19 | **The first daytime world.** A daytime tick on the Thor: the world advances between sessions under the same recipe, with the ledger as its only state. Start small — one room, one clock. | seat | The world is reproducible from the recipe and a tick count; the morning can show what changed while nobody was watching. |
| 20 | **The maquette author, contacted.** A short, specific, technical note with one concrete question — framed as "we studied your pipeline and borrowed the guide idea", not as a rescue pitch. | director | A reply or no reply; either way the fork's BSD-3 code is already ours to use, and the answer to "is `songe-blender-mcp` available?" is worth the note (MQ §4). |

Standing rule for all three weeks, from the carried-over discipline: **measure
with the box's state beside the number** (C; V §"Rules carried over"), and no
claim of "works" without a render, a timing, or a test (C).

---

## 4. Decisions Casey must make

Draft 1 carried eighteen decisions in a table. They are now a **condensed
sheet**: `docs/decisions-for-casey.md` — twelve items, each with one line of
context, the options, the team's recommendation, and what happens if he does
not decide. The "just say yes" items (already adopted in the spec) are
grouped separately from the real choices, so a yes costs him a minute.

The ones that block the next three weeks: **the engine** (already decided by
the team, needs his yes), **hosted engineers and the money cap** (blocked on
the bake-off), **the always-on daytime world** (Law 1 — the day half of the
product), **the project licence** (the repo is public with no licence file),
**the maquette author** (a one-message decision), **the 5 GbE cable** and
**the external drive's ext4 reformat** (two minutes of his hands).

---

## 5. What we deliberately won't do yet — and why

1. **No live video streaming of the world.** "Thor renders, laptop is a
   television" is right for the morning and wrong for the day: you cannot
   navigate a Cycles render, and headless EEVEE on Jetson is unproven (P §3).
   NVENC's honest job is playback of pre-rendered truth — filmstrips,
   timelapses, branch clips (P §3 recommendation (c)).
2. **No OptiX.** There is no aarch64 OptiX SDK; Cycles builds CUDA-only at
   sm_110 (P §4 idea 16; RT ledger). **Now settled by fact**, not by
   inference: 7.1× over 14 CPU cores is plenty (SP §5).
3. **No generated character motion in shipped paths.** HumanML3D ← AMASS
   research-use restrictions flow into shipped clips (R §4; RT R8). Procedural
   walk cycles authored in the recipe instead (X R14).
4. **No voice, no TTS, no read-aloud yet.** Covered by no technology report;
   every voice path ships as text+click first (S §0 non-goals; X R14).
5. **No hosted/multi-tenant deployment, no accounts.** A LAN project with two
   named users; the privacy analysis changes completely the day that changes
   (S §0; T §"The privacy boundary").
6. **No CRDTs, no live co-presence editing.** Agents edit a recipe, not a
   shared document (S §0; D §7 Figma row). A share link is a bundle, not a
   live world (G §4.1).
7. **No USD → recipe round trip** except wrapped asset import; USD is a
   compiled, one-way output (S §7.11 adopting R §8 verbatim).
8. **No orchestration framework.** The audit log is the checkpoint (S §7.7).
9. **No single "prediction score," no approval meter, no praise.** A single
   accuracy number is theatre (X C2); approval is a measurement, never a
   currency (T §"Taste without sycophancy").
10. **No model from the skip list:** FLUX.1-dev, MusicGen, Hunyuan3D, CHORD,
    TexGaussian, MotionGPT, TRELLIS v1, InstantMesh, nvdiffrec, and any
    flash-attn / xformers / spconv / kaolin path (RT §3 register; 3D §8; R).
    The GGUF repack stays out until its licence is pinned (RT C5).
11. **No scheduling against published numbers.** Every throughput figure in
    the reports is an A100/H100/4090/Orin number; the scheduler's table is
    filled from this box only (3D §8; RT C7; X §4). **The rule is now
    enforced by measurement**: TRELLIS.2 at 101 s / 194 s, Cycles GPU at 7.1×,
    FP8 at 1.6–1.7×, warm at 0.42 s p50 on a synthetic scene — every one of
    these came off this box.
12. **No in-world client before the panels prove the loop.** The `[now]`
    surfaces carry M1–M4; the thin client is M5 and gated on measurements
    (D §8; S §6.2.10). The night feed, slate, report, board and library are
    complete products, not placeholders.
13. **No critic prompt before the reference set exists.** Otherwise
    "adversarial" is unfalsifiable (X §6-6).
14. **No camera-injection, OFA-deformer, 4×25 GbE or FP4-sizing work.** Wrong
    as framed on this devkit: **no OFA node, no NVDLA, no cameras, no
    populated cage** (L3 `exp1_engines`; P §4 verdicts); the 2,070 TFLOPS is
    sparse-FP4 inference marketing, and FP4 measured **13.69 TFLOPS** here —
    slower than dequantizing to BF16 and multiplying (LAB
    `exp-fp8-tensorcores`).
15. **No silent CPU fallback, ever.** Environments assert CUDA + capability
    (11,0) at build time, because the failure is a quiet 10× slowdown, not an
    error (RT R2). The `nvidia-smi` memory blind spot has the same shape and
    the same rule: measure from `tegrastats` and `/proc/meminfo`, and never
    print a false zero.
16. **No vendoring the maquette fork wholesale.** BSD-3 makes the *code*
    ours to take, but its factory bank is their art direction and their
    runtime helpers overlap our own terrain work; the report's own verdict is
    "take the guide idea, not the code" (MQ §3).
17. **No adopting cognitive-ecology's tick loop or attention economy.** The
    **WHY kernel is vendored** (MIT, byte-identical, with a corpus test) and
    that is the right amount: justification semantics without a per-tick
    bidding runtime for a two-user product whose night is a scheduled window
    (CE §3, recommendation (b)). The ecology stays the research home for the
    always-on question.

---

## 6. How we will know it's working

Two ledgers of measures — one for the experience, one for the machine — and
both are checked **at every milestone gate**, with the box's state recorded
beside every number (C; V §"Rules carried over"). Draft 1's placeholders are
now mostly measurements; the ones still open say so.

### Standing gates (every milestone, no exceptions)

- The **kill -9 test**: every panel renders from the ledger alone (S §5.4; D §2).
- The **two-referent test**: an ambiguous order returns a question, not a plan (S §6.1b).
- The **seal-order invariant**: `prediction.sealed` committed before its render job enqueues (S §5.1).
- The **honesty sweep**: no verdict shown as colour without a word (G §5.2);
  no `[e]` presented as a promise; the report's status line is computed from
  heartbeats, not narrated (G §2).
- **Zero fabricated work**: the four-mornings suite (G §7 test 6).
- **The engine swap test**: a recipe written under one engine still replays
  under the next, because our schema sits above the engine (E's first
  falsifier).

### Experience measures (checked at each gate, from the spine's budgets)

| Measure | Budget | Source | Where it stands |
|---|---|---|---|
| First line after open (cold or return) | ≤ 2 s, with denominator | X S1/S2; G §7 test 1 | built and measured in-process |
| Chip lands (Casey or Magnus) | ≤ 1.5 s | X S3/S4 | built |
| Compile → confirm readable | ≤ 20 s / ≤ 5 s | X S6; D §4 | built |
| Slate transaction | ≤ 30 s, no cancel | X C13 | built |
| Peek join / card legible / stop | ≤ 5 s / ≤ 5 s / ≤ 2 s | X S9 | built |
| Report first paint / digest | ≤ 3 s / ≤ 2 min | X S10 | **measured 0.2 ms** to build the page; 0.052 ms for the status line (LAB `morning-report-clock`) |
| Branch flip / apply / re-stream | ≤ 2 s / ≤ 10 s / `[unmeasured: M5 spike]` | X S11; RS P14 | **measured 0.69 ms / 0.94 ms**, both fsynced (LAB `core-recipe-branch-flip`); re-stream still open |
| Keep-reject / "why?" / question answer | ≤ 2 s / ≤ 1 s / ≤ 2 s | S §4.1; X S13 | built |
| Decisions asked per morning | ≤ 10, cut named at the queue | G §4.3; X G6 | **measured: 16 → 2 across the seven simulated nights** (the melt week) |
| Cold-start questions per first session / by night 7 | ≤ 6 → 0 | G §1.9 | **measured: 6 → 0 across the seven nights** |
| Attention hours per morning (the third number) | trending down | X G6; G §4.3 | measured in the melt week; not yet with a real engine |
| Share-bundle defaults | no author-scoped rows, licence manifest first page | G §7 test 13 | built |
| **Iteration shown, not implied** | the report names the winner, what it beat, and the round | V §"The Thor is an iterator" | new in draft 2; the seams ship, the report line is M1's job |

The experience measures are pass/fail: a milestone gate re-runs the session
script and the budgets together, because a moment that is honest but late, or
fast but fabricated, is equally a failure (D §"The three clocks"; X A11).

### Technical measures (the machine's growth beat, "The box" section of every report)

| Measure | Target / note | Source | Where it stands |
|---|---|---|---|
| Cycles CPU vs GPU, same frame | GPU must win | RT spike 1; P §7-1 | **measured: 450.1 s → 63.4 s = 7.1×** (SP §5) |
| Hello Room / World stage timings on aarch64 | recorded per stage; solver vs the paper's ~38 min (x86) | P §1, §7-2 | **measured: room coarse 534 s, render 1 307 s; world coarse 214 s + 57 s + 48 s ≈ 5.5 min**; the solver inside the coarse stage is not yet isolated |
| TRELLIS.2 wall-clock 512³ / 1024³; peak `MemAvailable` dip | fills the throughput table; props-per-night derived | RT spike 2; 3D §8; TR `results/` | **measured: 101 s / 194 s, peak RAM 55 GB / 68 GB, GPU rail 74 W / 79 W** |
| Model-load count per night | 1 per model (the load cap) | P §6-5; RS P3 | open — needs the bake-off and the scheduler's tables |
| Cold read of a model checkpoint into unified memory | decides the hot/warm/cold shape | LAB `exp-nvme-bandwidth` | **measured: 1.2–1.7 GB/s; a 7.45 GiB fp16 checkpoint lands in 6.5 s cold, 1.7–4.3 s warm** |
| Stage-cache hit rate per night | reported from M3 | P §6-2; RS P13 | open — M3 |
| Edit→preview p50/p95, batch vs warm; Blender starts per night | warm beats batch by the launch+I/O tax | P §6-1 | **measured, and it is a partial no**: 3.31 s warm vs 3.28 s batch on the real room (render-dominated); builder wait 1.24 s better warm; synthetic scene warm wins 0.42 s vs 0.49 s |
| Warm-scene durability and memory growth | survive a kill; no leak over 1000 edits | WS `results/` | **measured: exact digest recovery after kill -9; +3.4 MiB over 1000 edits (3.2 KiB/edit); 550× recipe write amplification to fix** |
| Peak RSS per warm scene / branch | decides resident branches and pre-baked options | P §7-3 | **partly: 3.5 GB peak for a v2 room render**; per-branch still open |
| Critic FP/FN on the seeded reference set | inside the band before any verdict loses `@scripted` | X S6; RS P15 | open — M2 |
| Critic input cost | the critic should read the buffer | LAB `exp-critic-png-roundtrip` | **measured: 48.5 ms at 480p / 293 ms at 1080p, 88 % PNG encoder; zero-copy is 2.9–3.5× faster** |
| FP8 vs FP16 on the resident models | quality held | LAB `exp-fp8-tensorcores` | **measured: 1.6–1.7×, half the resident bytes; FP4 a no** |
| Batch scaling of the resident model | where batching stops being free | L3 `exp2_batched` | **measured: ~10–12 ms/step from N=1 to N=256; 21 118 items/s at N=256 at 0.0048 J/item** |
| Joules per fixed point and per iteration | the night's governing metric | L3 `exp4_equilibrium` | **measured: warm start saves 1.43–1.55× the iterations; ≈ 2.33 J per iteration; joules rise with the field's size** |
| Power rails for the joules metric | two sources that agree | L3 `exp1_engines` | **measured: tegrastats and the INA sensors agree within 2 %** |
| Budget: lane-time spent vs bar, **the cut named**, hosted cents | `$0.00 (local)` until hosted is enabled | S §5.5; X C11 | built |
| Licence scan | no asset without a complete licence row incl. dependency terms | S §2.3.6; X R8 | built |
| Sustained power under MAXN; mode logged beside every timing | decides MAXN vs 120 W for nights | P §5, §7-6 | **partly: GPU rail measured at 64–79 W across the render and prop runs**; a full-night sustained figure is still open |

**The one-sentence version of success**, borrowed from the corpus and kept as
the north star of this plan: *a night that was honest (the peek), legible (the
report), and cheap to decide on (the branch flip) earns the next evening's
plan* (D §4) — and the only thing that has to grow for that sentence to stay
true is the ledger (X §5 closing).

---

*End of plan, draft 2. Sources: everything in `~/src/builder-ide/` as of
2026-10-31 — the corpus (V, C, S, U, I and all of `docs/research/`), the lab
(`docs/lab/`), the phase-1 spike report, the engine decision and its running
confirming experiment, and the merged core's own test suite (831 tests,
verified green on 2026-10-31). Synthesis only; no code outside this file; no
sub-agents.*
