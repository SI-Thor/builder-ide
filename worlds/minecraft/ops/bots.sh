#!/usr/bin/env bash
# ops/bots.sh — the community: the reflex and the builders.
#
#   ops/bots.sh start        start the reflex and the builders
#   ops/bots.sh stop         stop them
#   ops/bots.sh status       how they are doing
#   ops/bots.sh logs [n]     the builders' own log (decisions and outcomes)
#   ops/bots.sh report       the numbers from the world's ledger
#   ops/bots.sh observe      is the sign holding?
#   ops/bots.sh mediate      step in, if the sign has faded
#
# Two processes, two windows of the world's tmux session:
#
#   reflex  the decision seam (Python): the library, the log, the
#           contextual bandit, and the one d1-2B server the whole world
#           shares. It listens on loopback only.
#   bots    the builders (Node): four mineflayer clients, one per role.
#           They ask the reflex what to do; they never choose for
#           themselves.
#
# The undo: ops/bots.sh stop.
set -euo pipefail

. "$(dirname "$0")/env.sh"

SESSION="$AW_TMUX_SESSION"
REFLEX_WINDOW="reflex"
BOTS_WINDOW="bots"
LOG="$AW_LOG_DIR/bots.jsonl"

PY="$AW_RUNTIME/venv/bin/python"
REFLEX_SRC="$AW_ROOT/reflex"
NODE="$AW_NODE/bin/node"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

window_exists() {
    tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$1"
}

# The environment every part of the world shares. It is written out
# inline in each tmux command, because a tmux session inherits the
# environment of the process that *created* the session, not of the
# process that opens a window in it — and the world was created by
# ops/paper.sh, which knows nothing about the reflex.
world_env() {
    echo "AW_RUNTIME='$AW_RUNTIME' AW_HOST='$AW_HOST' AW_PAPER_PORT='$AW_PAPER_PORT' \
AW_MINECRAFT_VERSION='$AW_MINECRAFT_VERSION' AW_REFLEX_HOST='127.0.0.1' \
AW_REFLEX_PORT='$AW_REFLEX_PORT' AW_D1_PORT='$AW_D1_PORT' AW_HEAVY_LOCK='$AW_HEAVY_LOCK' \
AW_BOT_LOG='$LOG' AW_TICK_MS='${AW_TICK_MS:-2000}'"
}

# --- the reflex ---------------------------------------------------------------
start_reflex() {
    if window_exists "$REFLEX_WINDOW"; then
        say "the reflex is already up"
        return 0
    fi
    [ -x "$PY" ] || die "no python at $PY — run ops/install-runtime.sh"
    mkdir -p "$AW_LOG_DIR"
    say "starting the reflex (loopback:$AW_REFLEX_PORT, d1 on $AW_D1_PORT)"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux new-window -d -t "$SESSION" -n "$REFLEX_WINDOW" \
            "cd '$REFLEX_SRC' && $(world_env) PYTHONPATH='$REFLEX_SRC' '$PY' -m agent_world_reflex serve >> '$AW_LOG_DIR/reflex.log' 2>&1"
    else
        tmux new-session -d -s "$SESSION" -n "$REFLEX_WINDOW" \
            "cd '$REFLEX_SRC' && $(world_env) PYTHONPATH='$REFLEX_SRC' '$PY' -m agent_world_reflex serve >> '$AW_LOG_DIR/reflex.log' 2>&1"
    fi
    local waited=0
    while [ "$waited" -lt 30 ]; do
        if curl -sS --max-time 2 "http://127.0.0.1:$AW_REFLEX_PORT/health" >/dev/null 2>&1; then
            say "the reflex is listening"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    warn "the reflex did not come up; its log:"
    tail -20 "$AW_LOG_DIR/reflex.log" >&2
    return 1
}

