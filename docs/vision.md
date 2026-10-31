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
   night's jobs by model to avoid thrash. The cast: a planner/companion (a local
   LLM, plus the cloud on a budget), a critic (a vision model that looks at
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
