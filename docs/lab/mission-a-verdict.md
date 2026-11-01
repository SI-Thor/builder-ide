# Mission A, thor-decide: the verdict (2026-11-01)

Two teams solved the same mission independently: **a batched decision server for Liquid d1-2B on the Thor that beats llama.cpp.** The workload is 64 characters per tick, each with a 3-question pack over a ~150-token shared state. The score was pre-registered:
- **the bar:** agreement with llama.cpp's top-1 ≥ 0.99, peak memory ≤ 10 GB;
- **the ranking:** decisions per second at 64 characters, then p95 for one character.

## The result
| | **mcode** (Python/torch engine) | zcode (native `d1server`) |
|---|---:|---:|
| Agreement with llama.cpp (bar 0.99) | 0.9909 (7/768 differ, all near-ties) | **1.0** (bit-exact at batch 1) |
| Peak memory (bar 10 GB) | 8.32 GB | **0.71 GB** |
| **Decisions/s, 64 characters** | **42.2** (llama.cpp 23.7 in the same rounds: 1.78×) | 32.5 (llama.cpp 28.7: 1.13×) |
| p95, one character | **79 ms** (llama.cpp 144) | 197 ms (llama.cpp 132) |
| p95, one whole tick | **4.9 s** | 10.4 s |

The baselines differ between the teams (23.7 vs 28.7 decisions/s) because the box's load moved. Each team measured llama.cpp interleaved with its own server under the same load, so the ratios are the fair comparison: 1.78× vs 1.13×. **mcode wins on the ranking.** Its server is merged as `tools/d1dec/`.

## Why batching d1 is possible, and why llama.cpp does not do it
llama.cpp refuses to put two d1 decision requests in one batch (`no_batching`, set for this model family): its decision graph reads the prompt as one flat token run, and the recurrent layers' short convolutions would mix sequences. So a tick of 64 × 3 questions is 192 separate prefills, each streaming the 1.76 GB of Q8 weights.

The winner adds two things:
- a **block-diagonal attention mask**, so no sequence sees another;
- a **per-sequence short convolution**, so the recurrent window never crosses a sequence boundary.

With those, one tick becomes a few forward passes, and the weights are streamed once per batch. A test checks batched outputs against an independent reference.

## What the other entry contributes
The zcode entry is a native engine that is **bit-exact with llama.cpp** at batch 1, in a **tenth of the memory**. Its weakness is single-character latency (197 ms vs 132). The natural next step combines the two: mcode's batching (the mask and per-sequence convolution) inside a native engine with zcode's exactness and footprint. That would remove the 7 near-tie disagreements, which come from fp16 vs llama.cpp's 8-bit activations, and cut 8.3 GB to about 1 GB.

## Caveat
zcode's run ended on a retryable API error after its scored round was committed ("scored round complete", 09:28). The numbers above are that committed round.
