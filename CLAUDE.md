# CLAUDE.md — builder-ide (and infinigen-thor)

The project Casey chose on 2026-10-30: **a game and simulation IDE whose
builders are avatars.** You and a small team of agent builders shape a world
together; you can leave them working on a project in-world overnight and come
back to hours of work done; the builders grow with you (your taste, their
skills). The world engine is **infinigen-thor**: a Thor-native port of
Princeton's Infinigen (procedural, photoreal worlds and rooms; BSD-3),
improved as we go, and designed so the generative models it uses (image gen,
image-to-3D, vision critic, planners) swap in and out by what runs well on the
Thor.

Read `docs/vision.md` for the why and the phases. This file is how a session
works.

## Machines

| Machine | Role | Access |
|---|---|---|
| Thor `192.168.0.78` (Jetson AGX Thor, aarch64, 122 GB unified, Blackwell GPU, CUDA 13.2) | **the whole box belongs to this project**: generation, rendering, model residency, the builders | `ssh thor-lan`; full access and sole use granted by Casey |
| ProArt (this laptop; Windows 11 + WSL, RTX 4050) | thin client with real muscle: views the world, fast previews, the human's seat | local |
| Orin `192.168.0.50` (8 GB) | spare; ask before using | `ssh orin-lan` |

- On 2026-10-30 skald (voice) and last-mile's model services were stopped and
  **disabled at boot** to give the Thor to this project. The undo lines are in
  the Thor's `~/last-mile-ops.md`. Log every service or system change there,
  with its undo.
- The Thor's disk: 343 GB free on NVMe after last-mile's build caches were
  cleared. The 1.9 TB external drive `/media/caseydigennaro/TOSHIBA EXT` is the
  cold shelf (models and big caches); mount it with sudo if it is missing after
  a reboot.

## Repositories

- **SI-Thor/infinigen-thor** (github.com/SI-Thor/infinigen-thor, public): a fork
  of princeton-vl/infinigen, BSD-3 with attribution kept. The Thor's working
  tree is `~/src/infinigen-thor` (remote `upstream` = Princeton); the spike's
  branch is `thor-spike`.
- **SI-Thor/builder-ide** (github.com/SI-Thor/builder-ide, public): this repo.
  The canonical `main` is the ProArt's `~/projects/builder-ide`; the Thor's
  `~/src/builder-ide` holds the seats' branches and worktrees.
- **Push often** (Casey, 2026-10-30): `~/lm-ops/push-all.sh` on the ProArt
  pushes `main` plus every seat branch from the Thor (the Thor's GitHub keyring
  locks after a reboot, so pushes go through the ProArt). Seat branches are
  pushed as they are; review comes before a merge to `main`.

## How work is done

- **Claude directs, seats implement.** zcode and mcode run briefs in tmux on the
  Thor (session `last-mile`, scripts in `~/lm-ops` on the ProArt: `launch-z.sh`,
  `launch-m.sh`, `relaunch-z.sh`, `watch-all.sh`). Claude reviews, commits with
  full messages (body = why), and pushes. Seats never push.
- **Store recipes, not meshes.** A project's source of truth is its recipe:
  generators, parameters, constraints and seeds. Renders and meshes are caches.
  A night's work is a diffable recipe history: undo, branch and replay are free.
- **Builders change recipes through a closed, typed vocabulary**, never by
  writing Blender code, and they **predict before they render** (the Vibe
  Dictionary pattern proven in last-mile: sealed prediction, test, verdict,
  undo).
