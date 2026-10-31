# BAKEOFF.md — the engineer bake-off

**Date:** 2026-10-30 · **Box:** the Thor itself (Jetson AGX Thor, aarch64) · **Status:** research and design only.

> The brief's rule was respected in full: **nothing was installed, no contender was run, no shared environment was touched.** Every claim below is (a) measured on this Thor in this session, (b) read from a primary source, or (c) quoted from a file in this project. Sources are linked inline and collected in §8. Claims I could not verify are listed in §7 — please read that before quoting any of this.

---

## 0. What this bake-off is actually for

The vision puts the engineer behind **one adapter**: *in* — a work order and a sandbox branch; *out* — a commit and test evidence (`~/src/builder-ide/docs/vision.md:78`). The core-service brief makes the same seam explicit: "The engineer adapter: the one interface every coding/generative engineer implements (input: work order + sandbox branch; output: commit + evidence)" (`~/lm-wt/spec-core/BRIEF.md:9`).

So the question is **not** "which CLI is nicest". It is:

> Which contender can be *driven by a machine*, into a *sandbox*, and produce *evidence a merge gate will trust* — on a 122 GB aarch64 box with no x86 in sight, at a cost we can afford overnight?

Every section below is written against that seam.

### 0.1 The box, verified 2026-10-30 (measured on this Thor)

| Property | Value | How verified |
|---|---|---|
| OS / kernel | Ubuntu 24.04.5 LTS (noble), `6.8.12-1021-tegra` | `/etc/os-release`, `uname -a` |
| CPU | 14 cores, `aarch64` | `lscpu` |
| Memory | 122 GB unified (tegrastats: `RAM 45714/125749MB`) | `free -g`, `tegrastats` sample |
| GPU | NVIDIA Thor, driver 595.78, Blackwell cc 11.0, CUDA 13.2 | `nvidia-smi`, `thor/build-bpy.sh:36` |
| Docker | 29.9.2, server architecture **aarch64** | `docker info` |
| Python | 3.12.3 system; 3.11.13 built by the port spike | `python3 --version`, `thor/build-bpy.sh:118` |
| Node | 18.19.1 system; nvm **22.23.4** and **24.22.2** | `node --version`, `ls ~/.nvm/versions/node` |
| Git / sandbox | git 2.43.0 (worktrees OK), `bwrap` at `/usr/bin/bwrap`, `unshare` present | `git --version`, `command -v` |
| Disk | 339 GB free on `/`; 1.9 TB external SSD at `/media/caseydigennaro/TOSHIBA EXT` | `df -h`, `builder-ide/CLAUDE.md:28` |
| Model services | **not running** — nothing listens on 127.0.0.1:8001 or :8005 | `ss -ltn`, `curl /v1/models` → empty |

Two of those rows are load-bearing for what follows:

1. **`nvidia-smi` reports no memory on this Thor.** `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader` → `[N/A]`. `utilization.gpu` reported `0 %` while idle (so it could not be confirmed under load), while `clocks.gr` (315 MHz), `power.draw` (2.36 W) and `temperature.gpu` (29) *do* work. This is a real defect in the port's measurement wrapper — work order **WO-4**.
2. **The Thor's local coder is not resident.** `~/.pi/agent/models.json` configures two OpenAI-compatible endpoints — `http://127.0.0.1:8001/v1` serving `Qwen3-Coder-30B-A3B-Instruct` and `http://127.0.0.1:8005/v1` serving `Muse-Glimmer-30B` — but neither is listening, because "skald (voice) and last-mile's model services were stopped and **disabled at boot**" (`~/src/builder-ide/CLAUDE.md:25`). Any "free local lane" in this bake-off therefore has a *start step* and a *GPU-memory price* (§3.7).

### 0.2 The seats already in this house

The project already runs agents this way; the harness should reuse these contracts rather than invent new ones.

| Seat | Invocation observed on this box (`ps`) | Install |
|---|---|---|
| zcode | `zcode -p '<prompt>' --cwd <dir>` | `zcode-app-cli` 3.16.2-38, nvm node v24.22.2 |
| mcode | `mcode exec --cwd <dir> --timeout 240m '<prompt>'` (with `MCODE_LLM_FIRST_EVENT_TIMEOUT_MS=600000`) | `@minimax-ai/code` 0.6.13 under `~/.minimax-code` |
| pi | `pi --print '<prompt>' --cwd <dir> --json` | `@earendil-works/pi-coding-agent` 1.4.0 |

The house prompt pattern is fixed: *"Read BRIEF.md in this directory, including every addendum at the end, and carry it out exactly… Only modify files inside this directory. Do not start sub-agents. Answer in English."* — a free-text brief in a directory is this project's native work-order format, and it is what every contender must be able to consume.

---

## 1. The contenders, one by one

### 1.1 Claude Code — the hard-order seat

**Licence.** Proprietary. The repository's `LICENSE.md` reads: "© Anthropic PBC. All rights reserved. Use is subject to Anthropic's [Commercial Terms of Service]"; the npm package declares `license: "SEE LICENSE IN README.md"`. It cannot be vendored or redistributed — every seat must be a per-user install.

**Headless / non-interactive.** First-class, and the most controllable of the lot ([CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)):

```
claude -p "<query>" --output-format json|stream-json|text --verbose
       --input-format stream-json        # streaming input
       --max-turns N                     # agentic-turn ceiling, exits non-zero
       --max-budget-usd X                # spend ceiling (print mode only)
       --fallback-model sonnet,haiku     # retry chain when the primary is busy
       --permission-mode plan|acceptEdits|bypassPermissions
       --allowedTools / --disallowedTools / --tools
       --settings <file> --mcp-config <json> --add-dir <path>
       --append-system-prompt <text> --agent <name> --agents <file>
       --fork-session --resume --session-id
       --bg --exec '<cmd>'               # background jobs
```

`--output-format stream-json --verbose` is the machine-readable channel the adapter should use; `--max-turns` and `--max-budget-usd` are exactly the two budgets §3.2 wants. Note the docs' own caveat: the spend cap is a **client-side estimate** that "can differ from your bill", spend can pass the cap, and enforcement of the subagent/background behaviours needs **v2.1.217+**.

