# MatAnyone-E: what it is, and what we take from it (2026-10-31)

Source: https://github.com/Shuyun-Wang/MatAnyone-E (arXiv 2610.35724, S-Lab NTU; repo created 2026-10-22). Casey asked us to examine it.

## State of the release
- **The paper and the README only.** Inference code, checkpoints and the Hugging Face demo are still TODO. There is nothing to run yet.
- **Licence: NTU S-Lab License 1.0**, a research and non-commercial licence like its parent MatAnyone 2. It is fine for lab measurement; outputs must not ship in anything commercial. Building it on the Thor needs Casey's explicit OK when the code lands (CLAUDE.md approvals list).

## What it does
**Video matting:** a per-pixel alpha for the subject of a video, down to hair strands, propagated through time by a memory of past frames. The claim is native 4K at 28.6 FPS on one H200 with `torch.compile` (12× MatAnyone 2) in 3.1 GB of GPU memory. On an A800 at 1080p: 26.6 FPS / 1.66 GB, against MatAnyone 2's 13.6 FPS / 5.47 GB.

## The mechanism (the part worth keeping)
**The hardware fact.** The cost of memory matching grows with resolution × memory size, so MatAnyone 2's memory bank would need ~80 GB at 4K.

**The change: Sparse Memory Propagation.**
1. A cheap **low-resolution pass** finds the *uncertain* query locations (hair, motion blur, edges): query pruning.
2. For those locations it picks the *relevant* memory entries: memory pruning.
3. **High-resolution matching runs only on those pairs.** Everything certain is carried at low resolution.

A lightweight decoder, distilled from the original, removes the next bottleneck found by stage-wise latency profiling.

This is the same rule as our own designs, measured in someone else's domain: **pay high resolution only where the cheap pass is uncertain.**
- **Syzygy and the keyframe policy:** high-resolution looks only where they inform (`design/emitter-projector.md`).
- **The operational fiction:** as real as the decision needs (`design/three-minds.md`).
- **The precision cascade:** the d1 confidence gate escalates only uncertain items.
- **The room:** pruned edges, where only relevant memory is heard.

What theirs adds is a two-sided pruning, of *which queries* and *which memory*, both chosen by a low-resolution pass. Our cascades today prune only the queries.

## Where it could be used here
1. **Asset capture from generated video (no humans).** World-model or video-generator clips of creatures, props or characters become alpha-matted sprites and billboards for the thor-world viewer and the builders. Kids' privacy rule: no human video is captured or stored. The subjects are generated or game characters.
2. **Compositing.** Rendered characters (thor-motion, Idol) over Infinigen scenes, or the reverse, for previews.
3. **The design pattern, applied now (no code needed).** Add *memory pruning* to the cascades: when the night escalates an uncertain item to a bigger model, send only the relevant past context (retrieved tiles, prior verdicts), not the whole history. Measure the cost per escalation and the agreement. This is a seed for lab-cascade.

## On the Thor (estimate, to measure when the code lands)
The memory is small (≤ 4 GB at 4K), so it fits beside the seats without a heavy lease. The Thor has no tensor-core parity with an H200 (dense FP16 is roughly an order of magnitude lower), so expect 1080p to be real-time-ish and 4K well below the H200's 28.6 FPS. `torch.compile` on sm_110 must be checked. It is also a candidate for thor-fp4's MXFP8 activations.

## Next
- Watch the repo for the code release (scout entry); then ask Casey for the build OK.
- Seed #158 (below) goes to lab-cascade now.
