# The agentic world-building landscape, 2025-2026

Prepared 2026-10-30. Read-only research: no code was changed, and the only builder-ide material consulted is the internal design documents cited as [1] and [2]. Every external claim carries a dated source; vendor performance statements are labelled as vendor claims. Section 9 lists the decisions this survey forces.

## 1. Scope, status labels, and the shape of the survey

The landscape divides into three families, and the division matters more than any individual product, because the three families solve different halves of the problem.

- **Collaborative builders** operate inside a live 3D editor or engine with a human in the loop: Roblox Studio, Unity, Unreal, Promethean AI.
- **Generative world models** synthesise environments outright: Genie, Marble, HunyuanWorld, Matrix-Game, EdenLive.
- **Long-horizon agents** run unattended and return a report: async coding agents, open-source overnight game harnesses, Minecraft agent research.

Each entry states what the system does, whether it is open or closed, what it gets right, where it falls short, and what to borrow or avoid.

**Status labels.** *Shipped* means generally available and usable in production today. *Open beta* means usable but unstable and subject to change. *Experimental* means behind a flag, unstable, or previewed. *Research preview* means access is limited to a small group. *Announced* means stated roadmap, not usable.

**Open and closed, three ways.** A system counts as open only if all three hold: it can be run independently of the vendor, work can be taken out of it through export formats or APIs, and its behaviour can be changed through plugins, protocol servers, or source. Several products here are open on one axis and closed on the others, and the closed axis is what determines what can be borrowed. Open weights with a restrictive licence are a common form of this: usable, but not reusable.

## 2. Collaborative builders inside existing engines

### 2.1 Roblox Studio's agentic Assistant

Roblox has shipped the most complete agentic loop in the surveyed set, inside a closed platform with a very large audience. On 15 April 2026 Roblox announced an expanded Planning Mode that analyses a place's code and data model, asks clarifying questions, and produces a reviewable, editable action plan, with agents then executing the plan's tasks in parallel and checking their work against the original intent [3]. The same announcement introduced a Playtesting Agent in beta, which tests the game against the original plan by reading code, logs, and the behaviour of the player character, and it reported that 44% of the top 1,000 creators on Roblox used the Assistant or third-party AI tools over MCP between 6 March and 7 April 2026 [3].

The plan artefact is the part worth copying. Generated plans are editable Markdown documents stored in the cloud and tied to the experience and creator profile rather than to any single chat; they are private and not visible to collaborators; they open in a dedicated Markdown editor; and they reconcile in both directions, since manual edits push a diff back into the Assistant's task list while prompting the Assistant rewrites the plan file [4]. The approval gate is stated more precisely than anywhere else in the landscape: "Plans never auto-execute or time out into acceptance. The workflow only executes when you click Build" [4]. Chat history is likewise stored in the cloud and persists across sessions, machines, and devices, scoped to a place, and any response can be spun off into a branch while the original chat remains intact [4].

Roblox converged separately on a package format for extended vocabulary. Skills are Markdown documents with YAML frontmatter carrying a name, a description, and an enabled flag; they teach the Assistant a domain, persist across sessions, and can be packaged for distribution [5]. The Studio MCP server is genuinely local, running as a stdio server inside the Studio process, with tools for reading and writing the data model, running code, capturing console output, starting and stopping play, a `subagent` tool that launches `explore` or `playtest` subagents, a `skill` tool, `screen_capture`, `character_navigation`, virtual keyboard and mouse input, and `list_roblox_studios` for addressing several Studio instances by identifier [6]. Generation is part of the Assistant too, covering mesh generation and procedural models that segment an object into up to eight parts, behave like standard objects until their parameters change, and are rate-limited to 50 calls per rolling 24 hours [7].

**What it gets right.** The plan-first, edit-before-run, build-only-on-click contract is the best-specified version of the loop anywhere in the survey, and it is nearly identical to the approval contract in the internal experience spine [2]. The branch affordance, keeping the original chat while exploring a different direction, is the same idea as branch, commit, and undo. Virtual input plus screen capture makes the agent's view of the running game a first-class surface, which is the same move as treating the in-world avatar as a view of an agent session [6].

**Where it falls short.** Every step still happens inside Roblox Studio against Roblox's data model and Roblox's cloud, and the announced long-form agent workflows are explicitly cloud workflows [3]. The plan remains a plan rather than a world: Markdown describing intended changes, not a declarative recipe that is itself the artefact. The 44% figure measures tool use rather than outcome, and the announcement is a vendor statement about its own platform.

**Borrow.** The editable Markdown plan tied to a project rather than a conversation, reconciled in both directions, private by default, and never auto-executing or timing out into acceptance [4]. The branch affordance [4]. The Skills frontmatter format as the packaging for work orders [5]. Virtual input and screen capture as the agent's sense of the running world [6].

**Avoid.** Treating a plan document as the deliverable. Planning in Markdown and then executing in code yields precisely the kind of artefact nobody can meaningfully review at scale, because the plan and the world are different objects. The cloud-only long-run path also runs directly against the local-night thesis.

### 2.2 Unity AI

Unity's shape is a gateway rather than a model. Unity AI spans an in-editor assistant with Ask, Plan, and Agent modes, generators producing dev-stage assets, an AI Gateway that connects verified third-party agents such as Claude, Codex, and Gemini, an official Unity MCP server for bring-your-own-tool workflows, and a credit meter [8][9][10][11]. The open beta began on 1 May 2026 [11].

Ask is read-only. Plan produces a plan. Agent acts under one of three permission levels, read-only, write scripts only, or full autonomy, with a permission prompt before changes apply, every change reversible, and every generated asset tagged with metadata identifying it as AI-generated [9]. Plan mode is described as following long end-to-end instructions including full game design documents "rather than skipping steps or calling things done before they are" [9]. The AI Gateway uses Unity's project context without consuming Unity AI Credits and runs on the developer's existing subscription with that provider [11]. The official Unity MCP server likewise runs without credits, and the distinction Unity draws is sharp: general coding agents can read project files through the MCP server but do not natively understand Unity's serialized state, and they do not verify changes in Play Mode [11].

The coupling is the part that matters for builder-ide. Unity's own getting-started sequence ends with "Link the project to Unity Cloud. Unity's AI tools require the project to be linked to Unity Cloud" [11]. Unity also states plainly that the tools "aren't a way to prompt a finished game into existence. This is coding and authoring assistance" [11]. Credits reset monthly and do not roll over; Personal access is a 14-day trial of 1,000 credits that converts to a $10 monthly subscription, and Pro, Enterprise, and Industry seats include a monthly allotment plus access to the AI Gateway and the official MCP server [11]. The Assistant package also ships skills, documented as specialised modules that provide expert guidance and tools for a particular area of Unity development [12], making Unity the third implementation of the skills-as-markdown pattern after Roblox and NVIDIA.

**What it gets right.** Three permission levels with an explicit prompt before mutation, and reversibility, is a cleaner governance model than most. The gateway posture, where the engine company refuses to be the AI company and lets the studio bring its own model on its own subscription, is a durable design and a warning, since it tells us the engine vendor has no incentive to build a better assistant than the model vendors do.

**Where it falls short.** The cloud project link is a hard dependency that no amount of local model running removes. Unity's tools are explicitly scoped to authoring assistance rather than generation, so the ambition is bounded by design. The nearest comparable product, Bezi, is a plugin rather than an in-editor agent, has less scene awareness, and needs more Play Mode verification iterations [11].

**Borrow.** The permission-level ladder with a prompt before mutation, and the metadata tag on generated assets that makes them findable and auditable at review time [9][11]. The gateway posture of connecting third-party agents to project context without metering them through the platform's own credits [11].

**Avoid.** The cloud project link as a precondition for agentic authoring. It is the single hardest dependency in the survey for a local-first product, and it is architectural rather than a policy choice.

### 2.3 Unreal Engine 5.8

Epic's position is a protocol server rather than an assistant. Unreal Engine 5.8, released 17 June 2026, ships an experimental Model Context Protocol plugin under `Engine/Plugins/Experimental/ModelContextProtocol` [13][14]. It embeds an MCP server in the editor process, binds a loopback HTTP endpoint at `127.0.0.1:8000/mcp`, and draws its tools from a separate AllToolsets plugin rather than from the MCP plugin itself [13].

The documented limitations are unusually candid and directly applicable. The transport is HTTP and SSE only, with no stdio or websocket support; binding is loopback only; there is no authentication layer; no shipping toolset advertises MCP Resources or Prompts; the toolset registry adapter is editor-only; many features are incomplete or missing; and tool invocations are serialised on the game thread, so clients must not issue overlapping calls [13]. One capability is more consequential than the rest: the server can be started in cooked and shipping builds through `IModelContextProtocolModule::StartServer()`, which puts the protocol surface inside the running game rather than only in the editor [13]. Epic's UE6 direction makes MCP central to the engine, with early access targeted for late 2027 [14].

**What it gets right.** Shipping a protocol server inside the engine process, and documenting its limits at that level of specificity, saves every adopter the archaeology. The in-cooked-build option is the most interesting idea in the section, because it is the same move as builder-ide's ship computer being reachable from inside the world rather than only from an IDE.

**Where it falls short.** Everything is labelled experimental in the plugin's own dependency metadata, there is no auth, and tool calls cannot overlap, which caps concurrency for exactly the parallel-agent workflows the design otherwise invites [13].

**Borrow.** The serialisation rule as a design constraint to adopt deliberately, since the engine's main thread is the real bottleneck for any agent that acts on a scene [13]. The in-cooked-build server option as the shape for an in-world agent surface [13].

**Avoid.** Loopback HTTP without an authentication layer if the surface ever leaves the machine.

### 2.4 Promethean AI

Promethean AI is the most architecturally interesting of the in-editor builders and the least verifiable. Founded in 2018 by Andrew Maximov, a former Naughty Dog technical art director, the project aimed at an AI co-author that reasons over a studio's own asset library to populate and dress scenes, automating repetitive placement and world-building rather than generating images, with a stated direction toward interiors, then biomes, then cities [15]. Early trials were reported at roughly 50% efficiency gains, with a belief in 10x, and these are vendor claims with no public measurement [15].

Availability is contested across sources and the survey cannot resolve it. The project's own site states it has reached MVP, is working with Early Adopter Game Studios, and cannot be released for personal use [16]. A contemporaneous distribution notice describes an early-access version free for non-commercial use with reduced functionality compared to the full enterprise product [16]. A June 2026 industry listing describes a free tier for individuals, plugins for Unreal, Unity, 3ds Max, Maya, and Blender, and assets remaining local rather than uploaded to a cloud [16]. These cannot all describe the same moment.

**What it gets right.** The choice to reason over the studio's own asset library rather than to generate new imagery is the correct instinct for environment work, and it is the same instinct as builder-ide's recipes rather than meshes.

**Where it falls short.** Availability cannot be established, the performance figures are unmeasured vendor claims, and the eight-year span since founding suggests the hard part is not the model but the integration into production pipelines [16][15].

**Borrow.** The asset-library reasoning posture. **Avoid.** Treating any efficiency figure as a planning input.

## 3. Generative world models

### 3.1 Genie 3 and Genie 4

Genie 3, announced 5 August 2025, generates interactive environments in real time from text or image prompts, holding a 720p scene at 24 frames per second for a few minutes of consistent interaction with roughly a minute of visual memory, and was released as a research preview [17]. Its structural weakness is duration, since the world lasts minutes rather than hours.

Genie 4, announced 27 October 2026, is the first world model to generate audio natively in the same forward pass as the pixels, uses Gemini Omni to anchor realism, and places Gemini 3.8 Flash in a loop where the model breaks a goal into steps, watches the frames, and checks that each step succeeded [18][19]. DeepMind's own list of open research problems is complex physical interactions, real-time audio accuracy, legible text, spatial accuracy, and long-term consistency [18]. Availability is a research preview for trusted testers, with rollout to Project Genie Ultra subscribers and Gemini API and AI Studio partners announced without dates, and all output watermarked with SynthID [18][19].

The significant part for builder-ide is not fidelity but the loop. Gemini 3.8 Flash acting as a guiding agent that watches frames and verifies each step is the same shape as the work-order loop in the vision document, on a different substrate, pixels rather than a scene graph [18]. That is third-party evidence that the watch-and-verify pattern is becoming standard, which is a reason to get the pattern right early rather than a reason to abandon it.

### 3.2 Marble, the World API, and Atlas

World Labs is the most productised of the world-model shops and has shipped continuously since late 2024. Marble became generally available on 12 November 2025, generating navigable 3D worlds from text, images, video, panoramas, and coarse layouts [20]. On 21 January 2026 World Labs opened a public World API taking text, single images, multi-image sets, 360-degree panoramas, and video, returning a navigable world asynchronously and exportable into simulators including Isaac Sim, MuJoCo, and RoboSuite [21]. Spark 2.0, on 14 April 2026, added streaming 3D Gaussian splatting on the web with a level-of-detail system [20]. On 1 September 2026 Atlas arrived as an omni world model operating natively on text, images, video, and 3D, generating camera-controlled sequences up to a minute at 1440p, with World Labs stating it will power future versions of Marble [22]. On 28 September 2026 World Labs announced it is joining AMD, which is a compute strategy statement rather than a product release [23].

The most useful artefact from World Labs is a frame rather than a product. The functional taxonomy of world models published on 3 June 2026 splits the field into Renderers, which produce pixels, Simulators, which produce state such as geometry and physics, and Planners, which produce actions, and observes that the simulator gets the least public attention while being the most consequential of the three [24]. Under that frame, Genie and Marble are renderers, game engines are simulators, and agent models are planners, and builder-ide's recipe-plus-engine architecture is a simulator-first product with a renderer attached rather than a renderer pretending to be a simulator. Every serious party in this survey has now implicitly accepted the taxonomy.

### 3.3 Open-weights generation and the direct competitor

This is where commoditisation is real, and where the closest competitor to builder-ide lives.

Tencent's HunyuanWorld line is the largest open family. HunyuanWorld-1.0, released July 2025, generates panoramic images and reconstructs them into navigable 3D scenes with a mesh output [25]. HunyuanWorld-Voyager added interactive RGBD video generation with real-time 3D reconstruction, and HunyuanWorld-Mirror added reflection-aware mirror modelling. HY-World 1.5 "WorldPlay", released 17 December 2025, claims the first open-source real-time interactive world model with long-term geometric consistency, and by January 2026 had shipped a 5B variant for small-VRAM GPUs, training code for the 8B model, and quantised inference [26].

Then, on 16 April 2026, HY-World 2.0, which deserves a careful reading. Tencent positions it explicitly against video world models: existing world models "generate pixel-level videos, essentially 'watching a movie' that vanishes once playback ends", whereas HY-World 2.0 "directly produces editable, persistent 3D assets (meshes / 3DGS) that can be imported into game engines like Blender/Unity/Unreal Engine/Isaac Sim, more like 'building a playable game' than recording a clip" [27]. It accepts text, single images, multi-view images, and video, and outputs meshes or Gaussian splats; inference code and the WorldStereo 2.0 and HY-Pano 2.0 weights were open-sourced through May 2026, and a hosted product followed in July 2026 [27]. The repository's own comparison table sets playable duration as limited, typically one minute, for video world models against unlimited for HY-World 2.0, on the grounds that assets persist permanently [27].

That is a dated, open-weights statement of builder-ide's thesis, from a company with the resources to act on it. The licence is the constraint: the HY-World community licence is not an OSI licence, excludes the EU, the UK, and South Korea, forbids using outputs to improve other AI models, and requires a separate Tencent licence above one million monthly active users [26].

Two further projects settle the architectural question by example. Skywork AI's Matrix-Game 4.0, released 15 October 2026, "combines executable game engines with a causal video model: the engine handles gameplay, physics and player input, while the model transforms low-poly RGB frames into detailed visuals through streaming neural rendering", running at 67 frames per second on an RTX 5080 [28]. VAST AI Research's EdenLive inverts the arrangement outright: "we decouple state evolution (maintained by coding agents or engines) and appearance (rendered by EdenLive)", at roughly 24.7 frames per second at 1280x704 on a single RTX 5090, and it ships an agent skill, EdenGolem, that turns a text prompt into a coarse playable game [29]. Robbyant's LingBot-World, an Apache-2.0 world simulator from video generation with sub-second latency at 16 frames per second, is in maintenance limbo, with the repository stating that development has moved to a successor project [30].

The pattern across these four is unambiguous. Every serious effort now separates state from appearance, keeps the state in an executable program, and treats the generative model as a renderer. EdenLive goes furthest by letting coding agents own state evolution, which is exactly the split between program and ship's computer in the vision document [1].

### 3.4 NVIDIA's stack and the hardware thesis

NVIDIA occupies the in-world character position and the asset-standards position, and it is the only vendor shipping a device class that matches the builder-ide hardware thesis. ACE for Games provides Unreal Engine 5 plugins under an MIT licence with ready-to-use ASR, SLM, and TTS models, the Game Agent SDK in beta as a lightweight C/C++ agentic framework with agent, chat, and RAG APIs, and the In-Game Inferencing SDK, which runs models in-process alongside graphics [31]. Shipped deployments include the Total War: PHARAOH advisor running an on-device small language model with retrieval over the game's data tables, PUBG's AI teammates in public beta in 2026 on the first-generation Nemotron, adaptive raid bosses in MIR5, and the second-generation companion model in Aniimo [31][32].

Nemotron 3.5 Bolt E4B 4GB, released 23 October 2026, runs a conversational agent with multi-turn tool use and grounding in application state inside 4GB of memory, with roughly 40% higher average quality against the prior model and up to 80% fewer output tokens than peers, across 35 languages with a 64k context [32][33][34]. It targets GeForce RTX, RTX Spark, DGX Spark, and Jetson devices, and runs under llama.cpp, vLLM, Ollama, Unsloth, and LM Studio [33]. The larger 74B-A9B 24GB variant shipped 15 October 2026 as an open model with weights, training data, and recipes released [33].

