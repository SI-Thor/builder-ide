# Open-H3-Regenerate-2K and NVIDIA's Sol-Engine: what we can and cannot take (2026-10-31)

Sources:
- the model card: https://huggingface.co/Efficient-Large-Model/Open-H3-Regenerate-2K (created 2026-10-26, 153 GiB);
- the code: https://github.com/NVlabs/Sana/tree/sol-engine (Apache-2.0).

Casey asked us to study it.

## The licence decides the model question: we cannot use it
The weights are MiniMax-H3 plus LoRAs, under the **MiniMax H3 Community License**.
- Its "Applicable Territory" is worldwide **excluding the EU, the UK, the Republic of Korea and the United States**.
- §IV.4: no use, reproduction or display of the works **or their outputs** outside that territory.

We are in Alaska, so we do not download, run or use outputs of MiniMax-H3 or this bundle. The base model is also 330 GiB, and the Sol-Engine forward needs ~150 GB on one GPU, so it would not fit the Thor anyway. **What we study is the method and NVIDIA's Apache-2.0 runtime code.** Reading the code is fine; building or running it on the Thor needs Casey's explicit OK (CLAUDE.md).

## What it is
A **draft-then-refine** video pipeline:
1. A cheap 768P draft (1344×768, 121 frames).
2. A 3D-conv **latent upscaler**.
3. **Three Euler steps** of a LoRA-tuned refiner, starting from `(1-σ₀)·upscaled + σ₀·noise` with σ₀ = 0.909. This is a partial re-noise, so the draft's structure survives and only the detail is regenerated.
4. A VAE decode to 2560×1440.

## The mechanisms, each with its measured share (one B200, latent upscale + 3-step refine)
| Added module | Total | Speedup |
|---|---:|---:|
| baseline, dense attention, BF16 | 73.11 s | 1.00× |
| + **Sol-Attn sparse attention** (refine step 0 dense, steps 1–2 sparse; `fast`: all sparse at τ 1.75) | 26.11 s | 2.80× |
| + **MXFP8 linear layers** | 22.77 s | 3.21× |
| + **SwiGLU fused into the MXFP8 quantization** | 22.49 s | 3.25× |
| + **one CUDA graph per step**, resident stage weights | 20.46 s | 3.57× |

Separately, a **distilled fast VAE decoder** (non-causal, 24 layers, 1.62 B parameters, from StreamRender-H3) decodes the clip in **1.6 s instead of 15 s**.

**Why each works, as a hardware fact.**
- **Attention.** Its cost is quadratic in tokens, and a 1440p, 121-frame latent is a lot of tokens. Most attention mass is local and sparse, so a sparse kernel skips the blocks that carry little.
  - The first refine step stays dense because it sets the global structure.
  - The later steps only add detail, so sparse is enough. This is the same "pay resolution where it matters" rule as MatAnyone-E (`matanyone-e.md`), applied over denoising time.
- **MXFP8.** Blackwell's tensor cores run block-scaled FP8 at about twice the BF16 rate. Fusing the activation's quantization into the SwiGLU saves one pass over memory.
- **CUDA graphs.** They remove launch overhead. That matters once the kernels are fast, the same finding as our `exp-ct-thor.md` (4.7 µs launches).
- **The distilled decoder.** The released VAE decoder was designed for quality and causality, not speed. Distilling into a non-causal decoder recovers ~9× on a stage that was 40% of the total.

## What we take, and where
1. **thor-fp4: the same ingredients, confirmed on a production pipeline.** Our measured rule (MXFP8 activations × MXFP4/NVFP4 weights; CUDA graphs) matches NVIDIA's recipe, and their table shows each ingredient's share. Round-3 candidates (added to `~/lm-ops/briefs/thor-fp4-round3-candidates.md`):
   - (a) fuse the activation quantization into the preceding elementwise op (SwiGLU, GELU), and measure the saved memory pass on sm_110;
   - (b) a "dense first step, sparse after" schedule for any diffusion model we run (SDXL, FLUX on the cold shelf);
   - (c) resident stage weights plus one CUDA graph per step.
2. **Draft-then-refine with a partial re-noise.** This is the generative version of the Syzygy keyframe:
   - a cheap low-resolution draft carries the structure, and a few expensive steps add detail only at the end;
   - for the night, draft many candidates cheap, let the critic pick, and refine only the winners. That moves the cost to where the human will look (presence: preparation tier).
3. **Distil the slow decoder, not the whole model.** Profile per stage first, then distil only the bottleneck stage (here the VAE decoder, 40% of the time). This is a coldshelf-bakeoff question: which stage dominates TRELLIS's and Hunyuan3D-2's time on the Thor, and is it a decoder?
4. **Exact LoRA merging by concatenating along the rank axis.** Three adapters become one: `B @ A` equals the sum of the scaled deltas, with relative error 2.2e-8. It is cheap, exact, and keeps one kernel. It is useful for stacking our own adapters (FP4-aware fine-tunes, per-builder styles).

## Not applicable
The model itself (licence; size). Sol-Attn's kernels need FlashAttention-4 and quack. Whether these build on sm_110 is an open question for when Casey OKs a build.
