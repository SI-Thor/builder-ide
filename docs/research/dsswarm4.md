# dsswarm4: optimising with other SuperInstance ideas (2026-10-31)

`dsswarm4.md` (~59k words) is a long conversation that builds on the crew's repos. Casey's read: "it rabbit trailed around but there's some mechanisms of good for sure". The DeepSeek library separated the mechanisms from the trails ($0.05). This is the director's sorting.

## Mechanisms worth keeping

| Mechanism | What it is | Where it lands for us |
|---|---|---|
| **A CPU gate for small checks, the GPU for large batches** | Invariant checks on a few candidates are CPU-shaped (branchy, tiny); thousands at once are GPU-shaped. The chat puts the switch at ~256 instances | The same law our measurements keep finding: AVX-512 beat the RTX 4050 at small N, and NVFP4 wins only at K ≥ 2048. `ct-thor` is measuring the CPU/GPU crossover on the Thor; thor-admit and the tiles' invariant kernel should route by that number |
| **A branchless error-mask kernel** | One thread per value, one byte out, no divergence (from `flux-gpu`) | The GPU half of the gate; already in ct-thor's experiment 2 |
| **A persistent kernel polling a lock-free queue in unified memory** | The kernel stays resident and pulls work, so no launch per batch | Our zero-copy result makes the queue shareable by CPU and GPU without copies; an alternative to CUDA Graphs for streams of tiny jobs (decisions per tick) |
| **A dirty-sector bitmap for incremental checkpoints** | One bit per 64-byte sector, set on write; a checkpoint copies only dirty sectors | The resident scene server's crash recovery and the daytime world's speculative field: checkpoint cheaply, roll back exactly |
| **Write-ahead log plus snapshot** | The decision journal is the log; everything else is a snapshot | Our core is already an event log; this names the snapshot side. `agent-memory` (scout #1) uses the same shape |
| **A trust ladder (T0–T4) with human-only promotion** | Autonomy is earned level by level; only the human promotes; one bad artifact demotes | **"Builders that grow with you"**: a builder earns the right to act alone at night (the tiles' open question #4) instead of having it by default. A1's permissiveness governs *who may write*, and this governs *what may run unattended* |
| **A perceptual grammar for rollbacks** | Classify each change as interpolatable (fade it in), maskable (hide behind something) or atomic-perceptible (the human will see the jump) before committing | **never-wait's supersede, as the player sees it:** a late answer that is interpolatable can slide in; an atomic one must wait for a natural cut. The missing piece between the ledger's supersede and the viewer |
| **A power-slot auction with a reserve calibrated to measured draw** | Jobs bid for thermal or power headroom; the reserve is the measured marginal cost, not the datasheet | The night's joules rail, priced from the Thor's INA power rails (already readable); a seed for the ecology auction and thor-admit |

**Metaphor and philosophy:** "the archive stops being a tomb", "the constitution of fallibility", "the Ship of Theseus problem, engineering edition", "the agent is the trajectory, not the version". Its closing point is worth keeping: *"the agent doesn't have to be right, it has to be legible"*. That is our ledger's purpose in one line.

**One correction:** the extraction says "our box has no Orin". We do have a Jetson Orin (8 GB, on the LAN, idle; Casey's OK is needed to use it). The chat's "Orin audit" role (checking agents' assumptions against the canon, off the main box) is a plausible job for it.

## Experiments, under a day each

1. **CPU gate vs GPU gate on the Thor** at batch sizes 1/10/100/1000 (part of ct-thor). Pass: a measurable crossover.
2. **The perceptual grammar on real supersedes:** hand-label 100 supersede events and check whether the statepoint predicts the label. Pass: ≥ 80 % agreement.
3. **Dirty-sector checkpoint exactness:** apply 10⁴ commits, checkpoint, apply 10³ more, roll back. Pass: a bit-identical restore, and a checkpoint ≤ 5 % of the state.

## Three checkable questions for the author

1. Has the power auction run against a real Thor power monitor, or is the reserve price still a design parameter?
2. At what batch size does the GPU gate win in its design, and does that match the ~256-instance threshold?
3. With an Orin available but small (8 GB), which of the "seven-part core" roles must it own, and which can the Thor absorb?
