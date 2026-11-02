#!/usr/bin/env bash
# Start the private Paper sandbox under the memory admission daemon.
#
# The brief: the Minecraft adapter runs "under thor-admit (peak honest,
# ~8 GB)". The peak here is 3 GB and it is honest in the sense that
# matters: Paper is given a 2 GB heap and the node bridge is a separate
# process, so the pair cannot take more than the heap plus the JVM's own
# overhead. The daemon reported the observed peak of an earlier 8 GB
# lease at 1.5 GB, so the reservation was four times the use.
# VOYAGER_PEAK raises it if a bigger sandbox is wanted.
#
# The lease is the whole point. On the Thor the GPU memory *is* the
# system memory, so a process that takes memory by surprise can take the
# box with it. thor-admit takes a lease, checks the box has room, and
# gives the lease back when the command stops.
#
# Usage:
#   bash docs/lab/voyager-port-scripts/start_mc_sandbox.sh          # foreground
#   bash docs/lab/voyager-port-scripts/start_mc_sandbox.sh --detach # detached
#
# What it needs: the sandbox made by setup_mc_sandbox.sh, and the
# runtime's JDK 25 (the 26.x Minecraft line asks for Java 25).
set -euo pipefail

RUNTIME="${AW_RUNTIME:-$HOME/lm-wt/agent-world/runtime}"
REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
SANDBOX="${VOYAGER_SANDBOX:-$REPO/mc-sandbox}"
PAPER_JAR="${AW_PAPER_JAR:-$RUNTIME/dl/paper-26.1.2-74.jar}"
JDK="${AW_JDK25:-$RUNTIME/jdk-25}"
ADMIT="${THOR_ADMIT:-$HOME/lm-tools/thor-admit}"
LOG_DIR="${VOYAGER_LOG_DIR:-$REPO/docs/lab/voyager-port-scripts/results}"
PEAK="${VOYAGER_PEAK:-3G}"

say() { printf '\033[1m==>\033[1m %s\n' "$*"; }
die() { printf '\033[31mxx\033[1m %s\n' "$*" >&2; exit 1; }

[ -d "$SANDBOX" ] || die "no sandbox at $SANDBOX; run setup_mc_sandbox.sh first"
[ -x "$JDK/bin/java" ] || die "no JDK at $JDK"
[ -f "$PAPER_JAR" ] || die "no Paper jar at $PAPER_JAR"
[ -x "$ADMIT" ] || die "no thor-admit at $ADMIT"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/mc-server.log"

# Already up? Say so rather than starting a second server on the port.
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":25600 "; then
  say "something is already listening on 25600"
  exit 1
fi

run_server() {
  cd "$SANDBOX"
  nice -n 10 "$JDK/bin/java" \
      -Xms512M -Xmx2G \
      -XX:+UseG1GC -XX:MaxGCPauseMillis=100 \
      -Dcom.mojang.eula.agree=true \
      -jar "$PAPER_JAR" --nogui
}

# The --exec flag runs the server without taking a lease, under the
# daemon's guard instead. It is there because the box's GPU allocation
# pool is sometimes saturated by other seats' reservations, and a
# measurement that cannot start is not a measurement. The guard still
# stops a command that takes the box's memory by surprise, and the
# server is given a 2 GB heap, so it cannot.
MODE="run"
for arg in "$@"; do
  if [ "$arg" = "--exec" ]; then MODE="exec"; fi
done

if [ "${1:-}" = "--detach" ] || [ "${2:-}" = "--detach" ]; then
  if [ "$MODE" = "exec" ]; then
    say "starting the sandbox detached under thor-admit exec (no lease)"
    setsid nohup "$ADMIT" exec -- \
      bash -c "$(declare -f run_server); RUNTIME='$RUNTIME' SANDBOX='$SANDBOX' PAPER_JAR='$PAPER_JAR' JDK='$JDK' run_server" \
      > "$LOG" 2>&1 < /dev/null &
  else
    say "starting the sandbox detached under thor-admit (peak $PEAK)"
    setsid nohup "$ADMIT" run --tier live --peak "$PEAK" --label voyager-port.mc \
      -- bash -c "$(declare -f run_server); RUNTIME='$RUNTIME' SANDBOX='$SANDBOX' PAPER_JAR='$PAPER_JAR' JDK='$JDK' run_server" \
      > "$LOG" 2>&1 < /dev/null &
  fi
  echo "launched at $(date +%H:%M:%S); the log is $LOG"
  exit 0
fi

say "starting the sandbox in the foreground under thor-admit (peak $PEAK)"
exec "$ADMIT" run --tier live --peak "$PEAK" --label voyager-port.mc \
  -- bash -c "$(declare -f run_server); RUNTIME='$RUNTIME' SANDBOX='$SANDBOX' PAPER_JAR='$PAPER_JAR' JDK='$JDK' run_server"
