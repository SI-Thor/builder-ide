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

> Status (2026-10-31): **research complete, first code in progress.** Six R&D
> reports, three cross-reviews, a synthesized understanding and plan, a core
> service spec (v2), and two lab rounds are in `docs/`. The core is being built
> on branches (below). Nothing is usable end to end yet; milestone M1 is "one
> evening, one night, one morning, one builder, one room".

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
- **Thor-native, not ported.** Everything we build on is open source, and we
  rewrite it for the Thor's chips: unified memory, FP8 tensor cores, its
  hardware engines, its 14 cores. Ideas become measured experiments in days.

## Read this first

| Document | What it is |
|---|---|
| [docs/vision.md](docs/vision.md) | The why, the three layers, the work order, calling the computer in-game, making characters and objects |
| [docs/understanding.md](docs/understanding.md) | **The whole picture in one place.** Everything known, by subject, every fact cited; what's decided, believed and unknown; a glossary |
| [docs/plan.md](docs/plan.md) | **The plan, experience first.** Milestones M0–M5 that each deliver something you live through, the first three weeks in detail, decisions for the owner |
| [docs/design/core-spec.md](docs/design/core-spec.md) | The core service, specified (v2): data model, engineer adapter, lifecycles, APIs, durability |
| [CLAUDE.md](CLAUDE.md) | How agents and Claude sessions work here: machines, repos, rules |

### Research ([docs/research/](docs/research/))

| Report | Subject |
|---|---|
| [ux-day](docs/research/ux-day.md) | A day and a night with your builders: the three clocks, ten moments that must feel great, the screens |
| [ux-trust](docs/research/ux-trust.md) | Trust, taste and growing together; Magnus (a kid co-designer); failure modes and the rules against them |
| [rev-ux](docs/research/rev-ux.md) | Cross-review of the two, against the technology: the merged experience spine |
| [gaps](docs/research/gaps.md) | The first evening, the Thor busy or off, Magnus's first session, honest versions of promises we can't keep yet |
| [res-3d](docs/research/res-3d.md) | 3D generators on the Thor (TRELLIS.2 first), licences of code and weights |
| [res-cad](docs/research/res-cad.md) | CadQuery/build123d, OpenUSD, textures, motion, music, the overnight scheduler |
| [rev-tech](docs/research/rev-tech.md) | Cross-review: one dependency ledger, one licence register, the environment plan, the first five spikes |
| [split](docs/research/split.md) | How to shift the processing burden across the Thor, the laptop, the cloud and the Orin |
| [rev-spec](docs/research/rev-spec.md) | The core spec checked against the experience and the compute plan |
| [bakeoff](docs/research/bakeoff.md) | The engineer bake-off: Claude Code, zcode, mcode, aider, OpenHands, Goose |
| [landscape](docs/research/landscape.md) | Who else builds agentic worlds, and where we're different |
| [cogeco](docs/research/cogeco.md) | Fit study: cognitive-ecology (our crew's project); we vendor its WHY kernel |
| [casey-ideas-fromgoogle5](docs/research/casey-ideas-fromgoogle5.md) | The owner's collected ideas on shifting the burden (triaged in `split`) |

### The lab ([docs/lab/](docs/lab/))

Small experiments that mine for Thor-native breakthroughs. Wins and failures are
both kept.

| Experiment | Verdict |
|---|---|
| [Unified memory](docs/lab/exp-unified-memory.md) | **Breakthrough.** One 4 GB buffer is shared by NumPy, PyTorch and a CUDA kernel with no copy. GPU reads of CPU memory run at 100.9 GB/s |
| [NVIDIA Warp terrain](docs/lab/exp-warp-terrain.md) | **Useful.** A 4096² heightfield takes 4.6 ms on the GPU, but a restructured CPU algorithm beat the GPU. Rethink the algorithm; don't just move it |
| [FP8/FP4 tensor cores](docs/lab/exp-fp8-tensorcores.md) | **FP8 useful** (1.6–1.7× faster, half the memory); **FP4 a measured no** on this stack |
| [IDEAS.md](docs/lab/IDEAS.md) | The mined candidates, what's next, and the killed-by-fact list |

## The code (in progress)

Branches are pushed as the agents work, and reviewed before they merge into
`main`.

| Branch | What | State |
|---|---|---|
| `core-api` | Audit ledger (SQLite, append-only), FastAPI service, SSE event stream, work orders | in progress |
| `core-recipe` | Recipe store: versions, branches, typed edits, recipe hash, constraint checks | done, 162 tests |
| `vocab` | Three vocabulary words, the door, the confidence gate, sealed predictions, the Prop-maker loop | done, 111 tests |
| `why-kernel` | The WHY justification kernel (vendored from cognitive-ecology), attached to assets, words, branches, work orders | done, 35 tests |
| `night-runner` | The night: task queue, budget rails, heartbeat, resume after reboot, the morning report page | in progress |
| `usd-backbone` | Recipe → layered USD, build123d → STEP → GLB, provenance, byte-identical re-emission | in progress |
| `cold-start` | New builders ask before they act; the critic's calibration set | in progress |

The world engine is a separate repo: **[SI-Thor/infinigen-thor](https://github.com/SI-Thor/infinigen-thor)**,
a fork of Princeton's Infinigen (BSD-3) being ported to the Thor. Branch
`thor-spike` builds Blender 4.2's Python module for aarch64; Infinigen's own
install guide offers no Linux ARM64 build.

## Machines

| Machine | Role |
|---|---|
| Jetson AGX Thor (aarch64, 14 cores, 122 GB unified memory, Blackwell GPU, CUDA 13.2) | All generation, rendering, models and the builders |
| ASUS ProArt laptop (Ryzen AI 9 HX 370, RTX 4050 6 GB, 31 GB) | The seat: in-world view, fast previews, the human |
| Jetson Orin (8 GB) | Spare |

## Licence

Not yet chosen; the owner decides. Third-party code keeps its own licence: the
vendored WHY kernel is MIT (see `core/why/VENDORED.md` on its branch), and
Infinigen is BSD-3.
