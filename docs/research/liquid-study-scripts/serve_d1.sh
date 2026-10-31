#!/usr/bin/env bash
# Start a PRIVATE d1 llama-server for the liquid-study experiments.
#
# We serve d1 ourselves on our own port, exactly as the brief asks, and stop
# it when we are done. We never touch another service on this box.
#
# The flags mirror the ones last-mile's systemd units and lab-cascade's
# servers use, so our numbers are comparable with theirs:
#   d1-2b.service / d1-3b.service  ->  -ngl 99 --flash-attn on --ctx-size 8192 -ub 4096
#   lab-cascade servers (8140-8148) -> same + 4 slots
#
# Usage:
#   serve_d1.sh start [PORT] [MODEL_PATH] [ALIAS]
#   serve_d1.sh stop  [PORT]
#
# Ports we own: 8290-8299. lab-cascade owns 8140-8148, 8180+, 8190+, 8200+.
# last-mile / Casey's services own 8093-8099, 8104, 8123.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LLAMA_SERVER="${LLAMA_SERVER:-$HOME/llama.cpp-upstream/build-up/bin/llama-server}"
SAVE_DIR="${SAVE_DIR:-$ROOT/state}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"

cmd="${1:-start}"
port="${2:-8291}"
model="${3:-$HOME/models/d1-omni-600M/d1-omni-600M-Q8_0.gguf}"
alias="${4:-d1-omni-600M-Q8}"

pidfile="$LOG_DIR/d1-$port.pid"
logfile="$LOG_DIR/d1-$port.log"

case "$cmd" in
  start)
    if [[ ! -x "$LLAMA_SERVER" ]]; then
      echo "FATAL: no llama-server at $LLAMA_SERVER" >&2; exit 1
    fi
    if [[ ! -f "$model" ]]; then
      echo "FATAL: no model at $model" >&2; exit 1
    fi
    mkdir -p "$SAVE_DIR" "$LOG_DIR"
    # Refuse to start if something is already listening on our port.
    if curl -s --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      echo "FATAL: something already answers on 127.0.0.1:$port" >&2; exit 1
    fi
    # EXTRA_ARGS lets a caller add flags (e.g. "--cache-ram 4096").
    # shellcheck disable=SC2206
    extra=(${EXTRA_ARGS:-})
    nohup "$LLAMA_SERVER" \
      -m "$model" \
      --host 127.0.0.1 \
      --port "$port" \
      -ngl 99 \
      --flash-attn on \
      --ctx-size 8192 \
      -np 4 \
      -ub 4096 \
      --alias "$alias" \
      --slot-save-path "$SAVE_DIR" \
      "${extra[@]}" \
      >"$logfile" 2>&1 &
    echo $! > "$pidfile"
    echo "started d1 '$alias' on 127.0.0.1:$port (pid $(cat "$pidfile")), log $logfile"
    # Wait for readiness (up to 180s: the box is shared and slow to load).
    for _ in $(seq 1 180); do
      if curl -s --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
        echo "ready after ${SECONDS}s"
        exit 0
      fi
      sleep 1
    done
    echo "FATAL: server did not become ready; see $logfile" >&2
    exit 1
    ;;
  stop)
    if [[ -f "$pidfile" ]]; then
      pid="$(cat "$pidfile")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
        kill -9 "$pid" 2>/dev/null || true
        echo "stopped pid $pid on port $port"
      else
        echo "pid $pid already gone"
      fi
      rm -f "$pidfile"
    else
      echo "no pidfile for port $port; nothing of ours to stop"
    fi
    ;;
  *)
    echo "usage: $0 {start|stop} [port] [model] [alias]" >&2; exit 2
    ;;
esac
