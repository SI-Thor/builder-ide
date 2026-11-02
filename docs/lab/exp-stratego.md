# Stratego on the Thor: the port, the measurements, and what a batched simulator would take from it

**Desk brief:** Casey, 2026-11-01 — *"think how this could be general purpose on our gpus
for our work https://github.com/AtaraxosAI/stratego"*, and the hands-on build approved for
the Thor.

Three deliverables, in the brief's order:

1. **The study** — [`docs/research/stratego.md`](../research/stratego.md): how the
   environment is batched on the GPU, how the belief model is trained, how the search uses
   sampled beliefs, how the arrangement model works. Every claim cites the upstream file
   and line.
2. **The build on the Thor** — the port from CUDA 11.8 / x86_64 / PyTorch 2.5.1 to
   **CUDA 13.2 / sm_110 / aarch64 / PyTorch 2.15.0+cu132**, and three measurements:
   (a) one RL iteration at `--num_envs 128` against upstream's "10-20 s on an RTX A6000",
   (b) the pretrained model against a random baseline over N games, (c) env steps/s at
   batch 128 / 1024 / 4096.
3. **The design** — [`docs/design/batched-sim.md`](../design/batched-sim.md): one
   batched-simulator interface for our own rule systems, where the belief model helps,
   sampled-belief search as the vibecode pre-flight, the arrangement model as a learned
   room seeder, and the three first builds ranked.

This doc is the build's log: the numbers, the box they were measured on, and what is
not verified.

---

## 0. The box, and what it means for the numbers

| | |
|---|---|
| machine | NVIDIA Jetson AGX Thor, aarch64, **122.8 GB unified memory**, Blackwell GPU, **compute capability 11.0 (sm_110)**, CUDA 13.2, driver 595.78 |
| CPU | 14 Neoverse cores |
| GPU memory | **is** the system memory. On this box that is the single most important fact for every number below. |
| PyTorch | 2.15.0+cu132 (already in the box's uv cache; nothing was re-downloaded) |
| upstream | AtaraxosAI/stratego at commit `92db29e`, MIT, cloned into `third_party/stratego/` (gitignored) |

The box was **shared and busy** for the whole session. Load average was 10-24 on 14
cores, and other seats' long-lived services (ComfyUI, a llama-server, the agent world,
a drift refit using 6 cores) held about 41 GB of the GPU-visible memory. Every number
below is recorded with the box state beside it, and the numbers that are timing numbers
say so.

One operational fact that cost an hour and is worth stating plainly, because it changes
how any GPU work is scheduled on this box:

> **On the Thor, a CUDA allocation that does not fit the GPU pool's largest free block
> blocks in the kernel rather than failing.** A first attempt at measurement (a) built
> both transformer models and then sat for 15 minutes producing no output. Its context
> switch counters and its CPU time did not move at all across an 8-second sample, and
> its main thread was in `os_acquire_rwlock_write` with fds open on `/dev/nvidia0` and
> `/dev/nvmap`. `nvidia-smi` blocked the same way — four times, two of them being
> **thor-admit's own daemon samplers**, which is why the daemon's GPU view froze for
> half an hour. `timeout 20 nvidia-smi` did not return in 50 s: the process was in
> uninterruptible sleep and the signal could not be delivered.

The daemon log has the history: the GPU pool's largest free block was 10.7 GB at
04:42Z, fell to 134 MB at 05:28Z and 25 MB at 05:34Z, recovered to 3.8 GB by 06:00Z,
and stood at 1.07 GB when the wedge happened. **Size a GPU workload against the pool's
largest free block, not against the free system memory.** They are the same bytes.

---

## 1. The study

[`docs/research/stratego.md`](../research/stratego.md) is the study; this is the short
version, because the design in §4 is built on it.

**The environment** (`src/env/**`) is a batched CUDA simulator. A game's whole state is
a fixed-size POD struct — `Piece` is exactly 16 bytes (`static_assert`,
`src/env/stratego_board.h:80`), `DeathStatus` exactly 2 — so a batch of 4096 games is
one contiguous allocation and a kernel reaches game *i* by pointer arithmetic
(`d_boards_` holds `buf_size * num_envs` boards, row stride `num_envs`,
`src/env/stratego.cu:735-737`). The step is **one thread per game**
(`ApplyActionsKernel`, `src/env/cuda/action_kernels.cu:107`): one thread does the whole
move for its game — decode, combat resolution, death status, flag capture. The legal-move
mask is a separate, far more parallel kernel: **100 threads per game**
(`LegalActionsMaskKernel`, `src/env/cuda/action_kernels.cu:5`), each thread resolving one
square's reachable lines and writing 18 booleans into a fixed `(num_envs, 1800)` mask.

