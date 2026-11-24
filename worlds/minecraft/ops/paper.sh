#!/usr/bin/env bash
# ops/paper.sh — the Minecraft Java world on the Thor.
#
#   ops/paper.sh start        start the world (in tmux, under the lease)
#   ops/paper.sh stop         stop it cleanly (save, then exit)
#   ops/paper.sh restart      stop, then start
#   ops/paper.sh status       is it up, on what port, how much memory
#   ops/paper.sh logs [n]     the last n lines of the server log
#   ops/paper.sh console      attach to the server console (Ctrl-C detaches)
#   ops/paper.sh whitelist list|add <name>|remove <name>
#   ops/paper.sh plugins      install Geyser + Floodgate (the Bedrock door)
#
# The undo for the whole thing: ops/paper.sh stop, then rm -rf runtime/.
set -euo pipefail

. "$(dirname "$0")/env.sh"
. "$(dirname "$0")/lease.sh"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

SESSION="$AW_TMUX_SESSION"
WINDOW="paper"
TARGET="$AW_TMUX_SESSION:$WINDOW"
LOG="$AW_LOG_DIR/paper.log"

# The world runs in its own window of the world's tmux session, so the
# bots and the browser view sit beside it and `tmux attach` shows all
# three at once.
window_exists() {
    tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$WINDOW"
}

# --- the address the world binds to -----------------------------------------
# The LAN address of the Thor, as the kernel currently sees it. The
# configured address wins when it is still there; otherwise the current one
# is used and the change is said out loud, because a server that cannot bind
# its address is a server nobody can reach.
aw_lan_ip() {
    if ip -4 addr show | grep -q "inet $AW_HOST/"; then
        echo "$AW_HOST"
        return
    fi
    local ip
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p')"
    [ -n "$ip" ] || ip="0.0.0.0"
    echo "$ip"
}

# --- the configuration -------------------------------------------------------
render_properties() {
    local ip
    ip="$(aw_lan_ip)"
    mkdir -p "$AW_SERVER_DIR"
    if [ "$ip" != "$AW_HOST" ]; then
        warn "the Thor is at $ip now (configured $AW_HOST) — binding to $ip"
        warn "update AW_HOST in ops/env.sh if this is a permanent change"
    fi
    sed -e "s|@IP@|$ip|" -e "s|@SEED@|$AW_LEVEL_SEED|" \
        "$AW_ROOT/ops/world/server.properties.template" \
        > "$AW_SERVER_DIR/server.properties"
    # The playtest door (Casey, 2026-11-01: "playable with the agents
    # live"). The whitelist itself stays in ops/world/whitelist.txt —
    # it is the intent for when the world is published — but while
    # AW_PLAYTEST=1 the door stands open for anyone on the LAN, which
    # is what playing with the family needs. (A plain restart used to
    # quietly re-arm the whitelist: rendering the template reset
    # white-list=true every start, undoing a hand-run "whitelist off"
    # from the console — which is how the first battery run was
    # refused at the door.)
    if [ "${AW_PLAYTEST:-1}" = "1" ]; then
        sed -i -e "s/^white-list=true/white-list=false/" \
               -e "s/^enforce-whitelist=true/enforce-whitelist=false/" \
               "$AW_SERVER_DIR/server.properties"
        warn "playtest: the whitelist is OFF for this start (AW_PLAYTEST=1)"
    fi
    cp "$AW_ROOT/ops/world/eula.txt" "$AW_SERVER_DIR/eula.txt"
    say "server.properties rendered (bind $ip:$AW_PAPER_PORT, seed $AW_LEVEL_SEED)"
}

