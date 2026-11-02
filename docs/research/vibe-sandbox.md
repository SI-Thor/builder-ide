# vibe-sandbox — Casey's spec against our stack, the claims table, the asks, the v2 plan

**Lane opened:** 2026-11-01 · **Worktree:** `~/lm-wt/vibe-sandbox` (branch `vibe-sandbox`) · **Spec:**
`SPEC.md` (Casey's agent's "End-to-End Vibecoding & Autonomous Playtesting Sandbox", condensed by
the director) · **Push:** never.

The spec is treated as a set of claims. §1 is the reality check (every row verified on 2026-11-01
unless a later date is printed beside it). §2 is the experiment:
`docs/lab/exp-vibe-sandbox.md` holds the build and its numbers. §3 is the asks for Casey, §4 the
ranked v2 plan.

---

## 1. The claims table

Verified on the ProArt (`Get-NetAdapter -Physical` under Windows, `ip -br link` under WSL) and on
the Thor (`ethtool`, `systemctl get-default`, `docker --version`, `/usr/bin/blender --version`,
`gh api repos/ramenvr/autopilot`, and the venv/listing checks named in each row). Read-only
throughout; nothing was installed for §1.

| # | the spec's claim | verdict | what is true, and the replace-with |
|---|---|---|---|
| 1 | Direct Cat6A ProArt↔Thor link, static IPs `10.10.10.1/.2` | **wrong (today)** | The ProArt PX13 HN7306WU has **no wired Ethernet adapter** — `Get-NetAdapter -Physical` shows one MediaTek Wi-Fi 7 card (Up, 1.2 Gbps) and nothing else. The Thor's four 10 GbE ports (`mgbe0_0`–`mgbe3_0`) all report `Link detected: no`. The link today is Wi-Fi. Fabric needs a **USB4 10GbE adapter + Cat6A** (ask, §3) and static IPs are a Thor system change (ask, §3). |
| 2 | `systemctl set-default multi-user.target` on the Thor (headless) | **holds as a request; not ours to do** | The Thor boots `graphical.target` (verified). Changing the default target is a system change our lane rules forbid; listed as an ask (§3). |
| 3 | Monitor PbP (ProArt DP, Thor HDMI), input-leap KVM, VS Code Remote-SSH | **partial** | Hardware/UX asks (§3). input-leap was surveyed in `docs/research/ingame-building.md` phase 1b. VS Code Remote-SSH already works (it is how the seats run). |
| 4 | Phase-2 storage: Thor NVMe exported by Samba, `[gamedev_share]` **writable, `guest ok`** | **not acceptable** | Guest-writable Samba breaks the lane's standing rule. Replace-with for v1: the inbox/outbox are directories on the Thor and files cross by **scp/rsync over ssh** (works today over Wi-Fi). An authenticated share is the v2 option, not a guest one. |
| 5 | A watchdog daemon on the share catches `*.json` with `action=generate_room`, runs `docker exec blender_worker blender …` | **replace-with** | The *shape* holds (inbox → watcher → pipeline) and is what v1 builds, with the Python `watchdog` package watching a local inbox dir. But no Docker Blender worker: the Thor's **system Blender 4.0.2** (`/usr/bin/blender`, apt aarch64) runs `--background --python` directly; a containerised Blender image is a download we do not need. Docker itself is present (29.9.2, active) for anything that genuinely needs it. |
| 6 | Phase 3: generation by "**vLLM** or multi-view Gaussian models like LGM" → raw `.gltf` | **wrong (vLLM); unapproved (LGM)** | vLLM is an LLM inference server — it serves token streams, it does not generate meshes. LGM is real but is not in our approved-generator set (CLAUDE.md 2026-10-31). Replace-with, cheapest first: **build123d** (CPU, deterministic, already proven in `physag-lite`/`cad-bakeoff`) and **TRELLIS.2 under a ComfyUI lease** (text→SDXL→mesh, proven end to end in `docs/lab/physag-lite`, GPU minutes under `thor-admit`). v1 uses build123d; the TRELLIS seam is the same generator interface. |
| 7 | ComfyUI API → 4K tileable normal/roughness/albedo | **holds (under a lease)** | ComfyUI is on the Thor at `~/lm-wt/trellis/ComfyUI` (approved 2026-10-31); SDXL textures were generated through it in `physag-lite`. No resident server: it starts under a lease and stops with it (`ff62313` made the lease own the render). |
| 8 | Blender: import, **Decimate ratio 0.35**, pack PBR, export `GLTF_EMBEDDED` | **holds, with two edits** | Blender 4.0.2 decimates and exports glTF fine. Edits: (a) v1 exports **GLB** (one binary file, what three.js hot-load wants) rather than `GLTF_EMBEDDED`; (b) decimation runs **only when a mesh is over budget** — `docs/lab/open3d-critic` adopted quadric LOD for that, and a blanket 0.35 on already-low-poly build123d output would spend time to make geometry worse. The spec's `bpy==4.2.0` is the *Infinigen* pin; a bpy-capable venv exists for the critic probe (`~/src/infinigen-thor/.venv`), and the system Blender 4.0.2 covers export. |
| 9 | "bone transformations from local skeletal generation" | **no evidence** | Nothing in our stack generates skeletons, and the spec names no tool. Parked for v2; rooms of rigid props do not need it. |
| 10 | Phase 4: the engine polls `Z:\` for `final_delivery_*.gltf`, loads via glTFRuntime, broadcasts `OnRoomGenerationComplete` | **replace-with for v1** | The Windows engine is explicitly later (lane brief). v1 hot-loads into a **three.js viewer** on the Thor — the agent-world viewer's stack (three + a Node server) — which polls an outbox `manifest.json` and GLTF-loads a new `room_id` without a restart. When the Windows/Godot client comes, Godot 4 imports glTF natively (`ingame-building` survey) and the outbox→poll→load→event seam is the same. |
| 11 | Phase 5: "**Aura Autopilot**" (`ramenvr/autopilot`, "Python/C++ API") runs on the Thor; streams the viewport as H.264 RTP/UDP; a VLM agent sends virtual inputs back | **exists; wrong about the Thor; not zero-cloud** | The repo is real (verified read-only, `gh api`, 2026-11-01): `ramenvr/autopilot`, **Apache-2.0**, Python, 626 stars / 43 forks, created 2026-10-30, last push 2026-11-01, homepage tryaura.dev/autopilot, "Play any game". But it is an **editor plugin for UE5 (5.4–5.8), Unity 6 and Godot 4.7+ on Windows and macOS**, with the agent service reached through an **Aura account or BYOK cloud API keys**. Nothing in the README or tree claims headless Linux or aarch64, and "runs on the Thor" is therefore wrong as written; "zero-cloud" is wrong for its hosted path. Replace-with: v1's playtest agent is **ours** — Playwright in headless Chromium on the Thor (aarch64 Chromium is installed for it, resolving the survey's open item), walking a capsule through the room in the same process that renders it, so no video stream is needed at all. Autopilot's *pattern* (watch frames, send inputs, learn a level) is the v2 candidate, on the ProArt Windows side with its Godot plugin, under our cloud keys. |
| 12 | GStreamer `d3d11screencapturesrc ! nvenc ! rtph264pay ! udpsink` viewport stream | **untested; v2** | No ProArt-side capture pipeline was measured (our nvenc round-trips were Thor-side, `docs/lab/exp-nvenc-roundtrip.md`). The privacy rule holds regardless: an **agent's view of a game build** may be streamed and held in memory; **a human session's pixels never are** (`docs/design/screen-watcher.md`). v1 needs no stream — the tester sits where the renderer sits. |
| 13 | Celery/Redis task worker, nvidia-docker containers | **over-built for v1** | Docker 29.9.2 is installed and active (verified). Celery/Redis are not installed and v1 does not need them: one `watchdog` watcher and one runner per prompt is the whole queue. Revisit only if rooms arrive faster than one box can bake them. |
| 14 | (lane brief) the assets to reuse: TRELLIS, SceneBloom, build123d props, the critic (+Open3D self-intersection), physag, three.js viewers, agent-world, posestream, screen-watcher.md, vibecode-in-world.md, ingame-building.md | **all present** | TRELLIS `~/lm-wt/trellis` (ComfyUI + models); SceneBloom `~/lm-wt/scenebloom-eval`; build123d importable in 13 existing venvs (uv-hardlinked); the critic `core/critic` (hybrid holds the band at 696 ms/verdict, `CALIBRATION.md`); Open3D **0.20.0** (the only cp312 aarch64 wheel) in `~/lm-wt/open3d-critic/.venv` and `~/lm-wt/critic-selfx/.venv` — the self-intersection lane landed as `open3d-critic` (`f69557a`: 34 of 38 reference meshes self-intersect, invisible to today's critic); physag `~/lm-wt/physag-lite`; three.js in the agent-world viewer (`viewer/node_modules/three` 0.128.0 via prismarine-viewer); agent-world live; posestream `~/lm-wt/posestream-net`; the three docs named are in `docs/design/` and `docs/research/`. |

**Rules that bind the spec** (lane brief; where the spec crosses them it is noted above): no
guest-writable Samba (row 4); no system changes on the Thor — static IPs, boot target, share config
are asks, not edits (rows 1–2, 4); no resident LLMs — VLM QA under a `thor-admit serve` lease or in
the cloud (row 11); no human-session pixels, ever (row 12); heavy steps under `thor-admit` with
honest peaks (§2).

---

## 2. The thin slice

Built and measured 2026-11-01/02: **`docs/lab/exp-vibe-sandbox.md`** holds the pipeline, the
per-stage latencies (≈ 9.6 s per attempt, four `study`-tier leases, load1 14–18 on the Thor), the
pass rate (5 of 7 rooms; the two failures are seeded faults v1 has no repair for), and the catch
matrix — the QA agent catches every placement/navigation fault (floating, door-blocking,
sealed-off floor), the critic every within-object fault (family-scale outlier, self-intersecting
shells), and neither fires on a clean room. Code: `tools/vibe-sandbox/` (README = run book);
the watcher seam is proven end to end (a prompt dropped in the inbox ran to a commit on its own).

## 3. The asks for Casey

Ordered by what they unlock, with the measured cost of not having each today.

1. **A USB4 10GbE adapter for the ProArt + Cat6A, and static IPs `10.10.10.1/.2`** (claims rows 1).
   The v1 numbers are unaffected — the whole pipeline runs Thor-local, and a room's artifacts are
   60.8 KB. What suffers on Wi-Fi is everything v2 wants: TRELLIS texture payloads, 4K PBR sets,
   any H.264 viewport stream, and the Windows client's latency. Static IPs are a Thor system
   change, so they are yours to approve, not ours to make.
2. **Thor headless (`systemctl set-default multi-user.target`)** (row 2). A system change; the box
   ran the whole batch at `graphical.target` with 107.6 GB free, so nothing in v1 needs it. It
   becomes worth asking when the box's memory is contended by the desktop session.
3. **An authenticated share, if the Windows engine wants a mounted path** (row 4). v1 crosses by
   ssh/rsync and needs nothing; guest-writable Samba stays refused on rule. If the v2 client
   prefers a mount, an authenticated (non-guest) export is the shape we would ask for.
4. **input-leap KVM + the PbP monitor arrangement** (row 3): the human seat for a two-box loop.
   Hardware/UX, no measured cost either way; surveyed in `docs/research/ingame-building.md` 1b.
5. **A decision on Aura Autopilot** (row 11): the v2 candidate for the Windows engine's tester
   (Godot 4.7+ plugin, Apache-2.0, Aura account or BYOK cloud keys). It needs your OK twice — a
   third-party plugin inside the engine, and a cloud service on the agent path — before anything
   is installed.

## 4. The ranked v2 plan

Ranked by unlock per unit of work; each is a day-ish, not a phase.

1. **Walk the shipped triangles.** The QA's collision model is the authored `scene.json`; a mesh
   that disagreed with its manifest would pass. A raycast/capsule query over the loaded GLB in the
   playtest page (or trimesh in the report step) closes the loop's one self-inflicted blind spot
   and lets the playtest catch prop–prop interpenetration too.
2. **The TRELLIS arm of the generator.** Same seam, real meshes: text→SDXL→TRELLIS.2 under a
   ComfyUI lease (the path `physag-lite` proved), spec-driven placement on top. Organic props are
   the biggest visual jump per hour of work; the measure to add is GPU-minutes per room beside the
   CPU wall the v1 batch already logs.
3. **The Windows/Godot client (the spec's phase 4).** It polls the outbox manifest exactly as the
   three.js viewer does — the manifest is already the wire format — imports the GLB at runtime and
   raises the completion event the spec names. This is where the ProArt re-enters the loop.
4. **A VLM judge stage.** The critic's scripted checks see geometry, not look: renders of the room
   scored by a leased VLM (`thor-admit serve` or DeepInfra cloud) for occlusion, style drift,
   "does this read as a room". Agent renders only — the no-human-pixels rule is unchanged.
5. **H.264 viewport stream + the Autopilot pattern (phase 5).** After 3: the client streams its
   own game viewport (never a human session), an agent sends inputs back. Needs ask 1 (the wire)
   and ask 5 (the Autopilot OK), and our Playwright harness is the local fallback that already
   works.
6. **Free-text prompts (the "vibecode" seam).** A cloud LLM writes the spec JSON from a sentence,
   the schema validates it, and everything downstream is unchanged — recipes stay the source of
   truth, which is the repo's standing rule.