**The belief model** (`pyengine/belief/**`) predicts which piece type each hidden
opponent piece is. It is trained with a plain cross-entropy on the true types
(`pyengine/belief/belief.py:231`), over the pieces that are still unknown, on the
arrangement distribution the arrangement model produces — not on uniform setups. Its
diagnostic is a KL to two uniform references (`mu_kl`, `u_kl`, `belief.py:236-249`).

**The search** (`pyengine/core/search.py`) samples `n_sample` *complete* hidden worlds
(`_generate_env_state`, `search.py:281`), rolls each out in an auxiliary env, and averages
the leaf values per root action (`estimate_q_values`, `search.py:180`). **The belief
samples are the search's branching factor** — the search plans over worlds drawn from a
learned posterior, which is the whole reason the belief model earns its keep.

**The arrangement model** (`pyengine/networks/arrangement_transformer.py`) generates the
setup autoregressively over the 40 arrangement cells, with a forced handedness
(`force_handedness=True`, so the flag may only go on the right half) that halves the
sample cost. It is trained on the **rewards of the games its setups produced**
(`arr_train`, `pyengine/core/rl.py:616`) — it learns an equilibrium over setups, not a
supervised mapping.

---

## 2. The port

Eight changes, all in [`docs/lab/stratego-port/apply_port.py`](../lab/stratego-port/apply_port.py),
applied as exact string replacements that refuse to continue on a missing anchor. The
port recipe, the commands, and the per-change reasons are in the
[port README](../lab/stratego-port/README.md).
| # | change | why the old way failed |
|---|---|---|
| 1 | read `_GLIBCXX_USE_CXX11_ABI` from the installed PyTorch | upstream hardcodes `0`, which matches PyTorch 2.5.1's old-ABI wheels; PyTorch 2.15 is CXX11-ABI, so every `std::string` argument would mismatch libtorch |
| 2 | find the CUDA 13.2 toolkit explicitly; target `sm_110` | `nvcc` is not on PATH here, and CUDA 13 dropped the `sm_52`/`sm_70` targets nvcc used to default to |
| 3 | `CUDNN_ROOT` at the cuDNN inside the PyTorch wheel | there is no system cuDNN on the Thor |
| 4 | `get_pybind_flags.py` tolerates PyTorch >= 2.6 | it read `_PYBIND11_*` attributes that no longer exist; the crash left `PYBIND_FLAGS` empty, which then aborted the configure |
| 5 | quote the `message()` arguments | an empty value must not abort cmake ("message called with incorrect number of arguments") |
| 6 | C++20 for both g++ and nvcc | PyTorch >= 2.6 refuses anything older (`#error C++20 or later compatible compiler is required`) |
| 7 | restore `--expt-relaxed-constexpr` for nvcc | upstream wipes Torch's CUDA flags, and PyTorch 2.15's bundled CUB calls `constexpr __host__` functions from device code |
| 8 | `pyengine/utils/helper.py`: the GPU-memory counter degrades gracefully | **NVML does not exist on the Thor.** The trainer logs a GPU-memory counter every iteration (`RL.log_stats`, `pyengine/core/rl.py:386`), and `nvmlDeviceGetMemoryInfo` raises `NVMLError_NotSupported` — uncaught, so the *first* `log_stats()` after the first iteration killed the training run. The fallback is this process's own reserved GPU memory, which is the better number here anyway |

**Result:** `pystratego.cpython-312-aarch64-linux-gnu.so`, 10.9 MB, 0 errors, sm_110
code. Build time ~10 min from a clean `build/` on the 14 Neoverse cores.

The build deliberately has **no `CMAKE_BUILD_TYPE`**, the way upstream's own `make` does:
no `-DNDEBUG`, so the device-side asserts and the per-step legality check stay in, and
the timing is comparable with upstream's 10-20 s figure.

