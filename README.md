# builder-ide

**A game and simulation IDE whose builders are avatars.** You and a small team
of agent builders shape a world together. Leave them working in-world
overnight, and come back the next day to hours of work done. The builders grow
with you: they learn your taste, and the "ship's computer" behind them extends
what they can do.

The north star is the holodeck from *Star Trek: The Next Generation*. We can't
build it, but we design toward its experience with what we have: an NVIDIA
Jetson AGX Thor doing the long, patient, generative work, and a laptop as the
seat you work from.

## Status (2026-10-31)

- **The engine runs on the Thor.** Infinigen (Princeton, BSD-3) runs natively
  on the Jetson Thor. Blender 4.2's Python module was built from source for
  aarch64, Hello Room and Hello World both work, and Cycles renders on the
  Thor's GPU at **7.1× its 14 CPU cores**. See
  [SI-Thor/infinigen-thor](https://github.com/SI-Thor/infinigen-thor) (branch
  `thor-spike`) and [docs/research/spike-phase1.md](docs/research/spike-phase1.md).
- **The engine decision is made.** The world engine is built on **Infinigen 2.0 +
  procfunc**, with our Warp terrain as a v2-native stage. The confirming
  experiment is running on the Thor; its first step already passed (a v2 room
  rendered on the GPU). See [docs/research/ig2-procfunc.md](docs/research/ig2-procfunc.md).
- **The engine is decided: Infinigen 2.0 + procfunc.** On the Thor, 2.0 renders on
  the GPU, a one-parameter edit regenerates one node of 4,231, and
  `fine_terrain` is now deterministic (CPU and CUDA, at no speed cost)
  ([v2-thor-experiment](docs/research/v2-thor-experiment.md)).
- **Two lab breakthroughs.** Unified memory lets NumPy, PyTorch and CUDA kernels
  share one buffer with no copy. A Warp port of Infinigen's `mountains` terrain
  is **bit-identical and 44–56× faster** than its 14-core CPU path (6× faster
  than its own CUDA kernel).
- **The core is integrated on `main`: 893 tests pass** in one suite (seven
  seats plus the engine seam merged, every stand-in replaced; see
  [INTEGRATION.md](INTEGRATION.md)). The M1 acceptance session and the melt
  week both play end to end on the integrated core.
- **The render rung is real (branch `render-rung`).** M1's render steps now
  render through the engine seam at **Infinigen 2.0 on the Thor's GPU** —
  the v2 venv behind `core.engine.venv2`, an opt-in acceptance run
  (`pytest -m engine`) that plays the whole session with real images,
  artifact hashes, provenance and licence rows in the ledger. Measured:
  **4–5 s per render** at the preview rung, a traced stage byte-stable
  across generations, the pin swap performed as one explicit edit.
- **Plan draft 2 is written, with a decision sheet.** 18 reports, three
  cross-reviews, a synthesized understanding, a core spec (v2), the plan
  ([docs/plan.md](docs/plan.md)) and a condensed sheet of the owner's open
  decisions ([docs/decisions-for-casey.md](docs/decisions-for-casey.md)).
- **Nothing is usable end to end yet.** Milestone M1 is "one evening, one night,
  one morning, one builder, one room".

## How it fits together

```
 you (ProArt laptop: the seat)        the Thor (122 GB unified memory, Blackwell GPU)
 ─────────────────────────────        ─────────────────────────────────────────────
 in-world view, fast previews  ◄────  the program: recipe + engine (infinigen-thor)
 talk to the characters        ────►  characters: avatars who build through a closed,
 "Computer, make these sturdier"        typed vocabulary (never write code)
 the morning report            ◄────  the ship's computer: backend coding and
                                        generative agents, working through work
                                        orders in the background and overnight
                                      the core: work orders, budgets, recipes,
                                        model scheduler, vocabulary, audit log
```

### The principles

