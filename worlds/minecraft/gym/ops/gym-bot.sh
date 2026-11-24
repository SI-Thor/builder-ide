#!/usr/bin/env bash
# gym/ops/gym-bot.sh — the gym's bot: the bridge between the Python
# environment and the mineflayer client.
#
#   gym-bot.sh start    start the bridge, detached
#   gym-bot.sh stop     stop it
#   gym-bot.sh status   is it up, is the bot in the world
#   gym-bot.sh logs [n] the last n lines of the bridge's log
#
# The bridge is loopback only (127.0.0.1:25640 by default). It plays on
# the **private** world (127.0.0.1:25630) and never on the live one.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$REPO/runtime"
LOG_DIR="$RUNTIME/logs"
LOG="$LOG_DIR/gym-bridge.log"

GYM_HOST="${AW_GYM_HOST:-127.0.0.1}"
GYM_PORT="${AW_GYM_PORT:-25630}"
BRIDGE_PORT="${AW_GYM_BRIDGE_PORT:-25640}"
BOT_NAME="${AW_GYM_BOT:-Pupil}"
BOT_ROLE="${AW_GYM_ROLE:-gatherer}"
NODE="${AW_NODE:-$HOME/lm-wt/agent-world/runtime/node/bin/node}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

bot_pids() {
  pgrep -af "[g]ym-bot.js" 2>/dev/null | awk '{print $1}' || true
}

cmd_start() {
  local pids
  pids="$(bot_pids)"
  if [ -n "$pids" ]; then
    say "the bridge is already running (pid $(echo "$pids" | tr '\n' ' '))"
    return 0
  fi
  [ -x "$NODE" ] || NODE="$(command -v node)" || die "no node on this box"
  [ -d "$RUNTIME/skills" ] || die "no skill snapshot at $RUNTIME/skills — run: gym-world.sh setup"
  [ -e "$REPO/bots/node_modules" ] || die "no node_modules — run: gym-world.sh setup"

  mkdir -p "$LOG_DIR"
  say "starting the bridge on 127.0.0.1:$BRIDGE_PORT (the bot plays on $GYM_HOST:$GYM_PORT)"
  setsid -f nohup "$NODE" "$REPO/gym/bot/gym-bot.js" \
    --host "$GYM_HOST" --port "$GYM_PORT" --bridge-port "$BRIDGE_PORT" \
    --name "$BOT_NAME" --role "$BOT_ROLE" \
    > "$LOG" 2>&1 < /dev/null

  local waited=0
  while [ "$waited" -lt 60 ]; do
    if curl -sf "http://127.0.0.1:$BRIDGE_PORT/health" >/dev/null 2>&1; then
      say "the bridge is up"
      curl -s "http://127.0.0.1:$BRIDGE_PORT/health"; echo
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  warn "the bridge did not answer in ${waited}s; the last lines:"
  tail -20 "$LOG" >&2
  return 1
}

cmd_stop() {
  local pids
  pids="$(bot_pids)"
  if [ -z "$pids" ]; then
    say "the bridge is not running"
    return 0
  fi
  say "stopping the bridge"
  for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done
  local waited=0
  while [ "$waited" -lt 20 ]; do
    pids="$(bot_pids)"
    [ -z "$pids" ] || { sleep 1; waited=$((waited + 1)); continue; }
    say "the bridge stopped"
    return 0
  done
  for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
  return 1
}

cmd_status() {
  local pids up="no"
  pids="$(bot_pids)"
  [ -n "$pids" ] && up="yes"
  printf 'bridge running : %s\n' "$up"
  printf 'bridge address : 127.0.0.1:%s\n' "$BRIDGE_PORT"
  printf 'world address  : %s:%s (the private world)\n' "$GYM_HOST" "$GYM_PORT"
  printf 'log            : %s\n' "$LOG"
  if [ "$up" = "yes" ]; then
    printf 'pid            : %s\n' "$(echo "$pids" | tr '\n' ' ')"
    curl -s "http://127.0.0.1:$BRIDGE_PORT/health" 2>/dev/null; echo
  fi
}

cmd_logs() {
  tail -n "${1:-40}" "$LOG" 2>/dev/null || echo "no log yet at $LOG"
}

case "${1:-}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  logs)   cmd_logs "${2:-40}" ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac
