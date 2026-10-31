# builder-ide — the vision (2026-10-30)

> You and your builders shape a world together. Leave them working in-world
> overnight; come back the next day to hours of work done. The builders are
> avatars who grow with you.

## Why this, and why on the Thor

Real-time game brains (last-mile) spend the Thor in milliseconds. Procedural
worlds want the opposite: long, patient, memory-hungry generation, agents that
take their time, and models swapped in and out by task. That is what a box with
122 GB of unified memory and a big GPU is good at, while its owner sleeps.

## The pieces

1. **infinigen-thor: the world engine.** A Thor-native Infinigen. Most of
   Infinigen is Python and Blender node graphs that should run on aarch64; the
   work is Blender 4.2 (bpy) on Linux ARM64, Cycles on the Thor's GPU, the
   terrain C++/CUDA built for aarch64 and Blackwell, and then making it
   *interactive*: warm scenes kept in memory and edited in place, instead of
   cluster-style batch regeneration.
2. **The recipe.** A project is its recipe (generators, parameters,
   constraints, seeds); meshes and renders are caches. Diffable, branchable,
   replayable; a night's work is kilobytes.
3. **The model scheduler.** Owns GPU memory (hot / warm / cold); batches a
   night's jobs by model to avoid thrash. The cast: a planner/companion (a cloud
   LLM; never hosted on the Thor, see below), a critic (a vision model that looks at
   every render), a concept and texture artist (image gen), a prop-maker
   (image-to-3D). Each one is swappable, and chosen for how well it runs on the
   Thor.
4. **The builders.** A small team of characters: Architect (layouts through
   Infinigen Indoors' constraint language), Landscaper (terrain, plants,
   weather, season), Prop-maker, Critic, and a Companion who talks with you and
   keeps the plan. They change the recipe only through a closed, typed
   vocabulary, and they predict before they render (seal, test, verdict, undo).
5. **The overnight loop.** Plan together before bed, then work a task queue
   under a budget of hours and model time. Each step: recipe edit, prediction,
   preview, critic check, keep or revert. In the morning, a report: a timeline
   of before and after, what was tried and dropped and why, two or three
   branches to choose from, and the questions they parked for you.
6. **Growing with you.** A taste ledger of what you kept and rejected, with a
   running tally of how often their predictions about you held; skills (recipes
   and generators they learned or wrote); a character and a speciality each.
7. **The IDE, headless first.** The builders are agent sessions behind a
   protocol. Front ends attach to them: an in-world avatar view; a desktop or
   web IDE (Eclipse Theia, EPL-2.0, is built to be a cut-down, extensible IDE
   platform with AI features); an editor (Zed: GPL-3 for the editor and Apache
   for parts; it speaks the Agent Client Protocol); or MCP. **An avatar is a
   view of an agent session.** Prefer the protocols over forking a whole editor.
8. **The thin client.** The ProArt views the live world (streamed glTF/USD) and
   renders fast previews on its own GPU; the Thor generates and does final
   renders.

## The architecture: three layers (the holodeck as north star)

We cannot build the holodeck. We can build toward its UX with what we have.

1. **The program**: the world. A recipe plus the engine (infinigen-thor):
   generate, render, history.
2. **Characters**: the avatars in the simulation (Architect, Landscaper,
   Critic, Companion). Personas you talk to and watch work. Their words come
   from cloud LLMs; their choices and their bodies run on the Thor, through
   small local decision models and motion policies. They **never write
   code**: they change the world only through the closed, typed vocabulary
   (predict, render, keep or undo).
3. **The ship's computer / chief engineer**: the backend agents, and the only
   layer that changes the program itself: new generators, engine fixes, new
   vocabulary words, the Infinigen port. Slow, powerful, sandboxed, working in
   branches, gated by tests (a render plus the critic) before anything goes
   live.

**The work order is the bridge.** A character that hits a limit ("I can't make
gothic arches"), or the human ("Computer, I want rope bridges"), files a work
order. The engineer takes it, builds and tests it in the background, and
promotes it into the vocabulary; the next morning the Architect can build
arches. The builders grow with you twice: they learn your taste, and the
computer extends what they can do.

**The engineer is pluggable** behind one adapter (in: a work order and a
sandbox branch; out: a commit and test evidence): Claude Code for hard orders on
a budget, zcode/mcode (z.ai and MiniMax subscriptions) for bulk, other cloud
subscriptions as they prove themselves, OpenHands or Goose as sandboxed runtimes, worth a test. Zed and Theia are
front ends onto the engineer's work (via ACP), not backends.

**The core is ours and small:** a durable service on the Thor owning work
orders, budgets and approvals, the recipe store and history, the model
scheduler, the vocabulary and the audit log. Plain Python first (the seed is
the brief → worktree → seat → review → merge-gate loop run in `~/lm-ops` during
last-mile); adopt LangGraph only if its checkpointing beats ours.

### Calling the computer in-game, with less text

The computer can be called from inside the world ("Computer, make these
sturdier") and already knows the situation, so a few spoken words become a full
work order. The core keeps a **context packet** that it attaches to every call:

- **what you mean by "this/these/here"**: the current selection, what you are
  looking at (the camera ray and the objects under it), and where you are
  standing;
- **recent history**: the last recipe changes, renders and critic notes,
  including who changed what (you, or which character);
- **the conversation**: what you and the characters just said, as the bounded
  labels the vocabulary already keeps;
- **the project state**: the branch, the open work orders, the budget left
  tonight, the vocabulary and its gaps.

From that the computer **compiles** the terse request into a full work order
(the goal, the objects named by id, the acceptance check, a budget), and
**confirms it in one line** before it starts ("Reinforce the 3 arches on the
east bridge so the critic passes them at 2x load; about 20 minutes; go?"). The
coding run then goes on in the background while you keep building. When it
lands, the change shows up in-world as a preview you can keep or reject, with
its evidence one click away. Ambiguity is resolved by asking, never by guessing:
if "these" could mean two groups, the computer asks which.

This is how speech stays short: the context does the explaining, as it does
between people who are standing in the same room.

### The engineer also makes things: characters, objects and generative batches

The ship's computer is consulted for **character and object changes** as well
as code: "Computer, give the Landscaper a lantern and a slower walk", "make this
chair Victorian". Two paths, chosen by what the request needs:

- **Text to a recipe, through curated, typed building blocks.** The model is
  nexu-io/motion-anything (Apache-2.0, 2026-07): describe the feeling and the
  agent ships the motion. That project is about web and UI motion (shaders,
  kinetic text, page animation), not 3D characters, but its *pattern* is the
  one we want. A library of recipes, each carrying taste ("avoid when ...").
  A router that picks from it by intent. Recipes exported as portable skills
  (SKILL.md). The agent engine plugged in over ACP. For us: character looks,
  props, materials and motions are recipe entries with taste notes, chosen and
  composed by intent, and new entries are added as work orders.
- **Generation, when the library has nothing that fits.** The builder sets up
  **generative batches**, run through the model scheduler (overnight if large),
  and returns candidates scored by the critic for you to pick from:
  - **textures and materials**: image generation, then the PBR maps the
    renderer needs;
  - **3D objects and props**: image-to-3D, then cleaned and scaled into the
    scene;
  - **CAD-precise parts** (hinges, gears, machinery): the engineer writes
    parametric CAD code (e.g. CadQuery). Deterministic and parametric, so it is
    recipe-native: a small script, not a mesh;
  - **character motion**: text-to-motion models producing skeletal clips,
    retargeted onto the avatar's rig;
  - **music and sound**: text-to-music and sound-effect models for the place's
    ambience and the builders' work sounds.

Every generated asset enters the project's library with its **provenance**
(prompt, model, seed, version) and **licence** (several image and music model
weights are non-commercial: a checked list, not an afterthought), so it can be
regenerated, traced and swapped when a better Thor-native model arrives.

## The Thor is an iterator (Casey, 2026-10-31)

Don't use the Thor only as a box that runs one big model once. Use it as an
**iterator**: models and scenes stay resident in unified memory, so many fast
**propose → critique → refine** cycles are cheap. The builders' work is
shaped as converging loops, not single shots:

- **At night, breadth.** For each step in the plan, generate many variants
  (seeds, parameters, alternative recipe edits), score them with the critics,
  keep the best, and refine from it. The morning report shows the winner *and*
  what it beat.
- **By day, warm starts.** A loop starts from the last converged result, not
  from scratch, so it converges in a few iterations while you watch.
- **Many agents, one pass.** Builders share resident models and are batched
  through them together. On the Thor, memory bandwidth is the wall, and
  batching N agents costs roughly what one does (lab round 3 measures where
  that stops holding).
- **Iteration is the budget.** The night's rails are spent as iterations per
  goal, and the quality gained per iteration (and per joule, from the power
  rails) decides how deep a loop goes before it stops.

## What the Thor is for (Casey, B2, 2026-10-31)

**No LLMs on the Thor.** Language comes from the cloud: the z.ai, MiniMax
and Claude subscriptions, and more as they earn a place. Each is a parameter
priced per call; Opus is used where its cost is worth it. On the Thor, LLMs
are slow or weak, and they take memory the renderer and the decision models
want.

**The Thor does what the cloud can't do cheaply:**

- **Motion as virtual robotics.** The builders are robots in a simulation.
  Their walking, reaching, carrying and building are policies trained and
  run on the GPU (RL, motion optimisation), not canned clips.
- **Visual assets:** images, textures, props and terrain, batched overnight.
- **World models and engines:** Infinigen, the resident scene, the stage
  cache, and the game engines that host the world.
- **Many small decision models:** fast enough for agents and game engines
  to call every tick.

**The system that gets better.** Cloud LLMs write **scripts**: a behaviour,
a build step, a recipe edit. Those scripts become **tiles**: the options a
local decision model chooses between in the moment. Every time a tile is
played, its outcome in the game is recorded, win or lose. The collections of
winning and losing scripts grow, and the decision models are trained on them
over time.

- The cloud is the **author**: slow, smart, and it writes the options.
- The Thor is the **player and the learner**: fast, and it learns which
  options work, and when.
- Each night adds scripts and outcomes, so the builders get better from both
  ends.

### The first mile is on the ProArt (Casey, 2026-10-31)

The human's side of every exchange is fast and local. A small Liquid voice or omni model (LFM3-Audio-2B / LFM3-Omni-2B) on the ProArt's GPU listens, takes turns and **answers within a breath**: "on it", or "the east span or the north?". It never waits on the slow paths. Behind it, it routes:

- **quick typed questions** go to decision models (d1, Clef, Jev);
- **world actions** go to world-mcp, with the context packet attached;
- **hard asks** become work orders for cloud LLMs and engineers;
- **assets and renders** go to the Thor.

Results come back as short spoken updates when they land. Speed is the first mile's job; depth comes from everything behind it. The spike is `first-mile` (ProArt).

## Phases

1. **Feasibility spike (days).** Blender 4.2 on the Thor; Infinigen Hello Room
   and Hello World; a Cycles GPU render; timings against the ProArt.
2. **The fork.** SI-Thor/infinigen-thor: the port, benchmarks, CI on the Thor.
3. **The core.** Recipe store, job runner, model scheduler.
4. **One night's work.** An overnight builder run and its morning report.
5. **The experience.** The thin client, avatars, builders that grow with you.

## Rules carried over from last-mile

Data, never code, for agent changes. Seal the prediction before the test.
Only decisions (recipes) travel. Measure with the box's load beside the number.
Licences are a checked list.
