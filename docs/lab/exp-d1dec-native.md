> Lab copy of `~/lm-wt/d1dec-native/README.md` on the Thor (the combined follow-up to mission A; see `mission-a-verdict.md`). Measured under heavy co-tenant contention: compare ratios, not absolute rates.

# missionA-zcode / mission B — a batched decision server for Liquid d1-2B on the Jetson AGX Thor

**Result: `d1server` answers the 64-character game tick in six batched
compute passes (192 decisions, chunks of 32 right-padded sequences),
at llama.cpp's own per-question arithmetic.** See `RESULT.json` for the
scored numbers (mission-A keys, median over paired interleaved rounds);
this file explains the mechanism. `NOTES.md` is the working log,
including everything that did not work.

## The workload

A game tick is 64 characters, each sending one *question pack*: one shared
state (~150 tokens of scene/context) plus three typed questions — a `choice`
(the tiles chooser's crates style), a `noul` (a critic defect check), and a
`score` (how well the state supports the night's plan). 192 decisions per
tick, each answered with calibrated probabilities over its options.

The workload is fixed and reproducible: `workload/build_workload.py` composes
it from builder-ide's own materials (the liquid study's sea scenes, the
tiles-toy's styles and phases from `tests/tiles/test_acceptance_learning.py`,
and the defect classes of `core/critic/reference-set.json`), seeded
(`seed:20261101`, per-character RNG streams), and recorded in
`workload/workload.json` with a content hash. The same JSON drives both
servers: a tick is 64 concurrent `/v1/systemone` requests to llama-server
(it has no batch endpoint) and one `/v1/tick` request to ours.

## Why llama-server is slow on exactly this workload

`d1-2B` is `lfm3-d1`: a non-causal, **memory-less** decision model. In
llama.cpp's server this has two consequences, both in `tools/server/`:

1. `can_split()` is false for decision requests over a non-causal context —
   each question's whole prompt is read in **one flat ubatch**, and
2. `can_batch_with()` refuses to batch **lfm3-d1** with anything
   (`server-context.cpp`: *"lfm3 d1 has no memory, its prompt is read as one
   flat ubatch and the short convs would mix the sequences"* — there is even
   a TODO acknowledging the fix).

So a tick is 192 serialized full forwards of the 2B model — each one
re-streams the 1.76 GB of Q8 weights for ~190 prompt tokens.

## The mechanism: same arithmetic, batched

`d1server` links against the box's llama.cpp build (commit `2e0d86b`,
unmodified) and reuses three things verbatim:

* **the prompts**: `server_decision_context` (exported by
  `libllama-server-impl.so`) parses, renders, escapes and tokenizes every
  question exactly as llama-server does, and formats the answers with the
  same softmax/temperature code;
* **the weights**: the same Q8_0 GGUF, loaded by libllama onto the GPU;
* **the kernels**: the graph is built from the same ggml ops
  (`mul_mat`, `rms_norm`, `rope_ext`, `flash_attn_ext`, `ssm_conv`,
  `swiglu_split`, …).

What changes is the schedule. One forward carries **B questions
right-padded to one length L** (the tick's 192 questions, sorted
longest-first, in chunks of 32 — sorting keeps each chunk's padding near
zero):

* **shortconv layers** (13 of the 24): the batched tensor is
  `{L, n_embd, B}`; each sequence gets the reference's zero left-state, and
  a per-position pad mask zeroes the padding *before* the transpose, so a
  causal conv never reads past its own sequence's end. For every real
  token this is op-for-op the flat single-sequence computation.