---

## 3. The measurements

### 3.0 The correctness gate

The port's gate is upstream's own ctest suite: **45 cases** over the rules engine.

| | |
|---|---|
| **40 passed** | of 45 (89%) in the full-suite run. Total suite time 5708 s (95 min). The slow ones are the real ones: `test_snapshot_env_history` 1282 s, `test_move_summary` 1086 s, `test_uniform_belief` 569 s, `test_reset_behavior` 553 s |
| **3 aborted** | `test_env_state`, `test_magnet_policy`, `test_twosquare_rule` |
| **2 failed on a missing module** | `test_replay_games`, `test_save_games` — `ModuleNotFoundError: No module named 'msgpack'` |

**The two module failures are the environment's, not the port's, and both pass
once it is fixed.** `msgpack` is in upstream's `environment.yml`
(`msgpack-python=1.1.0`) but was not in the venv. After
`uv pip install --no-deps msgpack`:

- `test_replay_games`: **Ran 1 test in 237.436 s — OK**
- `test_save_games`: **Ran 3 tests in 24.788 s — OK** (it only core-dumped when
  five tests were run at once on a contended GPU; run alone it passes)

**The three aborts are upstream's, not the port's**, and they are one bug
appearing three times. All three construct the env with `custom_inits=`, but the
upstream API's parameter is `initial_arrangements` (`src/pybind.cc:42`), and the
C++ side answers an unknown key with
`MUSTRATEGO_FATAL("Unrecognized configuration key %s")` (`src/pybind.cc:52`) —
which aborts the process. `custom_inits` appears nowhere in `pyengine/`; it is a
stale name in three upstream test files and one upstream script
(`tests/test_env_state.py:314`, `tests/test_magnet_policy.py:34`,
`tests/test_twosquare_rule.py:340`, `scripts/train/remember_main.py:89`).

Confirmed by running each one alone under `PYTHONFAULTHANDLER=1`: all three die
at the **same line**, `pyengine/core/env.py:99`, inside `Stratego.__init__` ->
`pystratego.StrategoRolloutBuffer(...)` -> `ParseStrategoConf(kwargs)`
(`src/pybind.cc:188`). This is a mismatch between the upstream tree and the
upstream tree's own API, in Python-land, and none of the port's eight changes
touch it. It would fail identically on upstream's own x86_64 / CUDA 11.8 build.

**So the gate reads: 42 of 45 passing, 3 failing, and all three failures are the
same upstream defect.** The port itself has no failing case.

Separately, the smoke test's own "40 pieces per side" assertion was **flaky and wrong**:
it counted after five random steps, and a captured piece leaves the board. The count is
now checked at reset, where it is deterministic — and at reset the Thor's board is
exactly the classic composition on both sides:

```
red   {B:6, C:1, D:8, E:5, F:4, G:4, H:4, I:3, J:2, K:1, L:1, M:1}   = 40
blue  {N:6, O:1, P:8, Q:5, R:4, S:4, T:4, U:3, V:2, W:1, X:1, Y:1}   = 40
```

which is `COUNTERS["classic"]` (`pyengine/utils/init_helpers.py:66`) exactly, with
`PIECE_ENCODING` (`src/env/stratego_board.h:37`) as the letter map. **The port places
pieces correctly.**

### 3.1 (a) One RL iteration at `--num_envs 128`

<!--RL-->
The upstream reference point, from upstream's own README:

```
python scripts/train/rl_main.py --num_envs 128 --rl.dtype float32 --rl.torch_compile false
```

"Iterations usually take 10-20 seconds on an RTX A6000."

Exactly that command was run on the Thor, with `--rl.max_num_train 3`. The
per-iteration times are the trainer's own counter (`[N] Time spent = X s`,
`pyengine/utils/multi_counter.py:115`), and the breakdown is the trainer's own
stopwatch:

| iteration | **total** | rollout | train | update_arrangements | prep_data | arr_train |
|---|---|---|---|---|---|---|
| 1 | **58.21 s** | 26.85 s | 18.59 s | 5.89 s | 0.45 s | 0.20 s |
| 2 | **34.90 s** | 26.97 s | 4.85 s | 2.78 s | 0.06 s | 0.23 s |

