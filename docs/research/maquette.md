# REPORT — the `maquette` fork of Infinigen: what to harvest for builder-ide

**Study date:** 2026-10-31 · **Subject:** `github.com/tangos302/infinigen` (fork of `princeton-vl/infinigen`) · **Mode:** read-only — cloned to `/tmp/maquette-fork`, nothing executed, nothing forked/starred/issued.

**Sources read:** `builder-ide/docs/vision.md`, `docs/design/core-spec.md` (v2), `docs/plan.md`, `docs/research/forks.md` (§0 + N1), and the fork — all four branch tips, every file under `infinigen/maquette/` on `maquette`, the pipeline/runtime files on the other branches, `MAQUETTE.md`, `CHANGELOG.md`, `TOOLS_SURVEY.md`, `FACTORIES_GUIDE.md`, `SCENE_PROMPTS.md`, plus the GitHub API for licences and identity.

---

## 0. TL;DR — and one correction to the brief

**The brief's premise mixes two different branches.** It says "branch `maquette` … a LOD/instancing/Draco bake for a browser client (~58k LOC)". Both halves of that are true of *`maquette-eroded-terrain`*, not of `maquette`:

| Branch | Tip | Date | `.py` under `infinigen/maquette/` | LOC | Commits ahead of upstream `main` | LOD/Draco bake? |
|---|---|---|---|---|---|---|
| `maquette` | `0893406b` | 2026-04-30 | 52 | **15,752** | 80 | **no** |
| `maquette-buildings` | `6cb6ceed` | 2026-04-28 | 12 | 2,103 | 30 | no |
| `main` | `fb5d6d55` | 2026-05-07 | 108 | 29,644 | 163 | **yes** (`runtime/lod_bake.py`) |
| `maquette-eroded-terrain` | `9c2d909c` | 2026-06-12 | 157 | **58,418** | 168 | **yes** |

Verified: `git grep -ilE "draco|gltf-transform|ktx2"` over the **entire** `maquette` tree returns **zero hits**. The 58k figure is `maquette-eroded-terrain`'s.

Topology (this matters for what to copy): `maquette`'s tip is an **ancestor of the fork's `main`** — it was merged and left 83 commits behind; `maquette-eroded-terrain` is 5 commits ahead of `main` and contains everything `main` has. So the "maquette" work is one continuous line of development: `maquette` → `main` → `maquette-eroded-terrain`. **There is no separate prototype to adopt — there is one prototype, in three snapshots.**

**The headline for us:** the fork prototypes our *builders layer* well and our *night* not at all. It has no scheduler, no budget, no recipe store, no typed vocabulary, no characters, no door. What it *does* have, and what we genuinely lack, is a **closed-loop LLM→build→find-gap→implement-gap→rebuild** cycle that closes **inside one process**, and the **empirical record** (22 real prompt attempts with gap tables) that it does close. That record is the most valuable thing in the fork.

**The headline for licence:** the fork is BSD-3 and the code is freely takeable — but three of its claims need correcting before we touch anything (details in §2):
- the 36 MB of textures are **CC0 (Poly Haven)**, not unlicensed — the fork scout's "unlicensed textures" flag is wrong;
- the `building_tools` dependency is **MIT at v1.0.13**, not GPL-3 — the fork's own CHANGELOG misstates it;
- the 434 bundled GLB models have **no provenance and no attribution at all** — those *are* a real licence hole, and they are the only one.

**Recommendation in one line:** take the *ideas* in §3 (guide-from-code, prompt-aware catalog filter, gap ledger, phase marker, the LOD bake as a sizing spike); take **no code** except the four upstream-compat patches and the CC0 textures; ignore the whole factories/terrain art direction.

---

## 1. Its architecture, mapped piece by piece onto ours

### 1.0 What the fork actually is

One CLI. `pipeline/cli.py` runs a single-shot pipeline:

```
prompt → build_prompt() → claude -p (LLM writes a Blender build script)
       → extract script from ```python fences
       → extract "# REQUESTED_ASSET:" comments from the script  → gap_tracker
       → [if --local] implement each missing factory (a second claude -p subprocess)
       → rebuild the catalog from the new code → re-run the LLM → new script
       → blender --background --python build.py  → .blend + .png
```

The five modules, on `maquette` (1,869 LOC total). `cli.py`, `gap_tracker.py`, `implementer.py` and `__init__.py` are **byte-identical across `maquette`, `main` and `maquette-eroded-terrain`** (verified by SHA-256); `runner.py`, `executor.py` and `factories_guide.py` differ on each. `maquette-buildings` is an early side-branch with **no pipeline at all** (12 files, 2,103 LOC — factories only).

| Module | LOC | What it does |
|---|---|---|
| `pipeline/factories_guide.py` | 17,390 (maquette) | Builds the factory catalog **by AST-parsing the factory source files** — class name, docstring pitch, `_<X>_ARCHETYPES` tuples, `__init__` signature with annotations and defaults. Emits Markdown. |
| `pipeline/gap_tracker.py` | 4,246 | The gap ledger. Parses `# REQUESTED_ASSET: <Name> — <spec>` comments out of the generated script; keeps a dated, counted Markdown table (`Factory \| First seen \| Last seen \| Count \| Spec`) in `requested_assets.md`. |
| `pipeline/implementer.py` | 6,241 | Spawns `claude -p` to write **one** missing factory module into the fork tree, then smoke-tests it (import + instantiate per archetype + assert face count > 0). |
| `pipeline/runner.py` | 23,497 | Assembles the prompt (catalog + a long scene brief + hard rules + a canonical example script), calls the LLM, extracts the script, title, plan and requested assets. |
| `pipeline/executor.py` | 1,619 | Runs `blender --background --python script.py` with `MAQUETTE_OUT_DIR` set; captures stdout/stderr. |

