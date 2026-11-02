# NOTES — in-game building tools investigation (phase 1: read only)

Working dir: `/home/proart/lm-wt/ingame-building`. Brief: `BRIEF.md`. Claims to check: `list.md`.
Rules: `/home/proart/lm-wt/DOC-RULES.md`.

## 2026-11-01 16:56 AKST — session start, environment survey

**Tried:** read `BRIEF.md` (40 lines, no addendum or CONTINUE note present at the end — the file ends at
the Deliverables section; nothing was appended after it), `list.md`, `/home/proart/lm-wt/DOC-RULES.md`,
and the referenced `builder-ide/docs/research/theatre-open3d.md`.

**What happened (box state):**
- Host: `linux 6.18.54.1-microsoft-standard-WSL2`, Ubuntu 26.04.1 LTS, x86_64.
- CPU: AMD Ryzen AI 9 HX 370 w/ Radeon 890M, 24 threads (12C/24T).
- RAM: 15 GiB total, ~4.9 GiB available at survey time (10 GiB used, swap 7.0/8.0 GiB used) — the box is busy.
- GPU: NVIDIA GeForce RTX 4050 Laptop, **6141 MiB** VRAM, driver 616.92 (WSL2 passthrough of the ProArt laptop GPU).
- Disk: 1007 G total, 808 G free on `/dev/sdd`.
- Toolchain present: git 2.53.0, curl 8.18.0, python3 3.14.4, node v24.21.0, npm 11.19.0, rustc 1.99.1, gh 2.46.0.
  **Missing: dotnet, mono, cmake, go, jq.**
- Network: `github.com` HTTP 200, `api.github.com` HTTP 200, `git ls-remote` against the first repo succeeded.

**Decisions:**
- Research run workspace lives **inside** the project dir at `.research/20261101_165600_ingame-building/`.
  Writing to `/tmp` was refused by the permission gate (`HOST_CAPABILITY_UNAVAILABLE`), which also enforces
  the brief's "only modify files inside this directory" rule. No writes outside the project dir.
- No sub-agents (brief + research skill both forbid delegation) — all reading done in this session.
- The deep-research 5-step flow is used for *process discipline* (background → direction → plan → verify → write);
  the **file locations come from the brief** (`docs/ingame-building.md`, `RESULT.md`), which overrides the
  skill's default `final_turn_XXX.md` naming. The final answer is also mirrored to
  `.research/20261101_165600_ingame-building/final_turn_001.md` to keep that trace intact.
- Phase 1 rule honoured throughout: **no install, no build, no execution** of the eight tools' code.
  Cloning and reading only. GitHub API calls are read-only metadata queries.

## 2026-11-01 17:05 AKST — seven repos cloned, metadata pulled, code read

**Tried:** `git clone --depth 1` of all seven GitHub repos into `src/` (script: `.research/clone.sh`);
`gh api` metadata pass (script: `.research/api_meta.sh`, raw JSON in `.research/api/`,
table from `.research/summarize_api.py`). Then read the code of each repo.

**What happened (box state):** all seven clones succeeded, exit 0 each.

| repo | working tree | .git | tracked files |
|---|---|---|---|
| Torque3D | 699 M | 296 M | 20 714 |
| Open-World-Builder | 377 M | 261 M | 394 |
| topview-3d-builder | 112 M | 100 M | 929 |
| Vibe3DScene | 113 M | 61 M | 330 |
| Prowl | 34 M | 13 M | 1 018 |
| build-world | 1.1 M | 524 K | 84 |
| MEP-SANDBOX-ENGINE | 404 K | — | 10 |

