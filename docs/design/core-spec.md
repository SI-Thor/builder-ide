# SPEC v2 — the core service of builder-ide

Status: design for implementation, **version 2** (2026-10-30). v1 is
`docs/design/core-spec.md`; this file supersedes it. Scope is unchanged: the
durable service on the Thor that owns **work orders, budgets and approvals, the
recipe store and its history, the model scheduler, the vocabulary, and the audit
log** (V, "The architecture: three layers"). Characters, engineers (coding and
generative agents behind one adapter) and front ends (ProArt in-world client,
Theia, Zed via ACP, web panels) plug into it; none of them own state.

Everything here is buildable with plain Python 3.12 on the Thor (FastAPI +
SQLite + Pydantic v2); no orchestration framework is adopted (§7.7).

**Citation shorthand**

- **V** = `~/src/builder-ide/docs/vision.md`
- **D** = `docs/research/ux-day.md` (ideation A; sections cited by in-fiction time)
- **T** = `docs/research/ux-trust.md` (ideation B; sections cited by name)
- **R** = `docs/research/res-cad.md` (sections cited by number)
- **X** = `docs/research/rev-ux.md` (the experience cross-review; items cited
  as C1–C13 contradictions, G1–G10 gaps, R1–R20 reality checks, S1–S15 spine
  moments, D1–D6 owner decisions, §6 self-review)
- **RV** = `docs/research/rev-spec.md` (round-2 review of v1; patch numbers)
- **P** = `docs/research/split.md` (the compute plan; sections by number)
- **G** = `docs/research/gaps.md` (the designed gap moments; sections by number)
- **3D** = `docs/research/res-3d.md` (3D-generation research; sections by number)

