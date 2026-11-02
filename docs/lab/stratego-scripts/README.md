# `stratego-scripts` — the measurements the brief asks for

Four scripts, each producing one number in `docs/lab/exp-stratego.md`. They
run against the ported extension in `third_party/stratego/` with that
checkout's own `.venv` (torch 2.15.0+cu132) on PATH.

Every script records the box state beside its number (load, free memory,
GPU), because a throughput number without the box it was measured on is not
a measurement (DOC-RULES.md).

| script | the brief's item | what it measures |
|---|---|---|
| `smoke_test.py` | — | the port works: the module loads, a batch of games resets, steps and observes |
| `run_rl_iteration.sh` | (a) | one RL iteration at `--num_envs 128`, timed, against upstream's "10-20 s on an RTX A6000" |
| `eval_pretrained.py` | (b) | the pretrained model against a random policy, over N games, in both seats |
| `bench_env.py` | (c) | env steps/s at batch 128 / 1024 / 4096 |

## Running them

All four need the checkout's venv first:

```bash
export PATH="$HOME/lm-wt/stratego/third_party/stratego/.venv/bin:$PATH"
export PYTHONPATH="$HOME/lm-wt/stratego/third_party/stratego"
cd "$HOME/lm-wt/stratego/third_party/stratego"
```

Then, from the checkout:

```bash
# smoke test (~30 s)
python ~/lm-wt/stratego/docs/lab/stratego-scripts/smoke_test.py

# (a) one RL iteration, timed
bash ~/lm-wt/stratego/docs/lab/stratego-scripts/run_rl_iteration.sh 128 3 /tmp/stratego-rl-128

# (b) pretrained vs random
python ~/lm-wt/stratego/docs/lab/stratego-scripts/eval_pretrained.py \
    --num-envs 256 --num-games 1024 --out results/eval.json

# (c) env throughput
python ~/lm-wt/stratego/docs/lab/stratego-scripts/bench_env.py \
    --num-envs 128,1024,4096 --out results/bench_env.json
```

The scripts write their JSON where `--out` says; the committed copies live in
`docs/lab/stratego-scripts/results/`.

## How long they take

- `smoke_test.py`: ~30 s.
- `run_rl_iteration.sh`: ~1 min of setup (the trainer builds two transformer
  models and the arrangement model) plus ~10-20 s per iteration. Run it for
  3 iterations and read the trainer's own `[N] Time spent = X s` lines.
- `eval_pretrained.py`: the long one. Each matchup plays `num_envs` games per
  seat and a Stratego game can run to 4000 moves, so this is minutes, not
  seconds.
- `bench_env.py`: ~5 min. It times 7 repetitions at each of the three batch
  sizes, and each repetition is 2000 steps.

## Notes that will save you a run

- **`evaluate()` returns 2 x num_envs.** The first half is the agent as
  player 0, the second half as player 1, so one `evaluate()` call already
  covers both seats (upstream's `evaluation.py:100`).
- **The random baseline must be an `ActionTaker`.** `extract_action`
  dispatches on the agent's *type* (`evaluation.py:16`): a `Model` is called
  with five keyword arguments, an `ActionTaker` with the legal-action mask.
  A one-argument callable matches `ActionTaker` and is called as
  `agent(env.current_legal_action_mask)`.
- **The legal-action mask is not filled in by a step.** It is computed on
  request with `compute_legal_action_mask(t)`.
- **The buffer needs 210 rows of history.** Below that the environment
  rejects the continuous-chasing rule ("the buffer size is too small to
  support the continuous chasing rule"), which is the env's own check, not a
  port bug.
- **`sample_random_legal_action(out=None)`** allocates its own output tensor
  if you do not pass one.
- **The trainer's CLI is pyrallis, not argparse** (`scripts/train/rl_main.py`
  ends with `pyrallis.parse(config_class=MainConfig)`), so nested options use
  dots: `--rl.dtype float32 --rl.torch_compile false --rl.max_num_train 3`.

## What these scripts do not measure

- They do not measure the *search* (upstream's `SearchBot`), only the policy
  and the environment. The belief model's contribution is described in
  `docs/research/stratego.md`, not measured here.
- `run_rl_iteration.sh` times the **whole** training iteration, which
  includes the arrangement model's training and the periodic evaluation —
  it is the number upstream quotes, so it is the number to compare with.
- The build has no `CMAKE_BUILD_TYPE`, so upstream's device-side asserts are
  still in. The env is therefore slower than a release build would be; the
  comparison with upstream's 10-20 s is like for like, because upstream also
  builds that way.
