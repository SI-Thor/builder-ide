#!/usr/bin/env bash
# The measured run: the Voyager loop against the private Minecraft
# sandbox, with every model call's tokens on the log.
#
# Usage:
#   bash docs/lab/voyager-port-scripts/run_measurement.sh            # detached
#   bash docs/lab/voyager-port-scripts/run_measurement.sh --foreground
#
# What it needs: the sandbox up on 127.0.0.1:25600, a DeepInfra key in
# the house secrets file, and the seat's venv. How long it takes:
# VOYAGER_HOURS of world time (default 0.7), or until the step or
# token limit stops it.
set -euo pipefail

REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
ADMIT="${THOR_ADMIT:-$HOME/lm-tools/thor-admit}"
OUT="${VOYAGER_OUT:-$REPO/docs/lab/voyager-port-scripts/results}"
HOURS="${VOYAGER_HOURS:-0.7}"
STEPS="${VOYAGER_STEPS:-90}"
TOKENS="${VOYAGER_TOKENS:-3000000}"

cd "$REPO"
mkdir -p "$OUT"
LOG="$OUT/minecraft-run.log"

export HOURS STEPS TOKENS OUT

run() {
  .venv/bin/python docs/lab/voyager-port-scripts/run_voyager.py \
    --world minecraft \
    --hours "$HOURS" \
    --max-steps "$STEPS" \
    --max-tokens "$TOKENS" \
    --out "$OUT"
}

if [ "${1:-}" = "--foreground" ]; then
  exec "$ADMIT" exec -- bash -c "$(declare -f run); cd '$REPO'; run"
fi

printf '\033[1m==>\033[1m starting the measured run: %s hours, %s steps, %s tokens\n' \
  "$HOURS" "$STEPS" "$TOKENS"
setsid nohup "$ADMIT" exec -- bash -c \
  "$(declare -f run); cd '$REPO'; run" > "$LOG" 2>&1 < /dev/null &
echo "launched at $(date +%H:%M:%S); the log is $LOG"