**Timing markup** (adopted from G's preamble, which makes X §4's rule a
convention): `[b]` marks a latency **budget** the UI must meet and a test can
check; `[e]` marks an **estimate** that did not come off this box and is not a
promise (X R1, quoting 3D §8: "fill in the scheduler's throughput table from
measurements on this box").

Where the sources disagree or explicitly defer a decision, this spec chooses and
says why; the summary is §0 and the reasoning is §7.

---

## Changelog against v1

Every patch in RV §4's list is **applied** — none declined. Two are applied as
a chosen variant, flagged below. Besides the patches, v2 integrates the compute
plan (P) into the data model and lifecycles, and specifies the gap states G
designed (the busy/dark box, the reboot, the absent client) plus cold start and
Magnus's first session.

| RV patch | Disposition | What changed in v2 |
|---|---|---|
| 1 — node registry / referent chain | Applied | New §1.4.0 node registry (node id ↔ entry path ↔ kind ↔ assets), maintained by the engine/compiler; `View` gains resolved referents and bounded current params; `History` gains renders and landed/kept WO outcomes touching the referents; bounds table amended; §3.1 compile walks the now-unbroken chain view → referent → entry → params → acceptance |
| 2 — the morning report's data | Applied | §3.2.8: the single "prediction score 8/10" is deleted; mandatory computed status line (`ran as planned / ran short / ran degraded / did not run` + reason); first content line names what was cut and any wall overrun; kept-counts split critic-keeps vs owner-keeps; parked questions triaged top-3 + count; assumptions render on the same card as the question they replaced; branch set gains the standing options keep-yesterday and back-to-plan |
| 3 — per-model load cap | Applied | §1.9 model-registry policy gains `loads_per_night` per model (default 1); enforced at batch **admission**; the 80% graduation becomes "stop opening batches, drain the current one"; night line reports model-load count (§5.5) |
| 4 — warm scene server | Applied | §1.9 gains a scheduler-managed **resident resource** (lifecycle `scene.loaded/evicted`, per-branch residency bound by peak RSS, eviction policy, "derived cache, never a writer, rebuildable from recipe + stage cache"); added to §5.2's does-not-survive list; slotted in §6.2 before the USD/glTF compiler |
| 5 — no "sim" | Applied | `load_floor` and friends are **scripted analytic computations** (build123d mass properties / member forces from recipe params, CPU lane, deterministic — R §1); "sim" language purged from §1.3, §2.3, §3.1 (X R11: no physics engine exists in any source) |
| 6 — three writers | Applied | §1.7 states the three-record rule (taste_note = owner only; prediction = builder, sealed; verdict = Critic, defects); the night's automated keep/revert is a **verdict** write, never a taste write; `taste_keep` predictions resolve only on owner keep/apply/reject, and the apply flow resolves them (§1.2, §3.2.4) |
| 7 — geometry check, thrash row, degraded on the card | Applied | §2.3 gains a mechanical **geometry check (watertight/manifold/scale) before the critic** at each rung; `Constraint.kind` gains `watertight`/`scale_bounds`; §3.3 gains the stall/thrash row alongside (not instead of) critic demotion; the `degraded` flag rides the evidence card (`verdict@low-res` / `verdict@scripted`), not just the report |
| 8 — Magnus structural | Applied | Tokens carry an actor (§4.1); `/v1/call` accepts chip input and refuses free text **by actor class, in code**; `/v1/branches/{id}/apply` is actor-scoped — a kid apply creates `branch.proposed`, pending owner confirm; Magnus's first three keeps are `pending_ratification` and inert (§1.7); his lane is a reserved slice capped by a fixed hour (§1.9, §3.2) |
| 9 — taste export/erase | Applied | Mechanism specified (§1.0, §1.7, §4.2): owner-initiated erase = one transaction that redacts the author's taste-event payloads and appends a `taste.erased` compensating event; projections rebuilt by the fold exclude them; `GET /v1/ledger/taste/export`, `POST /v1/ledger/taste/erase` |
| 10 — client events + timeout | Applied | `client.attach`/`client.detach` event types; big batches start on detach **or a deadline** (default 30 min after `night.started`, owner-settable, shown in the pre-flight); the report's "did not run"/"ran degraded" reasons can name "client never detached" (§3.4) |
| 11 — pre-night slate | Applied | `Task` exists before any `night_` id (`night` optional, state `slated`); `Task.cost_estimate` stores the **ask** (not just rail caps); `Task.author` + kid-lane `ends_at`; the slate shows the work-order ask as its own line; `/v1/tasks`, `/v1/slate` (§4.2) |
| 12 — TRELLIS.2, per-family envs, two-line estimates | Applied | §6.2.9 rebuilt on **TRELLIS.2 via the ComfyUI native path + TripoSR baseline** (3D supersedes R §2–§3 per X §7's closing ruling); textures via TRELLIS.2's shape-conditioned texturing — no longer deferred; model registry carries per-family environments (py3.10 conda where needed); every WO estimate and confirm line shows **build/verify vs generate/test** separately (§1.3 `Estimate`, §2.2); 3D added to citations |
| 13 — config pin, stage cache, dirty set, solver placement | Applied | `EnginePin.config` (gin/config hash) — the cache key is now a function of the recipe version; stage-cache keys ⊆ (recipe version hash, engine pin, stage name, dep keys); hit rate reported per night; §1.1 states the partial-regeneration **dirty-set contract**; solver rule: room-scoped re-solves only by day, full solves are night jobs (§3.2, §7.8) |
| 14 — the wire | Applied | Re-stream ≤ 15 s `[b]` added (marked measurement-gated with the 8 s initial load); `/v1/world/scene?since_version=` delta mode (KB-class edits); the night pre-bakes each morning option's compiled LOD manifest + comparison renders; glTF named the near-term wire (spike bpy builds `WITH_USD=OFF`); NVENC pre-encoded clips for the filmstrip (§4.1, §4.2, §6.2) |
| 15 — critic selection + calibration | Applied | Registry critic entry carries a calibration record (≥ 30 seeded-defect reference renders, measured FP/FN, target band); a critic enters service only inside its band; until chosen, automated verdicts are scripted checks labelled `verdict@scripted` on the card; spike line in §6.2; the slice states its band (§6.1) |
| 16 — sealed render spec + power mode | Applied | `Prediction.render_spec {rung, resolution, seed}` is inside the sealed payload (a verdict is re-scorable against the same inputs — X R7); the core owns `nvpmodel` at night begin/end and logs the mode beside every timing (P §5); `power.mode.set` event; `Night.power_mode`, `Job.power_mode` |
| 17 — cold start | Applied | New §3.5: ask-mode two-chip questions for the first N decisions (answers are taste notes); `confidence: "guess"` for sealed zero-prior bets (the gate governs spoken claims, not sealed bets); decay is mechanical at the two-observation gate; first-morning framing line; first-run test in slice acceptance (§6.1) |
| 18 — licence dependency terms, "reinterpreted", capability basis | Applied (capability part as a derived view) | `Licence.dependency_terms` from the registry ("MIT weights, DINOv3 encoder terms apply"); asset-library re-runs with a *different* model are labelled **"reinterpreted"**, never "regenerated"; capability claims cite `vocab.call` counts **as a derived view over existing audit events** — no new record type, because the counts are already in the log (X S14 calls the record "optional sugar"; G's capability rows render from this view) |
| 19 — Orin | Applied (non-goal arm + future-proof field) | `Job.worker` (default `"thor"`) added so no migration is needed later, but the Orin is an explicit **non-goal** for now — CLAUDE.md requires asking the owner before using it; any off-box watchtower is read-only/alerting only (a second writer would break §1.0) |
| 20 — tally read API + verdict words | Applied | `GET /v1/predictions/tally` (per builder × claim_type, denominators, recency-weighted) so the ledger line on any card is one call; panel rule: verdicts are words, never colours alone (§4.3) |

**Also new in v2 (not from the patch list):** the stage cache and night-lane
records from P (§1.9); the power plan (P §5) at §5.5; the gap states — pre-flight,
heartbeat, the four mornings, the absent client (G §2) — at §3.4; cold start and
the melt (G §1) at §3.5; Magnus's first session, ratification and lane (G §3)
woven into §1.7/§1.9/§3.2; the `[b]`/`[e]` timing markup (G) throughout; the
three-number morning line and the ≤ 10-decision budget (G §4.3) at §3.2.8;
accessibility minimums (G §4.2) at §3.2.8/§4.3. **Unchanged on purpose** (RV
"What not to change"): the durability design of §5 (audit-as-checkpoint, §7.7),
the recipe-vs-USD one-way rule (§7.11), the sealed-before-render ordering (§5.1),
the branch/pointer-move model (§1.2), the interruption/narration budgets (§5.6).

---

## 0. Decisions at a glance

| # | Question | Choice | Source tension |
|---|---|---|---|
| 1 | CAD authoring API for the engineer | **build123d primary**, CadQuery kept as readable secondary / few-shot corpus | V says "e.g. CadQuery"; R §1 verdicts build123d (§7.1) |
| 2 | Prediction `claim_type` set | T's six types **plus `weather_read`** (T's own example uses it) | T is internally inconsistent (§7.2) |
| 3 | Nightly money rail (T "Open decisions" #4) | Rails in **(GPU-minutes, hosted-cents, wall-minutes)**, defaults and degradation order in §5.5 — **plus a per-model load cap enforced at batch admission** | deferred by T; X C9/D5, R §9 and P §6-5 all name weight-swap thrash as the hardware's real constraint (§7.3, §7.13) |
| 4 | Does Magnus's taste count toward Casey's | **No.** Separate `author` scopes, forever; his pre-ratification rows are inert | T assumed; confirmed (§7.4) |
| 5 | Architect/Critic deadlock | **Critic wins on `hold`**; the owner breaks a true deadlock | T assumed; confirmed (§7.5) |
| 6 | Does the taste ledger leave the machine | **No.** Model calls get scoped slices; Magnus's rows never in a slice | T recommendation; adopted (§7.6) |
| 7 | Orchestration framework | **None.** The audit log *is* the checkpoint | V: "adopt LangGraph only if its checkpointing beats ours" (§7.7) |
| 8 | Interactive previews vs batch-by-model | **Hot tier reserved for interactive**; day previews may preempt warm loads via the **warm scene server**; the night batches strictly by model; **room-scoped solver work by day, full solves at night only** | D's three clocks vs R §9; mechanism from P §2.3-1/§2.1 (§7.8) |
| 9 | Recipe storage | **SQLite event-sourced store of record** + content-addressed blobs; git only for the engine repo | not specified in sources (§7.9) |
| 10 | Raw utterances retained? | The **confirm line is the record**; the raw utterance is kept for the owner only and purged at terminal state; **Magnus has no free text path at all — refused by actor class in code** | T "The privacy boundary"; made structural (§7.10) |
| 11 | Recipe vs USD | Recipe (typed, ours) is the source of truth; **USD/glTF is a compiled, one-way output** | R §8; adopted verbatim (§7.11) |
| 12 | How does "make these sturdier" reach a recipe param | **A node registry** (node id ↔ entry path), maintained by the engine/compiler; the packet carries resolved referents and bounded params | v1's chain was broken between node ids and entry paths (RV §1.2.1; §7.12) |
| 13 | What stops model-load thrash at night | A **per-model load cap per night** in the registry policy, enforced at batch admission, reported on the night line | X C9/D5/R6, P §6-5 (§7.13) |
| 14 | Is there a physics engine | **No.** Acceptance checks are scripted analytic computations from recipe params | no source adopts one (X R11; §7.14) |
| 15 | Magnus's authority | Chips in, free text refused structurally; preview-keeps and question-answers are his; **branch applies are proposals** pending owner confirm | X C7/C8/D4 (§7.15) |
| 16 | Can taste rows be erased from an append-only log | **Yes — one owner action**: payload redaction + compensating event, fold-excluded | T promises it; v1 had no mechanism (RV §1.3; §7.16) |
| 17 | Is the warm scene server a writer | **Never.** Derived cache, rebuildable from recipe + stage cache | P §2.3-1; keeps §1.0's single-writer rule intact (§7.17) |
| 18 | Prop/texture stack | **TRELLIS.2 via ComfyUI native + TripoSR baseline**; per-family environments, priced into two-line estimates | 3D supersedes R §2–§3 (X §7; §7.18) |
| 19 | What does the morning say when the night misbehaved | A **computed** four-value status line + reason; never narrated, never fabricated | X D6/G2, G §2 (§3.4) |

Non-goals (honesty section): no multi-tenant or hosted deployment; no CRDTs
(agents edit a recipe, not a shared document — D §7 "Figma" row); no USD→recipe
round-trip except asset import (R §8); voice input is [later] — every voice path
in this spec has a text+click equivalent that ships first (D §8); **the Orin is
out of scope for now** (CLAUDE.md: spare, ask before using; revisit as its own
decision — `Job.worker` already accommodates it); live video streaming is out —
NVENC is the playback channel for pre-rendered truth only (P §3); share bundles
(G §4.1) and the in-world client (D §8) are panel/client work with a design
already written, not core-service scope.

---

## 1. Data model

### 1.0 Conventions, IDs, store layout

- Timestamps RFC 3339 UTC. IDs are prefixed short strings: `rcp_` recipe,
  `ver_` recipe version, `br_` branch, `ed_` edit, `wo_` work order,
  `pkt_` context packet, `ast_` asset, `pr_` prediction, `tn_` taste note,
  `aud_` audit event, `night_`, `task_`, `job_`, `att_` attempt, `q_` parked
  question. Vocabulary entries and node-registry entries have no prefix id: the
  word itself (`bridge.rope`) and the node id (`span_south`) are the keys.
- Content hashes: sha256 over canonical JSON (sorted keys, no whitespace, UTF-8),
  written `sha256:ab12…`.
- **Store of record**: one SQLite database in WAL mode, `synchronous=FULL`,
  written by a **single writer process** (the core). The `audit` table is the
  source of truth; all other tables are projections rebuilt by folding `audit`
  (§5). Recipe version documents and artifacts are content-addressed blobs on
  disk, referenced by hash from the DB — so the DB is small (a night is
  kilobytes of decisions, V §"The pieces" #2) and the blobs are verified by
  hash on read.
- **One exception to payload immutability**, and only this one: an owner-initiated
  taste erasure (§1.7, §4.2) redacts the payloads of one author's
  `taste.note.appended` rows in the same transaction that appends the
  compensating `taste.erased` event. The fold then excludes them from every
  projection and every slice. ids/seq are never rewritten (§7.16).

```
$BUILDER_HOME (default ~/builder-ide)
  core.db                 # SQLite WAL: audit + projections
  artifacts/ab/ab1234…    # content-addressed, write-once (renders, GLBs, reports, clips)
  stages/<key2>/<key>/    # stage cache: content-addressed stage outputs (§1.9)
  recipes/ver_0192.json   # canonical recipe document per version (mirrors a blob)
  sandboxes/wo-14/3/      # engineer worktrees + seats (§2.2), deletable
  usd-cache/              # compiled scene layers per (recipe version, profile, LOD)
  reports/                # prebuilt static morning reports
```

Schemas below are Pydantic-style; `…` marks elisions. Every model has `id`,
`at`, and appears in `audit` on every change. Nothing but the core writes.

### 1.1 Recipe

A project is its recipe: generators, parameters, constraints, seeds. Meshes and
renders are caches (V §"The pieces" #2). Entries are typed; characters reach
them only through vocabulary words (§1.5), engineers through work orders (§2).

```python
class EnginePin(BaseModel):
    repo: str                 # "SI-Thor/infinigen-thor"
    commit: str               # pinned per project; WOs may move it forward
    config: str               # sha256 of the pinned engine-side config bundle
                              # (gin files, sampler settings) — RV patch 13: without
                              # this the stage-cache key is not a function of the
                              # recipe version and config drift defeats §5.3
    blender: str              # "4.2"
    python: str               # "3.12"

class GeneratorRef(BaseModel):
    module: str               # "infinigen_thor.structures"
    func: str                 # "bridge"
    variant: str | None       # "rope"
    rev: str                  # engine commit the generator came from

class Constraint(BaseModel):
    name: str                 # "oak_dripline", referenced by checks
    kind: str                 # keep_clear | load_floor | reachability | budget_custom
                              # | watertight | scale_bounds   (geometry kinds: RV patch 7)
    ref: str | None           # node id, e.g. "oak_0117"
    value: float | None       # radius_m; load factor; scale tolerance; …

class RecipeEntry(BaseModel):
    path: str                 # dotted, ≤ 3 segments, e.g. "harbor.crates"
    kind: str                 # generator | structure | prop_set | material | terrain
                              # | character | motion | light | weather | asset_ref
    generator: GeneratorRef | None
    params: dict[str, Json]   # validated against the linked VocabularyEntry schema
    seed: int | None
    constraints: list[Constraint] = []          # entry-local
    assets: list[str] = []                      # ast_ ids this entry consumes
    origin: str | None                          # wo_14 | "builtin" | word that made it

class Recipe(BaseModel):
    id: str
    name: str                  # "Fjellvik"
    schema_version: int = 2
    engine_pin: EnginePin
    seeds: dict[str, int]      # per channel: terrain / props / weather
    entries: dict[str, RecipeEntry]
    constraints: list[Constraint]              # project-level (drip lines etc.)
```

The Fjellvik example of v1 carries over unchanged (add
`"config": "sha256:cf90…"` to `engine_pin`). **`load_floor` and the other
checkable kinds are scripted analytic computations** — build123d mass properties
and member forces evaluated from the recipe's own parameters, run on the CPU
lane, deterministic (R §1; X R11). There is no physics engine in this system and
no "sim"; if one is ever wanted it is an engine decision with its own work order
(§7.14).

#### Edits and diffs

A recipe never mutates in place; change is an **edit**: a list of typed
operations against a parent version. The diff *is* the op list in canonical
JSON — the crate bet of D §23:04 is ~412 bytes with its envelope.

```python
class Op(BaseModel):
    op: Literal["set", "add", "remove"]
    path: str                 # JSON-pointer-ish into the recipe doc,
                              # e.g. "harbor.crates.params.count"
    value: Json | None

class RecipeEdit(BaseModel):
    id: str
    base: str                 # parent ver_
    ops: list[Op]             # ≤ 32 ops per edit; larger changes split
    author: Actor             # {kind: character|engineer|owner|core, id, via: word|wo}
    message: str              # ≤ 80 chars, one line, shown on cards
    prediction: str | None    # pr_ sealed BEFORE any render exists (D §23:04 step 2)
```

Validation: an edit is admitted only if the resulting document passes every
touched entry's vocabulary param schema (§1.5) and every project constraint that
is machine-checkable pre-render (D §04:2x: the drip-line constraint failed
*before* the critic ran — constraint checks precede renders in the pipeline,
§3.2).

#### The dirty set (engine-side contract for partial regeneration)

Entries are independent by construction (§1.2), so applying an edit must
re-evaluate **only the dirty set** — the touched entries, plus:

1. entries whose constraints reference nodes inside touched entries (the
   project-level constraints are exactly the cross-entry couplers: the oak's
   drip line crosses terrain and props);
2. entries consuming assets produced by touched entries;
3. downstream compile stages whose declared dependency keys (dep-keys, §1.9)
   include a touched entry's stage key.

Untouched stages must be byte-identical on re-evaluation — that is what a
stage-cache **hit** means, and what makes the Workshop clock and the preview
ladder physical rather than aspirational (P §2.3-2; RV §2.3). The engine hooks
(room-scoped re-solve, placeholder-scoped swap, `resample_scene`) are engine
work; this contract is what the spec requires of them.

### 1.2 RecipeVersion and branches

```python
class RecipeVersion(BaseModel):
    id: str                   # ver_…; content = canonical JSON of the document
    recipe: str               # rcp_
    parent: str | None
    edit: str | None          # ed_ that produced it (None for the root)
    root_hash: str            # sha256 of the canonical document
    at: str
    actor: Actor

class Branch(BaseModel):
    id: str
    name: str                 # "main" | "night-2026-10-30" | "wo-14" | "B-wild-wood"
    recipe: str
    head: str                 # ver_; moves only forward (fast-forward, never rewrite)
    base: str | None
    purpose: Literal["main", "night", "work-order", "morning-option", "standing",
                     "rejected"]
    created_by: Actor
    protected: bool = False   # "main" and kept morning-options are protected
```

Rules, from T §"Safe mistakes" ("every step runs on a branch; the world is
always a named commit"):

- Applying a choice is a **pointer move**, not a re-render: the morning A/B/C
  flip is `main.head = branch.head` (D §07:11: apply ≤ 10 s because the
  comparisons were pre-rendered overnight). **Applying resolves outstanding
  `taste_keep` predictions on that branch** — the owner's apply/keep/reject is
  the only event that scores them (§1.7; X C5).
- Rejection never deletes: a rejected branch is retargeted to
  `purpose="rejected"` and stays visitable (T: "a rejection is a branch you can
  revisit, not a hole in the ground").
- The three morning options are branches whose heads were rendered at the
  comparison rung during the night, so the flip is a viewer over cached
  artifacts (D §07:11, §4 moment 8). **Every branch set also contains the two
  standing options** (X G7, G §4.4): *keep yesterday* (`main` unchanged) and
  *back to the plan* (a fresh `purpose="standing"` branch cut from the slate's
  base — "start over" is a checkout, not a deletion). They are standing
  furniture from night one, so using them on a bad morning reads as a choice,
  not a failure.
- Merge into `main` is a fast-forward or, when `main` moved meanwhile, a
  three-way merge at *entry* granularity (entries are independent by
  construction; two edits to the same entry conflict and park a question rather
  than auto-merging — ambiguity is resolved by asking, never by guessing, V
  §"Calling the computer in-game").

### 1.3 WorkOrder

The bridge between the characters' closed vocabulary and the computer that can
extend it (V §"The architecture: three layers"). The state list extends D §5.5
(queued / compiling / building / testing / landed / parked) with the states the
compile-and-confirm loop needs before and after.

```python
WoState = Literal[
  "compiling",     # context packet + utterance -> draft (≤ 20 s, D §21:08)
  "questioned",    # ambiguity: a one-tap question is out; NEVER guess (V, D §21:08, T §"The open-question policy")
  "draft",         # confirm line rendered, awaiting the owner's one word
  "queued",        # approved; waiting for a window (night or spare day capacity)
  "building",      # engineer attempt running in a sandbox
  "testing",       # merge gate: rebuild, tests, render rungs, critic, licences (§2.3)
  "landed",        # gate passed; preview + evidence ready; waiting keep/reject
  "kept", "rejected",          # terminal owner decision
  "parked",        # waiting on the owner or budget; resumable
  "failed",        # terminal: attempts or budget exhausted; evidence kept
  "cancelled"]

class Budget(BaseModel):
    per_cycle: Rail           # one loop iteration / one gate run
    per_attempt: Rail         # one engineer attempt incl. its seat
    per_order: Rail           # the whole work order, may span nights
    night: str | None         # night_ it draws from, if any

class Rail(BaseModel):
    gpu_minutes: float        # measured GPU-seconds/60 across model registry costs (§5.5)
    hosted_cents: int         # cloud spend (engineer APIs, cloud LLM)
    wall_minutes: float

class Estimate(BaseModel):
    build_verify: Rail        # family-env provisioning + deterministic rebuild + tests
    generate_test: Rail       # renders, critic, generative batches
    basis: Literal["measured", "estimate"]   # [e] rule: estimates are marked fields
                                              # the morning replaces with measurements (G §1)

class AcceptanceCheck(BaseModel):
    kind: Literal["constraint", "geometry", "critic", "test_suite", "render_rung", "manual"]
    spec: dict                # examples below; "manual" requires the owner and blocks promotion

class Evidence(BaseModel):
    kind: Literal["commit", "code_diff", "recipe_diff", "render", "critic_verdict",
                  "test_run", "constraint_run", "geometry_run", "timing", "budget_spend",
                  "licence_scan", "log"]
    ref: str                  # artifacts/… path or aud_ id
    sha256: str
    summary: str              # ≤ 80 chars; what the card shows. Degraded verdicts
                              # say so HERE ("verdict@low-res", "verdict@scripted"),
                              # not only in the report (RV patch 7; X R17)

class Attempt(BaseModel):
    n: int                    # 1..; monotonic, ids never reused (idempotency, §5.3)
    engineer: str             # adapter id (§2.6)
    state: Literal["running", "delivered", "gate_failed", "failed", "cancelled"]
    seat: str                 # sandboxes/wo-14/3
    started_at: str; ended_at: str | None
    outcome: str | None       # "member-force check failed at 1.1x load (analytic)" (D §"In parallel")

class WorkOrder(BaseModel):
    id: str
    at: str
    filed_by: Actor                       # owner or a character hitting a vocabulary edge
    origin: Origin                        # below
    title: str                            # "Rope bridge, south span"
    goal: str                             # implementation spec for the engineer, ≤ 2000 chars
    targets: list[str]                    # resolved node ids ("span_south")
    vocabulary_gap: dict | None           # {"word": "bridge.rope", "requested_by": "architect"}
    acceptance: list[AcceptanceCheck]     # ≥ 1 machine-checkable check, or it cannot queue
    budget: Budget
    estimate: Estimate | None             # the ask, two lines (X R16); shown on the slate
    confirm_line: str                     # ≤ 25-word spec sentence + the two-line price (§3.1)
    state: WoState
    attempts: list[Attempt]
    evidence: list[Evidence]              # "no card without an artifact" (D §"The night's failures")
    promote: VocabularyEntry | None       # draft word; activated on keep (§2.3)

class Origin(BaseModel):
    channel: Literal["voice", "text", "chip", "character", "panel"]
    packet: str                           # pkt_ — the context packet snapshot (§1.4)
    utterance: str | None                 # owner only; kid actors cannot set it (§4.1);
                                          # purged at terminal state (§7.10)
    character_line: str | None            # the "real rope isn't in my hands yet" line (D §21:08)
```

Acceptance examples (WO-14, the rope bridge of D §21:08 and V):

```json
[
  {"kind": "constraint", "spec": {"path": "structure.south_span.params.load_factor", "op": ">=", "value": 2.0,
                                   "method": "analytic_member_forces"}},
  {"kind": "geometry",   "spec": {"check": "watertight", "tolerance": 0.0}},
  {"kind": "critic",     "spec": {"check": "reads.as.rope.bridge", "rung": 2, "verdict_in": ["keep"]}},
  {"kind": "test_suite", "spec": {"suite": "tests/structures/test_bridge_rope.py"}}
]
```

A `manual` check can exist only on owner-filed orders and forces a human gate
step before `landed`; it may never be auto-promoted.

Transition table (core-only writer; every arrow is one `audit` event; guards in
brackets) — unchanged from v1:

```
compiling ──(wo.compiled)──> draft            [confirm_line ≤ 25 words; ≥1 checkable acceptance]
compiling ──(wo.questioned)─> questioned      [≥2 plausible referent sets, §3.1]
questioned ─(question.answered)─> compiling
draft ──(wo.confirmed "go")──> queued         [Idempotency-Key; budget admitted against night rail]
draft ──(wo.cancelled)──> cancelled
queued ─(attempt.started)─> building          [seat built; rails pre-checked]
building ─(attempt.delivered)─> testing       [Deliverable schema-valid]
testing ─(gate.passed)──> landed              [all checks pass; preview artifact exists]
testing ─(gate.failed)──> building            [attempt n+1, if per_order rail allows]
testing ─(gate.failed)──> failed              [attempts or rail exhausted]
building/testing ─(wo.parked)─> parked        [blocked decision or rail event; one-line reason]
parked ─(wo.resumed)─> queued
landed ──(wo.kept)────> kept                  [branch merged/promoted; vocab word activated]
landed ──(wo.rejected)─> rejected             [branch retained; word stays coming-soon or retires]
```

### 1.4 ContextPacket

What the computer attaches to every in-game call so a few spoken words become a
full work order (V §"Calling the computer in-game, with less text"). Captured at
call time by the client (selection, gaze, position) plus core-held state; stored
as an event so any later "why did it read 'these' as the 3 arches?" is answerable
in one tap (D §4 moment 9).

#### 1.4.0 The node registry

World node ids and recipe entry paths are different keys for the same things,
and v1 never mapped between them (RV §1.2.1 — the chain
view → referent → recipe entry → params → acceptance check was broken between
its second and third links). The registry is that map. It is **written by the
engine/compiler only** (the job that compiles a recipe version into a scene),
published as a content-addressed artifact (`nodes.json`) plus a projection, and
keyed per branch head:

```python
class NodeRef(BaseModel):
    node_id: str        # "span_south" — stable across versions while the entry persists
    entry_path: str     # "structure.south_span"
    kind: str           # mirrors RecipeEntry.kind
    assets: list[str]   # ast_ ids the realized node consumes
    part: str | None    # named sub-part ("deck", "pier") when finer than the entry
```

Rules: the core resolves `view.selection` → entry paths through the registry at
the branch head the packet names; a removed entry orphans its node ids (kept,
marked orphaned, never reused); the registry is a projection, rebuildable from
the compiler's artifact. Acceptance checks, edit ops and targets may use either
key — the registry is the translator.

#### 1.4.1 The packet

```python
class ContextPacket(BaseModel):
    id: str; at: str
    actor: str                              # "casey" | "magnus"
    view: View                              # from the ProArt client [later]; text+click now
    history: History                        # from the core's own audit log
    conversation: list[ConvLabel]           # bounded labels the vocabulary keeps (V)
    project: ProjectState

class View(BaseModel):
    selection: list[str]                    # node ids, selection order
    referents: list[NodeRef]                # resolved via the node registry (§1.4.0)
    params: dict[str, dict]                 # entry_path -> current params of selected
                                            # entries, bounded (below) — "keep the sway"
                                            # now has something to keep (RV patch 1)
    gaze: Gaze | None                       # camera ray + hits, [later]
    position: tuple[float, float, float]
    region: str | None                      # "south-span", from region map

class Gaze(BaseModel):
    ray: dict                               # {"origin": [x,y,z], "dir": [x,y,z]}
    hits: list[dict]                        # [{"node_id": …, "dist": m, "part": "deck"}]

class History(BaseModel):
    recipe_changes: list[dict]              # {ver, actor, line} — last N
    renders: list[str]                      # artifact refs (V's packet includes renders;
                                            # v1 dropped them — restored, RV patch 1)
    critic_notes: list[dict]                # {at, node, reason_code, line} — last M
    work_orders_open: list[dict]            # {id, title, state} — all open, ≤ K
    landed_work_orders: list[dict]          # {id, title, outcome, touched} — recent kept
                                            # WOs touching the referents (D §3 07:26 compiles
                                            # from "selection + camera + last night's WO-14
                                            # evidence", which v1 hid; RV patch 1)

class ConvLabel(BaseModel):
    who: str                                # architect | landscaper | … | casey | magnus
    label: str                              # closed label set: "limit-hit:bridge.rope",
                                            # "request:new-capability", "taste:keep", …

class ProjectState(BaseModel):
    branch: str; head: str
    budget_left_tonight: Rail
    vocabulary_gaps: list[str]              # known missing words, ≤ 8 (D §5.5)
    engine_pin: dict
    world_time: str
```

**Bounds** (hard caps enforced at capture; on overflow drop in the order given,
never `view` or `project`):

| Field | Cap | Overflow behaviour |
|---|---|---|
| `view.selection` | 32 ids | keep first 32 in selection order |
| `view.referents` | 32 | mirrors selection |
| `view.params` | 8 entries / 2 KiB | largest entries first out |
| `view.gaze.hits` | 5 | nearest 5 |
| `history.recipe_changes` | 10 | drop oldest first |
| `history.renders` | 3 | drop oldest first |
| `history.critic_notes` | 5 | drop oldest first |
| `history.work_orders_open` | 8 | oldest filed first out |
| `history.landed_work_orders` | 3 | oldest first out |
| `conversation` | 12 labels | drop oldest first |
| `project.vocabulary_gaps` | 8 | — |
| whole packet (canonical JSON) | **16 KiB** | drop `history`, then `conversation`; fail loud if still over |

Typical size 2–8 KiB. The packet is the *only* situation data that crosses into
a model prompt together with the utterance (T §"The privacy boundary": the
ledger/packet are what get read into a prompt — never transcripts).

Example (the WO-14 call, D §21:08, amended):

```json
{
  "id": "pkt_0031", "at": "2026-10-30T21:08:39Z", "actor": "casey",
  "view": {
    "selection": ["span_south"],
    "referents": [{"node_id": "span_south", "entry_path": "structure.south_span",
                    "kind": "structure", "assets": [], "part": "deck"}],
    "params": {"structure.south_span": {"length_m": 14.0, "planks": 8, "rope": "hemp",
                  "sway": 0.22, "load_factor": 1.1}},
    "gaze": {"ray": {"origin": [142.1, 3.0, 88.4], "dir": [0.31, -0.12, 0.94]},
             "hits": [{"node_id": "span_south", "dist": 11.2, "part": "deck"},
                      {"node_id": "pier_s2", "dist": 14.9}]},
    "position": [140.0, 2.0, 80.0], "region": "south-span"},
  "history": {
    "recipe_changes": [{"ver": "ver_0188", "actor": "architect", "line": "south span planks loosened (fake sway)"}],
    "renders": ["artifacts/5c/5c31….png"],
    "critic_notes": [{"at": "2026-10-30T21:05:11Z", "node": "span_south", "reason_code": "wrong_material", "line": "planks read as glued"}],
    "work_orders_open": [],
    "landed_work_orders": []},
  "conversation": [
    {"who": "architect", "label": "limit-hit:bridge.rope"},
    {"who": "casey", "label": "request:new-capability"}],
  "project": {"branch": "br_main", "head": "ver_0192",
              "budget_left_tonight": {"gpu_minutes": 330, "hosted_cents": 0, "wall_minutes": 480},
              "vocabulary_gaps": ["bridge.rope"],
              "engine_pin": {"commit": "9f31c0e", "config": "sha256:cf90…"}, "world_time": "21:08"}
}
```

### 1.5 VocabularyEntry

The closed, typed vocabulary through which characters change the world — they
never write code (V §"The pieces" #4). A word is added only by the core, only
from a kept work order (promotion, §2.3) or by the owner; characters can read
and cite, never write (T §"The taste ledger": the agent never holds the pen).

```python
class TasteNote(BaseModel):
    code: Literal["keep", "avoid"]
    reason_code: ReasonCode        # the closed set, §1.7
    note: str                      # ≤ 6 words, optional
    basis: str                     # "4/5 kept" — counts with denominators, never percentages (T)

class VocabularyEntry(BaseModel):
    word: str                      # dotted, ≤ 3 segments: "bridge.rope"
    kind: Literal["structure", "prop", "material", "terrain", "weather",
                  "motion", "light", "constraint", "character"]
    owner_character: str           # who may call it
    status: Literal["active", "coming-soon", "retired"]
                                  # "coming-soon" is pinned when a WO is filed (D §21:08)
    params: dict                   # JSON Schema (draft 2020-12 subset, below)
    acceptance_template: AcceptanceCheck | None   # "{node}" placeholders bound at call time
    taste_notes: list[TasteNote]   # aggregated by the CORE from the taste ledger; read-only to characters
    provenance: dict               # {"origin": "wo_14" | "builtin", "commit": …, "at": …}
    version: int                   # params evolve only via kept work orders (crates v2 gains lids)
```

The **param schema subset** (bounded so a word is always validatable and
diffable, and a character can never smuggle free text):

- allowed types: `integer`, `number` (both require `minimum`/`maximum`),
  `string` only as `enum`, `boolean`, `integer` seed;
- ≤ 8 properties, `additionalProperties: false`, no nesting deeper than 2;
- canonical params JSON ≤ 512 bytes.

The `bridge.rope` example of v1 carries over unchanged.

A character's call is `POST /v1/vocab/call {word, node | region, params}` → the
core validates against the schema, binds the acceptance template, and produces a
`RecipeEdit` authored `{kind: character, id: …, via: word}`. Anything outside
the schema is refused at the door — that refusal, said in character, is the
"I can't do rope yet" moment (D §21:08). **Capability claims render from the
call log**: "Swing isn't in my hands yet — 0 built" is a derived view over
`vocab.call` counts and kept work orders, not a new record type (X C12; G §1
20:31's capability rows; RV patch 18).

### 1.6 Asset

Every generated or imported asset enters the library with provenance and a
licence — a checked list, not a footnote (V §"Rules carried over from
last-mile"; D §5.6). **The scheduler stamps provenance, not the job** (R §9):
whatever path created the file, the stamp is written by the core from the job
record, so it cannot be forged or forgotten by an engineer process.

```python
class Asset(BaseModel):
    id: str
    kind: Literal["mesh", "texture", "material", "cad_part", "motion_clip", "audio"]
    files: list[FileRef]          # {"role": "master|glb|step|maps|clip", "path", "sha256", "bytes"}
    provenance: Provenance
    licence: Licence
    critic: dict | None           # {"verdict": "keep", "code": …} once scored

class Provenance(BaseModel):
    source: Literal["generated", "library", "cad_script", "import"]
    generator: dict | None        # {"method": "image_to_3d|text_to_texture|text_to_motion|
                                  #            text_to_music|cad_script",
                                  #  "model_id": "trellis2-4b",
                                  #  "weights": {"repo", "revision", "licence"},
                                  #  "prompt": "≤ 256 chars", "seed": 771,
                                  #  "env": {"family": "trellis2", "revision": "…"},   # per-family env (3D §6)
                                  #  "library_versions": {"torch": "…", …}}            # full tuple (3D §5)

class Licence(BaseModel):
    spdx: str                     # "MIT", "OpenRAIL++-M", "CC-BY-NC-4.0", "CC0", …
    dependency_terms: list[str]   # terms that ride WITH the weights — e.g. TRELLIS.2's
                                  # DINOv3 encoder conditions on MIT weights (3D §3; X R8)
    commercial_ok: bool
    checked_at: str; checked_by: str   # the core's licence registry, not the creating job
    notes: str | None
```

Licence policy (from R's verdicts, amended by 3D §3 where it supersedes): the
prop stack is **TRELLIS.2 via ComfyUI native (MIT code, MIT ungated weights,
DINOv3 encoder terms recorded in `dependency_terms`) with TripoSR as the MIT
baseline** (§6.2.9, §7.18); `commercial_ok=false` rows (MusicGen CC-BY-NC,
FLUX-dev, ambiguous MotionGPT weights) can never enter an entry marked
shippable; Hunyuan weights carry a regional restriction flag; MoMask-derived
clips carry the AMASS/HumanML3D data-provenance flag until an owner decision
(R §4). The merge gate's licence scan (§2.3) blocks promotion on any missing or
failing licence row. **Naming rule:** an asset re-run through a *different*
model is labelled **"reinterpreted with [model]"**, never "regenerated" — a
re-run reproduces the recipe, not the bytes (3D §5; X R9).

### 1.7 Predictions and taste notes (the two ledgers)

Two distinct tallies, stored and displayed separately because they fail
differently (T §"Two tallies"): predictions about the **world** (competence,
scored by the Critic) and predictions about **you** (taste, scored by the
owner's keep/reject). Only sealed predictions count, anywhere (D §9).

**Three record types, three writers, one store** (X C5/D1/D2 — RV patch 6):

| Record | Written by | What it means | May it drive a change? |
|---|---|---|---|
| `taste_note` | **the owner only** (Casey or Magnus) | "I chose this and this is why" — the reason code | yes — it is the taste model |
| `prediction` | the builder, **sealed** | "I think you'll keep this" | no — a claim awaiting scoring |
| `verdict` | **the Critic** | "this artifact has defect X" — a quality finding | yes — a defect, not a taste |

The night's automated keep/revert (§3.2.4) is a **`critic.verdict` write plus an
audited branch op — never `taste.note.appended`**. Left implicit, the taste
model trains on its own output and the sealed bets become unfalsifiable (X C5).
Consequently: a critic keep does **not** resolve a `taste_keep` prediction; the
owner's keep/apply/reject does, and the apply flow (§1.2) scores any outstanding
`taste_keep` predictions on that branch.

```python
class Prediction(BaseModel):
    id: str; builder: str
    at: str; sealed_at: str        # equal at seal time; sealed_at is immutable
    branch_ref: str                # "br_07f2@ver_0193"
    claim: str                     # ≤ 120 chars, the spoken claim verbatim
    claim_type: str                # closed set: shadow_count | scale_read | clutter_density
                                   # | material_read | era_read | light_read | weather_read
                                   # | taste_keep        (§7.2 for the set's provenance)
    namespace: Literal["world", "taste"]   # taste iff claim_type == taste_keep — two gates (X §6 5)
    confidence: Literal["guess", "low", "medium", "high"]
                                   # "guess" = a sealed zero-prior bet (cold start, §3.5);
                                   # the two-observation gate governs *utterances*, not
                                   # sealed records (G §1 20:44)
    basis: str                     # denominator at seal time: "0 observations", "14/18 kept"
    render_spec: dict | None       # {rung, resolution, seed} — inside the sealed payload so a
                                   # verdict is re-scorable against the same inputs (X R7; RV patch 16)
    seal_hash: str                 # sha256 over canonical {builder, at, branch_ref, claim,
                                   #  claim_type, confidence, basis, render_spec} — written
                                   #  BEFORE the render job is created (§5.1)
    verdict: Literal["hit", "miss", "partial"] | None   # set by the Critic (world) or the
                                                        # owner's keep/apply/reject (taste_keep);
                                                        # never self-scored
```

**Two gates, two namespaces** (X §6 5, fixing T's conflation): the *world* gate
is per `claim_type` and requires a denominator; the *taste* gate is per reason
code and requires ≥ 2 prior observations. Both are hard gates in the core's
prediction and utterance APIs, not prompt instructions (T §"The 'I think you'll
like this' utterance", rule 4): a builder may not *say* a taste claim below two
observations, and below three observations the uncertainty leads the sentence.
A sealed record with `confidence: "guess"` is always permitted — the gate
forbids pretending to a view, not betting (G §1).

```python
ReasonCode = Literal["too_busy", "too_empty", "wrong_scale", "too_messy", "too_clean",
                     "too_flat", "too_dark", "too_bright", "wrong_material", "wrong_era",
                     "wrong_weather", "no_focus"]        # the closed dozen (T §"taste note fields")

class TasteNote(BaseModel):
    id: str; at: str
    author: str                     # "casey" | "magnus" — author-scoped, never merged (§7.4)
    status: Literal["active", "pending_ratification"]
                                    # Magnus's first three keeps are pending_ratification and
                                    # INERT: excluded from every slice any builder reads, until
                                    # the owner ratifies once that he understands "keep"
                                    # (G §3 guardrail; X G4)
    subject: dict                   # {node_id, param_path, value}
    artifact_ref: str               # branch@commit — a claim about a thing, never a conversation
    verdict: Literal["keep", "reject", "keep_with_caveat"]
    reason_code: ReasonCode
    words: str | None               # ≤ 6 words, for humans only
    tags: list[str]
```

Taste notes are **append-only with a single writer**: written by the owner's
verdict event and nothing else. Builders read and cite; they never write (T
§"The taste ledger"). Magnus's rows are separable, exportable and deletable in
one action each (T §"The privacy boundary"); they are never included in any
slice read into a model prompt (§7.6). **Export and erase are mechanisms, not
promises** (RV patch 9): export is `GET /v1/ledger/taste/export?author=` (the
author's rows, reason codes and artifact refs as one bundle); erase is
`POST /v1/ledger/taste/erase {author}` — one transaction that redacts that
author's taste-event payloads and appends `taste.erased` (§1.0, §5). Ratifying
Magnus is `POST /v1/ledger/taste/ratify {author}` — asked once, in the report,
in one line (G §3).

### 1.8 AuditEvent — the one log

Everything the panels show is a view over this table: the night feed is the
log, not a stream, so peeking is reading and rewind is free (D §02:07), and the
morning report is a static page over it (D §07:03). No card without an
artifact: any event that surfaces as a card carries `artifact` (D §"The night's
failures").

```python
class AuditEvent(BaseModel):
    seq: int                      # per-project, monotone, gapless — the resume cursor (§5.2)
    id: str                       # aud_
    at: str
    actor: Actor                  # {kind: owner|character|engineer|critic|core|scheduler|client, id}
    type: str                     # closed set below
    subject: dict                 # {entity_kind, entity_id}
    payload: dict                 # ≤ 4 KiB; anything bigger goes to artifacts/ and is hash-referenced
    artifact: dict | None         # {sha256, kind, bytes}
```

Event types (closed; new types are a schema change). **New in v2** marked ▲:

| Group | Types |
|---|---|
| work orders | `wo.filed`, `wo.compiled`, `wo.questioned`, `wo.confirmed`, `wo.queued`, `wo.attempt.started`, `wo.attempt.delivered`, `wo.testing`, `wo.landed`, `wo.kept`, `wo.rejected`, `wo.parked`, `wo.resumed`, `wo.failed`, `wo.cancelled` |
| recipe | `edit.proposed`, `edit.validated`, `version.committed`, `branch.created`, `branch.head.moved`, `branch.rejected`, ▲`branch.proposed` (kid apply pending owner confirm), `constraint.failed` |
| predictions | `prediction.sealed`, `prediction.scored` |
| taste | `taste.note.appended` (single writer: owner verdicts only), ▲`taste.erased` (compensating; §1.7), ▲`taste.ratified` |
| vocabulary | `vocab.word.added`, `vocab.word.status`, `vocab.call` (refused calls included — the edges are the story, D §5.5) |
| night | `night.started`, `night.stopped`, ▲`night.preflight`, ▲`night.tick` (heartbeat; the status line is computed from these, §3.4), `night.task.created`, `night.task.state`, `line.spoken` (line-budget enforced here, §5.6) |
| scheduler | `sched.model.load`, `sched.model.unload`, `sched.demote`, `job.enqueued`, `job.started`, `job.done`, `job.requeued`, `render.completed`, ▲`scene.loaded`, ▲`scene.evicted` (warm scene server, §1.9), ▲`power.mode.set` (§5.5) |
| critic | `critic.verdict` (carries `degraded` flag → `verdict@low-res`/`verdict@scripted`, D §03:5x, §3.5) |
| budget | `budget.spend`, `budget.threshold` (80/95/100), `kill.switch` |
| assets | `asset.created`, `asset.licence.checked` |
| questions | `question.parked`, `question.answered`, ▲`assumption.recorded` (the conservative reading taken at night, attached to the branch/card it replaced — X S12; RV patch 2) |
| continuity | `model.change.noticed` (T §"Research transfer": model swaps announced, never silent) |
| client | ▲`client.attach`, ▲`client.detach` (detach-gating is load-bearing, so presence is a durable fact; RV patch 10) |
| system | `core.boot`, `core.recovered`, `projection.rebuilt`, `integrity.failure`, ▲`call.refused` (free text refused by actor class, §4.1) |

### 1.9 Night, Task, Job — the scheduler's records

```python
class Night(BaseModel):
    id: str                        # night_2026-10-30
    started_at: str; stopped_at: str | None
    rails: Rail                    # the budget bar's ceiling (D §21:02: ~8 h wall, 5.5–6.0 GPU-h)
    load_budget: dict[str, int]    # per model id: max sched.model.load events tonight
                                   # (default 1 each — P §6-5's "model-load count per night
                                   # (target: 1 per model)"; enforced at batch admission, §5.5)
    power_mode: int                # nvpmodel mode owned by the core for the window (§5.5);
                                   # logged beside every timing (P §5)
    batch_start: Literal["detach", "deadline", "both"]
    detach_deadline: str | None    # big batches start on client detach OR this deadline
                                   # (default night.started + 30 min, owner-settable; X R19, RV patch 10)
    state: Literal["starting", "running", "stopping", "stopped"]
    status: str | None             # computed at stop from heartbeats + admission waits:
                                   # ran as planned | ran short | ran degraded | did not run
                                   # (+ one-line reason) — §3.4. Never narrated; computed.
    report: str | None             # artifacts/… report.html, prebuilt at stop

class Task(BaseModel):
    id: str
    night: str | None              # None until the night starts: chips and slate rows live
                                   # pre-night (RV patch 11; chips exist from 20:47, the night
                                   # starts 21:14 — D §1)
    author: str                    # "casey" | "magnus" — two queues, one lane (X G10)
    ends_at: str | None            # kid lane's fixed hour (21:30); the lane stops hard,
                                   # unfinished items park with kid-readable cards (G §3)
    owner_character: str
    intention: str                 # "Forest the east slope, keep the oak" (D §21:02 slate row)
    recipe_scope: list[str]        # entry paths this task may touch
    cost_estimate: Rail            # the ASK, stored at slate time so the morning can name
                                   # what was cut (X C11; RV patch 11) — marked [e] until
                                   # measured (§3.5)
    rail: Rail                     # per-task rail (T §"Safe mistakes": three rails)
    state: Literal["slated", "queued", "running", "kept", "reverted", "parked", "cut"]
                                   # "slated" = pre-night; "cut" = dropped at the bar,
                                   # requeued for tomorrow (D §05:0x)
    predictions: list[str]; branches: list[str]

class Job(BaseModel):
    id: str
    lane: Literal["cpu", "gpu"]
    worker: str = "thor"           # worker registry is config; the Orin is a non-goal for
                                   # now (§0, §6; CLAUDE.md: ask before using it) — RV patch 19
    model: str | None              # registry id for gpu jobs (R §9 tiers)
    request: dict                  # seeded, bounded; seeds are first-class (R: determinism)
    cost_estimate: Rail            # checked BEFORE dispatch (T: rails enforced before spend)
    claim_token: str; lease_until: str; heartbeat_at: str   # crash recovery, §5.2
    power_mode: int | None         # mode active when the job ran (logged beside timings, P §5)
    stage_cache: Literal["hit", "miss", "partial"] | None   # per stage; hit rate reported
                                   # per night (P §6-2; RV patch 13)
    state: Literal["queued", "running", "done", "failed", "requeued"]
    outputs: list[str]             # artifact refs; provenance stamped by the core on done
```

#### Model registry (config, not DB rows)

Per model id — tier `hot` (companion LLM, critic vision model: always resident),
`warm` (one generative model loaded at a time, drained per batch, R §9), `cold`
(disk, pinned revisions); a cost table mapping measured GPU-seconds and hosted
cents per call to rail units; demotion rules (critic OOM → smaller local critic,
verdicts marked `degraded` — defence in depth, §3.3); **`loads_per_night`**
(default 1) enforced at batch **admission** (RV patch 3); and, new in v2:

- **Per-family environments** (3D §1/§6): each family declares its env (e.g.
  TRELLIS.2's py3.10 conda; the core's cp312 venv); a model is *hot* when its
  env is resident; seats materialize the family env an order needs (§2.2), and
  every estimate prices provisioning separately (X R16).
- **Critic calibration** (RV patch 15; X R4/S6): the registry's critic entry
  carries `calibration: {reference_set, fp_rate, fn_rate, band}` — a fixed set
  of ~30 renders with seeded, known defects (hollow meshes, wrong scale, broken
  constraints), measured FP/FN against it, and a target band (catch the seeded
  defects; reject no more than a set fraction of clean ones). **A critic enters
  service only inside its band.** Until one is chosen and measured, automated
  verdicts are scripted checks and carry `verdict@scripted` on their cards (G §1;
  §3.5).

#### The stage cache

Key = `sha256(canonical(recipe_version_hash ⊕ engine_pin ⊕ stage_name ⊕
dep_keys))`, where `engine_pin` includes the pinned config hash (§1.1) — **the
key must be a function of the recipe version alone**: no wall-clock, no
hostname, no ambient config (P §2.3-3; RV patch 13). Value = the stage's side
effects (a per-stage blend library or layer + the timing row), content-addressed
under `stages/`. Invariants: a stage hit is byte-identical to re-evaluation
(the dirty-set contract, §1.1); job dedup (§5.3) converges on the same artifact
because config drift is now impossible; the merge gate's deterministic rebuild
(§2.3.1) cannot pass against a cache built under different engine settings than
a fresh rebuild would use. Hit rate is a first-class nightly measure (P §6-2).

#### The warm scene server — a resident resource, not a job

A resident Blender process owning the open scene, killing the per-task `bpy`
relaunch and the `scene.blend` round-trip (P §1, P §2.3-1) — the difference
between the Workshop clock (seconds for an in-place edit) and batch latency. It
never completes, so it is not a `Job`; it is a **scheduler-managed resident
resource** (RV patch 4):

```python
class SceneResidency(BaseModel):     # scheduler-held state; audited, not a DB row
    branch: str                      # residency is bound per branch (P §7-3)
    version: str                     # ver_ it was built from
    stage_keys: list[str]            # stage-cache keys it was assembled from
    rss_peak_mb: int                 # peak RSS decides how many branches stay resident
                                     # in 122 GB — hence how many pre-baked morning options exist
    loaded_at: str
```

Lifecycle: `scene.loaded` / `scene.evicted` audit events; the residency bound is
a peak-RSS budget (P §7-3) with morning-option branches pinned through the
report; eviction is LRU among unpinned branches. **Hard rule: it is a derived
cache, never a writer** — it owns no durable state, produces only artifacts via
jobs, and is rebuildable from recipe version + stage cache; it is on §5.2's
does-not-survive list. This is the mechanism behind §4.1's Workshop budget and
§7.8's day-preempt decision; without it, every edit pays a full engine restart
(P §1).

---

## 2. The engineer adapter

One interface every coding/generative engineer implements. In: a work order and
a sandbox branch. Out: a commit and test evidence (V §"The engineer is
pluggable"). The adapter is the stable seam; behind it sit Claude Code
(hard orders, on a budget), zcode/mcode (bulk), aider on the Thor's local coder
(free small fixes), OpenHands or Goose as sandboxed runtimes (V; R did not
evaluate these — they remain "worth a test").

### 2.1 The interface

```python
class Capabilities(BaseModel):
    kinds: list[Literal["code", "gen_batch"]]   # code = engine/vocab work; gen_batch = may
                                                # schedule generative batches via MCP
    max_rail: Rail | None                        # what one attempt may plausibly consume
    cost_class: Literal["hosted", "local"]

class EngineerEvent(BaseModel):
    kind: Literal["progress", "tool_call", "artifact_ref", "deliverable", "failure"]
    at: str
    text: str | None             # progress: ≤ 200 chars, rate-limited to the feed
    payload: dict | None         # tool_call: {tool, args_hash}; deliverable: Deliverable

class Deliverable(BaseModel):
    attempt: str                 # att_
    commit: dict                 # {"branch": "wo/wo-14/3", "sha": "a1c4e2…"}
    recipe_edit: str | None      # ed_ proposed (schema-validated by the core before the gate)
    code_diff: dict              # {"files": n, "insertions": n, "deletions": n, "patch_ref": artifact}
    evidence: list[Evidence]     # must include ≥1 test_run; render/critic evidence is
                                 # REGENERATED by the gate — never trusted from the engineer
    vocab_proposal: VocabularyEntry | None
    notes: str                   # ≤ 200 chars

class Engineer(Protocol):
    id: str
    def capabilities(self) -> Capabilities: ...
    def run(self, order: WorkOrder, seat: Seat) -> Iterator[EngineerEvent]: ...
    def cancel(self, attempt_id: str) -> None: ...
```

The core drives `run`, forwards `progress` to the feed (bounded), and treats
`deliverable` as a *claim* to be verified by the merge gate. The engineer never
writes the store; it works in its worktree and calls the core's MCP tools
(§2.5), each of which is an audited, rail-charged action. (Unchanged from v1.)

### 2.2 How sandboxes are made

The seed loop from last-mile — brief → worktree → seat → review → merge-gate
(V §"The core is ours and small") — made repeatable:

1. **Worktree**: `git worktree add sandboxes/wo-14/3 -b wo/wo-14/3 <engine_pin>`
   from the pinned infinigen-thor clone. The attempt branch is the sandbox
   branch the adapter contract names.
2. **Recipe checkout**: the project recipe at the order's base version is
   materialized into the seat as read-only data (`project/recipe.json` + assets
   by content hash). Data, never code, crosses the boundary (V §"Rules carried
   over from last-mile"); the engineer *proposes* a `RecipeEdit`, it does not
   edit the store.
3. **Seat**: a cgroup-scoped execution context — CPU shares, a GPU-memory
   fraction, wall-clock timer; a network namespace with an allowlist (package
   index, pinned model hosts; no LAN, no ledger); **the environment the order's
   model families need, materialized from the registry's per-family envs**
   (py3.10 conda where the family demands it — 3D §1; RV patch 12) on top of
   the project's pinned core venv; stdout/stderr captured to `artifacts/` as a
   log Evidence item.
4. **Rails**: the attempt's `per_attempt` rail is pre-checked at admission and
   hard-enforced by the seat (kill at rail) — enforced before spend, not
   alerted after (T §"Safe mistakes", citing the AWS agentic cost hierarchy).
   **Provisioning is priced**: a work order that must build a py3.10 conda
   environment before its first render is a different three hours than one that
   does not, which is why `Estimate.build_verify` exists and the confirm line
   shows both lines (X R16; §3.1).
5. **Idempotency**: attempt directories are numbered and never reused; a
   rebooted attempt restarts as attempt *n+1* in a fresh seat (§5.2).

### 2.3 How evidence is checked — the merge gate

Run by the core, on the deliverable, in a clean worktree. Ordered; any hard
fail stops the gate (the attempt is `gate_failed` with the failing evidence
attached — D §"In parallel": attempt 1 failed the member-force check at 1.1×
load; attempt 2 on plank spacing; attempt 3 passed at 2.3×).

1. **Deterministic rebuild**: apply the proposed recipe edit and build from the
   commit in a clean worktree, **against the pinned engine config** (§1.1). CAD
   parts must be byte-identical (R §1: same script + pinned wheels →
   byte-identical geometry); generative outputs must reproduce from
   `(prompt, weights revision, env revision, seed)` (R; 3D §5 — seeded
   samplers everywhere; seed is a first-class param).
2. **Static + unit tests**: typecheck and suites on the changed code.
   build123d's typed, property-based style is chosen precisely because it is
   statically checkable (R §1; §7.1).
3. **Geometry check** *(new, RV patch 7; X R10)*: watertight / manifold /
   scale-bounds — mechanical, per rung, **before the critic**. The
   crates-7-and-11-hollow failure is the known image-to-3D failure mode (R §2),
   and a hollow mesh must die at this step, not inside the critic's judgement.
4. **Render ladder** (T §"Safe mistakes": previews are a ladder, each rung a
   budget gate; the night spends on the last rung only what survived the first
   two): rung 1 fast layout (seconds) → rung 2 mid still with lighting and
   materials (~a minute) → rung 3 full render (minutes). The gate stops at the
   lowest rung that can decide every `acceptance` check. Rung-1/2 previews come
   from the warm scene server where one is resident (§1.9).
5. **Constraint checks**: machine-checkable acceptance — **scripted analytic
   computations** (load factor from member forces and mass properties,
   drip-line clearances) run *before* the critic at each rung (D §04:2x; X R11;
   §7.14).
6. **Critic check**: the required `critic` acceptance items at the required
   rung. If the critic was demoted, the verdict is recorded `degraded` and
   **the evidence card says so on its face** (`verdict@low-res`; until a critic
   is calibrated, `verdict@scripted`) — not only the report (X R17; RV patch 7).
   The Critic returns `hold`/`fix`/`keep` + reason code + at most one suggested
   change, and authors nothing (T §"Five builders and one computer"). The
   defect Critic never sees the taste ledger (X C6/D3).
7. **Licence scan**: every new asset has a complete `Licence` row from the
   registry, **including `dependency_terms`**; missing, ambiguous or
   non-commercial rows block promotion into vocabulary marked shippable
   (R §3–§5; 3D §3; V: licences are a checked list).
8. **Budget audit**: seat telemetry vs the deliverable's claimed spend; a
   mismatch > 20% fails the attempt (honest evidence or no evidence).
9. **Diff review pack**: recipe diff (ops), code diff, before/after renders at
   the deciding rung, timings **with the power mode logged beside each number**
   (P §5) — assembled as the evidence bundle, hashed into the ledger, openable
   in ≤ 1 s (D §4 moment 9).

**Pass ⇒ `wo.landed`.** The preview exists before the owner sees the card
(D §4 moment 10). **Keep ⇒ promotion, in one core transaction:** branch
fast-forwarded per the owner's choice, outstanding `taste_keep` predictions on
the branch scored (§1.7), `vocab.word.added` fires, the word's `status` flips
`coming-soon → active` with provenance pointing at the WO and commit, and the
owning character is notified so the "I can do rope now" reveal lands at the
moment it becomes useful (D §07:34). **Reject ⇒** the branch is retained under
`purpose="rejected"`, the word proposal is parked or retired, the evidence
stays.

### 2.4 How ACP maps onto it

ACP (Agent Client Protocol) is how editor-native agents and front ends talk
(Zed's protocol; V §"The pieces" #7: front ends onto the engineer's work, not
backends). The core plays **ACP client** to engineer agents and **ACP proxy**
to human front ends (unchanged from v1):

| ACP item | Core behaviour |
|---|---|
| `initialize` | negotiate once per adapter process; core is the client |
| `session/new` | create the agent session bound to `att_` |
| `session/load_history` | replay the attempt's audit trail as turns (post-reboot resume, §5.2) |
| `session/prompt` | send the work order goal + seat brief |
| `session/update` (notify) | translated to `EngineerEvent.progress` / `tool_call`; audited (`wo.attempt.*`), forwarded to the feed and to attached front ends |
| `session/request_permission` | auto-**deny** anything outside seat scope (store writes, network beyond allowlist, rail increase); rail-exceeding requests surface to the owner as a question, never auto-approved |
| `session/cancel` | adapter `.cancel()`; seat killed; attempt recorded `cancelled` |

Front ends attach through `GET /acp/proxy/{attempt}` (SSE/WS): the core
re-broadcasts `session/update` traffic to Theia/Zed read-only; write mode
requires the owner token and files as a co-driver event on the attempt. The
engineer cannot tell and does not care — it sees one client.

### 2.5 How MCP maps onto it

The core is an **MCP server** inside every seat (stdio for CLI agents, HTTP for
hosted runtimes). Tools are the only way an engineer touches project state, and
every call is an `aud_` event charged to the attempt rail (unchanged from v1):

| Tool | In | Out |
|---|---|---|
| `recipe.get` | version? | recipe document |
| `recipe.diff` | base, head | ops list |
| `vocabulary.search` / `vocabulary.get` | query / word | entries (incl. `coming-soon` edges) |
| `context.packet` | pkt_ | the packet the order compiled from |
| `render.request` | entry paths, rung, seed | job id → artifact ref (rail-charged; served by the warm scene server / stage cache where resident, §1.9) |
| `critic.request` | artifact, check | verdict (rail-charged; gate re-runs it independently) |
| `tests.run` | suite | results |
| `evidence.attach` | kind, artifact sha, summary | Evidence row |
| `budget.remaining` | — | rail snapshot |
| `order.get` | — | order + acceptance checks |
| `deliver.submit` | Deliverable | triggers the merge gate |

There are deliberately **no** tools to write the taste ledger, vocabulary,
audit log or branches (T §"The taste ledger": the agent never holds the pen;
D §7: data, never code, for agent changes — the inverse direction). modly's
own MCP server (R §2) stays behind the scheduler and is not exposed to seats;
the ComfyUI-native TRELLIS.2 path inherits the same isolation (§6.2.9).

### 2.6 Engineer registry (initial)

Unchanged from v1:

| id | class | use | notes |
|---|---|---|---|
| `aider-local` | local | small fixes, param additions | zero marginal cost (V); the slice engineer (§6.1) |
| `claude-code` | hosted | hard orders (new generators, engine work) | per-order `hosted_cents` rail mandatory |
| `zcode` / `mcode` | hosted/local | bulk mechanical work | same adapter |
| `openhands`, `goose` | hosted | sandboxed runtimes | "worth a test" (V); adapter treats them as ACP/MCP peers |

Generative *batches* (textures, image-to-3D, motion, music) are not engineers:
engineers and characters both request them through the scheduler as `Job`s
(§1.9), which is what stamps provenance (R §9). An engineer with
`kinds: ["gen_batch"]` may enqueue jobs via MCP to fulfil an order ("make this
chair Victorian", V §"The engineer also makes things").

---

## 3. Lifecycles

### 3.1 A terse in-game call, end to end

"Computer, make these sturdier" (V) / "Computer, I want rope bridges that
swing" (D §21:08). Latency budgets from D §4. The never-guess rule (V, T §"The
open-question policy") applies to **every** input path — utterances *and*
chips (RV §1.1 S3).

```
owner ── utterance + client view ──> POST /v1/call        (kid actors: chips only, §4.1)
core: capture ContextPacket (pkt_)                       [aud: pkt captured]
core: compile                                            ≤ 20 s [b] (D §21:08), Workshop clock:
                                                          progress + cancel (X R2)
   1. referent resolution over view.selection ∪ gaze.hits ∪ region,
      deterministic: node ids, distances, part names — then THROUGH THE NODE
      REGISTRY to entry paths (§1.4.0); view.params supplies the current values,
      so "these sturdier, but keep the sway" is a param delta: raise
      load_factor, leave sway at 0.22 (D §3 07:26)
   2. if top-2 candidate referent sets both plausible → wo.questioned.
      One-tap question naming candidates by what they are
      ("The south span, or both spans?"). NEVER guess (V, D §21:08, T).
      Test (D): say an order with two plausible referents;
      the second line must be a question, not a plan.
   3. draft: goal, targets by id, acceptance checks, budget estimate
      (model-registry cost table × historical baselines; provisioning priced
      separately), confirm line
   4. confirm line = a ≤ 25-word spec sentence (T §"Telling the computer apart
      from the crew": no first person) + the two-line price (X R16; G §1 20:38):

      CONFIRM: rope bridge, south span, hempen, 8 planks; analytic load check
      passes at 2x. build/verify: ~40 min [e] · generate/test: ~1.5 h [e] ·
      est. 3 h tonight; reversible at ver_0192. Go?

      A one-line estimate is a build failure (G §1 20:38 test).
owner ── "Go" ──> POST /v1/work-orders/{id}/confirm     (Idempotency-Key)
core: wo.confirmed → queued; night rail re-admitted; budget bar updates;
      vocabulary note `bridge.rope` pinned coming-soon on the Architect   [aud]
   (a veto is one sentence; a wrong compile is cheap to reject — D §21:08)

night (or spare day capacity):
core: attempt 1..N — seat, engineer.run, merge gate      [aud per attempt]
   failures keep evidence: "1.1x load, member-force check failed (analytic)" (D)
core: gate passes → wo.landed; preview + evidence bundle exist BEFORE the
      owner is notified                                  (D §4 moment 10)

morning / on arrival:
client: card "WO-14 · landed · preview ready"; ghost scaffolding [later];
      diff card [now]
owner ── keep | reject ──> POST …/keep | /reject        ≤ 2 s, one tap;
      evidence one click ≤ 1 s
core: keep → promote (§2.3): branch, taste_keep scored, vocab.word.added,
      character notified; reject → branch retained, word stays coming-soon;
      both audited
```

Character-filed orders are the same shape with `origin.character_line` set: a
character hits a vocabulary edge, says so in one sentence, and the order is
filed with the same packet mechanism (V §"The work order is the bridge"; T:
work orders are *linked control* — the order carries its context). Kid-filed
orders are chips: `origin.channel = "chip"`, no utterance field exists for the
actor class (§4.1), and a WO the kid requests that needs the computer is filed
*addressed to Casey* — Magnus proposes, Casey confirms (X C8/D4; G §3 09:06).

### 3.2 The overnight plan, through the queue, to the morning report

From D §1–§3 and T §"Safe mistakes", with R §9's lane layout doing the
scheduling, P's mechanisms making it physical, and the report carrying the
round-2 merge (X C2/C11/D6, G §2).

1. **Plan slate — pre-night, first-class** (D §21:02, but starting at the
   first chip, 20:47): chips and negotiated intentions are `Task` rows with
   `night: None`, `state: "slated"` (RV patch 11); the slate is one screen —
   intentions with owner character, **the ask** (`cost_estimate`, marked `[e]`
   until measured), the builder's one-line take as a **capability row**
   ("First layout. No record — I've built 0 of these for you." — derived from
   `vocab.call` counts, §1.5; G §1 20:31), one budget bar with counters under
   it and money scoped to hosted calls ("$0.00 (local)" is itself a product
   statement — X C9/R18), and **the work-order ask as its own line** ("Work
   orders: 3.0 h — approved separately"; on night one the line exists to say
   it is empty — X C11; G §1 20:31). If the ask exceeds the bar, builders cut
   their own lists first — recovery is a proposal, never an error (D); a cut
   row goes `state: "cut"`, requeued for tomorrow. Transaction ≤ 30 s, Workshop
   clock, no cancel — before the night a slow decision is free, after it it
   costs (X C13).
2. **Start the night + pre-flight** (D §21:14; G §2 21:18): `night.started`;
   the core sets the power mode (§5.5) and answers in computer register, ten
   seconds, before the client detaches:

   > PREFLIGHT: lane free (load 0.3) · queue 2 items · client detach: on close
   > or 22:00 timeout, whichever first · plan starts on time.

   If a foreign job holds the GPU: **start late** (queue admits when the lane
   frees; re-checked on a 10-min tick) · **start degraded** (scripted checks
   only, renders deferred) · **cancel**. The pre-flight **may propose, never
   decide** (G §2). If telemetry is blind it says so ("status will be
   `did not run — unknown`"), never guesses.
3. **Lanes** (R §9): the CPU lane runs continuously (build123d parts, analytic
   checks, mesh cleanup, USD/glTF assembly, CPU-capable SFX) and never waits on
   the GPU; the GPU lane batches by model — draining each warm model's queue
   before swapping — **under a per-model load cap enforced at batch admission**
   (§1.9, §5.5; RV patch 3). Big batches start on client detach **or the
   deadline** (§1.9 `detach_deadline`; X R19). Critic checks interleave after
   each batch. **Solver placement** (P §2.1): room-scoped re-solves are the
   only day-clock solver work; full solves are night jobs, full stop — the
   solver is ~38 min on the authors' x86 and likely worse on 2.6 GHz ARM
   (P §1/P §7-2). **Magnus's lane** is a reserved slice inside the night's
   lane, capped by his fixed hour, scheduled *into* the warm batches rather
   than alongside them — two parallel queues on a one-model-at-a-time lane is
   precisely the thrash the scheduler exists to prevent (X G10/R6; G §3).
4. **The sealed-bet loop** per task (D §23:04, the fish-crate bet): edit
   (typed vocab call) → predict (sealed, hashed, **committed before the render
   job exists**, §5.1, with `render_spec` inside the payload, §1.7) → preview
   (batched rungs, served by the warm scene server and the stage cache — a
   night's image-to-3D jobs batch so the Thor never swaps models twice) →
   geometry check → critic → keep or revert, **as a verdict write** (§1.7's
   three-writer rule; the owner scores taste in the morning). Each loop is
   capped by the per-cycle rail. The recipe diff is 412 bytes.
5. **Throttling is graduated** (T; X R6): at 80% of the night rail, builders
   stop **opening batches and branches** and finish-or-drain what is running;
   at 95% they stop and report; at 100% or kill switch, current branches are
   committed and the report is written immediately with whatever state
   existed. The queue stops cleanly at the bar; unrun batches requeue for
   tomorrow (`task.state: "cut"`).
6. **Questions at 3am** (T §"The open-question policy"): the night cannot ask.
   Two channels only — **park it** (a named question attached to a branch) or
   **assume the conservative reading**, with the assumption recorded as
   `assumption.recorded` **attached to the branch/card it replaced** (RV
   patch 2; X S12), not merely mentioned in the report. It never guesses and
   never stalls the queue behind it. **At most 3 blocking questions may
   exist**; a builder about to park a fourth parks the *task* instead, and the
   report says so in one line (G §4.5).
7. **Failure narration** (D): every recovery narrated by the builder in one
   line, ≤ 6 lines per builder per hour, only on state change — enforced by the
   core's `line.spoken` budget (§5.6). Every failure produces a card with an
   artifact, not an error.
8. **Pre-bake for the morning** (RV patch 14): before stop, the CPU lane
   compiles each morning option's **LOD scene manifest** (glTF near-term,
   §4.2) at the comparison rung, emits the comparison renders, and encodes the
   filmstrip/timelapse clips through NVENC (P §3) so the morning is instant and
   60 fps-class on the ProArt — the flip is a pointer, the re-stream is a
   cached manifest, and neither waits on a render (D §"The three clocks").
9. **Report build** (at stop, before the owner opens anything — the morning is
   instant because the night already did the rendering, D §"The three clocks"):
   static HTML+JSON over the ledger, with a **text mode that is the same ledger
   read** (G §4.2). Order of the page (X C2/D6/G2 — RV patch 2):

   1. **Status line, computed** (§3.4): `ran as planned | ran short | ran
      degraded | did not run` + a one-line reason in the last case.
   2. **Failure line** — always present, even when it is "nothing failed";
      failures lead (T §"Failures lead the report").
   3. **The cut named, not just the spend** (X C11): the first content line
      states what was dropped and any wall-clock overrun ("1.7 lane-h of the
      ask was cut at the 80% bar; the north-lantern batch is re-queued for
      tonight"). This is why tasks store the ask (§1.9).
   4. **Night numbers** — no single prediction score (killed; X C2):
      `8 h 20 m · 61 recipe edits · 23 sealed bets · 17 kept (9 critic-keeps,
      8 owner-keeps) · 4 reverted · 2 parked · 5.3 of 5.5 GPU-h · 6 model loads
      (budget 6) · stage-cache hits 71% · MAXN`.
   5. Filmstrip (cached renders + pre-encoded clips), the three branches
      **plus the two standing options** (keep yesterday, back to the plan),
      parked questions **triaged top-3 + a count** ("31 more, none blocking" —
      G §4.5) with assumptions on the same cards, landed work orders,
      model-change notices (T), lost time if the box rebooted.
   6. **The tally, per builder × claim type, with denominators**, recency-
      weighted, percentages only where the denominator supports one (T §"Sealed
      predictions"); on night one it says the empty thing ("not taste yet;
      that is a start" — G §1 07:12).
   7. **The three-number line** (G §4.3): `5.3 h of your Thor · $0.00 hosted
      (local) · 2 h of your attention (9 decisions; budget 10)`. The attention
      number is decisions the morning asked of you, and a morning may ask for
      ≤ 10 — if the night would produce more, the cut happens at the queue
      (§3.2.6), not at the reader.

### 3.3 Failure and recovery paths (the night's own handling)

All [now], all in the log (D §"The night's failures and recoveries"); each is
an audit event plus a card:

| Failure | Handling |
|---|---|
| image-to-3D returns hollow meshes | **the geometry check catches it before the critic** (§2.3.3 — the known failure mode, R §2; X R10); retry one seed; fall back to recolored library crate; park a note |
| a batch stalls on lane contention / the model-load cap (the likely failure on a 122 GB unified box — X R17) | queue delay, not a model swap: the batch waits, admission re-checks on the 10-min tick, the morning says `ran degraded` with the stall named (G §2) |
| critic OOMs in a big batch (defence in depth, unlikely on 122 GB) | scheduler demotes to the smaller local critic; verdicts marked `verdict@low-res` **on the evidence cards** and the report says so in one line (D §03:5x, amended by X R17) |
| a constraint breaks (drip line) | constraint check fails *before* the critic; auto-revert; the sealed prediction still resolves — that bet is lost |
| budget bar reached with work unrun | queue stops at the bar; `task.state: "cut"`, requeue for tomorrow; report's first content line names what didn't get done |
| reboot / power cut | durable queue; on boot resume from the last sealed step (§5.2); the status line and `lost_minutes` are computed from heartbeats, never hidden (§3.4) |
| the client never detached | batches start at the deadline anyway (§1.9); the morning names it ("the ProArt stayed attached; the 22:00 timeout started the batches 40 min late" — G §2) |
| owner mid-night peek, server killed | feed is stateless over the ledger; kill -9 test in §5.4, extended to the status line |

### 3.4 The gap states: busy box, dark box, reboot, absent client

The states between "good night" and "no night" (G §2; X G2/R19 — the brief's
mandatory coverage). Three pieces and a rule.

**Pre-flight** — §3.2.2: after `night.started`, before detach; checks lane
load, queue depth, telemetry; proposes start-late / start-degraded / cancel;
never decides. Admission is re-checked on a 10-minute tick, so a foreign job
that ends at 23:00 still yields a late start, recorded by the heartbeat.

**Heartbeat** — the core writes `night.tick` (a wall-clock row plus every
sealed step) for the whole window. **The morning's status line is computed
from the ledger, not written by whoever is awake to write it** — which makes
it survive the failure it is describing (G §2). Extension of the kill -9 test
(§5.4): kill the service mid-night in several states; every morning's status
line must be the correct one of the four, from heartbeat gaps alone.

**The four mornings**:

| Status | First line | What happened |
|---|---|---|
| `ran as planned` | `ran as planned · nothing failed · 2 parked` | the night of §3.2 |
| `ran short` | `ran short — 1.7 lane-h of the ask was cut at the 80% bar; the north-lantern batch is re-queued for tonight` | budget bite or partial outage; the cut is named (X C11) |
| `ran degraded` | `ran degraded — one batch stalled 41 min on the lane (model-load cap hit at 02:12) · 3 verdicts ran scripted-only — see their cards · nothing failed outright` | contention/thrash, degraded verdicts, late start after the detach deadline (G §2) |
| `did not run` | three variants, because from the owner's chair they are three different facts: **off** ("the Thor was off from 21:30. Nothing ran; nothing was lost. Your plan is unstarted, unchanged.") · **busy** ("the GPU spent the night on your render job. Ours queued and was never admitted.") · **no plan** ("no plan was started.") | dark ≠ asleep ≠ busy, stated in **words under the picture**, never colour alone (X G5) |

Every `did not run` morning ends identically: the plan is re-offered **verbatim**
— *start now · tonight · drop it* — one tap, because the plan is a recipe,
kilobytes, and survives every one of these nights by construction (X R20). If
telemetry was blind, the status says `did not run — unknown (no telemetry)`; a
status line may be uncertain, never fabricated.

**Reboot mid-night**: §5.2's boot sequence resumes from the last sealed step if
rails and the wall window allow; the morning then reads `ran short` with
`lost_minutes` named. Dark the whole window → `did not run (off)`.

**The client offline / late**: presence is a durable fact (`client.attach` /
`client.detach`, §1.8); big batches start on detach **or** the deadline; the
client is **a viewer of a named commit, never a holder of state** (X G9) — a
mid-night reconnect gets the ledger plus a commit name, and if the branch has
moved, one line ("the branch is 12 commits ahead of this view — re-attach")
where the line is instant `[b]` (a ledger read) and the re-attach is a
`since_version` delta fetch (§4.2), honestly unmeasured until the spike times
it (X R1). Ghost scaffolding, when it ships [later], previews against the
current commit, never stale geometry.

### 3.5 Cold start: the first evening and the melt (G §1)

On night one the only honest currency is the sealed guess and the measured
number; every claim carries its zero denominator, every render its measured
time.

- **The empty project** opens to one panel over an empty store and the
  Companion's first line ≤ 2 s `[b]` (it is a ledger read): "First night. I
  have nothing on you — 0 of 0. Four ways to start; pick one and I'll learn
  from what you keep." The four starters are **seeds, not guesses**
  (`harbor hamlet · seed 4471`, …), each chip carrying its seed on its face.
  No adjective about the owner; exactly one offer of choices. Test in §6.1.
- **Ask-mode**: for the first N decisions the system asks rather than infers
  (X G1) — one question at a time, each a **two-chip choice over two
  artifacts** ("Deep joints, or flush?" — two crops, never two adjectives
  floating free), each answer one tap `[b: ≤ 1.5 s]` writing a `taste_note`
  with author and reason code. Cold start *is* taste acquisition. Bounds: ≤ 6
  questions in the first session; any question skippable and a skip writes
  nothing; no question is about the owner; a second question collapses into
  the slate, never queues in the owner's face (G §1 20:12).
- **Sealed guesses**: the two-observation gate forbids pretending to a view,
  not betting — night-one predictions seal with `confidence: "guess"` and
  `basis: "0 observations"` (§1.7) and are scored like any other bet, so the
  tally is honest from row one (D §9; G §1 20:44).
- **The melt is mechanical**: questions stop for a builder the moment that
  builder holds two observations on a reason code; `guess` becomes a real
  claim the same way; nothing is switched off by hand. The first week's table
  (G §1.9) is then a prediction the tests can falsify, not a schedule.
- **Morning one** frames low N honestly ("You chose 4 of 6 times. That is not
  taste yet, that is a start"), replaces the slate's `[e]` fields with
  measured numbers in a **"The box"** section (onboarding doubles as the
  spike's first data collection — G §1 20:04), and the branch set already
  contains the two standing options (§1.2).
- **The calibration batch** runs as the queue's third item on idle nights,
  sized to the unused lane: the first members of the critic reference set
  (seeded defects) through the scripted checks — the cheapest data the project
  will ever buy (G §1; RV patch 15; §1.9). Until a critic is chosen and
  measured, every automated verdict is a scripted check carrying
  `verdict@scripted` on its face, and no defect check sits on the critical
  path of a daytime moment.

---

## 4. APIs

### 4.1 Transport, auth, clocks

HTTP/JSON + SSE on the LAN; the same API serves the ProArt client, panels
(web or Theia), character runtimes and engineer seats. **Token classes carry an
actor** (RV patch 8): `owner` tokens are issued *per actor* (`casey`,
`magnus`) — the actor is a fact in every audit event and gates §4.2's
actor-scoped endpoints; `panel` (read + SSE); `seat` (MCP tools only, scoped
to one attempt). Voice is [later]; every endpoint here has a text+click caller
today (D §8). **Kid actors cannot submit free text**: `/v1/call` rejects an
`utterance` field from a `magnus` token at the schema, audits
`call.refused` — the privacy rule is structure, not policy (X C7; T §"The
privacy boundary").

Service budgets by clock (D §"The three clocks" — nobody waits on the wrong
clock), `[b]` = budget (testable), `[e]` = estimate, not a promise (X R1):
Talk ≤ 2 s `[b]` (plan items, keep/reject, chips, report's first line);
Watch ≤ 5 s per card `[b]` (pre-render, cache, stale-then-fresh); Workshop
≤ 60 s `[b]` with progress and a cancel, else it goes to the night queue.
Compile ≤ 20 s `[b]` (Workshop clock: progress + cancel — a 20 s compile is
not a Talk action, X R2); confirm readable ≤ 5 s `[b]`; report first paint
≤ 3 s `[b]` (text mode identical); branch flip ≤ 2 s `[b]`; apply ≤ 10 s
`[b]`; **re-stream after apply ≤ 15 s `[b, measurement-gated — X R1]`**;
initial world ≤ 8 s warm `[e]`; per-edit delta < 100 ms network `[e]`;
evidence card ≤ 1 s `[b]` (D §4; P §2.3-4/§3; RV patch 14).

### 4.2 Endpoints

| Endpoint | Method | Caller | Purpose |
|---|---|---|---|
| `/v1/call` | POST | owner client | utterance + client view → pkt; **or chips `{chips: [...]}` (kid actors; free text refused by actor class)**; returns `question` XOR `draft` (compile ≤ 20 s) |
| `/v1/work-orders/{id}/confirm` | POST | owner | `{answer: "go"\|"no"\|"edit", …}`; Idempotency-Key; confirm carries the two-line price |
| `/v1/work-orders/{id}/keep` `/reject` | POST | owner | terminal decision; ≤ 2 s; scores outstanding `taste_keep` predictions (§1.7) |
| `/v1/work-orders` | GET | panels | board view: state, confirm line, budget, estimate, evidence (D §5.5) |
| `/v1/questions/{id}/answer` | POST | owner | one-tap answer to a parked question |
| `/v1/slate` | GET | owner/panels | the pre-night slate: slated tasks, asks `[e]`, capability rows, WO line, the bar |
| `/v1/tasks` | POST | Companion | file chips/intentions as pre-night `Task` rows (slate cuts rewrite them) |
| `/v1/night` | POST | owner | start the night (slate → queue); **response carries the pre-flight line** (§3.2.2) |
| `/v1/night/{id}/stop` | POST | owner | kill switch: stop all, commit branches, write report now (T) |
| `/v1/nights/{id}/report` | GET | panels | static report (html / json / text mode); first paint ≤ 3 s |
| `/v1/branches` / `/v1/branches/{id}/apply` | GET/POST | owner (**actor-scoped**) / panels | morning A/B/C + standing options; apply = head move ≤ 10 s; **a kid actor's apply creates `branch.proposed`, pending owner confirm** (X C8/D4) |
| `/v1/budget?night=` | GET | all | rail snapshot + bar state + load-cap counters |
| `/v1/vocab/call` | POST | characters | typed word call → validated RecipeEdit (refusals audited) |
| `/v1/vocab` | GET | characters/panels | words incl. `coming-soon` edges, taste notes (read-only), capability view (§1.5) |
| `/v1/predictions/seal` | POST | characters | seal before render; confidence gate + `render_spec` enforced (T; X R7) |
| `/v1/predictions/tally?builder=&claim_type=` | GET | panels | **tally read API** (RV patch 20): per builder × claim_type, denominators, recency-weighted — the ledger line on any card is one call (X S15/G5) |
| `/v1/ledger/taste` | GET | characters/panels | author-scoped read; never writable via this path |
| `/v1/ledger/taste/export?author=` | GET | owner | one-action export: the author's rows + reason codes + artifact refs |
| `/v1/ledger/taste/erase` | POST | owner | one-action erase (§1.7 mechanism); Idempotency-Key |
| `/v1/ledger/taste/ratify` | POST | owner | ratify Magnus's keeps (asked once, §1.7); Idempotency-Key |
| `/v1/night/{id}/tasks` | POST | Companion | file the slate's tasks (pre-night path is `/v1/tasks`) |
| `/v1/questions` | POST | characters | park a question (name + branch + two options) |
| `/v1/assets` | GET/POST | panels/scheduler | library with licence + dependency-terms column (D §5.6); re-runs with a different model labelled "reinterpreted" |
| `/v1/world/scene?branch=&lod=&since_version=` | GET | ProArt | compiled glTF/USD manifest per (branch, LOD) — thin client streams from this (V §"The pieces" #8; R §8); **`since_version` returns a KB-class delta (op list) instead of the whole manifest** (P §2.3-4; RV patch 14); glTF is the near-term wire (spike bpy builds `WITH_USD=OFF`, P §2.3-4), USD when the build flag returns |
| `/v1/events` | GET (SSE) | all | the stream, §4.3 |
| `/acp/proxy/{attempt}` | GET (SSE/WS) | Theia/Zed | read-only (default) front-end onto an engineer session (§2.4) |
| MCP tools (§2.5) | stdio/HTTP | seats | the engineer's only door into project state |

### 4.3 What streams to the client

`GET /v1/events?since_seq=&types=` — SSE with heartbeat; `since_seq` makes
reconnects and rewind the same operation (the feed is the log, D §02:07;
rewind free, **never fast-forward of live work** — D). Mapped event types → UI:

| Stream type | Rendered as | Clock |
|---|---|---|
| `card` (bet resolved: who · change · sealed prediction · verdict · kept/reverted · thumbnails) | night-feed card, legible ≤ 5 s | Watch |
| `wo.state` | board chip; toast when `landed` | Watch |
| `question` / `assumption` | one-tap card; an assumption renders on the same card as the question it replaced (X S12) | Talk |
| `plan.chip` | slate chip update (write path is `/v1/tasks`, §4.2) | Talk |
| `budget.threshold` / `budget.spend` | bar colour and fill (the state is also a word) | Talk |
| `line` | character utterance (≤ 6/builder/hour, state-change only, §5.6) | Talk |
| `world.dirty` | re-stream scene manifest — **carries `{branch, head}` so the client fetches a `since_version` delta, not everything** (RV patch 14) | Watch |
| `branch.proposed` | owner-facing confirm card for a kid's branch choice (§4.2) | Talk |
| `ghost.pointer` | [later] ghost scaffolding for a landed preview, against the current commit (D §07:26; X G9) | Watch |
| `report.ready` | morning notification | Talk |
| `job.progress` | workshop progress + cancel affordance | Workshop |

Panel rule (X G5; G §4.2): **every verdict is a word, never a colour alone**;
cards are labelled regions with a stable reading order; the whole night is
browsable as text over the ledger. The ProArt additionally receives the
compiled scene via `/v1/world/scene` (glTF now, USD later); previews render on
the client's own GPU (V §"The pieces" #8).

---

## 5. Durability

### 5.1 Write path

Single writer, one SQLite transaction per state change, WAL + `synchronous=FULL`
(fsync before the change is claimed durable): append the `audit` row and update
projections atomically. **Side effects happen only after commit** — a job is
enqueued, a seat started, a render dispatched strictly after the event that
justifies it exists on disk. The load-bearing special case: `prediction.sealed`
(committed, fsynced) **before** the render `job.enqueued` is committed — that
ordering is what makes a sealed bet unforgeable, and it survives crash by
construction (D §23:04 step 2: hashed into the ledger *before* any render
exists). Sealing the full payload including `render_spec` strengthens this: a
verdict is re-scorable against the same inputs (X R7).

### 5.2 What survives a reboot mid-night, and how a run resumes

Survives (all in the DB + blobs): every sealed prediction and verdict, every
committed recipe version and branch pointer, work-order states and attempts,
budget spend, parked questions and recorded assumptions, client attach/detach
facts, night heartbeats (`night.tick`), the audit log to the last committed
event, all artifacts (write-once, tmp+rename), **and the stage cache**
(content-addressed on disk, verified by hash — §1.9). Does not survive:
GPU-resident models, TCP connections, **resident scene-server processes
(rebuilt from recipe version + stage cache — §1.9)**, half-finished renders
(atomic — re-run, never resumed), and the predictions of steps that never
reached a render: they die **unsealed and unscored** (never invent a verdict
for work that did not happen — D §6: honest idleness; T: failures lead).

Boot sequence (`core.boot` → … → `core.recovered`):

1. Open DB; if projections are dirty, rebuild by folding `audit`
   (`projection.rebuilt`). An erased author's rows fold to nothing (§1.7).
2. Verify artifact hashes referenced by `landed` work orders and report cards;
   a broken reference fails loud (`integrity.failure`) — a night that cannot
   show its work did not happen (D).
3. Recovery pass over jobs: expired `lease_until` with no heartbeat →
   `job.requeued`. GPU renders re-run from seed (deterministic); CPU steps
   (CAD, USD assembly) replay byte-identically (R §1); stage-cache hits make
   both cheap (§1.9).
4. Attempts: seat process alive (checks claim token) → re-attach and keep
   streaming; else `attempt n+1` in a fresh seat — attempt ids never reused.
5. Nights: if `running`, rails unexhausted and the wall window open → resume
   from the last sealed step (the queue is durable; D §"The night's failures");
   else stop cleanly and build the report, **with the status line and
   `lost_minutes` computed from the heartbeat gaps** (§3.4) — never hidden
   (D, T, G §2).

### 5.3 Idempotency

- `Idempotency-Key` on every owner POST (`confirm`, `keep`, `reject`,
  `night.start`, `question.answer`, `call`, `taste.erase`, `taste.ratify`):
  the key maps to the committed event; a replay returns the original result,
  never a second state change. A doubled "Go" cannot start two attempts.
- State transitions are compare-and-swap on `(entity, expected_state, seq)`;
  a stale transition fails closed and is audited.
- Jobs are deduplicated by `hash(request + attempt)`; **stage-cache keys are
  ⊆ (recipe version hash, engine pin incl. config, stage name, dep keys)**
  (§1.9), so a re-run that reproduces converges on the same artifact instead of
  duplicating — and cannot be defeated by engine-config drift, because the
  config is pinned inside the key's inputs (RV patch 13).
- MCP tool calls carry the attempt id; retries are idempotent by tool
  semantics (`render.request` with the same seed returns the same artifact).

### 5.4 The kill -9 test (acceptance for this whole section)

From D §02:07 — kill -9 the feed server mid-night, reopen: the feed must render
from the ledger alone, complete to the last sealed bet. Concretely: every panel
is a stateless reader over `/v1/events` + GETs; there is no panel-local state
that is not derivable; the report is regenerable from the log at any time.
**v2 extension (G §2):** kill the service mid-night several times, in different
states (mid-batch, mid-admission-wait, idle); every morning's status line must
be the correct one of the four, derived from heartbeats alone. Test cadence: in
CI, nightly, and before every phase gate.

### 5.5 Budget mechanics (decision §0.3, T's open question answered; §0 #13's load cap)

Units: rails are `(gpu_minutes, hosted_cents, wall_minutes)`. GPU-minutes come
from the model registry's measured cost table (per model id), not from
wall-clock, so a cheap CPU-lane hour does not eat the GPU bar. Defaults: night
rail 360 GPU-min (the 6.0 h bar of D §21:02, owner-slidable to 5.5 h),
`hosted_cents: 0` unless the owner explicitly enables hosted engineers for the
night (then a hard cents cap), wall 560 min. Local wall-clock and CPU work are
effectively free and deliberately not the scarce axis (T §"Open decisions" #4:
"wall-clock on the Thor is nearly free; hosted model time is not").

**The fourth rail (RV patch 3): a per-model load cap per night**
(`Night.load_budget`, default 1 load per model), because the hardware's binding
constraint is weight-swap thrash, not VRAM (R §9; X C9/D5; P §6-5) and none of
the three spend units can count loads. It is enforced at **batch admission** —
a batch that would exceed a model's load budget waits for the drain, it is not
started and killed — and the night line reports the count against the cap
(§3.2.8.4).

Enforcement is **before spend** (T, citing AWS AGENTCOST07): admission control
projects each job's cost from the registry and refuses what a rail cannot
cover; the seat hard-kills at the per-attempt rail. Degradation order at the
rail, answering T's "what gets dropped first":

1. at 80% — **stop opening new model batches and new experiment branches; drain
   and finish or park what exists** with a one-line reason (graduated, not
   binary — T: "binary shutdown is how you get a morning report that says
   nothing happened"; X R6 maps the graduation to batch admission);
2. drop queued exploratory generative batches not needed by a landed preview or
   an open work order (requeue for tomorrow — D §05:0x);
3. at 95% — stop new work entirely; close out in-flight branches at their
   current rung;
4. at 100% or kill switch — commit branches, write the report immediately.
   Never dropped: merge-gate evidence for landed work, parked questions, the
   report itself.

**Power modes** (P §5, RV patch 16): the core owns `nvpmodel` as part of the
night window — MAXN (+`jetson_clocks`) from `night.started` through the morning
burst, day mode 2 (90 W) when interactive, mode 3 (70 W) the quiet-afternoon
fallback — one `nvpmodel -m` call each way, logged as `power.mode.set`, with
the active mode recorded beside every timing row (V's carried-over "measure
with the box's load beside the number" rule). If sustained throttling shows up
under MAXN, dropping to 120 W is a measured decision, not a guess (P §5).

### 5.6 Interruption and line budgets (enforced in the core, not the prompt)

Unchanged from v1. From T §"Failure modes": a builder may interrupt only for a
blocked decision, a budget-rail event, or a hard failure — at most one
interruption per builder per 20 minutes; the rest queue, and overnight
everything parks until morning. Narrations (written to the feed, addressed to
nobody) are separate: ≤ 6 per builder per hour, state-change only, no repeats
within a session (D; X C3/C4 — the merge v1 already carried). The
`line.spoken` audit event is emitted only after the budget check passes; the
check is code, because prompt instructions are not enforcement (T: "each rule
is placed where it can actually be enforced").

---

## 6. Build order

### 6.1 The smallest end-to-end slice — "one crate night"

One character, three vocabulary words, one work order, one engineer (the
brief's floor). Plain Python + web panels; no 3D client (D §8: [now] = phases
3–4).

- **Core skeleton**: SQLite ledger + audit events + projections, FastAPI,
  SSE `/v1/events`, the endpoints of §4.2 marked (call, confirm, WO CRUD,
  vocab/call, predictions/seal, night, report, budget, tasks/slate).
- **Recipe store**: versions, branches, edit validation, constraint checks
  (pre-render, analytic), diff rendering; the **node registry projection**
  (entries ↔ node ids — needed for `/v1/call`'s referent resolution even in
  text+click form).
- **One character — the Prop-maker** (chosen because D §23:04 specifies its
  loop in full): a small local LLM runtime (scripted loop acceptable in the
  slice) making typed calls, sealing predictions **with `render_spec`**.
- **Three words** (schema subset of §1.5):
  `props.harbor.crates {count 1–48, style enum[plain, weathered, stained],
  from_library 0–count, seed}`;
  `props.harbor.racks {count 1–24, length_m 0.5–6}`;
  `material.wood.weathering {wear 0–5, tone enum[pale, gray, dark]}`.
- **One work order**: the Prop-maker hits the param edge of
  `props.harbor.crates` — "lids and rope handles aren't in my hands" — and
  files WO-15. Compile from a text+click context packet (selection by click,
  gaze omitted, referents via the registry), one-line confirm **with both
  price lines**, queue, run.
- **One engineer — `aider-local`** (zero marginal cost, V) behind the full
  adapter: worktree + seat + MCP tools; implements the generator change and a
  test suite; delivers.
- **Merge gate (minimal)**: deterministic rebuild, unit tests, geometry check,
  rung-2 render, **scripted checks as the critic (`verdict@scripted`, with the
  slice's measured FP/FN band stated — RV patch 15)**, licence scan of the two
  library crates (incl. dependency terms), budget audit.
- **Landing**: preview card on the work-order board, keep →
  `props.harbor.crates` v2 gains `{lids: bool, handles: enum[none, rope]}`.
- **Night runner (minimal)**: task queue with per-task + per-night rails,
  sealed bets, heartbeats + the computed status line, morning report page with
  the status line, the cut named, failures first, and "The box" section.
  Per-cycle graduated throttling, the load cap and the kill switch can lag one
  step.

**Slice acceptance**: (a) the kill -9 test (§5.4), **status line included**;
(b) the two-referent test — an order with two plausible referents returns a
question, not a plan (D §21:08); (c) a sealed prediction exists in the DB with
`sealed_at` strictly before its render job's enqueue; (d) the report renders
with zero panel-side state; (e) **the first-run test** (RV patch 17): fresh
project → first line carries a zero-denominator, no adjective about the owner,
exactly one offer of choices; ≤ 6 ask-mode questions, strictly sequential;
(f) every confirm line shows both price lines — a one-line estimate is a build
failure (G §1).

### 6.2 What follows, in order

1. **Adapter hardening + merge gate at full strength**: ACP client + proxy,
   permission policy, hosted engineers (`claude-code`) behind the same seam;
   the full evidence bundle (degraded flags on cards).
2. **Scheduler tiers**: hot/warm/cold with **per-family environments**, batch-
   by-model with drain under the **per-model load cap**, CPU lane, provenance
   stamping on every artifact, critic demotion path (R §9; 3D §6; RV patches
   3/12), **power-mode ownership at night begin/end** (P §5).
3. **Warm scene server + stage cache + partial regeneration** (P §2.3-1..3; RV
   patch 4/13 — before the compiler, because the compiler's outputs and the
   morning pre-bake both sit on it): resident Blender owning the open scene;
   `hash(recipe ⊕ engine pin ⊕ stage ⊕ dep-keys)` stage cache; the dirty-set
   contract; measures: p50/p95 edit→preview latency batch-vs-warm, Blender
   process starts per night (target 1–2), stage-cache hit rate, peak RSS per
   warm scene (P §6-1/6-2, §7-3).
4. **Recipe → glTF/USD compiler + the ghost/LOD path**: deterministic emission
   (sorted prims, no timestamps), one layer per concern, provenance in
   `customData`, LOD/impostor export walking placeholders + room solids +
   scatter densities (P §2.3-4), the `since_version` delta channel, the
   nightly pre-bake of each morning option's manifest, **glTF-first** (spike
   bpy has `WITH_USD=OFF`; USD when the flag returns), NVENC clip artifacts
   for the filmstrip (R §8/§10.1; RV patch 14). This is also what
   `/v1/world/scene` serves.
5. **The rest of the crew + full vocabulary + cold start**: Architect,
   Landscaper, Critic, Companion; per-claim-type track records with
   denominators; the two tallies surfaced on cards (T); ask-mode questions and
   their mechanical melt; capability rows (§3.5).
6. **Critic selection + calibration spike** (RV patch 15; X R4/S6): choose the
   vision critic, build the ~30-render seeded-defect reference set, measure
   FP/FN against the band, gate entry into service; retire `verdict@scripted`
   only then.
7. **Taste ledger surfaces**: closed reason codes, author scoping, one-writer
   verdict path, tally API, **export/erase/ratify endpoints** (§1.7, §4.2),
   "why?" one tap on any artifact (T, D §4 moment 9).
8. **Context packet + compiler at full strength**: gaze rays when the client
   exists; referent resolution through the node registry with the question
   rule; utterance purge policy.
9. **Generative stations behind the scheduler** (RV patch 12; 3D): **TRELLIS.2
   via the ComfyUI native path** (MIT code + MIT ungated weights; PBR GLB out;
   no compiled CUDA extension; seeded — 3D §4.1/§8) **with TripoSR as the
   parallel MIT baseline** (it forces the provenance/seed/mesh-cache plumbing,
   3D §4.2); **textures via TRELLIS.2's shape-conditioned texturing — not
   deferred** (3D §4.8; X R12); StableMaterials + SDXL (OpenRAIL) with CC0
   libraries for scene-wide materials (R §3); keep modly's FastAPI/MCP
   *pattern* (3D §4.3); ACE-Step + SAOS per R §5; MoMask flagged (R §4). The
   phase-1 spike measures TRELLIS.2 **on this box** — wall-clock at 512³ and
   1024³, PBR fidelity through a Blender round trip, peak unified memory (3D
   §8); published H100/A100 numbers are not scheduleable (3D §1; X §4).
10. **Budget rails graduated + kill switch + load cap** as specified (§5.5),
    plus per-tool risk ratings driving auto-approval (T §"Research transfer";
    X C10: approve the slate tonight, approve each risky tool once, ever).
11. **Magnus mode**: chip grid via `/v1/call` (free text refused by actor
    class), actor-scoped apply as proposals, counts-not-percentages, his
    reserved lane ending at the fixed hour, ratification flow, one-action
    export/erase (T §"Magnus at the controls"; G §3; RV patch 8).
12. **Thin client** [later]: in-world view, plan chips, ghost scaffolding,
    branch flips in-world, phone peek, voice (D §8).

---

## 7. Decisions where the sources disagree or defer — and why

1. **CAD authoring API: build123d, not CadQuery.** *(unchanged)* V says
   "e.g. CadQuery" — an example, not a verdict. R §1 researched it: build123d's
   typed, property-based algebra is easier for an agent to write *and for the
   review pipeline to statically check* (mypy-clean by policy), it officially
   supports linux/aarch64 (the exact platform), and it exports glTF with
   material UVs headlessly. CadQuery stays installed as a readable secondary
   and a few-shot corpus — both share every binary dependency, so keeping it
   costs nothing (R §1). The merge gate's static-check step is materially
   weaker under CadQuery's string selectors; that decides it.
2. **Prediction `claim_type` set.** *(unchanged)* Take the union — seven world
   types plus `taste_keep` — closed but owner-extensible; adding a type is a
   schema change with a migration, not a runtime write. v2 adds the explicit
   `namespace` split and the two gates (§1.7), fixing X §6 5's finding that T
   conflated claim types with reason codes.
3. **The nightly money rail.** *(amended)* Decided in §5.5:
   GPU-minutes + hosted-cents + wall-minutes, defaults 360/0-cents/560, hosted
   spend off unless explicitly enabled, degradation order fixed — because the
   Thor's local compute is effectively free (T says so) and a single "dollars"
   rail would either throttle free local work or ignore the one scarce
   resource that can hurt. **v2 adds the per-model load cap** (§5.5): all three
   technology-side documents agree the hardware constraint is weight-swap
   thrash (R §9, X C9/D5, P §6-5), and a spend rail cannot count loads.
4. **Magnus's taste never folds into Casey's.** *(unchanged)* `author` is part
   of every taste row's key, slices read into prompts are author-filtered, and
   his rows are exportable/deletable in one action (now with a real mechanism,
   §1.7). The alternative — a house taste — would let a nine-year-old's
   preferences steer the adult's builds with no visible mechanism.
5. **Deadlock arbitration.** *(unchanged)* The Critic wins on `hold`; the owner
   breaks true deadlocks. The Critic's output is checkable; the Architect's
   objection is an opinion. Where the two disagree on a non-defect, the step
   parks as a question.
6. **The ledger stays on the Thor.** *(unchanged)* Any model call receives a
   scoped slice (author-filtered, purpose-bounded), never the whole ledger;
   Magnus's rows — including his `pending_ratification` rows — are never in a
   slice. If hosted taste reasoning is ever wanted, that is an owner decision
   recorded as an audit event, not a default.
7. **No LangGraph (or any orchestration framework).** *(unchanged)* The audit
   log with gapless `seq`, fold-to-rebuild projections, and job leases *is*
   the checkpointing — every panel and both reports replay from it. Revisit
   only if multi-step agent graphs need time-travel debugging the log cannot
   give.
8. **Interactive previews vs batch-by-model.** *(amended)* The hot tier
   (companion LLM, critic) is reserved for interactive work and always
   resident; during the day a Workshop request may preempt a warm-tier load
   (bounded to a swap budget per hour) **and is served by the warm scene
   server** (§1.9 — the mechanism v1 lacked); at night, after client detach or
   the deadline, batching is strict under the load cap. **Solver placement**
   is part of the same decision: room-scoped re-solves are the only day-clock
   solver work; full solves are night jobs, full stop (P §2.1 — the solver is
   ~38 min on x86 and likely worse on this ARM box). A request that would
   thrash goes to the queue *by design* — that is the third clock rule, not a
   failure.
9. **Recipe storage: event-sourced SQLite, not git-as-database.** *(unchanged)*
   Git is kept for the engine repo and engineer worktrees; the recipe store
   lives in the same transactional ledger as everything else, so a sealed
   prediction, its branch pointer and its budget spend commit or roll back
   together. A derived human-readable mirror (`recipes/*.json`) gives diff
   tooling without a second source of truth.
10. **Utterances.** *(amended)* The confirm line is the durable record; the
    raw utterance is retained only for the owner and only until terminal
    state. v2 makes Magnus's side structural: his token class cannot submit
    free text at all (`call.refused`, §4.1), so there is nothing of his to
    retain — the privacy property is code, not policy (X C7/D4).
11. **Recipe and USD.** *(unchanged)* R §8's verdict adopted verbatim: the
    typed recipe is the source of truth; USD/glTF is a deterministically
    compiled, layered output; the only reverse path is asset import. v2 names
    glTF the near-term wire on build-flag grounds (P §2.3-4) — a substrate
    choice inside the same one-way rule.
12. **The referent chain runs through a node registry** (RV patch 1; RV §1.2.1).
    v1's packet carried node ids, the recipe is keyed by entry paths, and
    nothing mapped between them — the product's signature move could not
    compile. The registry is written by the engine/compiler (the only component
    that knows both keys), stored as a projection, and the packet carries
    resolved referents plus bounded current params. Alternative rejected:
    making entry paths and node ids the same namespace — nodes are finer than
    entries (deck/pier parts), can outlive an entry swap, and are the client's
    native key; conflating them would push Blender-side churn into recipe ids.
13. **Model loads are a rail** (RV patch 3; X C9/D5, R §9, P §6-5). The three
    spend units cannot express "do not load the texture stack forty times",
    and on a 122 GB unified box thrash, not memory, is the failure. Enforced at
    batch admission (X R6's mapping), reported on the night line.
14. **No physics engine: acceptance is analytic** (RV patch 5; X R11). v1's
    "load factor from the sim" leaned on a component nobody chose; R §6's
    SimReady gives schemas, not a solver. `load_floor` is a scripted build123d
    computation from recipe params — deterministic, CPU-lane, recipe-native,
    and re-scorable. A real solver, if ever wanted, is an engine decision with
    its own work order.
15. **Magnus's authority is structural** (RV patch 8; X C7/C8/D4; G §3). He
    gets preview-keeps and question-answers; a branch apply is a real edit, so
    his apply is `branch.proposed` pending owner confirm. Chips-only input is
    enforced by token class in code. His first three keeps are inert until
    ratification. This keeps D §3's emotional beat ("that one") and T's
    authority rule, at the cost of one confirm step — cheap, and visible.
16. **Taste erasure beats payload immutability — once, and only for this**
    (RV patch 9). T promises one-action export/delete; v1's GET-only API over
    an append-only fold made that decoration. v2: erase = one transaction
    (payload redaction + `taste.erased`), fold-excluded everywhere, ids/seq
    preserved. The audit log's immutability is what makes every other promise
    in §5 hold, so the exception is narrow, owner-only, audited, and touches
    no other event type.
17. **The warm scene server is a cache, never a writer** (RV patch 4; P
    §2.3-1). Modeling it as a Job would be wrong (it never completes); letting
    it write would break §1.0's single-writer rule. As a scheduler-managed
    resident resource with audit events, an RSS bound and rebuild-from-cache
    semantics, it gives the Workshop clock without costing the durability
    story anything — it is on the does-not-survive list by construction.
18. **The generative stack follows res-3d where it supersedes res-cad**
    (RV patch 12; X §7's closing ruling). TRELLIS.2 via ComfyUI native + 
    TripoSR baseline; textures not deferred (TRELLIS.2's shape-conditioned
    texturing removes R §2's one genuinely heavy item, the texture CUDA
    builds); per-family environments from the registry, priced into two-line
    estimates (X R16) — a work order that must build a py3.10 conda env before
    its first render *is* a different three hours. modly's FastAPI/MCP pattern
    is kept; its texture path is not.
19. **The morning status line is computed, not narrated** (RV patch 2/10;
    X D6/G2; G §2). Four values + a reason, derived from heartbeats and
    admission waits, so it survives the failure it describes and cannot be
    written by whoever happens to be awake. The alternative — a narrated
    summary — fails the kill -9 test it would be describing.

---

*End of spec v2. Everything above is design; no code outside this directory was
touched, and no sub-agents were started. Built on: V (`vision.md`), D
(`ux-day.md`), T (`ux-trust.md`), R (`res-cad.md`), X (`rev-ux.md`), RV
(`rev-spec.md`), P (`split.md`), G (`gaps.md`), 3D (`res-3d.md`).*