- **Recipes, not meshes.** A project's source of truth is its recipe:
  generators, parameters, constraints and seeds. Meshes and renders are caches.
  A night's work is a small, diffable history you can branch, undo and replay.
- **Characters never write code.** They change the world only through a typed
  vocabulary, and they **seal a prediction before every render**. Each
  prediction is checked against what happened, so they build a track record.
- **The ship's computer extends the vocabulary.** A character that hits a
  limit, or you ("Computer, I want rope bridges"), files a work order. An
  engineer agent builds and tests it in the background, then promotes it into
  the vocabulary.
- **Calling the computer in-game takes few words.** It knows your selection,
  what you're looking at, and what just happened, so a short phrase becomes a
  full work order, confirmed in one line.
- **The Thor is an iterator.** Resident models and scenes make
  propose → critique → refine loops cheap. At night that means breadth: many
  variants, the best kept and refined, and the morning report shows what the
  winner beat. By day it means warm starts.
- **Thor-native, not ported.** Everything we build on is open source, and we
  rewrite it for the Thor's chips: unified memory, FP8 tensor cores, its
  hardware engines, its 14 cores. Ideas become measured experiments in days,
  failures included.
- **Nothing survives without a reason.** Every asset, word, branch and work
  order carries a justification chain (the WHY kernel). When a goal dies, its
  dependents become *questionable*; they are not deleted.

## Read this first

| Document | What it is |
|---|---|
| [docs/vision.md](docs/vision.md) | The why; the three layers; the work order; calling the computer in-game; making characters and objects; the Thor as an iterator |
| [docs/understanding.md](docs/understanding.md) | **The whole picture in one place**: everything known, by subject, every fact cited; what's decided, believed and unknown; a glossary |
| [docs/plan.md](docs/plan.md) | **The plan, experience first** (draft 2): milestones M0–M5, the rewrite ladder with the lab's numbers, the first three weeks, the measures |
| [docs/decisions-for-casey.md](docs/decisions-for-casey.md) | **The owner's open decisions, condensed**: twelve items — the ones that only need a yes, and the real choices, each with what happens if he doesn't decide |
| [docs/design/core-spec.md](docs/design/core-spec.md) | The core service, specified (v2): data model, engineer adapter, lifecycles, APIs, durability |
| [docs/rnd-plan.md](docs/rnd-plan.md) | How the research rounds were run |
| [CLAUDE.md](CLAUDE.md) | How agents and Claude sessions work here: machines, repos, rules |

### Research ([docs/research/](docs/research/))

