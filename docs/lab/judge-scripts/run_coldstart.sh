#!/usr/bin/env bash
# The tiles cold-start measurement, on the Thor, under the house rules.
#
# One server at a time, ours only, on our own port; the whole run takes
# ~/lm-wt/heavy.lock so it queues behind other seats instead of fighting
# them for the GPU; `free -g` is checked after the load (≥ 25 GB
# available, the brief's bar) and the server is stopped when we are done.
# Only the d1 decision model is served — no other LLM is hosted here.
#
# Usage (on the Thor):
#   cd ~/lm-wt/core-judge/docs/lab/judge-scripts
#   ./run_coldstart.sh [PORT] [PLAYS]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PORT="${1:-8295}"
PLAYS="${2:-600}"
MODEL="$HOME/models/d1-2B/d1-2B-Q8_0.gguf"
LLAMA_SERVER="${LLAMA_SERVER:-$HOME/llama.cpp-upstream/build-up/bin/llama-server}"
RUN_DIR="$HERE/run"
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/server-$PORT.log"
PIDFILE="$RUN_DIR/server-$PORT.pid"

if [[ ! -x "$LLAMA_SERVER" ]]; then echo "FATAL: no llama-server at $LLAMA_SERVER" >&2; exit 1; fi
if [[ ! -f "$MODEL" ]]; then echo "FATAL: no model at $MODEL" >&2; exit 1; fi
if curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "FATAL: something already answers on 127.0.0.1:$PORT" >&2; exit 1
fi

stop_server() {
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid="$(cat "$PIDFILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
    echo "[runner] server stopped"
  fi
}
trap stop_server EXIT

echo "[runner] $(date -Is) queueing for the heavy lock (~/lm-wt/heavy.lock)"
exec 9>"$HOME/lm-wt/heavy.lock"
flock -w 7200 9
echo "[runner] $(date -Is) got the lock"

# -- serve d1-2B Q8 (the seats' unit flags: -ngl 99 --flash-attn on --ctx 8192 -ub 4096)
"$LLAMA_SERVER" \
  -m "$MODEL" \
  --host 127.0.0.1 \
  --port "$PORT" \
  -ngl 99 \
  --flash-attn on \
  --ctx-size 8192 \
  -ub 4096 \
  --alias d1-2B-Q8 \
  >"$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "[runner] serving d1-2B Q8 on 127.0.0.1:$PORT (pid $(cat "$PIDFILE")); log $LOG"

for _ in $(seq 1 360); do
  if curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "[runner] server ready after ${SECONDS}s"
    break
  fi
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "FATAL: server died during load; see $LOG" >&2
    tail -5 "$LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

# -- the brief's bar: ≥ 25 GB available after the load
AVAILABLE_GB=$(free -g | awk '/^Mem:/{print $7}')
echo "[runner] free -g available after load: ${AVAILABLE_GB}G"
if [[ "$AVAILABLE_GB" -lt 25 ]]; then
  echo "FATAL: only ${AVAILABLE_GB}G available after the load (bar: 25G); stopping" >&2
  exit 1
fi

# -- the measurement
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="${PYTHON:-python3}"; fi
echo "[runner] measuring with $PYTHON ($PLAYS plays)"
cd "$REPO"
"$PYTHON" "$HERE/measure_tiles_coldstart.py" \
  --port "$PORT" \
  --plays "$PLAYS" \
  --server-pid "$(cat "$PIDFILE")" \
  --out "$HERE/results/judge-tiles-coldstart.json"

echo "[runner] $(date -Is) done; stopping the server"
