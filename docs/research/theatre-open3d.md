# Theatre.js and Open3D: what we use, what we extract (2026-11-01)

Casey: "Open3D cinematic tools / pipelines and theatre-js/theatre have tools we might be able to extract or even simply use."

## Theatre.js: keyframed motion and camera work for our web views
- **What it is:** a motion-design library for the web (three.js, DOM, any JS value) with a **visual timeline editor**: sequences, keyframes, curves, scrubbing. 12.8k stars. Public development paused since 2024-08 (1.0 is being built privately).
- **Licences, which decide how we use it:**
  - **`@theatre/core` (the runtime, plays sequences): Apache-2.0. Use freely**, including in shipped and public pages (agent-world, thor-world);
  - `@theatre/r3f` (react-three-fiber bindings): Apache-2.0;
  - **`@theatre/studio` (the editor): AGPL-3.0-only.** Fine as a *local authoring tool*: Casey or a seat edits a sequence on our LAN and exports the JSON. **Not** bundled into any page we publish or serve to others. The runtime reads the exported JSON, so studio never ships.
- **Where it fits:**
  1. **The Director's cut** (dsmc: the spectator should be a *program*, not a window). Keyframed camera moves over the live agent-world and thor-world 3D views: establishing shot, follow a builder, cut to the depot. Authored once in studio, played by core, triggered by events (a build finished, a coach cue).
  2. **The Biographer's return:** the five-beat arc (threshold, recognition, digest, thread, quiet moment) as a Theatre sequence the human advances, each beat a keyframed camera plus captions.
  3. **Keyframes, meaning-for-meaning:** Theatre's sequences are the same idea as Syzygy's precision keyframes, a few authored states with interpolation between. Its JSON format is a usable interchange for camera and motion keyframes produced by our tools (thor-motion, the night).

## Open3D: geometry and rendering we can stop rebuilding
- **What it is:** a 3D data-processing library (MIT): meshes, point clouds, voxels, registration (ICP), reconstruction, an offscreen renderer and visualiser, with camera-trajectory rendering for **cinematic flythroughs**. Active (pushed 2026-09-30).
- **Where it fits:**
  1. **The critic's geometry:** voxel occupancy (critic-shells' filled-hull measure), watertightness, normals, mesh simplification. One library instead of several ad-hoc ones (trimesh, manifold3d, scipy hulls). **Measure** it against what critic-shells and mesh-repair use before switching.
  2. **Depth to point cloud:** Infinigen's ground-truth depth to point clouds, for SceneBloom-style spatial checks and the room graph.
  3. **Offscreen thumbnails and flythroughs** of generated props and scenes, on a camera path (possibly authored in Theatre.js and exported), for the morning report and the Biographer.
  4. **aarch64 / sm_110:** check the pip wheel on the Thor (CPU builds are common; CUDA builds may need a source build). It is MIT, so a custom build is fine.

## Next (queued)
- **Theatre.js, after agent-world's playable round:** add `@theatre/core` to the agent-world viewer, with one authored "establishing shot → follow a builder → depot" sequence, triggered from the world's events. Verify in Playwright. Studio stays a local authoring tool only.
- **Open3D:** a small evaluation in the critic: occupancy, watertightness and simplification against the current tools, for speed and agreement, on the SimReady sample and the critic's reference set.

## Also queued: topview-3d-builder (2026-11-01)
https://github.com/topviewai/topview-3d-builder (Apache-2.0, TypeScript, created 2026-09-24): an agent plugin that builds a 3D scene from an idea, places cameras, plans a camera move in its "Studio", and renders an animated video. It is our B2 pattern (the agent writes the scene; local tools render) with a camera planner, so it is the natural companion to the Theatre.js work above. **Evaluate it in an isolated worktree;** its README asks agents to install it as a plugin into themselves, which we do not do without Casey's explicit OK.
