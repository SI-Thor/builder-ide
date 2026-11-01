#!/usr/bin/env bash
# Start the local VLM (Muse-Glimmer-30B + its perception encoder) for the bake-off.
#
# The model is the Thor's own copy: Apache-2.0, already on disk, no download.
# The server is the OpenAI-compatible llama.cpp endpoint, loopback only, on
# port 8123 (the port the other seats' d1 servers do not use).
#
#   bash docs/lab/critic-select-scripts/start_vlm.sh
#
# The reasoning budget is capped on purpose: Muse Glimmer always thinks, and a
# 30 B model thinking at length costs ~30 s per yes/no question. 320 thinking
# tokens is enough to answer the question and keeps the verdict in the
# seconds. The cap is part of the measurement, so it is reported.
set -euo pipefail

MODEL="${MODEL:-$HOME/models/Muse-Glimmer-30B-GGUF/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf}"
MMPROJ="${MMPROJ:-$HOME/models/Muse-Glimmer-30B-GGUF/mmproj-Muse-Glimmer-30B-Q4_K_M.gguf}"
SERVER="${SERVER:-$HOME/llama.cpp/build/bin/llama-server}"
PORT="${PORT:-8123}"
LOG="$(dirname "$0")/results/vlm-server.log"

mkdir -p "$(dirname "$LOG")"
nohup "$SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  -a muse-glimmer-30b \
  -ngl 99 -c 16384 -np 1 \
  --host 127.0.0.1 --port "$PORT" --jinja \
  --temp 0.0 --top-p 1.0 --top-k 1 \
  --reasoning-budget 320 \
  --chat-template-kwargs '{"reasoning_strength":"low"}' \
  > "$LOG" 2>&1 &

echo "llama-server pid $! on port $PORT (log: $LOG)"
