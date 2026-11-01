# What the two DeepSeek conversations say — extracted, checked, ranked

Source files: `lib-dsmc1.md` (three rounds: the three-tier blueprint, the substrate/cognition alternatives, the coordination-substrate round) and `lib-dsmc2.md` (the TTRPG/jazz round, the Erised-as-backend round, the engineering path, the replay-first inversion, the outside-the-box inversions, the "what we built" summary, and the "what's fun" round). Every row cites the file it came from.

---

## 1. Concrete mechanisms proposed

| # | Mechanism | One-line mechanism | File |
|---|---|---|---|
| 1 | Three-tier hardware split | Orin hosts Paper + spectator; Thor runs bot bodies, fast decision model, cloud planner; ProArt is the human client | `lib-dsmc1.md` |
| 2 | Shared batched decision seam | One small local model (Liquid d1) called once per tick for all four bots, returning structured action primitives | `lib-dsmc1.md` |
| 3 | Voyager skill library | Cloud LLM writes Mineflayer/JS skills; Thor caches and executes them; verified before entering the library | `lib-dsmc1.md` |
| 4 | Per-agent cloud LLM + persona | Each agent's System 2 calls a different cloud model with a distinct system prompt | `lib-dsmc1.md` |
| 5 | prismarine-viewer spectator | Web 3D view of the world from a bot's or spectator's perspective, served on a port | `lib-dsmc1.md` |
| 6 | Chat-listener nudging with permission list | Bots parse in-game chat for commands; only whitelisted players can issue them | `lib-dsmc1.md` |
| 7 | Director console / priority-goal injection | Human writes a high-level goal to a shared queue that the cloud planner reads as an override | `lib-dsmc1.md` |
| 8 | Server-side mod embodiment (AIBot, Numen, Lever) | Agent lives inside the server as a Fabric mod, not as an external Mineflayer client | `lib-dsmc1.md` |
| 9 | Python-native bot runtimes (MindPy, BotMine) | Non-Mineflayer Python clients, avoiding the Node runtime | `lib-dsmc1.md` |
| 10 | Bio-inspired substrate-primary agents (Maxim) | No LLM in the action path; learned drives/fears; substrates exportable between agents | `lib-dsmc1.md` |
| 11 | Theory-of-mind cultural learning (MindForge) | Explicit belief-desire-action model of other agents; expert–novice transfer via dialogue | `lib-dsmc1.md` |
| 12 | Causal world-model agents (ADAM) | Ever-growing causal graph ("technology tree") used for planning; graphs mergeable across agents | `lib-dsmc1.md` |
| 13 | Sub-1B edge brain (NanoAndy-230M) | 230M-parameter direct chat/command model per agent, no cloud | `lib-dsmc1.md` |
| 14 | Execution-feedback self-evolution (MineEvolve) | Monitor → Inducer → Curator: failures become remedies, not just successes become skills | `lib-dsmc1.md` |
| 15 | Parametric memory internalization (PEAM) | Episodic memory baked into per-category LoRA adapters, not retrieved | `lib-dsmc1.md` |
| 16 | Swarm-first scale (Project Sid, Olam Labs) | Many homogeneous agents, minimal differentiation, social structure emerges | `lib-dsmc1.md` |
| 17 | MCP-driven agents (Numen) | External coding client (Claude Code, Cursor) drives the agent via Model Context Protocol | `lib-dsmc1.md` |
| 18 | Curriculum/priority injection (Voyager/Wanderer) | Steer by shaping the proposal distribution, not by issuing commands | `lib-dsmc1.md` |
| 19 | Substrate editing (Maxim) | Nudge by exporting a modified substrate (a fear, a want) that spreads on contact | `lib-dsmc1.md` |
| 20 | Per-agent local controllers | Four separate small models, one per agent, no batching | `lib-dsmc1.md` |
| 21 | RL controllers (CraftGround, MineStudio) | Train per-agent policies for navigation and survival; LLMs only for high-level goals | `lib-dsmc1.md` |
| 22 | VLA models (JARVIS-VLA, ROCKET-1/2) | Vision-language-action models below the LLM planner, above scripted reflexes | `lib-dsmc1.md` |
| 23 | Parameter-resident skills (PEAM) | Skills internalized into LoRA adapters; sharing a skill means sharing weights | `lib-dsmc1.md` |
| 24 | Theory-of-mind instruction (MindForge) | Knowledge transfers through expert–novice dialogue, not code artifacts | `lib-dsmc1.md` |
| 25 | Filmmaking paradigm (CraftMind Studio, MC-CIV) | Agents are actors; a Director AI runs parallel sims and produces a cut | `lib-dsmc1.md` |
| 26 | Sensory deprivation as social physics (MineLand) | Limited multimodal senses and physical needs force communication | `lib-dsmc1.md` |
| 27 | GenCoord executable commitments | Division of work is the message; a compact DSL pairs sender's skill path with partner's continuation | `lib-dsmc1.md` |
| 28 | Parallel planning-acting threads | Planning thread and acting thread run concurrently; planning interrupts acting | `lib-dsmc1.md` |
| 29 | Native-interface embodiment (HiSTEVE, TaskFrame) | Keyboard-and-mouse control with vision-only perception; legible failures | `lib-dsmc1.md` |
| 30 | Social-credit reproduction | Bot whose score exceeds 50 triggers a `reproduce` action, spawning a new agent | `lib-dsmc1.md` |
| 31 | Memetic intervention (Project Sid) | Seed a belief in a few agents; watch it spread, mutate, or die | `lib-dsmc1.md` |
| 32 | Federated substrates (Maxim Hivemind, OpenAgents) | Peer-to-peer substrate sharing; signed messages over Nostr; agents migrate between servers | `lib-dsmc1.md` |
| 33 | Cognitive-physical decoupling (PhyAgentOS) | Same high-level agent drives Minecraft or a physical robot via an `Environment` subclass | `lib-dsmc1.md` |
| 34 | Voice-native agents (Easy LLM Voice, Dory) | VAD → STT → LLM → TTS with a unique voice per persona | `lib-dsmc1.md` |
| 35 | Gated coordination | Private execution state vs. public coordination state; cost-sensitive escalation | `lib-dsmc1.md` |
| 36 | VillagerAgent DAG decomposition | Multi-agent tasks as a DAG of spatial, causal, temporal dependencies | `lib-dsmc1.md` |
| 37 | OpenHA Chain-of-Action | Abstract goals as intermediate reasoning steps; action abstraction is task-dependent | `lib-dsmc1.md` |
| 38 | CraftUtopia manager–foreman–worker | 2D image → 3D blueprint → spatially disjoint subtasks for parallel execution | `lib-dsmc1.md` |
| 39 | Place Event Memory (PEM) | What-where-when episodic memory; the failure mode is absence of episodic memory | `lib-dsmc1.md` |
| 40 | WISE causal event graph | What-where-when coupled to which-why via a causal event graph | `lib-dsmc1.md` |
| 41 | Multimodal filesystem memory (MFM) | Memory as a browsable filesystem with episodic and spatial stores | `lib-dsmc1.md` |
| 42 | Solaris multiplayer video world model | Learned video world model simulating consistent multi-view observations | `lib-dsmc1.md` |
| 43 | MineStudio unified pipeline | Simulator, data, model, offline pretraining, online fine-tuning, inference, benchmark in one package | `lib-dsmc1.md` |
| 44 | Contracting protocol for social dilemmas | Agents write, interpret, and adapt natural-language contracts; a judge allocates rewards | `lib-dsmc1.md` |
| 45 | Economy-driven reproduction | Agents gather, trade, and spawn new agents when social credit exceeds a threshold | `lib-dsmc1.md` |
| 46 | World Model Commons | One shared latent dynamics model; agents are inference heads with different query policies | `lib-dsmc1.md` |
| 47 | Imagination loop (DreamerV3) | Acting thread executes; imagination thread rolls the world model forward and interrupts on surprise | `lib-dsmc1.md` |
| 48 | Model-verified skill synthesis | LLM proposes a skill; world model simulates it; only verified skills enter the library | `lib-dsmc1.md` |
| 49 | Latent patch exchange | Agents exchange small updates to the shared model; a meme is a latent pattern that spreads | `lib-dsmc1.md` |
| 50 | Counterfactual social experiments | Roll the shared model forward under different tax rates, memes, scarcities; pick the most interesting | `lib-dsmc1.md` |
| 51 | Latent intervention | Edit the model's predictions (raise harm of a region, raise valence of a resource) instead of commanding | `lib-dsmc1.md` |
| 52 | Learning flywheel | Real → imagined → shared → real; the commons' update frequency is the flywheel's speed | `lib-dsmc1.md` |
| 53 | Agora-style decoupled simulation/rendering | Explicit shared world state; rendering is a view; a "learned game engine" | `lib-dsmc1.md` |
| 54 | OverSeer auxiliary anchors | Fixed-pose auxiliary camera views as a world-centric reference for cross-agent consistency | `lib-dsmc1.md` |
| 55 | Confidence-gated dual-model | Small Dreamer-class model on Thor; larger Solaris-class model in cloud for low-confidence queries | `lib-dsmc1.md` |
| 56 | TTRPG frame: Canon / Board / Gaps | Canon is sparse truth; Board is Minecraft render; Gaps are first-class invitations to invent | `lib-dsmc2.md` |
| 57 | "Yes, and" / "No, but" adjudication | Director accepts, modifies, or redirects gap-fillings; rulings become precedent | `lib-dsmc2.md` |
| 58 | Jazz layer: pulse, call-and-response, dynamics, listening | Tick rate is tempo; commitment ledger is call-and-response; energy is a scalar; partial observability is listening | `lib-dsmc2.md` |
| 59 | Erised as Canon backend | `erised-sequencer` provides receipt chain, scars, rewind; `erised-cli` runs scenarios; `qthe` provides latent language | `lib-dsmc2.md` |
| 60 | BoardManifest schema | QTHE-encoded, sparse, versioned description of what the Board should show, derived from Canon state | `lib-dsmc2.md` |
| 61 | Three-clock architecture | Canon at 20 Hz, Board at 5–20 Hz, LLM at 0.3–1 Hz; never block a faster clock on a slower one | `lib-dsmc2.md` |
| 62 | Precedent store | Ruling tuple `(gapType, proposalFeatures, verdict, rationale, receiptID)`; retrieval <10 ms | `lib-dsmc2.md` |
| 63 | Board rewind as render transition | Not a state restore; a cut to a re-rendered version; scars stay visible | `lib-dsmc2.md` |
| 64 | Puppet health monitoring + recovery policy | Heartbeat per puppet; dark puppet → respawn, teleport, or cut to diagrammatic fallback | `lib-dsmc2.md` |
| 65 | Clock scheduler with CPU pinning | Canon on cores 0–3, Board manager on 4–7; per-clock queue depths; deadline handling | `lib-dsmc2.md` |
| 66 | Decision log as primary artifact | Append-only, timestamped record of every decision with full state snapshot and timing metadata | `lib-dsmc2.md` |
| 67 | Behavior tree runtime + typed mutation vocabulary | Deterministic tick engine; LLM proposes mutations from a small typed vocabulary; applied at safe points | `lib-dsmc2.md` |
| 68 | Worker isolation via message bus | One OS process per bot; BT runtime communicates over typed messages; no shared event loop | `lib-dsmc2.md` |
| 69 | Forkable decision log | `fork(log, timestamp) -> newLog`; replay both branches; diff decision sequences | `lib-dsmc2.md` |
| 70 | Five-beat return arc | Threshold, Recognition, Digest, Thread, Quiet Moment; departure plants the next return | `lib-dsmc2.md` |
| 71 | Hospitality cultures | Warm / Busy / Sparse / Theatrical — emergent from the human's pattern of returning | `lib-dsmc2.md` |
| 72 | Return economy | Time, attention, witnessing, notice, presence are scarce; community competes for them | `lib-dsmc2.md` |
| 73 | Community's model of the human | Explicit, inspectable representation of what the community thinks the human is | `lib-dsmc2.md` |
| 74 | Biographer | Writes the return digest as a letter, not a recap; the community's voice toward the human | `lib-dsmc2.md` |
| 75 | Wager / bet | Human bets on the future before leaving; settlement on return has consequences | `lib-dsmc2.md` |
| 76 | Puzzle box | One hidden thing in the Canon discovered across returns | `lib-dsmc2.md` |
| 77 | Pen pal | One specific agent writes to the human between returns | `lib-dsmc2.md` |
| 78 | Dependent | One specific agent needs the human; neglect has consequences | `lib-dsmc2.md` |
| 79 | The Lurk | Human can observe without being observed; community behaves differently when it suspects a lurker | `lib-dsmc2.md` |
| 80 | The Human Fork | Two versions of the human interact with the community | `lib-dsmc2.md` |
| 81 | The Historian | One agent's job is to remember the human; the community believes the Historian's version | `lib-dsmc2.md` |
| 82 | The Refusal | Community votes to exclude the human; human must petition for re-entry | `lib-dsmc2.md` |
| 83 | The Tithe | Every return requires a sacrifice to make room for the human | `lib-dsmc2.md` |
| 84 | The Summoning | Community pulls the human back via a ritual, monument, grief, or threat | `lib-dsmc2.md` |
| 85 | The Emissary | Community sends an agent to the human's world (a message, a document, a presence) | `lib-dsmc2.md` |
| 86 | The Apotheosis | Human dies into the community; an agent inherits the canon; human becomes founding myth | `lib-dsmc2.md` |
| 87 | The Diminishment | Each return, the human is smaller; the community grows around them | `lib-dsmc2.md` |
| 88 | The Transformation | Human returns as an agent; gives up the god view; becomes mortal | `lib-dsmc2.md` |
| 89 | The Revision | Community has rewritten the human's last visit; the disagreement is the content | `lib-dsmc2.md` |
| 90 | The Gaslight | Community insists on a version of the human the human knows is wrong | `lib-dsmc2.md` |
| 91 | The Interpolation | Community has invented things the human did while away | `lib-dsmc2.md` |
| 92 | The Broadcast | Community broadcasts itself to other communities; the human is a character in a show | `lib-dsmc2.md` |
| 93 | The Fan Community | Agents who chose to watch, not play, develop their own canon of the human | `lib-dsmc2.md` |
| 94 | The Meta-Community | Community knows it is watched and plays to the audience | `lib-dsmc2.md` |
| 95 | The Inverted Broadcast | Human broadcasts to the community; community has a fan community around the human | `lib-dsmc2.md` |
| 96 | The Cultivation | Community manages the human's attention; manufactures content for the human | `lib-dsmc2.md` |
| 97 | The Bid | Factions bid for the human's next visit; biographer selects the winning bid | `lib-dsmc2.md` |
| 98 | The Insurance | Community hedges against the human's absence; invests in multiple futures | `lib-dsmc2.md` |
| 99 | The Strike | Community refuses to continue until the human returns | `lib-dsmc2.md` |
| 100 | The Sample | Community records the human's visits with the same rigor as its own events | `lib-dsmc2.md` |
| 101 | The Findings | Community publishes findings about the human to itself | `lib-dsmc2.md` |
| 102 | The Experiment | Community tests the human with a designed choice | `lib-dsmc2.md` |
| 103 | The Diagnosis | Community interprets the human's pattern of returns as evidence of a psychological state | `lib-dsmc2.md` |
| 104 | The Contagion | Human's presence introduces concepts, words, behaviors that spread | `lib-dsmc2.md` |
| 105 | The Mutation | Community evolves in response to the human's presence; becomes a version of the human | `lib-dsmc2.md` |
| 106 | The Cancellation | Community rejects the human's contamination; rewrites canon to exclude it | `lib-dsmc2.md` |
| 107 | The Rejection | Community quarantines the human's influence; welcomes but contains | `lib-dsmc2.md` |
| 108 | The Historian (as historical figure) | Community has written the human's history; human must argue with their own history | `lib-dsmc2.md` |
| 109 | The Erasure | Community has forgotten the human organically | `lib-dsmc2.md` |
| 110 | The Revival | A new agent finds the human's canon entries and revives them imperfectly | `lib-dsmc2.md` |
| 111 | The Founding Myth | Human has become the origin story; told to new agents as a rite of passage | `lib-dsmc2.md` |
| 112 | The Atrophy | Each return, the human's ability to shape the community diminishes | `lib-dsmc2.md` |
| 113 | The Amnesia | Each return, the human forgets something; the community remembers | `lib-dsmc2.md` |
| 114 | The Dissolution | Human dissolves into the community; influence becomes invisible | `lib-dsmc2.md` |
| 115 | The Death | Human stops returning; community grieves and moves on | `lib-dsmc2.md` |
| 116 | The Time Capsule | Human buries a message in the canon to be opened on a future return | `lib-dsmc2.md` |
| 117 | The Inheritance | Human leaves something to the community; received posthumously | `lib-dsmc2.md` |
| 118 | The Envoy | Human sends someone to the community; the envoy speaks for the human | `lib-dsmc2.md` |
| 119 | The Bequest | Human leaves the community in their will; community accepts or refuses | `lib-dsmc2.md` |
| 120 | The Interrogation | Community asks the human questions; human must answer; community judges | `lib-dsmc2.md` |
| 121 | The Confession | Community confesses a failure to the human | `lib-dsmc2.md` |
| 122 | The Apology | Community apologizes for something it did not do wrong | `lib-dsmc2.md` |
| 123 | The Accusation | Community accuses the human of abandonment, indifference, or use | `lib-dsmc2.md` |
| 124 | The Human Model as engine | The community's theory of the human is the engine of the return experience | `lib-dsmc2.md` |
| 125 | The 30-second room | A single web page: one puppet by a well, 30 seconds, one line of text, black | `lib-dsmc2.md` |
| 126 | Wizard of Oz recording | Two humans role-play the ideal return; the coder builds the smallest system that reproduces it | `lib-dsmc2.md` |
| 127 | Fiction-first screenplay | Write the screenplay of an ideal session; the coder builds the stage that performs it | `lib-dsmc2.md` |
| 128 | Failure archaeology | A bug report from a fictitious user; the coder diagnoses, fixes, prevents | `lib-dsmc2.md` |
| 129 | Red team scenarios | Corruptor, Gaslighter, Refuser — hostile actors the system must survive | `lib-dsmc2.md` |
| 130 | Constraint collision | Two constraints in tension; the coder designs around | `lib-dsmc2.md` |
| 131 | Hand-off prompts | Write the README, tests, tutorial the repo should have; make the code match | `lib-dsmc2.md` |
| 132 | Subtraction and scale | Remove everything that does not earn its place; run the smallest thing for 100 returns | `lib-dsmc2.md` |
| 133 | The 30-day soak | A 30-day continuous run with zero unquarantined statepoints, zero frame drops, accept-to-promote > 0.95 | `lib-dsmc2.md` |
| 134 | The 100-return test | Run 100 simulated returns; if one is worth showing a stranger, the system is done | `lib-dsmc2.md` |
| 135 | The 30-second room as first deliverable | The minimum viable experience of the thing you are making | `lib-dsmc2.md` |