**The Thor is about 2-3.5x slower than the A6000 figure**, and the two
iterations differ by 1.7x because the first one pays for everything the
process has not touched yet (cuDNN benchmark autotuning, the first-touch
allocations, and the first policy update, which is 18.59 s against 4.85 s
afterwards). Iteration 2 is the steady state and the number to compare:
**34.90 s against upstream's 10-20 s**.

**This was measured on a loaded shared box, and the box state is part of the
number.** Before the run: load average **29.54 / 24.66 / 20.20** on 14
cores, with two other processes at 505% and 412% CPU (other seats' work), GPU
utilisation 26%. After: load average 20.72 / 23.52 / 20.41, GPU utilisation 5%.
The box was never quiet during the session. The honest statement is: *34.90 s
per iteration on a Thor that is sharing its CPU with other seats' jobs*, not
"the Thor is 3x slower than an A6000". Separating the two would need an idle
box, which this is not.

Where the time goes, from the trainer's own counters:

- **The rollout is 27 s and it is the policy, not the environment.** Iteration
  2's rollout made 51,456 env steps (402 steps x 128 games) in 26.97 s. The
  environment alone does 35,862 env-steps/s at batch 128 (§3.3, 27.9 µs per
  env-step), so the environment's share of those 27 s is **about 1.4 s**. The
  other 25 s is the transformer forward over the infostate tensor plus the
  per-step `.item()` calls, which force a GPU sync every step. The rollout is
  latency-bound, not throughput-bound.
- **The first `train` step is 4x the later ones** (18.59 s vs 4.85 s) —
  allocator and cuDNN warm-up.
- **`update_arrangements` is 2.78 s** for 1024 arrangements: 40 autoregressive
  steps of the arrangement transformer, which is the arrangement model's
  sampling loop, not the environment.

**Two port changes were needed before this would run at all**, and both are
recorded in `apply_port.py`:

- The trainer logs a GPU-memory counter every iteration
  (`RL.log_stats`, `pyengine/core/rl.py:386` -> `utils.get_gpumem_usage_gb()`).
  That helper asks NVML for the device's used memory, and **NVML is not
  supported on the Jetson Thor** — `nvidia-smi` reports "Not Supported" for
  memory and `nvmlDeviceGetMemoryInfo` raises `NVMLError_NotSupported`. The
  exception is not caught, so the **first `log_stats()` after the first
  iteration killed the run**: the training itself was fine, the counter was
  not. The fallback is this process's own reserved GPU memory, which is the
  better number on this box anyway, since the GPU memory *is* the system
  memory and NVML's device-wide "used" would count other seats' work as ours.
- The seventh build change (§2) was needed for the same run for a different
  reason: without `--expt-relaxed-constexpr`, PyTorch 2.15's bundled CUB fails
  to compile.

The run is reproducible with
[`docs/lab/stratego-scripts/run_rl_iteration.sh`](../lab/stratego-scripts/run_rl_iteration.sh),
which records the box state before and after into the results directory.
<!--RLSTATUS-->

### 3.2 (b) The pretrained model against a random policy

The baseline is the environment's own uniform sampler over legal actions
(`sample_random_legal_action`) — it plays legal moves and nothing else. The evaluation
helper plays the agent as player 0 and as player 1 over the same setups, so one
`evaluate()` call covers both seats (`pyengine/core/evaluation.py:100` returns
`2 * num_envs`).

<!--EVAL-->
The numbers, from the run's own output (the raw log is
[`stratego-scripts/results/eval.log`](../lab/stratego-scripts/results/eval.log)):

| matchup | games | W | L | T | win rate | mean reward | wall clock |
|---|---|---|---|---|---|---|---|
| pretrained **EMA** vs random | 256 | **256** | 0 | 0 | **1.000** | +1.0000 | 239.7 s |
| pretrained **raw** vs random | 256 | **256** | 0 | 0 | **1.000** | +1.0000 | 216.4 s |

**The pretrained model won every game.** 256 games per matchup, 128 per seat,
over the upstream checkpoint's own 1000 arrangements, against the environment's
own uniform sampler over legal actions. Not one loss and not one draw in 512
games.

Two caveats, stated rather than buried:

- The **control was not completed**. The third matchup — the pretrained EMA
  weights against *themselves* — was still running when the two matchups above
  had finished, and it was holding the GPU lease that measurement (a) was
  queued behind. It was stopped to release the lease. A strong agent against
  itself should score about 0, and that check is **not** claimed here.
- 256 games is enough to establish a 1.000 win rate against a random policy
  (the alternative is absurd), but it is not a tight estimate of the model's
  strength against a *strong* opponent. The win rate against random is a
  liveness check on the port — it says the pretrained weights load, act, and
  win — not a strength measurement.

What this does and does not show: the checkpoint's weights work on the Thor,
and the whole path works — model loading, the arrangement distribution, the
infostate observation, the legal-move mask, the policy forward, the rules
engine, the terminal detection and the reward. It does not exercise the
**belief model** or the **search**; both are part of the pretrained stack but
neither is used by a single-agent policy evaluation.

### 3.3 (c) Env steps/s at batch 128 / 1024 / 4096

Two variants are timed: `step` is the environment alone
(`sample_random_legal_action` + `apply_actions`), and `obs` adds
`compute_infostate_tensor` — the policy's actual input, 355+ planes per game written by
nine separate kernel launches.

<!--BENCH-->
| batch | variant | env-steps/s | µs per env-step | box state |
|---|---|---|---|---|
| 128 | `step` (env only) | **35,862** | 27.885 | load 10.22 / 12.66 / 15.86, 70.5 GB free |
| 128 | `obs` (+ infostate) | **33,301** | 30.029 | as above |
| 1024 | `step` (env only) | **281,482** | 3.553 | load 10.92 / 12.20 / 15.38, 78.2 GB free |
| 1024 | `obs` (+ infostate) | **145,614** | 6.867 | as above |
| 4096 | — | **not measured** | — | needs 6.26 GB of GPU; the box's pool would not give it |

`step` is `sample_random_legal_action` + `apply_actions`. `obs` adds
`compute_infostate_tensor`, which is what the policy actually consumes: 355+
planes per game, written by nine separate kernel launches. 7 repetitions of
2000 steps each, median reported; the raw numbers are in
[`stratego-scripts/results/bench_env.json`](../lab/stratego-scripts/results/bench_env.json).

**The interesting part is the jump, and it is the batch-size effect the study
predicts.** Going from 128 games to 1024 games is a 7.8x improvement *per
game* (27.885 µs → 3.553 µs). The environment's step is one thread per game,
so the parallelism available is exactly the batch size; at 128 games the Thor's
GPU is not filled and the step is dominated by kernel-launch latency, not by
work. The fixed cost per `apply_actions` is amortised over the batch. This is
the same mechanism that makes the design in §4 worth doing — and it is the
number to quote for "how big does a batch have to be before the GPU is worth
it".

**4096 is a capacity result, not a throughput result.** The environment's own
allocation table at 4096 games x 256 rows: `d_boards_` 2013 MB,
`d_zero_boards_` 2013 MB, `d_illegal_chase_actions_` 881 MB, plus the
observation tensors — **CUDA TOTAL 6256 MB**. The constructor returned and the
process then wedged in uninterruptible sleep holding the allocation (§0). On
this box, with other seats holding 41 GB of the GPU-visible memory, 4096 games
does not fit. The measurement was not taken and is not claimed; what *is* claimed
is the 6.26 GB figure, which comes from the environment's own allocation table
and is reproducible.

---

## 4. The design

[`docs/design/batched-sim.md`](../design/batched-sim.md) is the design. The short
version, because it is the part that answers Casey's question:

**One interface** (`core/sim/`): a `template <class State> struct Batch` holding one
contiguous array of fixed-size states, five kernels per rule system (`Reset`, `Step`,
`Mask`, `Obs`, `Terminate`), and one pybind11 module (`pysim`) whose tensors drop
straight into the code we already have. The rules that are not negotiable, taken from
the port: fixed-size state with no per-world allocation; the legal-move mask written by
the **rules engine** and never re-derived by the network; point of view is the caller's
problem, exactly as in Stratego, so the plane list does not depend on who is acting; and
the Python side clones every tensor it returns, because the backend reuses the buffers.

