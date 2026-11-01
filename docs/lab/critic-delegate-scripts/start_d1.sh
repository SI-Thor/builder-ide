#!/usr/bin/env bash
# Start the local decision model (d1-2B + its mmproj) for the delegate bake-off.
#
#   bash docs/lab/critic-delegate-scripts/start_d1.sh
#
# The model is the Thor's own copy: d1-2B (an LFM3 decision model) with the
# multimodal projector that gives it an eye. The server is the System One
# endpoint (`POST /v1/systemone`), bound to loopback only, on port 8131 (a
# port the other seats' d1 servers do not use).
#
# The reasoning is small: the model is a *decision* model, so it scores a
# typed question in one pass and writes no text. The image is encoded once
# per frame and the whole question set is scored in the same batch.
#
# The weights are small (1.8 GB of model, 200 MB of projector), so this is
# not the heavy stage the first bake-off's 17 GB VLM was — but it is still a
# resident model on a shared box, so it runs under the box's shared lock.
set -euo pipefail

MODEL="${MODEL:-$HOME/models/d1-2B/d1-2B-Q8_0.gguf}"
MMPROJ="${MMPROJ:-$HOME/models/d1-2B/mmproj-d1-2B-Q8_0.gguf}"
SERVER="${SERVER:-$HOME/llama.cpp-upstream/build-up/bin/llama-server}"
PORT="${PORT:-8131}"
LOG="$(dirname "$0")/results/d1-server.log"

mkdir -p "$(dirname "$LOG")"
nohup "$SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  -ngl 99 -c 4096 \
  --host 127.0.0.1 --port "$PORT" \
  > "$LOG" 2>&1 &

echo "llama-server pid $! on port $PORT (log: $LOG)"
