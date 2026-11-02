# RESULT — in-game building tools, phase 1 and phase 1b (2026-11-01)

## What was asked and what was done

Casey asked for the eight tools on `list.md` to be investigated thoroughly, with the
list's descriptions treated as claims to check. `BRIEF-2.md`, filed at 17:11 the same
day, added a second scope: the inference, tracing, transport and supervision seams
around the Thor/ProArt split, plus `list2.md`'s rewind-and-supervision ideas.

Twenty-one repositories were cloned at `--depth 1` and read — 2 171 724 KB of working
tree, 67 391 tracked files. Nothing was installed, built or executed; the only commands
run against third-party trees were `git`, `grep`, `du` and file reads. The Thor was
reached read-only over SSH for three questions: its Vulkan device, its network ports and
which services are resident.

The full write-up is `docs/ingame-building.md`: a section per tool with the seven fields
the brief asked for, a comparison table, a fit summary (use as is / extract / skip), the
phase-1b findings, a rewind-and-supervision map of `list2.md`'s ideas, a ranked phase-2
shortlist with one-day test plans, and the items that could not be verified without
running anything.

## Key numbers

- **4 of 8** claims in `list.md` fail against the code: MEP is a landing page plus a RAR
  with no licence file; Open-World-Builder's `Plugin` class is empty and it targets
  EOL `net7.0`; Prowl's ImGui package reference is commented out; Topview's MCP path is
  a hosted OAuth server while only its CLI path is local.
- **3 of 8** have a bus factor of one (Vibe3DScene 87/87 commits, MEP 20/20,
  Open-World-Builder 47/47). Prowl's lead author holds 4 669 of 5 918.
- **1 licence gap**: MEP-SANDBOX-ENGINE has no LICENSE file, its landing page claims
  MIT and free commercial use, and the same page sells a $5 copy. Treat as closed.
- **1 branch trap**: Torque3D's `master` has been frozen since 2018-04-05; the live
  branch is `development` (last commit 2026-09-26).
- **0** of the eight is a good base to adopt: our stack is web three.js, and the tools
  that carry world semantics are C#/C++ engines, while the two with the best agent
  surfaces (Topview's CLI, Prowl's HTTP command line) carry no world semantics.
- **Thor**: four 10 GbE ports, all reporting "Link detected: no"; the only active link
  is 2.4 GHz Wi-Fi at −68 dBm; Vulkan device "NVIDIA Thor", API 1.4.329, driver 595.78;
  Nsight Systems 2025.6.3 already installed; `nvidia-smi` shows no compute processes, so
  the no-resident-LLM rule is currently being kept.
- **ProArt**: ASUS ProArt PX13 HN7306WU, MediaTek Wi-Fi 7 only — `Get-NetAdapter
  -Physical` returns no wired Ethernet adapter, so the proposed direct 10 GbE cable
  cannot be made as written. It needs a USB4 10GbE adapter, Cat6a, and a fixed address
  on `mgbe0_0`.

## The phase-2 shortlist

Full test plans, with what each needs installed, are in `docs/ingame-building.md`.
Phase 2 needs Casey's OK before anything is installed.

1. **topview-3d-builder** — the only tool driveable end to end with no account, no
   cloud and no GPU. The day: build a scene from one of our recipes, run `evaluate` and
   `inspect views` over it, and compare its grounding and framing numbers against the
   critic's own checks on the same asset; then convert a Theatre.js sequence into
   topview fcurves and back. Needs Python 3.11+, Node 20.6+, `uv` or `pipx`, then
   `topview-3d-cli doctor` and `browser ensure`.
2. **build-world's three.js kit** — cheapest item in either phase, and it touches our
   actual viewers, both of which are three.js. The day: drive the capture harness
   against thor-world's viewer and agent-world's prismarine-viewer, check whether the
   same scene renders identically twice, and decide whether to port the harness under
   Apache-2.0 and gate the critic on a baseline diff. Needs Node 20.6+ and Chromium.
3. **Vibe3DScene** — shortlisted only for one mechanism: transactional tool execution
   (`safe_mode`, `rollback_on_guard_fail`, `validate_scene`). The day: run its MCP
   server against our own aarch64 Blender 4.2, exercise ten tools, then port the
   transactional shape into one of our write-path tools. Needs Docker, Redis, and
   pointing the server at our Blender build instead of the script's x86_64 download.

Not shortlisted: Prowl (best agent surface, wrong runtime — take the pattern, not the
engine), Torque3D (TorqueScript, 700 MB, a 2018 `master`), Open-World-Builder (.NET 7,
x64-only natives, frozen 2.7 years, one author), MEP (no licence).

## What is committed

| Commit | Contents |
|---|---|
| `4d1e505` | Research scaffolding: `scripts/clone_repos.sh`, `scripts/github_api_meta.sh`, `scripts/summarize_api.py`, `.gitignore`, the first `NOTES.md` entries |
| `a6db980` | `docs/ingame-building.md` — the full survey, plus `scripts/clone_repos_phase1b.sh` and `scripts/survey_sizes.sh` |
| (final commit) | `RESULT.md`, the final `NOTES.md` entries, `scripts/github_api_meta_phase1b.sh`, and the heading-hierarchy pass on the report. Its hash is reported at the end of the session response, since a commit cannot state its own hash. |

The 21 cloned repositories (2.07 GB) are deliberately **not** committed; `.gitignore`
excludes `src/` and `.research/`, and `scripts/clone_repos.sh` plus
`scripts/clone_repos_phase1b.sh` recreate them from scratch. Every number in the report
comes from a committed script: `scripts/survey_sizes.sh` for sizes and file counts,
`scripts/github_api_meta.sh` for the GitHub REST activity figures, and
`scripts/summarize_api.py` for the table they produce.

## What is left and the risks

Unverified, because phase 1 forbade installing and running: Prowl's linux-arm64
renderer natives (they live in NuGet, not the repo); Torque3D's ARM64 Linux build (the
CMake detects it, the CI does not exercise it); Playwright Chromium on aarch64; the body
of MEP's source inside the RAR (no `unrar`, `7z` or `bsdtar` on this box); and the
Vibe3DScene Blender addon (a submodule, licence confirmed via the API).

The risks in the recommendations are mostly legal and personal rather than technical.
MEP is a licence question, not an engineering one, and it needs someone with authority to
talk to its author. The bake daemon would introduce a third-party dependency that
`builder-ide/CLAUDE.md` says needs Casey's OK before it lands, and its "watchdog" name
would collide with the resident-memory watchdog we already run. The Game Agent SDK's
conversation lifecycle is worth porting, but its deployment wants a resident model on the
Thor, which the standing rule from 2026-10-31 forbids; only the method is ours to take.
And the single cheapest change in the whole survey is not a tool at all: a USB4 10GbE
adapter on the ProArt would take the world off a 2.4 GHz radio.
