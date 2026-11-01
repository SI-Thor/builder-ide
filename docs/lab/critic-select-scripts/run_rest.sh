#!/usr/bin/env bash
# The rest of the bake-off, in one go: the captions, the hybrid, Jev's arms.
#
#   bash docs/lab/critic-select-scripts/run_rest.sh
#
# The order matters: the captions come from the local VLM, and Jev's
# description arms need them.
set -euo pipefail

HERE="$(dirname "$0")"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

export CRITIC_BLENDER_PYTHON="${CRITIC_BLENDER_PYTHON:-$HOME/src/infinigen-thor/.venv/bin/python}"

echo "=== the VLM's descriptions of the frames ==="
.venv/bin/python "$HERE/caption_frames.py"

echo
echo "=== the hybrid: the checks first, the model on the out-of-band class ==="
.venv/bin/python "$HERE/score_set.py" --candidate hybrid --set delegate=vlm

echo
echo "=== Jev: the brief's arm (description and measurements) ==="
.venv/bin/python "$HERE/run_jev.py" --arm verify \
  --measurements --captions "$HERE/results/captions.json"

echo
echo "=== Jev: the classify arm, with the measurements ==="
.venv/bin/python "$HERE/run_jev.py" --arm classify \
  --measurements --captions "$HERE/results/captions.json"

echo
echo "=== Jev: description only ==="
.venv/bin/python "$HERE/run_jev.py" --arm verify \
  --captions "$HERE/results/captions.json"

echo
echo "=== Jev: classify, description only ==="
.venv/bin/python "$HERE/run_jev.py" --arm classify \
  --captions "$HERE/results/captions.json"
echo
echo "done"
