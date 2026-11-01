#!/usr/bin/env bash
# Start the local decision model (d1-2B + its mmproj) for the delegate bake-off.
#
#   bash docs/lab/critic-delegate-scripts/start_d1.sh
#
# The model is the Thor's own copy: d1-2B (an LFM3 decision model) with the
# multimodal projector that gives it an eye. The server is the System One
# endpoint (`POST /v1/systemone`), bound to loopback only.
#
# The reasoning is small: the model is a *decision* model, so it scores a
# typed question in one pass and writes no text. The image is encoded once
# per frame and the whole question set is scored in the same batch.
#
# **The server is started under the box's admission daemon**, not by hand:
#
#   thor-admit serve d1-2B --port 8131 -- llama-server -m ... --mmproj ...
#
# A model is loaded **once per box**, not once per seat. If another seat
# already has d1-2B answering, the daemon hands back that port and starts
# nothing — which is the point: two seats each starting one is half of how
# the box ran out of memory on 2026-10-31. So this script does not assume
# the port it asked for is the port it gets: it reads the port back out of
# the daemon's own answer and writes it to `results/d1.port`, and the stage
# script talks to whatever that is.
#
# The weights are small (1.8 GB of model, 200 MB of projector), so this is
# not the heavy stage the first bake-off's 17 GB VLM was — but it is still a
# resident model on a shared box, and the daemon holds the lease for it.
set -euo pipefail

MODEL="${MODEL:-$HOME/models/d1-2B/d1-2B-Q8_0.gguf}"
MMPROJ="${MMPROJ:-$HOME/models/d1-2B/mmproj-d1-2B-Q8_0.gguf}"
SERVER="${SERVER:-$HOME/llama.cpp-upstream/build-up/bin/llama-server}"
PORT="${PORT:-8131}"
#: The registry key the daemon files the server under. It is the model's name,
#: and the daemon answers with the port of *that* model's server if one is
#: already answering — which is the box-wide "one model, one server" rule.
SERVE_MODEL="${SERVE_MODEL:-d1-2B}"
#: The peak the lease reserves. A decision model with its projector is ~2 GB
#: resident; 8 G is what the other seats' d1 servers declare, and the daemon
#: needs an explicit peak for a label it has no history for.
PEAK="${PEAK:-8G}"
ADMIT="${ADMIT:-$HOME/lm-tools/thor-admit}"
HERE="$(dirname "$0")"
LOG="$HERE/results/d1-server.log"
PORT_FILE="$HERE/results/d1.port"
PID_FILE="$HERE/results/d1.pid"

mkdir -p "$HERE/results"
rm -f "$PORT_FILE" "$PID_FILE"

if [ ! -x "$ADMIT" ] && ! command -v thor-admit >/dev/null 2>&1; then
  echo "! thor-admit is not available — falling back to a bare server" >&2
  echo "  (the memory rule's daemon is the default; the flock is only for" >&2
  echo "   when the binary itself is missing — see ~/lm-wt/MEMORY-RULE.md)" >&2
  nohup "$SERVER" \
    -m "$MODEL" \
    --mmproj "$MMPROJ" \
    -ngl 99 -c 4096 \
    --host 127.0.0.1 --port "$PORT" \
    > "$LOG" 2>&1 &
  echo $! > "$PID_FILE"
  echo "$PORT" > "$PORT_FILE"
  echo "llama-server pid $(cat "$PID_FILE") on port $PORT (log: $LOG)"
  exit 0
fi
ADMIT="$(command -v thor-admit || echo "$ADMIT")"

nohup "$ADMIT" serve "$SERVE_MODEL" --port "$PORT" --peak "$PEAK" -- \
  "$SERVER" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  -ngl 99 -c 4096 \
  --host 127.0.0.1 --port "$PORT" \
  > "$LOG" 2>&1 &
echo $! > "$PID_FILE"

# The daemon answers in one of two ways:
#
#   "d1-2B" is served on port 8094   — another seat already has it; nothing
#                                     was started here, and the port is theirs
#   serving "d1-2B" on port 8131    — this is ours to start, on the port we
#                                     asked for
#
# Either way the port is in the log, so read it back rather than assuming.
RESOLVED=""
for _ in $(seq 1 120); do
  RESOLVED="$(grep -oE 'port [0-9]+' "$LOG" | head -1 | grep -oE '[0-9]+' || true)"
  if [ -n "$RESOLVED" ]; then
    break
  fi
  sleep 1
done

if [ -z "$RESOLVED" ]; then
  echo "! the admission daemon did not report a port" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

echo "$RESOLVED" > "$PORT_FILE"
echo "d1-2B is served on port $RESOLVED (serve pid $(cat "$PID_FILE"), log: $LOG)"