**Findings that contradict `list.md` (the list's wording is a claim, not a fact):**

1. **MEP-SANDBOX-ENGINE is not a source repo.** It is 10 files: a 2 306-line marketing landing page
   (`index.html`, with Google AdSense, Microsoft Clarity, a Stripe "founder" button and an itch.io
   purchase at $5), docs in Markdown, and `MicahEngineStudio_v1.3.rar` (197 KB, RAR v5) which holds
   the ~22 Python files of the actual editor. GitHub's licence detector returns nothing; there is no
   LICENSE file. The landing page's FAQ *claims* "MIT License" and "free for personal and commercial
   use", but the repo does not carry one, and the product is sold. **Unlicensed: treat as closed.**
2. **Open-World-Builder's "integrate into your own runtime" is aspirational.**
   `core/Core/Plugin.cs` is an empty class (`public class Plugin { }`). The shipped app is a standalone
   FNA window (`src/Program.cs` → `App : Game`). It targets **net7.0 (EOL since 2024-11)** and needs
   `--recursive` submodules (FNA, ImGui.NET) that the depth-1 clone did not fetch.
3. **Prowl does not use ImGui.** `Prowl.Editor/Projects/Project.cs:266` has the package reference
   **commented out** (`<!-- <PackageReference Include="ImGui.NET" .../> -->`); the editor ships its own
   GUI stack in `Prowl.Editor/GUI`. But Prowl has the best agent surface of the eight: a CLI
   (`prowl status|command|eval|eval_file`) talking HTTP+JSON to a token-authenticated server inside
   the running editor, with commands `scene tree select go component get set menu asset script
   prefab material play input screenshot build graph api importer`.
4. **Topview's `.mcp.json` points at a hosted server** (`https://mcp-3d.topview.ai`, OAuth). The local
   path is the Python CLI `topview-3d-cli` (5 443 LOC of non-test Python) over a JSON project format.
5. **build-world is a skill pack + a cloud connector**, not an engine: `uvx thrixel-mcp@latest` talks to
   a paid SaaS (Thrixel "cubes"). The code worth having is the three.js part: a lockstep capture
   harness + Playwright tools (capture/contactsheet/imagediff/baseline/profile/smoke/mobilecheck).
6. **Vibe3DScene** is LangGraph + FastAPI + MCP + a Blender addon; 37 MCP tools; Blender 4.2.15 is
   downloaded by a script that only knows `linux-x86-64` and `macos-x64` — **no aarch64, no Windows**.
7. **Torque3D** is MIT, but `LICENSE.md` also carries a BSD-3 block for the "ray" IES profile
   generator. The `master` branch has been frozen since **2018-04-05** (3.10.1); live work is on
   `development` (last commit 2026-09-26). The in-game editor is C++ `Engine/source/gui/editor`
   (21 531 LOC) + `Engine/source/gui/worldEditor`, **plus** 79 262 lines of TorqueScript in the
   project template (`Templates/BaseGame/game/tools/`, 30+ sub-editors).

**Decided next:** gather our own stack context (builder-ide, agent-world, thor-world viewer,
last-mile/Bevy, B2) so the fit section is written against facts, then write
`docs/ingame-building.md` and `RESULT.md`.

## 2026-11-01 17:11 AKST — a second brief landed mid-run

**Tried:** `git add -A` for the first commit. It picked up two files that did not exist when
the session started at 16:54: `BRIEF-2.md` (3 175 bytes, written 17:11) and `list2.md`
(44 791 bytes, written 17:03).

**What happened:** Casey filed a **phase 1b** brief while the phase-1 reading was in flight:
seven more tools to investigate (NVIDIA ACE / Game Agent SDK / NVIGI, Godot headless on
ARM64, NVTX + Nsight + OpenTelemetry, watchdog + a headless Blender bake daemon,
input-leap, gRPC vs NATS vs websockets, ComfyUI + vLLM), the Thor 10 GbE claim, a
paragraph-per-idea mapping of `list2.md`'s rewind-and-supervision ideas onto our designs,
and a "rewind and supervision" table.

**Decided:** finish phase 1b on the same read-only terms rather than stopping, and fold it
into the same two documents. The phase-1 clones were already done, so the extra cost was
one more clone script and one more API pass.

## 2026-11-01 17:20 AKST — phase 1b clones, licences, and the hardware facts

**Tried:** `scripts/clone_repos_phase1b.sh` (15 repos at `--depth 1`), `gh api` searches for
the exact NVIDIA repositories, and read-only SSH to the Thor.

**What happened (box state):** 14 of 15 clones succeeded; `github.com/NVIDIA/nsight-systems`
does not exist (Nsight Systems is a binary download, not a source repo — found
`NVIDIA/nsight-python` Apache-2.0 and `NVIDIA/nsight` instead). Working trees for the phase-1b
set: godot 372 144 KB, vllm 160 372, grpc 113 756, comfyui 52 100, game-agent-sdk 21 548,
nvidia-ace 20 856, nvtx 20 312, opentelemetry-cpp 15 400, opentelemetry-python 12 540,
input-leap 9 444, nvigi-core 3 124, nvigi-godot-extension 2 192, watchdog 1 120, nvigi 44 KB.

**Licence findings per component (the point of A1):**
- `NVIDIA/game-agent-sdk` = **Apache-2.0** (claim holds), but its own
  `THIRD-PARTY-LICENSES.md` says the Apache licence "covers only NVIDIA-authored SDK code":
  12 vendored open-source components, NVIDIA proprietary redistributables under the CUDA
  EULA, and 4 bundled model artifacts under their own model-card terms.
  Requirements: **Windows 10/11, Ampere+, driver 570.65+, CUDA 12.8+**; the bundled SLM wants
  ~3.8 GB VRAM; build scripts are `setup.bat`/`build.bat` (Visual Studio). **No mention of
  Linux, aarch64 or Jetson anywhere in README or docs.** Last push 2026-06-16.
- `NVIDIA/ACE` = Apache-2.0 at file level, but the microservices come through an **NV AI
  Enterprise evaluation licence via NGC**; the README's own deployment table shows several
  technologies cloud-only. Last push 2025-06-26 (16 months stale).
- `NVIDIA-RTX/NVIGI` = **MIT** for the SDK, except the Microsoft DirectX DLLs and the NVIDIA
  models under the Community Model License. GitHub reports `NOASSERTION` because the licence
  file is prose — a detector false negative worth remembering.
- `NVIDIA-RTX/nvigi_godot_extension` = Apache-2.0, GDExtension with **CUDA/Vulkan/CPU GGML
  backends** — but its CMake presets are `windows-x64`, `windows-vs2022`, `windows-vs2026` only,
  and its compute-in-graphics feature is D3D12-only.
- `NVIDIA/NVTX` = Apache-2.0 **with LLVM Exceptions**; also `NOASSERTION` in the detector for
  the same reason as NVIGI.
- watchdog **Apache-2.0**; input-leap **GPL-2.0 + OpenSSL exception**; gRPC Apache-2.0;
  vLLM Apache-2.0; **ComfyUI GPL-3.0**.

**Thor, read-only over SSH:**
- Vulkan device: `NVIDIA Thor`, apiVersion 1.4.329, driver 595.78.0.0, one integrated GPU.
  This answers the brief's open "Vulkan?" — yes.
- Network: **four 10 GbE ports** (`mgbe0_0`..`mgbe3_0`, `Speed: 10000Mb/s`, autoneg on) and all
  four report **"Link detected: no"**. The only up link is `wlP1p1s0`, Realtek RTL8852CE 802.11ax
  at **2.4 GHz** (2462 MHz, −68 dBm), carrying the default route. `enP2p1s0` also down.
- **Nsight Systems 2025.6.3 is already installed** (`/usr/local/bin/nsys`, `nsys-ui`). No reports.
  No `libnvToolsExt` and no `nvidia-nvtx` pip package, so NVTX ranges have no consumer yet.
- Resident services: Minecraft Paper on 25565, prismarine-viewer on 8080, `sitka-distill`
  `serve-index` on 8100, `agent_world_reflex serve` on 8110 (localhost), plus 8788 and 2206.
  **No NATS server, no vLLM, no ComfyUI process, and `nvidia-smi` shows no compute apps** —
  the no-resident-LLM rule is currently being kept. `ollama` is installed but not serving.
- `box64` is installed, which matters for x86 binaries on aarch64.
- Xorg is the Thor's display (GDM, vt1), not Weston — so input-leap's default X11 path applies.
- `thor-admit/work/docs/MEMORY-RULE.md` is where the admission daemon's contract lives
  (leases, tiers, FIFO, the watchdog that terminates the largest lease).

**ProArt side:** `Get-NetAdapter -Physical` returns exactly one adapter, a MediaTek Wi-Fi 7
MT7925 at 1.2 Gbps. The "10 Gbps" entry is the WSL2 Hyper-V virtual adapter. **There is no
physical Ethernet port on the laptop**, so list2's proposed direct 10 GbE Cat6a cable cannot be
made as written; it needs a USB4 10GbE adapter plus a fixed address on `mgbe0_0`.

**Dead ends (do not retry):**
- Writing the run workspace to `/tmp` — refused by the permission gate
  (`HOST_CAPABILITY_UNAVAILABLE`), which also enforces "only modify files inside this directory".
- Listing `MicahEngineStudio_v1.3.rar`: no `unrar`, `7z`, `7za`, `bsdtar` or `unar` on this box,
  and `python3 -c "import rarfile"` fails. Worked around by reading the RAR v5 headers with
  `strings` — the file names are uncompressed in the headers, which was enough to enumerate
  ~22 Python modules and the Lua scripts.
- `gh api repos/NVIDIA/nsight-systems` → 404. Nsight Systems ships as a binary only.
- Godot 4.8 moved the export platform sources from `editor/export/` to `platform/<os>/export/`,
  so `editor_export_platform_linuxbsd.cpp` no longer exists at the 4.7 path.

**Decided next:** write `docs/ingame-building.md` (phase 1 + phase 1b), the rewind and
supervision table, `RESULT.md`, then commit.

## 2026-11-01 17:40 AKST — written, committed, and the remaining gaps

**What changed:** `docs/ingame-building.md` (72 926 bytes) with the per-tool sections,
comparison table, fit summary, phase-1b section, rewind-and-supervision map, the ranked
phase-2 shortlist with one-day test plans, the unverified list and 34 references;
`RESULT.md` (6 648 bytes); `NOTES.md` extended; five scripts committed so every number is
reproducible.

**Corrections filed in writing (DOC-RULES rule 5):**
- `builder-ide/docs/research/theatre-open3d.md` says topview is "Apache-2.0, TypeScript" —
  the code licence is right, but the agent-facing surface is **Python** (5 443 non-test lines)
  and the built-in characters and poses are **CC BY 4.0 © Topview**, not Apache-2.0. The old
  wording stays visible in the doc with the correction beside it.
- `list.md`'s four wrong descriptions are quoted and corrected rather than dropped.

**What is still open:** Prowl's linux-arm64 renderer natives (in NuGet, not the repo);
Torque3D's ARM64 Linux build (CMake detects it, CI does not exercise it); Playwright
Chromium on aarch64; MEP's source body (no RAR tools); Vibe3DScene's addon body (submodule).
All are stated as unverified in the report rather than assumed.

**Next:** phase 2 needs Casey's OK before anything is installed — the ranking in
`RESULT.md` is the request.

