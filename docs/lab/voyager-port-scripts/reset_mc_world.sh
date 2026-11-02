#!/usr/bin/env bash
# Put the private sandbox back into a known state, and start it again.
#
# A measurement wants a world it can name: the same seed, the same
# spawn, an empty inventory. The run before it left a bot in a hole it
# had dug, with sand in its pack and its position saved in the world's
# player data, so the next run started somewhere else. This script
# stops the sandbox, moves the old world aside (it is kept, not
# deleted, so a run can be looked at afterwards), and starts the server
# again on the same port with the same seed.
#
# Usage:
#   bash docs/lab/voyager-port-scripts/reset_mc_world.sh
#
# What it needs: the sandbox made by setup_mc_sandbox.sh, and the
# runtime's JDK 25. How long it takes: about a minute, most of it the
# server generating the world.
set -euo pipefail

REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
SANDBOX="${VOYAGER_SANDBOX:-$REPO/mc-sandbox}"
PORT="${VOYAGER_MC_PORT:-25600}"

say() { printf '\033[1m==>\033[1m %s\n' "$*"; }
die() { printf '\033[31mxx\033[1m %s\n' "$*" >&2; exit 1; }

[ -d "$SANDBOX" ] || die "no sandbox at $SANDBOX; run setup_mc_sandbox.sh first"

say "stopping the sandbox server, if it is up"
if command -v pgrep >/dev/null 2>&1; then
  for pid in $(pgrep -f "paper-.*\.jar --nogui" || true); do
    # Only the sandbox's own server: the live agent-world server runs
    # from its own directory and must not be touched.
    if tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "$SANDBOX"; then
      say "stopping pid $pid"
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for _ in $(seq 1 30); do
    if ss -ltn 2>/dev/null | grep -q ":$PORT "; then sleep 1; else break; fi
  done
fi

if [ -d "$SANDBOX/world" ]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  say "moving the old world to $SANDBOX/world.$STAMP (kept, not deleted)"
  mv "$SANDBOX/world" "$SANDBOX/world.$STAMP"
fi

say "starting the sandbox again"
bash "$REPO/docs/lab/voyager-port-scripts/start_mc_sandbox.sh" --detach

say "waiting for the port to open"
for _ in $(seq 1 90); do
  if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    say "the sandbox is up on 127.0.0.1:$PORT"
    exit 0
  fi
  sleep 2
done
die "the sandbox did not open port $PORT in three minutes"
