#!/bin/bash
# (a) One RL iteration, timed, on the Thor.
#
# Upstream's own demo line (README.md):
#
#   python scripts/train/rl_main.py --num_envs 128 --rl.dtype float32 --rl.torch_compile false
#
# "Iterations usually take 10-20 seconds on an RTX A6000."
#
# This runs exactly that command, with --rl.max_num_train so that the run stops
# after N iterations, and extracts the per-iteration wall time from the
# trainer's own "[N] Time spent = X s" lines (pyengine/utils/multi_counter.py:115).
#
# Usage: bash run_rl_iteration.sh [num_envs] [num_iters] [out_dir]
set -euo pipefail

NUM_ENVS="${1:-128}"
NUM_ITERS="${2:-3}"
OUT_DIR="${3:-/tmp/stratego-rl-${NUM_ENVS}}"

CHECKOUT="$HOME/lm-wt/stratego/third_party/stratego"
cd "$CHECKOUT"

export PATH="$CHECKOUT/.venv/bin:$PATH"
export PYTHONPATH="$CHECKOUT"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

LOG="$OUT_DIR/rl_main.log"
echo "running: num_envs=$NUM_ENVS iters=$NUM_ITERS out=$OUT_DIR"

python scripts/train/rl_main.py \
    --num_envs "$NUM_ENVS" \
    --rl.dtype float32 \
    --rl.torch_compile false \
    --rl.max_num_train "$NUM_ITERS" \
    --save_dir "$OUT_DIR" > "$LOG" 2>&1 || {
        echo "TRAIN FAILED; tail of $LOG:"
        tail -30 "$LOG"
        exit 1
    }

echo "--- per-iteration wall time (trainer's own counter) ---"
grep -E "^\[[0-9]+\] Time spent" "$LOG" || true

echo "--- section breakdown (last iteration) ---"
grep -E "^(rollout|prep_data|train|arr_train|update_arrangements)" "$LOG" | tail -12 || true

echo "--- env stats ---"
grep -E "data/pl0_return|data/gamelen|count/num_env_step" "$LOG" | tail -6 || true

echo "log: $LOG"