Plus `runtime/checkpoint.py` (3,358) — the live-evolution marker (§1.6). The `runtime/` package grows from **3 modules** on `maquette` (`checkpoint`, `terrain`, `__init__`) to **18 on `main`** and **21 on `maquette-eroded-terrain`** — the new ones are scene-authoring helpers: `eroded_terrain`, `village_wfc` / `village_tile_wfc` (WFC settlement), `scatter` / `realistic_scatter`, `path_refine`, `dress_path`, `camera`, `composition`, `landmarks`, `influence`, `strata_bridge`, `multi_angle`, `reshoot`, `terrain_textures`, `loaded_factory`, and `lod_bake` (298).

### 1.1 Characters / vocabulary / the door

**Ours** (`core-spec.md` §1.5): a `VocabularyEntry` is a *closed, typed* record — `word` (dotted, ≤3 segments), `kind` (9-value closed set), `owner_character`, `status`, `params` (JSON Schema, draft 2020-12 subset: ≤8 properties, `additionalProperties: false`, nesting ≤2, ≤512 bytes canonical), `acceptance_template`, `taste_notes`, `provenance`, `version`. A character calls `POST /v1/vocab/call {word, node|region, params}`; the core validates against the schema, binds the acceptance template, and produces a `RecipeEdit`. Anything outside the schema is **refused at the door** — and that refusal, said in character, is a product moment. A word is added *only* by the core, *only* from a kept work order or by the owner. Capability claims are derived views over `vocab.call` counts, never a new record.

**Theirs:** there is no character, no vocabulary, no door, no promotion event. There is exactly one actor — an LLM — and it writes Python. The "closed catalog" is a **Markdown string injected into a prompt**. What is genuinely closed is *the set of factory classes that exist as importable modules*; what is *not* closed is anything about how they are called. The only constraints are (a) the class must exist in the catalog text, and (b) the model is asked to emit `SCENE_PLAN` JSON with exact class names. Nothing validates a call.

| | Verdict |
|---|---|
| **Matches** | Both want a *finite* set of things the world can contain, both derive the set from real code rather than prose, and both make the LLM name things by exact identifier. |
| **Differs** | Ours is a *data* contract (JSON Schema, bound at a door, versioned, owned, provenance-stamped). Theirs is a *text* contract (a prompt). |
| **Ahead (theirs)** | **The catalog cannot drift from the code.** `factories_guide.py` reads the real `__init__` signature, annotations, defaults and archetype tuples out of the source, so the guide always tells the truth about the engine. Our `VocabularyEntry.params` schema is hand-written and *can* drift from the engine's real signature — exactly the risk our `vocab.lock` idea gestures at but does not yet close. |
| **Weaker (theirs)** | No typing, no bounds, no validation, no refusal, no provenance, no `owner_character`, no taste ledger, no version. `spawn_asset("LowPolyHouseFactory", height=9999)` is accepted because nobody is checking. The refusal moment — the thing our spec calls a *product* moment — does not exist, because there is no door to refuse at. |

The cheapest way to take their advantage without giving up ours: **keep our typed vocabulary as the source of truth, and add their reflection as a *check*.** A nightly step that maps each `VocabularyEntry` to the engine function's real signature and fails the gate on mismatch is worth more than either scheme alone. See §3 item 2.

### 1.2 Work orders / the engineer adapter

**Ours** (§1.3, §2.1–2.3): `WorkOrder` carries `goal` (≤2000 chars), `targets`, `vocabulary_gap`, `acceptance` (≥1 machine-checkable check **or it cannot queue**), `budget`/`rail` (gpu_minutes, hosted_cents, wall_minutes), `estimate` (marked `[e]`), `confirm_line` (≤25 words), 12 states (`compiling → questioned → draft → queued → building → testing → landed → kept/rejected`, plus `parked`/`failed`/`cancelled`), `attempts` (numbered, never reused, with a `seat`), and `evidence` — *"no card without an artifact."* The adapter is a `Protocol` (`capabilities/run/cancel`), pluggable across Claude Code / zcode / aider / OpenHands / Goose, driven by the core, working in a **worktree + seat** with hard-enforced rails, returning a `Deliverable` that is treated as a **claim** and re-verified by a merge gate (deterministic rebuild → static/unit tests → geometry check → render ladder → constraint checks → critic). Promotion of a `VocabularyEntry` happens only on *keep*.

**Theirs:** `gap_tracker.py` is the queue and it is a **Markdown table in a file outside the repo** (`FORK_ROOT.parent / "requested_assets.md"`), rows of `Factory | First seen | Last seen | Count | Spec`. There *is* a spec per gap — the LLM writes `# REQUESTED_ASSET: LowPolyBridgeFactory — a stone arch bridge crossing the stream` in the build script, and that prose is handed straight to the implementer as the spec. That is a surprisingly good `WorkOrder.goal`. But everything else is absent: no ids, no states, no persistence beyond the table, no budget, no attempts, no acceptance checks beyond "the factory produces faces", no merge gate, no keep/reject, no promotion, no audit trail.

The engineer is `implementer.py:155`: `cmd = ["claude", "-p"]`, optionally `["--model", model]`, `subprocess.run(..., cwd=FORK_ROOT)`. A single hard-coded vendor, no seam, no cancel, no event stream, no capability model, no local alternative — against our `Engineer` protocol with `Capabilities`, `EngineerEvent` and `Deliverable`.