# --- the builders -------------------------------------------------------------
start_bots() {
    if window_exists "$BOTS_WINDOW"; then
        say "the builders are already up"
        return 0
    fi
    [ -x "$NODE" ] || die "no node at $NODE — run ops/install-runtime.sh"
    [ -d "$AW_ROOT/bots/node_modules" ] || die "the builders are not installed — cd bots && npm install"
    say "starting the builders"
    local cmd="cd '$AW_ROOT/bots' && $(world_env) '$NODE' src/index.js >> '$AW_LOG_DIR/bots.out' 2>&1"
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux new-window -d -t "$SESSION" -n "$BOTS_WINDOW" "$cmd"
    else
        tmux new-session -d -s "$SESSION" -n "$BOTS_WINDOW" "$cmd"
    fi
    sleep 5
    tail -8 "$AW_LOG_DIR/bots.out" 2>/dev/null || true
}

cmd_start() {
    mkdir -p "$AW_LOG_DIR"
    start_reflex || die "the reflex is not up; the builders have nothing to ask"
    start_bots
    cmd_status
}

cmd_stop() {
    # kill-window is a SIGHUP: the builders die mid-word and the server
    # logs four mystery "Disconnected" lines — day one's "Pebble's
    # disconnects at delivery moments" were exactly this, one per
    # operator restart, all four sockets closing the same second
    # (paper.log 03:13:20, 03:23:31, 03:30:04, 03:42:09, 04:00:03,
    # 04:26:41 local). SIGTERM walks the graceful path first —
    # bot.quit("the world is resting"), the log stream closed — and
    # the window comes down only after the leaf has had its seconds.
    for window in "$BOTS_WINDOW" "$REFLEX_WINDOW"; do
        if window_exists "$window"; then
            say "ending the '$window' window"
            local pane children waited
            pane="$(tmux display-message -p -t "$SESSION:$window" '#{pane_pid}' 2>/dev/null || true)"
            if [ -n "$pane" ]; then
                children="$(pgrep -P "$pane" 2>/dev/null || true)"
                if [ -n "$children" ]; then
                    kill -TERM $children 2>/dev/null || true
                    waited=0
                    while [ "$waited" -lt 8 ] && pgrep -P "$pane" >/dev/null 2>&1; do
                        sleep 1
                        waited=$((waited + 1))
                    done
                fi
            fi
            tmux kill-window -t "$SESSION:$window" 2>/dev/null || true
        fi
    done
    say "the community is resting"
}

cmd_status() {
    printf 'reflex       : %s\n' "$(window_exists "$REFLEX_WINDOW" && echo up || echo down)"
    printf 'builders     : %s\n' "$(window_exists "$BOTS_WINDOW" && echo up || echo down)"
    printf 'world        : %s\n' "$(tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | tr '\n' ' ')"
    if curl -sS --max-time 3 "http://127.0.0.1:$AW_REFLEX_PORT/stats" 2>/dev/null; then
        echo
    fi
}

cmd_logs() {
    tail -n "${1:-40}" "$LOG" 2>/dev/null || echo "no builder log yet at $LOG"
}

cmd_report() {
    cd "$REFLEX_SRC" && AW_RUNTIME="$AW_RUNTIME" PYTHONPATH="$REFLEX_SRC" "$PY" -m agent_world_reflex report
}

cmd_observe() {
    cd "$REFLEX_SRC" && AW_RUNTIME="$AW_RUNTIME" PYTHONPATH="$REFLEX_SRC" "$PY" -m agent_world_reflex observe
}

cmd_mediate() {
    cd "$REFLEX_SRC" && AW_RUNTIME="$AW_RUNTIME" PYTHONPATH="$REFLEX_SRC" "$PY" -m agent_world_reflex mediate
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) cmd_logs "${2:-40}" ;;
    report) cmd_report ;;
    observe) cmd_observe ;;
    mediate) cmd_mediate ;;
    *) sed -n '2,22p' "$0"; exit 1 ;;
esac
