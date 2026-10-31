# PLAN — builder-ide: the plan for the best user experience

Written 2026-10-30, round 3 part 2. This is the plan Casey reads. It is a
synthesis, not a new invention: every claim below cites the document it came
from, and where the documents disagree, this plan chooses and says why. The
plan is organised the way the product is lived: **the experience first, then
the milestones and the weeks that deliver it** (BRIEF.md; rnd-plan.md round 3).

**Citation key.** **V** = `docs/vision.md` · **C** = `CLAUDE.md` · **S** =
`docs/design/core-spec.md` · **X** = `docs/research/rev-ux.md` (its items are
C1–C13 contradictions, G1–G10 gaps, R1–R20 reality checks, S1–S15 spine
moments, D1–D6 owner decisions) · **G** = `docs/research/gaps.md` · **RS** =
`docs/research/rev-spec.md` (patch list P1–P20) · **P** = `docs/research/split.md`
· **RT** = `docs/research/rev-tech.md` (contradictions C1–C9, risks R1–R16,
spike order §5) · **B** = `docs/research/bakeoff.md` · **D** = `docs/research/ux-day.md`
· **T** = `docs/research/ux-trust.md` · **3D** = `docs/research/res-3d.md` ·
**R** = `docs/research/res-cad.md`.

**Timing convention** (G §intro, from X §4 and 3D §8): `[b]` marks a latency
**budget** — the UI must meet it and a test can check it. `[e]` marks an
**estimate that did not come off this box** and is therefore not a promise.
Unmeasured numbers are written `[unmeasured: SPIKE]` until the Infinigen spike
(`thor/SPIKE.md`) or a named spike fills them. The three clocks are inherited
unchanged (D §"The three clocks"): **Talk ≤ 2 s · Watch ≤ 5 s per card ·
Workshop ≤ 60 s with progress and a cancel** — anything that cannot hold its
clock moves to the night queue.

**Not present when this was written** (and therefore not used): the round-3
understanding document (`synth-u/UNDERSTANDING.md`), the landscape report
(`landscape/REPORT.md`), and `~/src/infinigen-thor/thor/SPIKE.md` — the bpy
build is still mid-flight on the external SSD (P §0 note; RT §0.1). Where the
plan depends on the spike's numbers, it says so.

---

## 1. The experience we are building

