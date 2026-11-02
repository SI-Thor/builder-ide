# Code-level survey of in-game building tools and agent seams (2026-11-01)

## Scope and method

Casey asked for the eight tools on `list.md` to be "investigated thoroughly", with `list.md`
treated as claims to check rather than facts. This document reports what each repository
actually is after reading its code, what it would cost us to adopt, and which two or three
are worth a hands-on day in phase 2. `BRIEF-2.md` (phase 1b, filed 17:11 the same day)
added a second scope: the inference, tracing, transport and supervision seams around our
Thor/ProArt split, plus a set of rewind-and-supervision ideas from `list2.md`.

Phase 1 was read-only. Twenty-one repositories were cloned at `--depth 1` and read:
2 171 724 KB of working tree, 67 391 tracked files, per `scripts/survey_sizes.sh`.
No package was installed, nothing was built, and no upstream code was executed. The only
commands run against third-party trees were `git`, `grep`, `du` and file reads. Where a
claim could only be settled by running the tool, it is listed as unverified rather than
guessed.

The box doing the reading was the ProArt: WSL2 on Ubuntu 26.04, 24 threads of an AMD
Ryzen AI 9 HX 370, 15 GiB RAM with 4.9 GiB free at survey time (the box was busy with
other seats), an RTX 4050 Laptop GPU with 6 141 MiB and a Radeon 890M, 808 GB free disk.
The Thor was reached read-only over SSH for three questions only: its Vulkan device, its
network ports, and which services are resident.

One structural point about `list.md` runs through everything below. The list sorts the
tools into three categories by *how they feel* to use — a director's stage, a sandbox
editor, an engine with an in-game editor. Read at code level, the categories do not
describe mechanisms. The real axis is: **can an agent drive it headless, and does its
state live in a file we can read, diff and rewind?** On that axis the eight tools fall
into three very different groups, and the ordering by "feels like an editor" turns out to
be close to reversed.

## Claim corrections against list.md

Four of the eight descriptions in `list.md` do not survive contact with the code. The
original wording is kept visible below, with what the code actually shows.

**MEP-Sandbox-Engine.** The list describes "a dedicated sandbox studio featuring a
classic Roblox-style layout... transform gizmos, precision snapping, real-time object
hierarchy explorers, and an integrated multi-tab Lua IDE panel". The repository holds
eleven files: a 2 306-line product landing page (`index.html`, carrying Google AdSense,
Microsoft Clarity, a Stripe "founder" button and an itch.io purchase at $5), five Markdown
notes, and a 197 KB RAR archive holding the editor itself.[9] The described features are
real, but they live inside `MicahEngineStudio_v1.3.rar`, not in the repository. GitHub's
licence detector reports nothing for this repository because there is no licence file;
the landing page's FAQ claims "Source code is available on GitHub under MIT License" and
"free for personal and commercial use", which the repository does not match.

**Open World Builder.** The list says it is "specifically designed to be compiled directly
into your own runtime engine, allowing you to sculpt terrain, place objects, and
manipulate entity positions directly inside the live environment". The repository's
`core/Core/Plugin.cs` is an empty class — `public class Plugin { }` — and `IViewport` is
an interface with no implementation.[11] The shipped program is a standalone FNA window
(`src/Program.cs` into `src/App.cs`), and the project targets `net7.0`, out of support
since November 2024. The terrain sculpting is real: `src/Nodes/TerrainNode.cs` implements
BrushRaise, BrushSmooth, BrushFlatten and BrushSplat with undo snapshots.

**Prowl Engine.** The list says it "uses an immediate-mode UI (ImGui) that overlays
directly onto a GPU-driven Vulkan simulation loop". The Vulkan half holds. The ImGui half
does not: `Prowl.Editor/Projects/Project.cs` carries the package reference commented out
(`<!-- <PackageReference Include="ImGui.NET" Version="1.91.6.1" /> -->`), and the editor
ships its own GUI stack under `Prowl.Editor/GUI`. Prowl also runs the game *inside* the
editor, not the editor inside the game, so it is an in-editor runtime rather than the
in-game editor the list category implies.

**Topview 3D Builder.** The list's "100% local" is true of the command-line path, and the
README badge says so, but the repository also ships `.mcp.json` pointing at a hosted
server, `https://mcp-3d.topview.ai`, over HTTP with OAuth.[1] The hosted entry point and
the local path are different products with different trust properties, and the list
mentions only one of them.

One correction is owed to our own documentation. `builder-ide/docs/research/theatre-open3d.md`
records topview-3d-builder as "Apache-2.0, TypeScript, created 2026-09-24" and calls it
"our B2 pattern ... with a camera planner, so it is the natural companion to the Theatre.js
work above". The date and the code licence are right; two details need correcting. The
agent-facing surface is **Python** (5 443 non-test lines in `agent/topview_3d_cli/`) with
TypeScript behind it, not TypeScript alone. And the licence is split: the code, schemas
and docs are Apache-2.0, but the four built-in characters, 121 poses and their cover images
are **CC BY 4.0, credited "© Topview"**, with the editor UI fonts under OFL-1.1.[3] Our
props come from our own Infinigen and TRELLIS.2 pipeline, so the CC BY assets would be
replaced rather than shipped, but the attribution obligation should be recorded now rather
than discovered later.

## Comparison across the eight tools

The table below is the summary of the seven GitHub repositories (Torque3D is one
repository and one tool). Read it for the shape: the second column is what the tool
actually is, the fourth is whether a seat can drive it without a human at the keyboard,
and the last is our verdict.

| Tool | What it actually is | Language and size | Agent-drive surface | Licence | Last commit | Verdict |
|---|---|---|---|---|---|---|
| topview-3d-builder | Director's stage for AI video; agent writes a JSON scene, local renderer shoots it | TypeScript + Python, 929 files | Python CLI, JSON in/out, documented exit codes | Apache-2.0 code; CC BY 4.0 assets | 2026-10-16 | Evaluate hands-on |
| build-world (Thrixel) | Claude/Codex skill pack plus a paid cloud connector; ships a three.js QA kit | JavaScript + Markdown, 84 files | Cloud MCP for assets; local Node/Playwright tools for capture | Apache-2.0; vendored Epic skills MIT | 2026-10-27 | Extract the three.js kit |
| Vibe3DScene | LangGraph agent + FastAPI + MCP server wrapped around Blender | Python, 330 files | MCP over HTTP, 37 tools, transactional code execution | Apache-2.0; addon MIT | 2026-04-12 | Extract ideas, no adoption |
| MEP-SANDBOX-ENGINE | Landing page plus a RAR of a Windows desktop editor | HTML + Markdown + binary, 11 files | None in the repository | **No licence file** | 2025-12-06 | Skip |
| Open-World-Builder | Standalone C# level editor with real terrain brushes and a JSON-schema level format | C# / .NET 7 / FNA, 394 files | File format only; no CLI, no MCP | MIT | 2024-02-10 | Extract ideas, no adoption |
| Torque3D | C++ engine whose in-game editor is a 79 000-line TorqueScript layer over the engine | C++ and C, 20 714 files | TorqueScript console; telnet console executes any command | MIT (BSD-3 and LGPL-or-BSD-3 in vendored deps) | 2026-09-26 | Skip as a base, extract patterns |
| Prowl | C#/.NET 10 Unity-like engine whose editor exposes an HTTP command line | C#, 1 018 files | `prowl` CLI over token-authenticated HTTP, Roslyn `eval` | MIT | 2026-11-01 | Extract the CLI pattern |

