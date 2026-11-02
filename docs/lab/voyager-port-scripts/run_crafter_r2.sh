#!/usr/bin/env bash
# Round 2's crafter run: the loop with the spatial fact, run until
# skills are admitted or the budget stops it (the brief asks for
# "until skills are admitted"; the wall and token caps are the honest
# fallback if none are).
#
# Usage:
#   bash docs/lab/voyager-port-scripts/run_crafter_r2.sh   # foreground
#
# Detach it with:  setsid -f nohup bash .../run_crafter_r2.sh \
#                      > .../results/crafter-r2-launch.log 2>&1 < /dev/null
#
# What it needs: the seat's venv and a DeepInfra key in the house
# secrets file. How long it takes: VOYAGER_HOURS (default 4).
set -euo pipefail

REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
ADMIT="${THOR_ADMIT:-$HOME/lm-tools/thor-admit}"
OUT="${VOYAGER_OUT:-$REPO/docs/lab/voyager-port-scripts/results/crafter-r2}"
HOURS="${VOYAGER_HOURS:-4}"
STEPS="${VOYAGER_STEPS:-200}"
TOKENS="${VOYAGER_TOKENS:-3000000}"

cd "$REPO"
mkdir -p "$OUT"
exec "$ADMIT" exec -- .venv/bin/python docs/lab/voyager-port-scripts/run_voyager.py \
  --world crafter \
  --hours "$HOURS" \
  --max-steps "$STEPS" \
  --max-tokens "$TOKENS" \
  --out "$OUT"
