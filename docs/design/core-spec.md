# SPEC — the core service of builder-ide

Status: design for implementation (2026-10-30). Scope: the durable service on the
Thor that owns **work orders, budgets and approvals, the recipe store and its
history, the model scheduler, the vocabulary, and the audit log**
(vision.md, "The architecture: three layers"). Characters, engineers (coding and
generative agents behind one adapter) and front ends (ProArt in-world client,
Theia, Zed via ACP, web panels) plug into it; none of them own state.

Everything here is buildable with plain Python 3.12 on the Thor (FastAPI +
SQLite + Pydantic v2); no orchestration framework is adopted (§7.7).

**Citation shorthand**

- **V** = `~/src/builder-ide/docs/vision.md`
- **D** = `docs/research/ux-day.md` (ideation A; sections cited by in-fiction time)
- **T** = `docs/research/ux-trust.md` (ideation B; sections cited by name)
- **R** = `docs/research/res-cad.md` (sections cited by number)

Where the sources disagree or explicitly defer a decision, this spec chooses and
says why; the summary is §0 and the reasoning is §7.

---

## 0. Decisions at a glance

| # | Question | Choice | Source tension |
|---|---|---|---|
| 1 | CAD authoring API for the engineer | **build123d primary**, CadQuery kept as readable secondary / few-shot corpus | V says "e.g. CadQuery"; R §1 verdicts build123d (§7.1) |
| 2 | Prediction `claim_type` set | T's six types **plus `weather_read`** (T's own example uses it) | T is internally inconsistent (§7.2) |
| 3 | Nightly money rail (T "Open decisions" #4) | Rails denominated in **(GPU-minutes, hosted-cents, wall-minutes)**; defaults and a degradation order in §5.5 | deferred by T (§7.3) |
| 4 | Does Magnus's taste count toward Casey's | **No.** Separate `author` scopes, forever | T assumed; confirmed (§7.4) |
| 5 | Architect/Critic deadlock | **Critic wins on `hold`**; the owner breaks a true deadlock | T assumed; confirmed (§7.5) |
| 6 | Does the taste ledger leave the machine | **No.** Model calls get scoped slices; Magnus's rows never in a slice | T recommendation; adopted (§7.6) |
| 7 | Orchestration framework | **None.** The audit log *is* the checkpoint | V: "adopt LangGraph only if its checkpointing beats ours" (§7.7) |
| 8 | Interactive previews vs batch-by-model | **Hot tier reserved for interactive**; day previews may preempt warm loads; the night batches strictly by model | D's three clocks vs R §9 (§7.8) |
| 9 | Recipe storage | **SQLite event-sourced store of record** + content-addressed blobs; git only for the engine repo | not specified in sources (§7.9) |
| 10 | Raw utterances retained? | The **confirm line is the record**; the raw utterance is kept for the owner only and purged at terminal state; Magnus has no free text | T "The privacy boundary" (§7.10) |
| 11 | Recipe vs USD | Recipe (typed, ours) is the source of truth; **USD is a compiled, one-way output** | R §8; adopted verbatim (§7.11) |

Non-goals (honesty section): no multi-tenant or hosted deployment; no CRDTs
(agents edit a recipe, not a shared document — D §7 "Figma" row); no USD→recipe
round-trip except asset import (R §8); voice input is [later] — every voice path
in this spec has a text+click equivalent that ships first (D §8).

---

## 1. Data model

### 1.0 Conventions, IDs, store layout

- Timestamps RFC 3339 UTC. IDs are prefixed short strings: `rcp_` recipe,
  `ver_` recipe version, `br_` branch, `ed_` edit, `wo_` work order,
  `pkt_` context packet, `ast_` asset, `pr_` prediction, `tn_` taste note,
  `aud_` audit event, `night_`, `task_`, `job_`, `att_` attempt, `q_` parked
  question. Vocabulary entries have no prefix id: the word itself
  (`bridge.rope`) is the key.
- Content hashes: sha256 over canonical JSON (sorted keys, no whitespace, UTF-8),
  written `sha256:ab12…`.
- **Store of record**: one SQLite database in WAL mode, `synchronous=FULL`,
  written by a **single writer process** (the core). The `audit` table is the
  source of truth; all other tables are projections rebuilt by folding `audit`
  (§5). Recipe version documents and artifacts are content-addressed blobs on
  disk, referenced by hash from the DB — so the DB is small (a night is
  kilobytes of decisions, V §"The pieces" #2) and the blobs are verified by
  hash on read.

```
$BUILDER_HOME (default ~/builder-ide)
  core.db                 # SQLite WAL: audit + projections
  artifacts/ab/ab1234…    # content-addressed, write-once (renders, GLBs, reports)
  recipes/ver_0192.json   # canonical recipe document per version (mirrors a blob)
  sandboxes/wo-14/3/      # engineer worktrees + seats (§2.2), deletable
  usd-cache/              # compiled USD layers per (recipe version, profile)
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
    ref: str | None           # node id, e.g. "oak_0117"
    value: float | None       # radius_m, load factor, …

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
    schema_version: int = 1
    engine_pin: EnginePin
    seeds: dict[str, int]      # per channel: terrain / props / weather
    entries: dict[str, RecipeEntry]
    constraints: list[Constraint]              # project-level (drip lines etc.)
```

Example (Fjellvik, abbreviated):

```json
{
  "id": "rcp_fjellvik", "name": "Fjellvik", "schema_version": 1,
  "engine_pin": {"repo": "SI-Thor/infinigen-thor", "commit": "9f31c0e", "blender": "4.2", "python": "3.12"},
  "seeds": {"terrain": 20261030, "props": 771, "weather": 4242},
  "entries": {
    "terrain.east_slope": {
      "path": "terrain.east_slope", "kind": "terrain",
      "generator": {"module": "infinigen_thor.terrain", "func": "slope", "variant": null, "rev": "9f31c0e"},
      "params": {"relief": 0.62, "birch": 0.8, "undergrowth": 0.35, "keep": ["oak_0117"]},
      "seed": 20261030
    },
    "harbor.crates": {
      "path": "harbor.crates", "kind": "prop_set",
      "generator": {"module": "infinigen_thor.props", "func": "crates", "variant": null, "rev": "9f31c0e"},
      "params": {"count": 12, "style": "weathered", "from_library": 6, "lids": true, "handles": "rope"},
      "assets": ["ast_0a41", "ast_0a42"], "origin": "wo_15", "seed": 771
    },
    "structure.south_span": {
      "path": "structure.south_span", "kind": "structure",
      "generator": {"module": "infinigen_thor.structures", "func": "bridge", "variant": "rope", "rev": "a1c4e2"},
      "params": {"length_m": 14.0, "planks": 8, "rope": "hemp", "sway": 0.22, "load_factor": 2.3},
      "constraints": [{"name": "load_floor", "kind": "load_floor", "value": 2.0}]
    }
  },
  "constraints": [{"name": "oak_dripline", "kind": "keep_clear", "ref": "oak_0117", "value": 4.0}]
}
```

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

Example — the Prop-maker's fish-crate bet (D §23:04):

```json
{
  "id": "ed_0442", "base": "ver_0192",
  "author": {"kind": "character", "id": "prop_maker", "via": "props.harbor.crates"},
  "message": "crates 12, weathered, 6 from library",
  "prediction": "pr_1189",
  "ops": [
    {"op": "set", "path": "harbor.crates.params.count", "value": 12},
    {"op": "set", "path": "harbor.crates.params.style", "value": "weathered"},
    {"op": "set", "path": "harbor.crates.params.from_library", "value": 6}
  ]
}
```

Validation: an edit is admitted only if the resulting document passes every
touched entry's vocabulary param schema (§1.5) and every project constraint that
is machine-checkable pre-render (D §04:2x: the drip-line constraint failed
*before* the critic ran — constraint checks precede renders in the pipeline,
§3.2).

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
    purpose: Literal["main", "night", "work-order", "morning-option", "rejected"]
    created_by: Actor
    protected: bool = False   # "main" and kept morning-options are protected
```

Rules, from T §"Safe mistakes" ("every step runs on a branch; the world is
always a named commit"):

- Applying a choice is a **pointer move**, not a re-render: the morning A/B/C
  flip is `main.head = branch.head` (D §07:11: apply ≤ 10 s because the
  comparisons were pre-rendered overnight).
- Rejection never deletes: a rejected branch is retargeted to
  `purpose="rejected"` and stays visitable (T: "a rejection is a branch you can
  revisit, not a hole in the ground").
- The three morning options are branches whose heads were rendered at the
  comparison rung during the night, so the flip is a viewer over cached
  artifacts (D §07:11, §4 moment 8).
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

class AcceptanceCheck(BaseModel):
    kind: Literal["constraint", "critic", "test_suite", "render_rung", "manual"]
    spec: dict                # examples below; "manual" requires the owner and blocks promotion

class Evidence(BaseModel):
    kind: Literal["commit", "code_diff", "recipe_diff", "render", "critic_verdict",
                  "test_run", "constraint_run", "timing", "budget_spend", "licence_scan", "log"]
    ref: str                  # artifacts/… path or aud_ id
    sha256: str
    summary: str              # ≤ 80 chars; what the card shows

class Attempt(BaseModel):
    n: int                    # 1..; monotonic, ids never reused (idempotency, §5.3)
    engineer: str             # adapter id (§2.6)
    state: Literal["running", "delivered", "gate_failed", "failed", "cancelled"]
    seat: str                 # sandboxes/wo-14/3
    started_at: str; ended_at: str | None
    outcome: str | None       # "critic failed at 1.1x load (rope snapped in sim)" (D §"In parallel")

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
    confirm_line: str                     # ≤ 25 words, spec register (§3.1)
    state: WoState
    attempts: list[Attempt]
    evidence: list[Evidence]              # "no card without an artifact" (D §"The night's failures")
    promote: VocabularyEntry | None       # draft word; activated on keep (§2.3)

class Origin(BaseModel):
    channel: Literal["voice", "text", "chip", "character", "panel"]
    packet: str                           # pkt_ — the context packet snapshot (§1.4)
    utterance: str | None                 # owner only; purged at terminal state (§7.10)
    character_line: str | None            # the "real rope isn't in my hands yet" line (D §21:08)
```

Acceptance examples (WO-14, the rope bridge of D §21:08 and V):

```json
[
  {"kind": "constraint", "spec": {"path": "structure.south_span.params.load_factor", "op": ">=", "value": 2.0}},
  {"kind": "critic",     "spec": {"check": "reads.as.rope.bridge", "rung": 2, "verdict_in": ["keep"]}},
  {"kind": "test_suite", "spec": {"suite": "tests/structures/test_bridge_rope.py"}}
]
```

A `manual` check can exist only on owner-filed orders and forces a human gate
step before `landed`; it may never be auto-promoted.

Transition table (core-only writer; every arrow is one `audit` event; guards in
brackets):

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
    gaze: Gaze | None                       # camera ray + hits, [later]
    position: tuple[float, float, float]
    region: str | None                      # "south-span", from region map

class Gaze(BaseModel):
    ray: dict                               # {"origin": [x,y,z], "dir": [x,y,z]}
    hits: list[dict]                        # [{"node_id": …, "dist": m, "part": "deck"}]

class History(BaseModel):
    recipe_changes: list[dict]              # {ver, actor, line} — last N
    critic_notes: list[dict]                # {at, node, reason_code, line} — last M
    work_orders_open: list[dict]            # {id, title, state} — all open, ≤ K

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
| `view.gaze.hits` | 5 | nearest 5 |
| `history.recipe_changes` | 10 | drop oldest first |
| `history.critic_notes` | 5 | drop oldest first |
| `history.work_orders_open` | 8 | oldest filed first out |
| `conversation` | 12 labels | drop oldest first |
| `project.vocabulary_gaps` | 8 | — |
| whole packet (canonical JSON) | **16 KiB** | drop `history`, then `conversation`; fail loud if still over |

Typical size 2–6 KiB. The packet is the *only* situation data that crosses into
a model prompt together with the utterance (T §"The privacy boundary": the
ledger/packet are what get read into a prompt — never transcripts).

Example (the WO-14 call, D §21:08):

```json
{
  "id": "pkt_0031", "at": "2026-10-30T21:08:39Z", "actor": "casey",
  "view": {
    "selection": ["span_south"],
    "gaze": {"ray": {"origin": [142.1, 3.0, 88.4], "dir": [0.31, -0.12, 0.94]},
             "hits": [{"node_id": "span_south", "dist": 11.2, "part": "deck"},
                      {"node_id": "pier_s2", "dist": 14.9}]},
    "position": [140.0, 2.0, 80.0], "region": "south-span"},
  "history": {
    "recipe_changes": [{"ver": "ver_0188", "actor": "architect", "line": "south span planks loosened (fake sway)"}],
    "critic_notes": [{"at": "2026-10-30T21:05:11Z", "node": "span_south", "reason_code": "wrong_material", "line": "planks read as glued"}],
    "work_orders_open": []},
  "conversation": [
    {"who": "architect", "label": "limit-hit:bridge.rope"},
    {"who": "casey", "label": "request:new-capability"}],
  "project": {"branch": "br_main", "head": "ver_0192",
              "budget_left_tonight": {"gpu_minutes": 330, "hosted_cents": 0, "wall_minutes": 480},
              "vocabulary_gaps": ["bridge.rope"],
              "engine_pin": {"commit": "9f31c0e"}, "world_time": "21:08"}
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

Example:

```json
{
  "word": "bridge.rope", "kind": "structure", "owner_character": "architect",
  "status": "coming-soon", "version": 1,
  "params": {
    "type": "object", "additionalProperties": false, "max_properties": 8,
    "properties": {
      "length_m": {"type": "number", "minimum": 2, "maximum": 40},
      "planks":   {"type": "integer", "minimum": 3, "maximum": 24},
      "rope":     {"enum": ["hemp", "chain", "steel-cable"]},
      "sway":     {"type": "number", "minimum": 0, "maximum": 1},
      "seed":     {"type": "integer"}
    }
  },
  "acceptance_template": {"kind": "constraint", "spec": {"path": "{node}.load_factor", "op": ">=", "value": 2.0}},
  "taste_notes": [{"code": "avoid", "reason_code": "wrong_material", "note": "chain reads prison-y", "basis": "0/3 kept"}],
  "provenance": {"origin": "wo_14", "commit": "a1c4e2", "at": "2026-10-31T07:26:00Z"}
}
```

A character's call is `POST /v1/vocab/call {word, node | region, params}` → the
core validates against the schema, binds the acceptance template, and produces a
`RecipeEdit` authored `{kind: character, id: …, via: word}`. Anything outside
the schema is refused at the door — that refusal, said in character, is the
"I can't do rope yet" moment (D §21:08).

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
                                  #  "model_id": "tripoSG-1.4",
                                  #  "weights": {"repo", "revision", "licence"},
                                  #  "prompt": "≤ 256 chars", "seed": 771,
                                  #  "library_versions": {"torch": "2.15.0+cu132", …}}
    cad_script: dict | None       # {"file", "sha256"} — the script IS the asset (R §1:
                                  # deterministic CAD; meshes are caches)

class Licence(BaseModel):
    spdx: str                     # "MIT", "OpenRAIL++-M", "CC-BY-NC-4.0", "CC0", "STABILITY-COMMUNITY"
    commercial_ok: bool
    checked_at: str; checked_by: str   # the core's licence registry, not the creating job
    notes: str | None
```

Licence policy (from R's verdicts): `commercial_ok=false` (MusicGen CC-BY-NC,
FLUX-dev, ambiguous MotionGPT weights) can never enter an entry marked
shippable; Hunyuan weights carry a regional restriction flag; MoMask-derived
clips carry the AMASS/HumanML3D data-provenance flag until an owner decision
(R §4). The merge gate's licence scan (§2.3) blocks promotion on any missing or
failing licence row.

Example:

```json
{
  "id": "ast_0a41", "kind": "mesh",
  "files": [{"role": "glb", "path": "artifacts/d7/d7b1e5….glb", "sha256": "sha256:d7b1…", "bytes": 4123312}],
  "provenance": {
    "source": "generated",
    "generator": {"method": "image_to_3d", "model_id": "tripoSG-1.4",
      "weights": {"repo": "VAST-AI/TripoSG", "revision": "2410…", "licence": "MIT"},
      "prompt": "weathered fish crate, hempen rope handle, harbor", "seed": 771,
      "library_versions": {"torch": "2.15.0+cu132", "modly": "0.4.3"}}},
  "licence": {"spdx": "MIT", "commercial_ok": true,
              "checked_at": "2026-10-30T23:12:00Z", "checked_by": "core/licence-registry"}
}
```

### 1.7 Predictions and taste notes (the two ledgers)

Two distinct tallies, stored and displayed separately because they fail
differently (T §"Two tallies"): predictions about the **world** (competence,
scored by the Critic) and predictions about **you** (taste, scored by the
owner's keep/reject). Only sealed predictions count, anywhere (D §9).

```python
class Prediction(BaseModel):
    id: str; builder: str
    at: str; sealed_at: str        # equal at seal time; sealed_at is immutable
    branch_ref: str                # "br_07f2@ver_0193"
    claim: str                     # ≤ 120 chars, the spoken claim verbatim
    claim_type: str                # closed set: shadow_count | scale_read | clutter_density
                                   # | material_read | era_read | light_read | weather_read
                                   # | taste_keep        (§7.2 for the set's provenance)
    confidence: Literal["low", "medium", "high"]
    seal_hash: str                 # sha256 over canonical {builder, at, branch_ref, claim,
                                   #  claim_type, confidence} — written BEFORE the render job
                                   # is created (§5.1)
    verdict: Literal["hit", "miss", "partial"] | None   # set by the Critic (world) or the
                                                        # owner's keep/reject (taste_keep); never self-scored
```

Confidence is **gated** at generation time: a builder may not predict on a
claim_type (or reason code) where it holds fewer than two prior observations —
no evidence, no claim; this is a hard gate in the core's prediction API, not a
prompt instruction (T §"The 'I think you'll like this' utterance", rule 4).

```python
ReasonCode = Literal["too_busy", "too_empty", "wrong_scale", "too_messy", "too_clean",
                     "too_flat", "too_dark", "too_bright", "wrong_material", "wrong_era",
                     "wrong_weather", "no_focus"]        # the closed dozen (T §"taste note fields")

class TasteNote(BaseModel):
    id: str; at: str
    author: str                     # "casey" | "magnus" — author-scoped, never merged (§7.4)
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
slice read into a model prompt (§7.6).

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
    actor: Actor                  # {kind: owner|character|engineer|critic|core|scheduler, id}
    type: str                     # closed set below
    subject: dict                 # {entity_kind, entity_id}
    payload: dict                 # ≤ 4 KiB; anything bigger goes to artifacts/ and is hash-referenced
    artifact: dict | None         # {sha256, kind, bytes}
```

Event types (closed; new types are a schema change):

| Group | Types |
|---|---|
| work orders | `wo.filed`, `wo.compiled`, `wo.questioned`, `wo.confirmed`, `wo.queued`, `wo.attempt.started`, `wo.attempt.delivered`, `wo.testing`, `wo.landed`, `wo.kept`, `wo.rejected`, `wo.parked`, `wo.resumed`, `wo.failed`, `wo.cancelled` |
| recipe | `edit.proposed`, `edit.validated`, `version.committed`, `branch.created`, `branch.head.moved`, `branch.rejected`, `constraint.failed` |
| predictions | `prediction.sealed`, `prediction.scored` |
| taste | `taste.note.appended` (single writer: owner verdicts only) |
| vocabulary | `vocab.word.added`, `vocab.word.status`, `vocab.call` (refused calls included — the edges are the story, D §5.5) |
| night | `night.started`, `night.stopped`, `night.task.created`, `night.task.state`, `line.spoken` (line-budget enforced here, §5.6) |
| scheduler | `sched.model.load`, `sched.model.unload`, `sched.demote`, `job.enqueued`, `job.started`, `job.done`, `job.requeued`, `render.completed` |
| critic | `critic.verdict` (carries `degraded` flag → `verdict@low-res`, D §03:5x) |
| budget | `budget.spend`, `budget.threshold` (80/95/100), `kill.switch` |
| assets | `asset.created`, `asset.licence.checked` |
| questions | `question.parked`, `question.answered` |
| continuity | `model.change.noticed` (T §"Research transfer": model swaps announced, never silent) |
| system | `core.boot`, `core.recovered`, `projection.rebuilt`, `integrity.failure` |

### 1.9 Night, Task, Job — the scheduler's records

```python
class Night(BaseModel):
    id: str                        # night_2026-10-30
    started_at: str; stopped_at: str | None
    rails: Rail                    # the budget bar's ceiling (D §21:02: ~8 h wall, 5.5–6.0 GPU-h)
    state: Literal["starting", "running", "stopping", "stopped"]
    report: str | None             # artifacts/… report.html, prebuilt at stop

class Task(BaseModel):
    id: str; night: str
    owner_character: str
    intention: str                 # "Forest the east slope, keep the oak" (D §21:02 slate row)
    recipe_scope: list[str]        # entry paths this task may touch
    rail: Rail                     # per-task rail (T §"Safe mistakes": three rails)
    state: Literal["queued", "running", "kept", "reverted", "parked"]
    predictions: list[str]; branches: list[str]

class Job(BaseModel):
    id: str
    lane: Literal["cpu", "gpu"]
    model: str | None              # registry id for gpu jobs (R §9 tiers)
    request: dict                  # seeded, bounded; seeds are first-class (R: determinism)
    cost_estimate: Rail            # checked BEFORE dispatch (T: rails enforced before spend)
    claim_token: str; lease_until: str; heartbeat_at: str   # crash recovery, §5.2
    state: Literal["queued", "running", "done", "failed", "requeued"]
    outputs: list[str]             # artifact refs; provenance stamped by the core on done
```

Model registry (config, not DB rows): per model id — tier `hot` (companion LLM,
critic vision model: always resident), `warm` (one generative model loaded at a
time, drained per batch: image-to-3D → texture stack → motion → music, R §9),
`cold` (disk, pinned revisions); a cost table mapping measured GPU-seconds and
hosted cents per call to rail units; demotion rules (critic OOM → smaller local
critic, verdicts marked `degraded`, reported in one line — D §03:5x).

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
(§2.5), each of which is an audited, rail-charged action.

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
   index, pinned model hosts; no LAN, no ledger); a fresh `uv` venv from the
   project lockfile (R's verified aarch64 set: torch 2.15.0 cu132, cadquery-ocp
   wheels, usd-core 26.11, …); stdout/stderr captured to `artifacts/` as a log
   Evidence item.
4. **Rails**: the attempt's `per_attempt` rail is pre-checked at admission and
   hard-enforced by the seat (kill at rail) — enforced before spend, not
   alerted after (T §"Safe mistakes", citing the AWS agentic cost hierarchy).
5. **Idempotency**: attempt directories are numbered and never reused; a
   rebooted attempt restarts as attempt *n+1* in a fresh seat (§5.2).

### 2.3 How evidence is checked — the merge gate

Run by the core, on the deliverable, in a clean worktree. Ordered; any hard
fail stops the gate (the attempt is `gate_failed` with the failing evidence
attached — D §"In parallel": attempt 1 failed the critic at 1.1× load; attempt
2 on plank spacing; attempt 3 passed at 2.3×).

1. **Deterministic rebuild**: apply the proposed recipe edit and build from the
   commit in a clean worktree. CAD parts must be byte-identical (R §1:
   same script + pinned wheels → byte-identical geometry); generative outputs
   must reproduce from `(prompt, weights revision, seed)` (R: seeded samplers
   everywhere; seed is a first-class param).
2. **Static + unit tests**: typecheck and suites on the changed code.
   build123d's typed, property-based style is chosen precisely because it is
   statically checkable (R §1; §7.1).
3. **Render ladder** (T §"Safe mistakes": previews are a ladder, each rung a
   budget gate; the night spends on the last rung only what survived the
   first two): rung 1 fast layout (seconds) → rung 2 mid still with lighting
   and materials (~a minute) → rung 3 full render (minutes). The gate stops at
   the lowest rung that can decide every `acceptance` check.
4. **Constraint checks**: machine-checkable acceptance (load factor from the
   sim, drip-line clearances) run *before* the critic at each rung — D §04:2x
   shows the ordering: the constraint failed before the critic even ran.
5. **Critic check**: the required `critic` acceptance items at the required
   rung. If the critic was demoted, the verdict is recorded `degraded` and the
   morning report says so in one line (D §03:5x). The Critic returns
   `hold`/`fix`/`keep` + reason code + at most one suggested change, and
   authors nothing (T §"Five builders and one computer").
6. **Licence scan**: every new asset has a complete `Licence` row from the
   registry; missing, ambiguous or non-commercial rows block promotion into
   vocabulary marked shippable (R §3–§5; V: licences are a checked list).
7. **Budget audit**: seat telemetry vs the deliverable's claimed spend; a
   mismatch > 20% fails the attempt (honest evidence or no evidence).
8. **Diff review pack**: recipe diff (ops), code diff, before/after renders at
   the deciding rung, timings — assembled as the evidence bundle, hashed into
   the ledger, openable in ≤ 1 s (D §4 moment 9).

**Pass ⇒ `wo.landed`.** The preview exists before the owner sees the card
(D §4 moment 10). **Keep ⇒ promotion, in one core transaction:** branch
fast-forwarded per the owner's choice, `vocab.word.added` fires, the word's
`status` flips `coming-soon → active` with provenance pointing at the WO and
commit, and the owning character is notified so the "I can do rope now" reveal
lands at the moment it becomes useful (D §07:34). **Reject ⇒** the branch is
retained under `purpose="rejected"`, the word proposal is parked or retired,
the evidence stays.

### 2.4 How ACP maps onto it

ACP (Agent Client Protocol) is how editor-native agents and front ends talk
(Zed's protocol; V §"The pieces" #7: front ends onto the engineer's work, not
backends). The core plays **ACP client** to engineer agents and **ACP proxy**
to human front ends:

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
every call is an `aud_` event charged to the attempt rail:

| Tool | In | Out |
|---|---|---|
| `recipe.get` | version? | recipe document |
| `recipe.diff` | base, head | ops list |
| `vocabulary.search` / `vocabulary.get` | query / word | entries (incl. `coming-soon` edges) |
| `context.packet` | pkt_ | the packet the order compiled from |
| `render.request` | entry paths, rung, seed | job id → artifact ref (rail-charged) |
| `critic.request` | artifact, check | verdict (rail-charged; gate re-runs it independently) |
| `tests.run` | suite | results |
| `evidence.attach` | kind, artifact sha, summary | Evidence row |
| `budget.remaining` | — | rail snapshot |
| `order.get` | — | order + acceptance checks |
| `deliver.submit` | Deliverable | triggers the merge gate |

There are deliberately **no** tools to write the taste ledger, vocabulary,
audit log or branches (T §"The taste ledger": the agent never holds the pen;
D §7: data, never code, for agent changes — the inverse direction). modly's own
MCP server (R §2) stays behind the scheduler and is not exposed to seats.

### 2.6 Engineer registry (initial)

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
swing" (D §21:08). Latency budgets from D §4.

```
owner ── utterance + client view ──> POST /v1/call
core: capture ContextPacket (pkt_)                     [aud: pkt captured]
core: compile                                          ≤ 20 s (D §21:08)
   1. referent resolution over view.selection ∪ gaze.hits ∪ region,
      deterministic: node ids, distances, part names
   2. if top-2 candidate referent sets both plausible → wo.questioned.
      One-tap question naming candidates by what they are
      ("The south span, or both spans?"). NEVER guess (V, D §21:08, T).
      Test (D): say an order with two plausible referents;
      the second line must be a question, not a plan.
   3. draft: goal, targets by id, acceptance checks, budget estimate
      (model-registry cost table × historical baselines), confirm line
   4. confirm line: ≤ 25 words, spec register, no first person (T
      §"Telling the computer apart from the crew"):
      "CONFIRM: rope bridge, south span, hempen, 8 planks; critic passes
       at 2x load; est. 3 h tonight; reversible at ver_0192. Go?"
owner ── "Go" ──> POST /v1/work-orders/{id}/confirm     (Idempotency-Key)
core: wo.confirmed → queued; night rail re-admitted; budget bar updates;
      vocabulary note `bridge.rope` pinned coming-soon on the Architect   [aud]
   (a veto is one sentence; a wrong compile is cheap to reject — D §21:08)

night (or spare day capacity):
core: attempt 1..N — seat, engineer.run, merge gate      [aud per attempt]
   failures keep evidence: "1.1x load, rope snapped in sim" (D)
core: gate passes → wo.landed; preview + evidence bundle exist BEFORE the
      owner is notified                                  (D §4 moment 10)

morning / on arrival:
client: card "WO-14 · landed · preview ready"; ghost scaffolding [later];
      diff card [now]
owner ── keep | reject ──> POST …/keep | /reject        ≤ 2 s, one tap;
      evidence one click ≤ 1 s
core: keep → promote (§2.3): branch, vocab.word.added, character notified;
      reject → branch retained, word stays coming-soon; both audited
```

Character-filed orders are the same shape with `origin.character_line` set: a
character hits a vocabulary edge, says so in one sentence, and the order is
filed with the same packet mechanism (V §"The work order is the bridge"; T:
work orders are *linked control* — the order carries its context).

### 3.2 The overnight plan, through the queue, to the morning report

From D §1–§3 and T §"Safe mistakes", with R §9's lane layout doing the
scheduling.

1. **Plan slate** (D §21:02): intentions with owner character, predicted cost,
   the builder's one-line take; one budget bar. `night.task.created` per row;
   rails: per-cycle < per-task ≤ per-night (T). If the ask exceeds the bar,
   builders cut their own lists first — recovery is a proposal, never an error
   (D).
2. **Start the night** (D §21:14): `night.started`. The scheduler waits for
   client detach before big batches so the GPU belongs to the night (D).
3. **Lanes** (R §9): the CPU lane runs continuously (build123d parts, mesh
   cleanup, USD assembly, CPU-capable SFX) and never waits on the GPU; the GPU
   lane batches by model — image-to-3D → texture stack → motion → music —
   draining each warm model's queue before swapping. Critic checks interleave
   after each batch.
4. **The sealed-bet loop** per task (D §23:04, the fish-crate bet):
   edit (typed vocab call) → predict (sealed, hashed, **committed before the
   render job exists**, §5.1) → preview (batched rungs; a night's image-to-3D
   jobs batch so the Thor never swaps models twice) → critic → keep or revert
   (recipe diff 412 bytes). Each loop is capped by the per-cycle rail.
5. **Throttling is graduated** (T): at 80% of the night rail, builders stop
   opening branches and finish-or-park what they have; at 95% they stop and
   report; at 100% or kill switch, current branches are committed and the
   report is written immediately with whatever state existed. The queue stops
   cleanly at the bar; unrun batches requeue for tomorrow and the report's
   first line says what didn't get done (D §05:0x).
6. **Questions at 3am** (T §"The open-question policy"): the night cannot ask.
   Two channels only — **park it** (a named question attached to a branch) or
   **assume the conservative reading** with the assumption recorded in the
   report. It never guesses and never stalls the queue behind it.
7. **Failure narration** (D): every recovery narrated by the builder in one
   line, ≤ 6 lines per builder per hour, only on state change — enforced by the
   core's `line.spoken` budget (§5.6). Every failure produces a card with an
   artifact, not an error.
8. **Report build** (at stop, before the owner opens anything — the morning is
   instant because the night already did the rendering, D §"The three clocks"):
   static HTML+JSON over the ledger. **Failures lead** (T §"Failures lead the
   report"), then the night line (`8 h 20 m · 61 recipe edits · 23 sealed bets
   · 17 kept · 4 reverted · 2 parked · 5.3 of 5.5 GPU-h · prediction score
   8/10 (was 7)`), the filmstrip (cached renders, 60 fps on the ProArt), three
   pre-rendered branches, parked questions answerable in one tap, landed work
   orders, model-change notices (T), lost time if the box rebooted, and the
   prediction tally — counts with denominators, recency-weighted, percentages
   only where the denominator supports one (T §"Sealed predictions").

### 3.3 Failure and recovery paths (the night's own handling)

All [now], all in the log (D §"The night's failures and recoveries"); each is
an audit event plus a card:

| Failure | Handling |
|---|---|
| image-to-3D returns hollow meshes | critic flags; retry one seed; fall back to recolored library crate; park a note |
| critic OOMs in a big batch | scheduler demotes to the smaller local critic; verdicts marked `verdict@low-res`; report says so in one line |
| a constraint breaks (drip line) | constraint check fails *before* the critic; auto-revert; the sealed prediction still resolves — that bet is lost |
| budget bar reached with work unrun | queue stops at the bar; requeue for tomorrow; report's first line says what didn't get done |
| reboot / power cut | durable queue; on boot resume from the last sealed step; report states lost time in minutes, never hides it (§5.2) |
| owner mid-night peek, server killed | feed is stateless over the ledger; kill -9 test in §5.4 |

---

## 4. APIs

### 4.1 Transport, auth, clocks

HTTP/JSON + SSE on the LAN; the same API serves the ProArt client, panels
(web or Theia), character runtimes and engineer seats. Three token classes:
`owner` (full), `panel` (read + SSE), `seat` (MCP tools only, scoped to one
attempt). Voice is [later]; every endpoint here has a text+click caller today
(D §8).

Service budgets by clock (D §"The three clocks" — nobody waits on the wrong
clock): Talk ≤ 2 s (plan items, keep/reject, chips); Watch ≤ 5 s per card
(pre-render, cache, stale-then-fresh); Workshop ≤ 60 s with progress and a
cancel, else it goes to the night queue. Compile ≤ 20 s; report first paint
≤ 3 s; branch flip ≤ 2 s; apply ≤ 10 s; evidence card ≤ 1 s (D §4).

### 4.2 Endpoints

| Endpoint | Method | Caller | Purpose |
|---|---|---|---|
| `/v1/call` | POST | owner client | utterance + client view → pkt; returns `question` XOR `draft` (compile ≤ 20 s) |
| `/v1/work-orders/{id}/confirm` | POST | owner | `{answer: "go"\|"no"\|"edit", …}`; Idempotency-Key |
| `/v1/work-orders/{id}/keep` `/reject` | POST | owner | terminal decision; ≤ 2 s |
| `/v1/work-orders` | GET | panels | board view: state, confirm line, budget, evidence (D §5.5) |
| `/v1/questions/{id}/answer` | POST | owner | one-tap answer to a parked question |
| `/v1/night` | POST | owner | start the night (slate → queue) |
| `/v1/night/{id}/stop` | POST | owner | kill switch: stop all, commit branches, write report now (T) |
| `/v1/nights/{id}/report` | GET | panels | static report (html / json); first paint ≤ 3 s |
| `/v1/branches` / `/v1/branches/{id}/apply` | GET/POST | owner/panels | morning A/B/C; apply = head move ≤ 10 s |
| `/v1/budget?night=` | GET | all | rail snapshot + bar state |
| `/v1/vocab/call` | POST | characters | typed word call → validated RecipeEdit (refusals audited) |
| `/v1/vocab` | GET | characters/panels | words incl. `coming-soon` edges, taste notes (read-only) |
| `/v1/predictions/seal` | POST | characters | seal before render; confidence gate enforced (T) |
| `/v1/ledger/taste` | GET | characters/panels | author-scoped read; never writable via API |
| `/v1/night/{id}/tasks` | POST | Companion | file the slate's tasks |
| `/v1/questions` | POST | characters | park a question (name + branch + two options) |
| `/v1/assets` | GET/POST | panels/scheduler | library with licence column (D §5.6) |
| `/v1/world/scene` | GET | ProArt | compiled USD/glTF manifest per (branch, LOD) — thin client streams from this (V §"The pieces" #8; R §8) |
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
| `question` | one-tap question card | Talk |
| `plan.chip` | slate chip update | Talk |
| `budget.threshold` / `budget.spend` | bar colour and fill | Talk |
| `line` | character utterance (≤ 6/builder/hour, state-change only, §5.6) | Talk |
| `world.dirty` | re-stream scene manifest (branch head moved) | Watch |
| `ghost.pointer` | [later] ghost scaffolding for a landed preview (D §07:26) | Watch |
| `report.ready` | morning notification | Talk |
| `job.progress` | workshop progress + cancel affordance | Workshop |

The ProArt additionally receives the compiled scene via `/v1/world/scene`
(glTF/USD); previews render on the client's own GPU (V §"The pieces" #8).

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
exists).

### 5.2 What survives a reboot mid-night, and how a run resumes

Survives (all in the DB + blobs): every sealed prediction and verdict, every
committed recipe version and branch pointer, work-order states and attempts,
budget spend, parked questions, the audit log to the last committed event, all
artifacts (write-once, tmp+rename). Does not survive: GPU-resident models,
TCP connections, half-finished renders (atomic — re-run, never resumed), and
the predictions of steps that never reached a render: they die **unsealed and
unscored** (never invent a verdict for work that did not happen — D §6: honest
idleness; T: failures lead).

Boot sequence (`core.boot` → … → `core.recovered`):

1. Open DB; if projections are dirty, rebuild by folding `audit`
   (`projection.rebuilt`).
2. Verify artifact hashes referenced by `landed` work orders and report cards;
   a broken reference fails loud (`integrity.failure`) — a night that cannot
   show its work did not happen (D).
3. Recovery pass over jobs: expired `lease_until` with no heartbeat →
   `job.requeued`. GPU renders re-run from seed (deterministic); CPU steps
   (CAD, USD assembly) replay byte-identically (R §1).
4. Attempts: seat process alive (checks claim token) → re-attach and keep
   streaming; else `attempt n+1` in a fresh seat — attempt ids never reused.
5. Nights: if `running`, rails unexhausted and the wall window open → resume
   from the last sealed step (the queue is durable; D §"The night's failures");
   else stop cleanly and build the report, with `lost_minutes` stated in the
   first line — never hidden (D, T).

### 5.3 Idempotency

- `Idempotency-Key` on every owner POST (`confirm`, `keep`, `reject`,
  `night.start`, `question.answer`, `call`): the key maps to the committed
  event; a replay returns the original result, never a second state change.
  A doubled "Go" cannot start two attempts.
- State transitions are compare-and-swap on `(entity, expected_state, seq)`;
  a stale transition fails closed and is audited.
- Jobs are deduplicated by `hash(request + attempt)`; job outputs are
  content-addressed, so a re-run that reproduces converges on the same
  artifact instead of duplicating.
- MCP tool calls carry the attempt id; retries are idempotent by tool
  semantics (`render.request` with the same seed returns the same artifact).

### 5.4 The kill -9 test (acceptance for this whole section)

From D §02:07 — kill -9 the feed server mid-night, reopen: the feed must render
from the ledger alone, complete to the last sealed bet. Concretely: every panel
is a stateless reader over `/v1/events` + GETs; there is no panel-local state
that is not derivable; the report is regenerable from the log at any time. Test
cadence: in CI, nightly, and before every phase gate.

### 5.5 Budget mechanics (decision §0.3, T's open question answered)

Units: rails are `(gpu_minutes, hosted_cents, wall_minutes)`. GPU-minutes come
from the model registry's measured cost table (per model id), not from
wall-clock, so a cheap CPU-lane hour does not eat the GPU bar. Defaults:
night rail 360 GPU-min (the 6.0 h bar of D §21:02, owner-slidable to 5.5 h),
`hosted_cents: 0` unless the owner explicitly enables hosted engineers for the
night (then a hard cents cap), wall 560 min. Local wall-clock and CPU work are
effectively free and deliberately not the scarce axis (T §"Open decisions" #4:
"wall-clock on the Thor is nearly free; hosted model time is not").

Enforcement is **before spend** (T, citing AWS AGENTCOST07): admission control
projects each job's cost from the registry and refuses what a rail cannot
cover; the seat hard-kills at the per-attempt rail. Degradation order at the
rail, answering T's "what gets dropped first":

1. at 80% — stop opening new experiment branches; finish or park existing ones
   with a one-line reason (graduated, not binary — T: "binary shutdown is how
   you get a morning report that says nothing happened");
2. drop queued exploratory generative batches not needed by a landed preview or
   an open work order (requeue for tomorrow — D §05:0x);
3. at 95% — stop new work entirely; close out in-flight branches at their
   current rung;
4. at 100% or kill switch — commit branches, write the report immediately.
   Never dropped: merge-gate evidence for landed work, parked questions, the
   report itself.

### 5.6 Interruption and line budgets (enforced in the core, not the prompt)

From T §"Failure modes": a builder may interrupt only for a blocked decision, a
budget-rail event, or a hard failure — at most one interruption per builder per
20 minutes; the rest queue, and overnight everything parks until morning. Night
lines: ≤ 6 per builder per hour, state-change only, no repeats within a session
(D). The `line.spoken` audit event is emitted only after the budget check
passes; the check is code, because prompt instructions are not enforcement (T:
"each rule is placed where it can actually be enforced").

---

## 6. Build order

### 6.1 The smallest end-to-end slice — "one crate night"

One character, three vocabulary words, one work order, one engineer (the
brief's floor). Plain Python + web panels; no 3D client (D §8: [now] = phases
3–4).

- **Core skeleton**: SQLite ledger + audit events + projections, FastAPI,
  SSE `/v1/events`, the endpoints of §4.2 marked (call, confirm, WO CRUD,
  vocab/call, predictions/seal, night, report, budget).
- **Recipe store**: versions, branches, edit validation, constraint checks
  (pre-render), diff rendering.
- **One character — the Prop-maker** (chosen because D §23:04 specifies its
  loop in full): a small local LLM runtime (scripted loop acceptable in the
  slice) making typed calls, sealing predictions.
- **Three words** (schema subset of §1.5):
  `props.harbor.crates {count 1–48, style enum[plain, weathered, stained],
  from_library 0–count, seed}`;
  `props.harbor.racks {count 1–24, length_m 0.5–6}`;
  `material.wood.weathering {wear 0–5, tone enum[pale, gray, dark]}`.
- **One work order**: the Prop-maker hits the param edge of
  `props.harbor.crates` — "lids and rope handles aren't in my hands" — and
  files WO-15. Compile from a text+click context packet (selection by click,
  gaze omitted), one-line confirm, queue, run.
- **One engineer — `aider-local`** (zero marginal cost, V) behind the full
  adapter: worktree + seat + MCP tools; implements the generator change and a
  test suite; delivers.
- **Merge gate (minimal)**: deterministic rebuild, unit tests, rung-2 render,
  local critic, licence scan of the two library crates, budget audit.
- **Landing**: preview card on the work-order board, keep →
  `props.harbor.crates` v2 gains `{lids: bool, handles: enum[none, rope]}`.
- **Night runner (minimal)**: task queue with per-task + per-night rails,
  sealed bets, morning report page with the night line and failures first.
  Per-cycle graduated throttling and kill switch can lag one step.

**Slice acceptance**: (a) the kill -9 test (§5.4); (b) the two-referent test —
an order with two plausible referents returns a question, not a plan (D §21:08);
(c) a sealed prediction exists in the DB with `sealed_at` strictly before its
render job's enqueue; (d) the report renders with zero panel-side state.

### 6.2 What follows, in order

1. **Adapter hardening + merge gate at full strength**: ACP client + proxy,
   permission policy, hosted engineers (`claude-code`) behind the same seam;
   the full evidence bundle.
2. **Scheduler tiers**: hot/warm/cold, batch-by-model with drain, CPU lane,
   provenance stamping on every artifact, critic demotion path (R §9).
3. **Recipe → USD compiler**: deterministic emission (sorted prims, no
   timestamps), one layer per concern, provenance in `customData`, payloads
   for heavy meshes (R §8, §10.1) — this is also what `/v1/world/scene` serves.
4. **The rest of the crew + full vocabulary**: Architect, Landscaper, Critic,
   Companion; per-claim-type track records with denominators; the two tallies
   surfaced on cards (T).
5. **Taste ledger surfaces**: closed reason codes, author scoping, one-writer
   verdict path, "why?" one tap on any artifact (T, D §4 moment 9).
6. **Context packet + compiler at full strength**: gaze rays when the client
   exists; referent resolution with the question rule; utterance purge policy.
7. **Generative stations behind the scheduler**: modly headless backend with
   TripoSG (mesh-only first, rembg workaround planned — R §2), StableMaterials
   + SDXL (OpenRAIL) with CC0 libraries (R §3), ACE-Step + SAOS (R §5), MoMask
   flagged (R §4).
8. **Budget rails graduated + kill switch** as specified (§5.5), plus
   per-tool risk ratings driving auto-approval (T §"Research transfer").
9. **Magnus mode**: chip grid (no free text), counts-not-percentages, his own
   queue ending at a fixed hour, vocabulary proposals needing Casey's confirm
   (T §"Magnus at the controls").
10. **Thin client** [later]: in-world view, plan chips, ghost scaffolding,
    branch flips in-world, phone peek, voice (D §8).

---

## 7. Decisions where the sources disagree or defer — and why

1. **CAD authoring API: build123d, not CadQuery.** V says "the engineer writes
   parametric CAD code (e.g. CadQuery)" — an example, not a verdict. R §1
   researched it: build123d's typed, property-based algebra is easier for an
   agent to write *and for the review pipeline to statically check*
   (mypy-clean by policy), it officially supports linux/aarch64 (the exact
   platform), and it exports glTF with material UVs headlessly. CadQuery stays
   installed as a readable secondary and a few-shot corpus — both share every
   binary dependency, so keeping it costs nothing (R §1). The merge gate's
   static-check step (§2.3.2) is materially weaker under CadQuery's string
   selectors; that decides it.
2. **Prediction `claim_type` set.** T's schema comment lists six types
   (shadow_count, scale_read, clutter_density, material_read, era_read,
   light_read) but its own track-record example scores `weather_read 15 sealed`
   for the Landscaper. Take the union — seven world types plus `taste_keep`
   for the second tally — and note that the set is closed but owner-extensible;
   adding a type is a schema change with a migration, not a runtime write.
3. **The nightly money rail** (T's open decision #4). Decided in §5.5:
   GPU-minutes + hosted-cents + wall-minutes, defaults 360/0-cents/560, hosted
   spend off unless explicitly enabled, degradation order fixed. Chosen because
   the Thor's local compute is effectively free (T says so) — a single
   "dollars" rail would either throttle free local work pointlessly or ignore
   the one scarce resource (hosted spend) that can actually hurt.
4. **Magnus's taste never folds into Casey's.** T assumed separation; this spec
   hardens it into the storage and API: `author` is part of every taste row's
   key, slices read into prompts are author-filtered, and his rows are
   exportable/deletable in one action (T §"The privacy boundary"). The
   alternative — a house taste — would let a nine-year-old's preferences steer
   the adult's builds with no visible mechanism (T's stated reason).
5. **Deadlock arbitration.** T assumed the Critic wins on `hold` and the owner
   breaks true deadlocks; adopted unchanged. The Critic's output is checkable
   (verdict + code against a sealed claim); the Architect's objection is an
   opinion. Where the two disagree on a non-defect, the step parks as a
   question rather than auto-resolving either way.
6. **The ledger stays on the Thor.** T's recommendation, adopted as a rule:
   any model call receives a scoped slice (author-filtered, purpose-bounded),
   never the whole ledger, and Magnus's rows are never in a slice. If hosted
   taste reasoning is ever wanted, that is an owner decision recorded as an
   audit event, not a default.
7. **No LangGraph (or any orchestration framework).** V: "Plain Python first;
   adopt LangGraph only if its checkpointing beats ours." The audit log with
   gapless `seq`, fold-to-rebuild projections, and job leases (§5) *is* the
   checkpointing — every panel and both reports already replay from it, which
   is the property a framework would have to beat. Revisit only if multi-step
   agent graphs need time-travel debugging the log cannot give.
8. **Interactive previews vs batch-by-model.** D's three clocks want a
   Workshop answer ≤ 60 s or it goes to the night queue; R §9 wants one warm
   model at a time to avoid swap thrash. Resolution: the hot tier (companion
   LLM, critic) is reserved for interactive work and always resident; during
   the day a Workshop request may preempt a warm-tier load (bounded to a swap
   budget per hour); at night, after client detach (D §21:14), batching is
   strict. A request that would thrash goes to the queue *by design* — that is
   the third clock rule, not a failure.
9. **Recipe storage: event-sourced SQLite, not git-as-database.** The sources
   fix the properties (diffable, branchable, replayable, kilobytes — V) but not
   the substrate. Git is kept for what it is already good at here — the engine
   repo and engineer worktrees (the lm-ops seed loop, V) — while the recipe
   store lives in the same transactional ledger as everything else, so a
   sealed prediction, its branch pointer and its budget spend commit or roll
   back together. A derived human-readable mirror (`recipes/*.json`, content-
   addressed) gives diff tooling without a second source of truth.
10. **Utterances.** The confirm line — a specification the owner approved — is
    the durable record of a work order; the raw utterance is retained only for
    the owner and only until terminal state (then purged). Magnus produces no
    free text at all (chips only), so there is nothing of his to retain
    (T §"The privacy boundary": nothing he says is retained as text).
11. **Recipe and USD.** R §8's verdict adopted verbatim: the typed recipe is
    the source of truth; USD is a deterministically compiled, layered output
    for interchange (SimReady profiles, Blender, the ProArt); the only
    USD→recipe path is asset import, wrapped by a recipe entry carrying its
    licence. USD's opinion/composition semantics are actively hostile to the
    diffable, typed, branch-by-character model the whole design rests on.

---

*End of spec. Everything above is design; no code outside this directory was
touched. The reports this builds on: V (`vision.md`), D (`ux-day.md`),
T (`ux-trust.md`), R (`res-cad.md`).*
