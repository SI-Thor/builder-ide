# Mission A — a batched decision server for Liquid d1-2B on the Jetson AGX Thor

**The claim:** a decision server for Liquid's d1-2B that beats llama.cpp on
a game tick, by doing the one thing llama.cpp cannot do with this model —
answer many characters' questions in a single forward pass.

- model: `d1-2B` = **LFM3-d1**, 24 blocks, 2048 wide, `Q8_0` GGUF
- hardware: NVIDIA Jetson AGX Thor (Blackwell, 128 GB unified memory)
- workload: 64 characters per tick, each with a **3-question pack** over a
  ~150-token shared state
- the numbers: [`RESULT.json`](RESULT.json) — the pre-registered score

---

## Why llama.cpp is slow here

llama.cpp's LFM3-d1 **decision** graph reads a whole prompt as one flat
token run: there is no KV cache and no memory (`src/models/lfm3.cpp`,
"decision: no memory, the whole prompt is read in one batch"), the
attention mask is two-dimensional over the batch
(`build_attn_inp_no_cache`), and the recurrent layers' short convolutions
run over the flat token run as well.

That flat layout is why the server refuses to batch it:

```cpp
// tools/server/server-context.cpp:537
// lfm3 d1 has no memory, its prompt is read as one flat ubatch and the short
// convs would mix the sequences
// TODO: batch them along the sequence dimension, this needs ubatches of
//       sequences with unequal lengths
if (task->decision.no_batching || other_slot.task->decision.no_batching) {
    return false;
}
```

```cpp
// tools/server/server-decision.cpp:1236
// the short convs of lfm3 d1 have no memory to separate the sequences of a batch
task.decision.no_batching = is_lfm3_d1();
```

The flag is set unconditionally for this model family — there is no
llama.cpp flag that turns it off, and upstream's own TODO describes
exactly what this server does.

So a tick of 64 characters asking 3 questions each becomes **192 separate
prefills**, and the weights are streamed out of memory 192 times instead of
once. The arithmetic is unchanged; only the memory traffic is wasted.

## What this server does instead

`src/d1dec/model.py` runs the same arithmetic as llama.cpp — the same norms,
the same sandwich norms, the same short convolutions, the same NeoX rotary,
the same grouped-query attention and head gate, the same non-causal dense
attention and causal sliding-window attention, the same output head — and
adds the two things the flat decision graph is missing:

1. **a block-diagonal attention mask**, so a dense layer of one sequence
   never sees another sequence, and a sliding-window layer sees only its own
   sequence's last 256 positions;
2. **a per-sequence short convolution**, so the recurrent layers' six-token
   window never crosses from one sequence into the next.

The batch is right-padded to the longest prompt. Padding is safe because
the convolutions look backwards and the attention masks the padded keys out.

Both make a batched forward pass **numerically the same** as running each
prompt on its own. `tests/test_batching_exactness.py` checks exactly that,
against an independent numpy reference written from llama.cpp's graph:
the batch and the one-at-a-time runs agree to 1e-6.

The server itself (`src/d1dec/server.py`) speaks llama.cpp's wire — the same
`POST /v1/systemone` body, the same answer shape — and a single worker
thread drains the request queue into batches, so a tick's burst of 192
questions becomes a handful of forward passes.

## Being the same server, not just the same idea

An agreement of 99% is not free: it means the two servers have to read the
same prompt, take the same logits and turn them into probabilities the same
way. Four things had to be got right, and each of them was worth more than
the whole speedup if it had been wrong:

- **the prompt** — llama.cpp's own `tokenizer.chat_template.systemone` out of
  the GGUF, rendered with Jinja, with its `d1_break` (a zero-width space
  after the first character of every quoted control token, applied
  repeatedly, because the break can create a new match that overlapped the
  one broken before it). `scripts/check_tokenizer.py` checks the result
  against llama.cpp's own `/tokenize`, token for token;
- **the label groups** — llama.cpp's `d1_labels`: the letter codes of a
  choice, the level numbers of a score, `yes`/`Yes`/`YES` and
  `no`/`No`/`NO` of a noul, each group being the token of the label *and*
  the token of the label with a leading space, and the logit of an option
  being the **largest** logit over its group;
- **the decision head** — the softmax over those logits at the model's own
  temperature (`lfm3.decision.temperature.<type>` out of the GGUF), the
  **median** level for a score, and the probability of the `true` option for
  a noul;
- **the weights** — the GGUF reader has to reproduce ggml's axis order.
  ggml stores a tensor with its **first** dimension varying fastest, and the
  GGUF file keeps that order on disk, while numpy's C order has the **last**
  dimension varying fastest. A reader that forgets the transpose does not
  crash, does not look wrong, and answers every question — confidently and
  wrongly. `tests/test_gguf_reader.py` checks the reader against gguf-py,
  the reference reader that ships with llama.cpp: all 154 quantised tensors
  byte-identical, all 133 plain tensors value-identical.

