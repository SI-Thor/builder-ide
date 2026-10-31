# REVIEW — round 2: the core spec against the experience and the compute plan

Cross-review of `docs/design/core-spec.md` (the spec, written 2026-10-30) against
`docs/research/rev-ux.md` (the merged experience spine and reality check), `docs/research/split.md`
(the compute plan), and `docs/research/res-cad.md` (recipe vs USD, the scheduler), with
`docs/vision.md` as the frame. Read-only: nothing outside this file was changed; no sub-agents.

**Citation key.** **S** = `docs/design/core-spec.md` (section numbers); **X** = `rev-ux.md`
(spine moments are X §5 S1–S15; contradictions X §2 C1–C13; gaps X §3 G1–G10; reality check
X §4 R1–R20; its ux-trust self-review is cited as "X §6 n" to avoid colliding with the spine's
S-numbers; owner decisions X §7 D1–D6); **P** = `split.md`; **R** = `res-cad.md`;
**3D** = `res-3d.md` (cited directly where it supersedes R, as X itself ruled);
**V / D / T** = `vision.md` / `ux-day.md` / `ux-trust.md` (the spec's own shorthand).

**The one-line verdict.** The spec is strong exactly where round 1's merge was hardest —
work orders, sealed bets, branches, budgets, the two ledgers — and it already folded in several
round-1 resolutions (the interruption/narration split, no-repeat line rule, the money-rail
answer). It is weakest at the two seams this round was asked to test. First, the **referent
chain is broken in the middle**: the context packet carries world node ids, the recipe is keyed
by entry paths, and nothing in the spec maps between them — so the product's signature move
("Computer, make these sturdier") cannot compile from the packet as specified. Second, the
**interactive compute plan has no home**: the warm scene server, the recipe-hash stage cache
and partial regeneration — split.md's moves #1 and #2, the mechanisms that make the Workshop
clock physically possible — are absent from the spec's data model, scheduler records and build
order, and the night rail cannot express the one constraint all three technology documents say
the hardware actually imposes (model loads). The morning report also still carries the single
"prediction score 8/10" that X C2 explicitly killed.

---

## 1. Does the spec serve the experience?

### 1.1 The spine, walked

Every moment of X §5's 15-moment spine, run through S's data model and APIs.

| Moment (X §5) | Where it lives in S | Verdict |
|---|---|---|
| **S1** First night, empty ledger | The confidence gate (S §1.7: < 2 prior observations ⇒ no prediction) makes every builder silent on night one; nothing in S says what the Companion does instead, and no starter-choices surface exists | **Missing** (X G1) |
| **S2** The recognized return | Data exists (taste ledger, author scoping, `/v1/ledger/taste`, audit fold); but there is no "since your last session" summary endpoint, no owner last-seen notion, and no first-run honesty rule or test | Holds, with gaps |
| **S3** Point-and-say planning | `plan.chip` is a *stream* type (S §4.3) with no write path; `Task` exists only under a `night_` id (S §1.9) though chips and the slate exist from 20:47, before the night starts; the never-guess rule is specified for `/v1/call` only (S §3.1.2), not for chips | Holds, with gaps |
| **S4** Magnus's request | Author scoping (S §7.4) and no-free-text (S §7.10) are solid; but there is no chip-input endpoint (`/v1/call` takes an utterance from the owner client, S §4.2), and `/v1/branches/{id}/apply` is authorized "owner/panels" with no actor scoping | Holds, with gaps (X C7/C8) |
| **S5** The plan slate | Task rails, `/v1/budget`, `/v1/night` exist; `Task.rail` is a cap, not a *predicted cost*; the work-order ask is not shown as its own line anywhere | Holds, with gaps (X C11) |
| **S6** The one-line work order | S §3.1 is the best-covered moment in the spec: question XOR draft, ≤ 25-word spec-register confirm, Idempotency-Key, purged utterance, never-guess test in the slice (S §6.1b) | **Holds** — except the packet it compiles from is too thin (§1.2.1 below) |
| **S7** The handoff | `/v1/night`, detach-before-big-batches (S §3.2.2), and the line budgets already carry X C3/C4's merge (interruptions 1/20 min for blocked decisions/budget/hard failure; narrations ≤ 6/h, state-change only, no repeats — S §5.6) | **Holds** (timeout gap: §3.10) |
| **S8** The sealed bet | The loop and the load-bearing ordering are right (S §3.2.4; `prediction.sealed` committed before `job.enqueued`, S §5.1). Two holes: the night's automated keep/revert is never typed as a Critic *verdict* write distinct from a taste write (X C5/D1/D2), and the Critic itself has no calibration or selection path (X R4, X §6 6) | Holds, with gaps |
| **S9** The 2 a.m. peek | Log-not-stream, `since_seq` rewind, no fast-forward (S §4.3), kill -9 acceptance (S §5.4), stop endpoint (S §4.2) | **Holds** (note: the always-visible stop button needs an owner token from a surface that looks read-only) |
| **S10** The morning report | Static page over the ledger, failures lead (S §3.2.8) — but see §1.2.2: the single score survives, the status line and the cuts are absent | Fails the merge, with gaps |
| **S11** Branch flip and apply | Pointer move not re-render, options pre-rendered at the comparison rung (S §1.2), flip ≤ 2 s / apply ≤ 10 s (S §4.1) | **Holds** — but re-stream ≤ 15 s is missing from the budget list, candidate scene manifests are not pre-baked, and apply is not actor-scoped |
| **S12** Parked question / assumption | Park + one-tap answer (S §4.2, `q_` records); the conservative assumption is "recorded in the report" (S §3.2.6) but is not a record attached to the branch/card, and there is no event type for it | Holds, with gaps |
| **S13** "Why?" in one tap | Evidence + provenance (model id, weights repo+revision, prompt, seed, library versions), bundle openable ≤ 1 s (S §1.6, S §2.3.8) | **Holds** — add dependency terms (X R8; 3D §3) |
| **S14** The growth beat | Promotion is one transaction with the character notified (S §2.3), and `model.change.noticed` exists (S §1.8) | **Holds** (X C12's capability record is optional sugar — see patch 18) |
| **S15** Tally attached to the artifact | Per-claim-type records with verdicts exist (S §1.7) and the confidence gate already consumes per-type history; no read API for a card to fetch "14 of 18 on shadow counts" in one call | **Holds**, one endpoint short |

**Reading.** Twelve of fifteen moments are buildable on this spec today; the failures cluster
in the morning (S10) and the first session (S1), and the gaps cluster around *pre-night* state
(S3/S5) and the second author (S4). Nothing in the spine requires a redesign of S's core —
the fixes are additions, mostly to §1.4, §1.9, §3.2.8 and §4.2.

### 1.2 The three the brief names

**1.2.1 The context packet vs "make these sturdier".** V §"Calling the computer in-game"
specifies the packet's history as "the last recipe changes, **renders** and critic notes" —
S's `History` (S §1.4) has `recipe_changes`, `critic_notes` and `work_orders_open`, but
**renders were dropped**. Worse, the 07:26 moment (D §3; X S6's morning sibling) cannot be
compiled from the packet as specified at all:

- The utterance "these sturdier, but keep the sway" is a **delta on parameters** — raise
  `load_factor`, leave `sway` at 0.22. The packet carries `view.selection` as node ids
  (`span_south`) and the compiler's referent resolution is "deterministic: node ids,
  distances, part names" (S §3.1.1) — but the recipe is keyed by **entry paths**
  (`structure.south_span`, S §1.1), `WorkOrder.targets` holds *node ids* (S §1.3), acceptance
  checks reference *paths* (`structure.south_span.params.load_factor`, S §1.3's example), and
  edit ops are paths (S §1.1). **No node-id ↔ entry-path registry exists anywhere in the
  spec.** The chain view → referent → recipe entry → params → acceptance check is broken
  between its second and third links.
- The packet carries no parameters, so "keep the sway" has nothing to keep: the compiler
  would have to fetch the recipe separately — possible for the engineer (MCP `recipe.get`,
  S §2.5) but the *compile* step that writes the goal and acceptance checks is not the
  engineer and is specified to receive only packet + utterance (S §1.4: "the packet is the
  *only* situation data that crosses into a model prompt").
- D §3 (07:26) explicitly compiles from "selection + camera + **last night's WO-14
  evidence**"; S's `History.work_orders_open` shows only *open* orders — the landed-and-kept
  WO (the reason the bridge exists, and its 2.3× result) is invisible to the compiler.

Fix (patch 1): a node registry maintained by the engine/compiler (node id → entry path,
kind, asset refs), `View` gaining resolved referents `{node_id, entry_path}`, a bounded
params block for selected entries, `History` gaining renders (artifact refs) and recent
landed/kept WO outcomes touching the referents. The 16 KiB cap survives with the bounds
table amended.

**1.2.2 The morning report's data.** S §3.2.8 has most of the merged report (failures lead,
filmstrip from cached renders, three branches, one-tap questions, landed WOs, model-change
notices, lost time, per-claim-type tallies with denominators). Three things fail or are
missing:

1. **The single score survived.** The night line still reads "… · prediction score 8/10
   (was 7)" (S §3.2.8) — the exact number X C2 calls "the one number both reports must
   kill" ("a single accuracy number per builder is theatre"). The per-claim-type lines
   appear later in the same section; the headline contradicts them.
2. **No status line.** X D6/G2 make a mandatory first line — `ran as planned | ran short |
   ran degraded | did not run` — with a one-line reason in the last case, distinguishing
   "queue empty" from "GPU busy with something else" from "machine off" from "client never
   detached". S has none of these states, and cannot state the fourth because client
   presence is not recorded anywhere (see §3.10).
3. **The cut is not shown.** X C11: a report that says "5.3 of 5.5" without naming the work
   that was dropped (and any wall-clock overrun) is the most dishonest-looking artifact in
   the set. Showing the cut requires the *ask* to be stored — which needs predicted costs
   on tasks and WOs (S has caps in `Rail`, not predictions; `Job.cost_estimate` exists,
   `Task` has none).

Also missing, smaller: parked-question triage (top three + "31 more, none blocking",
X G8), the assumption sitting on the same card as the question it replaced (X S12), and a
"nothing landed / start over" option in the branch set (X G7 — cheap, since rejection is
already a branch purpose, S §1.2).

**1.2.3 Branch flips in ≤ 2 s.** The flip itself is sound: options are branches pre-rendered
at the comparison rung, so flipping is a viewer over cached artifacts, and apply is a
fast-forward pointer move (S §1.2, S §4.1). Two gaps break the moment's tail:

- **Re-stream ≤ 15 s is not in the spec.** S §4.1's budget list stops at "apply ≤ 10 s".
  The re-stream needs each candidate's *compiled scene manifest* (not just comparison
  renders) to exist before the owner chooses — nothing schedules that pre-bake. S §6.2.3's
  compiler plus the `usd-cache/` layout (S §1.0) are the right bones; the night just has to
  run them per morning-option.
- **No delta channel.** P §2.3-4/§3 make edits ≈ KB over the wire with per-edit < 100 ms,
  against a 10–100 MB initial LOD scene on measured 2.4 GHz Wi-Fi. S's
  `/v1/world/scene?branch&LOD` (S §4.2) is a whole-manifest fetch; `world.dirty` (S §4.3)
  re-streams everything. Day-side building needs `since_version` deltas or the wire budget
  is blown by lunchtime.

### 1.3 Cross-cutting gaps the walk exposed

- **Cold start (X G1).** The confidence gate means night one has no predictions, no
  tallies, and — as specified — no voice. X's fix is ask-mode ("deep joints or flush?" as a
  two-chip choice recorded as a taste note) and a first-morning line that frames low N
  honestly. The spec's slice (S §6.1) starts with an empty ledger and never tests the
  first-run line D §1 requires ("first line must contain 'first' and no invented fact").
- **The slate has no pre-night home.** Chips appear at 20:47, the slate is negotiated at
  21:02 (D §1), the night starts at 21:14. `Task.night` requires a night id (S §1.9) and
  `/v1/night` POST is "start the night (slate → queue)" (S §4.2) — so where do chips and
  the negotiated bar live between 20:47 and 21:14? Underspecified, and the budget
  negotiation ("builders cut their own lists first") has no API to cut against.
- **Magnus's channel.** Input: `Origin.channel` includes "chip" (S §1.3) but no endpoint
  accepts chips and nothing refuses free text *by actor class* in code (S §7.10 states the
  policy; T/rev-ux want it structural). Authority: X C8 gives Magnus preview-keeps and
  question-answers but reserves branch applies for Casey; S's apply endpoint cannot express
  that.
- **Taste export/erase is promised with no mechanism.** S §1.7: Magnus's rows are
  "exportable and deletable in one action each" — but `/v1/ledger/taste` is GET-only
  ("never writable via API", S §4.2) and the audit log is the append-only source of truth
  (S §1.0). Deletion needs a design (tombstone event + filtered projection), or the
  privacy promise is decoration (T §"The privacy boundary"; X S8).
- **The Critic is unchosen and uncalibrated.** The merge gate's step 5 and the whole night
  loop lean on the critic; X R4 names it "the largest unchosen dependency in the whole
  stack" and X §6 6 supplies the missing acceptance: a fixed reference set (~30 renders
  with seeded defects), false-positive/false-negative rates, a target band. S has a demotion
  path (S §1.9) but no selection path, no calibration gate, and no spike line for it.

---

## 2. Does it match the compute plan?

Where each of P's mechanisms lives in S today, and what must change.

### 2.1 The warm scene server — **absent**

P §2.3-1 and P §6 move #1: a resident Blender process owning the open scene, killing the
per-task bpy relaunch and `scene.blend` round-trip; "the difference between the workshop
clock and batch latency". In S there is nothing: it is not a `Job` (it never completes), not
a model-registry tier (S §1.9's hot/warm/cold are model weights), not an endpoint, not in
the build order (S §6.2), not in the crash model (S §5.2's "does not survive" list covers
GPU-resident models but not scene processes). Without it, S §4.1's Workshop budget (≤ 60 s
previews) and S §7.8's interactive-previews decision have no mechanism — batch Infinigen
pays a full engine restart per edit (P §1).

What must change (patch 4): model it as a **scheduler-managed resident resource** —
lifecycle `scene.loaded / scene.evicted` audit events, residency bound per branch (P §7-3:
peak RSS per warm scene decides how many worlds/branches stay resident in 122 GB, hence how
many pre-baked morning options exist), eviction policy, and one hard rule that keeps S's
architecture intact: **it is a derived cache, never a writer** — rebuildable from recipe
version + stage cache, listed in S §5.2 among what does not survive a reboot.

### 2.2 The stage cache keyed by recipe hash — **half-present, key contract missing**

S already has the substrate: content-addressed artifacts (S §1.0), job dedup by
`hash(request + attempt)` with converging outputs (S §5.3), and `usd-cache/` per
(recipe version, profile). What P §2.3-3 adds is the stage-level cache — key =
`hash(recipe ⊕ gin config ⊕ stage_name ⊕ deps' keys)` — and here S has a hole that is also
a correctness issue: **the gin config is not pinned anywhere.** `EnginePin` (S §1.1) pins
repo/commit/blender/python only. If engine-side configuration can drift, then (a) the cache
key is not a function of the recipe version, so identical recipes can miss and divergent
configs can hit; (b) S §5.3's "a re-run that reproduces converges on the same artifact" is
defeatable; (c) the merge gate's deterministic rebuild (S §2.3.1) passes against a cache
that was built under different engine settings than a fresh rebuild would use. Pin the
config (hash in `EnginePin`), require the stage-cache key ⊆ (recipe version hash, engine
pin, stage name), and report the hit rate per night (P §6-2's measure). Patch 13.

### 2.3 Partial regeneration — **implied, never contracted**

S assumes it: entries are "independent by construction", merges are entry-granular (S §1.2),
edits are op lists on entry paths (S §1.1). But the engine-side contract is never stated:
applying an edit must re-evaluate only the **dirty set** — the touched entries, plus entries
containing constraint references that overlap the touched nodes (the oak's drip line crosses
terrain and props; S §1.1's project constraints are exactly the cross-entry couplers), plus
asset consumers. P §2.3-2's hooks (room-scoped re-solve, placeholder-scoped swap) are engine
work, but the *spec* must state the contract because the preview ladder (S §2.3.3) and the
Workshop clock depend on it. Also missing: **solver placement** — P §2.1's rule that
room-scoped re-solves are the only day-clock solver work and full solves are night jobs,
full stop (the solver is ~38 min on x86 and likely worse on 2.6 GHz ARM, P §1/P §7-2).
S §7.8 resolves preview-vs-batch but says nothing about the solver. Patch 13/19.

### 2.4 Ghost/LOD export and the wire — **bones present, deltas and pre-bake missing**

`/v1/world/scene` per (branch, LOD), the deterministic compiler (S §6.2.3), `world.dirty`
(S §4.3), and "previews render on the client's own GPU" (S §4.3) all match P §3's
recommended hybrid (state by day, encoded pixels on demand) and V §"The pieces" #8.
What must change: the delta channel and morning-candidate pre-bake (§1.2.3 above); glTF
named as the near-term wire since the spike's bpy builds with `WITH_USD=OFF` (P §2.3-4);
pre-encoded clip artifacts (NVENC, P §3) so the filmstrip is actually 60 fps-class; and the
8 s / 12 s / 15 s numbers marked measurement-gated (X R1: no stream time has been measured
by anyone). Patches 14.

### 2.5 The night lanes — **faithful to R §9, missing the load cap, Orin and the power plan**

S §1.9's registry and S §3.2.3's lane layout adopt R §9 essentially verbatim (CPU lane
never waits on GPU; GPU drains model-by-model in dependency order; critic interleaved;
provenance stamped by the scheduler — S §1.6). Four changes:

1. **The per-model-load cap.** R §9 names the real constraint ("GPU compute-time and
   **weight-swap thrash**"); X C9/D5 and X §6 1 make the enforceable unit "one loaded
   model × N prompts" and demand a thrash rail; P §6-5 measures "model-load count per
   night (target: 1 per model)". S's `Rail` is (gpu_minutes, hosted_cents, wall_minutes)
   (S §5.5) — none of these can express a load count, and S §7.8's swap budget exists only
   for the *day*. At night, nothing stops a scheduler bug from loading the texture stack
   forty times while staying under every rail. Add a per-model load budget per night to the
   registry policy and make batch *admission* (not spend) the enforced point — X R6's
   mapping: at 80% stop opening new batches and drain. Patch 3.
2. **Orin.** P §2.2 assigns the Orin CPU-lane overflow and a "watchtower" (budget/queue
   monitoring, OOM/fallback judgments). S is Thor-only and single-writer (S §1.0, S §4.1);
   `Job` has no `worker` field. CLAUDE.md says Orin is "spare; ask before using". Either add
   `Job.worker` + a worker registry (the claim-token/lease design in S §1.9 already
   generalizes), or make Orin an explicit non-goal for now. The watchtower, if it ever runs
   off-box, must be read-only/alerting — a second writer would break S §1.0. Patch 17.
3. **Power modes.** P §5: "the core service should own them [nvpmodel switches] as part of
   the night queue's begin/end (and log the mode beside every timing)" — the carried-over
   "measure with the box's load beside the number" rule (V). S never mentions power mode.
   Patch 16.
4. **Client presence.** "The scheduler waits for client detach" (S §3.2.2, P §2.2) requires
   the core to *know* attach/detach as a durable fact — it is also the input the report's
   "did not run" reason needs (§1.2.2). No `client.*` events exist (S §1.8). Patch 10.

---

## 3. Contradictions among the documents

Ordered by damage if left unresolved. Each carries a recommendation.

### 3.1 The report's headline number — S §3.2.8 vs X C2

S's night line includes "prediction score 8/10 (was 7)"; X C2, with T's evidence ("a single
accuracy number per builder is theatre"), explicitly kills it and replaces it with
per-builder per-claim-type lines with denominators — which S §3.2.8 *also contains*, later
on the same page. The spec contradicts its own §1.7, whose `claim_type` exists precisely to
prevent one-number summaries.
**Recommendation:** delete the score from the night line; the tally block (already
specified) is the replacement. Patch 2.

### 3.2 The report's first line — S §3.2.8 vs X C2/C11/D6/G2

S leads with the night line (after "failures lead"); X's merge requires status line →
failure line → numbers, with the *cut* named and any wall overrun disclosed in the same
line ("a report that shows '5.3 of 5.5' without naming the 1.7 h that was dropped is the
single most dishonest-looking artifact in either report"). S cannot comply today: it stores
caps, not asks (no `Task.cost_estimate`), and has no night-status taxonomy.
**Recommendation:** add the four-value status line, store predicted costs at slate time,
and require the first content line to state what was cut and any overrun. Patches 2, 11.

### 3.3 Night rail units — S §5.5 vs X C9/D5/R6, R §9, P §6-5

S answered T's money-rail question with a three-axis rail and a measured cost table — good,
and the cost table answers X R5's "no per-job cost model" objection. But all three
technology-side documents agree the *hardware* constraint is weight-swap thrash, and S's
rail cannot count loads (§2.5.1 above). Day has a swap budget (S §7.8); night — the
batched case the constraint is actually about — has none.
**Recommendation:** keep the three-unit rail for owner display and enforcement of spend;
add a per-model load cap per night to the registry policy, enforced at batch admission;
wire the 80% graduation to "stop opening new batches, drain the current one" (X R6).
Patch 3.

### 3.4 "The sim" — S §1.3/§2.3.4 vs X R11

S's acceptance story for the bridge is "load factor from the sim" and "rope snapped in sim"
(S §2.3.4, S §1.3 `Attempt.outcome`). X R11: no physics engine is adopted anywhere in the
document set; R §6's SimReady gives schemas, not a solver; 3D §6 keeps CAD on parametric
code for exactly this reason. As written, the spec's flagship acceptance check depends on a
component nobody has chosen.
**Recommendation:** define `load_floor` constraint checks as **scripted analytic
computations** (build123d mass properties / member forces from the recipe's parameters,
run on the CPU lane — deterministic and recipe-native, R §1); rename the sim language. If a
real solver is ever wanted, that is an engine decision with its own work order. Patch 5.

### 3.5 The critic OOM row — S §1.9/§3.3 vs X R17

S keeps D's "critic OOMs in a big texture batch" verbatim (S §3.3). X R17: on a 122 GB
unified box with every model under ~10 GB (R §9), OOM is the wrong row — the failure the
night will actually have is **contention/thrash**, whose recovery is queue delay plus a
report line, not a degraded verdict; and a `verdict@low-res` degrade is a silent quality
change that belongs on the evidence card, not only in a log line.
**Recommendation:** keep the demotion path as defence in depth; add the thrash/stall row;
require the `degraded` flag on the evidence card itself (S §1.3's `Evidence.summary` and
§2.3.8's bundle), not just the report. Patch 7.

### 3.6 The prop/texture stack — S §6.2.7 vs X §7's closing ruling (3D superseding R)

S §6.2.7 builds the generative stations on R §2/§3: "modly headless backend with TripoSG
(mesh-only first, rembg workaround planned), StableMaterials + SDXL …, textures deferred
past the spike". X §7 closes with the opposite ruling, on evidence S never saw: the
prop-maker stack is **TRELLIS.2 via the ComfyUI native path plus TripoSR as baseline** —
MIT code *and* weights, real PBR, no compiled CUDA extension (removing R's "one genuinely
heavy item", the texture source builds), and TRELLIS.2's shape-conditioned texturing covers
the texture role in the same environment (3D §4.1/§4.8) — so "textures deferred past the
spike" is obsolete. X also flags this "changes what the phase-1 spike measures".
**Recommendation:** update S §6.2.7 to the TRELLIS.2-native stack (keep modly's
FastAPI/MCP *pattern*, 3D §4.3), add 3D to S's citation list, and note the spike measures
TRELLIS.2 on-box. Patch 12.

### 3.7 One venv per seat vs one environment per model family — S §2.2.3 vs 3D §1/§6, X R16

S builds each seat as "a fresh `uv` venv from the project lockfile" — one environment.
3D §1: "each model family wants its own environment" (TRELLIS.2 answers with a py3.10 conda
env; cp312 pins collide); X R16 therefore requires every work-order estimate to carry two
lines — "build/verify: X" and "generate/test: Y" — because "a work order that must build a
py3.10 conda environment before its first render is a different three hours". S's
`hosted_cents`-style honesty about cost does not yet extend to provisioning time.
**Recommendation:** per-family environments pinned in the model registry; seats materialize
the family env the order needs; WO budgets and confirm lines show build-vs-generate
separately. Patch 12.

### 3.8 Cache key inputs — P §2.3-3 vs S §2.3.1/§5.3

P's stage-cache key includes gin config and dep-keys; S pins neither (§2.2 above). If the
key can vary under a fixed recipe hash, S's determinism guarantees (byte-identical CAD,
converging re-runs, clean-worktree rebuild) are all defeatable by config drift.
**Recommendation:** pin engine config in `EnginePin`; cache key ⊆ (recipe hash, engine pin,
stage). Patch 13.

### 3.9 Batch start on detach only — S §3.2.2 / P §2.2 vs X R19/G2

Both S and P gate the big batches on client detach; X R19 names the failure ("if the client
never detaches, the big batches never run, and the morning must say so") and recommends a
timeout fallback; X G2 requires the report to distinguish that morning from an empty queue.
S has neither the timeout nor the telemetry to explain it.
**Recommendation:** start big batches on detach *or* a timeout (e.g. 30 min after
`night.started`), and record client attach/detach so the report can name the reason.
Patch 10.

### 3.10 Magnus and `/v1/branches/{id}/apply` — S §4.2 vs X C8/D4

D §3 has Magnus applying branch C in 9 s; X C8 overrules: a branch choice is a recipe
pointer — a real edit — so Magnus proposes and Casey confirms (preview-keeps and
question-answers are his). S's apply endpoint is authorized by token class only
("owner/panels"), and its token classes (S §4.1) have no actor notion, so a Magnus holding
an owner token can repoint the world's recipe with no confirm.
**Recommendation:** actor-scoped apply: a kid actor's apply creates a proposal event
requiring an owner confirm; same for `/v1/call` (chips accepted, free text refused by actor
class, in code — S §5.6's own "prompt instructions are not enforcement" principle applied
to §7.10). Patch 8.

### 3.11 Who writes the night's keeps — S §3.2.4 vs X C5/D1/D2

X's most consequential round-1 resolution: three record types, one writer each —
`taste_note` (owner only), `prediction` (builder, sealed), `verdict` (Critic, defects) —
and the night's automated keep/revert is a **verdict** write, never a taste write, or "the
taste model trains on its own output" and the sealed bets become unfalsifiable. S has the
pieces: taste notes are owner-verdict-only (S §1.7), the Critic writes `critic.verdict`
(S §1.8), the night loop "keeps or reverts" on branches (S §3.2.4). But S never joins
them, and two consequences are unspecified: (a) the night's keep must not resolve a
`taste_keep` prediction (the owner scores those); (b) the owner's morning branch
apply/keep/reject *should* resolve any outstanding `taste_keep` predictions on that branch
— S's apply flow (S §1.2, §4.2) says nothing about prediction scoring.
**Recommendation:** one paragraph in S §1.7/§3.2 stating the three-writer rule and both
resolution rules. Patch 6.

### 3.12 Watertightness before the critic — S §2.3.4–5 vs X R10

X R10's note: the crates-7-and-11-hollow failure is exactly the "typically not
watertight" failure R §2 warns of for image-to-3D, so "the night must schedule a
watertightness check **before** the critic, not after". S's pre-critic checks are
constraint checks whose kinds are keep_clear | load_floor | reachability | budget_custom
(S §1.1) — no geometry-defect kind exists; watertightness first appears implicitly inside
the critic's own judgement (S §2.3.5).
**Recommendation:** add a mechanical geometry check (watertight/manifold/scale) to the
pre-critic rung — as a constraint kind or a fixed gate step. Patch 7.

---

## 4. Patch list

Concrete edits to `docs/design/core-spec.md`, ordered by importance.

| # | Section | Change | Reason |
|---|---|---|---|
| 1 | §1.4 (+ §1.0, §3.1) | Add the **node registry** (node id ↔ recipe entry path ↔ kind ↔ assets), maintained by the engine/compiler; extend `ContextPacket`: resolved referents `{node_id, entry_path}`, bounded current params of selected entries, `History.renders` (artifact refs, capped), recent landed/kept WO outcomes touching the referents; amend the bounds table | V's packet includes renders, which S dropped; "make these sturdier" (V, D §3 07:26) is a param delta the packet cannot express; targets are node ids while acceptance checks are entry paths — the referent chain is broken (§1.2.1) |
| 2 | §3.2.8 (+ §0 row 3) | Report: delete "prediction score 8/10 (was 7)" from the night line; add the mandatory status line (`ran as planned / ran short / ran degraded / did not run` + one-line reason); first content line names what was cut and any wall overrun; parked questions triaged top-3 + count; assumptions render on the same card; branch set gains a "nothing landed" option | X C2 (the killed number), X D6/G2 (status line), X C11 (the cut), X G7/G8, X S12 |
| 3 | §1.9, §5.5 | Add a **per-model load cap per night** to the model registry policy; enforce at batch admission; map 80% graduation to "stop opening batches, drain current" | R §9 + X C9/D5/R6 + P §6-5 all name weight-swap thrash as the real constraint; the three-axis rail cannot count loads; day already has a swap budget (§7.8), night has none (§3.3) |
| 4 | §1.9, §5.2, §6.2 | Add the **warm scene server** as a scheduler-managed resident resource: `scene.loaded/evicted` events, per-branch residency bound, eviction policy, "derived cache, never a writer, rebuildable from recipe + stage cache"; add to §5.2's does-not-survive list; slot it in §6.2 before the USD compiler | P §2.3-1 / §6 move #1 — the mechanism behind the Workshop clock (≤ 60 s previews, §4.1) and S §7.8's day-preempt decision; currently absent everywhere (§2.1) |
| 5 | §1.3, §2.3.4 | Replace "from the sim" acceptance with **scripted analytic checks** (constraint kind `load_floor` = deterministic build123d computation from recipe params, CPU lane); purge "sim" language from §1.3/§3.1 examples | No physics engine exists in any source (X R11); SimReady is schemas, not a solver (R §6) |
| 6 | §1.7, §3.2 | State the three-writer rule: night keep/revert = Critic `verdict` writes on branches (+ audited branch ops), never `taste.note.appended`; `taste_keep` predictions resolve only on owner keep/apply/reject — and the apply flow resolves them | X C5/D1/D2 — left implicit, the taste model trains on its own output (§3.11) |
| 7 | §2.3, §3.3, §1.9 | Add a mechanical **geometry check (watertight/manifold/scale) before the critic** at each rung; add the thrash/stall failure row alongside (not instead of) critic demotion; require the `degraded` flag on the evidence card, not only the report | X R10 (hollow crates are the known failure mode), X R17 (OOM is the wrong row on 122 GB) |
| 8 | §4.1, §4.2, §7.10 | Magnus: chip-input path on `/v1/call` (chips in, free text refused **by actor class, in code**); actor-scoped `/v1/branches/{id}/apply` — kid applies become proposals pending owner confirm | X C7/C8/D4; S's token classes carry no actor, so the privacy and authority rules are policy, not structure (§3.10) |
| 9 | §1.7, §4.2 | Give taste export/erase a mechanism: compensating tombstone events + filtered projections + an owner endpoint (`POST /v1/ledger/taste/erase {author}`, `GET …/export`); append-only source of truth preserved via the fold | S §1.7 promises one-action export/delete; the API is GET-only and the audit fold makes deletion undefined (§1.3) |
| 10 | §1.8, §3.2.2 | Add `client.attach`/`client.detach` events; big batches start on detach **or timeout** (~30 min); the report's "did not run" reason can then distinguish "client never detached" | X R19/G2; detach-gating is load-bearing but client presence is unmodelled (§3.9) |
| 11 | §1.9, §4.2 | Pre-night slate: intentions/chips as first-class records before any `night_` id exists; `Task.cost_estimate` (ask, not just rail caps); the slate shows work-order ask as its own line; `Task.author` + kid-queue end-hour | X C11/S5, X G10 (two queues, one lane, Magnus's fixed hour); S §3.2.8's cut-disclosure needs the stored ask (§1.2.2) |
| 12 | §6.2.7 (+ header citations, §0) | Generative stations: **TRELLIS.2 via ComfyUI native + TripoSR baseline** (textures via TRELLIS.2's shape-conditioned texturing — not deferred); per-model-family environments from the registry (py3.10 conda where needed); WO estimates and confirm lines split "build/verify" vs "generate/test"; add 3D to the citation list | X §7's closing ruling (3D supersedes R §2–§3); X R16; changes what the phase-1 spike measures (§3.6–3.7) |
| 13 | §1.1, §2.3.1, §5.3 | Pin engine-side config (gin/config hash) in `EnginePin`; require stage-cache keys ⊆ (recipe version hash, engine pin, stage); report stage-cache hit rate per night; state the partial-regeneration **dirty-set contract** (touched entries + crossing constraints + asset consumers) and the solver-placement rule (room-scoped by day, full solves at night) | P §2.3-2/§2.3-3; without the pin, deterministic rebuild and job-dedup convergence are defeatable by config drift (§3.8) |
| 14 | §4.1, §4.2, §6.2.3 | Add re-stream ≤ 15 s to the budget list; add a `since_version` delta mode to `/v1/world/scene` (KB-class edit deltas); nightly job pre-bakes each morning-option's compiled LOD manifest; note glTF-first (spike's bpy has `WITH_USD=OFF`); add pre-encoded clip artifacts (NVENC) for the filmstrip; mark 8 s/12 s/15 s as measurement-gated | D §4 moment 8 / X S11; P §2.3-4/§3 (edits ≈ KB vs 10–100 MB initial scene); X R1 (stream times unmeasured) (§1.2.3) |
| 15 | §1.9, §2.3, §6.1 | Critic selection + calibration: reference set of ~30 renders with seeded defects, FP/FN target band, a gate on entering service; a spike line in §6.2; the slice's local critic states its band | X R4 ("largest unchosen dependency"), X §6 6 ("without this, 'the critic passes it at 2× load' is a vibe") |
| 16 | §1.7, §5.5, §1.9 | Sealed payload includes the intended render spec (rung/resolution/seed), not just branch_ref — so a verdict is re-scorable against the same inputs; night start/stop set and log the power mode; timings record the mode beside the number | X R7 (seal the recipe tuple, not just a branch hash); P §5 (the core owns nvpmodel and logs mode beside timings) |
| 17 | §6.1, §6.2 | Cold start: ask-mode for the first N decisions (two-chip choices recorded as taste notes); first-morning framing line ("You chose 4 of 6 — a start"); add the clear-ledger first-run test to slice acceptance | X G1/S1 — the confidence gate silences everyone on night one and S never says what happens instead (§1.3) |
| 18 | §1.6, §4.2 | `Licence` carries dependency terms from the registry (e.g. "MIT weights, DINOv3 encoder terms apply"); asset-library "regenerate" with a *different* model is labelled **"reinterpreted"**, not regenerated; optional: capability claims cite `vocab.call` counts (word use history) as their basis | X R8/R9, 3D §3 (dependency licences ride with MIT weights); X C12 (capability records) |
| 19 | §1.9 | Orin: either add `Job.worker` (default `thor`) + a worker registry, or write Orin into non-goals for now; any off-box watchtower is read-only/alerting | P §2.2 plans Orin overflow + watchtower; S is Thor-only and single-writer; CLAUDE.md requires asking before using the Orin (§2.5.2) |
| 20 | §4.2 | A tally read API (per builder × claim_type, with denominators, recency-weighted) so S15's ledger line is one call on any card; note verdicts-as-words (not colours) as a panel rule | X S15, X G5 (accessibility minimum: every verdict is a word) |

**What not to change.** S §5's durability design (audit-as-checkpoint, §7.7), the recipe-vs-USD
one-way rule (§7.11, adopting R §8 verbatim), the sealed-before-render ordering (§5.1, which
X R7 finds *strengthened* by 3D §5), the branch/pointer-move model (§1.2), and the
interruption/narration budgets (§5.6, already the X C3/C4 merge) all survive this review
unchanged — cite them as settled when the patches land.

---

## Appendix — scope and compliance

**Read, in full:** `docs/design/core-spec.md` (S), `docs/research/rev-ux.md` (X),
`docs/research/split.md` (P), `docs/research/res-cad.md` (R), `docs/vision.md` (V);
for verification of S's citations and X's rulings: `docs/research/ux-day.md` (D),
`docs/research/ux-trust.md` (T), `docs/research/res-3d.md` (3D), `CLAUDE.md`.
**Not used as evidence:** `casey-ideas-fromgoogle5.md` (triaged inside P already),
`docs/rnd-plan.md`.

**Read-only compliance:** no file outside this directory (`~/lm-wt/rev-spec/`) was created,
edited or deleted; the documents reviewed are byte-identical to how they were found. No
sub-agents were started. Everything here is design review; no code was written or run.
