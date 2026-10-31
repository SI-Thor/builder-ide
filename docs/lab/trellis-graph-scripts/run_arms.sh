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
#
# **The box's memory rule** (every seat, after the box filled its 122 GB on
# 2026-10-31 and went down): a heavy step runs under the box's lock
# (``~/lm-wt/heavy.lock``), one heavy step at a time, and only when the box
# has room for it — 25 GB spare after the step's expected peak.  An arm's
# process peaks near 16 GB (the weights — twice in fp8 staging — plus the
# activations' reserve and the process's RSS), so an arm waits until at
# least ~41 GB is available, and queues on the lock behind whichever heavy
# step (this seat's or another seat's) got there first.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROUNDS="${1:-2}"
shift || true
SEEDS=("$@")
[[ ${#SEEDS[@]} -eq 0 ]] && SEEDS=(101 102)

HEAVY_LOCK="${HEAVY_LOCK:-$HOME/lm-wt/heavy.lock}"
EXPECTED_PEAK_GB=16
SPARE_GB=25
NEED_GB=$((EXPECTED_PEAK_GB + SPARE_GB))
WAIT_SECONDS="${HEAVY_WAIT_SECONDS:-1800}"

available_gb() {
  free -g | awk '/^Mem:/{print $7}'
}

wait_for_room() {
  local waited=0
  while true; do
    local avail
    avail="$(available_gb)"
    [[ "$avail" -ge "$NEED_GB" ]] && return 0
    if [[ "$waited" -ge "$WAIT_SECONDS" ]]; then
      echo "!! only ${avail} GB available (need ${NEED_GB}); waited ${WAIT_SECONDS}s — giving up" >&2
      return 1
    fi
    echo "   box has ${avail} GB free, waiting for ${NEED_GB} (${waited}s so far)..."
    sleep 60
    waited=$((waited + 60))
  done
}

for ROUND in $(seq 1 "$ROUNDS"); do
  for ARM in bf16 fp8-fixed fp8-declined; do
    echo "################ round $ROUND: $ARM  ($(date -u +%H:%M:%SZ))"
    export TRG_SUFFIX="-r$ROUND"
    wait_for_room
    flock -w "$WAIT_SECONDS" "$HEAVY_LOCK" \
      "$HERE/run_experiment.sh" "$ARM" "${SEEDS[@]}" || echo "!! $ARM round $ROUND failed"
  done
done
echo "################ all rounds done ($(date -u +%H:%M:%SZ))"
