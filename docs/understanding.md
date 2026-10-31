# builder-ide — the comprehensive understanding

*Round 3, part 1. Written 2026-10-30 from the whole document set — the output of the
three-round plan in `rnd-plan` §Round 3. Synthesis only: this file changes nothing else,
and no fact below was invented — every one carries its source document and section.*

**How to read the citations.** The key in [§0](#0-sources-and-how-numbers-are-marked)
names the file behind each short tag (`[vision §The pieces #2]` means *vision.md*, section
"The pieces", item 2). Three locator styles are used, and they are the sources' own:

- `§1.4`, `§5.6` — a numbered **heading** in that document.
- `§3.2.8`, `§2.3 step 4`, `§6.2.7` — a **numbered item inside** a heading (§3.2 item 8
  is the report build; §6.2 item 7 is the generative stations).
- `§C6`, `§D1`, `§R4`, `§G2`, `§S10` — **identifier rows** in `rev-tech`'s contradiction
  list, `rev-ux`'s decision and promise tables, and `rev-ux`'s gap and spine lists.
  `rev-spec` cites the same identifiers the same way, so the references are stable across
  documents.

**How numbers are marked.** Every figure in this document carries one of four tags:

| Tag | Meaning |
|---|---|
| **[M]** | **Measured** on the Thor (or on this machine) on 2026-10-30. The "how" is given. |
| **[C]** | **Claimed** by a source document. Someone asserted it; nobody here measured it. |
| **[P]** | **Placeholder.** The source that would settle it does not exist yet. |
| **[B]** | **Budget or target.** Not a measurement and not a claim about the world — a limit the UI or the queue must meet, or a design constant (a clock budget, a decision cap, a degradation threshold). The sources use the same idea as `[b]` vs `[e]` `[gaps §Timing convention]`. |

This matters more than usual here, because the project's own rule is that *"a latency
number that did not come off this box is not evidence"* `[rev-ux §4]`, and *"Do not schedule
against the published numbers. Fill in the scheduler's throughput table from measurements on
this box"* `[res-3d §8]`. So the distinction between a budget and a measurement is not
pedantry here — it is the difference between a promise the product keeps and one it breaks.

**Where the tags apply.** The machine table in §2.2 (*the machine, measured*) is **[M]**
throughout, with the "how" in its last column. The latency tables in §2.1 (the clocks, the
spine) are **[B]** throughout: they are limits the product must meet, cited to the document
that set them. Everything else carries its tag inline.

---

## 0. Sources and how numbers are marked

| Tag | File | What it is |
|---|---|---|
| `vision` | `~/src/builder-ide/docs/vision.md` | The vision (2026-10-30). The north star and the pieces. |
| `core-spec` | `~/src/builder-ide/docs/design/core-spec.md` | The spec for the core service: data model, engineer adapter, lifecycles, APIs, durability, build order. |
| `CLAUDE` | `~/src/builder-ide/CLAUDE.md` | How a session works: machines, house rules, current status. |
| `rnd-plan` | `~/src/builder-ide/docs/rnd-plan.md` | The three-round R&D plan this document is the output of. |
| `ux-day` | `docs/research/ux-day.md` | Ideation A — "a day and a night with your builders", written as scenes. |
| `ux-trust` | `docs/research/ux-trust.md` | Ideation B — trust, taste, and growing together, written as rules. |
| `rev-ux` | `docs/research/rev-ux.md` | Round-2 review: the two experience reports against each other and against the technology. |
| `res-3d` | `docs/research/res-3d.md` | 3D generation models on the Thor: licence, feasibility, spike order. |
| `res-cad` | `docs/research/res-cad.md` | CAD, assets, textures, motion, audio, USD, the model scheduler. |
| `rev-tech` | `docs/research/rev-tech.md` | Round-2 review of the technology reports against each other and the Thor. Owns the single dependency and licence ledgers. |
| `split` | `docs/research/split.md` | Compute placement: Thor / ProArt / cloud / Orin, the wire, the power plan. |
| `bakeoff` | `docs/research/bakeoff.md` | The engineer bake-off: contenders, work orders, harness, scoring. |
| `ideas` | `docs/research/casey-ideas-fromgoogle5.md` | Casey's raw idea dump (a search result, not a report). Triaged in `split §4`. |
| `gaps` | `docs/research/gaps.md` (= `~/lm-wt/gaps/REPORT.md`) | Round-2 follow-up: designs the ten missing moments. |
| `rev-spec` | `docs/research/rev-spec.md` (= `~/lm-wt/rev-spec/REVIEW.md`) | Round-2 review of the core spec against everything else; a 20-item patch list. |

**Two named sources do not exist.** `~/lm-wt/landscape/REPORT.md` and
`~/src/infinigen-thor/thor/SPIKE.md` are both absent. The second matters a lot: the spike
report is where the Infinigen-on-Thor numbers would live, and `split §7` recorded that as
of 22:30 on 2026-10-30 the build was mid-flight (CPython 3.11 ✅, OpenImageIO ✅, terrain
CPU extensions ✅, bpy wheel ⏳). Everything that depends on it is marked **[P]** below.

---

## 1. What we are building and why

We are building **an IDE for worlds, whose builders are characters**. You talk to a small
crew of agents inside a game world — an Architect, a Landscaper, a Prop-maker, a Critic and
a Companion (the glossary has their specialities). They are avatars, not chat windows. They
work on a shared project while you are away, and come back in the morning with what they
tried, what they kept, and why.

The shape is simple: **you make a plan in the evening, they work through the night, you
read the report in the morning** `[vision §The pieces #5]`. The evening is where your
attention goes; the night is machine time; the morning report opens *before* the world,
because the night already did the rendering — so every morning latency is a UI latency and
stays fast forever `[ux-day §The three clocks]` `[rev-ux §5]`.

Three ideas hold it together.

**The recipe is the truth; the world is a cache.** A project is its recipe: generators,
parameters, constraints, seeds. Meshes and renders are derived and can be thrown away and
rebuilt. A night's work is kilobytes of decisions — diffable, branchable, replayable. Undo
is a checkout, and two alternatives are two branches `[vision §The pieces #2]` `[CLAUDE]`.
This is the deepest agreement in the whole document set `[rev-ux §R20]`.

**Builders cannot write code.** They say things a typed vocabulary already understands:
predict, render, keep, undo. When a character hits a limit ("I can't make gothic arches"),
or you do ("Computer, I want rope bridges that swing"), that becomes a **work order** — the
computer's engineer takes it, builds and tests it in a sandbox branch, and promotes the
result into the vocabulary, so tomorrow the Architect can build arches `[vision §The
architecture]`.

**Trust is a receipt, not a feeling.** Every claim a builder makes about itself must be
checkable against a stored record, or it is decoration `[ux-trust §The trust stack]`. So
predictions are **sealed before the render** and scored after it by a different party; what
you keep and reject is written down; every artefact carries its provenance and licence. The
design must answer three questions: **competence** (per-claim-type hit rates with
denominators), **legibility** (sealed cards, receipts, the report), and **restraint**
(interruption policy, budget rails, a kill switch). The third is the one most projects skip,
and it decides whether the other two read as partnership or as surveillance `[ux-trust §The
trust stack]`.

The north star is the holodeck — a shared physical-feeling space you are *in* with the
characters. We cannot build that; we build toward its UX with what we have `[vision §The
architecture]`. And the ambition is deliberately larger than a port: everything is open
source, the hardware is the Thor's, and *"heavily rewrite any program (Infinigen, Blender
stages, generators) to fit the Thor's specific chips"* is welcome — the goal is
breakthroughs, not compatibility `[CLAUDE]`. §2.8 names, for each such choice, the rewrite
option and the experiment that would prove it.

---

## 2. What we know, by subject

### 2.1 The experience

#### The three clocks

Every interaction belongs to one of three latency clocks, and the rule is *"nobody ever
waits on the wrong clock"* `[ux-day §The three clocks]`. All three budgets below are
**[B]** — limits the product must meet, not measurements of what it achieves:

| Clock | Budget | Owns | If it can't be met |
|---|---|---|---|
| **Talk** | ≤ 2 s | speech, HUD, plan items, keep/reject | never batch, never spin |
| **Watch** | ≤ 5 s per card | the night feed, verdicts, provenance | pre-render, cache, show stale-then-fresh |
| **Workshop** | ≤ 60 s, with progress and a cancel | previews, critic runs, generations | it goes to the night queue instead of the screen |

`gaps` adds a fourth discipline on top: a number is a **budget** `[b]` (the UI must meet it,
a test can check it) or an **estimate** `[e]` (it did not come off this box, so it is not a
promise) `[gaps §Timing convention]`.

#### The fifteen-moment spine

`rev-ux §5` merged the two ideation reports into one spine of fifteen moments, and that
spine is the shared vocabulary for everything downstream. In order, with the clock each
belongs to. Every budget in this table is **[B]**; the "Reality" column is where the
technology says whether the moment holds:

| # | Moment | Clock · budget | Reality verdict |
|---|---|---|---|
| S1 | First night, empty ledger — the Companion says what it cannot yet do and offers four starter choices | Talk · ≤ 2 s | holds (text) |
| S2 | The recognized return — what changed in your absence, with a count and a denominator; never comments on how long you were gone | Talk · ≤ 2 s | the *line* is instant (a ledger read); the world stream is a phase-1 measurement |
| S3 | Point-and-say planning — a spoken intention becomes an editable chip; ambiguity is asked, never guessed | Talk · ≤ 1.5 s per chip | holds (text+click now, voice later) |
| S4 | Magnus's request — chips only, each with a Magnus badge, each an `author: magnus` row | Talk · ≤ 1.5 s per chip | holds (chips) |
| S5 | The plan slate — four intentions, owner, predicted cost, the builder's one-line take, one budget bar, work-order time on its own line, a risk flag on anything irreversible | Workshop · ≤ 30 s, no cancel needed | holds if the cost estimates are measured |
| S6 | The one-line work order — a ≤ 25-word confirm with cost and acceptance check, *or* a question. Never both | Workshop compile ≤ 20 s → Talk confirm ≤ 5 s | holds if the planner latency and "2× load" are defined |
| S7 | The handoff — "Start the night." Builders walk to their districts; they start after the client detaches | Workshop · ≤ 30 s | holds (the walk cycle is procedural, not generated) |
| S8 | The sealed bet — edit → predict → **seal** → preview → critic → keep/revert. Every artefact stamped; every write tagged | Night | holds if the preview, critic and seal definitions hold |
| S9 | The 2 a.m. peek — join cold, understand who did what, rewind free, never fast-forward, read-only, one always-visible stop button | Watch · join ≤ 5 s, card ≤ 5 s, stop ≤ 2 s | holds (the feed is the log, not the stream) |
| S10 | The morning report opens **before the world** — status line, failure line, numbers, filmstrip, branches, parked questions, landed work orders, per-claim-type tallies, model-change notices | Watch · first paint ≤ 3 s, digestible ≤ 2 min | holds if the filmstrip renders are measured |
| S11 | The branch flip and apply — A/B/C pre-rendered by the night, one tap to apply, the world re-streams | Watch flip ≤ 2 s → Workshop apply ≤ 10 s → re-stream ≤ 15 s | holds if pre-renders are in the night's budget |
| S12 | The parked question — or the assumption that replaced it, on the same card in the same place | Talk · ≤ 2 s | holds (both are ledger reads) |
| S13 | "Why?" in one tap — prompt, seed, model id, weights revision, licence + dependency terms, sampler, environment revision, critic note, who decided | Talk · ≤ 1 s to open | **holds** — "the best-supported promise in either report" |
| S14 | The growth beat — a new capability announced in one sentence, in world, at the moment it becomes useful | Talk · ≤ 2 s | holds (ledger + registry) |
| S15 | The ledger line that reaches the artefact — the count attached to the thing, not a dashboard | Talk · ≤ 1 s | holds (a ledger read) |

The shape of the day falls out of the clocks: **the evening (S1–S7) is where every human
decision happens and is nearly free of GPU cost**, which is why the budget bar, the slate
and the confirm line all live there. The night (S8–S9) is machine time and legibility. The
morning (S10–S13) is pure UI over cached artefacts. The loop closes (S14–S15) with the
ledger, which is the only thing that grows `[rev-ux §5]`.

Which three moments must feel great in phase 4: **S9 (peek), S10 (report), S11 (branch
flip)** — `ux-day`'s list — but built with `ux-trust`'s rules inside them (failures first,
tallies with denominators, an always-visible stop button). The two reports were not in
conflict: one is about *moments*, the other about *rules inside moments* `[rev-ux §5]`.

#### Trust and taste

The three trust layers, their questions, and the artefact that answers each: **competence**
— "do they do the work well?" → per-claim-type hit rates with denominators; **legibility** —
"do I understand what happened?" → sealed prediction cards, receipts, the nightly report;
**restraint** — "do they leave me alone, and cost what I expect?" → interruption policy,
budget rails, a kill switch `[ux-trust §The trust stack]`.

A **taste note** carries exactly two things, a verdict and a reason `[ux-trust §Taste note
fields]`: `{id, at, author (casey|magnus), subject {node_id, param_path, value},
artifact_ref, verdict (keep|reject|keep_with_caveat), reason_code, words (≤ 6 words,
optional, skippable)}`. The ledger is **append-only with a single writer** — the owner's
verdict event and nothing else. A builder can read the ledger and cite it; it can never
write to it. The difference matters: *"the Architect knows you like sandstone"* versus
*"the Architect trained itself to think you like sandstone"* — only the first is honest
`[ux-trust §Taste note fields]`.

