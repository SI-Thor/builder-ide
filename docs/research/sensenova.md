# OpenSenseNova (SenseTime): what we can use (2026-10-31)

Source: https://github.com/OpenSenseNova (SenseTime's open foundation-model org). Casey: "interesting". We surveyed its 30 repos and read the six most relevant. Licences are per repo.

## 1. Looped models: depth from time, not memory
- **SenseNova-Loop-9B-Preview** (Apache-2.0, released 2026-10-30). A contiguous block of **24 decoder layers runs twice with shared weights**: 56 layer executions from 32 distinct layers. Learned two-stream "hyper-connections" route between the passes, and attention is hybrid linear/full.
- **Looped-DiT** (MIT; training plus *inference at any loop depth*). A diffusion transformer runs a shared group of blocks several times per denoising step: "deeper without getting larger". Naive looping does not reliably help. Two additions make it work:
  - **deep supervision**, which decodes the state after *every* loop and trains each prediction on the clean target;
  - **self-modulating attention**, which gates the updates inside the loop.

**Why it matters on the Thor.** The Thor's two finite resources are memory, shared by everything resident, and time, which is free at night ("presence"). A looped model holds one copy of its weights and buys quality with **loop count**, a runtime dial.
- **Live:** few loops, fast.
- **Night:** many loops, the same memory.

This is the precision ladder's twin: precision trades memory for quality; loops trade time for quality.

**Deep supervision makes the model "anytime".** Every loop's output is a valid answer, so it fits **never-wait** exactly. At the deadline, commit the best loop so far, and record a later, deeper answer as a supersede. **Seed 160.**

## 2. SenseNova-RoboRSI: recursive self-improvement for embodied agents
Apache-2.0; the code is landing in stages, with RoboRSI-27B-Preview weights on HF.
- **The mechanism:** a shared runtime builds, evaluates and *recursively improves* embodied agents, with "**ICL experience packages**" per benchmark (in-context experience distilled from earlier runs).
- **Reported:** LIBERO-PRO 98.25% (No. 1); RoboLab No. 1; RoboDojo 54.17% success against the GPT-6 Astra baseline's 28.97 points.

**For us it is the mediator loop with a name.** Experience packages are tiles: cloud-written, reused by the reflex, kept when they win. agent-world can borrow the shape. Each bot skill keeps an experience package that the coach updates after sessions, and success with vs without the package is the metric. The 27B model is an LLM-class policy, so it does not go on the Thor (B2); we take the method.

## 3. SenseNova-SI: spatial intelligence at 8B
Apache-2.0; models on HF; the SenseNova-SI-8M dataset.
- **What it is:** VLMs trained on an 8-million-sample spatial taxonomy (depth, grounding, relations, geometry). It includes **SenseNova-SI-1.3-Qwen3-VL-8B**, the same base as the Qwen3-VL-8B Casey approved locally for the SceneBloom evaluation.
- **For us:** an extra arm in `scenebloom-eval`. Spatial plausibility of layouts ("is the lantern on the table, is the door reachable") scored by a spatially trained 8B vs the plain one, under the same job-scoped exception: leased, never resident.

## 4. SenseNova 6.8 Code2Video: video by writing code
No licence file in the repo, so ideas only.
- **The mechanism:** a 27B model (from Qwen3.8-27B) writes executable code that renders the video. Code can call image, video and 3D tools, so the result is **grounded** (motion from equations, not sampled pixels) and **editable**.
- **This is our B2 split for video:** the cloud model writes the script, and deterministic renderers do the pixels.

**Use:** the ProArt presentation side. A cloud seat writes the code for short explainer videos of a night's results, rendered locally from the real data and the thor-world viewer, for Casey and Magnus. Their `code-video` skill's craft guides are worth reading as a checklist.

## Not for us now
- **SenseSpec / vllm4spec:** draft-model training for speculative decoding needs 8× H100. Revisit only if Seed-OSS serving needs speculative decoding.
- **MemSense, the Skills repos, U1 / Vision:** general assistants and unified generation, not our bottleneck.

## Seeds
- **160. The anytime looped model for never-wait.** Use a deep-supervised looped model (Looped-DiT for images now; looped decision models later). Measure quality vs loop count, and commit-at-deadline quality vs a fixed-depth model of the same memory. Night: many loops; live: few.
- **161. Experience packages per bot skill (RoboRSI).** The coach updates a skill's package after sessions. Measure success with vs without it, matched by seed.
