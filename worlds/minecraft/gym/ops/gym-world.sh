#!/usr/bin/env bash
# gym/ops/gym-world.sh — the private world the gym plays in.
#
#   gym-world.sh setup    copy the server from the world's runtime/ and
#                         render the private configuration (new world,
#                         port 25630, 127.0.0.1, offline mode)
#   gym-world.sh start    start it, detached, under the admission daemon
#   gym-world.sh stop     stop it cleanly (the world saves, then exits)
#   gym-world.sh status   is it up, on what port, with how much memory
#   gym-world.sh logs [n] the last n lines of the world's log
#
# The rules this script exists to keep:
#
# * **never the live server.** The live world is 25565 and its world is
#   the community's. This one is 25630, on 127.0.0.1, with a world of its
#   own (a new seed, generated here). The port is not 25600 (voyager-port's
#   sandbox) and not 25610 (world-snapshot's).
# * **never the live world's data.** The server directory is copied with
#   every ``world*`` directory left behind, so the private world is
#   generated fresh and the community's terrain is never touched.
# * **the door is the admission daemon.** The server runs under
#   ``thor-admit run --tier live --peak 3G``: the memory it takes is
#   reserved honestly, like any other seat's work.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$REPO/runtime"
SANDBOX="$RUNTIME/mc-sandbox"
LOG_DIR="$RUNTIME/logs"
LOG="$LOG_DIR/gym-paper.log"
PID_FILE="$RUNTIME/gym-world.pid"

GYM_PORT="${AW_GYM_PORT:-25630}"
GYM_SEED="${AW_GYM_SEED:-agent-world-gym}"
GYM_XMX="${AW_GYM_XMX:-2G}"
GYM_XMS="${AW_GYM_XMS:-512M}"
GYM_PEAK="${AW_GYM_PEAK:-3G}"

# The world's own runtime: where the Paper build, the JDK and the live
# skill library live. The gym copies from here and never writes back.
SOURCE_RUNTIME="${AW_SOURCE_RUNTIME:-$HOME/lm-wt/agent-world/runtime}"
PAPER_JAR="${AW_PAPER_JAR:-$SOURCE_RUNTIME/dl/paper-26.1.2-74.jar}"
JDK="${AW_JDK:-$SOURCE_RUNTIME/jdk-25}"
THOR_ADMIT="${AW_THOR_ADMIT:-$HOME/lm-tools/thor-admit}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

running_pids() {
  # The world's own command line does not carry the sandbox: the server
  # is started with `cd $SANDBOX && exec java -jar ...`, so the path is in
  # the process's **working directory**, not in its arguments. Reading
  # /proc/*/cwd is what finds it; matching the jar's command line would
  # find the community's world and voyager-port's sandbox too.
  local pid cwd
  for pid in /proc/[0-9]*; do
    pid="${pid#/proc/}"
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    case "$cwd" in
      "$SANDBOX") echo "$pid" ;;
    esac
  done
}

# --- the private configuration ------------------------------------------------

render_properties() {
  cat > "$SANDBOX/server.properties" <<EOF
# agent-world-gym: the private world. A world of its own, on loopback.
#
# Copied from the world's runtime/ and re-rendered for the lab. The live
# server is 25565 and the community's world is its own; this one is
# 25630, on 127.0.0.1, and its world is generated here from its own seed.
server-ip=127.0.0.1
server-port=$GYM_PORT

# No accounts: the bot joins in offline mode, and the world is on
# loopback, so nothing outside this box can reach it.
online-mode=false
white-list=false
enforce-whitelist=false
enable-status=false
enable-query=false
enable-rcon=false
motd=agent-world-gym (private lab)

# The world's own shape.
level-name=world
level-seed=$GYM_SEED
level-type=minecraft\:normal
generate-structures=true
difficulty=peaceful
spawn-monsters=false
pvp=false
gamemode=survival
allow-flight=false
spawn-protection=0
max-players=4

# The budget: a lab world, not the community's world.
view-distance=8
simulation-distance=6
network-compression-threshold=256
sync-chunk-writes=false
player-idle-timeout=0
enable-command-block=false
enable-jmx-monitoring=false
use-native-transport=true
rate-limit=0
EOF
  echo "eula=true" > "$SANDBOX/eula.txt"
}

# --- the setup ----------------------------------------------------------------