**Where the belief model helps.** The general condition is (i) hidden state, (ii) a
decision to make, and (iii) a simulator to roll out in. The sharpest case is the drift
detector's **stuck vs waiting**: the six signals fire on rates, and a rate fall has two
very different causes — the agent is stuck and needs intervention, or the agent is
waiting correctly and needs silence. Today the detector cannot tell them apart. The
action is to *wait*, and waiting has an opportunity cost, so the rule is
`intervene when P(stuck | stream) > λ · P(waiting | stream)`: a classifier returns one
label and throws the uncertainty away, a posterior returns both and makes λ a policy
knob. The screen watcher is the same latent variable with a different sensor.

**Sampled-belief search as the vibecode pre-flight.** The pre-flight's three existing
checks all ask "is this proposal well-formed?". The question that is missing is "**if
this edit lands, what happens?**", and it is full of hidden state — the other agents'
intents, the world's state at the moment of landing, the resources available at that
moment. The search answers it the way Stratego's does: sample N plausible worlds of
the world-at-landing, roll each out, score the candidate edits over them, and report
the **tail**, not just the mean.

**The arrangement model as a learned room seeder.** Trained against the critic's
verdicts, with the human's verdicts held out. The anti-GAN part is stated properly: a
generator trained against a critic will find the critic's blind spot, and the only
external judge is a human with a small number of labels, so the held-out human verdict
and a pair-precision metric go in with it from the start.

**Ranked first builds:** (1) the drift simulator — it has real hidden state, an
existing Python reference to check bit-for-bit, and a caller that wants it today;
(2) the pre-flight simulator — the consumer that makes 1 and 3 general, but it needs
the seeder to have a distribution of worlds to roll out in; (3) the room seeder — it
makes the other two general, and its failure mode is silent, so it goes last.

**The honest cost.** The search multiplies the simulator's cost by N, on a box whose
GPU *is* its memory and whose CPU is also doing the world's work. N is a lease-sized
decision, not a constant. And §3.0 above is the warning: on this box, a workload that
does not fit the GPU pool **blocks in the kernel**. A batched simulator built here has
to be sized against the tier's peak, and it has to be sized against the *largest free
block*, not against the free memory.

---

## 5. What is not verified

- **The 4096-batch number is missing**, and the reason is capacity, not a bug: that
  configuration needs 6.26 GB of GPU memory (the env's own allocation table: `d_boards_`
  2013 MB, `d_zero_boards_` 2013 MB, `d_illegal_chase_actions_` 881 MB, plus the
  observation tensors) and the box's GPU pool had a 1.07 GB largest free block when the
  run was attempted. The constructor returned and the process then wedged in
  uninterruptible sleep holding the allocation.
- **The RL iteration number is measured under contention**, on a box whose load
  average was 15-24 on 14 cores with other seats' work running. It is a number for
  *this* box in *this* state, not a clean A6000 comparison.
- **The belief model was not measured.** The study describes how upstream trains it and
  what its diagnostic is (the KL to a uniform reference); the KL was not reproduced
  here, and the search was not run. Measurement (b) is the *policy*, which does not use
  the belief model.
- **Nothing about our own rule systems was built.** §4 is a design. The drift
  simulator, the pre-flight simulator and the room seeder are proposals.
- **The port was not tested on x86_64**, so "the eight changes are all that was
  needed" is a claim about *these* changes on *this* box, not a proof that upstream
  would build unchanged elsewhere.

## 6. What is committed

| | |
|---|---|
| study | [`docs/research/stratego.md`](../research/stratego.md) |
| port recipe | [`docs/lab/stratego-port/`](../lab/stratego-port/) — `apply_port.py`, `build_thor.sh`, `run_ctest.sh`, `time_one_test.sh`, `ctest.log`, `README.md` |
| measurement scripts | [`docs/lab/stratego-scripts/`](../lab/stratego-scripts/) — `smoke_test.py`, `bench_env.py`, `eval_pretrained.py`, `run_rl_iteration.sh`, `piece_audit.py`, `README.md` |
| results | [`docs/lab/stratego-scripts/results/`](../lab/stratego-scripts/results/) |
| design | [`docs/design/batched-sim.md`](../design/batched-sim.md) |
| this note | `docs/lab/exp-stratego.md` |

Reproduce any number with the script beside it and the README in its directory:
what it needs, how to run it, how long it takes.