The hardware point is the sharpest one in the survey. RTX Spark laptops arrived on 16 October 2026 at $2,599 with up to 128GB of unified memory, and NVIDIA's own October demonstration had a local agent plan an obstacle course on an RTX Spark, build the 3D assets, train a navigation policy in Isaac Lab, and validate it in Isaac Sim [34]. That is the same class of machine as the Thor, and NVIDIA is selling the same one-local-box-runs-the-loop story to a far larger audience.

SimReady is the most directly borrowable artefact in the survey. Announced at SIGGRAPH on 20 July 2026 alongside the Omniverse libraries entering the NVIDIA Agent Toolkit, SimReady is a versioned, named acceptance standard for simulation-ready assets, with a validator reporting per-requirement results, severity, target, and authored location [35][36][37]. The foundation's repository is Apache-2.0 and was active as of late October 2026 [38]. NVIDIA's agent skills packages point compatible agents at real source and real APIs, and CAD-to-SimReady skills are offered as a path from CAD output to a validated asset [35][36].

## 4. Long-horizon agents and the return-to-a-report contract

### 4.1 Async coding agents

These are not competitors to builder-ide. They are the precedent for its overnight loop, and their ceilings are the reason the slot is still open. Devin, Codex, Jules, and GitHub Copilot all take a request, work in an isolated environment, and return a pull request for review. The differences between them are the useful part.

GitHub's Copilot coding agent runs in an ephemeral GitHub Actions environment, opens exactly one pull request per task, and is capped at a 59-minute session and one repository per task [39]. Since 1 June 2026 it has been billed on usage rather than a flat seat, with one AI credit priced at $0.01 and code review carrying a 13x multiplier, on top of plans from Copilot Pro at $10 a month through Enterprise at $39 a seat [39][40].

Google's Jules clones the repository into a Google Cloud virtual machine, writes a plan, shows a diff, and opens a pull request only once the plan is approved, a plan-approve-pull-request flow that mirrors Roblox's and arrived at independently [41]. The free tier allows 15 tasks per rolling day with three concurrent; paid tiers raise the ceiling to 100 daily tasks and 15 concurrent on Pro, and 300 daily with 60 concurrent on Ultra [41].

Devin moved to quota-based plans, with Free, Pro at $20 a month, Max at $200, Teams at $80 a month plus $40 per developer seat, and additional usage sold at API pricing [42][43]. Devin's documentation also notes that sessions stop being billed while idle awaiting a reply, a small and instructive detail, since the approval pause should not cost money [42].

Codex cloud runs tasks in parallel sandboxes and produces pull requests, and moved to token-based pricing on 2 April 2026.

The pattern across all four is that the async artefact is a code diff and the economics are metered per unit of agent work. Copilot's hard ceiling is 59 minutes of wall clock. Nobody bills for the idle time between "here is a plan" and "yes, build it". A builder-ide night would be metered for exactly the thing these products meter least.

### 4.2 Open-source overnight builders

Three open projects attempt the overnight game build, and their honest state matters more than their ambitions.

open-game-works-core is the most interesting architecturally and the least finished. Its premise is that a prebuilt core supplies infrastructure, live-ops, store policy, and meta systems while agents write only the gameplay as content code, and a `create game:` command runs an edit, check, and judge loop until it stops and then reports, without waiting for a human midway [44]. The judge is the interesting part: judge agents play the game blind against the previous version, while completeness is checked by automated bot playtests, profiling, and UI captures [44]. The README states plainly that the project is under active development, tested only on macOS with Claude Code, and that the build command has never been run, so no game has been built or deployed [44]. The repository is Apache-2.0, was updated on the day this survey was written, and has 22 stars [44].

gamePocGen targets a narrow genre, browser-playable 2D incremental games, through a five-phase pipeline with explicit minute budgets: idea generation, a game design document produced by six specialised agents, an implementation guide, test-driven building, and deployment [45]. It is the only surveyed project that writes tests before the game [45]. The repository carries no licence file, which under default copyright means nobody may reuse it, and it has no stars [45].

XyoLua's GameForge is the closest public analogue to the builder-ide thesis and the most complete of the three. It describes itself as an open-source, local-first AI game development environment in which a description becomes a reviewed plan and then a playable Godot project, built, tested, and fixed by agents on the user's own machine [46]. Seven agents, a Project Manager alongside a Game Designer, Programmer, Level Designer, Asset Manager, Audio Designer, and QA, work behind an approval step offering Approve, Edit, Regenerate, and Cancel; every level is verified to be solvable; fixes arrive as staged diffs separating deterministic quick fixes from AI fixes; validation is headless, with import checks, every script and scene loaded, and a smoke run of the game scene; and a test runner emits machine-readable results [46]. It offers a desktop IDE, a CLI, and an optional MCP server, accepts Anthropic, any OpenAI-compatible provider, or local models through Ollama, and states that GameForge never pushes on its own, that there is no account, no analytics, and no telemetry, and that nothing is sent to XyoLua [46]. The MCP server is read-only unless writes are enabled [46]. It is Apache-2.0 and recent enough that it has no stars yet [46].

Claude Code Game Studios packages the same idea as an org chart, with 49 agents and 74 skills across three cost tiers, quality gates, and twelve safety hooks, and is by a wide margin the most popular artefact of this kind at roughly 30,500 stars under the MIT licence [47]. The engine-bridge layer is separately well served: Unity-MCP and Godot-MCP expose MCP tools, skill generation, and a CLI, work in both the editor and a running game, and offer a hosted backend or self-hosting [48][49]. Both are Apache-2.0 and actively maintained, with Unity-MCP at roughly 4,600 stars and pushed the day before this survey [48].

### 4.3 Minecraft agents as growth-loop precedent

Voyager is the purest precedent for builder-ide's growth loop and the most mature evidence in the survey. Its three components are an automatic novelty-biased curriculum, an ever-growing library of executable JavaScript skills indexed by natural-language description, and iterative prompting that feeds environment feedback and execution errors back to the model [50][51]. Measured against baselines it collected 3.3 times more unique items, travelled 2.3 times further, reached the wooden tech level 15.3 times faster, and was the only method to unlock diamond; removing the skill library caused catastrophic forgetting and a collapsed tech tree, and the library transferred to fresh worlds [50][51]. Skills are retrievable with 96.5% top-5 accuracy from natural-language descriptions [50].