A **prediction** is written before the render by the builder about to work, and scored
after it by the Critic. Self-scoring is a sycophancy vector and is not permitted `[ux-trust
§Sealed predictions]`. The record carries `builder, at, sealed_at, branch_ref, claim,
claim_type, confidence, seal_hash`. Six `claim_type` values are named — `shadow_count`,
`scale_read`, `clutter_density`, `material_read`, `era_read`, `light_read` — and the core
spec adds a seventh, `weather_read` `[core-spec §0 row 2]`. `claim_type` is the field that
makes the system worth having: *"A single accuracy number per builder is theatre, because a
builder can be excellent at reading scale and hopeless at counting shadows"* `[ux-trust §Sealed
predictions]`. Denominators are never omitted; old misses fade (the display is
recency-weighted); percentages appear only where the denominator can support one — a 3-of-4
line reads as a record, a 75% reads as a grade.

There are **two tallies, stored and displayed separately** `[ux-trust §Two tallies]`:
*prediction about the world* (did the arch shadows read as three bands?) is the competence
record and earns the right to be believed about geometry; *prediction about you* (will you
keep this?) is the taste record and is what actually trains the taste model. They fail
differently: a builder can have an excellent world-record and a poor taste-record, which
means "build well, ask the owner".

Two hard boundaries on taste itself: **taste is about artifacts, never about the owner.**
No builder asks how you are doing, no builder misses you, and there is no moment where a
builder's output is a feeling rather than a made thing `[ux-trust §The taste ledger]`. The
reason is in the source: 72% of US teens have used an AI companion, 50% distrust their
advice, 25% have shared personal secrets with one **[C — `ux-trust`'s cited survey
figures; they motivate the boundary, they are not measurements of this product]** — so a
companion-shaped product can become a confidant-shaped dependency fast
`[ux-trust §The taste ledger]`. The boundary is what keeps this a tool rather than a
relationship.

The five builders have fixed, distinct voices, and each has a "never says" column
`[ux-trust §Five builders and one computer]`: the Architect uses short sentences, counts
and spans, never "great idea"; the Landscaper leads with weather and season; the
Prop-maker speaks in material and hand-scale; the **Critic has no praise at all** — only
`hold`/`fix`/`keep` plus a code and one change; the Companion asks **one question at a
time** and never claims a feeling it cannot source.

#### Magnus

Magnus is Casey's son, and he is a **separate surface, not a smaller version of the adult
one** `[ux-trust §Magnus]` `[rev-ux §A13, C7, C8]`.

- **He taps; he does not speak.** Chips only — no mic, no free text. The privacy property
  is therefore structural rather than promised: *"there is no free text to leak, because
  there is no free text"* `[ux-trust §The privacy boundary, stated honestly]`.
- **He proposes; Casey confirms.** A branch choice is a recipe pointer — a real edit — so
  Magnus's applies become proposals pending an owner confirm `[rev-ux §C8, D4]`.
- **His rows are his.** Separate `author` scopes, forever; his taste never reweights
  Casey's builders and vice versa `[core-spec §0 row 4]` `[rev-ux §A13]`.
- **His lane is reserved and capped.** One item, ending 21:30, scheduled *into* the warm
  batches rather than alongside them `[gaps §3]` `[rev-ux §G10]`.
- **Nothing he does trains anything yet.** His first three keeps are written
  `pending_ratification` and are inert — visible to him, invisible to the builders' gates —
  until the owner confirms he understands what "keep" means `[gaps §3]`.
- **His version of trust is presence-continuity, not a hit rate.** "Your thing is still
  there tomorrow." His morning is one sentence, with no scores, tallies or percentages
  `[gaps §3]` `[ux-trust §Magnus]`.

`gaps §3` designs his first session as a scene (09:02 five chips, 09:04 the chip becomes a
plan item, 09:06 the limit said to a nine-year-old, 09:10 "your thing is still there") with
a hard test: fresh kid profile → ≤ 6 tappables, no reachable text input, tap → card ≤ 1.5 s
**[B — the test's budget, not a measured latency]**.

#### What the experience reports agree on

`rev-ux §1` lists fifteen independent convergences — the strongest single result in the
document set, because two reports written separately reached them. The load-bearing ones:
the prediction is sealed before the render exists and only sealed predictions count;
ambiguity is asked about, never guessed; the computer is a separate authority from the
characters, with no personality of its own; **approval is a measurement, never a currency,
and nobody praises the owner**; the Critic is a separate, adversarial, non-authoring role;
everything runs on a branch and undo is a checkout; budgets are set before the work and the
queue degrades rather than overruns; failures are first-class, visible, and carry an
artefact; provenance is a first-class citizen; the night must survive compression — a terse
log has to read as a story; honest idleness (no fake progress, no fast-forward, no
cheerleading); licences are a checked list, never a footnote.

### 2.2 The engine — Infinigen on the Thor

#### The machine, measured

Everything in this table was read off the box on 2026-10-30 `[split §0]` `[bakeoff §0.1]`.
All **[M]**.

| Property | Value | How it was verified |
|---|---|---|
| Board | NVIDIA Jetson AGX Thor Developer Kit, module P4071-0000 + carrier P3834-0008, SoC `nvidia,tegra264` | `/proc/device-tree/model`, `compatible` |
| OS | L4T R39.2.1 (JetPack 7 line), Ubuntu 24.04, kernel 6.8.12-1021-tegra | `/etc/nv_tegra_release` |
| CPU | 14× ARM Neoverse, one cluster, max 2,601 MHz, min 54 MHz, no SMT | `nproc`, `lscpu` |
| Caches | L1d/L1i 64 KiB/core, L2 1 MiB/core (14 MiB total). **No L3 in sysfs**, though NVIDIA's spec sheet says 16 MB shared | `/sys/devices/system/cpu/cpu0/cache/index*` |
| Memory | 128 GB physical; **125.7 GB visible to tegrastats; 122.8 GiB in `/proc/meminfo`**; unified CPU+GPU; LPDDR5X 256-bit; ~273 GB/s (vendor figure) | `/proc/meminfo`, `tegrastats`, NVIDIA Thor page |
| GPU | "NVIDIA Thor", driver 595.78, **CUDA 13.2**; **compute capability 11.0 (sm_110, Blackwell)**; toolkit at `/usr/local/cuda-13.2`; idle 2 W / 32 °C | `nvidia-smi`; cc 11.0 confirmed by the spike's `nvcc -arch=native` check |
| Power modes | **0 = MAXN, 1 = 120 W, 2 = 90 W, 3 = 70 W**; currently MAXN. Idle draw with desktop ~25–28 W at the VIN rail, GPU rail 0 mW | `nvpmodel -q`, `/etc/nvpmodel.conf`, `tegrastats` |
| Clock locking | `jetson_clocks` available, **not currently locked**; CPU scaling at 78% when sampled | `which jetson_clocks`, `lscpu` |
| Video engines | `/dev/v4l2-nvenc`, `/dev/v4l2-nvdec`; **AV1 encode controls present** alongside H.264/H.265 → NVENC does all three | `ls /dev`, `NvVideoEncoder.h`, `01_video_encode` sample |
| Other engines | PVA v3, 2 ISP channels. **No OFA device node. No camera `/dev/video*` capture nodes — no sensors attached** | `ls /dev` |
| Network | 4× `tegra264-mgbe` MACs exist but **all four are DOWN, no QSFP28 cage populated**; 1× `eqos`; 1× Realtek r8126 (the RJ45 5 GbE port) **DOWN, no cable**. Current link: **Wi-Fi only, 2.4 GHz (ch. 11), WiFi-6 2×2, PHY 229/207 Mbps, RTT 1.6–7.6 ms** | `ip -br link`, device tree compatibles, `ethtool -i`, `iw … link`, `ping` |
| Storage | Internal NVMe, 343 GB free; 1.9 TB USB SSD at `/media/caseydigennaro/TOSHIBA EXT` | `ls`, `df -h` |
| GPU memory reporting | **`nvidia-smi --query-gpu=memory.used,memory.total` returns `[N/A]`**; `utilization.gpu` read 0% while idle (so it is unconfirmed under load); `clocks.gr`, `power.draw`, `temperature.gpu` do work | `bakeoff §0.1` — a real defect in the port's measurement wrapper, work order WO-4 |
| Toolchain | Docker 29.9.2, server arch **aarch64**; Python 3.12.3 system and **3.11.13 built by the port spike**; Node 18.19.1 system plus nvm 22.23.4 and 24.22.2; git 2.43.0 (worktrees OK); `bwrap` present | `docker info`, `python3 --version`, `ls ~/.nvm/versions/node`, `git --version` |
| Model services | **Not running** — nothing listens on 127.0.0.1:8001 or :8005. They were stopped and disabled at boot to give the Thor to this project | `ss -ltn`, `curl /v1/models` → empty `[bakeoff §0.1]` `[CLAUDE]` |

The other seats, **not measurable from the Thor** — these are facts from the brief, so
**[C]**: the **ProArt** is a Ryzen AI 9 HX 370 with a Radeon 890M iGPU, an **RTX 4050
6 GB**, 31 GB RAM, Windows 11 + WSL — it is the human's seat and a thin client with real
muscle. The **cloud** is planner and engineer API calls on a budget. The **Orin** is 8 GB,
idle, spare — and `CLAUDE.md` says "ask before using".

#### What Infinigen does today, and why that is the problem

Infinigen is a **batch** system: one Blender (`bpy`) process per task, with state handed
through `scene.blend` on disk between tasks — `execute_tasks.py:217-221` reopens the blend
for every non-coarse task — and stages `coarse → populate → fine_terrain → render /
ground_truth / mesh_save / export` (`generate_indoors.py:557-566`) `[split §1]`.

Two existing hooks make the caching plan possible and are worth knowing by name
`[split §1]`: the `RandomStageExecutor` already times and counts objects and instances per
stage into `pipeline_coarse.csv` (`core/util/pipeline.py:96-99`), and already makes each
stage **deterministic** via `FixedSeed(int_hash((scene_seed, stage_name)))`
(`pipeline.py:41,84`).

The cost map `[split §1]`:

| Stage | Cost profile | Evidence |
|---|---|---|
| Constraint solving / scene composition | Greedy simulated-annealing over discrete + continuous moves; **pure Python** driving Blender ops; defaults 300/200/50 steps per stage per room assignment (`configs_indoors/base_indoors.gin:4-6`). **Published ≈ 2,281 s (~38 min) for 5k solver steps per scene on the authors' hardware** **[C — the x86 authors' hardware, not the Thor]**; ~100-min budgets scored higher (arXiv:2406.11824, Table 3). *On 2.6 GHz ARM expect worse, not better* | `solve.py:193-197` — the optimiser loop |
| Room solving + solidifying | included above; produces the room meshes the rest decorates | `generate_indoors.py:190-193` |
| Asset generation | Each placeholder realises a factory → node graph → mesh (often boolean-cut against walls); cost scales with object count (~29–50 solved objects/scene before meshes); memory grows monotonically | `populate_state_placeholders` |
| Terrain coarse | SDF kernels; a **CUDA path exists** (mountains, water, landtiles) and a CPU path (already compiled on this box) | `terrain/core.py:141+` |
| Terrain fine | Camera-aware octree SDF mesher (C++), meshes only what cameras see at view-dependent resolution; emits per-tile `glb` + displacement `.npy`. Heavy but **already view-dependent** — the natural LOD/impostor hook | `terrain/core.py:107-135` |
| Scattering / instancing | ~25 generators; placement cost is CPU, instances evaluated at render time | `generate_nature.py:481-617` |
| Materials / node evaluation | Node graphs are cheap to build; evaluation happens inside Cycles. `resample_scene` can re-noise every material/scatter seed in place — the existing partial-variation mechanism | `resample.py` |
| Camera trajectories | Search-based pose finding (`max_tries=50000`), CPU, minutes-class indoors | `base_indoors.gin` |
| Mesh export | `export_scene` **applies all modifiers and realizes instances** — the expensive step — then writes fbx/obj/**usdc/usda**/stl/ply | `export.py:29,55` |
| Rendering | Cycles; device preference **OPTIX > CUDA > CPU** (`core/init.py:29-33`) — on Thor this is **CUDA-only** (no aarch64 OptiX SDK; the spike builds sm_110 kernels). Defaults 1280×720, up to 8192 samples adaptive; indoors disables denoising, and the spike's bpy build has OIDN off anyway | `core/init.py`, `thor/build-bpy.sh` header |
| Ground-truth passes | A **separate C++/GLSL OpenGL rasterizer**, not Cycles; headless on Jetson needs EGL — untested | `datagen/customgt/` |

**What the map says** `[split §1]`: the interactive-killing costs are (1) the ~40–100-minute
Python solver, (2) per-task Blender relaunch plus the `scene.blend` round-trip, (3)
full-scene asset realisation. The GPU is busy only in fine terrain, rendering and the GT
rasteriser. The solver and populate are *why* batch Infinigen can't be interactive, and
*why* the Thor sits idle while the owner waits.

#### What is measured about the port, and what is not

**Measured [M]:**

- `bpy` 4.2.0 has **no Linux aarch64 wheel at any version** (PyPI's latest, 5.2.3, ships
  only macOS/Windows arm64). It must be built from source — this is the whole subject of
  the Infinigen spike `[rev-tech §2.1]`.
- **`nvcc` 13.2.86's default target is sm_75 SASS + compute_75 PTX.** It works only via
  driver PTX JIT; a SASS-only build fails outright with *"no kernel image is available for
  execution on the device"*. This is **certain** to bite every new extension
  (xatlas, torchmcubes, nvdiffrast, PyTorch3D, `custom_rasterizer`, Kaolin, spconv,
  flash-attn) `[rev-tech §6 R1]`.
- **The terrain CUDA kernels are already solved** as a Thor-native rewrite: commit
  `3668454a` switched the build to `-arch=native`, producing **21 CUDA `.so` and 27 CPU
  `.so`** `[rev-tech §2.1]`. This is the precedent for the whole pattern — the rewrite is
  not theoretical.
- A **permanent local fork of Blender** is required regardless, to patch `config.h` launch
  bounds to sm_90/100/110 and set `CYCLES_CUDA_BINARIES_ARCH=sm_110` `[rev-tech §2.1]`.
- Silent CPU fallback is a live hazard: torch 2.6.0's aarch64 wheel contains **no
  `libtorch_cuda.so`** and its `nvidia-*` deps are `platform_machine == "x86_64"`-gated, so
  the failure mode is a 10–50× slowdown that still "succeeds" `[rev-tech §6 R2]`.
- The nightly constraint on a 122 GB box is **not VRAM capacity** — nothing in the adopted
  set needs more than ~10 GB **[C — model-card figures]** — it is **GPU compute-time and
  weight-swap thrash**, plus the
  temptation to serialise CPU work behind the GPU `[res-cad §9]`.

**Not yet measured — placeholders [P]:**

- **Cycles GPU throughput at sm_110.** Nothing is known about how fast the Thor renders.
  This decides whether Thor-side previews can hold the 60 s Workshop clock or whether
  previews must render on the ProArt through the LOD path `[split §7 #1]`.
- **Hello Room / Hello World stage timings on aarch64.** The solver cost above is the
  x86 paper's number; if the Thor is 2–4× slower, room-scoped re-solving goes from "nice"
  to "the only way the Architect ever works during the day" `[split §7 #2]`.
- **Peak RSS per warm scene** — which decides how many worlds and branches stay resident in
  122 GB, and therefore how many pre-baked morning options exist `[split §7 #3]`.
- **Whether bpy 4.2 on aarch64 lands at all.** Every placement in `split §2` assumes it
  does; the alternatives (Blender 4.0.2 from apt plus API shims, or x86 emulation) change
  the plan materially `[split §7 #4]`.
- **EEVEE-headless (EGL) viability** — affects only the live-video variant `[split §7 #5]`.
- **Sustained power draw under GPU load** — decides MAXN vs 120 W for the night window
  `[split §7 #6]`.
- **Every experience latency involving the world or a render.** Neither technology report
  covers Infinigen, Blender, Cycles, the vision critic, the planner LLM or speech, so the
  morning filmstrip, the branch pre-renders, the peek's before/after thumbnails and the
  critic's 9 s have **no technology evidence at all** `[rev-ux §4]`. The 8 s / 12 s / 15 s
  stream numbers in `rev-spec` patch 14 are explicitly measurement-gated: they are
  **[B]** budgets with no measurement behind them yet.

### 2.3 The generators

The single ledger of adopt / spike / skip verdicts, with the reason each was given.
`rev-tech §2–3` is the deduplicated master; `res-3d` and `res-cad` are the underlying
reports; `rev-ux §7` records one ruling that supersedes `res-cad` (see §4).

#### 3D generation

**The verdict: TRELLIS.2, through ComfyUI's native implementation, plus TripoSR as a
licence-clean baseline** `[res-3d §3, §4.1, §8]` `[rev-ux §7]`.

The reason is four reinforcing facts `[res-3d §8]`: it is the only shortlisted model
**simultaneously MIT in code and MIT in weights with no region restriction**; it is the
only one that emits **real PBR maps** (which is what the renderer needs); it is the only
path on the list that **requires no compiled CUDA extension**, removing the entire sm_110
build risk from the critical path; and it **exposes a seed**, so the provenance work starts
on solid ground.

The route matters as much as the model. Microsoft's reference pipeline is MIT-licensed and
genuinely produces PBR meshes, but its dependency chain (flash-attn, nvdiffrast,
nvdiffrec, CuMesh, FlexGEMM, O-Voxel) either has no aarch64 wheels at all or pulls in a
renderer licensed for non-commercial use. **ComfyUI shipped the model natively in version
0.34.0 on 2026-08-31** — the same 4B model re-implemented in plain PyTorch and SciPy,
which removes the build problem and the licence problem in one move `[res-3d §3]`.

**About the numbers in this table.** Licence facts marked *(verified)* were read from the
model's Hugging Face frontmatter and licence files by the reports, not by me — **[M]** in the
sense of *checked against the source of truth*, not measured on the box. The **model sizes
and speeds are all [C]**: vendor or model-card figures for hardware nobody has run them on.
The speed figures that matter most are called out again in §3.2 with their real hardware
attached.

| Model | Licence | Verdict and why |
|---|---|---|
| **TRELLIS.2 (ComfyUI native)** | MIT code, MIT weights, ungated (verified); **DINOv3 encoder terms travel with it** | **Spike first.** Real PBR, no compiled CUDA extension, seeded `[res-3d §4.1]` `[rev-tech §3]` |
| **TripoSR** | MIT code and weights, ungated (verified `stabilityai/TripoSR`) | **Adopt in parallel** as the cheap licence-clean baseline and a plumbing exercise; MIT, ~8 GB **[C]**, mesh-only, first-class seed `[rev-tech §3, §5]` |
| TripoSG (modly's path) | MIT, ungated (verified `VAST-AI/TripoSG`) | Folded into the modly spike; strictly better than TripoSR for the same role `[rev-tech §5]` |
| Pixal3D | MIT code and weights, but **`extra_gated_eu_disallowed: true`** (verified) | Evaluate *inside* spike 2's ComfyUI environment — one extra weights download, not a separate spike; record the distribution constraint per asset `[rev-tech §3, §5]` |
| 3DTopia-XL | Apache-2.0 code and weights (verified) | **Later.** The only shortlisted model taking text as a first-class input and emitting a PBR GLB in one pass, exposing a `seed` and `export_glb`, claiming ~5 s per asset **[C]** — but its `triton==2.1.0` pin conflicts with CUDA 13 and it needs nvdiffrast + PyMCubes + libigl `[res-3d §4.6]` |
| Hunyuan3D 2.x | Tencent Hunyuan 3D Community; **`extra_gated_eu_disallowed: true`**, >1M MAU trigger | **Skip for shipped assets.** Memory is fine (10/21/29 GB **[C]**) but the stack is not: no cp312 wheels for numpy 1.24.4 or onnxruntime 1.16.3, no aarch64 wheel for pymeshlab, an in-tree custom CUDA rasteriser. The strongest variant (2.5, LATTICE) has **no released weights at all** `[res-3d §1, §4.4]` `[rev-tech §3]` |
| SF3D / SPAR3D | Stability AI Community Licence; `other`, gated `auto` (verified) | **Spike second.** Two source builds (pynanoinstantmeshes, gpytoolbox) plus a registration with lead time. **Start the registration now** — it costs no engineering time and gates a later option `[res-3d §4.5]` `[rev-tech §5]` |
| TRELLIS v1 | MIT code and weights | **Avoid.** Not viable as written: kaolin, spconv-cu120, xformers and flash-attn have no Linux aarch64 wheels, on top of a torch 2.4.0/cu118 pin. Its Gaussian-splat output also has no consumer in a Blender/Cycles scene graph `[res-3d §4.7]` |
| InstantMesh | Apache-2.0 code and weights | **Avoid.** Needs nvdiffrast, PyMCubes (no aarch64), bitsandbytes with unverified sm_110 coverage, diffusers 0.20.2 `[res-3d §4.7]` |
| Material Anything | MIT code, Apache-2.0 estimator weights | **Spike later.** The stronger tool when the mesh already exists (albedo, roughness, metallic, bump at 1024²), but PyTorch3D has no aarch64 wheel `[res-3d §4.8]` |
| Nova3D / nova3d-mcp | MIT code (archived 2026-06-28), hosted service, **output terms not published** | **Skip; steal the interface pattern** `[rev-tech §3]` |

**Textures.** Spike first on **StableMaterials + SDXL**: OpenRAIL weights (commercial-OK
with use restrictions), tileable SVBRDF in ~4 steps **[C]**. The nicer alternative,
MatForger, is
gated `[res-cad §TL;DR, §3]`. Note that TRELLIS.2's shape-conditioned texturing covers the
texture role in the same environment, which is what makes "textures deferred past the
spike" obsolete `[rev-ux §7]`.

**Character motion.** **Spike MoMask first** — MIT code, fastest of the family, seeded,
best published FID of the three. But the **weights are fine and the data is not**:
HumanML3D ← AMASS carries research-use restrictions that flow into shipped clips. This is
*"the one genuinely unresolved corner"* `[res-cad §TL;DR, §4]` `[rev-tech §3]`. MDM is
skipped (MoMask covers it, and it is slower with the same data problem); MotionGPT is
skipped (its flan-t5 stack adds weight for no text-to-motion gain, and its weights licence
reads only "cc"). SMPL/SMPL-X are research-only, so `smplx` and the whole PyTorch3D
rendering path are avoided.

**Audio.** **Adopt ACE-Step** — Apache-2.0 in code *and* weights, ~8 GB VRAM class
**[C]**,
diffusion + Sana DCAE + linear transformer, up to 4 minutes of music in ~20 s on an A100
**[C — that timing is an A100 number; the Thor number will be far worse, and measuring it
is the point of the spike]** `[res-cad §5]`. **Spike Stable Audio Open**: MIT code, Stability
Community weights, free incl. commercial under $1M annual revenue. The **Small** variant
(341M, with Arm, 2025-05) is SFX-focused and marketed as running on Arm CPUs — i.e. it can
occupy the Thor's CPU lane without touching the GPU `[res-cad §5]`. **Skip MusicGen/AudioCraft
for shipped assets**: the weights are **CC-BY-NC 4.0**, exactly the non-commercial flag the
vision warned about; the PyPI sdist also pins `torch==2.1.0` and `xformers<0.0.23`, dead on
CUDA 13. CHORD is skipped (research-only copyleft).

**CAD.** **build123d primary, CadQuery secondary** `[res-cad §TL;DR, §1]` `[core-spec §0
row 1]`. build123d has a typed algebraic API made for agents, Apache-2.0, explicit aarch64
support with verified wheels, and exports STEP + GLB with materials. CadQuery shares the
same OCCT base and the same wheels and has more LLM training data, but its string-selector
API is validation-hostile — which is a real cost when an agent writes the code. A
build123d part also costs **zero GPU memory** `[rev-tech §5]`. CAD is a CPU lane citizen
because it is *code*, not a mesh: deterministic, parametric, recipe-native.

**Scene format.** **OpenUSD (`usd-core` 26.11) adopted** — Pixar ships aarch64 wheels
(27 MB, verified by download), TOST-1.0 is Apache-class, layers are authored from Python
`[res-cad §TL;DR, §6]`. **SimReady adopted as a schema**, not as an asset library
(Apache-2.0) `[res-cad §TL;DR, §6]`. And the rule that settles the format question:
**the recipe is the source of truth; USD is a compiled, one-way output** — adopted
verbatim into the core spec `[res-cad §8]` `[core-spec §0 row 11]`. There is no USD→recipe
round-trip except asset import `[core-spec §0]`.

#### The model scheduler

Memory tiers, as the vision sets them `[res-cad §9]`:

- **Hot (always resident):** the Companion/planner LLM and the Critic. Small,
  latency-sensitive, used between every batch.
- **Warm (loaded once per night-segment, then drained):** one generative model at a time —
  image-to-3D, then the texture stack, then motion, then music. *"Batching by model is the
  whole game: hundreds of prompts through one loaded model, not one load per prompt."*
- **Cold:** everything else, on disk, with pinned weights revisions.

Lane layout for a night `[res-cad §9]`: plan → task queue; the **CPU lane runs
continuously** (build123d parts, audio SFX, mesh cleanup, USD assembly — these never wait on
the GPU); the **GPU lane ordered to feed dependencies** (image-to-3D props → texture batches
→ motion clips → music/ambience), with **critic checks interleaved after each batch** and
failed candidates regenerating within budget or parking for the morning; then assembly —
recipe entries updated, USD layers re-emitted, morning report with keep/revert branches.

**Provenance is the scheduler's job, not the job's**: it stamps every artefact with
`(prompt, model id, weights repo+revision, seed, library versions, wall-time, licence)`,
which is also what makes a night replayable and swappable when a better Thor-native model
lands `[res-cad §9]`.

### 2.4 Compute placement — the Thor, ProArt, cloud and Orin, and the wire

`split` answers the question the vision poses: how do we shift the processing burden
across the Thor, the ProArt, the cloud and the Orin?

#### The wire between the Thor and the ProArt

`split §3` recommends a **hybrid**: *state by day, encoded pixels on demand*. The mechanism
is **Ghost/LOD export** — walk the `placeholders` collection, room solids and scatter
densities into baked-LOD glTF and stream **deltas**, so the Thor's GPU stays free for
models and previews while the ProArt renders the day view on its own 4050 `[split §6 move
3]`. The claim is quantitative and modest: **edits are ≈ KB over the wire**, against a
10–100 MB initial LOD scene **[C — `split`'s estimate; the byte counts are not measured
yet]** `[rev-spec §1.2.3]`.

The physical link is a problem worth naming plainly `[split §0, §6 move 4]`: the box is on
**2.4 GHz Wi-Fi** **[M]** because the 5 GbE RJ45 port has no cable and the 4× 25 GbE
QSFP28 cage is not populated **[M]**. One cable fixes it. The loads do not need it — state
is ≈ KB/s and 1080p60 H.265 is ≈ ≤30 Mbps **[C — `split`'s figures]** — but every
video-class moment (the peek's clips, the morning filmstrip at 60 fps) currently competes
with Wi-Fi. NVENC on the Thor can encode H.264/HEVC/AV1 **[M]** and the ProArt's 4050
hardware-decodes all of it, so the filmstrip is practical once the wire is a wire
`[split §4 row 8]`.

**The state stream, the choice and the recommendation** `[split §3]`: the recommendation is
the hybrid above, weighted heavily toward state-by-day, because the ProArt's 4050 renders
previews faster than the Thor's mid-range rasteriser and because a live video variant would
need an EGL/headless renderer nobody has verified `[split §7 #5]`.

#### The power plan

`split §5` maps the day/night idea onto the box's **real** modes — and this is one of the
few places where the "day/night" framing turns out to be literally true of the hardware:

- **Day (interactive): mode 2 (90 W)** **[M — the mode's wattage is in
  `/etc/nvpmodel.conf`]**, DVFS left alone — the day is latency-sensitive but light.
- **Night (unthrottled): mode 0 (MAXN) + `jetson_clocks`** (locked clocks, max fan).
- **Morning burst:** stay MAXN until the human detaches, because branch flips are
  USD/recipe pointer moves rather than renders.

The rule carried over from last-mile applies: *"measure with the box's load beside the
number"* — and `split §5` wants the core service to **own the nvpmodel switches** as part
of the night queue's begin/end, and to **log the mode beside every timing** `[rev-spec
patch 16]`. The core spec never mentions power mode at all today `[rev-spec §2.5]`.

#### The five burden-shifting moves, ranked

From `split §6`, ranked by user-felt benefit per unit of effort. Each has a stated
measurement, which is what makes them plans rather than wishes. Every figure in the last
column is **[B]** — a target or a measurement to be taken, not a result — except the
~40 min and ~1-per-task figures, which are **[C]** (an x86 paper number and today's
behaviour).

| # | Move | Benefit | Measure that settles it |
|---|---|---|---|
| 1 | **Warm resident scene server** — kill the per-task Blender relaunch and the `scene.blend` round-trip; keep the solved scene open in a service the builders call into | *"the difference between the workshop clock and batch latency"*; the day UX becomes possible at all | p50/p95 edit→preview latency, batch-vs-warm on the same recipe edit; Blender process starts per night (target 1–2, vs ~1 per task today **[C]**) |
| 2 | **Recipe-hash stage cache + partial regeneration** — key on `hash(recipe, gin, stage, dep-keys)`; re-solve only the touched room; re-realise only the touched placeholders | Night throughput multiplies; morning branch flips become ≤ 2 s pointers; "change one room" costs minutes, not ~40 min **[C — the x86 paper's full-solve figure]** | Wall time of "edit one room" end-to-end vs full regeneration; stage-cache hit rate per night |
| 3 | **Ghost/LOD glTF export for the day view** (the ProArt renders) | The whole day half of the experience with the Thor's GPU left for models and previews | Export time and bytes per scene; ProArt fps and VRAM on the 4050; initial world-load ≤ 8 s warm |
| 4 | **Plug the 5 GbE RJ45 + stand up the NVENC clip channel** | Every video-class moment stops competing with Wi-Fi; zero risk to the core loop | `iperf` TCP Thor↔ProArt; glass-to-glass latency and dropped frames over a 10-min 1080p60 playback |
| 5 | **Night scheduler lanes** — GPU batched by model, CPU lane always busy, Orin as overflow and watchtower | Roughly doubles usable night GPU-hours for free (**[C — `split`'s estimate]**), because **weight-swap thrash is the real constraint**; CPU work never queues behind GPU work | Model-load count per night (target: 1 per model); GPU-hours consumed vs the budget bar; CPU-lane utilisation; the morning's "5.3 of 5.5 GPU-h" line becoming trustworthy |

Honourable mention, named as #2's prerequisite: **the recipe compiling deterministically to
USD layers** — `res-cad §8` already argued it and nothing contradicts it `[split §6]`.

#### What `split` says depends on the spike

`split §7` ranks its own dependencies by how much they move: (1) Cycles-CUDA throughput at
sm_110; (2) Hello Room / Hello World stage timings on aarch64; (3) peak RSS per warm scene;
(4) bpy 4.2 on aarch64 at all; (5) EEVEE-headless viability; (6) sustained power draw under
GPU load. **All six are placeholders [P] today** — see §2.2.

#### Casey's idea dump, triaged

`ideas` is a search result, not a report, and `split §4` triages all 17 ideas as
*practical now / practical later / speculative / wrong (with the killing fact)*. The
pattern the triage finds `[split §4]`: *"The file's architecture instincts (thin client,
day/night split, night bake, recipe-not-meshes over the wire) are sound and match the
vision. The hardware storytelling (OFA deformer, camera injection ports, 4×25 GbE as a
plug-in port, 2,070 TFLOPS sizing) is automotive-marketing material that mostly dies on
contact with this devkit — every surviving piece of it is cheaper as ordinary software."*

The wrong ones, with their killing facts. The *killing facts* are all **[M]** — read off the
box; the *vendor figures they kill* are **[C]**, NVIDIA's published numbers:

- **#5 OFA as a real-time mesh deformer** — **no OFA device node exists** on this box; Jetson
  optical-flow paths run through the GPU/ISP stack, not a free-standing fixed-function unit.
  The *kernel* is kept: camera/hand input as a sculpt brush is a fine software feature, it
  just costs ordinary GPU/CPU `[split §4 row 5]`.
- **#6 Camera lanes as injection ports** ("20 feeds", "10× 4K60 decode without touching the
  GPU") — **no cameras and no `/dev/video*` capture nodes** exist; the "20 camera" figure is
  Thor's automotive *configurations* **[C]**, not this devkit. The kernel is kept: "put a mug
  on the desk → it appears in the world", served by one ordinary USB webcam `[split §4 row 6]`.
- **#7 4× 25 GbE** — the silicon is real (4 `tegra264-mgbe` MACs in the device tree, one
  QSFP28 cage) but **nothing is populated**, the ProArt has no such port, and the box is
  on 2.4 GHz Wi-Fi `[split §4 row 7]`.
- **#16 OptiX on Thor** — **wrong**: no aarch64 OptiX SDK; the spike builds Cycles
  **CUDA-only** at sm_110 `[split §4 row 16]`.
- **#10 "2,070 TFLOPS FP4"** **[C — NVIDIA's sparse-FP4 NN *inference* figure]** —
  **misleading for this workload**: while Cycles and the procedural pipeline are FP32/FP16.
  *"The Thor GPU is a capable but mid rasterizer next to a 4050-class dGPU. Size renders by
  the spike's measured tiles/s, never by this number"* `[split §4 row 10]`.
- **#12 "16 MB shared L3, server-class Neoverse single-thread"** — **half-true**: 16 MB L3
  **[C — NVIDIA's spec sheet]** is in NVIDIA's spec but not in sysfs **[M]**, and 2.6 GHz ARM
  single-thread ≠ desktop x86, so the Python solver will run *slower* than the paper's x86
  timings. *"Do not size day-clock solver work on 'server-class'"* `[split §4 row 12]`.

The best-formed idea is **#17, "cloud dreams, ProArt edits light structures, Thor compiles
at night"** — which matches the vision's three layers and the placement table almost
exactly `[split §4 row 17]`.

### 2.5 The core — the spec's model

The core is deliberately small: a durable service on the Thor owning work orders, budgets
and approvals, the recipe store and history, the model scheduler, the vocabulary and the
audit log. Plain Python first; *"adopt LangGraph only if its checkpointing beats ours"*
`[vision §The architecture]` `[core-spec §0 row 7]`.

**The store of record** `[core-spec §1.0]`: one **SQLite database in WAL mode**,
`synchronous=FULL`, written by a **single writer process** (the core). The `audit` table is
the source of truth; every other table is a **projection rebuilt by folding `audit`**.
Recipe version documents and artefacts are **content-addressed blobs** on disk referenced
by hash from the DB, so the DB stays small ("a night is kilobytes of decisions") and blobs
are verified by hash on read. Content hashes are **sha256 over canonical JSON** (sorted
keys, no whitespace, UTF-8).

Layout under `$BUILDER_HOME` (default `~/builder-ide`) `[core-spec §1.0]`:

```
core.db                 # SQLite WAL: audit + projections
artifacts/ab/ab1234…    # content-addressed, write-once (renders, GLBs, reports)
recipes/ver_0192.json   # canonical recipe document per version (mirrors a blob)
sandboxes/wo-14/3/      # engineer worktrees + seats, deletable
usd-cache/              # compiled USD layers per (recipe version, profile)
reports/                # prebuilt static morning reports
```

IDs are prefixed short strings: `rcp_` recipe, `ver_` version, `br_` branch, `ed_` edit,
`wo_` work order, `pkt_` context packet, `ast_` asset, `pr_` prediction, `tn_` taste note,
`aud_` audit event, `night_`, `task_`, `job_`, `att_` attempt, `q_` parked question.
Vocabulary entries have no prefix — the word itself (`bridge.rope`) is the key
`[core-spec §1.0]`.

**The vocabulary** is the closed, typed language the builders speak. Each entry has a
parameter schema and constraint checks with kinds `keep_clear | load_floor | reachability |
budget_custom` `[core-spec §1.1, §2.3.4]`. The spec's smallest slice names three words and
one character, the Prop-maker `[core-spec §6.1]`.

**The eleven decisions already made** `[core-spec §0]`:

| # | Question | Choice |
|---|---|---|
| 1 | CAD authoring API | **build123d primary**, CadQuery as readable secondary / few-shot corpus |
| 2 | Prediction `claim_type` set | `ux-trust`'s six types **plus `weather_read`** |
| 3 | Nightly money rail | Rails denominated in **(GPU-minutes, hosted-cents, wall-minutes)**, with defaults and a degradation order |
| 4 | Does Magnus's taste count toward Casey's | **No.** Separate `author` scopes, forever |
| 5 | Architect/Critic deadlock | **Critic wins on `hold`**; the owner breaks a true deadlock |
| 6 | Does the taste ledger leave the machine | **No.** Model calls get scoped slices; Magnus's rows never in a slice |
| 7 | Orchestration framework | **None.** The audit log *is* the checkpoint |
| 8 | Interactive previews vs batch-by-model | **Hot tier reserved for interactive**; day previews may preempt warm loads; the night batches strictly by model |
| 9 | Recipe storage | **SQLite event-sourced store of record** + content-addressed blobs; git only for the engine repo |
| 10 | Raw utterances retained? | **The confirm line is the record**; the raw utterance is kept for the owner only and purged at terminal state; Magnus has no free text |
| 11 | Recipe vs USD | **Recipe is the source of truth; USD is a compiled, one-way output** |

Non-goals, stated honestly `[core-spec §0]`: no multi-tenant or hosted deployment; no
CRDTs (agents edit a recipe, not a shared document); no USD→recipe round-trip except asset
import; voice input is **[later]** — every voice path in the spec has a text+click
equivalent that ships first.

**The engineer adapter** `[core-spec §2]` is one interface — in: a work order and a sandbox
branch; out: a commit and test evidence — with ACP and MCP both mapped onto it, and a
registry of engineer seats. The **merge gate** `[core-spec §2.3]` is where evidence is
checked: a deterministic rebuild, unit tests, a render, the critic's verdict. A permanent
local fork of Blender, and the `usd-cache/` layout, sit under it.

**Durability** `[core-spec §5]` rests on the audit-as-checkpoint design, and §5.4 makes the
**kill -9 test** the acceptance criterion for the whole section. §5.6 enforces interruption
and line budgets **in the core, not in the prompt**.

**The build order** `[core-spec §6]`: §6.1 is the smallest end-to-end slice — "one crate
night" — with a SQLite ledger + audit events + projections, FastAPI, a recipe store, one
character (the Prop-maker), three vocabulary words, one work order, one engineer
(`aider-local`), a minimal merge gate, and a night runner with per-task and per-night
rails. §6.2 lists what follows, in order.

**The context packet** is how a few spoken words become a full work order `[vision §Calling
the computer in-game]`: the core attaches it to every call, carrying what "this/these/here"
means (selection, camera ray, objects under it, where you stand), recent history (recipe
changes, **renders** and critic notes, including who changed what), the conversation as
bounded labels, and the project state (branch, open work orders, budget left, vocabulary
and its gaps). From that the computer **compiles** a full work order — goal, objects named
by id, acceptance check, budget — and **confirms it in one line** before it starts.
*"Ambiguity is resolved by asking, never by guessing."*

### 2.6 The engineers — what the bake-off found

`bakeoff` is a designed experiment, not a bake-off that has happened: **no contender was
run** `[bakeoff §7]`. Every "runs headless as X" statement comes from vendor docs or from
reading the seats' installed source. The house rule was explicit: don't run them.

**Six work orders**, deliberately mixed so that a contender that only wins the light orders
is not ready for the hard ones `[bakeoff §2.1]`. The acceptance-check costs are **[C]** —
`bakeoff`'s own estimates of how long each check takes to run, not measurements:

| # | Order | Weight | Acceptance-check cost | Depends on |
|---|---|---|---|---|
| WO-1 | Reproducible bpy build + `thor/SPIKE.md` | H | < 60 s (network to raw.githubusercontent.com) | — |
| WO-2 | build123d rope-bridge generator, deterministic STEP | H | ~3–6 min (pip install + OCCT import) | build123d 0.13.0 wheels (verified aarch64) |
| WO-3 | Vocabulary slice + 3 words + tests | M | ~1 min (pydantic only) | — (core spec not yet written) |
| WO-4 | Honest GPU-state measurement in `run-timed.sh` | L | seconds | — |
| WO-5 | Texture batch with provenance | M | ~2 min (stub generator) | — |
| WO-6 | Model scheduler's batch planner (the brief's "scheduler bug") | M | ~1 min (pure Python + Hypothesis) | the core spec (`spec-core`) |

WO-4 was added in place of the brief's fifth example, because *"a scheduler bug" has no
code to bite on today* — the model scheduler is one paragraph of the vision and
`builder-ide` has no source yet. WO-4 is instead a **verified live defect**: the
`nvidia-smi` memory query returns `[N/A]`, so `run-timed.sh` records `maxGPUmem=0MiB` on
every run — a false zero `[bakeoff §0.1, §2.1]`.

**The recommended first lineup** `[bakeoff §4.1]`:

| Seat | Contender | Orders | Why |
|---|---|---|---|
| **A — chief engineer** | **Claude Code** | WO-1, WO-2 (hard), WO-6, anything that must land | Best headless contract in the field (`-p` + `--max-turns` + `--max-budget-usd` + stream-json) and the only contender with a real OS-enforced sandbox (bwrap + network isolation). Its weakness is cost, not capability — and cost is exactly what the bake-off measures |
| **B — Thor-local bulk** | **aider + local Qwen3-Coder-30B**, with **pi** as the second local seat | WO-3, WO-4, WO-5, one-file fixes; WO-6 as a second opinion | Free marginal cost, pure-Python wheel (arm64-safe), the best local-endpoint story. Run **both** — the cheapest experiment in the set |
| **C — bulk cloud** | **zcode** (Z.ai plan), with **mcode** as the hedge | bulk while A works; anything not needing a sandbox | Already proven on this box; Apache-2.0 first-party. But it is **quota-shaped, not token-shaped** (429s are its failure mode), so it stays off the critical path. mcode adds vendor diversity |
| **D — isolated** | **OpenHands** (per-conversation Docker sandbox) | risky/large orders; the first overnight-loop rehearsal | The only contender with genuine container isolation, which is what the core's "sandbox branch" actually wants; LiteLLM means any model, local included; its Agent Canvas can host ACP agents |
| **Front end, not a backend** | **Goose (ACP build)**, OpenCode, Codex | — | Goose already ships aarch64 builds and the vision wants Zed/Theia talking to the engineer over ACP. **Measure them, but do not put them on the first lineup** — except OpenCode, which should race Claude Code on WO-1 and WO-2 in round 1 |

**The harness** `[bakeoff §3]`: one sandbox per (contender, order) — `git worktree add
--detach` from the same pinned commit, so every contender sees byte-identical input; a
purpose-built image `bakeoff/sandbox:aarch64` **built from the Thor's own toolchain**;
isolated `HOME` per run so seats' configs never leak; a network allow-list. Scoring is
**gate first, then rank**: an order is accepted only if its acceptance check passes, and
**auto-failed** if the diff touches the check file, harness or fixtures. Within an accepted
order: evidence quality (1.0), **blinded human-fix minutes** (1.0 — a reviewer who does not
know which contender produced the diff is timed while making the check pass), cost (0.7),
time (0.5), scope discipline (0.5). Report **medians and spread of N≥3 runs** for the cheap
orders and N=1 for the expensive ones — *"single-sample agent comparisons are noise"*.

**The budget discipline is the finding** `[bakeoff §3.2]`: a money ceiling **per night, not
per order**; and the local lane is **not free in the way it looks** — the Thor idles around
31.7 W instantaneous **[M — `tegrastats` on the idle box]**, but a 30B model at bf16 is
~60 GB of weights before any KV cache **[C — arithmetic, explicitly not a measurement]**,
and that is memory the Infinigen/Cycles work also wants. *"Price it as GPU residency, not
as 'free', and schedule the local lane away from render windows."*

**What the bake-off is not allowed to change** `[bakeoff §4.3]`: the recipe principle, the
merge gate and the evidence rule are fixed by house style, not by this experiment. A
contender that passes an order by breaking one of those is **a failed run, not a fast one**.

### 2.7 Licences and dependencies — the single ledgers

`rev-tech §2` and `§3` are the deduplicated masters, one row per library and one per
component, gathered from both technology reports plus the Infinigen spike.

#### The dependency ledger

Columns: **aarch64** = is there a Linux aarch64 wheel on PyPI; **CUDA 13** = does it work
against this box's CUDA 13.2.86 driver / 13.2 toolkit; **sm_110** = do the kernels
actually target compute 11.0 `[rev-tech §2]`.

**The runtime and the world engine** `[rev-tech §2.1]`:

| Dependency | aarch64 | CUDA 13 | sm_110 | Verdict |
|---|---|---|---|---|
| `torch` **2.15.0** (PyPI, cp312) | ✅ 483.7 MB | ✅ `cuda-toolkit==13.2.2` | ✅ **535 sm_110 images** | **the base of the whole generative stack** |
| `torch` **2.6.0** (PyPI) | ✅ but **no CUDA lib** | 🧱 CPU-only (deps x86_64-gated) | n/a | 🧱 do not use |
| `torch` 2.9–2.11 (NVIDIA SBSA cu130/cu132) | ✅ | ✅ | ✅ | ⚙️ fallback only |
| `triton` 3.9.0 | ✅ cp311–cp315 | ✅ (the cu13 line) | ✅ via torch | ✅ — but 3DTopia-XL's `triton==2.1.0` pin conflicts with CUDA 13 |
| `numpy` 2.5.4 | ✅ | ➖ | ➖ | ✅ — but Infinigen caps `numpy>=1.25,<2`, so it needs **numpy 1.x**, a separate env |
| `scipy` 1.18.1 | ✅ | ➖ | ➖ | ✅ for 3.12; scipy ≥1.18 requires ≥3.12 |
| `procfunc` 0.37.0 | ✅ pure | ➖ | ➖ | ⚙️ **`requires-python >=3.11,<3.12`** → forces the 3.11 env |
| `landlab` 2.11.0 | ✅ | ➖ | ➖ | ✅ (Infinigen pins 2.6.0) |
| **`bpy` 4.2.0** | 🧱 **no Linux aarch64 wheel at any version** | ⚙️ source build | ⚙️ needs the local `config.h` patch | 🧱 **must be built from source** — the Infinigen spike's whole subject |
| Blender 4.2 Cycles CUDA arch | ➖ | ⚙️ | ⚙️ `CYCLES_CUDA_BINARIES_ARCH=sm_110` + `config.h` patch | ⚙️ **permanent local fork of Blender** |
| Infinigen terrain CUDA kernels | ➖ | ⚙️ | ⚙️ **already solved**: `3668454a` → `-arch=native`; 21 CUDA `.so` + 27 CPU `.so` compiled | ⚙️ the rule now applies to every other extension |
| `cpython` 3.11.13 | ⚙️ built from source on the box (`--enable-shared`, rpath) | ➖ | ➖ | ⚙️ done by the spike |

**3D generation** `[rev-tech §2.2]`: `transformers` 5.22.1, `diffusers` 0.42.1 and the
diffusers family are ✅ everywhere. `xatlas` 🧱 no aarch64 → C++ build. `torchmcubes` /
`PyMCubes` 🧱 → small CUDA build with `-arch=native`. `onnxruntime` ✅ but see R6 (native
abort on Tegra CPU). `rembg` ✅ (the crash risk is in the ONNX runtime, not the wheel).
`open3d` 0.20.0 ✅ — *"res-3d's 'open3d 0.18 has no cp312' is now stale"*. `flash-attn`
🧱 **sdist only, 0 wheels**, prebuilt binaries lack sm_110 SASS → **avoid entirely**.
`xformers` 🧱. `spconv-cu120` / `kaolin` 🧱. `nvdiffrast` ⚙️ (git only) and NVIDIA Source
Code Licence, 1-Way Commercial. `nvdiffrec` 🧱 **non-commercial → never in a shipped
path**. `pytorch3d` ⚙️ avoidable. `cupy-cuda13x` 14.2.0 ✅ — *"resolves res-3d's 'CUDA 12
runtime on a 13 driver' worry"*. `smplx` / `chumpy` ⚙️ rendering-only → avoid.

**Textures, audio, CAD, USD** `[rev-tech §2.3]`: `librosa` / `soundfile` ✅; `cadquery-ocp`
8.0.1.1.0 ✅ (`manylinux_2_28_aarch64`, 59 MB, downloaded); `cadquery` 2.8.0 and
`build123d` 0.13.0 ✅ pure wheels; `usd-core` 26.11 ✅ (27 MB, downloaded, TOST-1.0);
`simready-foundation` ✅ as a schema.

**The ledger's summary** `[rev-tech §2.4]`: *"Nothing in the adopted/spiked set is blocked
outright."* The only hard blocks — `flash-attn`, `xformers`, `spconv-cu120`, `kaolin`,
`nvdiffrec` and `bpy` (no wheel) — all belong to paths the reports already reject, **except
`bpy`, which is unavoidable and is exactly what the Infinigen spike is solving.**

#### The environment plan

`rev-tech §4.1` rules out both obvious answers and lands on **four environments plus one
optional**, because the real dividing lines are interpreter version, native ABI, and
process isolation for crash-prone native code:

| # | Environment | Python | Contents | GPU? | Why it is separate |
|---|---|---|---|---|---|
| **E1** | world engine | **3.11** | locally built `bpy` 4.2 wheel, Infinigen editable + terrain CUDA `.so`, `landlab`, `procfunc` | ✅ Cycles CUDA sm_110 | bpy 4.2 embeds exactly Python 3.11; `procfunc` is `<3.12`; `numpy<2`; a different ABI. **Nothing else may enter this env.** |
| **E2** | generative / torch | 3.12 | `torch` 2.15.0 aarch64 CUDA 13.2, `diffusers`, `transformers`, ComfyUI (TRELLIS.2 + Pixal3D), MoMask, ACE-Step, stable-audio-tools | ✅ sm_110 | one torch ABI for every generative model |
| **E3** | prop service | 3.12 | modly FastAPI backend + TripoSG / Trellis2-GGUF, `rembg`, `onnxruntime`, `trimesh`, `pymeshlab` | ✅ | **isolated because `rembg`/ONNX Runtime aborts natively on Tegra CPU** — a native crash in a shared env takes the scheduler with it |
| **E4** | CAD + USD (pure CPU) | 3.12 | `build123d`, `CadQuery`, `cadquery-ocp`, `usd-core`, `py-lib3mf`, `ezdxf`, `nlopt`, `casadi` | ➖ **no torch, no CUDA context** | keeps the deterministic CAD lane out of the torch ABI, so a CAD batch costs **zero GPU memory** and cannot perturb the generative lane's residency. Carries Stable Audio Open **Small** (Arm-CPU) as its audio-SFX occupant |
| E5 *(optional)* | CPU audio variant | 3.12 | `stable-audio-tools` + `torchaudio` | ➖ | only if SAOS Small's 44.1 kHz decode interferes with the CAD lane's latency |

And the rule that generalises: **"Environments are the compatibility unit; residency is the
process unit."** One venv can serve several models, but the scheduler must run each model
in **its own process**, so that "evict" means "exit the process" and the CUDA context and
its memory are genuinely returned `[rev-tech §4.1]`.

#### The licence register

Scope: what each permits **for shipped assets** — commercial, research-only, attribution
`[rev-tech §3]`.

| Component | Code | Weights | Commercial? | Status |
|---|---|---|---|---|
| **Infinigen** | BSD-3-Clause | n/a | ✅ | ✅ clean — but code in `src/infinigen/infinigen_gpl` is GPL: **don't link it** |
| **Blender 4.2 (bpy)** | GPL-2.0-or-later | n/a | ✅ as a separate process | ⚠️ **the process boundary is mandatory** |
| `usd-core` / OpenUSD | TOST-1.0 | n/a | ✅ | ✅ |
| `cadquery`, `build123d` | Apache-2.0 | n/a | ✅ | ✅ |
| `cadquery-ocp` / OCCT | Apache-2.0 wheels; OCCT LGPL-2.1-with-exception | n/a | ✅ | ✅ |
| **ComfyUI** | GPL-3.0 | n/a | ⚠️ only as a **separate service** | ⚠️ **host it as a service** — another reason for the ComfyUI/modly split |
| **TRELLIS.2 (ComfyUI native)** | MIT | MIT, ungated (verified) | ✅ | ✅ **cleanest PBR path** — DINOv3 encoder terms travel with it |
| DINOv3 encoder | Meta | `other`, gated `manual` | ✅ with **end-use** limits | ✅ non-commercial is *not* the issue here — end-use is |
| Pixal3D | MIT | MIT, `extra_gated_eu_disallowed: true` | ✅ outside the EU | ⚠️ record per asset |
| TripoSR / TripoSG | MIT | MIT, ungated (verified) | ✅ | ✅ |
| **Aero-Ex/Trellis2-GGUF** (modly's TRELLIS.2 path) | — | **none declared on the HF card** | ⚠️ **unknown** | 🧱 **pin the MIT terms in writing before use** |
| 3DTopia-XL | Apache-2.0 | Apache-2.0 | ✅ | ✅ (Objaverse-derived corpus provenance) |
| SF3D / SPAR3D | Stability Community | `other`, gated `auto` | ⚠️ **registration required**; >US$1M revenue needs enterprise | ⚠️ **register early (lead time)**; outputs remain ours |
| Material Anything | MIT | Apache-2.0 | ✅ | ✅ (blocked on PyTorch3D) |
| Hunyuan3D 2.1 / 2-mini / Paint | Tencent Hunyuan 3D Community | `other`, `extra_gated_eu_disallowed: true` | ⚠️ **not applicable in EU/UK/South Korea**; >1M MAU needs a separate licence | ⚠️ legal review; keep internal-only |
| `nvdiffrast` | NVIDIA Source Code Licence, **1-Way Commercial** | n/a | ✅ | ⚙️ build-time only |
| `nvdiffrec` | NVIDIA, *"only may be used or intended for use non-commercially"* | n/a | 🧱 **no** | 🧱 never in a shipped path |
| StableMaterials / SDXL base | — | **OpenRAIL** / OpenRAIL++-M | ✅ with restrictions | ✅ |
| FLUX.1-dev | — | **non-commercial** | 🧱 | 🧱 skip |
| FLUX.1-schnell | — | Apache-2.0 | ✅ | ✅ |
| Poly Haven / ambientCG | — | **CC0** | ✅ zero bookkeeping | ✅ **adopt now as the curated baseline** |
| MoMask / MDM | MIT | no stated weights licence | ⚠️ **the weights are fine; the DATA is not** | ⚠️ |
| HumanML3D ← **AMASS** data | — | research-use restrictions | ⚠️ restrictions flow into shipped clips | ⚠️ **the one genuinely unresolved corner** |
| SMPL / SMPL-X | research-only | research-only | 🧱 | 🧱 avoid (skip PyTorch3D and `smplx`) |
| MotionGPT | MIT | HF card says only `cc` | ⚠️ ambiguous | 🧱 skip |
| ACE-Step | Apache-2.0 | Apache-2.0 | ✅ | ✅ |
| Stable Audio Open 1.0 / Small | MIT | Stability Community, gated | ⚠️ commercial **< $1M revenue** | ⚠️ register |
| MusicGen / AudioCraft | audiocraft MIT but sdist pins `torch==2.1.0`, `xformers<0.0.23` | **CC-BY-NC 4.0** | 🧱 | 🧱 skip |
| CHORD | Ubisoft ML, **Research-Only Copyleft** | same | 🧱 | 🧱 skip |
| TexGaussian | **no LICENSE file** | card says apache-2.0 | ⚠️ ambiguous | 🧱 skip until pinned |
| Nova3D / nova3d-mcp | MIT (archived) | hosted service, **output terms unpublished** | ⚠️ | 🧱 skip; steal the interface pattern |
| SimReady foundation | Apache-2.0 | third-party robots keep their own notices | ✅ | ✅ schema only |

**The register's three rules** `[rev-tech §3]`: (1) **weights licences gate shipped assets,
not just code** — four entries have clean code with unusable weights, and one is the
reverse (the MIT ComfyUI host carrying a GPL codebase and a licence-unknown GGUF repack);
(2) **region flags are real** — `extra_gated_eu_disallowed: true` is present on Pixal3D
and Hunyuan3D-2-mini, verified from the HF README frontmatter; (3) **the scheduler stamps
the licence** — so the model registry, not the job, holds this table, and it must be held
**per weights revision**, because the same repo can be re-licensed.

### 2.8 Port as-is, or rewrite for the Thor?

Casey's standing instruction is explicit: *"Thor-native rewrites are welcome, and
breakthroughs are the point"* — *"heavily rewrite any program (Infinigen, Blender stages,
generators) to fit the Thor's specific chips. That means its unified memory, the Blackwell
GPU and tensor cores (FP8/FP4), its hardware engines, and its 14 Neoverse cores. Don't
settle for 'make it run as it does on x86'"* `[CLAUDE]`. Every choice below is a place
where the plan can either port something or rewrite it for the silicon. The rewrite option
and the experiment that would prove it are named for each. The precedent is not
hypothetical: the terrain CUDA kernels have already been rewritten this way
(`3668454a`, `-arch=native`) `[rev-tech §2.1]`.

| Choice | Port as-is | Thor-native rewrite option | Experiment that would prove it |
|---|---|---|---|
| **The scene / render path** | Port Infinigen's per-task Blender relaunch and `scene.blend` round-trip to aarch64 | **Do not port the batch workflow at all.** Replace it with a **warm resident scene server**: a long-lived Thor-side process owning the open scene, with the builders calling into it (split move #1) | p50/p95 edit→preview latency, batch-vs-warm on the *same* recipe edit; Blender process starts per night (target 1–2 vs ~1 per task today) `[split §6 move 1]` |
| **The constraint solver** | Port the pure-Python greedy simulated-annealing solver (≈38 min for 5k steps on x86 **[C]**; expected worse on 2.6 GHz ARM) | **Re-solve incrementally and natively**: room-scoped re-solves via the existing `solve_state.json` and per-assignment greedy-stage hooks, with the inner loop on the 14 Neoverse cores | Wall time of "edit one room" end-to-end vs full regeneration; stage-cache hit rate per night `[split §6 move 2]`. The x86-vs-ARM factor itself is a placeholder [P] until Hello Room is timed on the Thor `[split §7 #2]` |
| **Blender / Cycles on sm_110** | Build Blender 4.2 from source with a patched `config.h` (sm_90/100/110 launch bounds) — a **permanent local fork** either way | **Fork further: make the fork Thor-native** rather than merely sm_110-compatible — tune the build for the Thor's unified memory and Blackwell tensor cores | `cuobjdump --list-elf` on the Cycles CUDA binaries must show **sm_110**, not sm_75-only; and a GPU render of the same frame must not be slower than the CPU render (spike 1's pass/fail) `[rev-tech §5 #1]`. Sustained draw under load decides MAXN vs 120 W [P] `[split §7 #6]` |
| **The generative models** | Run stock ComfyUI + TRELLIS.2 (MIT weights, no compiled extension) | **Quantise and re-target for Blackwell FP8/FP4**, so the 24 GB floor **[C — TRELLIS.2's published H100 figure]** drops and interactive latency becomes reachable — the Thor's tensor cores are the point, and FP8 is what they are for | Measure wall-clock at 512³ and 1024³ on the Thor and peak `MemAvailable` dip, FP8 vs FP16, same seed — spike 2's pass/fail, which already requires `torch.cuda.get_device_capability() == (11, 0)` and no compiled extension in the install `[res-3d §8]` `[rev-tech §5 #2]` |
| **The critic** | Off-the-shelf vision model on the Thor, hot-resident | **Train or serve a small purpose-built defect detector** on the seeded reference set instead of a general VLM | The reference set of ~30 renders with seeded defects, and the checks' false-positive / false-negative rates against a target band `[rev-ux §R4]` `[rev-spec patch 15]` — *"without this, 'the critic passes it at 2× load' is a vibe"* |
| **The taste model** | A local LLM on the Thor reasoning over the ledger | **Replace the LLM with a small classifier/regressor trained directly on the taste rows** — cheap, local, deterministic, and it makes the two-observation gate a property of the model rather than a prompt rule | Replay a synthetic ledger of N rows and compare per-claim-type calibration against the two-observation gate; measure row→update latency. **Note: no source document chooses an implementation for the taste model — the choice is still open** `[vision §The pieces #6]` `[ux-trust §The taste ledger]` |
| **TTS / voice** | A local TTS on the Thor | A rule-based formant/phoneme synthesiser for the builders' fixed voices — no model, no licence, no latency | Only after a TTS is actually evaluated; until then voice is **[later]** and every voice path ships a text+click equivalent first `[core-spec §0]` `[rev-ux §R14]` |

---

## 3. What we decided, what we believe but haven't verified, and what we don't know

### 3.1 What we decided

These are settled across the rounds, with their source.

**Architecture and product**

1. **The recipe is the source of truth; USD is a compiled, one-way output.** No
   USD→recipe round-trip except asset import `[res-cad §8]` `[core-spec §0 row 11]`.
2. **Three layers**: the program (recipe + engine), the characters (avatars that change the
   world only through a closed typed vocabulary), and the ship's computer (the only layer
   that changes the program itself) `[vision §The architecture]`.
3. **The builders never write code.** They change the world only through predict, render,
   keep, undo `[vision §The architecture]` `[CLAUDE]`.
4. **The work order is the bridge** between a character hitting a limit and a new
   capability `[vision §The architecture]`.
5. **No orchestration framework.** The audit log is the checkpoint; adopt LangGraph only if
   its checkpointing beats ours `[core-spec §0 row 7]`.
6. **The store of record is a single-writer SQLite ledger with audit-as-source-of-truth and
   everything else a projection** `[core-spec §1.0]`.
7. **Hot tier reserved for interactive; the night batches strictly by model** `[core-spec §0
   row 8]`.
8. **Magnus's taste never counts toward Casey's.** Separate `author` scopes, forever
   `[core-spec §0 row 4]`.
9. **The taste ledger never leaves the machine**; model calls get scoped slices `[core-spec
   §0 row 6]`.

**The ledger and the night**

10. **Three record types, three writers, one store**: `taste_note` = owner only;
    `prediction` = builder, sealed; `verdict` = Critic, defects only. *"Build this
    first."* `[rev-ux §D1]`
11. **The night may keep things without asking, but only for defects, never for taste**
    `[rev-ux §D2]`.
12. **The Critic gets two surfaces**: the defect Critic never sees the ledger; the taste
    critic may only rank, never accept `[rev-ux §D3]`.
13. **The single "prediction score 8/10" is killed.** A single accuracy number per builder
    is theatre; the replacement is per-builder, per-claim-type lines with denominators
    `[ux-trust §Sealed predictions]` `[rev-ux §C2]` `[rev-spec §3.1]`.
14. **The morning leads with a mandatory status line** — `ran as planned | ran short | ran
    degraded | did not run` — then the failure line, then the numbers, then the cut named
    `[rev-ux §D6]` `[gaps §2]`.
15. **The night's keep/revert is a Critic *verdict* write, never a taste write** — otherwise
    "the taste model trains on its own output" `[rev-ux §C5]` `[rev-spec §3.11]`.
16. **Magnus is chips only, and proposes rather than applies** `[rev-ux §D4, C7, C8]`.

**Budgets, lines and interruption**

17. **Three clocks**: Talk ≤ 2 s, Watch ≤ 5 s per card, Workshop ≤ 60 s with progress and a
    cancel `[ux-day §The three clocks]`.
18. **Interruptions 3/hour; feed narrations 6/hour**; a line never repeats within a
    session, and no builder uses the same construction twice in a row `[rev-ux §C4]`.
19. **Rails are denominated in (GPU-minutes, hosted-cents, wall-minutes)**, with defaults
    and a degradation order `[core-spec §0 row 3]`.
20. **One budget bar for the owner, four counters under it, money scoped to hosted calls
    only** — plus the per-model-load cap the batched lane requires `[rev-ux §D5]`.
21. **A morning may ask for ≤ 10 decisions**; the cut happens at the queue, not at the
    reader `[gaps §4.3]`.
22. **At most 3 blocking questions may exist at night**; a builder about to park a fourth
    parks the *task* instead `[gaps §4.5]`.

**Technology**

23. **The prop-maker stack is TRELLIS.2 via the ComfyUI native path, plus TripoSR as the
    parallel baseline** — and modly's FastAPI/MCP *pattern* is kept, not its texture path
    `[rev-ux §7]` `[rev-spec §3.6]`.
24. **build123d primary, CadQuery secondary** `[core-spec §0 row 1]` `[res-cad §1]`.
25. **OpenUSD adopted for assembly and interchange; SimReady as a schema** `[res-cad §6]`.
26. **Four environments plus one optional**, and *"environments are the compatibility unit;
    residency is the process unit"* `[rev-tech §4.1]`.
27. **The merged spike order, first five**: (1) bpy 4.2 on aarch64 + Cycles CUDA on
    sm_110; (2) TRELLIS.2 native on ComfyUI; (3) the USD backbone (recipe → layered USD +
    build123d STEP→GLB); (4) modly headless FastAPI + TripoSG, mesh-only; (5) ACE-Step +
    StableMaterials/SDXL. Each has a written pass/fail check `[rev-tech §5]`.
28. **Deliberately deferred, with reasons**: MoMask (data licence — run it as a *technical*
    spike once the asset-record spine exists); TripoSR (folded into spike 4); SF3D/SPAR3D
    (start the registration now, spend no spike time yet); Material Anything, 3DTopia-XL,
    Hunyuan3D, Pixal3D (evaluate inside spike 2's environment) `[rev-tech §5]`.
29. **Acceptance checks are scripted analytic computations, not simulations.** No physics
    engine has been adopted anywhere in the document set; "2× load" is otherwise a vibe
    wearing a number `[rev-ux §R11]` `[rev-spec patch 5]`.
30. **The OOM row is the wrong failure row.** On 122 GB with every model under ~10 GB, the
    failure the night will actually have is contention and thrash; recovery is queue delay
    plus a report line, and a degraded verdict belongs on the evidence card, not only in a
    log `[rev-ux §R17]` `[rev-spec patch 7]`.
31. **Every source build passes `-arch=native`, and every `.so` is checked with
    `cuobjdump --list-elf` before it is trusted** — one build rule for the whole port
    `[rev-tech §6 R1]`.
32. **A silent CPU fallback is asserted against at environment-build time**:
    `torch.cuda.is_available()`, `get_device_capability() == (11, 0)`, `torch.version.cuda`
    starting with "13". *"Fail the install loudly, never at run time"* `[rev-tech §6 R2]`.

**Experience details settled in round 2**

33. **Standing exits in every branch set from night one**: "keep yesterday" and "back to
    the plan" — so using them on a bad morning reads as a choice, not a failure
    `[gaps §4.4]`.
34. **Every verdict is a word, never a colour alone**; the whole night is browsable as text
    over the ledger; the report has a text mode `[gaps §4.2]`.
35. **A share link carries a recipe + provenance bundle labelled "recipe — re-render may
    differ"**, and the regenerate action is worded **"reinterpret with [model]"**, never
    "regenerate" `[gaps §4.1]` `[rev-ux §R9, R15]`.
36. **The client is a viewer of a named commit, never a holder of state** `[gaps §4.6]`.
37. **Two queues, one lane, one priority rule**: Casey's queue is the night; Magnus's is a
    reserved slice scheduled *into* the warm batches, never alongside them `[gaps §4.7]`.
38. **The pre-flight may propose, never decide** — the owner's bar, the owner's start; only
    the safety rails act without asking `[gaps §8 #2]`.
39. **Cold start is a mechanism, not a number of nights**: questions and `guess` confidence
    decay per builder, per reason code, at two observations `[gaps §8 #3]`.
40. **Night one runs the calibration batch by default**, sized to the night's unused lane
    `[gaps §8 #1]`.

### 3.2 What we believe but have not verified

Things a source asserts, or that we infer, which **nobody has measured on this box**.

| # | Belief | Claimed by | How it would be verified |
|---|---|---|---|
| 1 | TRELLIS.2 will run on the Thor through ComfyUI's native path, with MIT weights and no compiled CUDA extension | `res-3d §4.1` | Spike 2's pass/fail `[rev-tech §5 #2]` |
| 2 | TRELLIS.2's speed ladder: 3 s at 512³, 17 s at 1024³, 60 s at 1536³, ≥24 GB | **`res-3d §1` — an H100 measurement** | Measure on the Thor at 512³ and 1024³, with the peak memory dip recorded `[res-3d §8]` |
| 3 | TripoSR generates in "less than 0.5 seconds" | **`res-3d §1` — an NVIDIA A100 measurement** | Measure on the Thor |
| 4 | ACE-Step makes a 4-minute track in ~20 s | **`res-cad §5` — an A100 number**; the report says so itself | Measure on the Thor; the report expects the number to be far worse, and says measuring it is the point `[rev-tech §5 #5]` |
| 5 | modly's headless FastAPI backend "already proven on a Jetson" | `res-cad §TL;DR` — not on *this* Thor | Spike 4's pass/fail `[rev-tech §5 #4]` |
| 6 | The Infinigen solver takes ≈38 min for 5k solver steps | **`split §1` — the x86 authors' hardware** | Hello Room on the Thor `[split §7 #2]` [P] |
| 7 | The Thor is 2–4× slower than x86 on that solver | `split §7 #2` — an estimate | Same |
| 8 | Batch-by-model "roughly doubles usable night GPU-hours for free" | `split §6 move 5` — an estimate | Model-load count per night (target 1 per model) |
| 9 | Stock PyPI `torch` 2.15.0 ships an aarch64 CUDA wheel with sm_110 kernels | **`res-cad §TL;DR, §2, Appendix`** — downloaded and scanned; but `res-3d §1, §7` says PyPI aarch64 torch wheels are CPU-only | `pip download torch==2.15.0 --only-binary=:all: --platform manylinux_2_28_aarch64` and look for `nvidia-*` deps — one command on the Thor `[rev-ux §4.1]`. **See §4.1** |
| 10 | Every contender "runs headless as X" | **`bakeoff §7` — from vendor docs and installed source; no contender was run** | Run the bake-off `[bakeoff §5]` |
| 11 | Claude Code's median cost per accepted hard order | Not measured. The $2 threshold in `bakeoff §4.2` is a **switch point**, not a result | The bake-off's cost dimension, N=1 for WO-1/WO-2 |
| 12 | The local 30B coder can hold repo context | **`bakeoff §4.2` — "very likely" it cannot on WO-2**; the model services are not even running | Start the local servers, run WO-2 |
| 13 | A 30B model at bf16 is ~60 GB of weights | `bakeoff §3.2` — **arithmetic, explicitly not a measurement** | Read the server's quantisation config |
| 14 | The Critic can be a defect model at all | Not chosen. `rev-ux §R4` calls it *"the largest unchosen dependency in the whole stack"* | The ~30-render seeded reference set and its FP/FN band `[rev-spec patch 15]` |
| 15 | The recipe compiles deterministically to USD layers | `res-cad §8` argued it; spike 3 tests it | Re-emit → identical bytes, sorted prims, no timestamps `[rev-tech §5 #3]` |
| 16 | The stage cache keyed by `hash(recipe, gin, stage, dep-keys)` will hit often | `split §6 move 2` — a design | Stage-cache hit rate per night |
| 17 | The critical-path loss is thrash, not OOM | `rev-ux §R17` with `res-cad §9` — **predicted, never observed** | One night with a load counter on it |
| 18 | The local lane can coexist with Infinigen/Cycles work | `bakeoff §4.2` — if it cannot, Seat B's "free" advantage evaporates | Measure memory contention during a render window |

### 3.3 What we don't know

**The six spike-dependent facts** — the whole reason `thor/SPIKE.md` matters, and the reason
it is a placeholder here [P]:

1. Cycles GPU throughput at sm_110.
2. Hello Room / Hello World stage timings on aarch64.
3. Peak RSS per warm scene → how many worlds and branches stay resident in 122 GB.
4. Whether bpy 4.2 on aarch64 lands at all.
5. EEVEE-headless (EGL) viability.
6. Sustained power draw under GPU load → MAXN vs 120 W for the night window.

**The experience latencies nobody has measured** `[rev-ux §4]`: neither technology report
covers Infinigen, Blender, Cycles, the vision Critic, the planner LLM or speech. So the
world-stream time, the branch pre-render time, the peek's before/after thumbnails and the
Critic's read time have **no technology evidence at all**. The 8 s / 12 s / 15 s numbers in
`rev-spec` patch 14 are explicitly *measurement-gated*.

**The open product questions**:

- **Which Critic**, and what its false-positive and false-negative rates are. Until it is
  chosen and measured, every automated verdict must carry `verdict@scripted` on its face
  `[gaps §1]`.
- **How the taste model is implemented.** No source document chooses one; it is a concept
  in the vision and the trust report, not a design.
- **Whether the recipe→USD spine, the warm scene server and the stage cache actually
  behave as designed.** All three are designs with stated measures, none is built.
- **What the referent chain does.** The spec has no node-id ↔ entry-path registry, so
  *"Computer, make these sturdier"* cannot compile from the context packet as specified
  `[rev-spec §1.2.1]`.
- **What the morning report's first line says when the night did not happen.** The spec has
  no night-status taxonomy and stores caps rather than asks, so it cannot name the cut
  `[rev-spec §1.2.2]`.
- **Whether the Orin is in scope at all.** `split §2.2` assigns it CPU-lane overflow and a
  watchtower; `CLAUDE.md` says "spare; ask before using"; the core spec is Thor-only and
  single-writer, and `Job` has no `worker` field. `rev-spec` patch 19 says: either add
  `Job.worker` + a worker registry, or write Orin into the non-goals.
- **Whether the taste ledger can actually be exported and erased.** The spec promises
  Magnus's rows are "exportable and deletable in one action each", but `/v1/ledger/taste`
  is GET-only and the audit fold makes deletion undefined — it needs a tombstone-and-
  projection design `[rev-spec §1.3]`.
- **How the magnitude of the "1023" the eye reads as "world" is achieved** — i.e. whether
  the ghost/LOD path is good enough for the day half of the experience.
- **What the "landscape" report would have said.** `~/lm-wt/landscape/REPORT.md` does not
  exist; nothing in this document is based on it.

---

## 4. Where the reports disagree, and how it resolves

### 4.1 The torch wheel — PyPI CUDA vs CPU-only (unresolved, non-blocking)

| Position | Source |
|---|---|
| *"stock PyPI `torch` 2.15.0 now ships an aarch64 CUDA wheel built against CUDA 13.2 with `sm_110` kernels inside `libtorch_cuda.so` (verified by downloading the 462 MB wheel and scanning the fatbin arch strings; deps pin `cuda-toolkit==13.2.2`, matching this box exactly)"* | `res-cad §TL;DR, §2, Appendix` |
| *"The aarch64 torch wheels published on PyPI are CPU-only builds — the 2.6.0 aarch64 wheel declares no `nvidia-*` runtime dependencies whatsoever — so a working Thor install must point at NVIDIA's own indexes"* | `res-3d §1, §2, §7` |

**Verdict: does not hold (unresolved) — but it does not block anything** `[rev-ux §4.1]`.
Both can be true at different versions: 2.6.0's wheel was CPU-only; 2.15.0 may genuinely
ship CUDA. `res-cad`'s evidence is stronger in kind (download-and-scan of the newer
release), but `res-3d` is the report that reasoned about it rather than sampled it.

A partial resolution has since appeared in `rev-tech`'s ledger, which lists torch 2.15.0 as
**✅ 483.7 MB, ✅ `cuda-toolkit==13.2.2`, ✅ 535 sm_110 images** `[rev-tech §2.1]` — but
that is a wheel-scanning result, still not an install on the Thor. **Settled by one
command** on the box: `pip download torch==2.15.0 --only-binary=:all: --platform
manylinux_2_28_aarch64`, look for `nvidia-*` runtime dependencies. **Plan on the NVIDIA
cu132 index either way** — `res-3d`'s path is correct in both worlds and also solves the
cp312 pin collisions.

### 4.2 The prop-maker stack — modly vs TRELLIS.2 (resolved)

`res-cad` recommends **modly's headless FastAPI backend with TripoSG**, with **textures
deferred past the spike** `[res-cad §TL;DR, §2, §10]`. `res-3d` recommends **TRELLIS.2 via
the ComfyUI native path, plus TripoSR as a licence-clean baseline**, and TRELLIS.2's
shape-conditioned texturing covers the texture role in the same environment
`[res-3d §3, §4.1, §8]`.

**Resolved in favour of `res-3d`** `[rev-ux §7]`: *"res-3d is newer than res-cad on this
point and it is the one that removes the source builds and the licence problem."* The
ruling is not merely a preference — it removes the one genuinely heavy item from the
critical path (the texture source builds), and it is the licence-clean option. The
correction lands in `rev-spec` as **patch 12**: update the spec's generative-station
section to the TRELLIS.2-native stack, *keep modly's FastAPI/MCP pattern*, and note that
this **changes what the phase-1 spike measures**. ComfyUI is GPL-3.0, so it is hosted as a
**separate service** `[rev-tech §3]`.

### 4.3 One environment per model family, or four (resolved)

`res-3d §6` says each model family wants its own environment (TRELLIS.2 answers with a
py3.10 conda env; cp312 pins collide). `rev-tech §4.1` rejects that for the adopted set
and lands on four environments plus one optional, because every adopted generator shares
one torch ABI (2.15 aarch64 / CUDA 13.2 / sm_110) and one interpreter (3.12) — so they need
their own **process**, not their own environment. The rule: **environments are the
compatibility unit; residency is the process unit.** The licence differences are a
**registry** concern, not an environment concern. `rev-spec` patch 12 carries the
consequence into the spec: WO estimates must split **build/verify** from **generate/test**,
because *"a work order that must build a py3.10 conda environment before its first render
is a different three hours."*

### 4.4 "122 GB makes VRAM a non-issue" (resolved, with a correction)

`res-3d §1`: *"the Thor's 122 GB of unified memory makes every published VRAM requirement a
non-issue."* `rev-tech §C9` agrees about capacity and disagrees about the conclusion:
right about capacity, **wrong about contention** — the real constraints are GPU
compute-time and weight-swap thrash, and on a unified pool `nvidia-smi` reports
`memory.used`/`memory.total` as `[N/A]`, so **there is no GPU-memory signal at all** and
eviction must be driven from `/proc/meminfo` `MemAvailable` plus `tegrastats` RAM
`[rev-tech §4.2, §6 R3]`. Capacity is a non-issue; observability and thrash are the issues.

### 4.5 "The sim" — an acceptance check with no engine (resolved)

The core spec's acceptance story for the bridge is *"load factor from the sim"* and *"rope
snapped in sim"* `[core-spec §2.3 step 4, §1.3]`. But **no physics engine is adopted
anywhere in the document set**; SimReady gives schemas, not a solver; and `res-3d §6`
keeps CAD on parametric code for exactly this reason `[rev-ux §R11]`. **Resolved**: define
`load_floor` constraint checks as **scripted analytic computations** (build123d mass
properties and member forces from the recipe's parameters, on the CPU lane — deterministic
and recipe-native), and purge the "sim" language. *"If a real solver is ever wanted, that
is an engine decision with its own work order."* `rev-spec` patch 5.

### 4.6 The critic OOM row (resolved)

`ux-day §2` has "the critic OOMs in a big texture batch" as one of the night's failure
rows. `rev-ux §R17`: on a 122 GB unified box with every model under ~10 GB, OOM is the
wrong row; the failure the night will actually have is **contention and thrash**, whose
recovery is queue delay plus a report line, not a degraded verdict. **Resolved**
`[rev-spec patch 7]`: keep the critic demotion path as defence in depth, add the
thrash/stall row alongside it, and require the `degraded` flag on the **evidence card
itself**, not only in the report.

### 4.7 The line budget — 6/hour vs 3/hour (resolved)

`ux-day` allows ~6 lines per builder per hour, only on state change. `ux-trust` allows one
interruption per builder per twenty minutes (≈3/hour), citing a companion-design density
finding of three to six conversational beats per hour. **Resolved** `[rev-ux §C4]`: **3/hour
for interruptions and 6/hour for feed narrations** — the literature is about *conversational*
beats, and a feed card is a log line. `ux-trust`'s rule that A lacks also survives: **no
line repeats within a session**, and no builder's line uses the same construction twice in
a row. This is already in the spec `[core-spec §5.6]`.

### 4.8 Who writes the ledger — owner only, or the Critic too? (resolved; the spec has not caught up)

This was *"the most consequential conflict in this review"* `[rev-ux §C5]`. `ux-day`'s
night has the Critic keeping 10 of 12 crates overnight; `ux-trust` says the ledger is
append-only with a single writer — the owner's verdict event and nothing else. If
`ux-day` is right, the ledger fills itself overnight and the privacy, author-scoping and
honesty architecture becomes decorative.

**Resolved** `[rev-ux §D1, D2]`: **three record types, three writers, one store** —
`taste_note` (owner only), `prediction` (builder, sealed), `verdict` (Critic, defects
only). The night may auto-revert on a checkable defect; only the owner's verdict writes a
taste note.

**But the core spec has not been updated.** `rev-spec §3.11` finds that the spec has all
the pieces and never joins them, with two consequences left unspecified: the night's keep
must not resolve a `taste_keep` prediction (the owner scores those), and the owner's
morning apply/keep/reject *should* resolve outstanding `taste_keep` predictions on that
branch. `rev-spec` patch 6 asks for one paragraph in §1.7/§3.2. **This is an open
implementation gap, not a live disagreement.**

### 4.9 What the Critic judges — taste or defects? (resolved)

`ux-day` implies the Critic judges by the owner's taste. `ux-trust` says the Critic judges
checkable defects and never sees the ledger. **Resolved** `[rev-ux §D3]`: **two surfaces**.
The defect Critic never sees the ledger; the taste critic may only **rank, never accept**.
`rev-spec §6` notes the Critic is still *unchosen and uncalibrated* — it has a demotion
path but no selection path, no calibration gate, and no spike line — and patch 15 supplies
the missing acceptance test.

### 4.10 Magnus — speaks or taps, and how much power? (resolved)

`ux-day`'s 20:47 beat has Magnus asking *"Can the bridge swing when you run on it?"* out
loud, with a narrative beat that `ux-trust` believes cannot survive the privacy boundary.
**Resolved** `[rev-ux §C7, D4]`: **chips only.** The narrative beat is preserved — a
two-surface walk — and the audio is dropped, which makes the privacy property structural
rather than promised. On power `[rev-ux §C8]`: Magnus gets preview-keeps and
question-answers; **branch applies are Casey's**, because a branch choice is a recipe
pointer and therefore a real edit. `rev-spec patch 8` notes that the spec's token classes
carry no actor notion, so the policy is currently prose rather than structure.

### 4.11 One budget bar or three rails? (resolved, plus a correction)

`ux-day` shows one bar in GPU-hours; `ux-trust` wants three rails including money.
**Resolved** `[rev-ux §D5]`: **one bar for the owner, four counters under it, money scoped
to hosted calls only** — and add the per-model-load cap the batched lane requires.
`rev-spec §3.3` adds the correction: all three technology documents agree the *hardware*
constraint is weight-swap thrash, and the spec's rail cannot count loads; the day has a
swap budget, the night — the batched case the constraint is actually about — has none.
`rev-spec` patch 3 adds a per-model load cap per night to the registry policy, enforced at
**batch admission**, with the 80% graduation **[B — a threshold, not a measurement]** mapped
to "stop opening new batches, drain the current one".

### 4.12 The morning report — what leads, and which number survives (resolved; the spec still has the old number)

`ux-day`'s report leads with the night's line and a single "prediction score 8/10 (was 7)".
`rev-ux §C2` calls that number *"the one number both reports must kill"* and requires
per-builder, per-claim-type lines with denominators instead. **Resolved**: the score is
deleted; the report is **status line → failure line → numbers**; and the *cut* must be
named — *"a report that shows '5.3 of 5.5' without naming the 1.7 h that was dropped is the
single most dishonest-looking artifact in either report"* `[rev-ux §C11]`.

**But the spec still carries the old number** `[core-spec §3.2.8]`, and contradicts its own
`§1.7`, whose `claim_type` exists precisely to prevent one-number summaries
`[rev-spec §3.1]`. `rev-spec` patch 2 deletes it. The spec also cannot comply with the
status line or the cut disclosure today: it stores caps rather than asks (no
`Task.cost_estimate`) and has no night-status taxonomy `[rev-spec §3.2]`.

### 4.13 The night is not silent — does the feed narrate recoveries? (resolved)

`ux-day` narrates recoveries at 03:12; `ux-trust` forbids narration. **Resolved**
`[rev-ux §C3]`: a split — the feed may narrate a **state change**, a conversational
interruption may not, and nothing may repeat. Already in the spec `[core-spec §5.6]`.

### 4.14 The spec vs the compute plan — five gaps `rev-spec` finds

These are not disagreements between reports but between the spec and everything else, and
they are the highest-value open items in the set.

| Gap | What `rev-spec` found | The fix |
|---|---|---|
| **The referent chain is broken** | The context packet carries world **node ids**; the recipe is keyed by **entry paths**; `WorkOrder.targets` holds node ids while acceptance checks reference paths. **No node-id ↔ entry-path registry exists anywhere in the spec** — so the product's signature move, *"Computer, make these sturdier"*, cannot compile from the packet as specified. The packet also dropped `renders`, which the vision's packet includes, and carries no parameters, so *"keep the sway"* has nothing to keep | Patch 1: a node registry; `View` gaining resolved referents; a bounded params block; `History.renders` and recent landed/kept WO outcomes |
| **The warm scene server is absent** | It is not a `Job`, not a model-registry tier, not an endpoint, not in the build order, not in the crash model. Without it, the ≤ 60 s Workshop budget has no mechanism, and batch Infinigen pays a full engine restart per edit | Patch 4: a scheduler-managed resident resource — `scene.loaded`/`scene.evicted` events, per-branch residency bound, eviction policy, and one hard rule: **it is a derived cache, never a writer**, rebuildable from recipe version + stage cache, listed among what does not survive a reboot |
| **The stage cache has no key contract** | `EnginePin` pins repo/commit/blender/python — **but the gin config is not pinned anywhere**. If engine-side configuration drifts, the cache key is not a function of the recipe version, so identical recipes can miss and divergent configs can hit; job-dedup convergence and the merge gate's deterministic rebuild are both defeatable | Patch 13: pin the config hash in `EnginePin`; require stage-cache keys ⊆ (recipe version hash, engine pin, stage); report the hit rate per night; state the partial-regeneration dirty-set contract and the solver-placement rule |
| **Batch start on detach only** | Both the spec and `split` gate the big batches on client detach — but if the client never detaches, the big batches never run, and the morning must say so. The spec has neither the timeout nor the telemetry to explain it | Patch 10: start on detach **or** a timeout (~30 min after `night.started`); add `client.attach`/`client.detach` events so the report can distinguish "client never detached" from "queue empty" |
| **Batch start on detach only** *(second consequence)* | Client presence is also the input the report's "did not run" reason needs | Same patch as above |

### 4.15 Where the experience spine fails to build, and what to do

`rev-spec §1.1` walks all fifteen spine moments through the spec's data model and APIs.
**Twelve of fifteen are buildable on this spec today**; the failures cluster in the
morning (S10) and the first session (S1), and the gaps cluster around *pre-night* state
(S3/S5) and the second author (S4). *"Nothing in the spine requires a redesign of S's
core — the fixes are additions, mostly to §1.4, §1.9, §3.2.8 and §4.2."*

Specifically: **S1 missing** (the confidence gate makes every builder silent on night one,
and nothing says what the Companion does instead); **S10 fails the merge** (the single score
survives, the status line and the cut are absent); **S11 holds but is short** (re-stream
≤ 15 s is missing from the budget list, candidate scene manifests are not pre-baked, and
apply is not actor-scoped); **S12 holds but the assumption is not attached to the branch**;
**S15 holds but is one endpoint short**.

### 4.16 The twenty-patch list

`rev-spec §4` is the consolidated, ordered patch list for the core spec. In order of
importance: node registry and packet enrichment (1); report rewrite (2); per-model load
cap (3); warm scene server (4); scripted analytic checks replacing "the sim" (5);
three-writer rule (6); geometry check before the critic plus the thrash row (7);
actor-scoped Magnus channels (8); taste export/erase mechanism (9); client presence events
and the batch-start timeout (10); pre-night slate records and `Task.cost_estimate` (11);
TRELLIS.2-native generative stations and per-family environments (12); engine-config pin
and the dirty-set contract (13); re-stream budget, delta channel, pre-bake, glTF-first
(14); Critic selection and calibration (15); seal the recipe tuple and log power mode
(16); cold-start ask-mode (17); licence dependency terms and "reinterpret" wording (18);
Orin decision (19); a tally read API and verdicts-as-words (20).

`rev-spec` is explicit about what must **not** change: §5's durability design
(audit-as-checkpoint), the recipe-vs-USD one-way rule, the sealed-before-render ordering,
the branch/pointer-move model, and the interruption/narration budgets all survive the
review unchanged. *"Cite them as settled when the patches land."*

### 4.17 The three open decisions `gaps` hands to the owner

`gaps §8` leaves three, each with a recommendation, in the order they block work:

1. **Does night one run the calibration batch by default?** It costs lane-time on a night
   whose lane is mostly idle. → **Recommendation: yes, sized to the night's unused lane.**
   It converts the review's "largest unchosen dependency" into a measurement schedule
   instead of a hope.
2. **May the pre-flight act, or only propose, when the lane is busy?** →
   **Recommendation: propose only** — the owner's bar, the owner's start; the sole
   exception is the safety rails, which act without asking exactly as `ux-trust` already
   specifies. *"A pre-flight that silently re-plans your night is the first step back to a
   night you don't trust."*
3. **Is cold start a number of nights or a mechanism?** → **Recommendation: a
   mechanism** — questions and `guess` confidence decay per builder, per reason code, at
   two observations, which makes the first week's melt auditable in the ledger rather than
   tuned by hand.

---

## 5. Glossary

**Recipe** — the project's source of truth: generators, parameters, constraints, seeds.
Meshes and renders are caches. Diffable, branchable, replayable; a night's work is
kilobytes `[vision §The pieces #2]`. **Recipe version** — an immutable, content-addressed
snapshot (`ver_`) of the recipe; **branch** (`br_`) — a named line of recipe versions, so
alternatives are branches and undo is a checkout `[core-spec §1.1–1.2]`.

**Entry** — one row of the recipe (a wall, a span, a jetty). **Entry path** — its dotted
address (`structure.south_span`), the key by which the recipe is indexed. **Node id** —
the engine's identifier for the thing in the world (`span_south`). These two are *not*
joined anywhere in the spec today — the referent-chain gap `[rev-spec §1.2.1]`.

**Vocabulary** — the closed, typed language the builders speak. Each entry has a parameter
schema and constraint checks; the builders can only change the world through it
`[vision §The architecture]`. **Work order** — the bridge between a limit and a new
capability: goal, objects named by id, acceptance check, budget; compiled from a terse
utterance and confirmed in one line `[vision §Calling the computer in-game]`.

**Context packet** — the situation data attached to every call to the computer: what
"this/these/here" means, recent history (recipe changes, renders, critic notes), the
conversation as bounded labels, and the project state. *"The packet is the only situation
data that crosses into a model prompt"* `[vision §Calling the computer in-game]`
`[core-spec §1.4]`.

**Sealed prediction** — a claim written *before* the render, hashed (`seal_hash`), and
scored afterwards by the Critic against that hash. *"Seal the prediction before the test"*
`[CLAUDE]` `[ux-trust §Sealed predictions]`. **Claim type** — the category of the claim
(`shadow_count`, `scale_read`, `clutter_density`, `material_read`, `era_read`,
`light_read`, `weather_read`), which is what makes the record worth having `[core-spec
§0 row 2]`.

**Taste note** — the owner's verdict on an artefact, with a reason code; append-only,
single writer, author-scoped `[ux-trust §Taste note fields]`. **Verdict** — the Critic's
finding against a sealed hash (`hit | miss | partial`), defects only `[ux-trust §Sealed
predictions]`. **Taste ledger** and **prediction ledger** — the two stores; the two
tallies are kept separate because they fail differently `[ux-trust §Two tallies]`.

**Audit event** (`aud_`) — the append-only record of everything that happened; the source
of truth the whole store is a fold of `[core-spec §1.0, §1.8]`. **Projection** — a table
rebuilt by folding the audit log. **Content hash** — sha256 over canonical JSON; the
addressing scheme for artefacts and recipe versions `[core-spec §1.0]`.

**Clocks** — the latency doctrine: **Talk** ≤ 2 s (speech, HUD, plan items, keep/reject);
**Watch** ≤ 5 s per card (the night feed, verdicts, provenance); **Workshop** ≤ 60 s with
progress and a cancel (previews, critic runs, generations). *"Nobody ever waits on the
wrong clock"* `[ux-day §The three clocks]`.

**Ghost / LOD** — the cheap stand-in for the real geometry that the client renders during
the day: baked-level-of-detail glTF built from placeholders, room solids and scatter
densities, streamed as deltas, with the photoreal work queued to the night
`[split §6 move 3]` `[ideas #1]`. **Stage cache** — a per-stage memo keyed by
`hash(recipe, gin config, stage, dependency keys)`, so an untouched stage never re-runs
`[split §6 move 2]`. **Dirty set** — the entries a recipe edit actually invalidates:
touched entries, plus entries containing constraint references that overlap them, plus
asset consumers `[rev-spec patch 13]`. **Warm scene server** — a long-lived resident
process owning the open scene, replacing the per-task Blender relaunch
`[split §6 move 1]`.

**Lane** — a class of work that runs without waiting for the other: the **CPU lane**
(build123d, audio SFX, mesh cleanup, USD assembly) and the **GPU lane** (image-to-3D,
textures, motion, music) `[res-cad §9]`. **Model tiers** — **hot** (always resident),
**warm** (loaded once per night-segment, then drained), **cold** (on disk, pinned
weights revisions) `[res-cad §9]`. **Weight-swap thrash** — the real constraint on the
122 GB box: loading and unloading models repeatedly instead of batching hundreds of
prompts through one loaded model `[res-cad §9]` `[rev-tech §C9]`.

**Merge gate** — the evidence check that lets an engineer's work land: a deterministic
rebuild, unit tests, a render, the Critic's verdict `[core-spec §2.3]`. **Branch /
worktree / sandbox** — the engineer's isolated copy of the repo, one per work order
`[core-spec §2.2]`. **Seat** — an engineer instance running in a sandbox
`[bakeoff §3.1]`. **Engineer adapter** — the single interface behind which every
engineer sits: in a work order and a sandbox branch, out a commit and test evidence
`[vision §The architecture]` `[core-spec §2.1]`. **ACP** and **MCP** — the two protocols
the adapter maps onto; front ends (Zed, Theia) talk ACP, tool surfaces talk MCP
`[core-spec §2.4–2.5]` `[vision §The pieces #7]`.

**Rails** — the budget limits, denominated in **GPU-minutes, hosted-cents and
wall-minutes**, with defaults and a degradation order `[core-spec §0 row 3, §5.5]`.
**Budget bar** — the owner's single view of those rails, with counters under it and money
scoped to hosted calls only `[rev-ux §D5]`.

**Status line** — the mandatory first line of the morning report: `ran as planned | ran
short | ran degraded | did not run`, with a one-line reason when the night did not run
`[rev-ux §D6]` `[gaps §2]`. **Parked question** — a question the night could not answer
without you, stored as a `q_` record; **assumption** — the conservative reading taken
instead, recorded on the same card `[core-spec §1.9]` `[gaps §4.5]`. **Standing exits** —
"keep yesterday" and "back to the plan", present in every branch set from night one
`[gaps §4.4]`.

**Architect, Landscaper, Prop-maker, Critic, Companion** — the five builders, each with a
speciality, a permitted vocabulary slice, a voice specification and a "never says" list
`[ux-trust §Five builders]`. **Companion** — the planner and the only builder that talks to
you; one question at a time. **Critic** — the adversarial, non-authoring judge; no praise
at all. **Magnus** — Casey's son; chips only, author-scoped rows, a reserved lane ending
21:30, and a ratification gate before anything he does can train anything
`[ux-trust §Magnus]` `[gaps §3]`.

**Holodeck** — the north star: a shared physical-feeling space you are *in* with the
characters. We build toward its UX; we do not build it `[vision §The architecture]`.
**North star** — a design direction to approach, never a promise `[gaps §0]`.

**Infinigen** — Princeton's procedural world generator (BSD-3); `infinigen-thor` is the
Thor-native port `[CLAUDE]`. **Infinigen Indoors** — the room-and-constraint-solver half
of it `[split §1]`. **bpy** — Blender's Python module; **4.2.0** is the pinned version and
has **no Linux aarch64 wheel**, so it must be built from source `[CLAUDE]` `[rev-tech
§2.1]`. **Cycles** — the renderer; on the Thor it is **CUDA-only** (no aarch64 OptiX SDK)
`[split §1]`. **sm_110** — the Blackwell compute capability 11.0 that every CUDA kernel
on this box must target. **aarch64** — the ARM64 architecture. **L4T / JetPack** — NVIDIA's
L4T Linux and the JetPack release that carries it.

**OpenUSD / `usd-core`** — the scene assembly and interchange format, compiled from the
recipe `[res-cad §6]`. **SimReady** — NVIDIA's physics/material metadata, adopted as a
**schema**, not as an asset library `[res-cad §6]`.

**TRELLIS.2** — the image-to-3D model emitting real PBR, reached through ComfyUI's native
implementation (MIT code and MIT weights) `[res-3d §4.1]`. **TripoSR / TripoSG** — MIT,
seeded, mesh-only image-to-3D `[rev-tech §3]`. **ComfyUI** — GPL-3.0, therefore hosted as a
separate service `[rev-tech §3]`. **modly** — the agent-friendly headless FastAPI pattern
for a prop service; the *pattern* is kept, its texture path is not `[rev-tech §3]`
`[rev-ux §7]`. **build123d / CadQuery** — the two parametric-CAD libraries, over OCCT
`[res-cad §1]`. **StableMaterials / SDXL** — the texture path `[res-cad §3]`. **MoMask /
MDM / MotionGPT** — the text-to-motion family; the data licence is the problem, not the
code `[res-cad §4]`. **ACE-Step** — the Apache-2.0 music model. **Stable Audio Open** —
the sound-effects model; its **Small** variant runs on Arm CPUs `[res-cad §5]`.

**The register's three rules** — the house licence rules, restated from "licences are a
checked list": weights licences gate shipped assets, not just code; region flags are real;
the scheduler stamps the licence, per weights revision `[rev-tech §3]` `[vision §The pieces
#6]`.

**Budget vs estimate** — in `gaps`, `[b]` marks a **budget** (the UI must meet it; a test
can check it) and `[e]` an **estimate** that did not come off this box and is therefore not
a promise `[gaps §Timing convention]`.

---

### Sources of this document

Every claim above is traceable to one of the files in [§0](#0-sources-and-how-numbers-are-marked).
No file outside `~/lm-wt/synth-u/` was created, edited or deleted in the course of writing
it; no sub-agents were used. The two absent sources — `~/lm-wt/landscape/REPORT.md` and
`~/src/infinigen-thor/thor/SPIKE.md` — are marked [P] wherever they would have supplied a
fact, and no placeholder was filled with a guess.