On top of that the arithmetic is kept as close to ggml's as it can be:
the RMS norms are ggml's own (fp32 accumulation, one rounding — PyTorch's
fused `F.rms_norm` is that computation), the short convolution accumulates
in fp32 (ggml's CUDA kernel is `ssm_conv_f32`), and the attention runs in
fp16.

## The engine: the same arithmetic, moved fewer times

Once the batch is right, the throughput is a question of how many times the
engine walks over the activations. The per-kernel profile of the forward
pass says it was a fifth arithmetic and four fifths data movement, and two
loops accounted for most of it.

**The rotary.** The NeoX rotation of a head's two halves is

```
out0 = x0*cos - x1*sin
out1 = x0*sin + x1*cos
```

which is exactly the product of the complex numbers `x0 + i·x1` and
`cos + i·sin`. Written the straightforward way it walks over the head ten
times — two casts to fp32, four multiplies, a subtraction, an addition, a
concatenation and a cast back — and it is called 22 times per forward pass
(once for the queries and once for the keys of each of the eleven
attention layers). Written as one complex multiplication it is one kernel.

**The short convolution.** The recurrent layers' convolution was copying
its whole input into fp32 for cuDNN. cuDNN's fp16 convolution accumulates
in fp32, so the fp16 form is the same computation with one rounding at the
end instead of three, and it does not make the copy.

**Grouped-query attention.** The four key/value heads are shared by the
sixteen query heads; repeating them costs a copy of both tensors in every
attention layer, and PyTorch's attention can read the shared ones directly.

**The chunk.** A tick's 192 sequences are run in chunks of 32. That keeps
the GPU's peak of live activations to half a tick's worth — which is worth
a gigabyte — at the cost of streaming the weights six times instead of
three, about seven per cent of the tick.

Measured on the real tick, all six settings in one session on the same box
state (`scripts/variants.py`):

| rotary | convolution | chunk | tick | GPU peak |
|---|---|---|---|---|
| plain | fp32 | 64 | 10062 ms | 5.96 GB |
| plain | fp32 | 32 | 10734 ms | 5.20 GB |
| complex | fp32 | 32 | 8665 ms | 5.20 GB |
| plain | fp16 | 32 | 10033 ms | 5.16 GB |
| **complex** | **fp16** | **32** | **6134 ms** | **5.16 GB** |

The settings the server ships with are the last row: **1.64x the engine it
started with, and 0.8 GB less GPU memory**. All of them are checked by
`tests/test_batching_exactness.py`, which runs the whole comparison for
each combination.

The answers do not move: the complex rotary and the fp16 convolution
change the logits by about one part in a hundred thousand, and the
server's answers on the workload's 768 questions are **the same 768
answers** as the plain engine's.

## The numbers

Measured on the box, the two servers interleaved — the baseline, then
ours, then the baseline, then ours — so that the shared box's drift hits
both of them the same way. The raw measurements are in `results/`, and
[`RESULT.json`](RESULT.json) has the pre-registered keys.

The box is shared and what else is using the GPU moves the absolute
numbers by a factor of two *within* a run, so the headline is the
**median over all 15 interleaved rounds measured with this engine**, each
round of this server paired with the baseline's round measured just
before it. Every round's number is in `results/rounds/pooled.json`.

| | llama.cpp | ours | |
|---|---|---|---|
| decisions/s, 64 characters a tick | 23.7 | **42.2** | **1.78x** |
| p95, one character (3 questions) | 144 ms | **79 ms** | 1.8x |
| p95, one tick (64 characters) | 8545 ms | **4886 ms** | 1.7x |
| peak memory | 0.74 GB | 8.32 GB | |

The spread is the box's, not the server's: our rounds went from 28.5 to
60.4 decisions/s and the baseline's from 11.3 to 26.2, and the two
track each other only loosely — the rank correlation between a round of
one and the round of the other measured just before it is 0.4. That is
why the headline is the median over all of them and not one round, and
why the two servers are measured in the same round, back to back.

Agreement with llama.cpp's top-1 answer: **99.09%** over the 768
questions of the workload.

The three runs the rounds come from are in `results/rounds/`. The
quietest one — the last, taken when the GPU's free block had grown back
to 12 GB — came out at a median of 51.0 decisions/s against the
baseline's 24.8, 2.05x; the busiest one, taken while the box's load
sat above 20, came out at 34.6 against 22.2. The pooled median is the
number in `RESULT.json` because it uses every round rather than the
luckiest window.

### where the last 0.9% is

All seven disagreements are questions where the **two leading options
are within 0.4% of each other**:

```
char_17 q1  llama.cpp  opt0 0.3043  opt1 0.3032   <- 0.001 apart
             ours      opt0 0.2984  opt1 0.3073
char_34 q1  llama.cpp  true 0.4997   ours  true 0.5022
char_10 q2  llama.cpp  opt1 0.2821   opt2 0.2859
             ours      opt1 0.2821   opt2 0.2821   <- an exact tie
```

The cause is the precision of the **activations**. llama.cpp's matmuls
go through its MMQ path, which quantises the activations to eight bits
(`ggml_cuda_should_use_mmq` returns true for Q8_0 weights on any
Turing-or-later GPU, and `ggml_cuda_should_use_mmf` — the F16 path —
returns false for a quantised weight). This server keeps them in fp16.
On a question whose two leading options are level, the two engines pick
different ones.

It is a real numerical difference, not llama.cpp's own noise: asking the
**baseline the same 768 questions twice** changes nothing
(`results/baseline_self_stability.json` — 0 changes out of 768).

### the peak memory

8.32 GB is the sum of two high-water marks that never happen at the
same moment: the server's host peak resident set (2.51 GB, most of
it the CUDA context and the host-side buffers) and the peak of the GPU
pool torch holds (5.81 GB, of which 3.9 GB is the fp16 weights). It is
under the 10 GB line, and the box is shared: the admission daemon's
learned peak for this server is what keeps another seat's job from
landing on top of it.

