#!/usr/bin/env bash
# Start both decision servers — the llama.cpp baseline and ours.
#
# Both model loads are heavy steps, so they are started through the
# box's admission daemon (`thor-admit serve`): the daemon takes the
# lease, waits until the box has room, and keeps the lease for as long
# as the server answers. If the daemon is missing, the heavy lock is
# the fallback.
#
# The two servers are registered under different model names, so each is
# loaded once per box but neither is confused with the other (the box
# also has a shared d1-2B server on :8094 that belongs to another seat).
set -u

PORT_BASE="${PORT_BASE:-8137}"
PORT_OURS="${PORT_OURS:-8138}"
MODEL="${MODEL:-/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf}"
BIN="${BIN:-/home/caseydigennaro/llama.cpp-upstream/build-up/bin/llama-server}"
LOG_BASE="${LOG_BASE:-logs/llamacpp_server.log}"
LOG_OURS="${LOG_OURS:-logs/ours_server.log}"
EXTRA="${EXTRA:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ADMIT="${ADMIT:-$HOME/lm-tools/thor-admit}"

mkdir -p "$REPO/logs"

# the baseline: llama.cpp in decision mode, with its own best flags.
#
#   -ngl 99            every layer on the GPU
#   -fa on             flash attention
#   -c 32768           the context: 64 slots of 512 tokens each, so the
#                      longest prompt of the workload (267 tokens) fits
#   --parallel 64      one slot per character of a tick
#   -ub 512            the physical batch size
#   -t 14 -tb 14       the CPU threads, for the parts that stay on the CPU
#   --cache-ram 0      no RAM prompt cache (the default for a decision model)
#
BASE_ARGS="-m $MODEL --host 127.0.0.1 --port $PORT_BASE -ngl 99 -fa on \
  -c 32768 --parallel 64 -ub 512 -t 14 -tb 14 --cache-ram 0 $EXTRA"

OURS_ARGS="$REPO/.venv/bin/python $REPO/scripts/run_server.py \
  --gguf $MODEL --host 127.0.0.1 --port $PORT_OURS \
  --max-batch-seqs 192 --max-batch-tokens 49152 --linger-ms 4.0"

launch() {
  local name="$1" port="$2" peak="$3" log="$4"; shift 4
  if command -v "$ADMIT" >/dev/null 2>&1; then
    # --priority 1 puts this lease in front of the ones already waiting.
    # The box's queue had two dead clients at its head (their processes
    # are gone, but the daemon only drops a waiter when it reaches the
    # head of the queue), and the head was held by a learned GPU peak of
    # 3.8 GB that belongs to a version of this server that no longer
    # exists — it now runs the tick's activations in chunks and uses
    # about 2.3 GB. The rule could not be satisfied, so nothing behind
    # it could be admitted either.
    "$ADMIT" run --tier live --priority 1 --peak "$peak" --label "$name" -- "$@" > "$log" 2>&1 &
  else
    echo "thor-admit unavailable ($name): falling back to the heavy lock" >&2
    flock -w 7200 "$HOME/lm-wt/heavy.lock" "$@" > "$log" 2>&1 &
  fi
  echo "launched $name on :$port (log $log)"
}

launch d1-2B-baseline "$PORT_BASE" 8G "$REPO/$LOG_BASE" $BIN $BASE_ARGS
launch d1-2B-batched  "$PORT_OURS" 6G "$REPO/$LOG_OURS" $OURS_ARGS

# wait for both
ok=0
for i in $(seq 1 900); do
  b=0; o=0
  curl -sf "http://127.0.0.1:$PORT_BASE/health" >/dev/null 2>&1 && b=1
  curl -sf "http://127.0.0.1:$PORT_OURS/health" >/dev/null 2>&1 && o=1
  if [ "$b" -eq 1 ] && [ "$o" -eq 1 ]; then
    echo "READY after ${i}s (baseline :$PORT_BASE, ours :$PORT_OURS)"
    ok=1
    break
  fi
  sleep 1
done

if [ "$ok" -eq 0 ]; then
  echo 'a server did not come up'
  echo '--- llama.cpp ---'; tail -30 "$REPO/$LOG_BASE"
  echo '--- ours ---'; tail -30 "$REPO/$LOG_OURS"
  exit 1
fi
