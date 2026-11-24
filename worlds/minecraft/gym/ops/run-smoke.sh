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
# The python that runs the smoke. The gym used to have its own venv at
# the root of its own repository; it is now the world's runtime venv,
# with the old path and the system python as fallbacks.
PY="${AW_GYM_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in "$REPO/runtime/venv/bin/python" "$REPO/.venv/bin/python"; do
    if [ -x "$candidate" ]; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ]; then PY="$(command -v python3 || true)"; fi
[ -n "$PY" ] || { echo "no python for the smoke: install one, or set AW_GYM_PYTHON" >&2; exit 1; }
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export MINARI_DATASETS_PATH="${MINARI_DATASETS_PATH:-$REPO/runtime/datasets}"

mkdir -p "$REPO/runtime/logs" "$REPO/runtime/datasets" "$REPO/runtime/reports"

# ``--detach`` starts the experiment in its own session and returns at
# once, so a long run never holds an ssh open (the box's rule: start it
# detached, then wait with one sleep between checks).
if [ "${1:-}" = "--detach" ]; then
  shift
  LOG="$REPO/runtime/logs/smoke.log"
  setsid -f nohup "$PY" "$REPO/gym/scripts/smoke.py" "$@" \
    > "$LOG" 2>&1 < /dev/null
  echo "the experiment is running; its log is at $LOG"
  exit 0
fi

exec "$PY" "$REPO/gym/scripts/smoke.py" "$@"
