#!/usr/bin/env bash
# ops/d1.sh — the world's decision model.
#
#   ops/d1.sh start     start d1-2B (it takes the lease only while the
#                       model loads)
#   ops/d1.sh stop      stop it
#   ops/d1.sh status    is it up, and how fast is it answering
#   ops/d1.sh logs [n]  the model's log
#
# One model, shared by every builder: the reflex batches their questions
# into one pack, so four builders cost one call.
set -euo pipefail

. "$(dirname "$0")/env.sh"

SESSION="$AW_TMUX_SESSION"
WINDOW="d1"
LOG="$AW_LOG_DIR/d1.log"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

window_exists() {
    tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$WINDOW"
}

cmd_start() {
    if window_exists; then
        say "the decision model is already up"
        return 0
    fi
    mkdir -p "$AW_LOG_DIR"
    say "starting d1-2B on port $AW_D1_PORT"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux new-window -d -t "$SESSION" -n "$WINDOW" \
            "'$AW_ROOT/ops/run-d1.sh' >> '$LOG' 2>&1"
    else
        tmux new-session -d -s "$SESSION" -n "$WINDOW" \
            "'$AW_ROOT/ops/run-d1.sh' >> '$LOG' 2>&1"
    fi
    local waited=0
    while [ "$waited" -lt 300 ]; do
        if curl -sf --max-time 2 "http://127.0.0.1:$AW_D1_PORT/health" >/dev/null 2>&1; then
            say "the decision model is up"
            cmd_status
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    warn "the decision model did not come up; its log:"
    tail -20 "$LOG" >&2
    return 1
}

cmd_stop() {
    if ! window_exists; then
        say "the decision model is not running"
        return 0
    fi
    tmux kill-window -t "$SESSION:$WINDOW" 2>/dev/null || true
    say "the decision model has stopped"
}

cmd_status() {
    printf 'd1-2B        : %s\n' "$(window_exists && echo up || echo down)"
    printf 'port         : %s\n' "$AW_D1_PORT"
    if curl -sf --max-time 3 "http://127.0.0.1:$AW_D1_PORT/health" >/dev/null 2>&1; then
        printf 'health       : ok\n'
    else
        printf 'health       : not answering\n'
    fi
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) tail -n "${2:-30}" "$LOG" 2>/dev/null || echo "no model log yet" ;;
    *) sed -n '2,12p' "$0"; exit 1 ;;
esac