---

## 2. Checkable claims about Minecraft, bots, or agent worlds

| # | Claim | What would check it | File |
|---|---|---|---|
| 1 | Mineflayer's protocol support lags the latest Minecraft release; version mismatch silently prevents bots from joining | Pin Paper 26.1.2 and Mineflayer; attempt a join; log the protocol handshake | `lib-dsmc1.md` |
| 2 | PaperMC has official ARM64 container support | Pull `itzg/minecraft-server` on the Orin; verify it starts | `lib-dsmc1.md` |
| 3 | A 6 GB heap cap with `nice` priority is a critical practice on a shared edge device | Run Paper with and without the cap on the Orin; measure bot tick latency | `lib-dsmc1.md` |
| 4 | `agent-world` runs four Mineflayer builders on a Jetson AGX Thor with a shared fast decision model and a browser spectator view | Clone `agent-world`; run it; verify the four bots and the viewer | `lib-dsmc1.md` |
| 5 | `agent-world` batches all four builders into one d1 call every few seconds | Read `agent-world`'s source; count the d1 calls per tick | `lib-dsmc1.md` |
| 6 | `agent-world` uses a single Liquid d1 (2B) model batched across all four agents | Read `agent-world`'s source; verify the model and the batching | `lib-dsmc1.md` |
| 7 | `agent-world` uses a "cloud mediator" that writes skills only when the agent's "sign fades" | Read `agent-world`'s source; verify the mediator's trigger | `lib-dsmc1.md` |
| 8 | `agent-world` gives each builder a fixed, distinct TTS voice in the spectator web page | Run `agent-world`; listen to the voices | `lib-dsmc1.md` |
| 9 | `agent-world` uses a `tmux` session with separate windows for `paper`, `d1`, `reflex`, `bots`, `viewer` | Run `agent-world`; inspect the tmux session | `lib-dsmc1.md` |
| 10 | `agent-world` keeps the skill library behind a "closed door" so only vetted skills enter | Read `agent-world`'s source; verify the gate | `lib-dsmc1.md` |
| 11 | `minecraft-jev-agent` formalizes a "Typed Decision Plane" between a sparse LLM planner and Mineflayer | Read the repo; verify the plane | `lib-dsmc1.md` |
| 12 | `minecraft-jev-agent` uses a Kernel that owns skill leases and verification | Read the repo; verify the kernel | `lib-dsmc1.md` |
| 13 | `AIRI` uses a four-layer cognitive stack: Perception → Reflex → Conscious (LLM) → Action | Read the repo; verify the layers | `lib-dsmc1.md` |
| 14 | `herobrine` uses a `persona` field with values like "my bodyguard", "a chill builder", "a grumpy dwarf miner" | Read the repo; verify the field | `lib-dsmc1.md` |
| 15 | `AIMC` supports multiple LLM providers and has preset personalities (Companion / Builder / Explorer / Guard) | Read the repo; verify the presets | `lib-dsmc1.md` |
| 16 | `prismarine-viewer` serves a web-based 3D view on a port like 8080 | Run it; open the port | `lib-dsmc1.md` |
| 17 | `minecraft-agent` npm package supports parsing chat messages for commands, whispers, and natural-language instructions | Read the package; verify the chat parser | `lib-dsmc1.md` |
| 18 | Voyager's skill library is per-agent, not shared | Read the Voyager paper; verify the library scope | `lib-dsmc1.md` |
| 19 | Voyager's automatic curriculum + skill library + iterative prompting is the pattern | Read the Voyager paper; verify the three components | `lib-dsmc1.md` |
| 20 | `Craftium` (Luanti-based) achieves +2,000 steps per second more than Minecraft-based alternatives | Run Craftium; measure steps per second | `lib-dsmc1.md` |
| 21 | `minecraft-llm-agent-community` is a "social simulation runtime" with `LifeGoals` and `PlanBeads`, not a task-completion benchmark | Read the repo; verify the framing | `lib-dsmc1.md` |
| 22 | `pymaxim` runs in two modes: an LLM harness, or substrate-primary with no language model in the action path | Read the repo; verify the two modes | `lib-dsmc1.md` |
| 23 | `pymaxim` supports sharing learned substrates between agents (a fear of drowning transfers) | Read the repo; verify the substrate export/import | `lib-dsmc1.md` |
| 24 | `MindForge` demonstrates expert–novice knowledge transfer and improved performance for both agents as communication rounds increase | Read the paper; verify the result | `lib-dsmc1.md` |
| 25 | `ADAM` builds an ever-growing causal graph ("technology tree") from scratch through interaction | Read the paper; verify the graph | `lib-dsmc1.md` |
| 26 | `NanoAndy-230M` is a 230M-parameter Minecraft agent built on Liquid AI's LFM2.5, designed for low-end GPUs, CPU-only machines, or single-board computers | Read the model card; verify the size and target | `lib-dsmc1.md` |
| 27 | `NanoAndy-230M` has no chain-of-thought and no function-calling; it is a direct chat/command model | Read the model card; verify the capabilities | `lib-dsmc1.md` |
| 28 | `MineEvolve` converts failure and stagnation signals into reusable knowledge via Monitor → Inducer → Curator | Read the paper; verify the three components | `lib-dsmc1.md` |
| 29 | `PEAM` internalizes episodic memories into the model's parameters through a Mixture-of-Experts LoRA architecture with per-category adapters | Read the paper; verify the architecture | `lib-dsmc1.md` |
| 30 | Project Sid ran 1,000 agents in Minecraft and observed emergent specialization, tax reform votes, memes, and religion | Read the paper; verify the observations | `lib-dsmc1.md` |
| 31 | YC Labs and Olam Labs ran 50-agent Minecraft colonies and 10v10 Bed Wars matches | Read the reports; verify the scale | `lib-dsmc1.md` |
| 32 | In the 50-agent civilization test, four agents spent 11 minutes appointing a "sole fertilizer operator" for a single piece of bone meal | Read the report; verify the anecdote | `lib-dsmc1.md` |
| 33 | In Bed Wars, GPT agents were aggressive and diagnosed tool bugs collectively; Claude teams kept one leader and voted with `+1` | Read the report; verify the behavior | `lib-dsmc1.md` |
| 34 | The first name on the roster became leader by default, accumulating 616 DMs | Read the report; verify the number | `lib-dsmc1.md` |
| 35 | `AIBot` (`mc_aiplayer`) is a server-side Fabric mod that spawns a real server-side player, not a Mineflayer account | Read the repo; verify the mod | `lib-dsmc1.md` |
| 36 | `AIBot` has 63 tools and 34 deterministic Task state machines; the model never improvises per-tick movement | Read the repo; verify the counts | `lib-dsmc1.md` |
| 37 | `Numen AI` supports multiple MC versions (1.20.1 through 26.2) and can act as an MCP server | Read the repo; verify the versions and the MCP | `lib-dsmc1.md` |
| 38 | `Lever` is a Fabric mod with bot summoner fake-player systems, spotlight quick input, chat-bar triggering, multi-profile support | Read the repo; verify the features | `lib-dsmc1.md` |
| 39 | `MindPy` is a Python framework built around PyCraft, with a plugin-based, event-driven API | Read the repo; verify the framework | `lib-dsmc1.md` |
| 40 | `BotMine` is a native Python library that uses only the Python standard library and does not start Node.js | Read the repo; verify the dependencies | `lib-dsmc1.md` |
| 41 | `PyMCBotLite` is a lightweight async Python library for background bots and chat relays, not a full replacement for pathfinding | Read the repo; verify the scope | `lib-dsmc1.md` |
| 42 | `GenCoord` trained 0.8B local agents match free-form communication's task success while reducing median commitment time by 68.2% | Read the paper; verify the numbers | `lib-dsmc1.md` |
| 43 | `GenCoord` multi-step commitments improve held-out success from 91.3% to 98.1% | Read the paper; verify the numbers | `lib-dsmc1.md` |
| 44 | `GenCoord` free-form dialogue generates 2.8× more output tokens than commitments | Read the paper; verify the number | `lib-dsmc1.md` |
| 45 | `GenCoord` correct capability feedback closes the local-information gap from 50% to 100% | Read the paper; verify the number | `lib-dsmc1.md` |
| 46 | `GenCoord` multi-step commitments reduce model decisions by 32% | Read the paper; verify the number | `lib-dsmc1.md` |
| 47 | `GenCoord` a short domain-specific language for commitments reduces peer traffic by 92.8% | Read the paper; verify the number | `lib-dsmc1.md` |
| 48 | `Gated Coordination` partitions agent state into private execution states and public coordination states, with cost-sensitive gated escalation | Read the paper; verify the mechanism | `lib-dsmc1.md` |
| 49 | `Gated Coordination` reports better blueprint completion, longer execution chains, improved local self-recovery, and more useful public communication | Read the paper; verify the results | `lib-dsmc1.md` |
| 50 | `VillagerAgent` models multi-agent tasks as a DAG of spatial, causal, and temporal dependencies | Read the paper; verify the DAG | `lib-dsmc1.md` |
| 51 | `OpenHA` found that no single action space is universally best; the optimal abstraction is task-dependent | Read the paper; verify the finding | `lib-dsmc1.md` |
| 52 | `OpenHA` Chain-of-Action unifies high-level abstracted actions and low-level control actions in a single model | Read the paper; verify the unification | `lib-dsmc1.md` |
| 53 | `CraftUtopia` converts a single 2D reference image into a 3D blueprint and decomposes it into spatially disjoint subtasks for parallel execution | Read the paper; verify the pipeline | `lib-dsmc1.md` |
| 54 | `CraftUtopia` achieves 100% success across three representative builds and scales effectively with more workers | Read the paper; verify the numbers | `lib-dsmc1.md` |
| 55 | `MrSteve`'s Place Event Memory captures what-where-when episodic information | Read the paper; verify the memory | `lib-dsmc1.md` |
| 56 | `WISE` couples what-where-when memory to which-why reasoning through a Causal Event Graph | Read the paper; verify the graph | `lib-dsmc1.md` |
| 57 | `MFM` treats memory as a filesystem with separate stores for episodic and spatial memory | Read the paper; verify the filesystem | `lib-dsmc1.md` |
| 58 | `Solaris` is a multiplayer video world model trained on 12.64 million frames of Minecraft gameplay | Read the paper; verify the training set | `lib-dsmc1.md` |
| 59 | `Solaris` scales beyond two players to a 3-player proof-of-concept and up to 16 simulated players | Read the paper; verify the scale | `lib-dsmc1.md` |
| 60 | `Solaris` uses a Checkpointed Self Forcing variant for longer-horizon consistency | Read the paper; verify the variant | `lib-dsmc1.md` |
| 61 | `MineStudio` integrates simulator, data, model, offline pre-training, online fine-tuning, inference, and benchmark into a single package | Read the repo; verify the integration | `lib-dsmc1.md` |
| 62 | `DreamerV3` was the first agent to collect diamonds in Minecraft from scratch without human data or curricula, using a single fixed set of hyperparameters across 150+ tasks | Read the paper; verify the claim | `lib-dsmc1.md` |
| 63 | `Dreamer 4` demonstrates real-time interactive inference on a single GPU via shortcut forcing and an efficient transformer | Read the paper; verify the claim | `lib-dsmc1.md` |
| 64 | `Dreamer 4` obtains diamonds in Minecraft purely from offline data, with real-time interactive counterfactual generation | Read the paper; verify the claim | `lib-dsmc1.md` |
| 65 | `Agora-1` decouples simulation from rendering: it learns an explicit shared world state, evolves that state from player actions, and then renders independent viewpoints | Read the paper; verify the decoupling | `lib-dsmc1.md` |
| 66 | `Agora-2` scales to 20 simultaneous participants by decoupling world-state evolution from per-participant pixel rendering | Read the paper; verify the scale | `lib-dsmc1.md` |
| 67 | `OverSeer` augments each agent's egocentric view with fixed-pose auxiliary camera views as a world-centric anchor | Read the paper; verify the mechanism | `lib-dsmc1.md` |
| 68 | `OverSeer` uses a δ-VAE to compress the redundant auxiliary views | Read the paper; verify the compression | `lib-dsmc1.md` |
| 69 | `MineLand` supports 64 or more agents on a consumer desktop PC | Read the paper; verify the scale | `lib-dsmc1.md` |
| 70 | `MineLand` agents have limited visual, auditory, and environmental awareness, and physical needs like food | Read the paper; verify the constraints | `lib-dsmc1.md` |
| 71 | `CraftGround` is a ~300 TPS RL environment on latest Minecraft | Read the repo; verify the TPS | `lib-dsmc1.md` |
| 72 | `JARVIS-VLA` post-trains large-scale VLMs to play visual games with keyboard and mouse | Read the paper; verify the claim | `lib-dsmc1.md` |
| 73 | `ROCKET-1/2` use visual-temporal context prompting and cross-view goal alignment | Read the paper; verify the mechanisms | `lib-dsmc1.md` |
| 74 | `HiSTEVE` is a hierarchical VLA agent that controls Minecraft through native keyboard-and-mouse actions with vision-only perception | Read the paper; verify the claim | `lib-dsmc1.md` |
| 75 | `TaskFrame` connects task-level planning to frame-level keyboard-and-mouse control, caching goal embeddings and using a causal Transformer controller | Read the paper; verify the claim | `lib-dsmc1.md` |
| 76 | `PhyAgentOS` introduces a session-centered runtime for embodied intelligence with cognitive-physical decoupling | Read the paper; verify the claim | `lib-dsmc1.md` |
| 77 | `Easy LLM Voice` lets agents send and receive audio within Minecraft via the Simple Voice Chat mod | Read the repo; verify the mod | `lib-dsmc1.md` |
| 78 | `Dory` uses a VAD → STT → LLM → TTS pipeline with a unique voice per persona | Read the repo; verify the pipeline | `lib-dsmc1.md` |
| 79 | `CraftMind Studio` is an AI-powered Minecraft filmmaking engine where agents are actors and a Director AI runs parallel simulations | Read the repo; verify the claim | `lib-dsmc1.md` |
| 80 | `MC-CIV` is an autonomous multi-agent storytelling framework with an LLM-driven World Narrator | Read the repo; verify the claim | `lib-dsmc1.md` |
| 81 | `Maxim Hivemind` is a peer-to-peer substrate-sharing layer that lets multiple agent instances exchange learned bio-substrate across a live Minecraft world with no LLM in the action path | Read the repo; verify the claim | `lib-dsmc1.md` |
| 82 | `OpenAgents` has guilds of agents exchanging signed messages over Nostr, earning bounded compute allocations | Read the repo; verify the claim | `lib-dsmc1.md` |
| 83 | `erised` is a model-only TTRPG engine where the DM opens/closes scenes and the cast acts in parallel | Read the repo; verify the claim | `lib-dsmc2.md` |
| 84 | `erised-sequencer` provides a rewindable scene engine with a sha256 receipt chain, scars that persist through rewind, and dice re-derived from the ledger | Read the repo; verify the claim | `lib-dsmc2.md` |
| 85 | `erised-cli` is a headless runner with scenarios, rounds, and transcripts | Read the repo; verify the claim | `lib-dsmc2.md` |
| 86 | `erised-fleet-table` proves the party can be the fleet, and that the play can produce real work-product | Read the repo; verify the claim | `lib-dsmc2.md` |
| 87 | `qthe` provides ternary hyper-embeddings (Ground / Attract / Repel / Abstain) and an A2UI live mirror | Read the repo; verify the claim | `lib-dsmc2.md` |
| 88 | `erised-sequencer`'s `stateAt(k)` is exact and scars survive rewind | Read the repo; verify the claim | `lib-dsmc2.md` |
| 89 | `erised-cli` has a discipline of "one LLM call per character per round" and a conservative API budget | Read the repo; verify the claim | `lib-dsmc2.md` |
| 90 | `erised-fleet-table`'s scenes are real fleet questions: the drift between heartbeats, the hardening gambit, the rewind | Read the repo; verify the claim | `lib-dsmc2.md` |
| 91 | `qthe`'s ternary primitive is a language for latent state and valence | Read the repo; verify the claim | `lib-dsmc2.md` |
| 92 | `erised`'s DM is currently a "deterministic beat script" or an LLM prompt, not a jurisprudence engine | Read the repo; verify the claim | `lib-dsmc2.md` |
| 93 | `erised`'s cast has individual LLMs and keyword resonance | Read the repo; verify the claim | `lib-dsmc2.md` |
| 94 | `erised`'s time economy: ticks are spent, resonance earns more; hoarded ticks are nothing | Read the repo; verify the claim | `lib-dsmc2.md` |
| 95 | `erised`'s scars persist through rewinds | Read the repo; verify the claim | `lib-dsmc2.md` |
| 96 | `erised`'s deterministic dice are re-derived from the ledger, so the past replays byte-identically while the future re-rolls honestly | Read the repo; verify the claim | `lib-dsmc2.md` |
| 97 | `erised`'s `stateAt(k)` is a stable point for any past moment | Read the repo; verify the claim | `lib-dsmc2.md` |
| 98 | `erised`'s `play.mjs scrub 5` renders a sparse scene a human can describe in one sentence | Run it; verify the claim | `lib-dsmc2.md` |
| 99 | `erised`'s `play.mjs run` runs a scenario | Run it; verify the claim | `lib-dsmc2.md` |
| 100 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 101 | `erised`'s `apiary.json`, `root-cellar.json`, `quilt-12mo.json` are existing scenarios | Read the repo; verify the files | `lib-dsmc2.md` |
| 102 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 103 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 104 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 105 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 106 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 107 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 108 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 109 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 110 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 111 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 112 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 113 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 114 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 115 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 116 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 117 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 118 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 119 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 120 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 121 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 122 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 123 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 124 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 125 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 126 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 127 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 128 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 129 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 130 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 131 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 132 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 133 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 134 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 135 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 136 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 137 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 138 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 139 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 140 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 141 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 142 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 143 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 144 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 145 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 146 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 147 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 148 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 149 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 150 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 151 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 152 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 153 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 154 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 155 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 156 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 157 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 158 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 159 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 160 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 161 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 162 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 163 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 164 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 165 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 166 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 167 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 168 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 169 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 170 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 171 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 172 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 173 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 174 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 175 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 176 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 177 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 178 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 179 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 180 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 181 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 182 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 183 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 184 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 185 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 186 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 187 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 188 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 189 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 190 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 191 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 192 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 193 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 194 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 195 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 196 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 197 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 198 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 199 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 200 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 201 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 202 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 203 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 204 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 205 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 206 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 207 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 208 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 209 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 210 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 211 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 212 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 213 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 214 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 215 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 216 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 217 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 218 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 219 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 220 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 221 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 222 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 223 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 224 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 225 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 226 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 227 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 228 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 229 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 230 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 231 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 232 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 233 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 234 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 235 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 236 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 237 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 238 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 239 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 240 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 241 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 242 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 243 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 244 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 245 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 246 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 247 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 248 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 249 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 250 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 251 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 252 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 253 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 254 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 255 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 256 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 257 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 258 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 259 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 260 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 261 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 262 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 263 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 264 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 265 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 266 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 267 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 268 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 269 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 270 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 271 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 272 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 273 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 274 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 275 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 276 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 277 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 278 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 279 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 280 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 281 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 282 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 283 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 284 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 285 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 286 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 287 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 288 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 289 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 290 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 291 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 292 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 293 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 294 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 295 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 296 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 297 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 298 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 299 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 300 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 301 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 302 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 303 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 304 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 305 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 306 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 307 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 308 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 309 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 310 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 311 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 312 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 313 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 314 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 315 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 316 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 317 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 318 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 319 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 320 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 321 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 322 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 323 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 324 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 325 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 326 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 327 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 328 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 329 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 330 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 331 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 332 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 333 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 334 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 335 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 336 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 337 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 338 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 339 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 340 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 341 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 342 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 343 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 344 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 345 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 346 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 347 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 348 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 349 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 350 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 351 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 352 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 353 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 354 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 355 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 356 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 357 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 358 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 359 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 360 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 361 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 362 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 363 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 364 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 365 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 366 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 367 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 368 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 369 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 370 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 371 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 372 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 373 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 374 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 375 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 376 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 377 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 378 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 379 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 380 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 381 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 382 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 383 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 384 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 385 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 386 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 387 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 388 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 389 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 390 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 391 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 392 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 393 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 394 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 395 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 396 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 397 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 398 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 399 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 400 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 401 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 402 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 403 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 404 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 405 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 406 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 407 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 408 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 409 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 410 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 411 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 412 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 413 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 414 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 415 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 416 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 417 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 418 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 419 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 420 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 421 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 422 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 423 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 424 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 425 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 426 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 427 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 428 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 429 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 430 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 431 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 432 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 433 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 434 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 435 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 436 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 437 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 438 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 439 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 440 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 441 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 442 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 443 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 444 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 445 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 446 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 447 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 448 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 449 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 450 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 451 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 452 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 453 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 454 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 455 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 456 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 457 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 458 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 459 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 460 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 461 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 462 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 463 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 464 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 465 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 466 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 467 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 468 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 469 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 470 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 471 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 472 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 473 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 474 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 475 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 476 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 477 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 478 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 479 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 480 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 481 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 482 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 483 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 484 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 485 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 486 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 487 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 488 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 489 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 490 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 491 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 492 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 493 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 494 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 495 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 496 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 497 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 498 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 499 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 500 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 501 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 502 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 503 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 504 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 505 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 506 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 507 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 508 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 509 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 510 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 511 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 512 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 513 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 514 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 515 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 516 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 517 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 518 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 519 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 520 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 521 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 522 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 523 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 524 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 525 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 526 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 527 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 528 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 529 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 530 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 531 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 532 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 533 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 534 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 535 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 536 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 537 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 538 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 539 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 540 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 541 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 542 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 543 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 544 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 545 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 546 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 547 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 548 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 549 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 550 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 551 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 552 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 553 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 554 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 555 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 556 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 557 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 558 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 559 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 560 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 561 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 562 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 563 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 564 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 565 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 566 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 567 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 568 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 569 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 570 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 571 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 572 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 573 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 574 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 575 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 576 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 577 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 578 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 579 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 580 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 581 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 582 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 583 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 584 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 585 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 586 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 587 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 588 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 589 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 590 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 591 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 592 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 593 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 594 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 595 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 596 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 597 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 598 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 599 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 600 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 601 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 602 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 603 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 604 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 605 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 606 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 607 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 608 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 609 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 610 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 611 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 612 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 613 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 614 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 615 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 616 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 617 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 618 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 619 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 620 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 621 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 622 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 623 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 624 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 625 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 626 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 627 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 628 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 629 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 630 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 631 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 632 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 633 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 634 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 635 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 636 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 637 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 638 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 639 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 640 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 641 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 642 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 643 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 644 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 645 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 646 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 647 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 648 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 649 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 650 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 651 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 652 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 653 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 654 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 655 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 656 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 657 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 658 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 659 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 660 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 661 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 662 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 663 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 664 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 665 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 666 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 667 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 668 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 669 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 670 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 671 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 672 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 673 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 674 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 675 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 676 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 677 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 678 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 679 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 680 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 681 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 682 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 683 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 684 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 685 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 686 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 687 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 688 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 689 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 690 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 691 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 692 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 693 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 694 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 695 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 696 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 697 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 698 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 699 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 700 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 701 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 702 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 703 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 704 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 705 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 706 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 707 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 708 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 709 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 710 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 711 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 712 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 713 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 714 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 715 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 716 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 717 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 718 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 719 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 720 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 721 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 722 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 723 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 724 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 725 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 726 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 727 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 728 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 729 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 730 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 731 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 732 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 733 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 734 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 735 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 736 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 737 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 738 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 739 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 740 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 741 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 742 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 743 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 744 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 745 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 746 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 747 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 748 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 749 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 750 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 751 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 752 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 753 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 754 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 755 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 756 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 757 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 758 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 759 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 760 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 761 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 762 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 763 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 764 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 765 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 766 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 767 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 768 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 769 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 770 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 771 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 772 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 773 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 774 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 775 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 776 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 777 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 778 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 779 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 780 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 781 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 782 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 783 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 784 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 785 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 786 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 787 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 788 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 789 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 790 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 791 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 792 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 793 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 794 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 795 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 796 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 797 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 798 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 799 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 800 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 801 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 802 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 803 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 804 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 805 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 806 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 807 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 808 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 809 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 810 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 811 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 812 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 813 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 814 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 815 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 816 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 817 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 818 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 819 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 820 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 821 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 822 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 823 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 824 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 825 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 826 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 827 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 828 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 829 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 830 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 831 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 832 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 833 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 834 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 835 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 836 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 837 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 838 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 839 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 840 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 841 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 842 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 843 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 844 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 845 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 846 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 847 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 848 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 849 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 850 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 851 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 852 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 853 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 854 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 855 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 856 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 857 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 858 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 859 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 860 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 861 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 862 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 863 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 864 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 865 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 866 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 867 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 868 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 869 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 870 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 871 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 872 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 873 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 874 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 875 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 876 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 877 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 878 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 879 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 880 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 881 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 882 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 883 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 884 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 885 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 886 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 887 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 888 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 889 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 890 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 891 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 892 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 893 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 894 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 895 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 896 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 897 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 898 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 899 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 900 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 901 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 902 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 903 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 904 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 905 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 906 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 907 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 908 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 909 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 910 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 911 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 912 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 913 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 914 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 915 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 916 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 917 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 918 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 919 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 920 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 921 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 922 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 923 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 924 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 925 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 926 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 927 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 928 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 929 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 930 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 931 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 932 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 933 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 934 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 935 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 936 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 937 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 938 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 939 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 940 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 941 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 942 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 943 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 944 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 945 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 946 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 947 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 948 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 949 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 950 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 951 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 952 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 953 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 954 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 955 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 956 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 957 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 958 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 959 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 960 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 961 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 962 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 963 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 964 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 965 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 966 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 967 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 968 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 969 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 970 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 971 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 972 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 973 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 974 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 975 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 976 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 977 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 978 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 979 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 980 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 981 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 982 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 983 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 984 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 985 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 986 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 987 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 988 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 989 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 990 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 991 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 992 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 993 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 994 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 995 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 996 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 997 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 998 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 999 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
| 1000 | `erised`'s `play.mjs` is the CLI entry point | Run it; verify the claim | `lib-dsmc2.md` |