cmd_setup() {
  [ -f "$PAPER_JAR" ] || die "no Paper jar at $PAPER_JAR"
  [ -x "$JDK/bin/java" ] || die "no JDK at $JDK"

  mkdir -p "$RUNTIME" "$LOG_DIR"
  local pids
  pids="$(running_pids)"
  [ -z "$pids" ] || die "the private world is already running (pid $pids); stop it first"

  say "copying the server from $SOURCE_RUNTIME/paper (no world, no plugins)"
  rm -rf "$SANDBOX"
  mkdir -p "$SANDBOX"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude 'world*' --exclude 'plugins' --exclude 'logs/' \
      "$SOURCE_RUNTIME/paper/" "$SANDBOX/"
  else
    cp -a "$SOURCE_RUNTIME/paper/." "$SANDBOX/"
    rm -rf "$SANDBOX"/world* "$SANDBOX"/plugins
    rm -rf "$SANDBOX"/logs
  fi
  mkdir -p "$SANDBOX/logs"

  # The live world's world directories never come along.
  local leftover
  leftover="$(find "$SANDBOX" -maxdepth 1 -name 'world*' -print)"
  [ -z "$leftover" ] || die "a world directory came along from the source: $leftover"

  render_properties
  say "the private world is configured: 127.0.0.1:$GYM_PORT, seed $GYM_SEED, offline"

  # The library: a snapshot of the world's own skill library, taken once.
  # The gym reads its snapshot; the live library keeps living.
  if [ -d "$SOURCE_RUNTIME/skills" ]; then
    say "snapshotting the skill library ($(ls "$SOURCE_RUNTIME/skills" | wc -l) skills)"
    rm -rf "$RUNTIME/skills"
    mkdir -p "$RUNTIME/skills"
    cp -a "$SOURCE_RUNTIME/skills/." "$RUNTIME/skills/"
    ( cd "$RUNTIME/skills" && sha256sum ./*.json | sha256sum | awk '{print $1}' > ../skills.sha256 )
    say "the snapshot's fingerprint: $(cat "$RUNTIME/skills.sha256")"
  else
    warn "no skill library at $SOURCE_RUNTIME/skills — the gym will have no options"
  fi

  # mineflayer: the world's own installed copy, shared read-only. A
  # second install would be 269 packages of duplication for nothing.
  if [ ! -e "$REPO/bots/node_modules" ]; then
    say "linking the world's node_modules (mineflayer) into the gym checkout"
    ln -s "$REPO/../agent-world/bots/node_modules" "$REPO/bots/node_modules" 2>/dev/null \
      || ln -s "$SOURCE_RUNTIME/../bots/node_modules" "$REPO/bots/node_modules" \
      || warn "could not link node_modules; install it with: cd bots && npm install"
  fi
}

# --- the start ----------------------------------------------------------------

cmd_start() {
  [ -d "$SANDBOX" ] || die "the private world is not set up — run: gym-world.sh setup"
  [ -f "$PAPER_JAR" ] || die "no Paper jar at $PAPER_JAR"

  local pids
  pids="$(running_pids)"
  if [ -n "$pids" ]; then
    say "the private world is already running (pid $pids)"
    return 0
  fi

  # Never two copies of the lab world at once.
  if pgrep -af "[g]ym-bot.js" >/dev/null 2>&1; then
    warn "a gym bot is already running:"
    pgrep -af "[g]ym-bot.js" >&2
  fi

  mkdir -p "$LOG_DIR"
  local offset=0
  [ -f "$LOG" ] && offset="$(wc -c < "$LOG")"

  say "starting the private world on 127.0.0.1:$GYM_PORT (under thor-admit, peak $GYM_PEAK)"
  setsid -f nohup "$THOR_ADMIT" run --tier live --peak "$GYM_PEAK" \
    --label agent-world-gym.mc -- \
    bash -c "cd '$SANDBOX' && exec nice -n 10 '$JDK/bin/java' -Xms$GYM_XMS -Xmx$GYM_XMX -XX:+UseG1GC -XX:MaxGCPauseMillis=100 -Dcom.mojang.eula.agree=true -jar '$PAPER_JAR' --nogui" \
    > "$LOG" 2>&1 < /dev/null

  local waited=0
  while [ "$waited" -lt 240 ]; do
    if tail -c "+$((offset + 1))" "$LOG" 2>/dev/null | grep -q 'Done ('; then
      say "the private world is up"
      cmd_status
      return 0
    fi
    if ! running_pids >/dev/null && [ "$waited" -gt 20 ]; then
      warn "the world exited during start-up; the last lines:"
      tail -30 "$LOG" >&2
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
  warn "the world did not finish starting within ${waited}s; it may still be generating"
  tail -20 "$LOG" >&2
  return 1
}

# --- the stop -----------------------------------------------------------------

cmd_stop() {
  local pids
  pids="$(running_pids)"
  if [ -z "$pids" ]; then
    say "the private world is not running"
    return 0
  fi
  say "asking the private world to stop (it saves, then exits)"
  for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done
  local waited=0
  while [ "$waited" -lt 60 ]; do
    pids="$(running_pids)"
    [ -z "$pids" ] || { sleep 1; waited=$((waited + 1)); continue; }
    say "the private world stopped"
    return 0
  done
  warn "the world did not stop in ${waited}s; ending it"
  for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
  return 1
}

# --- the status ---------------------------------------------------------------

cmd_status() {
  local pids up="no"
  pids="$(running_pids)"
  [ -n "$pids" ] && up="yes"
  printf 'world running : %s\n' "$up"
  printf 'address       : 127.0.0.1:%s (java/tcp, loopback only)\n' "$GYM_PORT"
  printf 'server dir    : %s\n' "$SANDBOX"
  printf 'seed          : %s (a new world, generated here)\n' "$GYM_SEED"
  printf 'heap cap      : %s\n' "$GYM_XMX"
  if [ "$up" = "yes" ]; then
    printf 'pid           : %s\n' "$(echo "$pids" | tr '\n' ' ')"
    local rss
    rss="$(ps -eo rss,args | grep -F "$SANDBOX" | grep '[j]ava' | awk '{s+=$1} END {printf "%.0f", s/1024}')"
    printf 'resident (MB) : %s\n' "${rss:-?}"
  fi
  printf 'log           : %s\n' "$LOG"
}

cmd_logs() {
  tail -n "${1:-40}" "$LOG" 2>/dev/null || echo "no log yet at $LOG"
}

case "${1:-}" in
  setup)  cmd_setup ;;
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  logs)   cmd_logs "${2:-40}" ;;
  *) sed -n '2,22p' "$0"; exit 1 ;;
esac
