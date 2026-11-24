#!/usr/bin/env bash
# ops/drift-watch.sh — the drift detector's loop over the live world.
#
# One window every five minutes: ops/drift-watch.py folds the live
# ledger, gates it, and enforces SOFT holds on the pause file (tier and
# hard stay dry-run — a human's call). The world reads the pause file
# at its admission seam and yields politely; nobody is killed.
#
#   ops/drift-watch.sh start     run detached (setsid nohup)
#   ops/drift-watch.sh stop
#   ops/drift-watch.sh status    the pauses in force
#   ops/drift-watch.sh once      one window, in the foreground
#
# The undo: stop; the entries lapse at their TTL (30 min) on their own.
set -euo pipefail

. "$(dirname "$0")/env.sh"

PY="${AW_DRIFT_PYTHON:-$HOME/lm-wt/core-api/.venv/bin/python}"
WATCH="$AW_ROOT/ops/drift-watch.py"
LOG="$AW_LOG_DIR/drift-watch.out"
PIDFILE="$AW_RUNTIME/drift-watch.pid"
INTERVAL="${AW_DRIFT_INTERVAL:-300}"

cmd_start() {
    if pgrep -f "drift-watch.py --loop" >/dev/null 2>&1; then
        echo "the drift watcher is already running:"
        pgrep -af "drift-watch.py --loop" || true
        return 0
    fi
    setsid nohup "$PY" "$WATCH" --loop "$INTERVAL" >> "$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    echo "the drift watcher is detached (every ${INTERVAL}s), log $LOG"
}

cmd_stop() {
    pkill -f "drift-watch.py --loop" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "the drift watcher is stopped; pauses lapse at their TTL"
}

cmd_status() {
    if pgrep -f "drift-watch.py --loop" >/dev/null 2>&1; then
        echo "watcher: running"
    else
        echo "watcher: down"
    fi
    "$PY" "$WATCH" --status || true
    tail -5 "$AW_LOG_DIR/drift-watch.log" 2>/dev/null || true
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    once) "$PY" "$WATCH" ;;
    *) sed -n '2,18p' "$0"; exit 1 ;;
esac