Three cautions apply. The model was GPT-4 through a paid API, so the growth loop was never local and never unmetered [50]. The skill library grew inside an action space Minecraft itself defined, a closed vocabulary the agent could not widen, which is exactly the constraint builder-ide's work orders exist to relieve [1]. And the repository has not been touched since April 2024 [51].

Mindcraft, a separate and still-maintained project, is the open local-model counterpart: an LLM agent driving Mineflayer, with profiles, multi-model support including local models through Ollama, and code writing sandboxed and disabled by default against prompt-injection risk [52]. Its repository is MIT, at roughly 5,900 stars, and was updated within days of this survey [52]. A third project also called Mindcraft, by soapantelope, is unrelated to the bots: it is a Minecraft mod generating infinite worlds from text prompts, with no hardware requirements and a shared rate-limited proxy, and it carries no licence file [53].

### 4.4 Inworld and the character-platform pivot

Inworld is the clearest case of a well-funded position being abandoned. It began as a character-creation studio and became a runtime: on 15 October 2025 it announced Inworld Runtime, a C++ graph engine with Node.js and Unreal SDKs that orchestrates LLMs, speech-to-text, text-to-speech, memory, and tools in a single pipeline, with remote configuration, A/B variants through a Graph Registry, and built-in telemetry, now available to all developers [54]. On 29 October 2025 it shipped the Unreal AI Runtime SDK with more than 100 models behind a single API key, a visual graph editor, pre-built NPC and chatbot templates, and observability tooling, and put the Unity AI Runtime SDK into early access the same day [55]. Its partner list included Xbox, NVIDIA, Ubisoft, Niantic, NBCUniversal, Streamlabs, Unity, and Epic [54].

Then the platform moved. Character Studio was deprecated with a migration path to the Portal and Agent Runtime [56], the Unity Asset Store package was deprecated and withdrawn, first-generation TTS models were discontinued in June 2026, and the Node.js voice-agent template repository was archived in July 2026 [56][57]. The current product is Inworld Inference, positioned for consumer applications, with solutions grouped as social and companions, learning and education, health and wellness, agentic workforce, and, last, games and media [57]. Pricing is now inference pricing, with text-to-speech from $25 per million characters on demand down to $10 on enterprise terms, faster and cheaper tiers below that, speech-to-text at $0.10 per hour, and language models from $0.07 per million input tokens [57].

The lesson is not that character platforms fail. It is that a platform which owns the authoring surface can retire it, and that everything built on the authoring surface is rewritten. The current site still offers an Inworld skill to paste into Claude Code or Cursor, the same skills-as-markdown pattern, now on a platform whose centre of gravity is consumer voice [57].

## 5. Comparison axes

The table below places the surveyed systems on the four axes that actually separate them: where the agent runs, the artefact a session leaves behind, what a human reviews afterwards, and how the work is metered.

| System | Where the agent runs | Artefact left by a session | What a human reviews | Metering |
|---|---|---|---|---|
| Roblox Studio Assistant [3][4][6] | Roblox cloud and Studio | Editable Markdown plan plus data-model edits | The plan, then the diff | Platform credits and cloud quota |
| Unity AI Agent mode [9][11] | Unity Cloud linked to the project | Code and generated assets with metadata tags | Permission prompt, then Play Mode verification | Unity AI Credits, plus gateway agents metered by their own provider |
| Unreal 5.8 MCP plugin [13] | Inside the editor process | Tool calls against the live editor | The tool log, with no plan artefact | Free, and unauthenticated on loopback |
| Inworld Runtime [54][55] | In-game client or server | Graph pipeline configuration | Nothing, at runtime | Per character and per million characters |
| Genie 4 [18][19] | DeepMind-hosted research preview | A navigable scene that disappears | Nothing, it is a preview | Research preview, no published price |
| Marble and the World API [20][21] | World Labs infrastructure | An exported navigable 3D world | The export | Subscription and API pricing |
| HY-World 2.0 [27] | Local weights or Tencent's hosted product | Editable meshes or Gaussian splats | The asset | Open weights under a restricted licence |
| EdenLive [29] | Local single consumer GPU | A render stream over a live program | The program | Hardware only |
| Async coding agents [39][41][42] | Vendor cloud sandbox | One pull request | The diff | Per agent-work unit, hard session ceilings |
| open-game-works-core [44] | Local, on the operator's machine | A merged change plus a report | The report | Hardware only |
| GameForge [46] | Local, on the operator's machine | A playable Godot project plus staged diffs | Approve, Edit, Regenerate, Cancel | Hardware only |
| Voyager [50] | Remote API model inside Minecraft | A growing library of executable skills | The skill library | Tokens, plus a long API dependency |
| builder-ide [1] | Local Thor and thin client | A recipe, its branches, and a ledger | The world, in-world | Hardware only, with power and wall clock |

Three patterns in that table carry most of the weight of this survey. The async artefact is a diff or a plan everywhere except builder-ide, whose artefact is the world itself. Metering is per unit of agent work everywhere except the local products, where the only limits are hardware, power, and wall clock. And the human review surface is a text diff everywhere except Roblox's plan and builder-ide's in-world view.

## 6. Where builder-ide is genuinely different

**Local, unmetered, and sovereign.** No surveyed product runs a world builder overnight on the operator's own hardware. Unity's agentic tooling requires the project to be linked to Unity Cloud [11]; Roblox's long-form workflows are explicitly cloud [3]; every async coding agent runs in a vendor sandbox with metered quotas [39][41][42]. The local box is not a privacy feature in this landscape, it is an economic one, because the alternatives charge by the unit of agent work while a local box charges by the watt.

**The recipe as the unit of truth.** A night of work in builder-ide leaves kilobytes of declarative recipe, which is diffable, branchable, replayable, and reviewable. Every other async product in the survey leaves a code diff, which is diffable but not comprehensible to a non-programmer, and a plan, which is comprehensible but not the artefact [4][39][41]. A recipe is the only object in this survey that is both the plan and the world.