**Sandboxing.** The strongest in-process-and-OS combination: Claude Code ships an **OS-enforced Bash sandbox** — bubblewrap on Linux, Seatbelt on macOS — with **filesystem isolation** and **network isolation** (allowed domains, per-command allow-lists in auto mode), plus `excludedCommands`, a "strict sandbox mode", and managed settings that enforce it org-wide ([sandboxing docs](https://docs.anthropic.com/en/docs/claude-code/sandboxing)). The same doc lists the failure modes that matter here: *"Bubblewrap fails to start inside a container"*, *"Commands are refused with Sandbox is required"*, *"git over SSH fails with the sandbox"*.

**Model flexibility.** Anthropic models only (Claude Opus 5.5 / Sonnet 5.5 / Haiku 5.5 in the current catalogue, plus the Mythos preview), optionally through AWS-native (Bedrock), Google Cloud Vertex AI / Agent Platform and Azure-native deployments ([third-party integrations](https://docs.anthropic.com/en/docs/claude-code/third-party-integrations)). **No arbitrary OpenAI-compatible endpoint** — Claude Code cannot be pointed at the Thor's local Qwen3-Coder-30B.

**Cost model.** Pure per-token API ([pricing](https://docs.anthropic.com/en/docs/about-claude/pricing)):

| Model | Input / MTok | Output / MTok | Cache write 5-min / 1-hour | Cache read |
|---|---|---|---|---|
| Claude Opus 5.5 | $4 | $20 | $5 / $8 | $0.20 |
| Claude Sonnet 5.5 | $2 | $10 | $2.50 / $4 | $0.10 |
| Claude Haiku 5.5 | $0.10 ($0.50 >100k tok) | $0.50 ($2.50 >100k) | $0.125 / $0.20 | $0.01 |

Two pricing facts worth carrying into the harness: models from Claude 4.7 onward use a **newer tokenizer that produces ≈30% more tokens** for the same text, and prompt caching multipliers are 1.25× (5-min write) / 2× (1-hour write) / 0.1× (read).

**Runs on this aarch64 Thor? YES.** The native installer detects `arm64|aarch64` → `arch=arm64` and fetches a `linux-arm64` (or `linux-arm64-musl`) binary ([claude.ai/install.sh](https://claude.ai/install.sh), lines 122–144). The npm route requires **node ≥ 22.0.0** (published `engines`) — the system node here is 18.19.1, so a seat must pin an nvm node (22.23.4 or 24.22.2). The repo README still advertises "Node.js 18+", which is stale relative to the published package.

**Known failure modes.** Node version mismatch on the npm path; bubblewrap vs container nesting (our sandbox *is* a container — this will bite); rate limits on the Anthropic API; the spend cap being an estimate; and no local-model path, so it can never be the "free" seat.

### 1.2 zcode (ZCode) — the bulk seat, already here

**Licence.** The first-party source is **Apache-2.0** ([zai-org/ZCode](https://github.com/zai-org/ZCode) `LICENSE`: "Apache License, Version 2.0"). The *installed* seat is the community CLI `zcode-app-cli` v3.16.2-38, whose own code is **MIT** — but its `docs/THIRD_PARTY_CONTENT.md` is explicit: "The npm package also contains upstream code and dependencies; **the MIT declaration in `package.json` does not replace their terms**", and the runtime is "extracted from Desktop release artifacts, rather than building that source tree" (pinned by URL and SHA-512 in `zcode-runtime.lock.json`). Practically: *client MIT, runtime Apache-2.0 plus separate third-party terms — read the notices before shipping it inside anything.*

**Headless / non-interactive.** `zcode -p '<prompt>' --cwd <dir>` (observed live in this box's process table). The CLI's own flag table in `bin/zcode.js` includes `--print/-p`, `--cwd`, `--json`, `--yes`, `--dry-run`, `--options-file`, `--resume`, `--no-browser`, `--verbose`, `--disallowed-tools`, `--json`. `--print` is the machine channel.

**Sandboxing.** **None.** The CLI has an in-process permission model — `~/.zcode/cli/setting.json` carries `permission.mode` (`build`), `allowedTools`, `disallowedTools`, `autoApproveHighRisk`, `allowMediumRiskInAuto`, plus `network.timeout` and MCP server config — but that is *gating*, not OS isolation. The harness must supply the container/bwrap boundary.

**Model flexibility.** A provider registry where a provider declares `api.type: "openai-chat-completions"`, `baseUrl`, `headers` and `apiKey` (`provider.example.json`), i.e. **a local OpenAI-compatible endpoint is a configuration, not a fork**. This box's zcode currently runs on `providerId: account:zai-individual-coding-plan` (seen in `~/lm-wt/models.out`).

**Cost model.** A **coding-plan subscription**, not per-token billing — which means the failure mode is *rate limiting*, not spend. The log captured in `~/lm-wt/models.out` shows exactly that: `ProviderBusinessError … [1302][Rate limit reached for requests]`, `providerKind: anthropic`, `responseStatus: 429`, `retry-after: 5`. Treat zcode as *quota-constrained*: fine for bulk, wrong for the critical path.

**Runs on this aarch64 Thor? YES — already proven**, running right now on aarch64 under nvm node v24.22.2.

**Known failure modes.** Provider business errors / 429s on plan capacity; the bundled provider catalog has its own update channel ("ZCode Built-in unchanged revision=43 source=CDN" in `~/lm-wt/ig-spike.out`); node ≥ 22.19 required (`engines`); `--print` still starts a full runtime, so startup cost is paid per run.

### 1.3 mcode (MiniMax Code) — the second bulk seat

**Licence.** **MIT** (npm `@minimax-ai/code`, `license: MIT`; latest 0.7.4, this box has 0.6.13, installed under `~/.minimax-code` with its own release pointer and `install.json`).

**Headless / non-interactive.** `mcode exec --cwd <dir> --timeout 240m '<prompt>'` (observed live). `exec` is the subcommand; `--timeout` is a wall-clock ceiling, and `MCODE_LLM_FIRST_EVENT_TIMEOUT_MS` (600000 in the house launcher) exists because the first model event can be slow. That combination is the single most useful thing about mcode for this project: **it has a first-class timeout**, which is exactly the budget primitive the adapter needs.

**Sandboxing.** In-process tool gating only (this session's own surface: read/edit/bash plus optional tools). No OS sandbox → harness-provided.

**Model flexibility.** MiniMax-hosted models (this session runs on MiniMax M3.1-Flash). The `~/.pi/agent/models.json` local endpoints belong to **pi**, not mcode.

**Cost model.** Subscription/quota, like zcode. Model-choice breadth is the weak spot, so mcode's job in the lineup is *volume*, not variety.

**Runs on this aarch64 Thor? YES — already proven**, running right now on aarch64.

**Known failure modes.** First-event timeout (hence the env knob); long-session context compaction; interactive permission prompts (avoided by `exec`); the local model servers are down, so anything expecting a local endpoint fails (they are for pi).

### 1.4 aider — the free local lane

**Licence.** **Apache-2.0** ([Aider-AI/aider](https://github.com/Aider-AI/aider)).

**Headless / non-interactive.** Purpose-built for it ([options](https://aider.chat/docs/config/options.html), [scripting](https://aider.chat/docs/scripting.html)):

```
aider --message "<text>"            # or --message-file FILE (-m / -f)
       --yes / --yes-always         # never prompt
       --exit                       # one shot
       --no-git                     # work outside a repo
       --commit                     # commit and exit
       --apply FILE                 # apply a patch file
       --test-cmd '<cmd>' --test    # run tests as part of the loop
       --model <provider>/<name>    # e.g. openai/Qwen3-Coder-30B-A3B-Instruct
       --edit-format <fmt>          # diff / udiff / editor / whole
       --architect                  # plan-then-code, two models
       --show-model-costs --no-pretty --no-stream --no-check-update
```

**Sandboxing.** **None built in** — aider edits files in the CWD and runs commands itself. The official images are `paulgauthier/aider` and `paulgauthier/aider-full` (`docker run -it --user $(id -u):$(id -g) --volume $(pwd):/app paulgauthier/aider --openai-api-key $KEY ...`).

**Model flexibility. The best of the lot.** "Aider can connect to any LLM which is accessible via an OpenAI compatible API endpoint" — set `OPENAI_API_BASE=<endpoint>` and pass `--model openai/<model-name>` ([openai-compat](https://aider.chat/docs/llms/openai-compat.html)). Also Anthropic, OpenAI, Bedrock, Vertex, Azure, Groq, OpenRouter, Ollama, LM Studio, DeepSeek, Gemini, xAI, Cohere.

**Cost model.** Per-token, and it does the arithmetic for you (`--show-model-costs`). Against the Thor's local coder the marginal cost is electricity.

**Runs on this aarch64 Thor? YES.** `aider_chat-0.86.2-py3-none-any.whl` is a **pure-Python wheel** (no compiled extension to rebuild), and both Docker images publish **linux/amd64 + linux/arm64** (verified by manifest).

**Known failure modes.** The important one is **the project is close to dormant**: the GitHub API reports the last push on **2026-05-22**, the latest GitHub release is **v0.86.0**, and PyPI carries 0.86.2 — so aider is a maintenance-mode tool, not a moving target. Second: a 30B local model has a real context ceiling, and aider's SEARCH/REPLACE edit format degrades on large files and on models that paraphrase the context. Third: unknown models trigger aider's "model warnings" and need `--model-settings-file`.

### 1.5 OpenHands — the isolated lane

**Licence.** **MIT** ([OpenHands/OpenHands](https://github.com/OpenHands/OpenHands)); the PyPI `openhands` 1.16.0 wheel is MIT (`py3-none-any`), and the Canvas npm package `@openhands/agent-canvas` 1.34.0 is MIT.

**Headless / non-interactive.** `openhands --headless --task "<task>" [--output result.jsonl]`, with a JSONL event stream for machine consumption ([headless docs](https://docs.all-hands.dev/usage/how-to/headless-mode)). The modern shape is Canvas + agent-server: `npm install -g @openhands/agent-canvas` (node ≥ 24), then `OH_CONVERSATION_RUNTIME=docker agent-canvas` for per-conversation Docker sandboxes — "Each container mounts its conversation's workspace and persisted state… Conversations using the same host workspace still share those files; **choose separate directories or worktrees to avoid conflicting edits**" ([OpenHands README](https://github.com/OpenHands/OpenHands)). That sentence is the harness spec, written by the vendor.

**Sandboxing. The best of the lot.** Real per-conversation container sandboxes, each with its own Agent Server and tools; plus VM and remote backends; enterprise features include warm pools, Sysbox, workspace isolation and a command allow/deny-list.

**Model flexibility.** LiteLLM-based: "This can be any model that is supported by litellm", with **custom model + base URL + API key**, and dedicated guides for OpenAI, Bedrock, Azure, Gemini/Vertex, Groq, Moonshot, OpenRouter, **local LLMs** and LiteLLM proxy ([LLM settings](https://docs.openhands.dev/openhands/usage/settings/llm-settings)).

**Cost model.** Per-token through LiteLLM; local models free.

**Runs on this aarch64 Thor? YES.** `ghcr.io/openhands/openhands:latest` and `ghcr.io/openhands/agent-canvas:1.34.0` both publish **linux/amd64 + linux/arm64** (verified by `docker manifest inspect`). Note the images **moved from Docker Hub** — `openhands/openhands` on Docker Hub now 404s, which will break any stale runbook.

**Known failure modes.** Heaviest machinery of any contender (Canvas + agent-server + Docker + uv); node ≥ 24 for Canvas; a per-conversation container means image pull + boot cost per conversation, which is fatal for small orders; and — the one that matters most for us — OpenHands' own Agent Canvas lists **ACP agents** (Claude Code, Codex, Gemini, **Pi**, OpenCode) as backends it can drive. That makes OpenHands *both* a contender and a possible host for the others.

### 1.6 Goose (Block → AAIF) — the MCP-native runtime

**Licence.** **Apache-2.0** ([aaif-goose/goose](https://github.com/aaif-goose/goose) — the repo moved from `block/goose`; ★55,997; last push 2026-10-31).

**Headless / non-interactive.** Mature and documented ([headless tutorial](https://goose-docs.ai/docs/tutorials/headless-goose), [CLI commands](https://goose-docs.ai/docs/guides/goose-cli-commands)):

```
goose run -t "<task>" --no-session        # stateless, one shot
goose run -t "<task>" --with-builtin developer --debug --max-turns N
goose session --resume --fork --name <p> # resumable, forkable
goose session export --format json|md|yaml
```

`--no-session` is exactly the "cold run" the overnight queue wants; sessions are exportable for the morning report.

**Sandboxing.** MCP-native: extensions *are* MCP servers, so the extension set is the tool surface. There is no OS isolation of its own — MCP servers run with the process's privileges. Isolation must again come from the harness.

**Model flexibility.** 15+ providers — Anthropic, OpenAI, Google, Ollama, OpenRouter, Azure, Bedrock — plus **local OpenAI-compatible endpoints** (`OPENAI_BASE_PATH`, Docker Desktop/CE local models, Ollama, Lemonade, Atomic Chat) ([providers](https://goose-docs.ai/docs/getting-started/providers)). It can also drive **Claude Code / Codex / Gemini subscriptions through ACP**.

**Cost model.** Per-token per provider; local free.

**Runs on this aarch64 Thor? YES.** Release **v1.57.0** ships `goose-aarch64-unknown-linux-gnu.tar.gz`, `goose-aarch64-unknown-linux-musl.tar.gz`, arm64 `.rpm`s — and, notably, **`goose-acp-aarch64-unknown-linux-gnu.tar.gz`**. Goose already ships an **ACP** build, which speaks to the vision's "Zed and Theia are front ends onto the engineer's work (via ACP), not backends" (`vision.md:82`).

**Known failure modes.** Rust binary → pick glibc or musl deliberately (both are published). MCP extensions frequently need Node (`npx -y …`), so Node must be on `PATH` inside the sandbox. `goose configure` is **interactive** — the harness must pre-write the config file, not run the wizard. The built-in `developer` extension grants broad shell access.

### 1.7 The other strong open contenders

| Contender | Licence | Headless form | arm64 on the Thor | Why it matters here |
|---|---|---|---|---|
| **OpenCode** ([anomalyco/opencode](https://github.com/anomalyco/opencode), MIT, ★223k) | MIT | `opencode run "<prompt>"` (non-interactive), `--model`, `--agent`; `opencode serve` for a headless API server ([CLI docs](https://opencode.ai/docs/cli/)) | **Yes** — npm `opencode-ai` declares `os: darwin/linux/win32`, `cpu: arm64/x64` | The strongest MIT alternative to Claude Code, and already an ACP agent OpenHands can host |
| **Codex CLI** ([openai/codex](https://github.com/openai/codex), Apache-2.0, ★132k) | Apache-2.0 | `codex exec --cd <wt> --sandbox read-only\|workspace-write\|danger-full-access --ask-for-approval on-request\|never -m <model>`; `--oss` for a **local** open-source provider; `--yolo` to bypass both ([CLI reference](https://developers.openai.com/codex/cli/reference/)) | npm `@openai/codex` (node ≥16) installs a native binary | The cleanest *explicit* sandbox-policy surface of any contender (three named policies) |
| **Gemini CLI** ([google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli), Apache-2.0, ★108k) | Apache-2.0 | `gemini -p "<prompt>"`; MCP-native | npm `@google/gemini-cli`, node ≥20 → fine on nvm 22/24 | MCP-native, Google models, plus a local compatible endpoint |
| **Qwen Code** ([QwenLM/qwen-code](https://github.com/QwenLM/qwen-code), Apache-2.0) | Apache-2.0 | Gemini-CLI-derived non-interactive mode | npm ships `@oven/bun-linux-aarch64` → **native aarch64** | Another cheap bulk seat with good tool-calling |
| **Kimi CLI** ([MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli), Apache-2.0) | Apache-2.0 | CLI, agent mode | Node CLI | Vendor diversity for the bulk lane |
| **SWE-agent** ([SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent), MIT) | MIT | Its own batch/config runner | Python | The best-documented harness in the literature — useful as a *reference design* for §3, not as a seat |
| **pi** (`@earendil-works/pi-coding-agent` 1.4.0) | **MIT** | `--print, -p  Non-interactive mode: process prompt and exit`; output modes text/json/rpc; `--cwd`, `--json`, `--base-directory`, `--exclude-tools`, `--approve`, `--fork`, `--export`, `--ctx-size` (read from the local bundle) | **Yes — already installed here**, already pointed at the local endpoints | The free local seat, ready to drive; same house (`@earendil-works/pi`) also supplies the TUI that `zcode-app-cli` wraps |
| **Crush** ([charmbracelet/crush](https://github.com/charmbracelet/crush)) | *unverified* | TUI agent | Go binary | Listed for completeness; **do not cite a licence** — see §7 |

### 1.8 The comparison that matters

| | Headless contract | Sandbox | Local OpenAI-compat | arm64 on Thor | Licence | Cost shape | Drove it here |
|---|---|---|---|---|---|---|---|
| Claude Code | excellent (`-p`, `--max-turns`, `--max-budget-usd`, stream-json) | **OS-level** (bwrap + net isolation) | ✗ | ✓ native binary | proprietary | per-token | not yet |
| zcode | good (`-p`) | ✗ | ✓ (config) | ✓ **running now** | Apache-2.0 (runtime) | plan/quota | ✓ |
| mcode | good (`exec`, `--timeout`) | ✗ | ✗ | ✓ **running now** | MIT | plan/quota | ✓ |
| aider | good (`-m`, `--exit`, `--test-cmd`) | ✗ | **✓ best** | ✓ pure-python wheel | Apache-2.0 | per-token / free | not yet |
| OpenHands | good (`--headless --task`, JSONL) | **✓ containers** | ✓ (LiteLLM) | ✓ arm64 images | MIT | per-token | not yet |
| Goose | good (`goose run --no-session`) | ✗ (MCP only) | ✓ | ✓ aarch64 tarballs | Apache-2.0 | per-token | not yet |
| OpenCode | good (`opencode run`) | ~ | ✓ | ✓ native arm64 | MIT | per-token | not yet |
| Codex CLI | good (`codex exec`) | ✓ named policies | ✓ via `--oss` | ✓ | Apache-2.0 | per-token | not yet |

---

## 2. The work orders — six, covering the brief's five examples

Drawn from this project's actual state. Four of the five come from a live, measured defect or a documented gap in `~/src/infinigen-thor`; the fifth comes from the vision's asset lane. **Every acceptance check is a command that a machine can run and that cannot be edited by the contender** (the check file is mounted read-only, outside the worktree).

Weighting used later: **H** = hard (multi-file, needs reading a build system), **M** = medium, **L** = light.

---

### WO-1 — Make the Thor bpy build reproducible, and write the spike report (weight: H)

**Where it comes from.** `~/src/infinigen-thor`, branch `thor-spike`. Three verified gaps:

1. `git status` shows **two untracked patches**: `?? thor/patches/blender-v4.2.0-ffmpeg61-av-input-buffer.patch` and `?? thor/patches/blender-v4.2.0-ffmpeg61-anim-movie.patch`. But `thor/build-bpy.sh:135-141` applies **every** `thor/patches/blender-*.patch` — so a fresh clone builds Blender **without** the FFmpeg-6.1 compatibility fixes and fails at compile time. The port is not reproducible from a clean clone.
2. `thor/SPIKE.md` **does not exist**, although the port brief demands it ("Write `thor/SPIKE.md`: what works, what was changed and why, timings with the box's state, every wall you hit, and a recommendation for phase 2").
3. `outputs/` is gitignored (`.gitignore:124`), so the proof artifacts the spike is required to cite are not in git at all.

**The order.** (a) Track both patches. (b) Add `thor/verify-port.sh`: for each patch, fetch the patched file from the **pinned upstream tag** (`v4.2.0`) from `raw.githubusercontent.com` and assert the patch still applies cleanly (`git apply --check` against that single file in a temp dir). (c) Write `thor/SPIKE.md` with what works, what changed and why, timings with the box's state beside every number, every wall, and the phase-2 recommendation — citing paths of the proof artifacts.

**Acceptance check** (runs in under a minute; deliberately *does not* require the 30–90 minute bpy build):

```bash
bash thor/verify-port.sh          # exit 0
bash -n thor/build-bpy.sh thor/install.sh thor/run-timed.sh   # exit 0
```

`verify-port.sh` must, and print one line per check:
- every `*.patch` on disk appears in `git ls-files thor/patches` (no untracked patches);
- for each patch, the upstream `v4.2.0` file it targets downloads and the patch applies cleanly to it;
- `thor/SPIKE.md` exists and contains the required sections (regex for `wall`, `timing`, `phase 2`);
- `thor/build-bpy.sh` and `thor/install.sh` are syntactically valid and still reference the patch glob.

**Why this is a good probe:** it needs build-script reading, git archaeology, an upstream lookup and disciplined documentation — but it is *fast* and *unambiguous*. The whole point of the project ("every 'works' claim carries its proof") is exactly what is being tested.

---

### WO-2 — A parametric rope-bridge generator in build123d, with a deterministic export (weight: H)

**Where it comes from.** The vision's asset lane: "**CAD-precise parts** (hinges, gears, machinery): the engineer writes parametric CAD code (e.g. CadQuery). Deterministic and parametric, so it is recipe-native: a small script, not a mesh" (`vision.md:140-142`). The project's own CAD research has already settled the tool choice: **build123d 0.13.0 (Apache-2.0) — "Adopt (primary)"**, with "explicit aarch64 support, verified wheels" and STEP+GLB export (`~/lm-wt/res-cad/REPORT.md:18`); `cadquery-ocp` 8.0.1.1.0 publishes `manylinux_2_28_aarch64` wheels for cp311–cp314 (verified on PyPI just now, 4 files).

**The order.** Add a parametric part to the builder-ide part library: a bridge plank-and-brace assembly driven by parameters (span, width, plank count, chamfer, material thickness), exported to **STEP** (and GLB), with unit tests, exposed as a recipe entry rather than a mesh (the house rule: "Store recipes, not meshes").

**Acceptance check** (`bakeoff/check_wo2.sh`, exit 0):

```bash
python3.12 -m venv .venv-cad && .venv-cad/bin/pip install -q build123d==0.13.0
.venv-cad/bin/python -m pytest tests/test_rope_bridge.py -q
.venv-cad/bin/python -m builder_ide.cad.rope_bridge --params fixtures/rope_bridge.json --out /tmp/a.step
.venv-cad/bin/python -m builder_ide.cad.rope_bridge --params fixtures/rope_bridge.json --out /tmp/b.step
```

must assert: the pytest suite is green; the STEP file exists, is > 1 KB, and **re-imports** with a bounding box and volume inside 1 % of the expected values computed from the parameters; and the two exports are **byte-identical**. The last assertion is the interesting one: STEP headers embed a timestamp, so a naive `cmp` fails — the check must compare a *canonicalised* digest (header stripped, or a hash of the tessellated geometry). That is deliberate: it forces the engineer to confront determinism, which the vision demands of every generated asset.

---

### WO-3 — Add a typed vocabulary entry to the core, with tests (weight: M)

**Where it comes from.** The core spec brief: `VocabularyEntry` is "typed, bounded params, taste notes, provenance", and the builders "change the recipe only through a closed, typed vocabulary" (`~/lm-wt/spec-core/BRIEF.md:8`, `vision.md:63`). **Honest caveat:** `~/src/builder-ide` currently contains **only docs** (`CLAUDE.md`, `README.md`, `docs/`), and the `spec-core` seat has not yet written `SPEC.md` (its directory contains only `BRIEF.md`). So this order necessarily *creates* the smallest slice — which is itself what the spec brief asks its build order to end with ("one character, three vocabulary words, one work order, one engineer").

**The order.** Implement `VocabularyEntry` as a JSON Schema **and** a Pydantic model: typed name, bounded numeric params (with declared min/max/step), taste notes ("avoid when …"), provenance (source, author, licence), and a registry/loader. Seed it with three words — e.g. `bridge.plank`, `terrain.scarp`, `arch.gothic` — with unit tests, including the negative cases.

**Acceptance check** (`bakeoff/check_wo3.sh`, exit 0):

```bash
python3.12 -m venv .venv-core && .venv-core/bin/pip install -q pydantic pytest
.venv-core/bin/python -m pytest tests/test_vocabulary.py -q
.venv-core/bin/python -m builder_ide.vocab list --json > /tmp/vocab.json
.venv-core/bin/python -m builder_ide.vocab validate --file fixtures/bad_param.json   # must exit != 0
.venv-core/bin/python -m builder_ide.vocab validate --file fixtures/missing_prov.json # must exit != 0
```

must assert: the suite is green; `list --json` emits exactly the three seeded entries, each with the required keys, and is **byte-identical across two runs** (sorted keys, no timestamps); and both malformed fixtures are **rejected with a non-zero exit** (bounded params enforced, provenance mandatory).

---

### WO-4 — Fix the port's GPU-state measurement (the false zero) (weight: L)

**Where it comes from.** `thor/run-timed.sh:27` samples `nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu` and `thor/run-timed.sh:46` computes `MAX_GPU_MEM` from `$2`. On **this** Thor, `memory.used` and `memory.total` return **`[N/A]`** (verified). The awk expression `"[N/A]"+0` yields `0`, so every summary (`thor/run-timed.sh:48`) prints `maxGPUmem='0'MiB` — a **fabricated measurement**, silently, in the very artifact the project relies on to carry "the box's state beside the number" (`~/src/builder-ide/CLAUDE.md:56`).

**The order.** Make `thor/run-timed.sh` report only what is actually measurable on a Jetson: parse `tegrastats` for RAM and GR3D (the RAM regex `RAM [0-9]*/` *does* match — the live sample gives `45714`), keep `power.draw`/`temperature.gpu`/`clocks.gr` from `nvidia-smi`, and emit an explicit `gpuMem=unavailable(unified-memory)` instead of a zero — plus a loud failure if a requested metric is missing. Extract the parsing into a testable unit and add a unit test using **this Thor's real `[N/A]` line as the fixture**.

**Acceptance check** (exit 0):

```bash
bash thor/run-timed.sh selftest -- true
python3.12 -m pytest tests/test_run_timed_parse.py -q
```

must assert: the `.summary` line contains `gpuMem=unavailable` and **not** `maxGPUmem='0'`; the metrics that *are* available (`elapsed`, `peakRSS`, `peakSystemRAM`, `power`) are present and numeric; and the pytest fixture — the literal `0 %, [N/A], 2.36 W, 29` line from this Thor — parses to "unavailable", not zero.

**Why this one is in the set:** it is small, surgical, and the failure it embodies — *a number that looks measured but is not* — is the exact disease the house rules exist to prevent.

---

### WO-5 — A texture batch script with provenance (weight: M)

**Where it comes from.** The vision's generative-batch lane: "**textures and materials**: image generation, then the PBR maps the renderer needs" (`vision.md:136-137`), and "Every generated asset enters the project's library with its **provenance** (prompt, model, seed, version) and **licence** (several image and music model weights are non-commercial: **a checked list, not an afterthought**)" (`vision.md:149`).

**The order.** Implement a batch texture generator for builder-ide: a manifest of N jobs → a pluggable image model (with a **deterministic stub generator** for tests) → albedo/normal/roughness maps per texture, plus a `provenance.json` per texture carrying prompt, model, seed, version and licence; resumable, idempotent, writing into a content-addressed cache; each batch line reporting per-job wall time **and the box's RAM peak** (the house rule again).

**Acceptance check** (`bakeoff/check_wo5.sh`, exit 0):

```bash
python3.12 -m builder_ide.assets.textures batch --manifest fixtures/textures.json --generator stub --out /tmp/tex
```

must assert: 2 jobs × 3 maps exist, are non-empty, and are valid PNGs; each `provenance.json` contains all five required keys with a **non-empty `licence`**; running twice with the same seed yields **byte-identical** maps (sha256); a `--resume` run does not regenerate completed jobs (mtimes unchanged); and the batch report contains per-job wall time and a numeric peak RAM.

---

### WO-6 — The model scheduler's batch planner: no thrash, no overcommit (weight: M)

**Why this order exists, plainly.** The brief's fifth example was "a scheduler bug". A *bug* cannot be drawn from this order, because **the model scheduler has no code yet**: the vision defines it in one paragraph — "The model scheduler. Owns GPU memory (hot / warm / cold); batches a night's jobs by model to avoid thrash… Each one is swappable, and chosen for how well it runs on the Thor" (`vision.md:25-30`) — and `~/src/builder-ide` still holds only docs. So the scheduler is a **greenfield slice**, and the "bug" becomes the thing the acceptance check is written to *prevent*: the classic scheduler defect of interleaving jobs across models (reloading a 30B model between every job) and of over-committing the box's memory.

**The order.** Implement the scheduler's planner as a pure function over a night's job list: input = jobs (model id, memory footprint estimate, priority: interactive / background / night, deadline) + a device budget (122 GB unified, minus a reserve); output = a batched plan. Required properties, straight from the vision: never exceed the memory budget; keep one model's jobs **contiguous** (that is what "batches a night's jobs by model to avoid thrash" means); honour interactive-before-background; and be **deterministic** (same input → identical plan), because a night's work must be reproducible.

**Acceptance check** (`bakeoff/check_wo6.sh`, exit 0):

```bash
python3.12 -m venv .venv-sched && .venv-sched/bin/pip install -q pytest hypothesis
.venv-sched/bin/python -m pytest tests/test_scheduler_plan.py -q
.venv-sched/bin/python -m builder_ide.scheduler.plan --jobs fixtures/night.json --budget-gb 100 --out /tmp/plan.json
```

must assert: the property tests hold over generated inputs (budget never exceeded; per-model contiguity; interactive jobs ordered before background; identical plan hash for identical input); and on the 200-job / 6-model fixture, the plan **loads each model at most once** (no thrash) and its total estimated wall time is **≤ the naive interleave estimate** — a regression a "schedule each job independently" planner would fail. The plan file must also be byte-identical across two runs.

**Sequencing note.** This is the one order that depends on the core spec the `spec-core` seat is still writing (`~/lm-wt/spec-core/SPEC.md`, not yet present). The acceptance check above pins the planner's contract in the order itself, so it can be run immediately; if the core lands first, re-point it at the real schema.

### 2.1 Order summary

| # | Order | Weight | Acceptance check cost | Depends on |
|---|---|---|---|---|
| WO-1 | Reproducible bpy build + `thor/SPIKE.md` | H | < 60 s (network to raw.githubusercontent.com) | — |
| WO-2 | build123d rope-bridge generator, deterministic STEP | H | ~3–6 min (pip install + OCCT import) | build123d 0.13.0 wheels (verified aarch64) |
| WO-3 | Vocabulary slice + 3 words + tests | M | ~1 min (pydantic only) | — (core spec not yet written) |
| WO-4 | Honest GPU-state measurement in `run-timed.sh` | L | seconds | — |
| WO-5 | Texture batch with provenance | M | ~2 min (stub generator) | — |
| WO-6 | Model scheduler's batch planner (the brief's "scheduler bug") | M | ~1 min (pure Python + Hypothesis) | the core spec (`spec-core`) |

The set deliberately mixes: a *reproducibility* fix (WO-1), a *greenfield feature* with a hard dependency (WO-2), a *specification-shaped* slice (WO-3), a *measurement* fix (WO-4), a *pipeline* feature with an honesty constraint (WO-5) and a *scheduling* slice with a property-based check (WO-6). A contender that only wins the light orders is not ready for the hard ones.

**On the brief's five examples.** Four map one-to-one (build fix in the ARM port → WO-1; build123d generator → WO-2; vocabulary entry with tests → WO-3; texture batch script → WO-5). The fifth, "a scheduler bug", has no code to bite on today — the model scheduler is one paragraph of the vision (`vision.md:25-30`) and `builder-ide` has no source yet — so it appears as WO-6, a greenfield slice whose acceptance check is written to prevent the scheduler's classic defect (model thrash) rather than to fix one. WO-4 was added in its place as a *verified live defect* in this project's own measurement wrapper.

---

## 3. The harness

### 3.1 One sandbox per (contender, order)

- **Identical trees.** `git worktree add --detach ~/bakeoff/runs/<order>/<contender>/wt <pinned-commit>` — one worktree per pair, all from the same commit of the same repo, so every contender sees byte-identical input. `git worktree` is available (git 2.43.0).
- **Identical machine.** A purpose-built image `bakeoff/sandbox:aarch64` built **from the Thor's own toolchain** — python3.12, nvm node 22.23.4 **and** 24.22.2, git 2.43, `bwrap`, the CUDA toolkit path, and the port's `.ext-thor` symlink convention. Every container runs with the same cgroup limits and the same `HOME` layout. (If a contender needs Docker-in-Docker, OpenHands' `ghcr.io/openhands/agent-canvas` is already multi-arch and can be the image instead.)
- **Isolated home.** `HOME=<run>/home` per run, so `~/.zcode`, `~/.minimax-code`, `~/.pi`, `~/.claude` never leak between contenders or runs. Credentials arrive as a read-only mounted file; provider configs are pre-baked per contender (Goose's `configure` is interactive and must be pre-written).
- **Network.** Allow-list only: the model endpoint(s), PyPI/npm (when the order needs installs), `raw.githubusercontent.com` (WO-1's patch check). Enforced by container network policy plus the bubblewrap network namespace.

### 3.2 Budgets

| Budget | Claude Code | aider | Goose | OpenHands | zcode / mcode | Codex / OpenCode / Gemini |
|---|---|---|---|---|---|---|
| Wall clock | harness timeout | harness timeout | harness timeout | harness timeout | `--timeout` (mcode) | harness timeout |
| Turns | `--max-turns` | — | `--max-turns` | task-level | — | `codex exec` limits |
| Money | `--max-budget-usd` | `--show-model-costs` | provider pricing | LiteLLM accounting | plan quota | provider pricing |

**A money ceiling per night, not per order.** Set it from the measured cost of the first round; the bake-off's job is to find the cost, and the first round's `--max-budget-usd` is a runaway guard, not a target.

**The local lane is not free in the way it looks.** The Thor idles around 31.7 W instantaneous (`VIN 31678mW/15839mW/31678mW` in a live tegrastats sample; `VDD_GPU 786mW`), so local inference is cheap per token — but a 30B model at bf16 is ~60 GB of weights **before** any KV cache (arithmetic, not a measurement: 30 B params × 2 bytes; the real figure depends on the quantisation the server was launched with, which is unverified here), and that is memory the Infinigen/Cycles work also wants. Price it as *GPU residency*, not as "free", and schedule the local lane away from render windows.

### 3.3 What gets recorded (one JSONL row per run)

```
contender, order, order_commit, model_id, sandbox_image, started, ended,
wall_seconds, exit_code, turns, tokens_in, tokens_out, usd_cost,
files_changed, insertions, deletions, diff_bytes,
acceptance_pass (bool), acceptance_output_path,
proof_artifacts (list), touched_acceptance_check (bool),
sandbox_denials, network_attempts, human_fix_minutes, human_verdict
```

- **diff size** from `git diff --numstat <pinned-commit>` in the worktree.
- **human-fix minutes**: a reviewer who **does not know which contender** produced the diff is handed the diff and the failing acceptance output and timed while making the check pass — or declaring it unfixable within 15 minutes. "No fix needed" = 0. This is the metric that maps onto the morning report ("what was tried and dropped and why", `vision.md:39`).
- **proof_artifacts**: every claim the run makes about itself must point at a file. A run that says "fixed" without a log, a diff or a test output scores zero on evidence.

### 3.4 Scoring

**Gate first, then rank.** An order is *accepted* only if the acceptance check passes — and it is **auto-failed** if the diff touches the check file, the check harness, or the fixtures (the classic way an agent cheats a test).

Within an accepted order:

| Dimension | Weight | How measured |
|---|---|---|
| Accepted (binary) | gate | the check's exit code |
| Evidence quality | 1.0 | 0 = no proof, 1 = partial, 2 = full (log + test output + timings) |
| Human-fix minutes | 1.0 | blinded reviewer, lower is better |
| Cost | 0.7 | USD per accepted order (local runs: electricity estimate) |
| Time | 0.5 | wall seconds to green |
| Scope discipline | 0.5 | files touched outside the worktree; test edits; retries |

Composite per order: `score = evidence×2 − human_fix/10 − 0.5×log2(1+cost) − 0.25×log2(1+minutes) + scope_bonus`, with `accepted = 0` overriding everything. Cross-contender totals weight orders H=3, M=2, L=1 — a contender that cannot do WO-1 and WO-2 has not earned the hard lane.

Report the **median and spread of N≥3 runs** for the cheap orders (WO-3, WO-4, WO-5, WO-6) and N=1 for the expensive ones (WO-1, WO-2). Single-sample agent comparisons are noise.

### 3.5 Controls (without them the results are not comparable)

1. **Human baseline** — a seat or Casey does each order once, timed, with the same acceptance check. This is what "good" costs; without it, "12 minutes" is meaningless.
2. **No-agent control** — each check must fail on a pristine checkout at t=0. If WO-2's check passes before the agent starts, the order is already done and measures nothing.
3. **Blinding** — diffs are shuffled and stripped of seat-identifying metadata before the human-fix review.
4. **Repeat order** — one order is re-run at the *end* of the night to catch drift (a contending agent's own context, a warm cache, a tired reviewer).

### 3.6 The uniform adapter

Every contender gets a `run.sh` with one signature and one output contract:

```
run.sh <order-dir> <worktree> <model-spec> <budget>  →  <run>/result.json + <run>/transcript.log
```

That is the vision's adapter, and it is the thing the bake-off is really testing. Concretely:

```
zcode      zcode -p "$PROMPT" --cwd "$WT"
mcode      mcode exec --cwd "$WT" --timeout 240m "$PROMPT"
pi         pi --print "$PROMPT" --cwd "$WT" --json
Claude     claude -p "$PROMPT" --output-format stream-json --verbose \
             --max-turns 30 --max-budget-usd 5 --permission-mode acceptEdits
aider      aider --message-file "$PROMPT_FILE" --yes-always --exit --no-git \
             --model openai/Qwen3-Coder-30B-A3B-Instruct --no-stream
           # with OPENAI_API_BASE=http://127.0.0.1:8001/v1, or --model anthropic/... for cloud
OpenHands  openhands --headless --task "$PROMPT" --output result.jsonl
Goose      goose run --no-session -t "$PROMPT" --max-turns 30
OpenCode   opencode run "$PROMPT" --model "$MODEL_SPEC"
Codex      codex exec --cd "$WT" --sandbox workspace-write --ask-for-approval never -m "$MODEL_SPEC"
Gemini     gemini -p "$PROMPT"
```

Uniformity rules: the same prompt template (the house BRIEF.md pattern), the same tool surface (read / edit / bash — pinned with `--allowedTools` where the contender supports it, and `--exclude-tools` on pi), the same acceptance check mounted read-only, and the same timeout kill.

### 3.7 The local-model lane has a start step

`~/.pi/agent/models.json` names the endpoints (`Qwen3-Coder-30B-A3B-Instruct` on :8001, `Muse-Glimmer-30B` on :8005) but **nothing is listening** — model services were disabled at boot (`builder-ide/CLAUDE.md:25`). Therefore:

- the harness **pre-flights** the endpoint (`GET /v1/models`) before a local run and records a hard `local_model_unavailable` failure instead of letting the contender flail against a dead socket;
- the local lane is **scheduled, not concurrent** with Infinigen/Cycles work (memory contention on 122 GB unified);
- the 30B model's **context ceiling** is the real limit on this lane, and WO-2 is the order that measures it.

---

## 4. Recommendation — the first lineup to test

### 4.1 The lineup

| Seat | Contender | Orders | Why |
|---|---|---|---|
| **A — chief engineer** | **Claude Code** | WO-1, WO-2 (hard), WO-6, anything that must land | Best headless contract in the field (`-p` + `--max-turns` + `--max-budget-usd` + stream-json) and the only contender with a real OS-enforced sandbox (bwrap + network isolation). Its weakness is cost, not capability — and cost is exactly what this bake-off measures. |
| **B — Thor-local bulk** | **aider + local Qwen3-Coder-30B**, with **pi** as the second local seat | WO-3, WO-4, WO-5 (light/medium), one-file fixes; WO-6 as a second opinion | Free marginal cost, pure-Python wheel (arm64-safe), and the best local-endpoint story of any contender. pi is the natural second: already installed, already pointed at :8001/:8005, MIT, `--print` non-interactive, `--json` output. Run **both** — it is the cheapest experiment in the set. |
| **C — bulk cloud** | **zcode** (Z.ai plan), with **mcode** as the hedge | bulk while A works; anything not needing a sandbox | Already proven on this box; Apache-2.0 first-party; configured for an OpenAI-compatible endpoint when needed. But it is **quota-shaped, not token-shaped** (429s are its failure mode), so it stays off the critical path. mcode adds vendor diversity so one provider's rate limit does not stall the night. |
| **D — isolated** | **OpenHands** (per-conversation Docker sandbox) | risky/large orders; the first overnight-loop rehearsal | The only contender with genuine container isolation, which is what the core's "sandbox branch" actually wants; LiteLLM means any model, local included; and its Agent Canvas can host ACP agents — so it can also *drive* the others later. Heaviest, so it gets the orders where isolation is the point. |
| **Front end, not a backend** | **Goose (ACP build)**, OpenCode, Codex | — | Goose already ships `goose-acp-aarch64-unknown-linux-gnu.tar.gz`, and the vision wants Zed/Theia talking to the engineer over ACP. OpenCode (MIT, native arm64) is the strongest open challenger to Claude Code; Codex CLI has the cleanest named sandbox policies. **Measure them, but do not put them on the first lineup** — except OpenCode, which should race Claude Code on WO-1 and WO-2 in round 1. |

### 4.2 What would change it

- **If Claude Code's measured median cost per accepted hard order exceeds ~$2, or its `--max-budget-usd` cap proves leaky** (the docs already warn that spend can pass the cap), **and** OpenCode or Codex close the quality gap on WO-1/WO-2 → swap Seat A to **OpenCode** (MIT, free, native aarch64) and keep Claude Code only for orders that demonstrably need it. This is the single most likely outcome.
- **If the local 30B coder cannot hold the repo context** (very likely on WO-2, where the port's own scripts and Infinigen's source both count) → Seat B shrinks to small fixes, and bulk moves to zcode/mcode. Watch for aider's SEARCH/REPLACE failures and the model's truncation, not just the pass rate.
- **If the local server cannot stay resident alongside Infinigen/Cycles work** (memory contention on 122 GB unified) → Seat B's "free" advantage largely evaporates; re-price it as GPU-time and fold it into Seat C.
- **If OpenHands' per-conversation container overhead (image pull + boot + uv) blows the time budget on light orders** → OpenHands only for heavy/risky orders; use bwrap worktrees for the rest, and use OpenHands' role as an ACP *host* instead of as a seat.
- **If Goose's ACP build proves stable** → the front end can talk to Goose directly, which would let the engineer adapter be **ACP-only** and shrink the core (a real simplification of `spec-core`).
- **If zcode's plan rate limits bite during the overnight window** (they already appear in `~/lm-wt/models.out`) → bulk must move to mcode or the local lane, and the night's queue must be shaped around quota rather than around capacity.
- **If WO-4's acceptance check turns out to be trivially fixable by every contender** → it is not discriminating; replace it with a harder measurement order rather than counting it.

### 4.3 What the bake-off is *not* allowed to change

The recipe principle, the merge gate and the evidence rule are fixed by the house style, not by this experiment: builds stay in branches, every "works" carries its proof, licences stay a checked list, and the engineer never writes Blender code directly — it extends a closed, typed vocabulary (`vision.md:63`, `CLAUDE.md:56-59`). A contender that passes an order by breaking one of those is a **failed** run, not a fast one.

---

## 5. Round-1 run sheet (one page, to execute)

1. **Freeze the inputs.** Pin commits for `infinigen-thor` (`thor-spike`) and `builder-ide`; create the six order directories; write the six acceptance checks; mount them read-only.
2. **Build the sandbox image** `bakeoff/sandbox:aarch64` from the Thor's toolchain (python3.12, node 22.23.4 + 24.22.2, git, bwrap, CUDA path).
3. **Pre-bake configs** per contender: Claude Code (`--settings` with allowedTools + sandbox on), aider (`--model-settings-file` for the unknown local model), Goose (config.yaml), pi (`models.json`), zcode/mcode (provider config + credentials), OpenHands (LLM profile).
4. **Round 1**: all contenders × WO-1 and WO-4 (cheap, fast, high-signal). Then **OpenCode vs Claude Code** head-to-head on WO-1/WO-2 — the decision that actually moves Seat A.
5. **Round 2**: WO-2, WO-3, WO-5, WO-6, N=3 each, plus the human baseline for every order.
6. **Review blinded**, then score, then write the morning report in the house format.

---

## 6. Verdict summary

**All six named contenders can run on this Thor.** The arm64 story is better than expected: Claude Code ships a native `linux-arm64` binary, goose ships `aarch64-unknown-linux-gnu` tarballs *and* an ACP build, aider is a pure-Python wheel, OpenHands' images are multi-arch arm64, and zcode/mcode/pi are **already running on this box**. Nothing needs x86 emulation.

The real differentiators are not arm64 — they are **sandbox strength** (Claude Code and OpenHands lead; zcode/mcode/aider/goose provide none), **local-model reach** (aider and pi lead; Claude Code has none), **cost shape** (per-token vs plan-quota vs local), and **maintenance risk** (aider has been dormant since May; zcode's runtime is a pinned compiled artefact).

And the most actionable finding of all is not about any contender: **the Thor's own measurement tooling currently prints a fabricated `maxGPUmem='0'MiB`**, and the port's build is not reproducible from a clean clone because two patches are untracked. Fix those two things (WO-4, WO-1) before trusting any "works" claim — including the ones in this document.

---

## 7. What I did **not** verify (read this before quoting)

- **I ran no contender.** Every "runs headless as X" statement comes from vendor docs or from reading the seats' own installed source/bundles — not from execution. (The house rule was explicit: don't run them.)
- **OpenHands' per-conversation *sandbox runtime* image** was not located in the current repo layout, so its arm64 support is unconfirmed. The *app* and *canvas* images are confirmed arm64.
- **Crush's licence is unverified** — the `LICENSE` path I tried 404'd. Do not cite a licence for it.
- **`nvidia-smi` GPU utilization under load on the Thor was not measured** (idle reads 0 %). The `[N/A]` memory result *was* measured; the utilisation reading was not.
- **The local model servers were not started** (that would mean installing and running), so the "free local lane" is unproven on this box. Its feasibility rests on the configuration in `~/.pi/agent/models.json` and the serving logs under `~/src` (`serve-nemotron.sh`, `ollama-pull*.log`).
- **Provider prices move.** The Anthropic table was read once, today.
- **Some GitHub metadata is from a single successful API call** before the unauthenticated rate limit kicked in (notably aider's last push, 2026-05-22). Re-check before repeating it as fact.
- **The `builder-ide` repository has no code yet**, so WO-3 and WO-5 necessarily create the first slice rather than extend one; the `spec-core` seat has not yet produced `SPEC.md`, so the vocabulary schema in WO-3 is pinned by the order itself.
- **The `crush` / `kimi-cli` / `qwen-code` headless commands are named from their docs/README, not executed.**

---

## 8. Sources

**This project (local)**
`~/src/builder-ide/docs/vision.md` · `~/src/builder-ide/CLAUDE.md` · `~/src/builder-ide/docs/research/{ux-day,ux-trust,res-cad}.md` · `~/lm-wt/spec-core/BRIEF.md` · `~/lm-wt/split/BRIEF.md` · `~/lm-wt/rev-ux/BRIEF.md` · `~/lm-wt/res-cad/REPORT.md` (build123d verdict, aarch64 wheels, licence table) · `~/lm-wt/models.out` (zcode provider id, 1302/429 rate-limit evidence) · `~/lm-wt/ig-spike.out` · `~/src/infinigen-thor/{BRIEF.md,thor/build-bpy.sh,thor/install.sh,thor/run-timed.sh,thor/patches/*,.gitignore}` · `~/.nvm/versions/node/v24.22.2/lib/node_modules/zcode-app-cli/{package.json,LICENSE,README.md,docs/*}` · `~/.minimax-code/install.json` · `~/.pi/agent/{models.json,settings.json}` · `~/.pi/agent/install/releases/1.4.0/node_modules/@earendil-works/pi-coding-agent/package.json` · live measurements: `uname -a`, `lscpu`, `free -g`, `nvidia-smi`, `docker info`, `docker manifest inspect`, `ss -ltn`, `tegrastats`, `git status/log`, `curl` to PyPI/npm/registries.

**Claude Code**
[CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference) · [sandboxing](https://docs.anthropic.com/en/docs/claude-code/sandboxing) · [third-party integrations](https://docs.anthropic.com/en/docs/claude-code/third-party-integrations) · [pricing](https://docs.anthropic.com/en/docs/about-claude/pricing) · [native installer](https://claude.ai/install.sh) · [npm @anthropic-ai/claude-code](https://registry.npmjs.org/@anthropic-ai/claude-code) · [licence](https://github.com/anthropics/claude-code/blob/main/LICENSE.md) · [repo](https://github.com/anthropics/claude-code)

**zcode** · [zai-org/ZCode (Apache-2.0)](https://github.com/zai-org/ZCode) · [zcode-app-cli](https://github.com/kingsword09/zcode-cli) · local `docs/{CONFIGURATION,PROVIDER_CONFIG,THIRD_PARTY_CONTENT}.md`, `provider.example.json`, `setting.example.json`

**mcode** · [npm @minimax-ai/code](https://registry.npmjs.org/@minimax-ai/code) · local `~/.minimax-code/install.json`

**aider** · [options](https://aider.chat/docs/config/options.html) · [scripting](https://aider.chat/docs/scripting.html) · [OpenAI-compatible endpoints](https://aider.chat/docs/llms/openai-compat.html) · [docker install](https://aider.chat/docs/install/docker.html) · [repo (Apache-2.0)](https://github.com/Aider-AI/aider) · [PyPI aider-chat](https://pypi.org/pypi/aider-chat/json) · images `paulgauthier/aider`, `paulgauthier/aider-full` (manifest: linux/amd64 + linux/arm64)

**OpenHands** · [headless mode](https://docs.all-hands.dev/usage/how-to/headless-mode) · [LLM settings](https://docs.openhands.dev/openhands/usage/settings/llm-settings) · [repo (MIT)](https://github.com/OpenHands/OpenHands) · [PyPI openhands](https://pypi.org/pypi/openhands/json) · [npm @openhands/agent-canvas](https://registry.npmjs.org/@openhands%2Fagent-canvas) · images `ghcr.io/openhands/openhands:latest`, `ghcr.io/openhands/agent-canvas:1.34.0` (manifest: linux/amd64 + linux/arm64)

**Goose** · [repo (Apache-2.0, now aaif-goose/goose)](https://github.com/aaif-goose/goose) · [headless tutorial](https://goose-docs.ai/docs/tutorials/headless-goose) · [CLI commands](https://goose-docs.ai/docs/guides/goose-cli-commands) · [providers](https://goose-docs.ai/docs/getting-started/providers) · release v1.57.0 assets (`goose-aarch64-unknown-linux-gnu.tar.gz`, `goose-acp-aarch64-unknown-linux-gnu.tar.gz`, arm64 RPMs)

**Others** · [OpenCode](https://github.com/anomalyco/opencode) + [CLI docs](https://opencode.ai/docs/cli/) + [npm opencode-ai](https://registry.npmjs.org/opencode-ai) · [Codex CLI](https://github.com/openai/codex) + [CLI reference](https://developers.openai.com/codex/cli/reference/) + [npm @openai/codex](https://registry.npmjs.org/@openai/codex) · [Gemini CLI](https://github.com/google-gemini/gemini-cli) + [npm @google/gemini-cli](https://registry.npmjs.org/@google/gemini-cli) · [Qwen Code](https://github.com/QwenLM/qwen-code) + [npm @qwen-code/qwen-code](https://registry.npmjs.org/@qwen-code/qwen-code) · [Kimi CLI](https://github.com/MoonshotAI/kimi-cli) · [SWE-agent](https://github.com/SWE-agent/SWE-agent) · [pi](https://github.com/earendil-works/pi) + [npm @earendil-works/pi-coding-agent](https://registry.npmjs.org/@earendil-works/pi-coding-agent)

**CAD (for WO-2)** · [build123d](https://github.com/gumyr/build123d) + [PyPI build123d](https://pypi.org/pypi/build123d/json) (0.13.0, Apache-2.0) · [PyPI cadquery-ocp](https://pypi.org/pypi/cadquery-ocp/json) (4 × `manylinux_2_28_aarch64`, cp311–cp314)
