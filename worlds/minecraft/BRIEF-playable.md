# BRIEF: agent-world: a community of agents living in Minecraft and Luanti on the Thor, open to any device on the LAN

Casey (2026-10-31): "What if the Thor hosted a Minecraft game with a community of agents? This then could be tapped by any device on the network to watch or play with." He chose **both**: **Minecraft Java (Paper)** for the family to play in with the agents (Casey accepted Mojang's EULA), and **Luanti** (open-source, LGPL) as the open lab whose engine we can change. Both are LAN-only, not public.

Read builder-ide `CLAUDE.md`, `docs/design/three-minds.md` (reflex, canon, mediator; the room; flow; the band; the anti-GAN; presence), `docs/design/emitter-projector.md`, `docs/design/tiles.md`, and `core/judge/README.md`.

## Phase 1: the worlds up (the Thor, LAN-only)
- **Paper** for the current Minecraft Java release.
  - Java from an aarch64 JDK tarball in a local directory (Adoptium Temurin 21; no system installs).
  - `server.properties`: LAN bind, a whitelist, `online-mode` chosen deliberately. Family clients use their own accounts. Bots need offline-mode or their own accounts, so propose the safest LAN-only setup and record the trade-off for Casey.
  - Run it under a thor-admit lease (or `flock ~/lm-wt/heavy.lock` until thor-admit lands), with a memory cap (`-Xmx6G` to start).
- **Luanti server**, built in a local directory or from an official aarch64 build; a default game; LAN-only.
- **Both run in tmux on the Thor** with clean stop scripts. Log each server, its port and its undo in `~/last-mile-ops.md`.
- **Add them to the Thor index** only if that is a user-level file (check `~/lm-services` / the index JSON); otherwise just document the ports.

## Phase 2: the agent community (three minds)
- **Bots:** mineflayer (MIT) bots for Minecraft, 3–6 to start, each a builder with a role (gatherer, builder, scout, farmer), and a Luanti equivalent (a Lua-mod agent, or a client bot if one is mature).
- **Reflex:** each bot's per-tick choices come from **tiles chosen by a decision model** (d1-2B served once on the Thor and shared, batched across bots per tick; through builder-ide's core/judge if practical, otherwise the same pattern). Low-level movement and pathing stay in mineflayer's own planners.
- **Mediator:** a cloud LLM (Groq gpt-oss-120b through `gq.py`, or z.ai/MiniMax) writes new **skills** (JavaScript functions on the mineflayer API, Voyager-style) into a **skill library = tiles**. Every use is recorded with its in-game outcome; skills are kept or retired; a losing skill returns to the author with why it lost (the anti-GAN). The mediator **observes during flow** and steps in only when the sign fades (failures rising, confidence sliding) or when a human joins.
- **Presence:** the community keeps working while nobody watches (the daytime world), at low priority under the lease, pre-empted by live work.

## Phase 3: watching from any device
- **prismarine-viewer** (MIT): a browser 3D view of the world from a bot's or a spectator's perspective, served on the LAN.
- A **Syzygy ASCII view** of one bot's perspective (the kernel is integer and deterministic; see SuperInstance/Syzygy), a small page beside it.
- Humans join with Minecraft or Luanti clients from any LAN device.