One paragraph, before the table. Casey and Magnus are building a world
(**Fjellvik**) with a crew of builders that work while they sleep. The promise
of the product is a loop, not a feature: **plan together in the evening, let
the crew bet sealed predictions overnight, wake to an honest report and a
cheap decision** (V; D §1–3). Everything the person lives through belongs to
one of three clocks, and the deepest rule in the whole plan is honesty about
what is measured: no line the builders speak without a denominator (T §"The 'I
think you'll like this' utterance"), no card without an artifact (D §2), no
speed number that did not come off this box (X §4, 3D §8), no silent model
swap (T §"Research transfer"), no fake progress ever (D §2 02:07).

The spine below merges rev-ux's fifteen moments (X §5) with the gap designs
(G §§1–4). Screens are D's six: *in-world view* (the ProArt client, [later]),
*plan slate*, *night feed*, *morning report*, *work-order board*, *asset
library* — plus the *kid panel*, which is the most accessible surface in the
product (G §4.2). "Honest version" states what ships when the technology
cannot yet keep the promise.

| # | Moment | Clock · budget | Screen | The honest version |
|---|---|---|---|---|
| 1 | **Cold open — night one, empty ledger.** "First night. I have nothing on you — 0 of 0. Four ways to start; pick one and I'll learn from what you keep." Four seed chips, each with its seed on its face. | Talk · ≤ 2 s from open `[b]` | Plan slate (empty) | Holds now as text. No world streams in — there is no stream promise to break (X R1); the first render is also the box's first measurement (G §1 19:58–20:04). |
| 2 | **The recognized return** (from night 3 on). "The north jetty stayed; the spiral stairs went. That's 1 of 2 on the line I read as straight and weathered — two more like that and I'll call it taste." Recognition with a count, never longing or absence-duration. | Talk · ≤ 2 s from app open `[b]` | In-world view [later]; a panel line [now] | The **line** holds always — it is a ledger read, instant by construction. The world behind it loads unnamed until a stream time is measured (X S2, R1). |
| 3 | **Cold-start questions.** "Deep joints, or flush?" — two crops side by side; one tap writes a taste note. ≤ 6 in the first session, strictly one at a time, any question skippable (a skip writes nothing). | Talk · ≤ 1.5 s per answer `[b]` | Plan slate / report | Cold start *is* taste acquisition, not a special case (X G1; G §1 20:12). |
| 4 | **Point-and-say chips (Casey).** A spoken intention becomes an editable chip where he pointed. Ambiguity is asked about, never guessed: "The slope, or the whole east shore?" | Talk · ≤ 1.5 s per chip `[b]` | In-world [later]; map+click [now] | The never-guess rule is code, not prompt (S §3.1.2). Chips are first-class records before any night exists (RS P11). |
| 5 | **Magnus taps.** Chips only — no mic, no free text, no keyboard — each with a Magnus badge and an `author: magnus` row. "Tower. Big or small?" — two chips over two silhouettes. | Talk · ≤ 1.5 s per chip `[b]` | Kid panel | Structured data from the first second: no free text to leak, because there is no free text (X C7/D4; T §"Magnus at the controls"). |
| 6 | **The plan slate.** One screen: intentions with owner, predicted cost, the builder's one-line take; one budget bar with counters underneath; **work-order time as its own line**; every estimate marked `[e]` until measured. | Workshop · transaction ≤ 30 s, no cancel (the night has not started; before the night a slow decision is free) | Plan slate | One bar for the owner ("8 h wall · 2.0 h lane `[e]` · $0.00 hosted (local)"), four counters for the scheduler (X C9; G §1 20:31). |
| 7 | **The limit, said aloud.** The Architect: "Swing isn't in my hands yet — 0 built. Creaky loose planks: yes." A capability row on her face, so the claim is a record, not decoration. | Talk · ≤ 2 s | Plan slate / work-order board | Capability rows cite vocabulary use counts (X C12; RS P18). |
| 8 | **The one-line work order.** "Computer, I want rope bridges that swing." → compile with progress and cancel ≤ 20 s `[b]` → a **question XOR a confirm**: "CONFIRM: rope bridge, south span, hempen, 8 planks; passes the analytic load check at 2×; build/verify ~40 min `[e]`, generate/test ~1.5 h `[e]`; reversible at ver_0192. Go?" | Workshop ≤ 20 s → Talk · confirm readable ≤ 5 s `[b]` | Work-order board | Two prices, never one (X R16); acceptance is a scripted analytic computation, not "the sim" — no physics engine exists (X R11; RS P5). |
| 9 | **The pre-flight.** Ten seconds after "Start the night": "PREFLIGHT: lane free · queue 2 items · client detach: on close or 22:00 timeout, whichever first." If the lane is busy it proposes (start late / start degraded / cancel); it never decides. | Watch · ≤ 10 s | Plan slate | The timeout is the fix for the client that never detaches (X R19; RS P10). |
| 10 | **The handoff.** "Two small bets tonight. Both sealed as guesses — zero priors. Morning: what we kept, what we guessed, and this box's first real numbers." The night is silent by construction. | Workshop · ≤ 30 s | Plan slate → night feed | Sealed guesses are legal on night one — the gate forbids pretending to a view, not betting (G §1 20:44). |
| 11 | **The sealed bet (no screen — the ledger).** edit → predict → **seal** (hashed, committed before the render job exists) → preview → checks → keep or revert. Recipe diffs are hundreds of bytes. | Night; the feed is the only user-visible surface | (ledger; night feed cards) | Previews are priced as batched lane-minutes `[e]`, never "38 seconds" (X R3); automated verdicts read `verdict@scripted` until a critic is chosen and calibrated (X R4/S6; G §1). |
| 12 | **The 2 a.m. peek.** Join cold, understand who did what, kept or reverted; rewind free; **never fast-forward of live work**; one stop button, always visible. | Watch · join ≤ 5 s; card legible ≤ 5 s; stop ≤ 2 s `[b]` | Night feed | The feed is the log, not a stream — kill -9 the server and it re-renders from the ledger alone (D §2 02:07; S §5.4). |
| 13 | **The morning report opens — before the world.** First the status line (`ran as planned / ran short / ran degraded / did not run` + one-line reason), then the failures, then the numbers **with the cut named**, then the filmstrip, branches, parked questions, landed work orders, per-claim-type tallies with denominators. No single "prediction score" — it is theatre (X C2). | Watch · first paint ≤ 3 s; digestible ≤ 2 min `[b]` | Morning report | A static page over the ledger: fast forever. Dark ≠ asleep ≠ busy, stated in words under the picture (G §2; X G2/G5). |
| 14 | **The branch flip and apply.** A/B/C pre-rendered overnight, plus the two standing exits present from night one: **keep yesterday** and **back to the plan**. Magnus points at C: "that one" — it becomes a proposal; Casey confirms (a branch is a recipe pointer, a real edit). | Watch · flip ≤ 2 s → Workshop · apply ≤ 10 s; re-stream ≤ 15 s `[unmeasured: W3 #16, the LOD/client-stream spike]` | Morning report → in-world [later] | Flip/apply are pointer moves, always fast (S §1.2). The re-stream number is measurement-gated and each option's scene manifest is pre-baked by the night (X S11; RS P14). |
| 15 | **The parked question — or the assumption that replaced it.** One tap to answer; a taken assumption sits on the same card. Top three shown, the rest counted ("31 more, none blocking"); at most 3 blocking questions may exist — the fourth parks the *task*. | Talk · ≤ 2 s `[b]` | Morning report | Both are ledger reads; the dam is at night, not at breakfast (X S12; G §4.5). |
| 16 | **Magnus's morning.** "You asked for a tower. It is by the water. Casey kept the north jetty." Presence-continuity is his trust; no scores, no percentages — counts out of five only when asked. | Talk · ≤ 2 s | Kid panel | His first three keeps are `pending_ratification` and invisible to the builders' gates until Casey answers one question: "Does he know what *keep* means?" (G §3). |
| 17 | **"Why?" in one tap.** Prompt, seed, model id, weights revision, licence **including dependency terms**, sampler, environment revision, critic note, who decided. | Talk · ≤ 1 s `[b]` | Anywhere | **Holds fully — the best-supported promise in the corpus** (X R8), because the technology requires exactly this record. "Regenerate" with a different model is labelled **"reinterpreted"** (X R9). |
| 18 | **The growth beat.** "I can do rope now. North span too?" — the new capability announced in one sentence at the moment it becomes useful. Model changes are announced too, in character, at the next report. | Talk · ≤ 2 s | In-world [later] / report [now] | Promotion is one core transaction (S §2.3); the notice rule costs nothing and prevents the Replika-shaped betrayal (T §"Research transfer"). |
| 19 | **The ledger line that reaches the artifact.** Not a dashboard: "Architect had 14 of 18 right on shadow counts; this one is in that run. Its last miss was a double pier, three weeks ago." | Talk · ≤ 1 s | Report / asset library | One tally-read API away (RS P20). |
| 20 | **The three-number morning line.** "5.3 h of your Thor · $0.00 hosted (local) · 2 h of your attention." A morning may ask for **≤ 10 decisions**; a night that would need more is cut at the queue, and the report says where. | — (report footer) | Morning report | The attention number is the one nobody measures and the one that decides whether the owner comes back (X G6; G §4.3). |
| 21 | **Sharing a night.** "Share this night" builds a recipe + provenance bundle: licence manifest on the first page, thumbnails, author-scoped rows excluded by default, labelled **"recipe — re-render may differ."** | Watch · bundle build ≤ 30 s `[e]` | Morning report | The recipe is kilobytes; the pictures are not — and the label says which is which (X G3/R15; G §4.1). |
| 22 | **The world in the room** `[later]`. Arrival beats, ghost work-order previews against the *current* commit, point-and-say chips in-world, voice (unevaluated — no TTS was researched; X R14). One rule: **the client is a viewer of a named commit, never a holder of state.** | Watch/Workshop (budgets above) | In-world view | The ghost/LOD glTF export makes the ProArt the renderer (P §2.3-4, move #3); the Thor's GPU stays for models and previews. Live video streaming is **not** this moment — see §5. |

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

### M0 — "The box tells the truth" (days, in flight)

- **Lived:** Casey opens one page and sees his own machine's first honest
  numbers: Hello Room and Hello World rendered on the Thor, CPU vs GPU timed,
  the patches tracked, `SPIKE.md` written with the box's state beside every
  number (B WO-1; C §Status).
- **Acceptance script:** `bash thor/verify-port.sh` exits 0 (patches tracked,
  upstream-appliable); `cuobjdump --list-elf` on the Cycles kernels shows
  sm_110; two PNGs (CPU, GPU) of the same frame exist with timings and the
  power mode beside them; `run-timed.sh selftest` prints
  `gpuMem=unavailable(unified-memory)`, never a false zero (B WO-4; RT C9b).
- **Technical work:** finish the bpy 4.2 wheel build (in flight, external
  SSD); apply the Cycles sm_110 `config.h` patch (RT R10); fix `run-timed.sh`
  memory sampling to `tegrastats` (RT R3); write `thor/SPIKE.md` (B WO-1).
- **Risks / what changes:** if bpy 4.2 will not build or GPU render is slower
  than CPU, the whole engine plan changes (P §7-4) — fallbacks are Blender
  4.0.2 from apt with API shims, and previews moving to the ProArt through the
  LOD path (P §6-1). This is the plan's largest single uncertainty.

### M1 — "One evening, one night, one morning, one builder, one room" (≈ week 2)

- **Lived:** the crate night, in its cold-start form (S §6.1 + G §1). Casey
  creates a project, gets the zero-denominator opener and four seeds, answers
  ≤ 6 two-chip questions, puts two small bets on a slate with a budget bar,
  says "Go" to one honest work order (crates gain lids and rope handles), goes
  to bed. In the morning: status line, failures first, the numbers with the
  cut, two branches plus keep-yesterday and back-to-the-plan, one landed work
  order with a preview and evidence, "why?" in one tap, and the tally saying
  *"2 sealed · 1 hit · 1 miss — not taste yet; that is a start."*
- **Acceptance script (session):** played on a fresh project, it must pass
  S §6.1's slice gates — (a) the kill -9 test: kill the feed server mid-night,
  reopen, the feed renders from the ledger alone; (b) the two-referent test:
  an order with two plausible referents returns a question, never a plan; (c)
  a sealed prediction exists with `sealed_at` strictly before its render job's
  enqueue; (d) the report renders with zero panel-side state; plus the cold
  open test (first line has a zero-denominator, no adjective about the owner,
  one offer of four seeds) and the question budget (≤ 6, strictly sequential,
  every row with a reason code and an artifact ref) (G §7 tests 1–4).
- **Technical work:** the core slice of S §6.1 — SQLite audit ledger +
  projections, FastAPI + SSE, recipe store with branches and typed edits, one
  character (Prop-maker, scripted loop acceptable) making typed calls, three
  vocabulary words, one work order compiled from a text+click context packet
  **with the node registry fix** (RS P1 — without it "make these sturdier"
  cannot compile), one engineer (`aider-local`) behind the full adapter
  (worktree + seat + MCP tools), the minimal merge gate (deterministic
  rebuild, tests, rung-2 render, scripted checks, licence scan, budget audit),
  the minimal night runner with per-task rails, and the morning report page.
  Patches to fold in as built, not later: P2 (no single score; status line),
  P5 (analytic checks, no "sim"), P6 (three-writer rule), P7 (geometry check
  before critic; thrash row), P10 (client attach/detach + timeout), P11
  (pre-night slate records + stored asks).
- **Risks / what changes:** if the bpy wheel is late, M1 runs its render rungs
  against a **stub generator** (deterministic images) and the engine lands in
  M2 — the loop, the ledger and the report do not wait on Blender. If
  `rembg`/ONNX aborts on Tegra CPU (RT R6), the prop path stays mesh-only with
  pre-cut alpha.

### M2 — "The honest week" (≈ weeks 3–5)

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
  ask > 10 decisions is cut at the queue and the report says where).
- **Technical work:** pre-flight + heartbeat + computed status line (G §2);
  capability rows (X C12); the calibration batch — a fixed reference set of
  ~30 renders with seeded defects through scripted checks, publishing
  false-positive/false-negative rates (X S6; RS P15); watertightness before
  the critic (RS P7); graduated throttling + kill switch at full strength and
  the **per-model load cap** enforced at batch admission (S §5.5; RS P3);
  actor-scoped chips and Magnus-safe endpoints (RS P8); taste export/erase
  via tombstone events (RS P9); the share bundle (G §4.1); the tally read API
  (RS P20). Engine side: the port graduates from Hello Room to a seeded room
  variant good enough to be "one room" — stage timings recorded per stage.
- **Risks / what changes:** if the calibration batch shows the scripted checks
  cannot catch seeded defects, critic selection is pulled forward and becomes
  the milestone's blocker (X R4). If stage timings show the solver is 2–4×
  worse than the paper's ~38 min on ARM (P §7-2), room-scoped re-solving
  moves from "nice" to "the only way the Architect ever works at day" — the
  Architect's day-side work re-plans around it.

### M3 — "The crew, and the vocabulary that grows" (≈ weeks 5–8)

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
  scheduler tiers with provenance stamping and the CPU lane (S §6.2.2); the
  recipe → USD/glTF compiler with deterministic emission (S §6.2.3; R §8);
  **the warm scene server** (P §6 move #1; RS P4) and the **recipe-hash stage
  cache + partial regeneration with the dirty-set contract and pinned engine
  config** (P §6 move #2; RS P13); generative stations: TRELLIS.2 via
  ComfyUI native + TripoSR baseline behind a thin HTTP service of modly's
  shape (RT C3's composition; RT spike 4; RS P12), textures via TRELLIS.2's
  shape-conditioned texturing plus StableMaterials/SDXL, and ambience via
  ACE-Step (RT spike 5 — Apache-2.0 and OpenRAIL, both licence-verified);
  critic selection gated on the M2 calibration numbers.
- **Risks / what changes:** TRELLIS.2's on-box throughput `[unmeasured: spike
  2]` decides how many props a night can afford — if 1024³ lands far above the
  tens-of-seconds estimate, props become library-first with generation as the
  exception (3D §4.1). If the warm scene server's peak RSS per branch is
  large, fewer pre-baked morning options exist (P §7-3). The engineer seat may
  change: if Claude Code's measured median cost per accepted hard order
  exceeds ~$2 or its budget cap leaks, Seat A moves to OpenCode (B §4.2).

### M4 — "Magnus's Sunday" (≈ weeks 6–9, can start earlier — it is [now]-shaped)

- **Lived:** Magnus's first session is a **five-chip guided world**: tap one
  of five nouns ("Tap one. It gets built tonight."), see the chip land with
  his badge ≤ 1.5 s, hear the limit said to a nine-year-old ("Swing isn't in
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

### M5 — "The world in the room" `[later]` (≈ weeks 9+, gated on measurements)

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
  `since_version` deltas (RS P14); the 5 GbE RJ45 + NVENC clip channel
  (P §6 move #4); the thin client itself; voice only after a TTS is actually
  evaluated (X R14).
- **Risks / what changes:** if initial-scene export or the 4050's rendering
  cannot hold the clocks, the day half stays on panels and the world stays a
  morning-and-peek experience — the loop of M1–M4 is complete without it.

### The rewrite ladder — where porting stops and Thor-native begins

Casey's addendum to this brief: everything here is open source, so the plan may
heavily rewrite Infinigen, Blender stages and generators for this specific
chip — unified memory, the Blackwell GPU, the hardware engines, the 14
Neoverse cores — not just port them (BRIEF.md addendum; the vision already
says the engine is "improved as we go" and the port exists to be made
*interactive*, V §"The pieces" #1). The milestones above are deliberately
rewrite-friendly: the warm scene server, the stage cache and partial
regeneration (M3) are already rewrites of Infinigen's batch process model, not
ports (P §2.3). Where a genuine port-as-is vs Thor-native-rewrite choice
exists, here is the rewrite option and the experiment that decides it. The
one build rule every rewrite inherits: `-arch=native` + `cuobjdump --list-elf`
before trusting any produced `.so` (RT C6/R1), and honest about which chip
feature actually matters — FP4/FP8 tensor cores accelerate neural inference,
not Cycles' FP32/FP16 render math (P §4 idea 10).

| Choice point | Port as-is (current plan) | The Thor-native rewrite option | The experiment that proves it | Decided at |
|---|---|---|---|---|
| Blender 4.2 / bpy | source-build the wheel + sm_110 patch set, kept as a permanent fork (RT R10) | keep Infinigen's generators (Python + node graphs, BSD-3) but retire `scene.blend` file hand-off entirely: the resident scene service owns an in-memory scene graph other stages call into — the warm scene server taken to its conclusion (P §2.3-1) | p50/p95 edit→preview, batch vs warm, on the same edit (W3 #14): if the launch+I/O tax dominates even warm, the blend-file boundary is the cost, and the rewrite is justified | M3 |
| The constraint solver (~38 min/5k steps on the authors' x86; likely worse at 2.6 GHz ARM, P §1/§7-2) | run it as a night job, room-scoped by day (RS §2.3) | batch-vectorise the greedy/SA inner loop (numpy on the 14 cores; room assignments are already enumerated per-assignment, P §2.3-2), or score candidate moves on the Blackwell GPU | profile one room's solve from the W1 stage timings, then a two-day prototype of the vectorised inner loop on the same scene, same seed — same result, less wall | M2→M3 |
| Fine terrain (camera-aware octree SDF mesher, C++ single-process, P §1) | run the existing CPU path (already compiled on this box) | move the SDF sampling/meshing to the GPU, which the coarse stage already does for its kernels (terrain CUDA exists, commit `3668454a`) | if fine-terrain shows up as a top-3 night cost in the stage timings, prototype one tile GPU-side and compare tiles/s and watts | M3 |
| Preview rendering | Cycles-CUDA low-spp (16-spp 480p is a config knob, P §2.1) | a Thor-native fast preview pass, or previews on the ProArt through the LOD export (already the fallback, P §6-1) | measured tiles/s of Cycles-CUDA at 16-spp 480p from the M0 timings: if it cannot hold the 60 s Workshop clock, the rewrite path is taken by rule (the clock is the test) | M0→M3 |
| Background removal for image-to-3D (`rembg`/ONNX aborts natively on Tegra CPU, RT R6) | the documented NumPy/SciPy patch or mesh-only with pre-cut alpha | do the alpha cut GPU-side in the prop service's own torch process (unified memory makes this a copy-free hand-off), or a small CUDA kernel | run 10 images through both paths in the TRELLIS.2 spike: whichever never aborts and is faster wins; record peak RSS beside it | W2 #7 |
| Hot-tier models (companion LLM, critic) | fp16 + SDPA attention (the sm_110-safe default, RT C3) | FP8 quantisation of the resident models (`--fp8_e4m3fn-unet`-class flags exist but are unvalidated on sm_110, RT R9) | talk-clock and watch-card latency at fp16 vs fp8 with quality held: adopt only if it buys the ≤ 2 s / ≤ 5 s budgets back | M2→M3 |
| Asset realization (per-object sequential in `populate`, P §1) | sequential, cached by stage hash | parallel placeholder realization across the 14 cores, determinism preserved because stages already seed by `int_hash((seed, stage))` (P §1) | populate wall-time vs object count from the stage timings; a parallel prototype on one room, byte-comparable outputs | M3 |
| Filmstrip/timelapse delivery | pre-encoded NVENC clips (P §6 move #4 — already the Thor-native use of a hardware engine) | — (no further rewrite sought; the PVA v3 engine exists on this box, P §0, but has no load-bearing job yet — it stays unused until an experiment earns it) | the 10-min 1080p60 playback check of P §6-4 | M5 |

The ladder is climbed in cost order and every rung keeps the recipe as the
source of truth — a rewrite that changed what a recipe means would break the
one guarantee the whole experience stands on (R §8; S §7.11).

---

## 3. The first three weeks, in detail

**What exists now** (2026-10-30): the Thor is dedicated to the project, with
skald/last-mile services stopped and disabled at boot (C); `~/src/infinigen-thor`
branch `thor-spike` has CPython 3.11, OpenImageIO and the terrain CPU
extensions compiled, the bpy wheel still building, **two untracked patches**
and a measurement wrapper that prints a false `maxGPUmem=0MiB` (B WO-1, WO-4;
RT §0.1); the core spec is written, no builder-ide code exists (B §2 WO-3
caveat); the bake-off is designed but not run (B §7); the Thor's local model
servers are **stopped**, so the free local lane has a start step and a memory
price (B §0.1, §3.7).

Owners are seats, per the house way of working (C §"How work is done"): **Claude
(the director session)** reviews and commits; **zcode / mcode** run briefs in
tmux (bulk); **pi + aider on the local Qwen3-Coder-30B** is the free local
lane (needs the model server started — a Casey decision, §4); **Claude Code**
takes hard orders on a hosted budget; **Casey** decides, plugs the cable, and
plays the human baseline in the bake-off (B §3.5).

### Week 1 (Oct 30 – Nov 6) — land the truth about the box, and the first slice's bones

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 1 | Finish the bpy 4.2 wheel; verify kernels; Hello Room + Hello World; CPU-vs-GPU Cycles timings with the power mode logged; write `thor/SPIKE.md` | spike seat (in flight) + mcode assist | RT spike 1's checks: wheel imports; `cuobjdump --list-elf` shows sm_110; both scenes complete; two PNGs + timings + box state. **M0 gate.** |
| 2 | Track the two patches; write `thor/verify-port.sh`; fix `run-timed.sh` to `tegrastats` and emit `gpuMem=unavailable` | zcode (bulk) | B WO-1 / WO-4 acceptance checks exit 0; the selftest parses the real `[N/A]` line to "unavailable", not zero. |
| 3 | Bake-off round 1: all contenders × WO-1 + WO-4 (cheap, high-signal), then OpenCode vs Claude Code head-to-head on WO-1/WO-2 | Casey (baseline + sandbox) + director (scoring) | B §5 run sheet; blinded review; the Seat A decision data exists (cost per accepted order). |
| 4 | Core skeleton: SQLite audit ledger + projections, FastAPI, SSE `/v1/events`, the §4.2 endpoints; recipe store (versions, branches, typed edits, pre-render constraint checks) | zcode + mcode | Unit suites green; `list --json` byte-identical across runs (B WO-3's determinism check); kill -9 of the service loses no committed event. |
| 5 | Three vocabulary words + the Prop-maker scripted loop + sealed predictions with the confidence gate | zcode | Negative cases rejected at the door (out-of-schema params refuse); a sealed bet's `sealed_at` precedes its render job's enqueue, checked by test. |
| 6 | Build rules into every script, not memory: `-arch=native` (or `compute_110/sm_110`) + `cuobjdump --list-elf` on every produced `.so`; assert `torch.cuda.is_available()` and capability `(11,0)` at env build time | director (scripts) + seats | A CI check that fails loudly on sm_75-only binaries and on CPU-only torch (RT R1, R2). |

### Week 2 (Nov 7 – 13) — one honest night, end to end

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 7 | TRELLIS.2 spike on ComfyUI with stock PyPI torch 2.15 (E2 env) | pi/aider-local + spike seat | RT spike 2: CUDA true, capability (11,0), a GLB with PBR out, wall-clock at 512³ and 1024³ recorded, peak `MemAvailable` dip recorded, no compiled extensions. |
| 8 | USD backbone spike: recipe → layered USD + build123d STEP→GLB, provenance in `customData`, deterministic re-emit | zcode | RT spike 3: byte-identical re-emission (sorted prims, no timestamps); build123d uses zero GPU memory. |
| 9 | One engineer behind the full adapter: `aider-local` (local lane; if the model server stays off, `pi` on the same lane or zcode as the slice engineer) — worktree, seat, MCP tools, minimal merge gate | zcode + director | WO-15 (crates v2) delivered, gated, landed as a preview card with evidence; budget audit within 20%. |
| 10 | Night runner (minimal): task queue, per-task + per-night rails, status line + heartbeat, detach-or-timeout, morning report page | mcode | The four-mornings suite passes on simulated nights; report renders with zero panel-side state. |
| 11 | **M1 acceptance session played live** (Casey at the ProArt, panels in a browser) | Casey + director | The M1 session script of §2 passes end to end on a fresh project. **M1 gate.** |
| 12 | Cold-start ask-mode + the calibration batch's first members (seeded-defect reference set grows nightly, sized to the unused lane) | zcode | G §7 tests 1–3; the reference set's FP/FN table publishes its first row. |

### Week 3 (Nov 14 – 20) — the honest week begins; the interactive half gets its spikes

| # | Work | Owner | Pass / fail |
|---|---|---|---|
| 13 | Seven-night melt run (real or simulated owner); capability rows; two-line estimates everywhere; standing exits in every branch set; decision budget at the queue | mcode + director | G §7 tests 4, 7, 9, 10; the melt table of G §1.9 reproduced or falsified from the ledger. |
| 14 | Warm scene server spike (P move #1): resident Blender process, in-place stage calls | spike seat | p50/p95 edit→preview latency, batch vs warm, on the same recipe edit; Blender process starts per night → 1–2. |
| 15 | Stage cache + partial regeneration (P move #2), with `EnginePin` gaining the config hash and the dirty-set contract stated | spike seat + zcode | "Edit one room" end-to-end vs full regeneration; stage-cache hit rate per night reported; cache keys ⊆ (recipe hash, engine pin, stage). |
| 16 | Ghost/LOD glTF export spike (P move #3) + one measured cold and warm client stream; plug the 5 GbE RJ45 (Casey's cable) and iperf it | spike seat + Casey | Export time and bytes per scene; ProArt fps and VRAM on the 4050; the 8 s / 12 s / 15 s numbers leave `[unmeasured]` or get re-planned (X R1). |
| 17 | Bake-off round 2: WO-2, WO-3, WO-5, WO-6, N≥3, plus human baselines; seat assignments fixed for M3 | Casey + director | B §5; median-and-spread recorded; the lineup of B §4.1 confirmed or swapped per B §4.2. |
| 18 | Critic selection from the calibration numbers (small local vision models on the Thor; SDPA path, no flash-attn) | spike seat | FP/FN inside the target band on the reference set (catch seeded defects; reject no more than a set fraction of clean ones) — otherwise verdicts stay `@scripted` (X S6). |

Standing rule for all three weeks, from the carried-over discipline: **measure
with the box's state beside the number** (C; V §"Rules carried over"), and no
claim of "works" without a render, a timing, or a test (C).

---

## 4. Decisions Casey must make

Collected from every report's open-decision section: T §"Open decisions" (six),
X §7 (D1–D6), G §8 (three), RS (implied by patches), B §4.2, P (the cable),
RT §4.1 (E5). Several have already been adopted inside S; those are marked
**ratify** — the plan needs his yes, not a new debate.

| # | Decision | Options | Team recommendation |
|---|---|---|---|
| 1 | **Who writes the ledger** (X D1/D2/D3; T's single-writer rule vs D's self-keeping night) | (a) three record types, one writer each: `taste_note` owner-only, `prediction` builder-sealed, `verdict` Critic-for-defects (X C5) · (b) owner-only for everything (kills the night's automated keeps) · (c) let the night write taste (the ledger trains on itself) | **(a) — ratify.** Without it the sealed bets become unfalsifiable and Magnus's rows decorative (X §2 C5: "fix this before anything else is built"). S has the pieces; RS P6 states the join. |
| 2 | **Does the Critic judge quality or taste** (X C6) | (a) split: defect Critic never sees the ledger; a taste-critic that may only *rank* · (b) one critic that has learned your taste | **(a).** "The Critic decides whether a thing is *good*; you decide whether it is *yours*" (X C6). A critic that learned your taste approves anything that matches it. |
| 3 | **May Magnus speak, and what may he apply?** (X C7/C8/D4) | (a) chips only; preview-keeps and question-answers his; branch applies are proposals Casey confirms · (b) spoken + full apply (D's original morning) | **(a) — ratify** (S §7.4/§7.10 adopted; RS P8 makes it structural). His input is structured data from the first second; a nine-year-old should say "that one" about a picture, not repoint the hamlet's recipe (X C8). |
| 4 | **The night rail, in what units** (X D5/C9; S §5.5; RS P3) | (a) one bar for the owner (wall + lane-time + $ hosted), four counters underneath incl. a **per-model load cap** enforced at batch admission · (b) a single GPU-hour bar (D's original) · (c) money-first rails (T's AWS framing) | **(a) — ratify + extend.** GPU-hours are not enforceable before spend; the hardware's real constraint is weight-swap thrash (R §9; X §6-1; RT C9). Money is scoped to hosted calls only and reads `$0.00 (local)` by default — itself a product statement. |
| 5 | **The morning report's first lines** (X D6/C2/C11; RS P2) | (a) status line → failures → numbers with the cut named; no single prediction score · (b) the night line first (D's original) | **(a) — ratify.** The single score is "the one number both reports must kill" (X C2); a report that shows "5.3 of 5.5" without the 1.7 h that was dropped is the most dishonest-looking artifact in the set (X C11). |
| 6 | **The prop/texture stack** (X §7 ruling; RT C3/C5; RS P12) | (a) TRELLIS.2 via ComfyUI native + TripoSR baseline; textures via TRELLIS.2's shape-conditioned texturing; a thin HTTP service of modly's shape in front · (b) modly + TripoSG with its texture path (Tencent licence + two CUDA source builds) | **(a).** res-3d supersedes res-cad here: MIT code *and* weights, real PBR, zero compiled CUDA extensions (RT C3). The modly texture path and the licence-unknown GGUF repack stay **closed** until terms are pinned in writing (RT C5/R13). |
| 7 | **The Critic model, and when** (X R4/S6; RS P15) | (a) scripted checks now (`verdict@scripted` on the face), choose a vision model only from calibration numbers · (b) pick and prompt a critic now | **(a), then (b) at M3.** The critic is "the largest unchosen dependency in the whole stack" and no report evaluated one (X R4); without a reference set, "genuinely adversarial" is a vibe (X §6-6). |
| 8 | **Character motion** (RT R8; X R14) | (a) procedural, recipe-authored walk cycles; no generated motion in shipped paths · (b) MoMask clips now, AMASS data-provenance flag on every clip | **(a).** The data licence flows into shipped outputs (R §4; RT R8). Revisit only with a licence review or mocap. |
| 9 | **Hosted engineers and the money ceiling** (S §5.5; B §4.1/4.2) | (a) hosted off by default; Claude Code for hard orders under a per-night cents cap once bake-off numbers exist · (b) always local · (c) hosted by default | **(a).** Local is free but the local model servers are stopped and a 30B model is ~60 GB of the same unified pool the renderer wants (B §3.7) — price it as residency, not as free. |
| 10 | **Start the Thor's local model lane?** (B §0.1/§3.7; C) | (a) start `Qwen3-Coder-30B` on :8001 for the aider/pi lane, scheduled away from render windows · (b) leave stopped; slice engineer is zcode | **(a) from week 2 if W1 shows memory headroom, else (b).** The undo lines exist in `~/last-mile-ops.md` (C); the decision is Casey's because the services were disabled at boot by his instruction. |
| 11 | **Orin: worker or non-goal** (RS P19; P §2.2) | (a) non-goal for now, revisit at M3 for CPU-lane overflow · (b) add `Job.worker` + watchtower now | **(a).** S is single-writer and Thor-only by design; CLAUDE.md says ask before using the Orin. Add the worker field when a measured CPU-lane backlog exists. |
| 12 | **The 5 GbE cable** (P §3/§6-4) | plug it · stay on 2.4 GHz Wi-Fi | **Plug it.** One cable, driver verified; stops the 2.4 GHz band being the system bus. Costs a minute of Casey's cooperation. |
| 13 | **Cold start: mechanism or number of nights** (G §8-3) | (a) mechanism — questions and `guess` confidence decay per builder per reason code at two observations · (b) a fixed onboarding week | **(a).** Makes the first week's melt auditable in the ledger rather than tuned by hand. |
| 14 | **May the pre-flight act when the lane is busy** (G §8-2) | propose only · auto-degrade | **Propose only.** The owner's bar, the owner's start; the sole exceptions are the safety rails (T §"Safe mistakes"). |
| 15 | **Does the taste ledger ever leave the machine** (T open decision; X S8; G3) | (a) never by default; model calls get author-filtered slices; Magnus's rows never in a slice; share bundles exclude them unless named · (b) free export | **(a) — ratify** (S §7.6). Note the honest boundary: *rows* are scoped; *artifacts and their prompts travel with the world* (X §6-8). |
| 16 | **Model changes: quiet or loud** (T open decision; S §1.8) | announce in character at the next report · silent swap | **Loud.** The identity-discontinuity evidence is unambiguous (T §"Research transfer"). |
| 17 | **Companion's memory of Magnus's chip requests** (T open decision #3) | count them (his scope, after ratification) · ignore them | **Count them, scoped, post-ratification.** Repeated requests are legible as such; they must never reweight Casey's builders (T §"Magnus at the controls"). |
| 18 | **Public GitHub repos** (C §Repositories) | create SI-Thor org repos now · stay local | **Casey's call alone** — the house rule is that creating them needs his go-ahead. Nothing in weeks 1–3 blocks on it. |

---

## 5. What we deliberately won't do yet — and why

1. **No live video streaming of the world.** "Thor renders, laptop is a
   television" is right for the morning and wrong for the day: you cannot
   navigate a Cycles render, and headless EEVEE on Jetson is unproven (P §3).
   NVENC's honest job is playback of pre-rendered truth — filmstrips,
   timelapses, branch clips (P §3 recommendation (c)).
2. **No OptiX.** There is no aarch64 OptiX SDK; Cycles builds CUDA-only at
   sm_110 (P §4 idea 16; RT ledger). Anything OptiX-shaped will not load.
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
    filled from this box only (3D §8; RT C7; X §4).
12. **No in-world client before the panels prove the loop.** The `[now]`
    surfaces carry M1–M4; the thin client is M5 and gated on measurements
    (D §8; S §6.2.10). The night feed, slate, report, board and library are
    complete products, not placeholders.
13. **No critic prompt before the reference set exists.** Otherwise
    "adversarial" is unfalsifiable (X §6-6).
14. **No camera-injection, OFA-deformer, 4×25 GbE or FP4-sizing work.** Wrong
    as framed on this devkit: no OFA node, no cameras, no populated cage; the
    2,070 TFLOPS is sparse-FP4 inference marketing, not a render figure
    (P §4 verdicts). The surviving kernels (thin client, day/night split,
    recipe-over-the-wire) are already in the plan.
15. **No silent CPU fallback, ever.** Environments assert CUDA + capability
    (11,0) at build time, because the failure is a quiet 10× slowdown, not an
    error (RT R2).

---

## 6. How we will know it's working

Two ledgers of measures — one for the experience, one for the machine — and
both are checked **at every milestone gate**, with the box's state recorded
beside every number (C; V §"Rules carried over").

### Standing gates (every milestone, no exceptions)

- The **kill -9 test**: every panel renders from the ledger alone (S §5.4; D §2).
- The **two-referent test**: an ambiguous order returns a question, not a plan (S §6.1b).
- The **seal-order invariant**: `prediction.sealed` committed before its render job enqueues (S §5.1).
- The **honesty sweep**: no verdict shown as colour without a word (G §5.2);
  no `[e]` presented as a promise; the report's status line is computed from
  heartbeats, not narrated (G §2).
- **Zero fabricated work**: the four-mornings suite (G §7 test 6).

### Experience measures (checked at each gate, from the spine's budgets)

| Measure | Budget | Source |
|---|---|---|
| First line after open (cold or return) | ≤ 2 s, with denominator | X S1/S2; G §7 test 1 |
| Chip lands (Casey or Magnus) | ≤ 1.5 s | X S3/S4 |
| Compile → confirm readable | ≤ 20 s / ≤ 5 s | X S6; D §4 |
| Slate transaction | ≤ 30 s, no cancel | X C13 |
| Peek join / card legible / stop | ≤ 5 s / ≤ 5 s / ≤ 2 s | X S9 |
| Report first paint / digest | ≤ 3 s / ≤ 2 min | X S10 |
| Branch flip / apply / re-stream | ≤ 2 s / ≤ 10 s / `[unmeasured: M5 spike]` | X S11; RS P14 |
| Keep-reject / "why?" / question answer | ≤ 2 s / ≤ 1 s / ≤ 2 s | S §4.1; X S13 |
| Decisions asked per morning | ≤ 10, cut named at the queue | G §4.3; X G6 |
| Cold-start questions per first session / by night 7 | ≤ 6 → 0 | G §1.9 |
| Attention hours per morning (the third number) | trending down | X G6; G §4.3 |
| Share-bundle defaults | no author-scoped rows, licence manifest first page | G §7 test 13 |

The experience measures are pass/fail: a milestone gate re-runs the session
script and the budgets together, because a moment that is honest but late, or
fast but fabricated, is equally a failure (D §"The three clocks"; X A11).

### Technical measures (the machine's growth beat, "The box" section of every report)

| Measure | Target / note | Source |
|---|---|---|
| Cycles CPU vs GPU, same frame | both timed from M0 onward; GPU must win | RT spike 1; P §7-1 |
| Hello Room / Hello World stage timings on aarch64 | recorded per stage; solver vs the paper's ~38 min (x86) | P §1, §7-2 |
| TRELLIS.2 wall-clock 512³ / 1024³; peak `MemAvailable` dip | fills the throughput table; props-per-night derived | RT spike 2; 3D §8 |
| Model-load count per night | 1 per model (the load cap) | P §6-5; RS P3 |
| Stage-cache hit rate per night | reported from M3 | P §6-2; RS P13 |
| Edit→preview p50/p95, batch vs warm; Blender starts per night | 1–2 starts; warm beats batch by the launch+I/O tax | P §6-1 |
| Peak RSS per warm scene / branch | decides resident branches and pre-baked options | P §7-3 |
| Critic FP/FN on the seeded reference set | inside the band before any verdict loses `@scripted` | X S6; RS P15 |
| Budget: lane-time spent vs bar, **the cut named**, hosted cents | `$0.00 (local)` until hosted is enabled | S §5.5; X C11 |
| Licence scan | no asset without a complete licence row incl. dependency terms | S §2.3.6; X R8 |
| Sustained power under MAXN; mode logged beside every timing | decides MAXN vs 120 W for nights | P §5, §7-6 |

**The one-sentence version of success**, borrowed from the corpus and kept as
the north star of this plan: *a night that was honest (the peek), legible (the
report), and cheap to decide on (the branch flip) earns the next evening's
plan* (D §4) — and the only thing that has to grow for that sentence to stay
true is the ledger (X §5 closing).

---

*End of plan. Sources: everything in `~/src/builder-ide/` as of 2026-10-30
(V, C, S, and all of `docs/research/`); the three documents named in the brief
as optional were not present when this was written and are marked where their
numbers belong. Synthesis only; no code outside this file; no sub-agents.*
