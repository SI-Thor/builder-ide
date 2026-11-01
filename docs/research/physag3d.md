# PhysAg3D: image to interactive asset, by an agent around a 3D generator (2026-10-31)

Sources:
- the project page: https://supra-3d.github.io/PhysAg3D/;
- the code: https://github.com/Supra-3D/PhysAg3D (MIT, 13 commits, no release);
- the paper: arXiv 2610.39924, a research manuscript (PKU, Huawei, Wuhan University).

Casey asked us to study it. The arXiv tables were not checked; the numbers below are the project page's.

## What it does
**One image in; an asset that moves out.** The outputs are:
- a refined GLB and an editable Blender file;
- a **MuJoCo scene**;
- a motion video;
- a `delivery.json` recording `interaction_status`, `physics_status`, `motion_kind` (simulated replay, parameterized animation or static) and `limitations`.

It handles rigid articulation (joints) and compliant deformation.

## The mechanism
1. **A vision-language agent reads the image** and proposes semantic parts, candidate interactions ("the lid opens"), and physical priors.
2. **A pretrained 3D generator** (TRELLIS.2) makes the textured whole-object mesh from the same image. There is no joint training: the generator stays frozen.
3. **A hierarchical interaction representation** links each prior to a mechanism, and each mechanism to the generated surfaces it controls.
4. **The agent builds the parts, joints and deformable regions** with geometry and physics tools, keeping the generator's useful geometry and materials.
5. **Closed-loop repair:** renders and execution measurements in MuJoCo drive targeted revisions within a fixed budget. The defaults are 3 h per case, ≤ 2 acceptance passes and ≤ 2 repair rounds.

**Measured:** 50 in-the-wild objects with 110 predefined actions. The action completion rate is **91.3%**, and the function-and-visible-stability pass is **88.0%**.

**What it does not do:** mass and material parameters are *estimates*, recorded as such. "A single image does not uniquely determine hidden mechanisms or material parameters."

## Why it fits our split
It is our B2 architecture, built by someone else:
- **the cloud agent writes the script** (parts, joints, priors, repairs);
- **local models do the geometry and the physics** (the generator, MuJoCo, Blender).

On our box, the agent's work runs on cloud models (z.ai, MiniMax, Claude), and the Thor runs the generator and the simulation. Their requirement is "≥ 28 GiB free GPU memory on the generation host", which fits a thor-admit lease. Their controller is Windows plus Codex CLI. Ours would be a seat or the night, with the Thor as the generation host.

## What it gives us
1. **Props that work, not only props that look right.** The critic's plausibility check today is visual. PhysAg3D adds *functional* acceptance: does the drawer open, does the lantern hang, does the stack stand? These are measured by executing in a simulator. That is the anti-GAN rule in its strongest form: the verdict is a test that runs, and the repair is the continuation.
2. **The missing half is in SimReady.** PhysAg3D's weak point is mass and material, which it guesses. NVIDIA SimReady (`simready.md`, queued) carries measured physics per category. **Seed 159:** SimReady priors feed the agent's physical priors, and the generated asset is scored against SimReady's ranges.
3. **The delivery contract is worth copying.** We would record, per asset, what was verified and what was estimated (`physics_status`, `limitations`). That is the honest record, and the morning report can say "the hinge works; the mass is a guess".
4. **Agent-world and thor-motion targets.** Articulated props are things Minecraft-adjacent bots and thor-motion characters can *use* (open, push, carry), and the coach can teach it.
5. **The budget is a night job.** At 3 h per case it belongs in the presence tier, not in a live preview. The night sends one batch of props through it, ranked by how often the builders use them.

## On the Thor (estimates, to measure)
- **TRELLIS v1** is in our stack already: 55–68 GB peak in fp8-real, under the heavy lock.
- **TRELLIS.2, DINOv3 and BiRefNet** are separate downloads with their own licences, each to check.
- **MuJoCo** has aarch64 wheels.

The orchestrator is MIT code from outside, so **building or running it needs Casey's explicit OK** (CLAUDE.md). A reimplementation of the loop inside builder-ide, credited, would need the same check.

## Next (proposed)
A night experiment: "physag-lite". For 10 props the builders use often:
- a cloud seat proposes parts and joints;
- TRELLIS (v1, our stack) generates;
- a MuJoCo check executes the predefined action;
- one repair round.

Measure the action completion rate against PhysAg3D's 91.3%, plus the time and the GPU-hours per prop. Then compare with SimReady priors (seed 159).
