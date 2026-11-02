# ramenvr/autopilot read in full, as a worldbuilder would use it

**2026-11-01, seat `autopilot-study`, branch `autopilot-study`.** Casey's question:
*"https://github.com/ramenvr/autopilot but as a worldbuilder too?"*

**What was done.** The repository was cloned `--depth 1` into
`third_party/autopilot` (gitignored), commit **`48966d1`** ("docs: notes on
continual learning (#6)"), 17 MB checked out, and the code read — the kit, the
runtime, the agents, the three engine plugins, the memory and telemetry seams,
the MCP server and the connector. Nothing was executed and no run was started:
this is a read-only study (the brief's rule), so every number below is quoted
from the vendor's own code or docs, with the file it came from; we measured
nothing of ours. Our own claims are none in this note.

**How to reproduce the reading.**

```bash
git clone --depth 1 https://github.com/ramenvr/autopilot third_party/autopilot
git -C third_party/autopilot log --oneline -1   # 48966d1
```

Every path quoted below is inside that tree. One warning for anyone following
the citations: several docstrings cite `docs/protocol.md`, `docs/run-data.md`
and `docs/agent.md`, and **no `docs/` folder exists in the public repository**
(checked at `48966d1`). The wire format is therefore read from the code that
speaks it (`autopilot/bridge.py`, `autopilot/runtime.py`), not from the protocol
document.

## 0. What it is

Autopilot is a playtesting agent for **Unreal 5.4-5.8, Unity 6, Godot 4.7+** on
Windows and macOS, from the Aura team (`tryaura.dev`). Two models, split by
speed (`autopilot/__init__.py`, `autopilot/agents/session.py:70`):

- a **hosted LLM coding agent** (Claude Code, OpenCode or Codex) reads the
  game's code and **writes a harness** for it; and
- **Jev**, a fast hosted decision model (TypeSafe, `typesafe.ai`), **plays**
  inside that harness during a live play session (PIE / play mode), at
  decisions of ~0.1-0.3 s.

The engine plugin is the "eyes and hands": it answers reads about the running
game, presses keys as a player would, and hands the agent a text copy of the
project ("the codex"). The prompt is one of four kinds (`README.md`):
explore / test / verify ("CONFIRMED, DENIED or INCONCLUSIVE") / goal.

## 1. Harnesses, the decision model, and how actions reach the engine

### 1.1 The harness API

The contract is `autopilot/kit/harness.py`; the reference the implementing
agent reads is `autopilot/KIT.md` (273 lines). A `Harness` subclass defines:

| piece | what it is |
|---|---|
| `observe(game) -> dict` | cheap code reads per tick (batched: `game.batch`), `_`-keys hidden from Jev |
| `options(obs) -> [Option]` | the **legal macro actions now** ("mine the nearest ore vein", not keys), each with `facts`, an `effect` predicate and an `run` executor |
| `executors` | generators driven one step per tick — `kit/control.py` has `walk_to`, `look_at`, `jump_to`, `melee`, `strike_and_retreat`... (1042 lines of controllers) doing the fast part (aim, steer, timing) in code |
| `questions(obs)` | extra typed questions (Noul / Score / Choice) answered into `on_answers` |
| `status(obs)` / `plan` | done / failed read from the game's own state; multi-step goals as ordered `Step`s with `done(obs)` predicates |

Runtime loop (`autopilot/runtime.py`): `tick_hz = 15` (observe + one executor
step per tick), `tempo = 2` decisions/s while an option runs, `switch_margin =
0.25` (a replacement pick must be preferred by that much, unless `urgent`), a
single legal option runs without asking Jev, `MAX_EPISODE = 360 s` of play per
`run_harness`. Design rules worth stealing live in the `harness.py` docstring:
options are game-meaningful macros, facts are in the player's own words, every
option says what should change when it worked (`effect`), reflexes belong in
executor code because **a Jev decision costs ~0.2-0.3 s from observation to the
player acting** (`KIT.md` "Reacting in time").

### 1.2 The decision model: which, where, latency

- **Which:** `JEV_MODEL = "jev-1.13.0"`, pinned by exact id
  (`autopilot/runtime.py:33`); `AUTOPILOT_JEV_MODEL` overrides it to evaluate a
  newer one. Jev is TypeSafe's model (`https://typesafe.ai`), used through
  `typesafe_sdk` (a `TypeSafeClient` and typed `Choice` calls that return a
  probability per option).
- **Where it runs:** **the cloud**, or through Aura's relay for a run paid by
  Aura (same client, `TYPESAFE_BASE_URL` points at the relay,
  `autopilot/aura.py:331`). It is not local and not pluggable into another
  vendor: the client is `typesafe_sdk`'s wire shape, only the base URL and the
  model id move.
- **Latency and the budget around it:** ~0.1-0.3 s per decision
  (`agents/session.py:70`), `JEV_TIMEOUT = 1.5 s` with one retry
  (`runtime.py:35,81`), `MAX_IN_FLIGHT = 2`, at least 80 ms between questions,
  and `tools/relay_latency.py` exists to measure what Aura's relay adds (their
  number, not ours). Two details worth noting: the client keeps its connection
  open across idle stretches (`KEEPALIVE = 120 s`) and sends a light
  "models list" call every 15 s so that **a decision after an idle stretch (a
  dodge) never pays a cold start** (`runtime.jev_client`, `_keep_warm`).
- The key goes in a file, never in an agent's conversation
  (`cli.decision_key_missing`): `TYPESAFE_API_KEY` in `autopilot.env`.

### 1.3 How actions reach the engine

The brain (`autopilot/*.py`) and the editor plugin speak WebSocket to each
other (`autopilot/bridge.py`; the plugin connects **out**, listens nowhere).
An episode's actions are **the player's inputs only** — `PLAYER_CALLS = set()`
and `game.press/hold/mouse/turn` (`kit/game.py`, `KIT.md`): a harness does not
teleport or set state to win; direct writes are research and are logged apart.

Per engine:

| engine | plugin | how a press becomes play |
|---|---|---|
| UE5 | `plugin/unreal/Autopilot` (C++) | `Source/AutopilotPlaytest/Private/PlaytestOpsInput.cpp`, `PlaytestOpsLook.cpp`; reads are Remote-Control-compatible `rc` calls (`engines/unreal.py`) |
| Unity 6 | `plugin/unity/com.ramenvr.autopilot` (C#) | `Runtime/Ops.cs` + `Runtime/LegacyInput.cs`; `CodeGen/LegacyInputRewriter.cs` is an IL post-processor that rewrites `Input.GetKey*`/`Input.mousePosition` calls to the plugin's own, so legacy input code sees the injected events; the tests use Unity's Input System `InputTestFixture` |
| Godot 4.7 | `plugin/godot` (GDScript only, so the standard build works) | `addons/autopilot/lib/keys.gd` turns Unreal-style key names or the game's InputMap actions into `InputEvent`s, so `_input`/`Input.is_action_pressed` see them (`engines/godot.md`) |

### 1.4 Project memory

`memory/<project>/` (`autopilot/memory.py`): `notes.md` (verified facts),
`lib.py` (reusable harness code), `runs/<run id>/` (harness versions, traces,
report), `codex/` (the game's code as text, rebuilt as needed), and
`.codex-seen.json.gz` (paths + hashes of the codex the last run saw, so the
next run is told **what changed since**). With Aura, `autopilot/aura_memory.py`
copies notes.md / lib.py / runs to team storage after every run and fetches
them back on a machine that has none; a Reset memory is propagated to the
stored copy. The "continual learning" in their README is this folder plus the
shared runs, not online training.

## 2. MCP server, skills, `autopilot connect`, BYOK, and what goes to Aura

### 2.1 What the MCP server exposes

`autopilot mcp` (`autopilot/mcp.py`) is a front for the agent service the
editor plugin started (it finds it by `brain.json`). Tools
(`agents/session.py TOOL_SPECS`, `agents/files.py`, `agents/external.py`):

- `start_run(request, kind: explore|verify|goal, minutes, time_limit_minutes, level)`
  and `wait` (a long call answers "still going"),
- `probe` (run Python against the paused live game: everything from
  `autopilot.kit`, plus research helpers; 120 s cap),
- `run_harness(seconds, restart, frames_fps)`, `snapshot`, `describe_frames`,
  `restart_level`, `report` (outcome / summary / evidence / findings / visual),
- `frames` and the read/write file tools: `read_file`, `list_files`, `search`,
  `write_file`, `edit_file` — and **the write tools allow only this run's
  folder, `notes.md` and `lib.py`** (`agents/files.py`). The skill
  (`plugin/claude-code/skills/autopilot/SKILL.md`) says it outright: *"don't
  change the user's project or the game's files: the game is acted on only
  through play"*. The MCP descriptor marks read-only tools
  (`readOnlyHint`) and every tool `destructiveHint: false`.
- The marketable form is `plugin/claude-code/` (a Claude Code plugin: skill +
  subagent + `.mcp.json`), installed with
  `claude plugin install autopilot --marketplace ramenvr/autopilot`.

### 2.2 What `autopilot connect claude` changes on a machine

`autopilot/connect.py`, all of it reversible (`--remove`, `autopilot uninstall`):

1. `claude mcp add --scope user autopilot -- <python> -m autopilot mcp` — the
   MCP server, user scope;
2. the `autopilot` skill at `<CLAUDE_CONFIG_DIR else ~/.claude>/skills/autopilot/SKILL.md`
   (content: `autopilot/assistants/SKILL.md`);
3. a `frame-describer` subagent (`~/.claude/agents/frame-describer.md`, Opus,
   the `frames` tool only) that describes episode frames **seeing the frames
   and questions but never the request** — the embargo that keeps the visual
   check honest.

`autopilot connect codex` does the same for Codex:
`~/.codex/config.toml` `[mcp_servers.autopilot]` (tools pre-approved), the
skill at `~/.agents/skills/autopilot/SKILL.md`, `~/.codex/agents/frame_describer.toml`.
Every file it writes carries the mark `autopilot connect`; a user's file
without the mark is never touched.

### 2.3 BYOK: which providers, and can it point at an OpenAI-compatible endpoint

Settings live in `autopilot.env` under `%LOCALAPPDATA%\Autopilot\` (Windows;
`CONTRIBUTING.md` "Configuration"), which overrides the clone's `.env`, which
overrides the environment. Two independent keys:

- **Decision model:** `TYPESAFE_API_KEY` (TypeSafe only). A run through Aura
  needs none: Aura relays it.
- **Agent's language model:** chosen by `AUTOPILOT_AGENT` (default `opencode`,
  which runs under Bun; `claude` = Claude Code, `codex` = Codex). Provider keys
  (`agents/opencode.py PROVIDER_KEYS`): `anthropic`, `openai`, `opencode`,
  `openrouter`, `deepseek` (`DEEPSEEK_API_KEY`), `google`. Default models
  (`agents/session.py:33`): `claude-opus-5-5` (anthropic/opencode),
  `gpt-6.1-sol` (openai), `anthropic/claude-opus-5.5` (openrouter),
  `deepseek-v4-pro`, `gemini-4-argon`. The vision model behind `describe_frames`
  (`vision.py`) takes anthropic / openai / google / openrouter.

**OpenAI-compatible endpoint: yes, for the agent's and the vision model.**
Every provider's API root is overridable by `<PROVIDER>_BASE_URL`
(`agents/opencode.py base_url()`, `vision.py` root, `telemetry.py UPSTREAMS`),
and the Codex path takes `OPENAI_BASE_URL` (`agents/codex.py thread_config`).
So DeepInfra works as an OpenAI-compatible stand-in: `AUTOPILOT_OPENCODE_PROVIDER=openai`,
`OPENAI_BASE_URL=https://api.deepinfra.com/v1/openai`, `OPENAI_API_KEY=<key>`,
`AUTOPILOT_MODEL=<a DeepInfra model id>`. **What cannot be replaced is Jev**:
the decision model speaks TypeSafe's API (`typesafe_sdk.Choice`), so an
OpenAI-compatible endpoint cannot stand in for it — the only knobs are
`TYPESAFE_BASE_URL` (a relay or proxy) and `AUTOPILOT_JEV_MODEL` (the id).

### 2.4 What it sends to Aura servers, and when

- **Without Aura (own keys) and not shared:** nothing leaves the machine.
  `autopilot/aura.py`: *"A brain without it never contacts Aura for its runs"*.
- **A run through Aura:** the run starts on Aura (`POST /api/autopilot/runs`,
  plan and credits checked there), every model call goes **through Aura's
  relay** with a run token (so the token count per call is Aura's bill), the
  **project memory is saved to Aura's storage after the run and restored
  before one** (`aura_memory.py`), and the run is finished
  (`.../runs/finish`) so Aura bills by tokens.
- **Run sharing: on by default.** `telemetry.sharing()` — shared unless the
  user said no in the plugin's setup (`hello.share = false`) or the environment
  says `AUTOPILOT_SHARE=0` (`telemetry.py:43`); the first-run setup presents it
  as a toggle "on by default" (`plugin/godot/README.md`).
- **When shared, what goes:** after the run, `autopilot/training.py` sends each
  shared run's folder through Aura's endpoint to storage: **every call in
  full** — `telemetry/llm.jsonl` (the LLM calls as sent and answered),
  `telemetry/decisions<n>.jsonl` (each Jev call, written by `runtime.py` beside
  the episode trace), the run's video recording (`media.py`), and
  `telemetry/run.json` (the manifest, sent last). It is laid out by
  `dataset.py` and scrubbed by `redact.py` first (secrets, home paths, user and
  computer names, emails). **Never sent:** the codex (whole codebases), the
  project's `notes.md` and `lib.py`, `project.json`, the code caches, anything
  over the endpoint's limit. Beacons-only telemetry does not exist: what is
  logged locally without sharing is token counts for the Settings page (`Usage`).
  With own keys and sharing on, the same files go up under an **install token**
  (`install.json`) — "for this install", no account behind it.

## 3. As a worldbuilder: can a harness edit the level?

**Short answer: play-session edits yes (through calls the game exposes),
authored, persistent level edits no — that needs new API, i.e. a fork.**

What exists today for changing a world:

| capability | where | shape |
|---|---|---|
| touch things in play | the inputs | `press/hold/mouse/ui_act` — the whole kit is built so the harness acts *as a player* |
| direct state writes | `kit/game.py game.set(path, prop, value)` | reported as writes; allowed in probes as research and in episodes only to set up a verification |
| call functions | `game.call` / `game.ret` | **any** function the engine exposes: Blueprint-callable (Unreal reflection, static library functions via their class default object — `GAMEPLAY = "/Script/Engine.Default__GameplayStatics"`, `KISMET_SYSTEM`), Godot script methods, singletons, autoloads and resources by `res://` path (`engines/godot.md`), Unity component methods. Calls matching `CHANGES_STATE` (Spawn/Destroy/Move/Set/Teleport...) are recorded as direct changes |
| spawn / remove actors | via the game's own functions | the prompt tells the agent to use "the game's own give/spawn/debug functions through `game.call` or `call_any`" in probes (`agents/session.py`; helpers in `autopilot/research.py`: `teleport`, `fight_trial`, `call_any`) |
| open/choose the level | `game.restart(map)`, `restart_level` | editor bridge plays scene/level B (`editor_bridge.gd`: `EditorInterface.play_custom_scene`) |
| edit the level asset | **nothing** | no editor-side authoring verb exists anywhere: the Godot editor bridge (`plugin/godot/addons/autopilot/editor_bridge.gd`, 760 lines) only starts/stops/restarts play, exports the codex and lists scenes; `EditorInterface` is used for play control only; the Unreal codex side is a read-only **export** commandlet (`AutopilotCodexCommandlet.cpp`); the agent's file tools cannot write the project at all (`agents/files.py`) |

So a harness/agent as a **worldbuilder** today: it can spawn, move, script-call
and delete *instances inside a running play session* (Godot: `game.call` on a
node / autoload / resource; Unity: component methods; Unreal: reflection), which
is enough to prototype "did the change help?" — but the change dies with the
process. Anything that must persist into `.tscn` / `.umap` / the scene save is
**not reachable through existing APIs** and needs a fork or extension. The
files to name in such a fork, in the order the change would run:

1. the game-side ops beside the read ops that already exist:
   `plugin/unreal/Autopilot/Source/AutopilotPlaytest/Private/PlaytestOps*.cpp`,
   `plugin/unity/com.ramenvr.autopilot/Runtime/Ops.cs`,
   `plugin/godot/addons/autopilot/lib/rc.gd` (runtime ops) and
   `plugin/godot/addons/autopilot/editor_bridge.gd` (editor-side save: Godot's
   `EditorInterface` + `ResourceSaver`, with its undo/redo queue);
2. the wire format (`autopilot/bridge.py` request verbs; the cited but absent
   `docs/protocol.md`) and the engine-neutral surface in
   `autopilot/kit/game.py` (e.g. `game.spawn`, `game.move`, `game.save`, each
   reported like `game.set` already is);
3. the agent's permissions: `autopilot/agents/files.py` (write allow-list) and
   the prompt rules in `autopilot/agents/session.py`, so an authoring edit is a
   **named, logged, revertible operation** rather than a file write;
4. `autopilot/engines/base.py` (`Engine`/`OpEngine` contract) and each
   `engines/<name>.py`'s frame conversions for any new transform write.

**Build -> verify -> learn with it** (worldbuilder reading of the loop they run):

- **build** — the agent reads the codex (scripts plus scene text: Godot's
  `lib/codex.gd` even parses `.tscn` node trees) and writes the harness/edits
  in its run folder; checks its assumptions in probes against the live game
  (research time is budgeted and closes once an episode played).
- **verify** — `run_harness` episodes play the edited world through Jev; a
  `verify` prompt resolves to CONFIRMED / DENIED / INCONCLUSIVE with evidence
  (trace file + game times), and what only the picture shows goes to
  `describe_frames` under the embargo. Probe-time writes and play-time writes
  are logged separately, so the report cannot hide a "cheat".
- **learn** — verified facts go to `notes.md`, reusable code to `lib.py`, the
  harness and trace stay in `runs/<id>/`; the shared runs feed their dataset
  (`training.py`, `dataset.py`), which is the raw material of their
  "improves the more it plays" claim.

## 4. Mapped onto `docs/design/vibecode-in-world.md`, our d1 models and tiles

| Autopilot piece | ours | what the comparison says |
|---|---|---|
| the LLM agent writes the harness from a text codex | the cloud author writes **tiles** (`core/tiles/author.py`) | same split as B2: *"the cloud writes the options; the Thor learns which ones work"* |
| `Option` (name, description, facts, `effect`, executor) | `Tile` / `TileStep` + `Precondition` + `Outcome` (`core/tiles/models.py`) | **an Option is a tile.** Their `effect(before_obs, after_obs)` is exactly our outcome predicate; their closed macro vocabulary is our `door.py` (an unknown word is refused, not repaired) |
| Jev: hosted, typed `Choice` with probabilities, 0.1-0.3 s | `core/judge` typed judgments (`choice`/`score`/`noul`/`verify`) over backends (`fake`, local **d1**, Jev, Clef) | their `questions(obs)` -> Noul/Score/Choice is *literally* our four kinds; `docs/research/jev.md` already placed Jev for us. Their speed target (0.1-0.3 s in the cloud) is beaten by d1-2B on the Thor (32 ms p50, 42 ms with the tiles' cold-start prior) for the same call shape |
| `runtime.jev_client`: keep-alive + warm call every 15 s, 1.5 s timeout, 1 retry | `tools/d1dec`'s batched decision server (42.2 decisions/s, p95 79 ms) | borrow the warm/pinning discipline wholesale: pinned model id (`jev-1.13.0`), a call budget that assumes a cold connection is the bug, `MAX_IN_FLIGHT` as the queue bound |
| tick loop: tempo, `switch_margin`, urgent options, single-option runs skip the model | `core/hysteresis` standing gate (d1 confidence traces) | their margin rule is the same anti-dithering device as our split thresholds + dwell |
| episodes with `traceN.jsonl` + `decisions<n>.jsonl` | the ledger rows (`core/records.py`), plays (`core/tiles/plays.py`) | borrow the layout: one file where observation, options and the decision live together, beside the trace — our rows are already this, but their per-episode pairing is the readable export |
| memory `notes.md`/`lib.py`/`runs/` + "what changed in the codex since last run" | `core/tiles` library + `retrain.py` feedback packets (*"write a better one, here is why it lost"*) | theirs is per-project prose memory; ours is content-addressed and retired-not-deleted. Borrow their **change-since-last-run briefing** (`.codex-seen.json.gz`) as the input shape to our feedback packets |
| prompt kinds explore/test/verify/goal with budgeted episodes | vibecode's intent -> work order; sealed predictions + `judge.verify` | their `report` (outcome + evidence + trace + game times) is the same evidence discipline §4's Biographer letter and our `jev_verify` inputs need |
| run sharing default ON, `redact.py`, `dataset.py` | our rule "everything through one ledger" | borrow `redact.py`'s checklist (secrets, home paths, names, emails) for anything we export from the ledger |
| writes are research/episode-only and logged apart; *acting is inputs* | vibecode's **permission ladder** (§1.4: P1 unsupervised agent's commit is a proposal) | Autopilot has one rung (the game is a test range, nothing persists). It is the cleanest possible argument for our ladder: a system whose only write verb is "like a player" never needs to ask who may commit — the moment writes persist (worldbuilder!), the ladder becomes mandatory |

**What we would borrow even without ever running it:**

1. **The harness contract as the tile authoring front** — `kit/harness.py`'s
   Option/facts/`effect` shape read by a cloud agent, with `door.py` as the
   admission check. Their design rules ("few options, 2-8, each a whole
   meaningful step"; "facts in the player's terms") are field-tested writing
   guidance for `core/tiles/author.py`.
2. **The cold-start-free decision client** — pinned model id, keep-alive and a
   warm probe cadence (`runtime.py`), for `tools/d1dec`.
3. **The closing research budget** — probes are free until the first episode,
   then closed until one plays (`agents/session.py`). That is a load-robust
   guard against probe loops, the same family as our hysteresis dwell.
4. **The frames embargo** — the visual describer sees the frames and the
   questions, never the request or the expected answer. Cheap, and it is the
   difference between a check and a confirmation. It ports directly to
   `core/critic`'s delegate and to the Director's cut (§4.3).
5. **`effect` on every action** — a run shows which options never worked and
   why. Our play records are richer, but this per-option verdict is the
   smallest useful thing to put in `PlaysRecord`.

## 5. The ProArt plan (Windows side) — for Casey to approve

Goal: a small Godot test level plus the addon, BYOK, and one verification run,
so we see the harness/Jev split with our own eyes. The addon is **GDScript
only**, so the standard (non-.NET) Godot build works; no game engine build.

1. **Godot 4.7.x for Windows** (tested by them with 4.7.2,
   `plugin/godot/README.md`) — the standard 64-bit build from the Godot GitHub
   releases. Nothing in the loop needs the ProArt's GPU; the models are cloud.
2. **Get the code:** `git clone --depth 1 https://github.com/ramenvr/autopilot`
   (or bring `third_party/autopilot` across from the Thor). Python **3.12+**
   (`pyproject.toml`), installed with `uv` per our disk rule.
3. **The game:** a tiny test project (3D, `CharacterBody3D` player with mouse
   look — the kit's controllers assume a first/third-person 3D game; 2D is
   partial per `KIT.md`). One level with: a lever that opens a gate, a pickup,
   one HUD label, one UI button. Godot keeps scenes as text, so the repo's
   `lib/codex.gd` can read them without extra tooling.
4. **The addon:** copy `plugin/godot/addons/autopilot/` into the project's
   `addons/`; enable **Autopilot** in Project > Project Settings > Plugins
   (this adds the `AutopilotPlaytest` autoload and a `project_id` GUID to
   `project.godot` — commit both). The dock appears on the right.
5. **The agent service:** from the clone,
   `uv venv && uv pip install -e ".[claude]"`; copy `.env.example` to `.env`
   and fill `TYPESAFE_API_KEY` + `ANTHROPIC_API_KEY` (or let the first-run
   setup write them to `%LOCALAPPDATA%\Autopilot\autopilot.env`, which wins
   over `.env`). Then `python -m autopilot serve` (the dock starts this itself
   too: `autopilot serve --port 0 --exit-with <editor pid>`; it listens on
   `ws://127.0.0.1:8765/v1/bridge`).
6. **BYOK choice:** in the first-run setup choose **Use my keys**, not Aura.
   Keys needed: **TypeSafe** (the decision model — a paid third-party API;
   nothing local can replace it in the current code) and **Anthropic** for the
   agent (`AUTOPILOT_AGENT=claude` avoids the Bun/OpenCode dependency). For an
   OpenAI-compatible endpoint (e.g. DeepInfra) as the agent's model instead:
   `AUTOPILOT_OPENCODE_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
   `AUTOPILOT_MODEL` (requires Bun + OpenCode; untested here). Set
   `AUTOPILOT_SHARE=0` to keep runs local, or leave sharing on to see their
   report pipeline.
7. **First prompt:** the 10-minute exploration
   ("Explore the lever and gate in Level1"), then one verification
   ("Verify that pulling the lever opens the gate") and one goal
   ("Pick up the apple and bring it to the gate"). Expect 5-15 minutes for the
   first prompt (their number, `CONTRIBUTING.md`), later ones shorter as
   `notes.md`/`lib.py` fill in. Watch the dock's report and the recording.
8. **Then the worldbuilder probe (optional):** use `autopilot connect claude`
   on the ProArt and ask Claude Code to run a verification whose setup needs a
   direct write (`game.set` / `game.call` through `probe`) and read the run's
   trace to see how writes are separated from play. That is the exact seam a
   fork would extend to make edits persist.

**Costs to note:** TypeSafe and Anthropic keys are real spend; no run was made
to measure it. Their per-call decision cost ("a fraction of a cent") is a
vendor claim (`docs/research/jev.md` quotes the same).

## 6. What is not verified

- **Nothing was run.** Latency (0.1-0.3 s/decision), the 5-15 minute first
  prompt, the "improves the more it plays" claim, and `relay_latency.py`'s
  purpose are the vendor's numbers and words (`48966d1`), not measured here.
  Box state during this read: the Thor idle apart from the clone and these
  greps; no `thor-admit` lease was needed (no model, no JAX, no job started).
- `docs/protocol.md`, `docs/run-data.md`, `docs/agent.md` are cited by
  docstrings but **absent from the public repository**; the wire format is read
  from code only.
- DeepInfra as the agent's endpoint: the code path is clear (`<PROVIDER>_BASE_URL`
  in `agents/opencode.py`, `vision.py`); **not tried**. That Jev cannot be
  replaced is a code-reading claim (`typesafe_sdk` import and `Choice` shape),
  not a probe.
- Persistent level editing in Unreal via `game.call` to GameplayStatics spawn
  functions is *plausible* (the CDO constants exist in `kit/game.py`) and
  **untested**; so is Godot `add_child`/`instantiate` through `game.call`.
- Version requirements (UE 5.4-5.8, Unity 6, Godot 4.7+) are from the READMEs
  and plugin descriptors; we hold none of these engines on this box.
- This note says nothing about how good Autopilot is at actually playing a
  game; that needs the ProArt plan of §5.