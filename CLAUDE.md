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

- `~/src/infinigen-thor` on the Thor: a clone of princeton-vl/infinigen, with
  the remote renamed to `upstream`. It is to become **SI-Thor/infinigen-thor**,
  a fork that keeps the BSD-3 licence and attribution.
- `~/projects/builder-ide` on the ProArt (this repo): the IDE, the builders,
  the overnight loop and the client. It is to become **SI-Thor/builder-ide**.
- **Creating the public GitHub repos needs Casey's go-ahead**; until then they
  are local.

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
- **Measure, with the box's state beside every number.** "Works" carries its
  proof: a render, a timing, a test.
- **Licences are a checked list**, especially for models: some image models are
  non-commercial. See the Thor model inventory notes.
- **Thor-native rewrites are welcome, and breakthroughs are the point**
  (Casey, 2026-10-30). Everything here is open source, and we are pioneering
  new abilities and uses for the Thor: heavily rewrite any program (Infinigen,
  Blender stages, generators) to fit the Thor's specific chips. That means its
  unified memory, the Blackwell GPU and tensor cores (FP8/FP4), its hardware
  engines, and its 14 Neoverse cores. Don't settle for "make it run as it does
  on x86". Mine ideas for breakthroughs by **running small experiments**: an
  idea becomes a measured result (or a measured no) within days, not a debate.
  Record every experiment, wins and failures alike, in `docs/lab/` with the
  numbers and how to reproduce them.

## Status (2026-10-30)

- Infinigen pins `bpy==4.2.0`; the Thor has Blender 4.0.2 (apt, aarch64), and
  Infinigen's install matrix has no Linux ARM64 column. Phase 1 is the
  feasibility spike: Blender 4.2 on aarch64 (prebuilt or source), Infinigen's
  Hello Room / Hello World on the Thor, and a Cycles render on its GPU, timed
  against the ProArt.