# The whitelist.
#
# Paper keeps the whitelist in its own whitelist.json, keyed by the
# player's UUID — and in offline mode that UUID is derived from the
# name, so the only reliable way to write it is the server's own
# `whitelist add` command. So this file (ops/world/whitelist.txt) is the
# **intent**, and the console commands are how the intent is applied:
# every start re-applies it, which is idempotent.
sync_whitelist() {
    # In playtest the door stands open (see render_properties), and the
    # console's "whitelist add" can itself re-arm enforcement on Paper —
    # so in playtest the names are left as they are and the whitelist is
    # said off, out loud, once.
    if [ "${AW_PLAYTEST:-1}" = "1" ]; then
        tmux send-keys -t "$TARGET" -l "whitelist off" </dev/null 2>/dev/null || true
        tmux send-keys -t "$TARGET" Enter </dev/null 2>/dev/null || true
        return 0
    fi
    local name
    while read -r name; do
        # Skip the comments and the blank lines: the file is written for
        # people to read.
        case "$name" in ''|'#'*) continue ;; esac
        # -l sends the text literally; </dev/null stops tmux from eating
        # the loop's own input (a tmux command reads stdin unless it is
        # given none).
        tmux send-keys -t "$TARGET" -l "whitelist add $name" </dev/null 2>/dev/null || true
        tmux send-keys -t "$TARGET" Enter </dev/null 2>/dev/null || true
    done < "$AW_WHITELIST"

    # And the other way round: a name the server still holds that our
    # file does not is a name that came off the list. The file is the
    # truth, so the server is corrected.
    local stray
    for stray in $(python3 -c "
import json, sys
try:
    entries = json.load(open('$AW_SERVER_DIR/whitelist.json'))
except Exception:
    entries = []
print(' '.join(sorted(str(e.get('name', '')) for e in entries)))
" 2>/dev/null); do
        [ -n "$stray" ] || continue
        case "$stray" in '#'*) continue ;; esac
        if ! grep -vxF "$stray" "$AW_WHITELIST" >/dev/null 2>&1; then
            tmux send-keys -t "$TARGET" -l "whitelist remove $stray" </dev/null 2>/dev/null || true
            tmux send-keys -t "$TARGET" Enter </dev/null 2>/dev/null || true
        fi
    done
}

# --- the start ---------------------------------------------------------------
cmd_start() {
    if window_exists; then
        say "the world is already up (tmux $TARGET)"
        cmd_status
        return 0
    fi
    [ -f "$AW_PAPER_JAR" ] || die "no Paper jar at $AW_PAPER_JAR — run ops/install-runtime.sh"
    render_properties
    mkdir -p "$AW_LOG_DIR" "$AW_SERVER_DIR"

    # World generation is the heavy part of starting a world, so it takes
    # the lease: the world waits its turn rather than competing with a seat
    # that is already running something heavy. The wait happens inside the
    # tmux session, so this command returns at once and the world starts
    # when its turn comes.
    # Remember where the log is now, so "the world is up" is only ever
    # read from what this run wrote.
    local LOG_OFFSET=0
    if [ -f "$LOG" ]; then LOG_OFFSET="$(wc -c < "$LOG")"; fi

    say "starting the world in tmux ($SESSION); it queues for the lease"

    # nice 10 (in ops/run-paper.sh): the world is a resident, low-priority
    # citizen of the box. A live seat's work is never slowed down by it.
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux new-window -d -t "$SESSION" -n "$WINDOW" \
            "'$AW_ROOT/ops/run-paper.sh' >> '$LOG' 2>&1" \
            || die "tmux could not open the world's window"
    else
        tmux new-session -d -s "$SESSION" -n "$WINDOW" \
            "'$AW_ROOT/ops/run-paper.sh' >> '$LOG' 2>&1" \
            || die "tmux could not start the world"
    fi

    # Wait for the server to say it is done, or for it to die trying. Only
    # the part of the log written by *this* run counts: an earlier run's
    # "Done (" is not this world being up.
    local waited=0
    while [ "$waited" -lt "${AW_START_TIMEOUT:-180}" ]; do
        if tail -c "+$((LOG_OFFSET + 1))" "$LOG" 2>/dev/null | grep -q 'Done ('; then
            say "the world is up; applying the whitelist"
            sync_whitelist
            sleep 2
            cmd_status
            return 0
        fi
        if ! window_exists; then
            warn "the world exited during start-up; the last lines:"
            tail -30 "$LOG" >&2
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    if tail -c "+$((LOG_OFFSET + 1))" "$LOG" 2>/dev/null | grep -q 'queued for the lease'; then
        say "the world is queued for the lease (another seat is running heavy work)"
        say "it will start by itself; check with: ops/paper.sh logs 20"
        cmd_status
        return 0
    fi
    warn "the world did not finish starting within ${waited}s; it may still be generating"
    tail -20 "$LOG" >&2
    return 1
}