**Data rather than code for agent changes.** The internal rule that agents change data and not code, and that a prediction is sealed before the test, has no counterpart anywhere in the survey. Every in-editor agent writes scripts, and every coding agent writes code, which means the artefact a human reviews is always a program [3][9][39][41]. This is the most genuinely novel design decision in builder-ide and the one the landscape is furthest from.

**Taste memory with denominators.** The ledger scores the user's own prior predictions against their verdicts, which is a growth axis no surveyed system measures. Voyager's skill library is the closest structural precedent, and it grows along capability rather than taste, with no notion of a user's aesthetic preference [50][51]. Promethean AI claimed to learn individual tastes [15], but it is a closed B2B product with unmeasured claims.

**Vocabulary extension as a reviewed promotion.** Work orders that let characters extend a closed typed vocabulary, gated by human approval, have no counterpart. The nearest things are skills packages [5][12][36] and MCP tool sets, which are vendored or hand-written rather than grown through a branch-and-review process.

**Two growth axes in one product.** The builder-ide design grows capability, through recipes and generators the characters learned or wrote, and taste, through the ledger, in the same product and in the same characters [1]. No surveyed system runs both.

**The in-world avatar as a view of an agent session.** Roblox's screen-capture subagent, which describes the viewport back to the Assistant, is the nearest precedent [4][6], and it stops short of treating the world as the primary view of the agent's work.

## 7. Where builder-ide is not yet different

**Nothing user-visible is built.** The phase plan starts with a feasibility spike, and there is no public prototype, no users, no community, and no distribution. The 44% Roblox adoption figure describes a platform with a very large audience and an installed base [3], and builder-ide's counterfactual is one operator and one box.

**Every experience promise is currently unbacked.** The internal cross-review records that every in-world, voice, and critic-latency promise in both experience reports is unbacked by any measurement, and that the technology has not yet chosen a Critic [2]. The unresolved questions are structural rather than cosmetic: who writes the ledger, whether the Critic judges by taste or by checkable defect, how the characters speak or tap, how much power they hold, whether one budget bar or three rails apply, and whether bulk approval or per-action risk gating applies [2]. The work-order acceptance check, that the critic passes work at twice the target load, has no definition at all.

**The world has an unresolved first spike.** The Thor currently carries Blender 4.0.2, the target is 4.2, and the install matrix has no Linux ARM64 column [1]. The engine fork is a standing maintenance obligation against an upstream with roughly 7,400 stars that has itself moved to a V2 line [58].

**No measurement of anything.** No timings, no render budget, no token cost, no taste-curve, no evaluation harness. Voyager had a benchmark, in unique items and tech-tree milestones, and the taste ledger's value is precisely the thing that cannot be verified without a long-running user who has an opinion [50].

**Single-operator, single-box, single point of failure.** The 122GB figure is a ceiling on one machine, and the hot, warm, and cold scheduler plan is a design rather than a measurement [1].

**A contested position in a consolidating market.** The engine vendors have converged on the editor as a protocol server with the model supplied by a third party, which means the engine layer is being commoditised from above [6][10][13]. The platform vendors are shipping local-capable models and local-capable hardware at consumer prices [32][33][34].

## 8. Threats and opportunities

### 8.1 The threat if world models get good enough

The threat is not that a world model generates prettier worlds. It is that the split of labour between state and appearance, which builder-ide depends on, moves.

- **Pixel-bound world models** leave builder-ide unaffected. Genie 4 renders and verifies in pixels with no editable scene [18][19], and Atlas is early access only [22]. The world model becomes a draft renderer for the Critic's preview.
- **Exportable and editable world models** erode the asset half of the recipe. HY-World 2.0 already produces editable, persistent meshes and Gaussian splats importable into Blender, Unity, Unreal, and Isaac Sim [27], and the World API already exports navigable worlds into simulators [21]. This is the scenario that bites, and it bites sooner than it looks.
- **Persistent and controllable world models** threaten the growth loop itself. If a world model can hold state across sessions, the memory moves out of the ledger and into the world, and builder-ide's distinguishing asset becomes less distinct [24][22].
- **A local, open-weights, controllable world model** is the scenario that matters, because it removes the local advantage entirely. The ingredients are already public: Matrix-Game 4.0 running an engine plus a renderer at 67 frames per second on an RTX 5080 [28], EdenLive at 24.7 frames per second on a single RTX 5090 with state evolution delegated to coding agents [29], and Nemotron 3.5 Bolt 74B-A9B 24GB with weights, training data, and recipes released [33]. A Thor has 122GB. If a controllable local world model lands on that hardware within eighteen months, "local Thor-native" stops being a differentiator and becomes table stakes, and the only remaining moat is taste memory with evidence.

The defence that follows from this is structural rather than rhetorical. The parts of builder-ide that survive all four scenarios are the ledger, the vocabulary, the growth loop, and the local budget; the part that does not survive is a hand-authored asset pipeline, and the vision document already treats the prop-maker as pluggable [1]. Keep the pluggable part pluggable.

### 8.2 Pieces worth using rather than building

Three standards and formats are worth taking rather than building.

- **A SimReady-shaped validator and acceptance standard.** A named, versioned requirement set with per-requirement severity, target, and authored location, plus a validator that reports against it, is exactly the shape of the Critic's verdict that the internal design calls for and that the work-order acceptance check still lacks [36][37][38]. Apache-2.0.
- **Skills as Markdown with frontmatter.** Roblox, Unity, NVIDIA, IvanMurzak's MCP bridges, Claude Code Game Studios, and EdenLive's EdenGolem all converged on the same package shape [5][12][29][36][47][48]. The internal plan to export recipes as portable SKILL.md packages should adopt that shape rather than invent one, so that the ship's computer can consume other ecosystems' skills.
- **The state-appearance decoupling as an explicit interface.** Matrix-Game and EdenLive both prove it works and both show how to expose it [28][29]. Adopting their separation as a named interface between the program and the renderer would make the recipe swappable between Cycles, a neural renderer, and whatever ships next.

Three further items concern content weights and the engine base.

