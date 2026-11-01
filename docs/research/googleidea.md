# googleidea 1–2: low-level GPU mechanisms, sorted (2026-10-31)

Casey shared two more chats from a Google agent (`googleidea1/2.md`, ~39k words). They go down to the metal: scale-factor layouts, PTX fences, persistent warps, doorbells. The DeepSeek library extracted them ($0.06). This is the director's sorting.

## Kernel mechanisms worth testing (they feed thor-fp4 round 3 and the ct-thor kernels)

| Mechanism | What it is | Verdict, and where it lands |
|---|---|---|
| **Power-of-two (E8M0) block scales** | If each block's scale is a pure power of two (as in the MX formats), dequantising is an exponent add (a shift), not a multiply | Real: it is what MXFP8/MXFP4 already use. For thor-fp4 the question is whether NVFP4's UE4M3 scales can be restricted to powers of two at an acceptable accuracy cost, to save work in the GEMV and quantise kernels. **Measure accuracy first** (round 1 showed activation quantisation is where accuracy goes) |
| **Writing scales directly in the tensor cores' 128×4 interleaved layout** | Produce scale tiles in the hardware's expected order, so no reorder pass runs | thor-fp4 already handles this layout for cuBLASLt and its own CUTLASS kernels; relevant when fusing activation quantisation into an epilogue (round 2) |
| **An L2 persistence window** (`cudaAccessPropertyPersisting`) | Ask the GPU to keep a hot buffer (gate bounds, a decision model's weights) resident in L2 | The API exists. **Not yet measured on the Thor** (idea3 proposed it; nobody has run it). A quick A/B for the invariant gate and d1's hot weights. (The extraction claimed we had already measured it; we have not.) |
| **`cp.async` / `ldmatrix`: global memory into shared memory, bypassing registers** | Standard Ampere-and-later PTX for streaming tiles | What CUTLASS already does; relevant to the hand-written FP4-weight GEMV (DIRECTIONS §2) |
| **`__launch_bounds__` to hold a warp's registers** | A compiler hint that prevents spills | A tuning detail for the GEMV and the flux-gpu kernels |
| **A persistent warp that dispatches its own work** | A resident kernel pulls tasks from a queue, so the CPU is not in the dispatch loop | The same idea as dsswarm4's persistent kernel on a unified-memory queue. ct-thor's CUDA-Graph launches (~4.7 µs) set the bar it must beat |
| **One-pass spatial fusion** (`mask·actor + (1−mask)·background`) | A Triton kernel compositing an actor over a background in one pass | **The viewer and the first-mile video peek:** compose a changed object over a cached background per frame instead of re-rendering the whole frame |
| **A Kalman-smoothed bounding box** for a moving mask | Damps frame-to-frame jitter in a predicted box (`inertia_gain = 0.3`) | The same family as `core/hysteresis`, for spatial signals: stable highlight boxes in the viewer |

## Not for us, and why

- **Hard-coded MMIO doorbell and base addresses** (`0x50000000`, `0x50004000`), and a "silicon-level context switch". Physical addresses on a production Jetson are not ours to poke: they are unverified for the T5000 and unsafe without a driver. The persistent-queue version of the idea gets the same effect through CUDA.
- **NVLink peer mapping and 500 ns epoch semaphores across nodes:** one Thor, no NVLink peer.

**Metaphor:** "the Tensor Conveyor Belt", "the Fluid State Space Engine", "the self-dispatched hardware automaton", "the architecture is officially complete".

## Experiments, under a day each

1. **L2 persistence** on the invariant gate's bounds and on d1's hot weights. Pass: ≥ 15 % at 10⁶ candidates, no regression at 10⁴.
2. **One-pass fusion vs two-pass** for an actor over a background. Pass: ≥ 1.5× and bit-identical.
3. **Power-of-two NVFP4 scales:** the top-1 and RMS cost against UE4M3 scales on the tile scorer, and the speed gained in the quantise and GEMV kernels.

## Three questions for the author

1. Were `0x50000000` and `0x50004000` confirmed on a T5000, or extrapolated from another part?
2. Does cuBLASLt expose a hook for caller-written scale buffers in the interleaved layout, or does the E8M0 approach require bypassing it (our own CUTLASS kernels)?
3. What does the persistent dispatch warp measure against a CUDA Graph launch (~4.7 µs on our Thor)?
