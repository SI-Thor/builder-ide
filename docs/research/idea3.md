# idea3: optimisations, checked against what we measured (2026-10-31)

Casey shared `idea3.md`, a chat about squeezing the Thor. Most of it is written for **serving an LLM on the box**, which B2 rules out. Many of its techniques still apply to what the Thor *does* run: the d1 decision models (single-pass, batched), the generators (TRELLIS, SDXL), the critic and the renderer. The DeepSeek library lane extracted it ($0.02) and marked each item against our measured facts.

| Optimisation | Verdict for our box | Where it lands |
|---|---|---|
| **In-flight batching** (never infer at N=1) | True | **d1 decision models:** batch every character's questions per tick. Round 3 measured batching as nearly free on the FP8 synthetic up to N≈128; d1 under llama.cpp is not yet measured |
| **Pin hot weights in L2** (`cudaLimitPersistingL2CacheSize`) | True (the API exists) | Small decision models and the critic; worth a quick A/B |
| **Static pre-allocation of the memory pool at boot** | True | **Memory admission:** pairs with thor-admit, which turns "whoever allocates first" into planned residency |
| **PagedAttention with LRU eviction for the KV cache** | True | Only if a model with a long context lives on the box; d1 packs are short (§4.1 of liquid-study) |
| **Green Contexts:** hardware-isolated SM partitions | Unverified on sm_110 | **Co-scheduling:** the critic and a decision model on reserved SMs while a render runs. It isolates compute, not memory, so it complements thor-admit |
| **Coherent unified memory:** the GPU reads pageable host memory directly | True: our round-1 zero-copy breakthrough | Already ours |
| **Video and images through NVDEC/NVJPG** before the GPU | NVENC confirmed; NVDEC to confirm | The filmstrip and peek clips; no cameras, so only our own media |
| **Speculative drafting, K = 16–32** | Unverified, and LLM-shaped | Not for us (no LLM on the box) |
| **Offload experts to the DLA** | **False:** the Thor has no NVDLA | — |
| **Stream logits over NVLink-C2C** | **False on one die:** no C2C bridge inside the chip, as the doc itself concedes | — |
| **A thermal governor dropping work under heat** | Unverified | A seed for the night scheduler: the INA power rails and temperatures are readable |

**Metaphor only:** "memory bandwidth prison", "all 8 cylinders", "play the chip like an instrument".

## Experiments, under a day each

1. **d1 batching on our box.** Batch 1/8/16/32, with CUDA Graphs where the runtime allows. Pass: throughput at batch 16 ≥ 3× batch 1, with batch-1 p99 unchanged. This sizes how many characters one d1 can serve per tick.
2. **L2 pinning** for a small decision model or the critic. Pass: ≥ 10 % throughput, reproducible over 3 runs.
3. **Green Contexts on sm_110.** Create two SM partitions and run a kernel in each. If the API refuses, item 11 is dead for us and co-scheduling stays with thor-admit.

## Three checkable questions for the author

1. The doc first assigns experts to an "independent NVDLA co-processor", then concedes "that block doesn't exist". **Does anything downstream still depend on the DLA split?**
2. It uses "NVLink-C2C" throughout, then says there is no C2C bridge inside a single chip. **Over what interconnect does the logit-streaming design run instead?**
3. It derives "~27 tokens/s" for a 20B model at 4 bits from 273 GB/s. We measure ~166–220 GB/s achievable, and Q4 *slower* than BF16 for d1 under llama.cpp. **Does its arithmetic assume a memory-bound regime we are not in?**