The pattern the table shows: the two tools with the best agent surfaces (topview's CLI,
Prowl's HTTP command line) are also the two that carry no world semantics, while the two
that carry real world semantics (Torque3D's editor suite, Open-World-Builder's terrain
tools) are the two that are hardest to drive. That split is the finding that shapes the
phase-2 ranking.

## The eight tools

### topview-3d-builder (agent-directed scene staging)

This is a tool for staging a shot that a video model will later render: where a person
stands, what they face, where the camera sits. That product goal matters for how we read
it, because a staged shot is a small, bounded scene, not a world with agents in it. The
list calls it a "3D director's stage built specifically for developers and AI agents", and
that is accurate; what the list misses is that the whole design is downstream of video
generation, and that the video step itself is outside the repository.

The architecture is two languages and a boundary. The TypeScript side is a pnpm workspace:
`editor/packages/builder` holds the scene model (React peer dependency, three.js 0.184 as
a peer, MobX for state, Zod for validation), `editor/packages/director-cli` is the Node
renderer driven by Playwright 1.63, and `editor/apps/studio` is a Next.js 15.1.9
application that renders the same document for a human. The Python side,
`agent/topview_3d_cli/`, is the part an agent touches, and it is deliberately thin: the
only runtime dependency in `agent/pyproject.toml` is `jsonschema>=4.23.0`, and the package
declares Python 3.11 or newer.

The scene format is a directory, `.topview-3d/`, holding `document.json` and `fcurves.json`
at `schemaVersion` 2, with `assets/` and `renders/` beside them. Writes are atomic (temp
file plus rename), `revision` increments on each write, and `sceneSequence` acts as a
compare-and-set token so a stale writer is rejected rather than silently overwriting.
Hand edits to those two files are ignored and overwritten on the next write — the file is
owned by the tool, which is the right default for a machine-written artefact. The fcurve
side is a compact keyframe format (`fcurves-compact-v1`): each curve carries an id, a
target node and property path, an interpolation mode, and keyframes with bezier handles.
That format is close enough to Theatre.js's sequence JSON to be worth a conversion test,
which is the specific question `theatre-open3d.md` left open.

The agent surface is the strongest thing in the eight, and it is strong because it is
boring. `topview-3d-cli` exposes project operations (`init`, `status`, `adopt`), document
operations (`get`, `validate`, `apply`, `delete`, `batch`), `evaluate` for numerical
checks, `inspect nodes` and `inspect views` for bounds, grounding and pairwise distance
and overlap, `render` for frames plus a contact sheet, `renders list` and `renders show`
with verified sha256, `generation record` for offline provenance, `camera presets`, `bom
get` and `bom checkpoint`, and `asset list`, `search`, `show`, `import`.[2] The operational
discipline is the part worth copying: `doctor` checks Python, Node, the renderer runtime,
the built-in assets, the pinned Playwright and Chromium, and attaches a hint to every
failing check; `browser ensure` installs the pinned browser idempotently while `render`
never downloads anything and fails with `BROWSER_NOT_INSTALLED` instead; exit codes are
documented (0, 1, 2); error codes are a closed vocabulary (`ASSET_NOT_AVAILABLE`,
`CAMERA_NOT_FOUND`, `RUNTIME_MISSING`, `RENDER_IMAGE_INVALID`); and Chromium is confined
to the local server plus an optional `publicAssetBase`, so a scene cannot phone home.

The check-before-render behaviour is the mechanism that matters most for us. `inspect
views` returns `checksComplete` with `checksBlockedBy`, measuring characters by their
posed mesh bounds rather than their origin, so grounding and framing follow the geometry.
This is our critic's job description in someone else's vocabulary, and it is the single
closest existing analogue to the thing `builder-ide` is trying to build.

Licence and activity both raise eyebrows in the same way. The code, schemas and docs are
Apache-2.0; the four characters, 121 poses and cover images are CC BY 4.0 "© Topview";
the editor fonts are OFL-1.1. The repository was created 2026-09-24 and had 77 commits,
270 stars and 2 watchers by 2026-11-01, with the last push on 2026-10-16 — twenty-two days
of development, then sixteen days of silence. Three people account for the commits
(gyx450 31, topviewai 6, hinsenoo 4), so the bus factor is one in practice. It is young
enough to be fragile and new enough that nobody depends on its internals yet.

On hardware, the requirement is Python 3.11, Node 20.6 or newer and a Chromium download.
Chromium is published for linux-arm64 by Playwright, but we have not run it on the Thor,
so that stays unverified. Nothing here needs a GPU to be useful, which makes it the one
tool in the list that could run identically on the Thor and the ProArt.

**Verdict: evaluate hands-on.** It is the only tool in the list whose agent contract,
licence posture and offline behaviour match the B2 pattern exactly, and its
check-then-render vocabulary is the nearest thing to our critic that exists off the
shelf.

### build-world (skill pack with a three.js QA kit)

The list describes "Thrixel Build World", previously Goal to Game, using an iterative
"gauntlet loop" workflow in which an agent builds and refines a world. The gauntlet loop
is real and documented,[5] and it is executed against a paid cloud service: `.mcp.json` in
this repository calls `uvx thrixel-mcp@latest`, which talks to Thrixel's hosted API where
asset generation is metered in "cubes".[4] The repository itself is not an engine and not
a world format. It is a skill pack — `skills/build-world/SKILL.md` plus per-engine guides
for three.js, Unity, Unreal, Roblox, Godot and Blender — and the loop it describes is the
loop a seat would run against that API.

What is worth our time is the part that is not the product. Under
`skills/build-world/engines/threejs/` sits a reference three.js implementation and, next
to it, a Node and Playwright toolchain: `capture`, `contactsheet`, `imagediff`,
`profile`, `smoke` and `mobilecheck`, plus `record`, `playcheck`, `serve` and `doctor`
one level up. The capture harness is the part with teeth. It drives a headless Chromium
in lockstep mode with a fixed shutter clock, takes named shots, writes a contact sheet,
diffs frames against a baseline and gates on the result. The code is young — the
repository was created 2026-08-03 and had 46 commits by 2026-11-01, all authored under
one identity, with 107 stars — but the harness is only a few hundred lines of Node and
its ideas are not proprietary.

That harness maps onto our stack more directly than anything else in this document.
`thor-world` renders in three.js with a WebGPU path and a WebGL2 fallback; `agent-world`
views the world through prismarine-viewer, which is three.js under the hood. A
reproducible capture rig for those two viewers is a QA instrument for the world, not for
a game, and "the same scene at two commits must produce the same frames" is a property
nobody in our stack is currently asserting.

Licence is permissive with one wrinkle: the repository is Apache-2.0, the vendored
EpicGames-UnrealMCP skills are MIT (© 2026 Epic Games), and the community field notes are
MIT (© 2026 Alex Coulombe Presents). No conflict, and both licences are compatible with
Apache-2.0 distribution.

**Verdict: extract the three.js kit, skip the connector.** The cloud half costs money we
do not need to spend, and the local half is the piece we can adopt under our own MIT
licence without a licence discussion.

### Vibe3DScene (Blender hosted by an MCP server)

The list's description is accurate: "a specialized framework running on LangGraph and an
MCP server... It connects directly into a Blender runtime". The implementation is a
FastMCP server on streamable HTTP (default port 9877) that drives Blender through a
socket client addon listening on 9876; the addon is a git submodule pointing at
`3DSceneAgent/blender-mcp-vision`, which is MIT-licensed and not present in a depth-1
clone.[8] The Python side is large for what it does: about 23 500 lines under `scene_agent/`,
6 000 under `mcp_server/`, 15 000 of TypeScript in the web layer and 17 800 of tests.

The tool surface is the most powerful per line of code in the whole survey: 37 MCP tools
covering scene inspection, object deletion, PolyHaven and Sketchfab and Objaverse asset
retrieval, ambientCG and HSSD materials, TRELLIS.2 / Rodin / Tripo / Hyper3D / Hunyuan3D
generation, Infinigen asset generation, rendering from objects or from a camera, camera
pose, observation and action, a global scene observer, and an undo snapshot.[7]

The mechanism that deserves a second look is `execute_blender_code`, which runs arbitrary
Python inside Blender with three safety switches: `safe_mode`, `rollback_on_guard_fail`
and `validate_scene`, with the result returned as a transaction record.[6] A tool that
executes code the agent wrote, wrapped in a transaction that can roll back and validate
the scene afterwards, is exactly the shape our write-path tools should take. It is also
the pattern that answers one of `list2.md`'s ideas directly: the pre-flight sandbox for
injected scripts.

Everything else about the deployment argues against adoption. Blender is not optional; it
is the runtime, and the scene format is `.blend`. `scripts/download_blender.py` fetches
Blender 4.2.15 with sha256 verification for `linux-x86-64` and `macos-x64` only — no
aarch64 and no Windows path in the script, though our own Thor has an aarch64 Blender 4.2
built from source, so pointing it at that build is a path that exists. The stack also
wants Docker, Redis for multi-worker operation, and provider API keys for the asset
generators.

Activity is the warning sign: created 2026-02-16, 87 commits, and **every one of them
from one author**. The last commit was 2026-04-12, seven months before this survey, and
there are no open issues and no pull requests to show that anyone else has looked since.

**Verdict: extract ideas, do not adopt.** The transactional code-execution shape and the
observer-camera idea are worth porting into our own tools; the LangGraph, Redis and
Docker stack and the Blender-as-runtime shape are not ours.

### MEP-SANDBOX-ENGINE (product landing page and binary archive)

This is the entry that most needs the list's wording corrected, because the product
described in `list.md` — Roblox-style layout, transform gizmos, precision snapping, a
hierarchy explorer, a multi-tab Lua IDE — is a Windows desktop application written in
Python with OpenGL, with an embedded Lua runtime (`lua_runtime.py`, `lua_scripting.py` in
the archive's file list), and none of it is in the repository. What is in the repository
is the shop window: a landing page that takes payments and fetches GitHub statistics for
social proof.

The archive is the reason to stop. `MicahEngineStudio_v1.3.rar` is a RAR v5 file; the box
has no `unrar`, `7z`, `bsdtar` or `unar`, and installing one would breach the read-only
constraint, so we read the archive's raw headers instead and enumerated roughly twenty-two
Python modules plus Lua scripts from the uncompressed header names. That is enough to
know the shape and not enough to audit the code.

Licence is the decisive problem. There is no licence file, so GitHub reports nothing; the
landing page's FAQ asserts MIT and free commercial use; the same page sells a $5
itch.io copy and a Stripe-funded "founder" tier. Three signals point in three directions,
and the one with legal weight is the absent licence file. Treat the code as closed until
someone with authority confirms otherwise.

Activity is equally thin: created 2025-12-04, pushed 2025-12-07, twenty commits, one
author, one release (v1.3, on the creation day), one star. The whole project is three
days of commits.

**Verdict: skip.** Wrong platform, no licence, dormant, one author, and a Lua-inside-
Python design that collides with our Python-first stack for no gain. The only artefact
with any value is `MEPLua_Complete_Library_v1.1.md`, a written Lua API catalogue, which
does not repay the reading time it would cost.

### Open-World-Builder (standalone C# level editor)

The list's category — "in-viewport sandbox editor" — is the right instinct and the wrong
mechanism. This is a standalone desktop application: C# on .NET 7, with FNA as the XNA
reimplementation underneath, ImGui.NET for the immediate-mode interface, Newtonsoft.Json for
serialisation and SharpGLTF for the scene graph. Forty-five C# files and about 11 000
lines. The `deps/` folder carries prebuilt native binaries for `linux64` and `x64` only
(`cimgui.so`, `cimguizmo.so`, `cimnodes.so`, `cimplot.so`, plus FNA's `libFNA3D.so.0`,
`libFAudio.so.0`, `libSDL2-2.0.so.0` and `libtheorafile.so`).

What is genuinely well made is the level format and the terrain tools. `schema/Level.cs`
and `schema/Level.schema.json` describe the level document as JSON with a published
schema, alongside `Project.cs` and `Project.schema.json` for the project, with
`example/example_project.owbproj` as a worked instance. That is a format a seat could
read, write and validate without running the editor — the property that matters most to
us and the one that makes Open-World-Builder a source of ideas rather than a candidate.
`src/Nodes/TerrainNode.cs` is 1 510 lines implementing BrushRaise, BrushSmooth,
BrushFlatten and BrushSplat, each with an undo path that snapshots the old heightmap.
Terrain sculpting with per-brush undo is a mechanic our Infinigen recipe vocabulary does
not have, and it maps onto a recipe op ("raise ridge by 3 m along the north edge")
cleanly.

Against that: the integration story the list repeats is aspirational. `core/Core/Plugin.cs`
is `public class Plugin { }`, the editor is not embedded in anything, and there is no CLI,
no MCP and no headless mode — the file format is the entire agent surface. The runtime is
out of support (`.NET 7` since 2024-11), the native binaries have no linux-arm64 build, so
the Thor cannot run it, and the repository has been frozen since 2024-02-10 with forty-seven
commits from a single author, four open issues unanswered, and no releases.[10]

**Verdict: extract ideas, do not adopt.** Take the brush-op model and the schema-first
level format into our recipe vocabulary; leave the C# and FNA stack alone.

### Torque3D (C++ engine with a script-level in-game editor)

Torque3D is the origin of the in-game editor idea,[12] and reading it explains why the idea
is compelling and why it has not become the default. The list's claim is accurate: with
a single keypress the engine transitions from gameplay to its editor suite.
`Templates/BaseGame/game/tools/main.tscript` binds `GlobalActionMap.bind(keyboard, "F10",
fastLoadGUIEdit)` and `fastLoadGUIEdit` loads the editor GUI.[13] The suite is real and
large: thirty-odd editors under `Templates/BaseGame/game/tools/` — world, river, road,
mesh-road, material, shape, forest, navigation, particle, mission-area, decal, convex,
asset browser, shader, GUI, datablock, component, project importer, window console — plus
Verve, the visual scripting environment.[15]

The mechanism behind the claim is the finding. The editor is **not** an engine module. It
is 79 262 lines of TorqueScript in the project template, layered over the C++ module at
`Engine/source/gui/editor` (21 531 lines) and `Engine/source/gui/worldEditor`. The C++
side is thin: `EditManager::editorEnabled` sets `gEditingMission` and fires `onEditorEnable`
on every SimObject — and the comment in `Engine/source/gui/worldEditor/editor.cpp` records
that this callback once stopped being called, breaking anyone hooking it. A whole editor
suite sitting in the *project* rather than the *engine* is a distribution problem as much
as a design one: to get the in-game editor you adopt their project template wholesale.

Scene format and scripting have both moved. Assets are TAML (1 576 `.asset.taml` files in
the template) and the old `.tor` text format is gone from the live branch — zero `.tor`
files. The scripting language is TorqueScript, and the agent surface is the console, which
is more interesting than it sounds: `Engine/source/console/telnetConsole.cpp` implements
a remote console, `telnetSetParameters(port, consolePass, listenPass, remoteEcho)`, whose
`processConsoleLine` feeds every line into `Con::smConsoleInput` — so a telnet session
executes arbitrary console commands, including `exec(fileName)`.[14] An agent could
telnet into a running engine and run TorqueScript. That is a genuine headless drive path,
and it is also the shape of every in-game console since.

Activity is healthy in a way the branch structure obscures. The live branch is
`development`, last commit 2026-09-26, with 8 586 commits and about 123 contributors
(Azaezel 3 170, Areloch 1 614, marauder2k7 808, crabmusket 466), 87 open issues, 30 open
pull requests. But `master` has been frozen since 2018-04-05 at release 3.10.1,
`Preview4_0` since 2022-11-01 and `development_3_X` since 2021-01-27. Releases are
v4.0.3 (2023-02-07) and earlier. The project a reader meets by following the canonical
GitHub link is eight years stale.

Licence is permissive with one item to watch. The root `LICENSE.md` is MIT but also
carries a BSD-3-Clause block for the "ray" IES profile generator, and `Engine/lib/` vendors
assimp (BSD-3), SDL (zlib), Bullet (zlib), OpenAL-soft, recast, tinyxml2, sqlite, zlib,
lpng, pcre, squish, nativeFileDialogs and the xiph libraries (BSD-3), plus a vcpkg
manifest. OpenAL-soft is the item that needs a decision rather than a note: it is
LGPL-2.1, and the tree also ships the BSD-3 alternative, so we would take the BSD-3
option rather than reason about copyleft.

On hardware the engine compiles for ARM64 — the root `CMakeLists.txt` detects `arm` and
sets `TORQUE_CPU_ARM64` — but the Linux CI builds `ubuntu-latest`, which is x86_64, and
the platform directories are POSIX, SDL, X11, Windows and Mac. ARM64 Linux is therefore
plausible and unverified.

**Verdict: skip as a base; extract two patterns.** The first is the editor-as-script-layer
architecture — an in-game editor that is a script package running inside the engine, which
is what `bevy_egui` already gives us in the Bevy plan, so we have the pattern without the
700 MB tree. The second is the terrain, river and road brush set, which is the most
complete in the survey and worth reading as a reference for our recipe vocabulary.

### Prowl (C# engine and editor with an HTTP command line)

Prowl is the most active project in the survey,[16] with 5 918 commits, about thirty
contributors, commits on 2026-11-01, v1.0-preview-5 on 2026-10-20, 1 272 stars — and it
is a C#/.NET 10 engine with a Vulkan renderer, an editor, and a command-line client. The
engine libraries ship as NuGet packages rather than source in this repository
(`Prowl.Aperture` 3.9.3 among them,[18] also MIT), and `Libraries/` carries miniaudio natives for
linux-arm64, linux-arm, android-arm64 and the desktops, plus the OpenXR loader for
Windows.

The list's ImGui claim is wrong, as noted above; the editor ships its own GUI stack. The
real story is the command line, and it is the best agent surface in the survey. `prowl`
talks to a server running inside the editor over loopback HTTP with JSON, with the port
and a token written to `Library/Cli.lock` and the token sent as `X-Prowl-Token`. The
command set covers `status`, `logs`, `undo`, `compile`, `scene` (tree, select, go),
`component`, `get`, `set`, `menu`, `asset`, `script`, `prefab`, `material`, `play`
(start, stop, pause, step), `input` (key and mouse), `screenshot`, `build`, `graph`,
`api` and `importer` — about 4 350 lines of server and command code.[17]

Two of those commands are worth naming. `eval` compiles a C# snippet with Roslyn against
every loaded assembly and runs it on the editor's main thread, returning the result —
an agent can ask the running editor anything its own API can answer. And `api` searches
the real scripting API and returns documentation for it, so an agent can look up the API
instead of guessing at it. `screenshot`, `play` and `input` together give an agent the
loop we keep rebuilding for the web viewers: drive the thing, look at it, drive it again.

Licence is MIT throughout, including the NuGet engine packages,[18] the dual public-domain /
MIT miniaudio, and the Apache-2.0 OpenXR loader. Activity is strong, though the
contributor list shows concentration: one author accounts for 4 669 of 5 918 commits.

On hardware, Prowl is Vulkan-only, and the Thor does have Vulkan — device "NVIDIA Thor",
API 1.4.329, driver 595.78 — so the platform question is not the blocker. The blocker is
that the renderer natives for linux-arm64 live in the NuGet packages rather than in this
repository, so we cannot confirm an aarch64 renderer build without downloading them,
which phase 1 forbids.

**Verdict: extract the command-line pattern; do not adopt the engine.** A token-
authenticated loopback HTTP command line with an eval escape hatch and an API lookup is
a better shape for our own web viewers than anything we have, and it costs nothing to
copy. The engine itself is a Unity clone in C# with a Vulkan renderer, which is the wrong
shape for a three.js world.

## Fit summary across the eight tools

The table below answers the brief's question directly: for each tool, what we would use
as is, what we would extract or rebuild, and what we skip.

| Tool | Use as is | Extract or rebuild | Skip |
|---|---|---|---|
| topview-3d-builder | The CLI contract: JSON project, documented commands, exit and error codes, `doctor`, offline render with sha256 manifest | Check-then-render vocabulary (`checksComplete`, `checksBlockedBy`, mesh-bounds grounding) and the compact fcurve format as a Theatre.js interchange candidate | The Studio UI, the Topview characters and poses, the hosted MCP path |
| build-world | The three.js capture harness pattern: lockstep fixed-shutter shots, contact sheet, pixel diff, baseline gate | The harness itself, ported into our own repo under Apache-2.0 | The Thrixel cloud connector and its metering, the Unity/Unreal/Roblox guides |
| Vibe3DScene | Nothing | Transactional tool execution (`safe_mode`, rollback, validate) for our write-path tools; the observer-camera idea | The LangGraph/Redis/Docker stack, the provider zoo, Blender as the runtime |
| MEP-SANDBOX-ENGINE | Nothing | Nothing | Everything — closed, Windows-only, dormant |
| Open-World-Builder | Nothing | The brush-op terrain model (raise/smooth/flatten/splat with undo) and the schema-first level format as recipe ops | The C#/FNA stack, the prebuilt x64 native binaries, the plugin architecture |
| Torque3D | Nothing | Editor-as-script-layer architecture (we already have the shape in `bevy_egui`); the terrain/river/road brush reference set | The engine, TorqueScript, the 700 MB tree, the 2018 `master` |
| Prowl | Nothing | Token-authenticated loopback HTTP command line, `eval` escape hatch, `api` lookup, `play`/`input`/`screenshot` loop | The engine, the Vulkan renderer, the editor GUI |

## Phase 1b: supervision, inference and transport seams

Phase 1b asks about the machinery around the tools rather than the tools themselves: the
NVIDIA inference stack, a headless server engine, tracing, a bake daemon, a virtual KVM,
the transport between our two machines, and the inference servers we already run. The
questions that matter for us are whether each thing can run on the Thor and whether it
earns its place, so the findings are ordered by that.

### NVIDIA Game Agent SDK

The repository exists and the licence claim holds: `NVIDIA/game-agent-sdk` is Apache-2.0,
created 2026-05-26, last pushed 2026-06-16, 31 stars.[19] It is a C99 ABI with a thin
C++ wrapper exposing three API groups — Agent (stateful, owns the conversation and drives
the inference and tool-call loop autonomously), Chat (stateless, the application drives the
loop) and RAG (semantic, lexical and hybrid retrieval). It is the plugin seam we would
need if we ever wanted an LLM beside a game loop, and its samples include a poker
assistant, a two-agent multi-agent sample sharing one model with distinct identities and
histories, and a RAG database builder.

The licence is per component and the repository says so itself.
`THIRD-PARTY-LICENSES.md` states that the root Apache-2.0 "covers only NVIDIA-authored
SDK code": twelve vendored open-source components (cpp-httplib and faiss among them, MIT),
NVIDIA proprietary redistributables under the CUDA EULA, and four bundled model artifacts
under their own model-card terms.

The deployment story does not fit us. Requirements are Windows 10 or 11, an Ampere-or-newer
GPU, driver 570.65 or later and CUDA 12.8 or later; the build scripts are Visual Studio
project generators (`setup.bat`, `build.bat`), the bundled SLM wants about 3.8 GB of VRAM,
and there is no mention of Linux, aarch64 or Jetson anywhere in the README or the docs.
That collides with our standing rule that no language model is resident on the Thor
(`builder-ide/CLAUDE.md`, "No LLMs on the Thor", Casey and B2, 2026-10-31) and with the
rule that the Thor is for motion, visual assets, world models and engines, and many small
decision models. One detail is worth keeping: the SDK's own limitations note that the
NVIGI backend is not yet supported — `ACEModelLoadParam_Backend` accepts only
`ACEInferenceBackend_Llama` — so the two NVIDIA components in this brief do not yet
integrate with each other.

The methods are the payload, and they are good. The agent deep-dive documents four
conversation lifecycle rules that map onto our canon design without translation:[20]

- *Transient messages* are included in the next prompt only and then dropped, which is how
  you steer once without polluting the history.
- *Redacted messages* keep their content in the conversation but render as `[REDACTED]`
  in later prompts once the autonomous tool-call chain that produced them ends. A tool
  result that the model should read once but not carry forever is exactly this.
- *A preamble* is a persistent prefix between the system instructions and the windowed
  conversation; it survives history-window aging and is emitted on every inference until
  cleared. The SDK's own suggested use is a pending-operations summary that updates as
  long-running tools complete — which is our canon ledger with the word "canon" removed.
- *Window-start introspection* (`ace_agentGetWindowStart`) tells the application which
  messages are about to age out, so the application can summarise them into the preamble
  before they go.

Two more fit a supervision brief: `ace_agentCancel` interrupts a running inference from
another thread, which is how "a human comes and goes, and can rewind" would be
implemented; and `ace_agentSerializeConversation` returns an opaque version-tagged buffer
that survives a session, with a trailing assistant message holding unanswered tool calls
stripped on load so an orphaned call cannot be replayed.

**Verdict: read for methods, do not install.** The conversation lifecycle is the most
directly transferable design in phase 1b, and it costs nothing to implement in our own
seats. The SDK itself is Windows-only, wants a resident model, and is four and a half
months stale.

### NVIDIA ACE and NVIGI

Both components are real and both carry licence detail the list's single sentence hides.

`NVIDIA/ACE` is Apache-2.0 at the file level — `LICENSE` carries SPDX Apache-2.0 headers
— but the README is explicit that the microservices come through an **evaluation licence of
NVIDIA AI Enterprise via NGC**, and its own deployment table shows several technologies as
cloud-only with Windows deployment marked "Coming Soon".[21] The repository is samples and
workflows, not an SDK; it was last pushed 2025-06-26, sixteen months before this survey,
with 330 stars.

`NVIDIA-RTX/NVIGI` (version 1.7.0) grants the MIT licence to the SDK "except for the
Microsoft DLL libraries, which are governed by the Microsoft Software License Terms for
Microsoft DirectX, and the NVIDIA models ... governed by the NVIDIA Community Model
License".[22] GitHub's licence detector reports "NOASSERTION" for it because the licence
file is prose rather than a licence text — worth knowing, because a reader who trusted the
detector would misjudge it. The build is Windows-only in practice: MSVC 2022 minimum,
`setup.bat` and `make.bat`, D3D12 core runtime and DXIL DLLs to be copied in from the
binary pack, and experimental GGML plugin DLLs that are not built by the source pack. The
models are downloaded through `download_data.bat`, not committed.

One repo is the exception and the most interesting item here for us:
`NVIDIA-RTX/nvigi_godot_extension` is Apache-2.0 and is a GDExtension that binds NVIGI to
Godot, running LLMs, ASR, TTS and embeddings on the GPU from GDScript through GGML with
**CUDA, Vulkan or CPU backends**, explicitly "no cloud required".[23] That CPU and Vulkan
backends matter, because they are the paths that exist on aarch64. In practice the
extension's own CMake presets are `windows-x64`, `windows-vs2022` and `windows-vs2026`
only, and its "compute in graphics" feature is D3D12-only and experimental. So it is a
GDExtension we could not build on the Thor without porting its build, aimed at exactly
the "LLM beside the game loop" shape our rule forbids.

**Verdict: read the method notes, do not install.** The Game Agent SDK's conversation
lifecycle is the extract; the inference SDKs are Windows-first, model-licensed, and
aimed at a deployment our own rule excludes.

### Godot headless dedicated server on ARM64

Godot is the one phase-1b item that is both buildable on the Thor and genuinely useful
as a world runtime, so the facts matter.

It runs on aarch64 without work: the official builds publish
`Godot_v4.7.2-stable_linux.arm64.zip` alongside the x86_64 and arm32 binaries and the
Mono variants.[25] The source lists `arm64` among the supported Linux architectures and
the Linux export plugin offers `x86_64,x86_32,arm64,arm32,rv64,ppc64,loongarch64` as
export architectures.[24] The dedicated-server shape is first-class: the export dialog has
an "Export as dedicated server" mode, and the platform exporters skip shader baking
because no rendering is performed in that mode. Runtime flags exist for the same purpose
— `--headless` selects the headless display driver and the dummy audio driver, and the
help text describes it as "useful for servers". The repository is at 4.8.0-beta with
14 453 tracked files, MIT-licensed, last commit 2026-10-30.

Against our stack, Godot is a third world runtime, and the comparison is not close.
`agent-world` already is a server-authoritative world — a Paper server on port 25565 with
mineflayer agents driving it and prismarine-viewer watching — and it is running on the
Thor right now. `last-mile` plans a Rust Bevy world with `bevy_egui` 0.43.1 over Godot's
own physics conventions. Adding Godot would mean a third world runtime, a third scripting
language (GDScript alongside GDScript-like Bevy Rust and JavaScript mineflayer), and a
third asset pipeline, for a viewer we already have twice.

**Verdict: do not adopt.** Godot is the right answer to a question we are not asking.
Its one transferable idea is the shape of a headless authoritative server with scripted
agents, which both of our existing worlds already implement.

### World-tick tracing with NVTX, Nsight Systems and OpenTelemetry

This is the item where our box is already better prepared than the survey suggests.
`NVIDIA/NVTX` is Apache-2.0 **with LLVM Exceptions** (the exception matters: it is the
patent grant), with C, Python and Rust bindings, and it is a header-only annotation API
that costs nothing when unused.[26] GitHub's detector also reports NOASSERTION here, for
the same prose-licence reason as NVIGI.

Nsight Systems is not a repository — `github.com/NVIDIA/nsight-systems` does not exist,
and the product is a binary download — but **it is already installed on the Thor**:
`/usr/local/bin/nsys` and `nsys-ui`, version 2025.6.3.541. There are no reports yet.
For a Tegra target, Nsight Systems additionally needs the target-side helper[28]
(`nvidia-sysprof-daemon`) running on the device, which we would have to check for and
start; the Python pip package `nvidia-nvtx-cu13` is not installed on the Thor and no
`libnvToolsExt` is present, so NVTX ranges would have no consumer until both are in
place.

OpenTelemetry is the cross-vendor half: `opentelemetry-python` and
`opentelemetry-cpp` are both Apache-2.0 and both active.[27] For our stack, the Python
SDK is the relevant one, because the world tick we want to trace runs in Python (the
night, the critic, the recipes) and in the Thor's Rust admission daemon.

The cheap additions, in the order they would pay off:

1. **One trace id per admitted run.** `thor-admit run` already owns the lease, the label,
   the peak and the tier, and it already records what ran. Adding a span id to the lease
   record costs one field and makes every nightly run joinable with any span the
   workload emits.
2. **OpenTelemetry spans in the recipe pipeline, not in the game loop.** The interesting
   boundaries are recipe-to-glTF, critic-check-batch and Infinigen-invocation, not
   individual frame ticks. Python OTel gives us those spans with no engine change.
3. **Nsight Systems only for the one run that needs the whole machine.** It is
   heavyweight, needs the target daemon, and our workloads are already bounded by the
   admission floor; save it for the question "where did the 63 seconds go" in a single
   run, not for continuous tracing.

**Verdict: adopt the trace-id seam, defer Nsight.** The OpenTelemetry Python exporter on
the night and the critic is a day's work; NVTX and Nsight Systems are for when we have a
GPU timeline question that OTel cannot answer.

### File-watch bake daemons with watchdog and headless Blender

`gorakhargosh/watchdog` is Apache-2.0, pure Python, 1 120 KB, 116 tracked files, and was
last committed the day before this survey — it is alive and it is tiny.[29] On Linux it
uses inotify. Its job is watching a directory and calling a handler when files change.

What it would do for us is watch a shared directory and run a bake. The piece that makes
it feasible already exists: our own aarch64 Blender 4.2 on the Thor, built from source
with Cycles CUDA for sm_110, is the thing that would do the baking.

What is missing on our side is the bake itself. Searching `builder-ide` for decimation,
AO or normal baking and LOD turns up nothing in the pipeline — we generate meshes from
Infinigen, TRELLIS.2 and build123d, and then the critic measures them. There is no
decimate step, no bake step and no LOD tier. So a watchdog daemon would not be
automating an existing step; it would be adding a new one, and the question is whether
that step earns its place.

It does, for one specific job: the critic currently measures the asset it was given. A
bake daemon that produces a decimated, AO- and normal-mapped copy lets the critic measure
what the viewer will actually draw. That is a small, well-bounded addition with a clear
acceptance test — bake a known prop, then check that the baked copy still passes the
critic's geometry checks, and that the decimated copy differs from the original by less
than a stated tolerance. `watchdog` is the right trigger because the ProArt writes into a
share and the Thor must notice without polling.

Two cautions. First, our "watchdog" already means something else: `core/engine/resident/
policy.py` is the resident-memory guard inside the admission daemon, and the term collision
will confuse readers. Second, and more seriously, `builder-ide/CLAUDE.md` records that
"Any other third-party project from GitHub still needs his OK". A bake daemon is a new
third-party dependency, and it needs Casey's sign-off before it lands, not after.

**Verdict: worth a proposal, not a build.** The mechanism is sound and the missing piece
is a bake step we do not have; the dependency needs approval first.

### input-leap across two machines

`input-leap` (formerly synergy) is GPL-2.0 with an explicit OpenSSL exception.[30] It is
a virtual KVM: one keyboard and mouse, two machines, cursor slides across the boundary.
Running it as a separate program is unproblematic under the GPL; linking it into our code
would be, and nothing here suggests we should.

The feasibility question is whether there is a desktop on the far side to receive the
events, and there is: the Thor runs Xorg under GDM (`Xorg ... -nolisten tcp` on vt1), with
`thor-desk-vnc.sh` in `/usr/local/bin` for access. Input-leap's Wayland support is opt-in
through `INPUTLEAP_BUILD_LIBEI`, which is off by default, and the Thor is on X11 anyway,
so the default path applies.

The honest assessment is that we do not need this. The Thor is a headless generation box;
the ProArt is the human's seat. There is no "Thor desktop" for a human to work in, so
there is nothing to slide a cursor into. The idea would only earn its place if we ever
gave the Thor a human-facing desktop, and if we did, `scrcpy`-style access or plain VNC
would serve the same purpose without a GPL dependency.

**Verdict: skip.** The problem it solves does not exist on our topology.

### Transport choice for the engine-to-Thor hook

The brief asks how gRPC compares with what we already run. The current state is worth
stating precisely, because it is not what the brief assumed.

There is no NATS server on the Thor. The listening ports are SSH (22), the Minecraft
Paper server (25565), the prismarine-viewer (8080), a `sitka-distill` index server
(8100), the `agent_world_reflex` server (8110, bound to localhost), and two others
(8788, 2206). The `agent-world` stack does use websockets, through prismarine-viewer and
the reflex server. gRPC itself is Apache-2.0 with first-class aarch64 support — the
`grpcio` Python wheels ship manylinux aarch64[33] — and OpenTelemetry's gRPC exporter is
already a dependency of the Python SDK.

The choice turns on what crosses the wire, and our traffic is not a hot stream. What
crosses today is recipe text, critic verdicts, work orders and asset paths: kilobyte
JSON messages, a few per second at most, each needing to be readable by a human and by
our own scripts. gRPC would buy typed schemas and HTTP/2 multiplexing, and charge us a
protobuf toolchain, a schema registry and a codegen step for every message we already
read as plain JSON. NATS would buy publish-subscribe fan-out, which we do not need yet
because we have exactly one consumer per subject and our world state has a single writer.

There is a third option that the survey of the eight tools points at, and it is the one
we would actually take: HTTP plus JSON, with the same shape Prowl uses for its command
line — loopback or LAN, a token, a small command vocabulary, and a documented error
vocabulary. Our `thor-world` already speaks MCP over HTTP to `builder-ide`. The honest
answer to the brief's question is that gRPC earns its place only on a hot path that does
not exist yet, and NATS earns its place only when more than one consumer needs the same
event.

**Verdict: keep HTTP and JSON, and copy Prowl's command shape.** Revisit when a
continuous state stream exists; measure the latency first, because today the link is
2.4 GHz Wi-Fi and a wire-protocol decision made on a saturated radio would be the wrong
decision.

### ComfyUI and vLLM against what we already run

The brief asks only for what we already have or have already ruled out, and the answer is
short.

**ComfyUI: we already have it.** `builder-ide/docs/lab/` records a ComfyUI server
running the TRELLIS.2 sampler on the Thor at about 9.8 GB of GPU memory, with capture
scripts for the KSampler step and a graph-capture probe that is monkeypatched into the
ComfyUI process from a base directory. Its licence is GPL-3.0.[32] That is a licence
obligation only if we redistribute or link it; running it as a separate process that our
scripts call over HTTP is exactly how we already use it, so nothing changes.

**vLLM: ruled out by rule, not by licence.** vLLM is Apache-2.0 and actively developed,
so the licence is not the obstacle.[31] The obstacle is our own: "No LLMs on the Thor
(Casey, B2, 2026-10-31). Language comes from cloud subscriptions." The Thor does have
`ollama` installed, but its server is not running, and `nvidia-smi` shows no compute
processes at all — the box is currently running no model. That is the rule being kept, so
vLLM needs a different decision than a licence check. The rule does allow "many small
decision models", and `d1-2B` is served for `agent-world` through `thor-admit serve`, which
is a resident decision model on the box — allowed, because it chooses between tiles rather
than writing text.

**Verdict: no change.** ComfyUI stays as the TRELLIS.2 path; vLLM stays out until the
no-resident-LLM rule changes, at which point ollama is already installed and would be
cheaper to keep.

### The Ethernet link between ProArt and Thor

This item ends in a correction, and it is the one piece of hardware news in phase 1b.

The Thor's claim checks out. It has four 10 Gigabit Ethernet ports (`mgbe0_0` through
`mgbe3_0`, each reporting `Speed: 10000Mb/s` with auto-negotiation on), and they are
present and usable. But all four report **"Link detected: no"** — nothing is plugged into
them. The only active link on the Thor is Wi-Fi: a Realtek RTL8852CE 802.11ax adapter
associated at **2.4 GHz** (centre frequency 2462 MHz, signal −68 dBm), carrying the
default route and the Thor's address 192.168.0.78. The other wired port, `enP2p1s0`, is
also down. So the ten-gigabit path exists and is unused; the world currently runs over a
2.4 GHz radio.

The ProArt is the problem. The machine is an ASUS ProArt PX13 HN7306WU, and
`Get-NetAdapter -Physical` returns exactly one adapter: a MediaTek Wi-Fi 7 MT7925. There
is **no wired Ethernet port on the laptop**. The "10 Gbps" entry that appears in the
adapter list is the WSL2 Hyper-V virtual adapter, which is not a physical port. So the
instruction in `list2.md` — "Connect the AGX Thor's 10 Gigabit Ethernet port directly to
the 10 GbE port on your ProArt workstation or motherboard using a Cat6a/7 patch cable" —
cannot be carried out as written, because there is no port to plug into.

What it needs instead: a USB4 or Thunderbolt 10GbE adapter on the PX13 (the machine has
USB4 ports), a Cat6a patch cable, and a fixed IP on the Thor's `mgbe0_0` so the link
does not depend on DHCP. Cat6a is the right cable class for 10GBASE-T at 100 m. The
proposed topology is otherwise sound, and it would remove a 2.4 GHz radio from the path
between the viewer and the world.

**Verdict: worth the ask.** This is the cheapest change in phase 1b: one adapter, one
cable, one fixed address, and the transport question in the previous section gets
answered on wire instead of over radio.

## Rewind and supervision ideas mapped to our designs

The brief asks for each of `list2.md`'s named ideas to be judged as exists, partial or
new against our designs. The table is the map; the paragraphs after it are the reasoning
that does not fit in cells.

| Idea | Our existing piece | Gap |
|---|---|---|
| #9 Time-travel delta ledger, headless timeline forks | agent-world's canon ledger and its "deterministic replay pinning" (COACHING-IDEAS #6); the `decision-ledger` project's append-only `ledger.jsonl` | No fork mechanism: we can record, pin and replay, but not re-run a branch while the human keeps playing |
| #8 Pre-flight sandbox for injected scripts, hot-swap if it passes | thor-admit leases and tiers; the critic's scripted checks | No isolated execution of agent-written code before it runs live |
| #7 Client prediction plus server hindsight correction | agent-world reflex/canon split; `agent_world_reflex serve` on the Thor | Correction blending is not specified; the reflex server does not send state corrections back |
| #1 "Never wait" placeholder fallback, bake ahead on the Thor | Infinigen tile generation; the night's queueing | No placeholder asset path, and no look-ahead bake of neighbouring tiles |
| #6 Shared substrate, many viewers | prismarine-viewer in agent-world; thor-world's three.js viewer | One world state, two viewers, no agreed substrate format between them |
| #10/#16 Repo-as-a-room, terminal MUD | agent-world rooms; TextWorld | Rooms are spatial, not navigable as text |
| #11 Interface that adapts to failure patterns | seat-watcher; the screen watcher | No failure-pattern log feeding a layout decision |
| #14 Push-to-talk voice to world macros | skald (voice), stopped on 2026-10-30 | No macro vocabulary; and no human audio may be stored |
| #17 Orin as a perception sub-node | Orin at 192.168.0.50, 8 GB, shared | Nothing runs on it; a memory-hungry service is not allowed |

**#9 is the closest to done, and the most valuable.** We already record decisions: agent-world's
canon ledger is described in `agent-world/COACHING-IDEAS.md` as the single source of truth,
holding coaching data as structured deltas pinned to exact world ticks, with a deterministic
replay and the note overlaid — which is the annotate-and-rewind half of this idea, already
designed. The `decision-ledger` project keeps its own append-only `ledger.jsonl`, one row per
(source, question, state, answer), for calibrating the decision models. What is missing is the
fork: the ability to re-run a branch from a snapshot on the Thor while the human keeps
playing. The Game Agent SDK gives us the shape for that second half — an opaque, version-tagged
buffer that can be serialised and restored, with the specific care that a trailing assistant
message holding an unanswered tool call is stripped on load so an orphaned call cannot be
replayed. For a world, the equivalent is a snapshot of (canon state, recipe versions, RNG
seeds) plus the ability to re-run the night from that snapshot. The Thor has 122 GB of unified
memory and no swap, which makes in-memory forks of a scene cheap; that is the hardware fact
that makes the idea practical here.

**#8 is the one we can borrow a mechanism for.** Our admission daemon bounds memory and
kills the largest lease when the box runs short, but it does not run agent-written code
in isolation before it goes live. Vibe3DScene's `execute_blender_code` wraps arbitrary
code in a transaction with `safe_mode`, `rollback_on_guard_fail` and `validate_scene`.
That is a three-line shape we can apply to any tool our seats call: run it, validate the
result, roll back on failure, and only then commit. The Thor is the natural place for the
pre-flight instance because it already runs the heavy work and already has the memory.

**#7 already exists in outline.** Agent-world's reflex server on the Thor and the
canon model on the ProArt are the front-end prediction and back-end truth of this idea.
What is missing is the third element, the correction: the server currently answers
requests but does not push a correction vector, and the client does not blend. The
interestingly correct part of the idea is the interpolation — a correction that snaps the
pose would read as a bug, while a blended one reads as physics.

**#1 is partly ours.** The night already batches and queues work, so "the Thor bakes ahead
of where the camera is looking" is an extension of a mechanism we run rather than a new
one. The missing piece is the placeholder: an agent or a viewer arriving at a tile that
does not exist yet must get *something* — a block-out proxy — rather than nothing. This
is the same shape as topview's `MOTION_NOT_AVAILABLE:<id>` warning, where the character
keeps its pose and the render still succeeds.

**#6 exists as two viewers and no substrate.** agent-world's prismarine-viewer and
thor-world's three.js viewer both watch the same world, and they are separate code paths
with separate formats. The shared-substrate idea is right and the gap is concrete: the
two viewers should read the same document, which is the format question `thor-world`
already answers for recipes.

**#10 and #16 are the same idea twice** — repo-as-a-room and terminal MUD — and both
map onto agent-world's rooms. The interesting part is not the MUD skin; it is that
walking into a "room" could scope which part of the system you are looking at. Today
that scoping is done by directory, which is invisible from the world.

**#11 is the least developed.** The screen watcher knows when to speak; nothing collects
failure patterns across a run and feeds them back into a layout. The cheap version is a
JSONL log of crash counts per script label, which is the same shape as the critic's
verdict records, and then a morning report line.

**#14 needs the privacy rule stated, not just obeyed.** Push-to-talk voice into world
macros is a real friction reducer, and the machinery exists — skald was the voice
component and it was stopped on 2026-10-30 to give the Thor to this project. The rule is
"no transcripts or audio are stored", so the design has to be: audio is streamed to the
Thor, transcribed, and the audio never lands on disk. The half-built part is the macro
vocabulary, which we do not have.

**#17 is the one to decline.** The Orin has 8 GB and is shared; `builder-ide/CLAUDE.md`
records that the box is for other work and should be asked before use. A perception
sub-node that ingests camera streams and runs detection is a memory-hungry resident
service, which is exactly what the Orin cannot afford. Defer until someone asks.

The ideas we are skipping, and why, are listed in `list2.md` itself and repeated here so
the record is complete: the AYN Thor handheld is a different device from the Jetson AGX
Thor and off-track; the monitor picture-by-picture setup is a display feature, not a
system change; posture and glasses health advice is not ours; and the bathymetry data is
Casey's own, off-track for this survey, though it could seed real terrain later if the
world wants a heightfield with a provenance.

## Ranked phase-2 shortlist and one-day test plans

Phase 2 needs Casey's OK before anything is installed, and installing is his call
("Any other third-party project from GitHub still needs his OK"). The ranking below is
the recommendation that goes to him. Nothing here beats a phase-1 pick on raw capability,
but one phase-1b item does beat one phase-1 pick on cost, and the ranking reflects that.

### Shortlist 1: topview-3d-builder

This is the only tool that can be driven end to end by a seat today, with no account, no
cloud and no GPU, and its check-then-render behaviour is the nearest existing analogue to
the critic.

What it needs installed: Python 3.11 or newer, Node.js 20.6 or newer, and `uv` or `pipx`;
then `topview-3d-cli doctor` and `topview-3d-cli browser ensure --with-deps` to fetch the
pinned Playwright and Chromium into the user cache. About 500 MB, no GPU required, and
it runs identically on the ProArt and on the Thor.

The day, in three blocks. Morning: build a scene from one of our own recipes — a prop
from the Infinigen path, one camera, a 24-frame push-in written as fcurves — and check
the JSON document round-trips through `apply`, `get` and `validate` unchanged. Midday:
run `evaluate` and `inspect nodes` and `inspect views` over that scene, and compare the
numbers against the critic's own checks on the same asset; the specific question is
whether topview's grounding and framing vocabulary covers what the critic already
measures, and where the two disagree, which is right. Afternoon: render frames and a
contact sheet, then convert one of our Theatre.js sequences into topview fcurves and
back, and record whether the compact format can carry a Theatre sequence without loss.

The deliverable is a short note in `builder-ide/docs/research`: the mapping between
topview's check vocabulary and the critic's, and a yes or no on the fcurve format as a
Theatre.js interchange, with the round-trip files kept as evidence.

### Shortlist 2: build-world three.js kit

This is the cheapest item in either phase, and it is the one that touches our actual
viewers. Our two viewers are three.js, and neither currently asserts that the same scene
renders the same way twice.

What it needs installed: Node.js 20.6 or newer and `npx playwright install chromium`.
Nothing else, no account, no cloud. The Thrixel connector is not needed and should not
be installed.

The day. Morning: point the capture harness at thor-world's viewer and at agent-world's
prismarine-viewer, and take a fixed set of named shots of each. Midday: render the same
scene twice and diff the frames; the question is whether our viewers are deterministic
enough that a diff is a usable signal rather than noise. If they are, commit a baseline
and flip one recipe value, and confirm the diff catches the change. Afternoon: decide
whether to port the harness into our own repository under Apache-2.0 and wire it into the
critic as an optional check, or to write our own smaller version, and record the choice
with the measurement that justified it.

The deliverable is the harness in our repo plus a baseline-gate entry in the critic's
checks, or a written reason not to.

### Shortlist 3: Vibe3DScene transactional tool calls

This is third because the tool itself is a poor fit — Blender as the runtime, Docker,
Redis, provider keys, one author, seven months stale. It is on the list because one
mechanism in it is worth copying, and because we already have the hard prerequisite it
needs: an aarch64 Blender 4.2 on the Thor, which its own download script does not know
how to fetch.

What it needs installed: Docker and Redis on the Thor, and its MCP server pointed at our
aarch64 Blender instead of a downloaded x86_64 one. No provider keys for a first pass —
the asset-generation tools are the part we are not evaluating.

The day. Morning: run the MCP server locally, connect our own MCP client to it, and
exercise ten tools by hand: `get_scene_info`, an object placement through
`execute_blender_code`, `render_from_camera`, `camera_set_pose`, `camera_act`,
`observe_scene_global`, `undo_last_snapshot` and the import paths. Midday: run one of our
own recipes through the Blender path and through the Infinigen path and compare the two
results — the question is whether Blender-as-runtime gives us anything our pipeline does
not already give us. Afternoon: port the transactional shape (`safe_mode`,
`rollback_on_guard_fail`, `validate_scene`) into one of our own write-path tools and
write it up.

The deliverable is the transactional pattern in our code, plus a written answer on
whether Blender-as-runtime earns a place at all. If the answer is no, the day still
returns the pattern, which is why it is worth a day and not a week.

### Tools left out of the shortlist

Prowl is the hardest call, because its command line is the best agent surface in either
phase. It is not shortlisted for a hands-on run because the engine is a C#/Vulkan Unity
clone that cannot produce our three.js world, and the part we want — a token-authenticated
loopback HTTP command line with an `eval` escape hatch, an `api` lookup and a
`play`/`input`/`screenshot` loop — is a shape we can write ourselves in an afternoon
against our own viewers. The extraction is recorded; the engine is not worth a build.

Torque3D is not shortlisted because adopting it means adopting TorqueScript, a 700 MB
tree, a project template with thirty-odd editors in it, and a `master` branch frozen in
2018. Its two transferable patterns, the editor-as-script-layer architecture and the
terrain brush set, are already ours in the first case (`bevy_egui` in the Bevy plan) and
are readable in an afternoon in the second.

Open-World-Builder is not shortlisted because it cannot run on the Thor at all — .NET 7
and x64-only native binaries — and has been frozen for two years and nine months with
one author. Its brush model and schema-first level format are worth reading; a build is
not.

MEP-SANDBOX-ENGINE is not shortlisted because there is no licence, which makes it a legal
question rather than a technical one, and the answer to a legal question is not a day of
engineering.

## Unverified items and deliberate exclusions

Phase 1 forbade installing, building and running, so the following are stated as open
rather than guessed:

- **Prowl's Graphite/Silica renderer on linux-arm64.** The natives live in the NuGet
  packages, not in this repository, so aarch64 renderer support is unconfirmed. The Thor
  does have Vulkan (device "NVIDIA Thor", API 1.4.329, driver 595.78), so the platform is
  not the blocker; the renderer is.
- **Torque3D on ARM64 Linux.** The root `CMakeLists.txt` sets `TORQUE_CPU_ARM64` when it
  detects an ARM processor with 64-bit pointers, and there are arm64-specific paths in
  the platform code, but the Linux CI builds x86_64 only. Compilable on the Thor is
  likely; proven is not.
- **Playwright Chromium on aarch64.** Playwright publishes linux-arm64 Chromium builds
  and both topview and the build-world kit need it, but we have not run one on the Thor.
- **MEP's actual source.** The archive could not be listed: this box has no `unrar`,
  `7z`, `bsdtar` or `unar`, and installing one would breach the read-only constraint. We
  read the RAR v5 headers directly and enumerated the file names.
- **Vibe3DScene's Blender addon body.** It is a submodule, not cloned at depth 1. Its
  licence (MIT, © 2025 Siddharth Ahuja) was confirmed through the API, and the upstream
  `ahujasid/blender-mcp` it extends is MIT as well.
- **Nsight Systems on the Thor.** The binary is installed (2025.6.3) but the target-side
  `nvidia-sysprof-daemon` has not been checked for, and no NVTX library is installed, so
  ranges would have no consumer yet.
- **The GPU on the Thor in a Vulkan context.** `vulkaninfo` reports one integrated
  device, "NVIDIA Thor", API 1.4.329, driver 595.78 — enough to answer the open question
  in the brief, but the Thor has no RT cores, so ray-traced paths are out regardless of
  the driver.

Two things are deliberately out of scope. We did not build or run anything, and we did
not adjudicate the MEP licence question, which needs someone with authority to talk to
its author. The `list2.md` material that is off-track — the AYN Thor handheld, the
monitor picture-by-picture setup, posture and glasses health advice, and the bathymetry
data — was skipped as the brief instructed, with the note that the bathymetry data could
seed real terrain later if the world wants a heightfield with a provenance.

## Reproducing the numbers

Every number in this document comes from one of four committed scripts, run on the box
described in the scope section:

| Script | What it produces | Needs | Time |
|---|---|---|---|
| `scripts/clone_repos.sh` | The seven phase-1 clones at `--depth 1` | git and network | 3 min |
| `scripts/clone_repos_phase1b.sh` | The fifteen phase-1b clones | git and network | 9 min |
| `scripts/github_api_meta.sh` | The GitHub REST metadata JSON per repository,[34] one blob per repo | `gh` with a token | 1 min |
| `scripts/summarize_api.py` | The activity table (commits, contributors, issues, releases, languages) | the JSON from the previous script | seconds |
| `scripts/survey_sizes.sh` | The working-tree sizes and tracked-file counts | the clones | seconds |

The Thor facts were read with read-only commands over SSH: `vulkaninfo --summary` for the
Vulkan device, `ip -br link` plus `/sys/class/net/*/speed` and `ethtool` for the network
ports, `ps`, `ss -ltnp` and `nvidia-smi` for resident services, and `powershell.exe
Get-NetAdapter -Physical` on the ProArt for the laptop's adapters.

## References

1. [topviewai/topview-3d-builder](https://github.com/topviewai/topview-3d-builder) — repository, commits 631c08c8fd352b4ff83df33aa9a74a4563f4674b (2026-10-17).
2. [topview-3d-cli.md — the CLI contract](https://github.com/topviewai/topview-3d-builder/blob/631c08c8fd352b4ff83df33aa9a74a4563f4674b/docs/topview-3d-cli.md) — commands, exit codes, runtime and offline rules.
3. [Topview 3D Builder README and licence](https://github.com/topviewai/topview-3d-builder/blob/631c08c8fd352b4ff83df33aa9a74a4563f4674b/README.md) — Apache-2.0 code, CC BY 4.0 built-in assets, OFL-1.1 fonts.
4. [thrixel/build-world](https://github.com/thrixel/build-world) — commits 362fd6641656dbffba108cf70ba7f1a1db60ca4f (2026-10-27).
5. [build-world README — the gauntlet loop and the cloud connector](https://github.com/thrixel/build-world/blob/362fd6641656dbffba108cf70ba7f1a1db60ca4f/README.md).
6. [Vibe3DScene `execute_blender_code`](https://github.com/3DSceneAgent/Vibe3DScene/blob/fed449b480e9a3d20858965a8b2e05fdb17fd946/mcp_server/tools/base.py) — transactional execution with safe_mode, rollback and validation.
7. [Vibe3DScene tool registry](https://github.com/3DSceneAgent/Vibe3DScene/blob/fed449b480e9a3d20858965a8b2e05fdb17fd946/mcp_server/tool_registry.py) — the 37 registered MCP tools.
8. [3DSceneAgent/blender-mcp-vision](https://github.com/3DSceneAgent/blender-mcp-vision) — the Blender addon submodule, MIT.
9. [FugthChat/MEP-SANDBOX-ENGINE](https://github.com/FugthChat/MEP-SANDBOX-ENGINE) — landing page, docs and the RAR archive, commits a92bc3de94429febeac731185baaf395e10e5072 (2025-12-06).
10. [GlaireDaggers/Open-World-Builder](https://github.com/GlaireDaggers/Open-World-Builder) — commits 5151a3dbc174b1d0c71a113ccef9277ebfc38507 (2024-02-10).
11. [Open-World-Builder `core/Core/Plugin.cs`](https://github.com/GlaireDaggers/Open-World-Builder/blob/5151a3dbc174b1d0c71a113ccef9277ebfc38507/core/Core/Plugin.cs) — the empty plugin class.
12. [TorqueGameEngines/Torque3D](https://github.com/TorqueGameEngines/Torque3D) — commits 4c44642aab32cf79be4f66966d49fd74ab18e221 (2026-09-25).
13. [Torque3D `Templates/BaseGame/game/tools/main.tscript`](https://github.com/TorqueGameEngines/Torque3D/blob/4c44642aab32cf79be4f66966d49fd74ab18e221/Templates/BaseGame/game/tools/main.tscript) — the F10 binding to `fastLoadGUIEdit`.
14. [Torque3D `Engine/source/console/telnetConsole.cpp`](https://github.com/TorqueGameEngines/Torque3D/blob/4c44642aab32cf79be4f66966d49fd74ab18e221/Engine/source/console/telnetConsole.cpp) — the remote console and `Con::smConsoleInput`.
15. [Torque3D engine overview](https://torque3d.org/engine/) — the vendor's description of the in-game editor suite.
16. [ProwlEngine/Prowl](https://github.com/ProwlEngine/Prowl) — commits 59e7afe1248619f10277164d575b20122c842378 (2026-11-01).
17. [Prowl editor CLI commands](https://github.com/ProwlEngine/Prowl/blob/59e7afe1248619f10277164d575b20122c842378/Prowl.Editor/Cli/CliEditorCommands.cs) — the command set behind `prowl`.
18. [Prowl.Aperture on NuGet](https://www.nuget.org/packages/Prowl.Aperture) — the engine libraries, MIT.
19. [NVIDIA/game-agent-sdk](https://github.com/NVIDIA/game-agent-sdk) — commits 9aa6e1c59d9fd0ffda7d4cdc046f22cf85c00cd0 (2026-06-15).
20. [Game Agent SDK agent deep dive](https://github.com/NVIDIA/game-agent-sdk/blob/9aa6e1c59d9fd0ffda7d4cdc046f22cf85c00cd0/docs/sphinx/source/agent-deep-dive.md) — transient, redacted, preamble, window-start, cancellation and serialisation semantics.
21. [NVIDIA/ACE](https://github.com/NVIDIA/ACE) — samples and workflows, commits 92a0ac1af1644429e9b3639985ebcdb9a824d2a6 (2025-06-26).
22. [NVIDIA-RTX/NVIGI](https://github.com/NVIDIA-RTX/NVIGI) — the In-Game Inferencing SDK, commits c1213a4bde80e26e49f475212203a3e08b49f94a (2026-08-07).
23. [NVIDIA-RTX/nvigi_godot_extension](https://github.com/NVIDIA-RTX/nvigi_godot_extension) — Apache-2.0 GDExtension binding NVIGI to Godot, commits da03e74f6e59f67af5ae175e93fa90713efe60e2 (2026-09-14).
24. [godotengine/godot](https://github.com/godotengine/godot) — 4.8.0-beta, commits 95c0fa5fe8a019adc29d074c16b64469b04571f7 (2026-10-30).
25. [Godot 4.7.2 stable builds](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable) — the official linux.arm64 binaries.
26. [NVIDIA/NVTX](https://github.com/NVIDIA/NVTX) — Apache-2.0 with LLVM Exceptions, commits b20b676e62e09621bc8dddc62e5596908c104d06 (2026-08-18).
27. [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) and [open-telemetry/opentelemetry-cpp](https://github.com/open-telemetry/opentelemetry-cpp).
28. [Thor Nsight Systems installation](https://developer.nvidia.com/) — the binary installed on the Thor, version 2025.6.3, with no public source repository.
29. [gorakhargosh/watchdog](https://github.com/gorakhargosh/watchdog) — Apache-2.0, commits 38cbb3bf3df04a194c211cd5ca89e943e057f638 (2026-11-01).
30. [input-leap/input-leap](https://github.com/input-leap/input-leap) — GPL-2.0 with an OpenSSL exception, commits 34a34fb20b93113a6b26052cb5a54f9be2327775 (2025-11-28).
31. [vllm-project/vllm](https://github.com/vllm-project/vllm) — Apache-2.0, commits 16d667348d91ae010cb3cc9d4d6a5b7908a717a9 (2026-11-01).
32. [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) — GPL-3.0, commits 17ff1dcce963bd9f23095ec9b28febbfc4db8388 (2026-11-01); the `comfyanonymous/ComfyUI` path now redirects to this organisation, 144 501 stars.
33. [grpc/grpc](https://github.com/grpc/grpc) — Apache-2.0, commits df3dd4dcb1409c826341a0df6eb808f741e58dea (2026-10-30).
34. [GitHub REST API — get a repository](https://docs.github.com/en/rest/repos/repos#get-a-repository) — the metadata source for the activity numbers, read on 2026-11-01.