- **Open generation weights for asset work.** HunyuanWorld 1.0 and its relatives [25], HY-World 2.0 [27], and EdenLive's weights [29] are usable now, subject to licence. The Tencent licence excludes the EU, UK, and South Korea, forbids training on outputs, and requires a separate licence above one million monthly active users [26]; EdenLive's `flux-c2f` weights sit under the FLUX non-commercial licence rather than Apache-2.0 [29]. The internal rule that licences are a checked list is the right rule, and this survey supplies concrete entries for it.
- **The blind-judge trick.** open-game-works-core's judge agents play the game blind against the previous version, and completeness is checked by bot playtests, profiling, and UI captures [44]. That is a cheap, concrete form of adversarial review that the internal Critic design does not yet have, and it maps onto the sealed-prediction rule.
- **The upstream engine, kept as a fork.** Infinigen is BSD-3-Clause, actively maintained as of 14 October 2026, with branches for nature, interiors, and articulated subjects and export paths to simulators [58]. The port should be kept as a thin fork with a tested upstream sync rather than diverged.

### 8.3 Pieces worth avoiding

Three of these concern product shape.

- **Building an assistant.** Roblox and Unity have both spent far more money on the same surface, and Unity has explicitly abdicated the model layer to third parties [11]. builder-ide's assistant should be a view of the world, not a chat panel competing for the same attention.
- **A pull-request-shaped workflow.** The entire async-coding-agent industry converged on a diff as the reviewable artefact [39][41][42], and it works there because the reader is a programmer. The reader of a recipe is not.
- **Generating the world.** Every serious implementation in section 3.3 keeps state in an executable program and treats the generative model as a renderer [27][28][29]. Making the model authoritative over state would forfeit the diffability that makes the whole design work.

Three further items concern where the night runs and what it depends on.

- **A cloud agent for the night.** It is the default choice across the industry and it is the one choice that forfeits the local thesis and adds per-unit metering to the part of the work that should be cheapest [39][41][42].
- **An org chart of many agents.** Claude Code Game Studios shows how popular the packaging is [47], and how much of the popularity is packaging. The five builder-ide characters are a vocabulary constraint, not an org chart, and collapsing them into a generic agent pool would destroy the thing that makes them legible.
- **Closed dependencies anywhere in the night loop.** Inworld retired Character Studio and rewrote everything built on it [56]. Any dependency that can be retired should sit outside the loop that runs unattended.

## 9. Decisions this survey forces

1. **Adopt a named acceptance standard for work orders before choosing a Critic.** The Critic's verdict shape, hold, fix, or keep with a reason code, is specified in the internal design [2] and is the same shape as SimReady's per-requirement report [36][37]. Picking the standard first makes the Critic an implementation rather than a design project.
2. **Make the recipe the reviewable artefact and refuse the pull-request shape.** This is the one decision where the landscape offers no precedent to copy, and therefore the one most likely to be uniquely ours.
3. **Treat the local box as the product constraint that prices everything else.** Metering per unit of agent work is the norm across the cloud incumbents [39][41][42], which means local execution is a cost position and not only a privacy position.
4. **Keep the prop-maker and the renderer swappable, and watch HY-World 2.0 as the leading indicator.** Editable, persistent, open-weights world generation arrived in April 2026 [27]; the day it becomes good enough to write the recipe's assets is the day the asset half of the product is a solved problem.
5. **Do not build the world-model layer.** Section 3.3 shows four independent implementations of the same decoupling [27][28][29][1]. The scarce thing is not generation, it is generation with taste memory, and generation is converging on open weights with a floor.
6. **Instrument the taste ledger before claiming the growth loop.** The ledger is the differentiator, it is also the part with no external precedent and therefore no benchmark, and Voyager's skill library only demonstrated its value because it was measured against baselines [50][51]. Without an evaluation harness, the central claim of the product is unfalsifiable, which is the same failure mode the internal review already identifies in the Critic [2].

## References

All URLs verified 2026-10-30. Entries are numbered in order of first citation.