| Report | Subject |
|---|---|
| [spike-phase1](docs/research/spike-phase1.md) | **Infinigen on the Thor, measured**: the bpy build, Hello Room/World, CPU vs GPU, walls hit, phase 2 |
| [v2-thor-experiment](docs/research/v2-thor-experiment.md) | **The engine confirmed**: Infinigen 2.0 + procfunc on the Thor, tracer on |
| [ig2-procfunc](docs/research/ig2-procfunc.md) | Infinigen 1.x vs 2.0 and procfunc: the engine decision |
| [trellis-spike](docs/research/trellis-spike.md) | TRELLIS.2 on the Thor: works, clean licence, BF16 not FP8, CPU-bound mesh tail |
| [warm-scene](docs/research/warm-scene.md) | The warm scene server spike: the win is builder wait and crash recovery |
| [ux-day](docs/research/ux-day.md) | A day and a night with your builders: the three clocks, ten moments that must feel great, the screens |
| [ux-trust](docs/research/ux-trust.md) | Trust, taste and growing together; Magnus (a kid co-designer); failure modes and the rules against them |
| [rev-ux](docs/research/rev-ux.md) | Cross-review of the two, against the technology: the merged experience spine |
| [gaps](docs/research/gaps.md) | The first evening, the Thor busy or off, Magnus's first session, honest versions of promises we can't keep yet |
| [res-3d](docs/research/res-3d.md) | 3D generators on the Thor (TRELLIS.2 first); licences of code and weights |
| [res-cad](docs/research/res-cad.md) | CadQuery/build123d, OpenUSD, textures, motion, music, the overnight scheduler |
| [rev-tech](docs/research/rev-tech.md) | Cross-review: one dependency ledger, one licence register, the environment plan, the first five spikes |
| [split](docs/research/split.md) | How to shift the processing burden across the Thor, the laptop, the cloud and the Orin |
| [rev-spec](docs/research/rev-spec.md) | The core spec checked against the experience and the compute plan |
| [bakeoff](docs/research/bakeoff.md) | The engineer bake-off: Claude Code, zcode, mcode, aider, OpenHands, Goose |
| [landscape](docs/research/landscape.md) | Who else builds agentic worlds, and where we're different |
| [cogeco](docs/research/cogeco.md) | Fit study: cognitive-ecology (our crew's project). We vendor its WHY kernel |
| [forks](docs/research/forks.md) | The Infinigen fork network: no GPU or Jetson work anywhere, so ours is new; a few unmerged fixes |
| [maquette](docs/research/maquette.md) | tangos302's maquette prototype of a builders layer: take the ideas, not the code |
| [solidcraft](docs/research/solidcraft.md) | SolidCraft (open-source Rust CAD with MCP): borrow its tool surface and oracle checks |
| [casey-ideas-fromgoogle5](docs/research/casey-ideas-fromgoogle5.md) | The owner's collected ideas on shifting the burden (triaged in `split`) |

### The lab ([docs/lab/](docs/lab/))

| Experiment | Verdict |
|---|---|
| [Unified memory](docs/lab/exp-unified-memory.md) | **Breakthrough.** One 4 GB buffer is shared by NumPy, PyTorch and a CUDA kernel with no copy; GPU reads of CPU memory run at 100.9 GB/s |
| [Warp terrain port](docs/lab/exp-warp-terrain-port.md) | **Breakthrough.** Infinigen's `mountains` in Warp is bit-identical and 44–56× faster than the CPU path, 6× faster than its CUDA kernel |
| [Warp terrain](docs/lab/exp-warp-terrain.md) | Useful. A restructured CPU algorithm beat the GPU: rethink the algorithm, don't just move it |
| [FP8/FP4 tensor cores](docs/lab/exp-fp8-tensorcores.md) | FP8 useful (1.6–1.7× faster, half the memory); **FP4 a measured no** on this stack |
| [NVMe bandwidth](docs/lab/exp-nvme-bandwidth.md) | Useful. Load speed decides the hot/warm/cold scheduler's shape |
| [Critic PNG round-trip](docs/lab/exp-critic-png-roundtrip.md) | Useful. The critic should read the render buffer, not a PNG |
| [Solver scoring](docs/lab/exp-solver-scoring.md) | Useful. Python vs numba vs Warp vs restructured CPU for the layout solver |
| [Engines on the Thor](docs/lab/exp-engines.md) | PVA v3, NVENC/NVDEC and INA power rails are real; **no NVDLA, no OFA** |
| [Batched shared model](docs/lab/exp-batched-shared-model.md) | FP8 is 3.0× on a GEMM chain, 1.3× end to end (launch-bound); batching is free only when weights dominate |
| [Joules per fixed point](docs/lab/exp-joules-per-fixed-point.md) | Warm starts converge in 2–3 iterations (6 cold), 1.39 J each; the critic belongs on the GPU |
| [Adapters](docs/lab/exp-adapters.md) | Skill adapters are cheap to hold (60 MiB) but slow to switch (73–119 ms) |
| [CUDA Graphs](docs/lab/exp-cuda-graphs-nvenc.md) · [NVENC round-trip](docs/lab/exp-nvenc-roundtrip.md) | Graphs pay; NVENC is free but not a warm-start store |
| [IDEAS.md](docs/lab/IDEAS.md) | The mined candidates, what's next, and the killed-by-fact list |

## The code

Branches are pushed as the agents work and reviewed before they merge into
`main`. Each package has its own README.

| Branch | What | State |
|---|---|---|
| `core-api` | Audit ledger (SQLite, append-only), FastAPI service, SSE event stream, work orders | merged into main, ~177 tests |
| `core-recipe` | Recipe store: versions, branches, typed edits, recipe hash, constraint checks | merged into main, 162 tests |
| `vocab` | Three vocabulary words, the door, the confidence gate, sealed predictions, the Prop-maker loop | merged into main, 111 tests |
| `why-kernel` | The WHY justification kernel (vendored, MIT), attached to assets, words, branches and work orders | merged into main, 35 tests |
| `night-runner` | The night: queue, rails, heartbeat and lease, resume after reboot, the **iterator loop**, the morning report | merged into main, ~197 tests |
| `cold-start` | New builders ask before they act (the switch to acting at two observations); the critic's calibration set | merged into main, 63 tests |
| `usd-backbone` | Recipe → layered USD, build123d → STEP → GLB, provenance, byte-identical re-emission | merged into main, 79 tests |
| `m1-acceptance` + `m1-real` | The M1 session as an automated test, now on the integrated core: evening → night → morning, 30 steps | **merged: 30/30, one ledger** |
| `integrate-core` | All of the above merged into one core, stand-ins replaced, one green suite | **merged: 842 tests** |
| `melt-week` | A seven-night simulated week: the ask-to-act switch, attention cost falling | **merged: 105/105 on the integrated core** |
| `m1-real` | Both acceptance suites rewired onto the integrated core (real spine, real recipe store) | **merged: 30/30 + 105/105, 842→893 tests** |
| `engine-adapter` | The engine seam: `Engine` protocol, the fake, the v1/v2 adapter skeletons, the gate's engine rungs, `open_engine` configuration | **merged: 893 tests** |
| `render-rung` | **The render rung, real**: the v2 venv behind the seam (`core.engine.venv2`), the M1 session's `-m engine` run renders Infinigen 2.0 on the Thor's GPU with artifact hashes, provenance and licence rows in the ledger | **this branch** |
| `plan-v2` | Plan draft 2 and the owner's decision sheet | merged |

| `engine-adapter` | One seam between the recipe and the engine: protocol, fake, Infinigen 1.x and 2.0 adapters | **merged** |
| `render-rung` | The M1 render steps render for real (Infinigen 2.0, Cycles on the Thor GPU) | **merged** |
| `scene-server` | The resident engine: builder wait 4.7× lower, exact crash recovery | **merged** |
| `propmaker-batch` | TRELLIS.2 behind the scheduler; the first real mini-night: 3 props × 3 seeds in 24 min 44 s ([record](docs/lab/mini-night.md)) | **merged** |

### In flight

- **Engine round 2**: whole scenes traceable, a byte-stable recipe graph, Warp terrain as a 2.0 stage.
- **Lab round 4** and **the critic's calibration set** on real sweep renders (queued for a provider quota).
- **An overnight Infinigen scene sweep** on the Thor (8 scene types × 6 seeds) for the scheduler's timings and the calibration set.

## Machines

| Machine | Role |
|---|---|
| Jetson AGX Thor (aarch64, 14 cores, 122 GB unified memory, Blackwell GPU sm_110, CUDA 13.2; no RT cores) | All generation, rendering, models and the builders |
| ASUS ProArt laptop (Ryzen AI 9 HX 370, RTX 4050 6 GB, 31 GB) | The seat: in-world view, fast previews, the human |
| Jetson Orin (8 GB) | Spare |

## Licence

Not yet chosen; the owner decides — it is item **B4** on the
[decision sheet](docs/decisions-for-casey.md), with the recommendation
**BSD-3-Clause** (the licence the whole corpus already uses, and the one
`infinigen-thor` inherits from Princeton). Third-party code keeps its own
licence: the vendored WHY kernel is MIT (`core/why/VENDORED.md`), and
Infinigen is BSD-3.