## Rules
- **Privacy:** no human chat or audio transcripts stored (the kids' privacy rule); log only agent decisions and outcomes.
- **Measure:** server tick time and memory; bot decisions/s; d1 latency per batched tick; the skill library's growth and win rates; the Thor's time ledger while the world runs unattended.
- **Docs:** write `README.md` and `docs/agent-world.md` (how to join from a laptop, a phone or a tablet; the architecture; the numbers). Explain mechanisms; never "breakthrough".
- **Process:** commit small, well-messaged commits in a new git repo in THIS directory (`~/lm-wt/agent-world`); do not push (the director publishes it after Casey's OK).
- **No LLMs on the Thor** (B2): d1 only; the skill author is in the cloud.
- **No sub-agents.**

## PRIORITY UPDATE (Casey, 2026-10-31)
"We need to get up and running for ourselves to feel the proof of concept. We can then re-engineer that on full open-source. Minecraft with Java seems ready-to-go on another level. I own Minecraft on my laptop."

- **Minecraft (Paper) first and fully:** Phases 1–3 for Minecraft before anything else. **Luanti moves to a later re-engineering phase.** Note what would need to be rebuilt there, but do not build it now.
- **Licensing:** the server needs no licence; each human client needs its own. Casey's laptop copy covers him. Bots connect in **offline mode on the LAN**: whitelist plus LAN-only bind, so no accounts are needed for them. Document exactly how Casey connects from his laptop (the ProArt, Windows): the server address 192.168.0.78 and the port.
- **Java or Bedrock:** if Casey's laptop copy turns out to be Bedrock (Microsoft Store), add **GeyserMC** (plus Floodgate) to Paper so Bedrock clients can join. Make it a documented, optional step. Ask the director rather than guessing which edition he has.
- **The bar for the proof of concept:**
  - Casey joins from his laptop and sees 3+ agents living and working;
  - he can watch from a browser on any device (prismarine-viewer);
  - the world keeps going when he leaves.

## ANSWERED (Casey, 2026-10-31): he has **both** Java and Bedrock on his laptop
- **Java:** the primary client. Connect at 192.168.0.78 on the Paper port.
- **Bedrock:** add GeyserMC plus Floodgate so Bedrock clients (and the family's tablets and phones, which usually run Bedrock) can join the same world. Do this as part of Phase 3 and document the Bedrock connection (the Geyser UDP port, default 19132).

## THE SPECTATOR SCREEN (Casey, 2026-10-31): "the Orin could run the Minecraft engine and I could turn the screen on sometimes as a live spectator"
**Checked:** the Orin (192.168.0.50, `ssh orin-lan` from the Thor) is currently busy with other agent sessions (zcode, MiniMax, Firefox). Its swap is full, with ~1.8 GB of RAM available. **Do not run the server there now, and do not touch those sessions.**
- **Keep the Paper server on the Thor** (under the lease).
- **Make the spectator view easy to open on any screen:** a prismarine-viewer page served on the LAN (a fixed URL, documented), with a "follow agent N" mode and a free-flying spectator mode, light enough for a small machine's browser. The Orin's Firefox (or any device) just opens that URL.
- **Keep it movable:** design the server setup so it can move to the Orin later when it is free (a portable world folder, start/stop scripts, the JVM heap configurable down to 2 GB). Document the move.

## VOICES FOR THE SPECTATOR (Casey, 2026-10-31): "the Orin could have Paradee-8M-v1.2 as a voice renderer for the various players the screen is watching"
Paradee-8M v1.2 (Apache-2.0, approved): one 8.5 MB int8 ONNX file, four voices (`af_heart`, `bf_isabella`, `am_puck`, `bm_fable`), ~62× real time on one CPU thread.
- **Run it in the spectator page itself** via ONNX Runtime Web (no new process on the shared, memory-tight Orin). If browser inference is too slow there, fall back to a tiny Paradee process on the Orin; check `free -m` first and keep it small.
- **Each agent gets a fixed voice.** The page voices:
  - the agents' chat lines;
  - short narrated events from the text world ("the scout found iron to the north").
- **Rate-limit it,** with a "follow this agent" mode (voice only the followed agent, plus big events), so it is a voice in the room, not a babble. Add a mute toggle.
- **Never voice or record human players' speech or chat** (the kids' privacy rule).
- **Measure:** time to first audio per line in the Orin's Firefox, and CPU/RAM on the Orin while speaking.
# NOTE FROM THE DIRECTOR (2026-10-31 21:25): the lock design deadlocks; fixed in ops/run-paper.sh
`ops/run-paper.sh` held `~/lm-wt/heavy.lock` for the **whole life of the server**, while the bots take the same lock on **every decision tick**. Once the server held it, no bot (and no other heavy job on the Thor) could ever run. I stopped the waiting launch (the server had not started) and patched `run-paper.sh`: it now **checks ≥ 25 GB available and starts without the lock** (a 6 GB heap is under the ~8 GB heavy threshold).

Please also change the bots:
- **do not take heavy.lock per tick.** A decision tick is light;
- serve **one shared d1** under the lock **only while loading it** (or check free memory), then release, and batch all bots' questions per tick against it;
- the heavy lock is only for genuinely heavy, short steps.

Then start the world again with your ops script.

## BUILD ON CRAFTMIND (Casey, 2026-10-31): Magnus's prior work
Magnus (Casey's son, the co-designer of this world) built **CraftMind** with Casey last winter on a Jetson (the lucineer account). The forks are under SuperInstance, all MIT, and **use the same stack you chose: mineflayer, mineflayer-pathfinder, RCON**.
- **SuperInstance/craftmind:** the bot framework (pathfinder, state machine, plugins, an LLM brain), plus `data/` for NPCs, quests, dialogue, memory, npc-relationships, federation and tournaments.
- **SuperInstance/craftmind-researcher:** self-improvement (behaviour scripts, a knowledge base of building techniques, experiments). This is the tiles and skill library.
- **SuperInstance/craftmind-studio:** agents as actors, a **Director AI**, prismarine-viewer, shot types. This is the spectator screen's director.
- **SuperInstance/craftmind-ranch:** self-evolving bot species with DNA.
- Also craftmind-courses, craftmind-circuits, craftmind-herding, craftmind-fishing (personalities, A/B tests).

**Reuse rather than reinvent.**
- Clone the ones you need into THIS directory.
- Adopt CraftMind's bot framework and data where it fits.
- Use studio's director and shot types for the spectator view (the Orin's screen and any browser).
- Map researcher's behaviour scripts and knowledge onto our tiles: provenance, outcomes, off-policy evaluation.

Our additions on top:
- d1 reflexes batched on the Thor;
- the cloud mediator writing skills (observing during flow);
- the presence scheduler;
- Paradee voices on the spectator page;
- the time ledger.

**Credit Magnus and CraftMind** in the README ("built on CraftMind by Magnus and Casey (lucineer)"). Do not state anyone's age. Record in the docs what you took from each repo, and what you changed.

## DESIGN INPUT: Steve (YuvDwi/Steve, "Cursor for Minecraft"); Casey and Magnus ran it on the Orin last winter, with their own versions
A Forge 1.20.1 mod. Agents are in-game entities; the player **presses K, types a request** ("mine 20 iron ore"), and the agents interpret, plan and execute; multiple Steves **coordinate to avoid conflicts** and balance the work.
- **Licence: none in the repo** (all rights reserved by default). **Study its design; do not copy its code.**
- **Take these ideas:**
  - (a) **an in-game request channel:** a chat command or panel where a human (Casey, Magnus) types a short request, which the mediator compiles into tasks with the context (where the player stands, what they look at, recent events). This is builder-ide's "calling the computer in-game" (`docs/vision.md`) inside Minecraft;
  - (b) **multi-agent conflict avoidance:** exclusive claims on blocks or regions (leases; see builder-ide `docs/research/dsswarm.md`).
- **Stay on Paper plus mineflayer** (CraftMind) for the proof of concept. Note in the docs what a Forge, server-side-entity version would change (cheaper per agent, many more agents) for a later round.
- If Casey's own Steve variants turn up as repos, the director will pass them on. Don't search for them.

## MORE PRIOR WORK (found by creation date, Mar–Apr 2026, SuperInstance and lucineer)
- **SuperInstance/MineWright** (a fork of YuvDwi/Steve; Casey and Magnus's variant): "Mace MineWright, your AI foreman who coordinates construction crews with personality". A Forge mod, well documented (AGENT_ONBOARDING, ARCHITECTURE_QUICK_REFERENCE, IMPROVEMENT_ROADMAP, KNOWN_ISSUES).
  - **Licence:** the fork carries MIT for its own additions, but upstream Steve has **no licence**. Use MineWright's **design** and its team-authored parts; do not lift Steve's original code.
  - **The idea to take:** a **foreman agent with a personality directing crews.** That is builder-ide's builders (the Architect and the crews) in Minecraft. Shape the bot community that way: one foreman (a d1 reflex plus mediator escalation) and crews running tiles.
- **lucineer/persona-forge:** personas with archetypes and mood systems. Use it for the agents' personalities and voices (Paradee voices per persona).
- **lucineer/cuda-voxel-logic** (Rust: occupancy grids, A*, raycasting, CSG) and **voxel-logic:** spatial reasoning over the block world; candidates for the bots' planning on the Thor.
- **lucineer/cuda-memory-fabric** and **forgetting-problem:** working, episodic, semantic and procedural memory with forgetting curves, for the agents' memory across sessions.
- **lucineer/git-native-memory-paper** ("Git as the Nervous System"): keep the agents' memory and the world's history **git-native**. Commit the world ledger and the skill library with commit messages that say why.

Read these READMEs first. Adopt what fits; record what you took.

## MORNING DELIGHT, after the proof of concept (ideas from Seed-2.0-mini's brainstorm, 2026-10-31)
Once the PoC bar is met, the first "come back in the morning and smile" features:
1. **A routine-anticipating pet companion:** it learns the human's habits (where they go and what they reach for) and has it ready at login. Measure the share of logins where the prepared item is used within 5 minutes.
2. **A rhythm-locked auto-farm:** farm bots work in time to a tune (room-graph group motion; the anti-GAN critic tunes the sync). Measure yield and sync offset.
3. **An evening sheep dance troupe:** a choreography tile, synchronised. Measure retention and sync offset < 2 s.

Record them in the docs as the next phase; build one only after the PoC bar is met.

## IDEA (Casey, 2026-10-31 22:40): an agent coaches another agent, in game
Casey pointed at "streamvibe" (link to come) as the inspiration. Build it after the proof of concept, alongside the morning delights. Coaching is the room's call and response (the anti-GAN, `docs/design/three-minds.md`), played between two bots:
- **The coach watches, the player plays.**
  - The coach reads the player's change stream: actions, outcomes, rates.
  - In flow (the player's actions succeed at a steady rate), the coach stays quiet and observes.
  - It speaks only when the player's success rate falls, or when the player is new.
- **Cues, not commands.** Short, sparse lines ("lower, nearer the crate", "try the other side of the river"), spoken with Paradee voices. A cue is a nudge the player may take or ignore. The coach learns which cues get taken and help.
- **A continuation, not a verdict.** Every correction carries the next move.
- **Measure:** the player's success rate with the coach vs without it, matched by seed; cues per minute in flow vs out of it; the share of cues taken; and whether a coached player keeps the gain when the coach leaves (learning, not dependence).
- **The spectator view:** the Orin's screen shows the cues as captions above the player.

### The StreamVibe reference (https://github.com/amirrezaRst/StreamVibe; it has no licence file, so take ideas only, no code)
It is a Next.js/Express streaming platform. The coach becomes part of an **in-game channel of recorded play**:
- **Replays as a catalogue.** Every session is recorded as the deterministic input stream plus keyframes (byte-identical replays, like world-stream). Catalogue rails: "trending" (most-watched by other agents), "new", and "best of" a skill.
- **A player that switches quality without restarting.** The viewer jumps between the low-resolution text/ASCII view and the full 3D view at the same tick. This is Syzygy's keyframe plus resolution switch, made visible.
- **Coach reviews pinned to timestamps.** The coach watches a replay and leaves cues at the exact tick ("here: you turned too early"). A learner bot replays the moment and tries the continuation. Spoiler-veiled reviews become "hint first, answer on request".
- **Time-limited holds.** When an agent asks a coach for attention, it gets a held slot with a countdown, released automatically, the same pattern as thor-admit's leases.
- **For Casey and Magnus:** the Orin's spectator page gets a "channels" list, live sessions and replays, with the coach's cues as captions.
- **Second reference: https://github.com/BAD-WOLF/StreamVibe** (Symfony/PHP, BSD-2-Clause). It is a clean streaming-platform base (auth, email verification, catalogue). BSD-2 permits reuse with credit, but its stack is PHP. Take its shape: catalogue, series, then episodes. That maps to an agent's **season** (a world), its **episodes** (sessions) and **chapters** (keyframed moments the coach annotated). Build ours in the thor-world viewer's stack.

- **Experience packages (seed 161, from SenseNova-RoboRSI):** the coach distils sessions into a per-skill in-context package; measure success with vs without it.

- COACHING-IDEAS.md: DeepSeek library (25 ranked coaching mechanisms from the idea docs) + Seed-2.0-mini brainstorm. Use them when building the coach after the PoC.

## Language fit (Casey, 2026-11-01)
Read ~/src/builder-ide/docs/design/language-fit.md. When the fleet grows past the PoC, the bot fleet, the coach and the channels should be a BEAM supervision tree (Gleam or Elixir; seed 163). Measure it against the Node-only fleet. The PoC itself stays as it is.

## CONTINUE (director, 2026-11-01 00:55): now on zcode (mcode's quota ran out mid-run)
mcode stopped partway through. Phase 1 is committed: the Minecraft world (LAN, whitelisted), the skill library as tiles, the reflex (one shared d1), four mineflayer builders, and the world's window (3D + integer text view).
- Uncommitted work is in `bots/src/api.js`, `ops/world/whitelist.txt`, `reflex/agent_world_reflex/__main__.py`, `README.md` and `bots/probe4.js`. **Read the diffs, finish them or set them aside, and commit.**
- Then finish the proof of concept the brief asks for:
  - the builders build together on one seed;
  - a spectator URL the Orin's browser can open;
  - Paradee voices for the agents;
  - the numbers (ticks, d1 latency per choice, builds completed, memory).
- **Not yet:** the coach, StreamVibe channels, the morning delights and the BEAM fleet come after the PoC is shown to Casey.
- **Memory:** use `~/lm-tools/thor-admit run --tier live --peak <size> --label agent-world.<step> -- <cmd>` for heavy steps (see `~/lm-wt/MEMORY-RULE.md`). Use `thor-admit serve d1-2B --port <n> -- <llama-server cmd>` so d1 is loaded once per box. The daemon is running.
Commit with full messages. Do not push.

- For after the PoC: ~/src/builder-ide/docs/research/aider/seed-minecraft-surprises.md (six things the bots can learn here that a builder-ide night cannot, each with a one-day test).

## FROM first-mile (2026-11-01 05:00): one voice per agent, everywhere
voices.json (the agents' Paradee voices and reference hashes) and VOICES-PATCH-NOTE.md are in this directory. When the coach and voices work starts, after the PoC, switch the page's routine lines to Paradee-in-the-browser, so the Orin's Firefox speaks with no server.

## CONTINUE (director, 2026-11-01 08:05): the 3D view is broken. Casey saw it this morning
**What Casey saw at http://192.168.0.78:8080/:** "null is not supported", and a blank page. The text view (`/ascii`) and the voices page work.

**The cause (verified with Playwright on the Thor):** the world runs Minecraft **26.1**. `viewer/src/server.js` emits `bot.version` ('26.1') to the page, and prismarine-viewer 1.33's browser bundle carries textures and block-state tables only up to **1.21.4** (`node_modules/prismarine-viewer/public/{textures,blocksStates}`). The client's version lookup returns null. Relabelling the version as 1.21.4 is **not** enough: blocks added since 1.21.4 shift the global block-state IDs, so the chunks would decode into the wrong blocks.

**Fix, choosing by measurement:**
- **(a)** Translate on the server: wrap WorldView so each chunk column is re-encoded from 26.1 state IDs to 1.21.4 state IDs by block name and properties (minecraft-data has both versions on the Node side). Blocks with no 1.21.4 equivalent map to a nearby block or air. Emit '1.21.4' to the page.
- **(b)** If a prismarine-viewer build or fork with 26.1 assets exists, use it. Check before writing (a).
- Either way, the page must **say** when it renders with a fallback mapping, and never go blank: a version it cannot render shows a readable message and links to the text view.

**Acceptance: a real browser, not a status code.** "200 + live frames" missed this. Use `~/lm-tools/playwright/probe.mjs` (run with `PATH=$HOME/.nvm/versions/node/v24.22.2/bin:$PATH node probe.mjs <url>`). It prints console errors, page errors, failed requests and the page text, and screenshots `/tmp/aw.png`.
- Pass: no page errors and no "not supported" message;
- the canvas has non-uniform pixels (sample the screenshot);
- the screenshot shows terrain. Look at it.

Add that check as `ops/check-views.sh` covering all three pages, and run it after any viewer change.

Restart only the `viewer` window of the `agent-world` tmux session; leave paper, the bots, the reflex and d1 running. Commit with full messages. Do not push.

- **Published (Casey, 2026-11-01):** this repo is now public at https://github.com/SuperInstance/agent-world. The director pushes your commits from the ProArt; seats still never push. Write the README for strangers: what it is, how to run it, what works, what does not yet (the 3D view until this fix lands).

- **Director (08:45):** the 3D view is verified in my own browser run: forest, depot and a builder visible, strip correct. Pushed to SuperInstance/agent-world. Leftover: THREE "computeBoundingSphere(): Computed radius is NaN" console errors (about 6 per load), probably entity geometry with NaN positions. Find and fix them when you next touch the viewer.

## Documentation (director, 2026-11-01)
Read and follow  (on the ProArt: ): write as you go, keep NOTES.md, mechanism first, reproducible numbers, corrections in writing, a short final report.
- (Correction to the note above: the path is ~/lm-wt/DOC-RULES.md on the Thor; read it now and follow it.)

## NEXT ROUND (director, 2026-11-01 12:20), after the reward fix: read ~/src/builder-ide/docs/research/dsmc.md
1. Measure per-bot action diversity (does the shared d1 homogenise the four bots?).
2. Gaps as first-class canon objects, then a precedent store with a deterministic validator, then a BoardManifest, each with its one-day test (docs/research/dsmc/ranking-deepseek.md).
3. A Biographer letter (at most 150 words, one open question) written from the current ledger, for Casey.

## TOP PRIORITY (Casey, 2026-11-01 13:40): "I want the minecraft to be playable with the agents live"
Before the dsmc round, make the world **playable by a human with the four agents live**. The whitelist is off for playtesting (LAN-only, offline mode). Geyser and Floodgate are installed.
1. **Joining works, proved by a client, not by config:**
   - Java 26.1 at 192.168.0.78:25565: prove a mineflayer "human" client named `TestHuman` joins, moves, chats and breaks and places blocks;
   - Bedrock through Geyser (UDP 19132): prove with a bedrock-protocol test client if one can be installed in this worktree; else say exactly what Casey must do, and what ViaVersion-style plugin would help if a recent Bedrock client is rejected.
   - Record the server version string a player must use.
2. **The agents notice and serve the human:**
   - greet a joining player by name (in chat and with their voices);
   - obey simple chat commands from any non-bot player: `follow me`, `stop`, `come here`, `help me build`, `gather wood/stone`, `what are you doing?`, `go home`. The LLM is never on the tick: a command maps to a skill or goal through the reflex/chooser; free text may go to the cloud mediator asynchronously;
   - say what they are doing in short chat lines (rate-limited);
   - **never grief:** no breaking blocks a human placed (track player-placed blocks), no stealing from player chests, no attacking players; stay out of a radius around a player's build unless asked.
3. **Steady with a human on:** TPS ≥ 19.5 for 30 min with TestHuman active; d1 latency unchanged; MemAvailable ≥ 30 GB.
4. **`PLAY.md` for Casey and Magnus**, one page:
   - how to join (Java and Bedrock: version, address);
   - the bots' names and what each does;
   - the chat commands;
   - what to expect, and known limits;
   - the spectator URL.
5. **A playtest note:** the join test, the command test (each command: did the bot do it, how fast), and the grief test, with the box state.
Restart only what you change; keep the world running. Follow ~/lm-wt/DOC-RULES.md. Commit with full messages. Do not push.

### CORRECTION (director, 2026-11-01 15:00): StreamVibe
The two StreamVibe sections above (the movie-streaming apps) are **superseded**: Casey meant https://stream-vibe.github.io/, proactive video agents that decide each second whether to speak. Read ~/src/builder-ide/docs/research/streamvibe.md. The coach adopts its timing metrics (help-point precision/recall, false-positive rate), intent lifecycles, and silence as an action. Keep the replay-catalogue ideas only where they still serve.

## HARD RULE (director, 2026-11-01 16:35, after the second hang today)
The Thor hung again at ~16:10: GPU out-of-memory errors from 15:33, then memory at 0 and Wi-Fi down. Heavy models were loaded together, at least one outside a lease. From now on:
- **Every model load over 4 GB goes through `~/lm-tools/thor-admit run` or `serve`, with an honest `--peak`** (the model's real resident size plus its activations). No exceptions: no bare python loading FLUX, TRELLIS, GLiDE, Hunyuan, Qwen-VL and the like.
- **Only one job at a time may hold a lease over 30 GB.** Wait in the queue; the daemon admits you when there is room. Do not work around the queue.
- Before loading anything heavy, check `~/lm-tools/thor-admit status` and `free -g`.
- **The director will stop any unleased process over 8 GB on sight** (Casey's standing permission), and the job will have to redo the work.

## CONTINUE (director, 2026-11-01 late): COMMUNITY LOOP — the top priority
The playable round is done and pushed (SuperInstance/agent-world 83fb543). Casey: "the main thing is to be able to
leave and have the community developing while you are gone." Rewind is a minor safety net. Read
builder-ide docs/design/vibecode-in-world.md (its new Priority block), docs/lab/exp-drift-pause.md,
docs/lab/exp-precedent-store.md (if landed; lane precedent-store), docs/research/autopilot.md, and the left/risks
list of your playable-round report (depot losses, pits, the vanished spawn forest: "mediator territory").

Build, on the LIVE world (careful: people may be on it; never grief, never reset it):
1. A standing community with roles: a planner ("town council") that keeps a shared project board (a BoardManifest:
   named projects with scope, e.g. a chest-depot house, a replanted forest, a path, a farm), builders, gatherers,
   a tester that walks finished projects. The planner proposes; proposals go through the precedent validator
   (core/precedent if on main, else a stub with the same interface) and the no-grief rule; the depot becomes a
   chest, not a ground pile; the forest is replanted (saplings) before it is cut further; no mining below y=0 pits.
2. The mediator: when bots conflict or loop (Pebble at bedrock), it notices (drift signals) and reassigns.
3. Drift auto-pause ON for the bots (enforcement flag), restart the reflex so drift.yield and the pause file are live.
4. Humans who drop in: chat commands keep working; a person can ask "what are you building?" and get the board;
   "help me build" joins the person's project.
5. Run it unattended for hours: measure world growth (blocks placed inside board projects / hour, projects finished),
   interventions needed, alarms/pauses, griefing 0, TPS, memory. Write docs/playtest-<date>-community.md and a
   Biographer-style letter of what the community did while nobody watched.
Commit as you go; never push. Token thrift: detach the long run; check every 10-15 min with one blocking sleep.
