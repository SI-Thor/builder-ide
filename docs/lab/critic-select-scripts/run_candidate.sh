#!/usr/bin/env bash
# Run one candidate of the bake-off over the reference set.
#
#   bash docs/lab/critic-select-scripts/run_candidate.sh vlm
#
# The run writes its result to docs/lab/critic-select-scripts/results/<name>.json
# and its log next to it.
set -euo pipefail

NAME="${1:-scripted}"
HERE="$(dirname "$0")"
ROOT="$(cd "$HERE/../../.." && pwd)"

export CRITIC_BLENDER_PYTHON="${CRITIC_BLENDER_PYTHON:-$HOME/src/infinigen-thor/.venv/bin/python}"

cd "$ROOT"
exec .venv/bin/python "$HERE/score_set.py" --candidate "$NAME"