- **Third-party generators are approved** (Casey, 2026-10-31): the
  open-source generators the research picked may be installed and run on the
  Thor, each in its own venv, with its licence checked first: ComfyUI +
  TRELLIS.2 first, then TripoSR, build123d/CadQuery, ACE-Step and MoMask.
  Infinigen was approved before. Also approved (2026-10-31): a LAN-only agent
  world on the Thor with Minecraft Java (Paper; Casey accepted Mojang's EULA),
  mineflayer and prismarine-viewer, and Luanti; localai-org/motion-bricks.cpp
  (NVIDIA MotionBricks in GGML, Apache-2.0; weights licence checked first) to
  evaluate and then rebuild Thor-native under SI-Thor; speridlabs/idol-sdk (image
  to 3D Gaussians, Apache-2.0 code; gated DINOv3 and FLUX.2-dev weights via
  Casey's Hugging Face access; outputs marked non-commercial); Tinaliu0123/
  scenebloom (Apache-2.0 code) with its VLM swapped to a cloud vision model we
  already use (no OpenRouter), or locally as a scoped B2 exception;
  KBRASK/UniAction with Wan2.2-I2V-A14B (Apache-2.0), after the current wave.
  Paradee-8M (Apache-2.0 TTS) for the first mile.
  Also our crew's
  quilt-pincher, KTX-Software (`toktx`), and the open-source builds the seats
  listed in their reports. Any other third-party project from GitHub still
  needs his OK.
- **No LLMs on the Thor** (Casey, B2, 2026-10-31). Language comes from cloud
  subscriptions (z.ai, MiniMax, Claude, others), each a parameter priced per
  call. The Thor is for motion as virtual robotics, visual assets, world models
  and engines, and many small decision models. Cloud LLMs write scripts that
  become the tiles local decision models choose between; every play's outcome
  is recorded, win or lose, so the decision models learn over time. See
  `docs/vision.md` §"What the Thor is for".
- **Move fast; permissive by default** (Casey, A1/A2, 2026-10-31). We are in
  development for a long while: no gates on who may write what. Every row
  still records its author. Magnus may do everything (spoken input, full
  apply); Casey is with him at runtime. No transcripts or audio are stored.
- **MIT licence** (B4) for this repo; third-party code keeps its own.
- **Documentation explains mechanisms; it never claims** (Casey, 2026-10-31). Never write "breakthrough", "ah-ha", "game-changer" or similar in READMEs and docs, lab verdict lines included. Let engineers reach that understanding themselves. For each result, explain:
  1. the hardware fact;
  2. why the old path could not use it;
  3. what the new path does differently;
  4. the measured numbers, with the box state beside them;
  5. what it makes possible, built up to the applications.
- **Keep the READMEs current** (Casey, 2026-10-31). Every package or directory
  a seat creates gets a README (what it is, how to run its tests, what it
  stubs, how it connects to the rest), and every change updates it. The top
  README's status, document map and branch table are refreshed by the
  **director only**, when a report lands or a branch merges. Seats must not
  edit the top README on their branches (parallel edits conflict at every
  merge); they put their status in their package README and summary.
- **Measure, with the box's state beside every number.** "Works" carries its
  proof: a render, a timing, a test.
- **Licences are a checked list**, especially for models: some image models are
  non-commercial. See the Thor model inventory notes.
- **Thor-native rewrites are welcome, and finding what the hardware can really do is the point**
  (Casey, 2026-10-30). Everything here is open source, and we are pioneering
  new abilities and uses for the Thor: heavily rewrite any program (Infinigen,
  Blender stages, generators) to fit the Thor's specific chips. That means its
  unified memory, the Blackwell GPU and tensor cores (FP8/FP4), its hardware
  engines, and its 14 Neoverse cores. Don't settle for "make it run as it does
  on x86". Mine ideas by **running small experiments**: an
  idea becomes a measured result (or a measured no) within days, not a debate.
  Record every experiment, wins and failures alike, in `docs/lab/` with the
  numbers and how to reproduce them.

## Status (2026-10-30)

- Infinigen pins `bpy==4.2.0`; the Thor has Blender 4.0.2 (apt, aarch64), and
  Infinigen's install matrix has no Linux ARM64 column. Phase 1 is the
  feasibility spike: Blender 4.2 on aarch64 (prebuilt or source), Infinigen's
  Hello Room / Hello World on the Thor, and a Cycles render on its GPU, timed
  against the ProArt.

- **Seed-OSS-36B-Instruct** (Apache-2.0; Casey 2026-10-31): a scoped exception to no-LLMs-on-the-Thor. Our own NVFP4 conversion (thor-fp4), served only under a thor-admit lease, never resident: live during development cycles, and a practice-tier night drain that batches the ideation inbox other systems fill during the day.
- **NVIDIA SimReady assets** (dataset, CC-BY-4.0): read and sample freely with credit; do not mirror the full 77 GiB.
- **Audio8 TTS** (Edge0-AI, code + Realistic 0.6B + 0.1B ONNX INT8 Apache-2.0; the 0.1B PyTorch checkpoint is under a revenue-capped community licence; Casey 2026-10-31): the ProArt presentation voice. Clone **only from synthetic references** (never human recordings).
- **SolidCraft** (tangency-labs, MIT OR Apache-2.0; Casey 2026-11-01): build from source on the Thor in its own worktree (CLI only, no services) for `cad-bakeoff` against build123d. Cloud-written designs are JSON command scripts, validated against the registry before running.
- **Rust rewrites are in scope** (Casey 2026-11-01): "don't be afraid to rewrite programs into rust for custom fit". Rewrite the part we use, with credit and licence respected; keep it if it measures better (memory, latency, determinism) than the original. That is Rust for CPU-side code. **GPU kernels use whatever measures fastest per case** (CUDA C++/CUTLASS, PTX, Triton, Vulkan/HLSL compute for the ProArt and the browser), with Rust as host and orchestrator. **Large agent networks (the quilt): BEAM** (Gleam for new typed cells, Elixir or Erlang/OTP where they fit). Pick what is best, not what is easiest to write (`docs/design/language-fit.md`).
