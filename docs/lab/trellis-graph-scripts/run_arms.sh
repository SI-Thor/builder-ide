#!/usr/bin/env bash
# =============================================================================
# The fp8 arms, interleaved.
#
#   run_arms.sh [rounds] [seeds...]
#
# The box is shared: the seed sweep and other seats' work move the numbers
# under the measurement, and they move them by different amounts at
# different times.  So the arms are **interleaved** rather than run one
# after another: bf16, then fp8-fixed, then fp8-declined, then round again.
# A drift in the box's load then lands on every arm about equally, instead
# of landing on whichever arm happened to run while the box was busy.
#
# Each arm is still one ComfyUI process (the arm runner's rule), and each
# round writes its own files (``$ARM-r1-...``), so nothing is overwritten.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROUNDS="${1:-2}"
shift || true
SEEDS=("$@")
[[ ${#SEEDS[@]} -eq 0 ]] && SEEDS=(101 102)

for ROUND in $(seq 1 "$ROUNDS"); do
  for ARM in bf16 fp8-fixed fp8-declined; do
    echo "################ round $ROUND: $ARM  ($(date -u +%H:%M:%SZ))"
    export TRG_SUFFIX="-r$ROUND"
    "$HERE/run_experiment.sh" "$ARM" "${SEEDS[@]}" || echo "!! $ARM round $ROUND failed"
  done
done
echo "################ all rounds done ($(date -u +%H:%M:%SZ))"