* **attention layers** (11, of which 5 are sliding-window): one QKV matmul
  covers all sequences' tokens at full width; flash attention then runs **one
  `ggml_flash_attn_ext` per sequence**, on that sequence's own rows with a
  mask that is exactly the mask the reference builds for a lone sequence
  (dense layers: bidirectional over the sequence's keys; SWA layers:
  causal, window 256). No sequence's node ever names another's keys — the
  block-diagonal property the mission-A winner (mcode's `tools/d1dec/`)
  gets from one masked call over the batch. Each FA result's rows are
  copied into the sequence's slot of a flat `{E, LB}` buffer.
* the logits head runs once per forward as one Q8 matmul on the B answer
  rows; the K label rows are gathered **on the device**
  (`transpose → cont → get_rows`, exact copies), and the per-option scores
  are read at the label token positions, as in the reference.
* the 64 packs of a `/v1/tick` are parsed and tokenized in parallel.

### Exactness: what is bit-equal and what is not

With `D1_PADKV=1`, every FA call is shaped exactly like llama.cpp's own
no-cache call for that sequence alone (q rows = its own length, K/V
zero-padded to `GGML_PAD(len, 256)`, the reference's own mask layout —
`llama-graph.cpp` `build_attn_inp_no_cache` + `[TAG_NO_CACHE_PAD]`), and
**a B=1 forward is bit-identical to `llama_decode`** (verified in-process
by `D1_SELFTEST=1 ./src/d1server`, both selftest questions). This is the
strongest exactness anchor: what llama-server computes for one question,
we compute with the same bits.

At B>1 the bits cannot be held: the CUDA mma flash-attention kernel
(ggml 2e0d86b, Thor cc 11.0) rounds differently per launch context — the
first diverging layer is the model's first attention layer, where three
IDENTICAL per-sequence FA launches (a solo run, and two slots of a twin
batch) produce three different results. PDL, CUDA graphs, atomics, mask
values and matmul column-count effects were each ruled out
(`NOTES.md` 11:35-12:20); the stream-K seam merge of the kernel is the
likely site. The deviation is small (~1e-2 in max-logit scores) and
deterministic; it moves top-1 only on genuine coin tosses. The scored
agreement with llama-server and every flip's top-2 margin are in
`results/agreement.json`; `--selftest-batch` enforces exactly that bar
(all finite; every top-1 move a near-tie, both runs' top-2 gap < 0.5).

`D1_ATTN_BATCHED=1` switches to the single-FA-per-layer form (one
`ggml_flash_attn_ext` over the whole right-padded batch with a 4D
block-diagonal mask `{P, L, 1, B}` — ggml's FA accepts it because both
CUDA kernels index the mask `+ nb33*(sequence % ne33)`). It is kept for
A/B and the record: on this box it measured 2-3× slower per token at
this workload's shapes than B per-sequence calls, and its bits differ
from the per-sequence walk by the same mechanism (the seam positions
scale with the launch's total work). `D1_HEAD_MMVQ=1` runs the head in
≤8-column groups (the reference's MMVQ vec-kernel arithmetic) — bit-aligned
head dots, ~2× the forward cost, opt-in for experiments.

## The game-facing API

`/v1/tick` (one request, 64 packs, parsed in parallel, one set of batched
forwards). `/v1/systemone` is also served, llama-server-compatible, with
an optional micro-batching window so 64 concurrent requests still
coalesce into batched forwards.

## Files

| path | what it is |
|---|---|
| `src/d1server.cpp` | the server: model load, batched graph engine, HTTP |
| `src/Makefile` / `src/Makefile.cpu` | GPU build / CPU smoke-test build |
| `src/cpu-ref/` | CPU-mode helpers: `nocuda.so` shim + a copy of `llama-server` that cannot see the CUDA backend |
| `src/start_cpu.sh`, `src/smoke_cpu.sh` | CPU-mode bring-up and comparison |
| `workload/build_workload.py` | the fixed, seeded workload generator |
| `bench/bench.py` | throughput (n=64 tick) and latency (n=1) harness |
| `bench/interleave.py` | the scored protocol: paired interleaved rounds, pooled medians |
| `bench/run_scored.sh` | the full scored sequence under thor-admit |
| `bench/agree.py` | top-1 agreement + probability MAE |
| `bench/make_result.py` | assembles `RESULT.json` from the pooled rounds |
| `results/` | raw artifacts of the runs (`rounds/` holds every round ever scored) |

## Reproducing

```bash
python3 workload/build_workload.py          # regenerates the fixed workload
cd src && make && cd ..                     # GPU build against ~/llama.cpp-upstream
./src/d1server --selftest-batch             # batching-exactness test (near-tie bar)
D1_SELFTEST=1 ./src/d1server                # B=1 vs llama_decode, bit-exact with D1_PADKV=1
bench/run_scored.sh 12                      # baseline + ours, interleaved, under thor-admit
python3 bench/make_result.py                # writes RESULT.json
```

CPU-only correctness check (no GPU needed, slow but exact):

```bash
cd src && make -f Makefile.cpu
D1_SELFTEST=1 LD_PRELOAD=$PWD/cpu-ref/nocuda.so ./d1server-cpu --cpu --max-seqs 8
```

Two CPU-mode notes, both discovery stories worth keeping: the CPU backend's
weight *repack* (`q8_0_4x8`) corrupts `ggml_get_rows` reads on the embedding
tensor (NaN rows from row ~800 on), so the CPU build disables
`use_extra_bufts`; and a 0-device successful `cuInit` still makes the model
loader pick CUDA_Host buffers, so the smoke shim makes CUDA init fail
outright. Neither affects the GPU path.

## Box etiquette

Model loads and all GPU steps run under `thor-admit`
(`~/lm-tools/thor-admit run --tier live --peak … --label d1dec-native.*`;
small jobs use `--priority 1` when the FIFO head is blocked by a big
co-tenant); measurements record the box state beside every number (load,
MemAvailable — see `results/rounds/pooled.json`). The scored numbers are
medians over paired interleaved rounds so the shared box's drift hits the
baseline and ours the same way. No system installs; the server links the
pre-existing llama.cpp build in-place without modifying it.