1. builder-ide, `docs/vision.md`, internal design document, read 30 Oct 2026. `/home/caseydigennaro/src/builder-ide/docs/vision.md`
2. builder-ide, `docs/research/rev-ux.md`, internal cross-review of the two experience reports, read 30 Oct 2026. `/home/caseydigennaro/src/builder-ide/docs/research/rev-ux.md`
3. Roblox, "Roblox Studio: Going Agentic", newsroom, 15 Apr 2026. https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
4. Roblox, "Assistant for Studio", documentation. https://create.roblox.com/docs/assistant/guide
5. Roblox, "Skills", documentation. https://create.roblox.com/docs/assistant/skills
6. Roblox, "Connect to the Roblox Studio MCP server", documentation. https://create.roblox.com/docs/studio/mcp
7. Roblox, "Accelerated workflows", documentation. https://create.roblox.com/docs/ai/accelerated-workflows
8. Unity, "Unity AI: How to get started", 5 May 2026. https://unity.com/blog/unity-ai-how-to-get-started
9. Unity, "The in-editor AI Assistant: Ask, Plan, and Agent modes explained", 6 May 2026. https://unity.com/blog/unity-ai-assistant-ask-plan-agent-mode-explained
10. Unity, "Unity AI MCP: how to get started", 11 May 2026. https://unity.com/blog/unity-ai-mcp-how-to-get-started
11. Unity, "What are Unity's AI tools?", updated Jul 2026. https://unity.com/resources/what-is-unity-ai
12. Unity, "Unity AI Assistant" package documentation, version 2.8. https://docs.unity3d.com/Packages/com.unity.ai.assistant@2.8/manual/index.html
13. Epic Games, "Unreal Engine 5.8 Release Notes". https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5.8-release-notes
14. Engadget, "Epic Games details how it's embracing generative AI in Unreal Engine", 17 Jun 2026. https://www.engadget.com/2196807/epic-games-details-how-its-embracing-gen-ai-in-unreal-engine/
15. GamesIndustry.biz, "Promethean AI promises to unlock experimentation in AAA development", 18 Jul 2018. https://www.gamesindustry.biz/promethean-ai
16. Promethean AI, "Welcome". https://www.prometheanai.com/welcome
17. Google DeepMind, "Genie 3: A new frontier for world models", 5 Aug 2025. https://deepmind.google/discover/blog/genie-3-a-new-frontier-for-world-models/
18. Google DeepMind, "Genie 4: A new generation of world simulation", 27 Oct 2026. https://deepmind.google/blog/genie-4-a-new-generation-of-world-simulation/
19. Google, "Introducing Genie 4", 27 Oct 2026. https://blog.google/innovation-and-ai/models-and-research/google-deepmind/introducing-genie-4/
20. World Labs, "Marble", 12 Nov 2025. https://www.worldlabs.ai/blog/marble-world-model
21. World Labs, "Announcing the World API", 21 Jan 2026. https://www.worldlabs.ai/blog/announcing-the-world-api
22. World Labs, "Atlas", 1 Sep 2026. https://www.worldlabs.ai/blog/atlas
23. World Labs, "World Labs is Joining AMD", 28 Sep 2026. https://www.worldlabs.ai/blog/amd-announcement
24. World Labs, "A Functional Taxonomy of World Models", 3 Jun 2026. https://www.worldlabs.ai/blog/taxonomy-of-world-models
25. Tencent Hunyuan, "HunyuanWorld-1.0", repository, Jul 2025. https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0
26. Tencent Hunyuan, "HY-World 1.5 (WorldPlay)", repository, released 17 Dec 2025. https://github.com/Tencent-Hunyuan/HY-WorldPlay
27. Tencent Hunyuan, "HY-World 2.0", repository, released 16 Apr 2026. https://github.com/Tencent-Hunyuan/HY-World-2.0
28. Skywork AI, "Matrix-Game", repository, v4.0 released 15 Oct 2026. https://github.com/SkyworkAI/Matrix-Game
29. VAST AI Research, "EdenLive", repository. https://github.com/VAST-AI-Research/EdenLive
30. Robbyant, "LingBot-World", repository. https://github.com/Robbyant/lingbot-world
31. NVIDIA, "ACE for Games". https://developer.nvidia.com/ace-for-games
32. NVIDIA Developer Blog, "NVIDIA RTX Spark Powers Neural Rendering and AI Characters in Games", 27 Oct 2026. https://developer.nvidia.com/blog/nvidia-rtx-spark-powers-neural-rendering-and-ai-characters-in-games/
33. NVIDIA Blog, "Open From Data Center to Desktop: NVIDIA Expands Nemotron Family With Highest Efficiency Super VL and Bolt Models", 15 Oct 2026. https://blogs.nvidia.com/blog/nemotron-3.5-super-vl/
34. NVIDIA Blog, "All Systems Go: Global PC App Ecosystem Ready for NVIDIA RTX Spark", 13 Oct 2026. https://blogs.nvidia.com/blog/local-ai-rtx-spark-laptops-software-updates/
35. NVIDIA, "Omniverse", developer portal. https://developer.nvidia.com/omniverse
36. NVIDIA, "NVIDIA Omniverse libraries now available in NVIDIA Agent Toolkit", press release, 20 Jul 2026. https://investor.nvidia.com/news/nvidia-announces-omniverse-libraries-now-available-in-nvidia-agent-toolkit/
37. NVIDIA, "SimReady", documentation. https://docs.omniverse.nvidia.com/simready/latest/overview.html
38. NVIDIA, "simready-foundation", repository, Apache-2.0. https://github.com/NVIDIA/simready-foundation
39. GitHub, "GitHub Copilot is moving to usage-based billing", 1 Jun 2026. https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/
40. GitHub, "GitHub Copilot plans". https://github.com/features/copilot/plans
41. Google, "Jules". https://jules.google/
42. Devin, "Pricing". https://devin.ai/pricing
43. Cognition, "Devin 2". https://cognition.ai/blog/devin-2
44. wnsrn3436, "open-game-works-core", repository, Apache-2.0, updated Oct 2026. https://github.com/wnsrn3436/open-game-works-core
45. J-Gierend, "gamePocGen", repository, no licence file, updated Aug 2026. https://github.com/J-Gierend/gamePocGen
46. XyoLua Studios, "GameForge", repository, Apache-2.0, updated Oct 2026. https://github.com/xyoluastudios/xyolua-gameforge
47. Donchitos, "Claude Code Game Studios", repository, MIT licence, updated Oct 2026. https://github.com/Donchitos/Claude-Code-Game-Studios
48. IvanMurzak, "Unity-MCP", repository, Apache-2.0, updated Oct 2026. https://github.com/IvanMurzak/Unity-MCP
49. IvanMurzak, "Godot-MCP", repository, Apache-2.0. https://github.com/IvanMurzak/Godot-MCP
50. Guanzhi Wang et al., "Voyager: An Open-Ended Embodied Agent with Large Language Models", arXiv:2305.16291, 25 May 2023. https://arxiv.org/abs/2305.16291
51. MineDojo, "Voyager", repository, MIT licence, last updated Apr 2024. https://github.com/MineDojo/Voyager
52. Mindcraft, "mindcraft", repository, MIT licence, updated Oct 2026. https://github.com/mindcraft-bots/mindcraft
53. soapantelope, "mindcraft", text-conditioned infinite worlds mod, repository, updated Jun 2026. https://github.com/soapantelope/mindcraft
54. Inworld, "The new AI infrastructure for scaling games, media, and characters", 15 Oct 2025. https://www.inworld.ai/blog/new-ai-infrastructure-scaling-games-media-characters
55. Inworld, "Unreal AI Runtime: The first unified interactive AI toolkit for game developers", 29 Oct 2025. https://www.inworld.ai/blog/introducing-unreal-ai-runtime-sdk
56. Inworld, "Character Studio deprecation", documentation, updated Oct 2026. https://docs.inworld.ai/character-studio-deprecation
57. Inworld, "Pricing". https://inworld.ai/pricing
58. Princeton Vision and Learning Lab, "Infinigen", repository, BSD-3-Clause, updated Oct 2026. https://github.com/princeton-vl/infinigen

## Internal sources

Two builder-ide documents were read to establish what is being differentiated. Section 6 and section 7 map directly onto the commitments in `docs/vision.md` [1], and the open questions named in section 7 are the unresolved conflicts recorded in `docs/research/rev-ux.md` [2], whose merged experience spine is the fifteen-moment sequence the survey compares the external approval contracts against. Section 8.2 maps the "licences are a checked list" rule onto the specific entries collected here.
