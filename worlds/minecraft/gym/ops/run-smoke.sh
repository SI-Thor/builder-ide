#!/usr/bin/env bash
# gym/ops/run-smoke.sh — run the smoke experiment.
#
#   run-smoke.sh [args...]      the experiment (see gym/scripts/smoke.py --help)
#
# The environment is set here rather than at the call site, because two of
# them are rules and not preferences:
#
# * ``XLA_PYTHON_CLIENT_PREALLOCATE=false`` — Minari pulls jax, and on the
#   Thor the GPU's memory is the box's memory (the 13:22 OOM).
# * the datasets and the reports go under ``runtime/``, which is the
#   world's re-creatable state and not in git.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export MINARI_DATASETS_PATH="${MINARI_DATASETS_PATH:-$REPO/runtime/datasets}"

mkdir -p "$REPO/runtime/logs" "$REPO/runtime/datasets" "$REPO/runtime/reports"

# ``--detach`` starts the experiment in its own session and returns at
# once, so a long run never holds an ssh open (the box's rule: start it
# detached, then wait with one sleep between checks).
if [ "${1:-}" = "--detach" ]; then
  shift
  LOG="$REPO/runtime/logs/smoke.log"
  setsid -f nohup "$REPO/.venv/bin/python" "$REPO/gym/scripts/smoke.py" "$@" \
    > "$LOG" 2>&1 < /dev/null
  echo "the experiment is running; its log is at $LOG"
  exit 0
fi

exec "$REPO/.venv/bin/python" "$REPO/gym/scripts/smoke.py" "$@"