# --- the stop ----------------------------------------------------------------
cmd_stop() {
    if ! window_exists; then
        say "the world is not running"
        return 0
    fi
    say "asking the world to stop (save and exit)"
    tmux send-keys -t "$TARGET" -l "stop" </dev/null
    tmux send-keys -t "$TARGET" Enter </dev/null
    local waited=0
    while [ "$waited" -lt 90 ]; do
        if ! window_exists; then
            say "the world stopped cleanly"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    warn "the world did not stop in ${waited}s; ending the world's window"
    tmux kill-window -t "$TARGET" 2>/dev/null || true
    sleep 2
    return 1
}

# --- the status --------------------------------------------------------------
cmd_status() {
    local up="no"
    window_exists && up="yes"
    printf 'world running : %s\n' "$up"
    printf 'address       : %s:%s (java/tcp)\n' "$(aw_lan_ip)" "$AW_PAPER_PORT"
    printf 'bedrock       : %s:%s (udp, %s)\n' "$(aw_lan_ip)" "$AW_BEDROCK_PORT" \
        "$([ -f "$AW_SERVER_DIR/plugins/Geyser-Spigot.jar" ] && echo installed || echo "not installed")"
    printf 'server dir    : %s\n' "$AW_SERVER_DIR"
    printf 'heap cap      : %s\n' "$AW_PAPER_XMX"
    if [ "$up" = "yes" ]; then
        local rss
        rss="$(ps -eo rss,args | grep '[p]aper-.*\.jar' | awk '{s+=$1} END {printf "%.0f", s/1024}')"
        printf 'resident (MB) : %s\n' "${rss:-?}"
        printf 'joins so far  : %s\n' "$(grep -c 'joined the game' "$LOG" 2>/dev/null | head -1 || true)"
    fi
    printf 'log           : %s\n' "$LOG"
}

# --- the whitelist -----------------------------------------------------------
cmd_whitelist() {
    case "${1:-list}" in
        list)
            grep -vE '^\s*(#|$)' "$AW_WHITELIST" || true
            ;;
        add)
            [ -n "${2:-}" ] || die "usage: ops/paper.sh whitelist add <name>"
            if ! grep -qxF "$2" "$AW_WHITELIST"; then
                printf '%s\n' "$2" >> "$AW_WHITELIST"
            fi
            if window_exists; then
                tmux send-keys -t "$TARGET" -l "whitelist add $2" </dev/null
                tmux send-keys -t "$TARGET" Enter </dev/null
                say "$2 is on the whitelist"
            else
                say "$2 is on the list; it will be applied when the world starts"
            fi
            ;;
        remove)
            [ -n "${2:-}" ] || die "usage: ops/paper.sh whitelist remove <name>"
            grep -vxF "$2" "$AW_WHITELIST" > "$AW_WHITELIST.tmp" || true
            mv "$AW_WHITELIST.tmp" "$AW_WHITELIST"
            if window_exists; then
                tmux send-keys -t "$TARGET" -l "whitelist remove $2" </dev/null
                tmux send-keys -t "$TARGET" Enter </dev/null
                say "$2 is off the whitelist"
            else
                say "$2 is off the list; the world is not running"
            fi
            ;;
        *)
            die "usage: ops/paper.sh whitelist list|add <name>|remove <name>"
            ;;
    esac
}

# --- the plugins -------------------------------------------------------------
cmd_plugins() {
    mkdir -p "$AW_SERVER_DIR/plugins"
    local src="$AW_RUNTIME/dl"
    [ -f "$src/Geyser-Spigot.jar" ] || die "no Geyser jar in $src — run ops/install-runtime.sh"
    [ -f "$src/floodgate-spigot.jar" ] || die "no Floodgate jar in $src — run ops/install-runtime.sh"
    cp "$src/Geyser-Spigot.jar" "$AW_SERVER_DIR/plugins/"
    cp "$src/floodgate-spigot.jar" "$AW_SERVER_DIR/plugins/"
    say "Geyser + Floodgate installed (the world restarts to pick them up)"
}

# --- the logs ----------------------------------------------------------------
cmd_logs() {
    local n="${1:-40}"
    tail -n "$n" "$LOG" 2>/dev/null || echo "no log yet at $LOG"
}

cmd_console() {
    tmux attach -t "$TARGET"
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status) cmd_status ;;
    logs) cmd_logs "${2:-40}" ;;
    console) cmd_console ;;
    whitelist) cmd_whitelist "${2:-list}" "${3:-}" ;;
    plugins) cmd_plugins ;;
    *) sed -n '2,20p' "$0"; exit 1 ;;
esac