The server survives a box that runs out of GPU memory: on an
out-of-memory error it gives the memory back and does the batch in
halves, down to a single question, so a burst survives the GPU being
full instead of losing a third of it.

## The workload

`src/d1dec/workload.py` builds the tick from builder-ide's own data, not from
thin air:

- the **tiles toy** vocabulary and tile families (`core/vocab/words.py`,
  `core/tiles/models.py`) and the shortlist question the judge seat already
  asks over them (`core/judge/shortlist.py`);
- the **critic reference set** (`core/critic/reference-set.json`) — the 60
  base renders (scene, seed, size) and the 30 members with the defect class
  planted in each;
- the **critic's defect classes** (`core/critic/defects.py`).

One *character* per tick sends one *pack*: a shared state plus three typed
questions (`choice`, `score`, `noul` in rotation). The states are **distinct
per character** — a pack shares its state across its own questions, not
across characters — so nothing in the workload can be answered out of a
cache.

The shared state is 149–173 tokens (mean 160), and each pack's prompt is
about 219 tokens.

Everything is a pure function of the seed (20261031):

```
python scripts/make_workload.py
```

## Running it

```bash
# the venv (torch is reused from the build already on this box)
python3 -m venv .venv && .venv/bin/python -m pip install regex jinja2 pyyaml

# the workload
.venv/bin/python scripts/make_workload.py

# the tests
.venv/bin/python tests/test_batching_exactness.py
.venv/bin/python tests/test_gguf_reader.py
.venv/bin/python tests/test_http_backlog.py
.venv/bin/python tests/test_server.py

# the whole measurement, end to end, on the box as it is
bash scripts/final_measurement.sh      # -> results/ and RESULT.json

# the pooled rounds, if a run was interrupted
.venv/bin/python scripts/pool_rounds.py
```

The llama.cpp baseline is started on `:8137` with its own flags:

```
-ngl 99 -fa on -c 32768 --parallel 64 -ub 512 -t 14 -tb 14 --cache-ram 0
```

## Layout

```
src/d1dec/
  gguf.py        a small GGUF reader (F32, F16, BF16, Q8_0), in ggml's axis order
  tokenizer.py   the d1 tokenizer, reproduced from the GGUF
  template.py    the d1 prompt and the label groups, from llama.cpp's rules
  model.py       the batched LFM3-d1 engine
  decision.py    the calibrated probabilities (softmax at the model's temperature)
  server.py      the /v1/systemone server and the batcher
  client.py      the client both servers are measured with
  workload.py    the workload
scripts/
  make_workload.py     build the workload from builder-ide's data
  start_servers.sh     start both servers under the admission daemon
  final_measurement.sh the whole measurement, end to end
  measure.py           the interleaved measurement of the two servers
  bench.py             one server, one mode
  agreement.py         the answers against llama.cpp
  baseline_stability.py  llama.cpp against itself, twice
  check_tokenizer.py   the prompts against llama.cpp's /tokenize
  peak_mem.py          the peak memory of the two servers
  box_state.sh         the state of the box
  microbench.py        the kernels, not the server
  profile_forward.py   where the forward pass's time goes
  profile_kernels.py   the same, per kernel
  variants.py          the engine's settings, measured on the real tick
  pool_rounds.py       every round ever measured, pooled
  make_result.py       RESULT.json out of the measurement files
tests/           the batching-exactness test, the reader test, the server test
results/         the raw measurements
results/rounds/  every interleaved round, and the pooled summary
```

## Licence

The weights are Liquid's **d1-2B** under the **LFM Open License 1.0**
(`general.license.name = lfm1.0` in the GGUF, `general.license.link = LICENSE`).
The BF16 weights were already on the box at
`/home/caseydigennaro/models/d1-2B/d1-2B-BF16.gguf`; the measurements here use
the Q8_0 weights, which both servers read from the same file.

## The box is shared

Other seats run on this machine (infinigen and hunyuan generation, other
d1-2B servers, the agent-world runtime). The measurements are therefore
interleaved — the baseline and ours are run against the same workload on the
same box state — and the box state is recorded before and after in
`results/box_state_before.txt` and `results/box_state_after.txt`. Both model
servers are started through the box's admission daemon (`thor-admit`), so
each load takes a lease and waits for the box to have room.
