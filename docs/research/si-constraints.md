# The crew's constraint work, mapped onto builder-ide (2026-10-31)

Casey pointed us at 20 SuperInstance repos and `beam-quilt`: "optimizations based on constraints has been a long-time study of our group". The DeepSeek library lane read their READMEs, file trees and beam-quilt's core documents ($0.03). This note is the director's mapping onto our products.

## What is there

**Real, tested code:**

| Repo | What it is | Tests and status |
|---|---|---|
| `constraint-theory-core` | Rust: Pythagorean-lattice and KD-tree snapping, holonomy, cohomology, Laman rigidity, a quantizer | 262 tests, on crates.io |
| `eisenstein` | Rust, `no_std`: E12 Eisenstein integers, `HexDisk`, `HexRoomMap`, D₆ rotations | |
| `cuda-constraint-engine` | CUDA/C: multi-precision constraint checking, CUDA graphs | benchmarked on an RTX 4050, the ProArt's GPU |
| `holonomy-consensus` | Rust | |
| `flux-lucid` | Rust: precision classes by stakes, XOR dual-path checking | |
| `si-core-c` | C: budget conservation, a spectral ranker | |
| `lau-optimization` | Rust: GD, BFGS, L-BFGS, Nelder–Mead, NSGA-II, PSO | 87 tests |
| `superinstance-live` | a DAW/MIDI/OSC controller | |

**Prototypes:** `si-gradient-flow`, `si-variational-agent`, `jc1-ct-bridge`, `futhark-lab`, `warp-flux-poc`.

**Prose:** the papers, the syntheses, `roadmaps`, `tripartite-room`, and `beam-quilt`. **beam-quilt's fact-check lane is the corpus's honest anchor:** it refutes several claims other repos still repeat, such as Laman rigidity as a test of truth ("a rigid graph can be rigidly wrong").

## Where constraint ideas meet our products

| Idea (crew repo) | The mechanism | Where it lands for us |
|---|---|---|
| **Exact lattice snapping** (`constraint-theory-core`, `eisenstein`) | Snap continuous coordinates to Pythagorean or Eisenstein integer lattices, so positions are *exact* integers rather than floats | **Determinism:** we already demand byte-identical recipe graphs and world files. Placements snapped to an exact lattice make rebuilds and deltas identical across the Thor (aarch64) and the ProArt (x86) **by construction**, not by careful float ordering. world-stream already proved cross-machine byte-identity; this would make it structural for placements |
| **A hex room map with D₆ symmetry** (`eisenstein`) | Six equal neighbours, true hex distance, hex BFS | A tile-adjacency and navigation grid for the builders' moves; the daytime world's room layout |
| **The deadband ring** (`eisenstein`) | A region rings only when its aggregate crosses a threshold | The same family as `core/hysteresis`: region-level triggers for the daytime world ("the east span needs attention") |
| **Precision classes by stakes** (`flux-lucid`) | Each constraint gets a precision tier by what an error would cost (dual, int32, int16, int8) | **Per-layer precision** (idea2, lab-fp4): FP4 where errors are cheap, BF16 where they are checked; the critic and provenance stay high |
| **XOR dual-path verification** (`flux-lucid`) | Two independent execution paths must agree, which catches silent hardware or kernel errors | **thor-fp4's validation:** run the NVFP4 GEMM and a reference path and require agreement within a stated bound, a check against silent errors in a new kernel |
| **Constraint projection** (`si-gradient-flow`, `si-core-c`) | After each step, project back onto the conserved set (Σxᵢ = C) | **The night's rails:** when a job overruns, redistribute the remaining budget so the totals hold exactly, instead of cutting ad hoc |
| **Laman rigidity as an under-specification check** (`constraint-theory-core`; beam-quilt's correction) | Count constraints against degrees of freedom: is a structure determined, under-determined or over-determined? It is not a test of truth | **Infinigen's indoor solver:** a room's constraint graph can be checked *before* annealing. Under-determined rooms are where lab5 saw tie ambiguity (~17 %) and distribution sensitivity. It also checks the WHY kernel's justification graphs for "is this conclusion actually pinned down?" |
| **Classical optimisers with tests** (`lau-optimization`: L-BFGS, NSGA-II, PSO) | Gradient and population optimisers | Candidates for parts of the indoor solver's continuous moves, and NSGA-II for multi-objective tile and plan selection (quality vs cost vs time) |

## Claimed but unproven (to be checked before we lean on any of it)

- Holonomy consensus: "Byzantine tolerance: any number" and "38 ms @ 26,316 tx/s". The benchmark is not reproduced in the corpus.
- `jc1-ct-bridge`: H1 cohomology "detects patterns 2.7 s before any individual turns" at 100 % vs 62 % for ML. One 470-line bridge, no replication.
- Numerical coincidences presented as laws (a Ricci-flow constant matching a threshold to 0.5 %); "880:1 seed-to-tile compression" and "97.3 % cost reduction" without methods or baselines.

## Experiments, under a day each

1. **Lattice snapping determinism:** snap 10⁶ vectors on the Thor and the ProArt. Pass: 100 % bit-identical, ≤ 200 ns per op on the Thor.
2. **XOR dual-path on NVFP4:** compare the native NVFP4 path with the BF16 reference. Pass: every deviation over the bound is flagged, with no false alarms. This goes into thor-fp4.
3. **Constraint projection for the night:** inject a mid-night overrun. Pass: budget error < 0.1 % after projection and no job silently lost.
4. **A Laman-style determinacy check on Infinigen rooms:** count constraints against degrees of freedom per room, and test whether under-determined rooms are the ones whose solves vary most across seeds (lab5's data).

## Three questions for the crew

1. Holonomy consensus claims Byzantine tolerance for "any number" of faulty nodes. **What was the test setup, and does it survive one node that lies consistently rather than randomly?**
2. `jc1-ct-bridge`'s 100 % vs 62 %: **the same data for both, and what is the false-positive rate?**
3. beam-quilt's fact-check refutes claims (Laman-as-truth, sub-millisecond MIDI, the 6.8M/7 ms ARM figure). **Have the corrections propagated to the papers and syntheses that still state them?**