**Where theirs is weaker:** it writes **straight into the engine working tree** (`infinigen/maquette/factories/native/{module}.py` + two `__init__.py` edits — the target path is even hard-coded to the author's machine, `/home/tang/songe/_artifacts/maquette/infinigen-fork`, `implementer.py:41`). No branch, no worktree, no seat, no rollback, no isolation, no network policy. The smoke test asserts only that the module imports and each archetype yields face count > 0 and slot count > 0 — a factory that renders grey cubes passes. The model is not pinned by default (`--model sonnet` is a moving target unless the caller passes one). And there is **no licence scan** on generated code — which is not hypothetical: the fork's own CHANGELOG mislabels one of its dependencies (§2).

**Where theirs is ahead — and this is the important one:** **the loop closes.** `cli.py:134–184` implements the full cycle in one command: generate → find gaps → implement → **rebuild the catalog from the new code** → regenerate the script against the expanded catalog → render. That "rebuild the catalog from the code" step is the bit we would otherwise have to invent: the vocabulary grows *and the context the model sees grows with it*, automatically, in the same run. Our design pays a night's budget, a merge gate and a human keep/reject to achieve the same thing — correctly, because we promise auditability theirs doesn't offer, but expensively.

`SCENE_PROMPTS.md` (65 KB) is the empirical proof the loop closes: **22 real attempts** ("medieval village by a stream", "abandoned forest campsite at dusk", "Wild West frontier town main street", …), each with a **"GAPS HIT"** table of the factories it could not build and *why the prompt needed them*, each followed by a **re-run** once those factories existed (Attempt 7 → Attempt 8 → Attempt 15 → 16 → 18 → 19 → 21 → 22 are all re-runs). Then a **cross-attempt frequency table** ranking gaps by how often they blocked a build.

**That frequency table is a prioritiser we do not have.** Our work-order queue is first-come; theirs is a demand histogram over real prompts.

### 1.3 The recipe store

**Ours** (§1.1, §1.2): `Recipe` (schema_version 2) with `EnginePin` (repo + commit + **config hash** + blender + python), `RecipeEntry` (dotted path, kind, `GeneratorRef`, `params` validated against the linked `VocabularyEntry` schema, `seed`, constraints, asset refs, origin), `RecipeVersion` branches, content-addressed stores, and a stage cache keyed on `sha256(recipe_version ⊕ engine_pin ⊕ stage ⊕ dep_keys)` with the dirty-set contract. The recipe is the unit of review, diff and replay.

**Theirs:** **there is no recipe store.** The recipe *is* a Python file — `build.py`, written by the LLM, executed by Blender. The persisted artefacts are `raw_response.md`, `build.py`, `requested_assets.txt`, `blender_stdout.txt`, `blender_stderr.txt`, a `.blend`, a `.png`, `map.obj` and the phase markers. No typing, no version, no pin, no diff, no seed discipline, no deterministic rebuild, no replay. The one thing they get right is *scope*: each new factory is one atomic commit with its spec in the commit body (`SCENE_PROMPTS.md:1826`) — a discipline that maps onto our `Evidence`/`provenance` instinct.

**Verdict: ours is far ahead; nothing to harvest, one lesson to take.** The lesson is negative and cheap: a script-as-recipe cannot be reviewed, diffed, replayed or gated — it is exactly the failure mode our `Recipe` exists to prevent. Their one transferable habit is the atomic-commit-with-spec rule.

### 1.4 The night

**Ours** (§1.9, §3.2, §5): `Night` (rails, per-model load budget, power mode, detach deadline, computed status — *"never narrated; computed"*), `Task` (slate rows with `night: None`, cost estimate marked `[e]`, states incl. `cut`), `Job` (cpu/gpu lanes, claim token, lease, heartbeat, `stage_cache` hit/miss/partial), the sealed-bet loop (edit → predict → preview → geometry check → critic → keep/revert), graduated throttling (80% stop opening batches, 95% stop and report, 100% commit and write the report), and the morning report. Multi-lane, budgeted, restartable, audited.

**Theirs: no night exists.** There is no scheduler, no lanes, no rails, no clock, no budget, no report, no restart, no heartbeat. The "night" is one `claude -p` call and one Blender run, started by a human at a terminal. `executor.py` has a `timeout_seconds`; that is the entire resource discipline.

**Verdict: this is the largest gap, and it is a gap in *their* favour to fill, not to copy.** Nothing in the fork informs the night. What it *does* give us is the **substrate the night would run on**: `runtime/` is a library of scene-authoring helpers — terrain (FBM + ridges), eroded terrain (SDF + marching cubes), WFC village/settlement tiles, scatter, path refinement, camera placement, composition. These are the "runtime verbs" a scene script calls instead of writing raw `bpy`. Two of them are directly relevant to our night:

- `runtime/checkpoint.py` — the live-evolution marker (§1.6), which is the **only** thing in the fork that resembles our warm scene server;
- `runtime/lod_bake.py` — the browser export (§1.6), which is a concrete instance of our §6.2 step 4.

**One important caveat about their `runtime/` helpers:** they are *not* in the catalog. The brief names two of them by hand with import snippets — `from infinigen.maquette.runtime.terrain import make_terrain` (`runner.py:122–135`) and `from infinigen.maquette.runtime.checkpoint import checkpoint` (`runner.py:110–111`) — and the example scripts use more. But there is no discovery mechanism for them: no signature listing, no closure, nothing that tells the model the other 18 exist. So their "closed catalog" covers **assets** but not **scene operations** — a hole in their model of the world that our typed vocabulary would not have.

### 1.5 — 1.6 LOD / ghost export to the client

*(Two separate, disconnected exports. They are not one pipeline.)*

**Ours** (§6.2 item 4, §4.3): a deterministic recipe→glTF/USD compiler — sorted prims, no timestamps, one layer per concern, provenance in `customData`, LOD/impostor export walking placeholders + room solids + scatter densities, the `since_version` delta channel, a nightly pre-bake of each morning option's manifest, glTF-first (bpy has `WITH_USD=OFF`), NVENC clips for the filmstrip. The client is told `world.dirty` **carrying `{branch, head}`** so it fetches a `since_version` **delta, not everything**; `/v1/world/scene` serves glTF now, USD later.

**Theirs — live path:** `runtime/checkpoint.py`. `checkpoint('terrain')` exports **the entire scene** to `$RUN_DIR/map.obj` via `bpy.ops.wm.obj_export` and writes `$RUN_DIR/_phase_{phase}.json` = `{phase, timestamp, obj_path, history}`. A runner tails the directory and the frontend cache-busts the OBJ URL — but both live in the **companion repo, which is not public** (§2.2), so we can only read the writer, not the reader. The prompt names five phases (terrain, foliage, structures, props, final, `runner.py:102–109`); the canonical example script uses six, adding `water`.

**Theirs — offline path:** `runtime/lod_bake.py` (on `main`/`maquette-eroded-terrain`). A shell pipeline over `gltf-transform`: `dedup` → `instance` → `simplify --ratio 0.25` → `quantize` → `draco`, producing `scene_baked.glb` plus a manifest `scene_lod.json` = `{version, glb, glb_baked, lod_ratios, instance_extension}`.

| | Verdict |
|---|---|
| **Matches** | Both take the shape "build a scene → export → the browser consumes it". Both want a lighter payload for the client. |
| **Differs** | They have no recipe behind the export, so there is nothing to diff and nothing to delta against. Ours is a compiler *from the recipe*; theirs is a post-process over a finished scene. |
| **Ahead (theirs)** | **It is a working, measured pipeline, not a plan.** Ours describes exactly this step list in prose (§6.2.4) with no reference implementation. Theirs tells us the actual tool chain (`gltf-transform` does all five transforms; Blender's own Draco exporter plus a `draco` pass is idempotent) and the actual artefact shape. That is a real de-risking of our most under-specified milestone item. |
| **Weaker (theirs)** | Five concrete defects: (1) the "4-level LOD chain" in the manifest is **a lie** — `lod_ratios` is metadata; only **one** `simplify` pass runs, so there is one simplified mesh, not four LODs; (2) `toktx` is *probed* in `tools_available()` and **never invoked** — KTX2 never happens, textures stay PNG; (3) the manifest declares no instancing **templates** at all (the `instance` transform duplicates identical meshes; the manifest schema has no template list); (4) **no determinism** — Draco + `gltf-transform` output is not byte-stable across runs, so it cannot pass our §2.3.1 deterministic rebuild; (5) **no provenance, no version, no delta channel** — nothing ties the GLB to a recipe version, so `since_version` is impossible. |
| **Weaker (ours, relative)** | The checkpoint→OBJ path is *also* worse than ours in the same ways: a **whole-scene re-export per phase** (O(scene) each time), OBJ (huge, slow, no materials in any useful form), no delta, no LOD, no instancing. It is a 100-line demo, not a wire format. But its *idea* — a phase marker the client polls — is the cheapest possible proof of "the scene evolves while you watch", which is worth having for our M1 slice. |

One structural note: their checkpoint mechanism is **convention, not contract**. The LLM is *instructed* in the prompt to call `checkpoint('<phase>')` at each boundary (`runner.py:102–113`); the example scripts do it. Nothing enforces it, nothing validates phase ordering, nothing checks that a phase happened. Ours would need the marker to be a first-class record.

### 1.7 Summary

| Ours | Theirs | Match / differ / ahead / weaker |
|---|---|---|
| Typed vocabulary + door (§1.5) | Markdown catalog in a prompt | **Match** on "finite, code-derived". **Ahead of them:** typing, refusal, provenance, promotion. **Ahead of us:** the catalog can't drift from the code. |
| Work order + engineer adapter (§1.3, §2) | Markdown gap table + `claude -p` subprocess | **Ahead of us:** the loop closes in one process, and 22 attempts prove it. **Ahead of them:** states, seats, rails, evidence, gate, keep/reject, pluggable seam. |
| Recipe store (§1.1) | A Python file | **Ahead of us, decisively.** Nothing to harvest but the atomic-commit habit. |
| Night (§1.9, §3.2) | — | **Absent.** They prototype nothing here. The substrate is `runtime/`. |
| Ghost/LOD export (§6.2.4, §4.3) | `checkpoint()`→OBJ; `lod_bake.py`→glb | **Ahead of us:** a measured toolchain and a manifest shape. **Ahead of them:** determinism, provenance, deltas, real LODs. |

---

## 2. Licence and authorship

### 2.1 The fork itself

- **Licence: BSD-3-Clause**, `LICENSE` at the repo root — *"Copyright (c) 2023 Princeton University. All rights reserved."* — inherited from `princeton-vl/infinigen` and **unchanged**. GitHub reports the fork as BSD-3-Clause. The only other licence file in the tree is upstream's own `infinigen/terrain/mesh_to_sdf/LICENSE`.
- **The fork adds no licence file and no SPDX/copyright header to any of the new files** under `infinigen/maquette/` (52 `.py` on `maquette`, 157 on `maquette-eroded-terrain`; a grep for `copyright|licence|license|SPDX` across the package hits only prose in `CHANGELOG.md`, `TOOLS_SURVEY.md`, `SCENE_PROMPTS.md` and the two third-party wrapper files). Every one of them is BSD-3 by inheritance from the root `LICENSE`.
- **BSD-3 obligations on us if we copy:** retain the copyright notice and the BSD-3 disclaimer in redistributions; no endorsement claim. In practice: keep the root `LICENSE` text in whatever we vendor, add a `NOTICE` line naming Princeton (upstream) **and** the fork author, and keep our own repo's licence text intact. Our own `SI-Thor/infinigen-thor` is also BSD-3, so the licences are compatible in both directions.
- No CLA exists between us and the author, and none is needed for BSD-3. **Attribution is required; permission is not.**

### 2.2 Authorship

- The fork's new work is by **one person**: `tanguydelume <tanguyydelume@gmail.com>` — **80 commits** on `maquette`, **164** on `maquette-eroded-terrain`. Every other author in the history (Raistrick, Mei, Ma, Lipson, Parakh, Wang, …) is upstream Princeton/Infinigen.
- The GitHub account is **`tangos302`** (display name "Tang", Tokyo, account created 2014-11-07). The commit identity and the GitHub handle do not match by name — worth knowing before we write to them.
- Repo metadata: created **2026-04-28**, last push **2026-06-12**, **0 stars, 0 forks**, default branch `main`.
- The companion repo named in `MAQUETTE.md` — `tangos302/songe-blender-mcp`, branch `maquette`, holding the MCP server/addon — is **not publicly reachable** (GitHub API 404; it does not appear in the account's public repo list: `dotfiles`, `GameDashboard`, `infinigen`, `poissonDiskSample`, `r4cppp`, `react-navigation`). **The MCP server, the run-dir tailer and the Three.js viewer are therefore not in the fork we can read** — and the most interesting half of their system is the half we cannot see.

### 2.3 Third-party code and assets inside the maquette package

| Part | Where | Claimed | **Verified** | Verdict |
|---|---|---|---|---|
| Textures (47 files, 36.1 MB) | `runtime/textures/` | `runtime/textures/README.md:37`: *"License: CC0 — no attribution required, unrestricted commercial use."* (line 3: "CC0 1K PBR sets from Polyhaven") | Poly Haven is CC0 — stable and widely established | ✅ **Take.** Attribution appreciated, not required. **This corrects the fork scout: the textures are not unlicensed.** |
| Models (434 `.glb`, 4.1 MB) | `runtime/models/{nature,medieval}` | *nothing* — no README, no attribution, no licence anywhere in the tree | Provenance unknown; naming style resembles commercial kits | ⛔ **Do not take.** Blocked by our house rule (licences are a checked list). Ask the author, or regenerate. |
| `btools_building.py` | `factories_realistic/` | File header + CHANGELOG: "GPL-3" | **`ranjian0/building_tools` v1.0.13 is MIT** (Copyright © 2019 Ian Karanja); current master is MIT (© 2018 Jian Karan). The addon is *not vendored* — installed under `~/.config/blender/4.2/scripts/addons/` and called at runtime | ⚠️ The fork's licence claim is **wrong** (in our favour). The wrapper file is fork-authored BSD-3; the dependency is MIT with attribution. The two **local patches** applied to the addon must stay under MIT with attribution if we ever carry them. |
| `beam.py` | `factories_realistic/` | "GPL-2.0-or-later (bundled Blender addon)" | The addon (`bl_ext.blender_org.extra_mesh_objects`) is **not bundled** — imported at runtime from the installed Blender extension. Blender extensions are GPL | ⚠️ The GPL-2.0+ attaches to the **addon**, not to the BSD-3 wrapper. Fine for a separate process/addon we do not distribute; still a house decision if we ship anything. |
| `TOOLS_SURVEY.md` | doc | mentions `GoodPie/modular_tree` (GPL) | Surveyed only — **no code taken** | ✅ harmless. |
| Upstream compat patches | `CHANGELOG.md` (4 patches) | Blender 4.2 + numpy 2.x fixes | Upstream Princeton code, BSD-3 | ✅ **Copy with attribution** — but diff our own `infinigen-thor` first; we may already carry them. |

**House rule check:** licences here are a *checked list*, and the fork demonstrates the cost of not checking: its own CHANGELOG misstates a dependency's licence. Anything we take from this fork gets re-checked by us, not trusted from the source.

---

## 3. What to harvest, ranked

Effort scale: **S** ≤ 1 day · **M** 2–4 days · **L** 1–2 weeks · **XL** > 2 weeks. "Enter as" = copy-with-attribution / re-implement / learn-from-only.

### 3.1 ★ The prompt-aware catalog filter — *re-implement* (S, high value)

**What:** `factories_guide.py` on `maquette-eroded-terrain`, `build_guide(mode, user_prompt=…)` (line 1219) and `_file_keywords` (line ~300) with `_FACTORY_KEYWORD_EXPANSIONS` (line 263) and `_ALWAYS_FULL_STEMS` (line 384). Prompt tokens are matched against a per-factory keyword set (class-name tokens + archetype values + hand-curated synonyms + docstring pitch nouns). Hit → **full entry** (signature, types, defaults); miss → **one-line summary**. Commit `8470804e`: *"prompt-aware factory filter (33-37% catalog reduction); unmatched collapse to one-liners."* The docstring claims "typically halves" — the commit's measured figure is 33–37%. `_ALWAYS_FULL_STEMS` pins `tree` and `boulder` to full entries on every prompt, *"preventing the model from skipping them on narrow prompts"*.

**Why we care:** this is the **vocabulary-as-context-budget** problem. Our context packets (§1.4) must decide which of N vocabulary words to show a character; we have no mechanism for that yet. Theirs solves it in 60 lines with lexical overlap. The `_ALWAYS_FULL_STEMS` escape hatch is a nice touch: some entries must always be present.

**How it enters:** re-implement, do not copy. Their scorer is lexical overlap only; ours should rank on `kind` + `owner_character` + `status` + the params schema, with lexical overlap as a tiebreak, and it must be **ours that decides what a character may see** — the whole point of our door is that the character does not choose its own vocabulary. Copy the *mechanism* and the *escape hatch*; write our own ranker.

**Effort:** S for a lexical baseline; then A/B it against a "show everything" baseline on prompt hit-rate.

### 3.2 ★ The catalog derived from the code — *re-implement as a check* (M, high value)

**What:** `factories_guide.py`'s core — `ast.parse` each factory file, find the class, find `__init__`, extract parameters with annotations and defaults, find `_<X>_ARCHETYPES` and `_ARCHETYPE_DEFAULTS` by convention, emit a Markdown entry. It never imports Blender, so it works headless.

**Why we care:** our `VocabularyEntry.params` schema is hand-maintained and can silently drift from the engine's real signature — a character calls `bridge.rope` with `{length: 12}`, the engine expects `span`, and the build fails at 2 a.m. inside a work order. Theirs cannot drift. `vocab.lock` in our spec is the instinct; this is the mechanism.

**How it enters:** re-implement as a **nightly gate check**, not as the source of truth. Map each `VocabularyEntry` → the engine generator's real signature; mismatch ⇒ fail the gate with a diff. Our schema stays authoritative; their trick becomes the auditor. Bonus: the same mapper gives us the params→JSON-Schema generator we want for the §1.5 subset rules (≤8 props, `additionalProperties: false`, numeric bounds).

**Effort:** M — needs an Infinigen-signature→JSON-Schema mapper and a naming convention for our `GeneratorRef` → factory mapping.

### 3.3 ★ The one-command gap→implement→re-guide→re-run loop — *learn from, re-implement the shape* (M, high value)

**What:** `cli.py:134–184`. Generate → gaps → implement → **regenerate the catalog from the new code** → regenerate the script → render. All in one process.

**Why we care:** ours can do this too, but only through the whole night machinery (budget → queue → seat → gate → keep/reject → promotion), which is the right shape for auditability and the wrong shape for *learning whether the loop closes*. We have no cheap way to ask "if the vocabulary had `bridge.rope`, would the scene build?"

**How it enters:** build a **scratch harness** — our adapter protocol, our typed vocabulary, our gate checks — but running with no budget, no keep/reject, no writes to the store: everything into a temp dir, everything disposable. This is the "dry-run the night" mode we want anyway, and it is the cheapest possible proof of our §2.3 design before we trust it with the store.

**Effort:** M. **Value:** de-risks the most expensive assumption in the spec.

### 3.4 ★ The empirical gap ledger (`SCENE_PROMPTS.md`) — *learn from, copy the shape* (S + project time, high value)

**What:** 65 KB. 22 real prompt attempts, each with a **"GAPS HIT"** table (missing factory → why the prompt needed it) and, where applicable, a **re-run** once the factory existed. Then a **cross-attempt frequency table**. Then the missing-object specs in a fixed shape: class name · key dimensions · archetypes · defaults · material slots · polycount target · implementation hints — *"so they can be implemented in atomic commits later."*

**Why we care, two ways:**
1. Their spec shape is a good template for our `WorkOrder.goal` (≤2000 chars) and for a `VocabularyEntry`'s params schema. Ours is written as prose requirements; theirs is a checklist a builder can implement from.
2. **Their 22 attempts are a ready-made prompt corpus.** We can run *our* vocabulary against those 22 prompts and measure coverage directly — that is the empirical answer to "is the vocabulary big enough?", which we currently have no way to produce.

**How it enters:** adopt the *shape* (a prompt→gaps ledger, with a frequency table, and the spec template); take the 22 prompts as test fixtures; do not take the content (their art direction is theirs).

**Effort:** S to adopt the template and ingest the prompts as fixtures. The ledger itself is a project artefact we then maintain.

### 3.5 ★ The phase marker (`runtime/checkpoint.py`) — *learn from, copy the marker shape* (S, medium-high value)

**What:** 100 lines. `checkpoint(phase)` → whole-scene OBJ export + `_phase_{phase}.json` = `{phase, timestamp, obj_path, history}`. The client polls and cache-busts.

**Why we care:** it is the cheapest possible demonstration of "the scene evolves while you watch" — exactly our M1 "one evening, one night, one morning" milestone, and the only part of their system that touches our warm-scene-server idea. The marker shape (`phase`, `timestamp`, `obj_path`, `history`) maps onto our `world.dirty` event.

**How it enters:** copy the *marker shape*, not the mechanism. Our event must carry `{branch, head}` and point at a **delta**, and our payload must be a recipe-derived glTF, not a whole-scene OBJ. But for a one-evening demo, a marker plus a cheap preview is exactly the right size.

**Effort:** S. **Caveat:** their phases are convention — the LLM is *asked* to call `checkpoint()` and nothing enforces it. Ours must make the phase a record the core writes, not a call the model makes.

### 3.6 ★ The LOD bake as a sizing spike — *re-implement as a spike* (S to spike, M/L for real) (medium-high value)

**What:** `runtime/lod_bake.py` on `main`/`maquette-eroded-terrain` — `gltf-transform` pipeline `dedup → instance → simplify(0.25) → quantize → draco`, manifest `scene_lod.json`.

**Why we care:** our §6.2.4 is our most under-specified milestone item and it is the item with the most "we'll know when we measure it" in it. Theirs is a working reference chain we can run against a real scene and get real numbers on payload size and wall-clock. **We would learn the cost of our own step 4 for the price of a day.**

**How it enters:** re-implement as a **spike** (do not adopt as our export path). Take the step list and the manifest shape as prior art; then build the real thing — recipe-driven, deterministic, with provenance in `customData`, per-LOD meshes, real KTX2, and a delta channel.

**Effort:** S for the spike; M/L for the real path (which we were doing anyway).

### 3.7 The low-poly factory catalog — *learn from, do not copy* (S to adopt one trick, XL to port)

`factories/` — 27 `.py` (24 of them under `factories/native/`), 8,958 LOC on `maquette` — is BSD-3 and legally takeable, but it is *their art direction* (Firewatch-ish low-poly, painterly Sky-CotL terrain), and our vocabulary is about structure, constraint and rooms rather than decorative props. Porting it would be an XL project that would fight our art direction.

**The one trick worth taking:** archetypes whose defaults are **derived from the bounding box** (`density.py`) — a word like "crate" can accept any size and still look right, because the knob values scale with the box. That maps directly onto our §1.5 params subset, where numeric ranges must exist: it suggests the schema should express **ratios**, not absolutes, so one word serves a range of sizes.

**Effort:** S for the idea. **Value:** medium — it improves the shape of our params schemas.

### 3.8 The upstream compat patches — *copy with attribution* (S, medium value)

Four small patches for Blender 4.2 + numpy 2.x (`node_utils.assign_curve`; `BoulderPile`), recorded in `CHANGELOG.md`. Our own `infinigen-thor` faces the same Blender wall, so these may save us an afternoon. **Diff our fork first** — we may already have them.

### 3.9 `terrain/` — *out of scope* (L, unknown value)

`terrain/` is **7 files / 3,714 LOC of CPU terrain** (FBM, ridges, SDF + marching cubes) — **identical on `maquette` and `maquette-eroded-terrain`**; the eroded-terrain work that came later lives in `runtime/eroded_terrain.py` and friends, not here. This is a *different scope* from the builders layer and overlaps our own Thor-native terrain work (`docs/research/split.md`). **Do not harvest now.** Note it as an available corpus if the terrain milestone ever wants a reference.

### 3.10 `TOOLS_SURVEY.md` — *copy the list* (S, low-medium value)

A survey of external Blender tools with licences and fit assessments (Building Tools, Infinigen Indoors, Modular Tree, Buildify, …). Cheap to adopt as a starting list for our own survey; it is also the file that shows the fork's art-direction pivot (*"start drifting toward template-and-randomize (kit-bash) style"*).

---

## 4. What to avoid — and why our design differs

1. **Don't copy the implementer's execution model.** `claude -p` with inherited permissions, `cwd` = the engine checkout, target path hard-coded to the author's machine, no branch, no seat, no rollback. A bad factory leaves a dirty engine tree. Ours is a `Protocol` behind a worktree + cgroup seat with hard rails and cancel.
2. **Don't copy the prompt-as-contract.** Theirs is prose in a prompt; ours is JSON Schema at a door, and a character must never be able to smuggle free text into a build.
3. **Don't copy `gap_tracker`'s frozen ledger semantics.** The `REQUESTED_ASSET` table is a Markdown file outside the repo with no ids, no state, no budget and no audit. Ours is a `WorkOrder` row with a state machine and evidence. (Copy the *spec-in-the-request* idea; copy the *frequency table* idea; copy neither the *storage* nor the *lifecycle*.)
4. **Don't copy the checkpoint→OBJ contract.** Whole-scene re-export per phase, OBJ, no delta, no LOD, no version. Ours needs `{branch, head}` + `since_version` deltas + a recipe-derived glTF.
5. **Don't copy `lod_bake.py` as our export path.** It is a scene-level post-process, not recipe-driven; its output is not byte-stable (fails our deterministic rebuild); its manifest declares a 4-level LOD chain that does not exist; `toktx` is probed and never called; there are no instancing templates in the manifest; there is no provenance and nothing to delta against. Use it as a **sizing spike**, not as an implementation.
6. **Don't take `factories_realistic/`.** It depends on Blender addons that live outside the repo, are patched in place locally, and whose licences the fork itself misstates. Their own CHANGELOG records that three of its factories are broken: `RealisticTreeFactory` silent-exits above 5 spawns (upstream twig-collection accumulation), `RealisticBoulderPileFactory` is disabled (cascading upstream bugs), and `RealisticMengerSpongeFactory` falls back to a cube. Unmaintained since 2026-06-12.
7. **Don't take the 434 GLB models.** No provenance, no attribution, no licence. Blocked.
8. **Don't take the "prompt → one big script" architecture.** No recipe, no diff, no replay, no determinism, no seed discipline — precisely what our `Recipe` exists to prevent.
9. **Don't copy the path conventions.** `MAQUETTE_OUT_DIR` / `maquette_session` hard-codes *their client's* directory layout into an engine helper, and the generated scripts `sys.path.insert` a machine-specific absolute path (`/home/tang/songe/_artifacts/maquette/infinigen-fork`) — so the artefacts are not portable or replayable anywhere else. Our wire format is core-defined; an engine helper must not know the client's layout.
10. **Don't copy the docstring discipline.** `--local`'s help text says "NOT YET IMPLEMENTED in phase 1" while the code 100 lines below implements it; `lod_bake.py`'s docstring advertises a "4-level LOD chain" that produces one simplified mesh; the CHANGELOG misstates a dependency's licence. Cheap to fix in a fork; expensive in a thing other people read. (It is also the reason we checked the licences ourselves rather than trusting the fork's own labels.)
11. **Don't mistake the fork for a night prototype.** There is no scheduler, no budget, no lanes, no report, no restart. §1.4 is not harvestable — it is the thing we are building.

---

## 5. Should we reach out to its author? *(a question for Casey — no action taken)*

**My recommendation: yes, but as a small, late, specific ask — and only after we have extracted everything we can from the public tree.**

**Why the timing matters:** the fork's last push is **2026-06-12**, about four and a half months ago. It has **0 stars and 0 forks**. The companion repo that holds the MCP server, the run-dir tailer and the Three.js viewer (`tangos302/songe-blender-mcp`) is **not publicly reachable** — so the most interesting half of their system may be private, discontinued, or simply not published. We should assume the maintainer may be gone.

**What we would want from the conversation (ranked by value):**

1. **Is `songe-blender-mcp` available?** That repo holds the MCP server and the client that consumes `checkpoint()` and the baked GLB — i.e. the half that would tell us whether the *live scene evolution* actually worked in practice, or was only ever a file-polling demo. This is the single most valuable unknown in the whole fork, and it is the one thing we cannot get by reading.
2. **Was the reflection-derived catalog guide a deliberate design or a convenience?** Their `build_guide(prompt=…)` filter and the AST-based catalog are the two ideas we most want to adapt. Knowing whether they hit a wall with lexical matching (my expectation) would save us the experiment.
3. **Is the project still alive, and would they be open to us using the code?** BSD-3 needs no permission, so this is courtesy plus information — and it may open the private repo.
4. **What broke last?** Their CHANGELOG's "known limitations" list (broken tree factory, disabled boulder pile, Menger sponge fallback) hints at where the Infinigen-realistic path gets hard. Useful for our own generative stations.

**How to frame it:** as *"we studied your maquette pipeline and borrowed the guide idea"* — not as a rescue pitch, and not as a collaboration proposal yet. The fork has 0 stars and a stale CHANGELOG; an approach that reads as "let us save your work" is unlikely to land. A short, specific, technical note with a concrete question is more likely to get a reply from a dormant single-maintainer.

**What not to do:** don't fork, star, or open an issue to "wake it up" (the brief forbids it, and a star on a 0-star fork is noise); don't propose a collaboration before we know whether they consider the work shareable; and don't reach out *first* — reaching out before reading is how you end up asking for things you could have just read. Everything in §3 is available without a single message.

---

## Appendix A — corrections to `docs/research/forks.md` (the fork scout's report)

Read-only cross-check, not a criticism — three of these change decisions, one changes a licence answer.

| forks.md says | **Verified** |
|---|---|
| "branch `maquette` … ~58k LOC" | The 58k figure is **`maquette-eroded-terrain`** (157 files / 58,418 LOC). Branch `maquette` is **52 files / 15,752 LOC** and was merged into the fork's `main` back on 2026-05-07. |
| "a LOD/instancing/Draco bake for a browser client" (on `maquette`) | **Not on `maquette`.** `runtime/lod_bake.py` exists only on `main` and `maquette-eroded-terrain`; zero draco/gltf/ktx hits in the whole `maquette` tree. |
| "35 MB of unlicensed textures" | **Wrong — they are CC0.** `runtime/textures/README.md:37`: *"License: CC0 — no attribution required, unrestricted commercial use."* (Poly Haven). 36.1 MB, 47 files. Take them. |
| "every fork is BSD-3-Clause, unchanged — code is safe" | **Half right.** The repo is BSD-3 and no licence text was *added*, but: the fork **misstates** `building_tools` as GPL-3 (it is **MIT** at v1.0.13); the Blender `extra_mesh_objects` extension it wraps is **GPL-2.0+**; and the **434 bundled GLB models have no licence or attribution at all** — the only genuine hole. |
| "the implementer's wiring is incomplete — `cli.py --local` is 'NOT YET IMPLEMENTED in phase 1'" | The **docstring** is stale, not the code: `cli.py:133–184` implements the whole gap→implement→re-guide→re-run cycle. The stale help text is itself the lesson (§4.10). |
| "the prompt-aware filter typically halves the catalog token weight" | The docstring says "halves"; the commit that shipped it (`8470804e`) says **33–37% catalog reduction**. Use the measured figure. |
| (not mentioned) | **The companion repo `tangos302/songe-blender-mcp` is not public** — the MCP server and the client are not in the fork we can read. |
| (not mentioned) | The fork's **most valuable artefact is not code**: `SCENE_PROMPTS.md` — 22 real prompt attempts, gap tables, re-runs, and a cross-attempt frequency table. That is a prompt corpus and a demand histogram we can reuse. |
| (not mentioned) | The gap mechanism is **not** a hard-coded dict: the LLM emits `# REQUESTED_ASSET: <Name> — <spec>` comments in the build script, and the tracker parses them into a dated, counted ledger with the spec text — i.e. an ad-hoc work-order queue with a goal per order. |

## Appendix B — what I read

**Fork (branch `maquette`, tip `0893406b`, cloned to `/tmp/maquette-fork`):** `pipeline/{cli,executor,factories_guide,gap_tracker,implementer,runner,__init__}.py` (all read in full) · `runtime/{checkpoint,terrain,__init__}.py` · `factories/` (27 `.py`) · `terrain/` (7 `.py`) · `FACTORIES_GUIDE.md` · `SCENE_PROMPTS.md` · `TOOLS_SURVEY.md` · `MAQUETTE.md` · `LICENSE` · `pipeline/examples/medieval_village.py` (the canonical few-shot example).

**Fork (other branches, read via `git show`):** `origin/main:infinigen/maquette/{CHANGELOG.md,runtime/textures/README.md,factories_realistic/{btools_building,beam}.py}` · `origin/maquette-eroded-terrain:infinigen/maquette/{runtime/lod_bake.py,pipeline/factories_guide.py}` (full + the prompt-aware-filter diff against `maquette`).

**Git history:** all four branch tips, merge-bases, per-author commit counts, commit counts ahead of `princeton-vl/infinigen:main`, and the branch topology (`maquette` ⊂ `main` ⊂ `maquette-eroded-terrain`).

**Ours:** `builder-ide/docs/vision.md` · `docs/design/core-spec.md` §§1.0–1.9, 2.1–2.6, 3.1–3.5, 4.1–4.3, 5.1–5.6, 6.1–6.2 · `docs/plan.md` §§1–6 · `docs/research/forks.md` §0 + N1 · `CLAUDE.md`.

**Licences verified externally:** `ranjian0/building_tools` — MIT at tag `v1.0.13` (© 2019 Ian Karanja) and MIT on master (© 2018 Jian Karan); `tangos302/infinigen` — BSD-3-Clause, fork of `princeton-vl/infinigen`, created 2026-04-28, pushed 2026-06-12, 0 stars, 0 forks, default branch `main`; `tangos302/songe-blender-mcp` — **not public** (404).

**Not done, deliberately:** nothing was executed, no Blender was started, no GitHub action was taken (no fork, star, issue or PR), no network calls to the author's own infrastructure.
