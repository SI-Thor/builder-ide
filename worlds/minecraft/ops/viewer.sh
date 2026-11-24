#!/usr/bin/env bash
# ops/viewer.sh — the world's window on the LAN.
#
#   ops/viewer.sh start     start the view
#   ops/viewer.sh stop      stop it
#   ops/viewer.sh status    is it up, and where
#   ops/viewer.sh logs [n]  the view's log
#
# One port, two views:
#
#   /            the 3D view (prismarine-viewer), the world as a
#                spectator sees it
#   /ascii       the text view of one perspective, projected by an
#                integer kernel
#
# The undo: ops/viewer.sh stop.
set -euo pipefail

. "$(dirname "$0")/env.sh"

SESSION="$AW_TMUX_SESSION"
WINDOW="viewer"
LOG="$AW_LOG_DIR/viewer.log"
NODE="$AW_NODE/bin/node"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

window_exists() {
    tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$WINDOW"
}

cmd_start() {
    if window_exists; then
        say "the view is already up"
        return 0
    fi
    [ -x "$NODE" ] || die "no node at $NODE — run ops/install-runtime.sh"
    [ -d "$AW_ROOT/viewer/node_modules" ] || die "the view is not installed — cd viewer && npm install"
    mkdir -p "$AW_LOG_DIR"
    say "opening the world's window on http://$AW_HOST:$AW_VIEW_PORT/"
    local env="AW_HOST='$AW_HOST' AW_PAPER_PORT='$AW_PAPER_PORT' AW_MINECRAFT_VERSION='$AW_MINECRAFT_VERSION' AW_VIEW_PORT='$AW_VIEW_PORT' AW_REFLEX_HOST='127.0.0.1' AW_REFLEX_PORT='$AW_REFLEX_PORT'"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux new-window -d -t "$SESSION" -n "$WINDOW" \
            "cd '$AW_ROOT/viewer' && $env '$NODE' src/server.js >> '$LOG' 2>&1"
    else
        tmux new-session -d -s "$SESSION" -n "$WINDOW" \
            "cd '$AW_ROOT/viewer' && $env '$NODE' src/server.js >> '$LOG' 2>&1"
    fi
    local waited=0
    while [ "$waited" -lt 30 ]; do
        if curl -sS --max-time 2 "http://127.0.0.1:$AW_VIEW_PORT/status" >/dev/null 2>&1; then
            say "the view is up"
            cmd_status
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    warn "the view did not come up; its log:"
    tail -20 "$LOG" >&2
    return 1
}

cmd_stop() {
    if ! window_exists; then
        say "the view is not running"
        return 0
    fi
    tmux kill-window -t "$SESSION:$WINDOW" 2>/dev/null || true
    say "the world's window is closed"
}

cmd_status() {
    printf 'view         : %s\n' "$(window_exists && echo up || echo down)"
    printf '3D view      : http://%s:%s/\n' "$AW_HOST" "$AW_VIEW_PORT"
    printf 'text view    : http://%s:%s/ascii\n' "$AW_HOST" "$AW_VIEW_PORT"
    printf 'status       : http://%s:%s/status\n' "$AW_HOST" "$AW_VIEW_PORT"
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) tail -n "${2:-40}" "$LOG" 2>/dev/null || echo "no view log yet" ;;
    *) sed -n '2,18p' "$0"; exit 1 ;;
esac
