#!/usr/bin/env bash
# The VLM stage of the bake-off, under the box's shared heavy lock.
#
#   bash docs/lab/critic-select-scripts/run_vlm_stage.sh
#
# One model server, one lock, one job: start the local VLM, wait for it, make
# the captions the Jev arms need, score the hybrid (the checks first, the model
# on the out-of-band class), then stop the server. The server is stopped even
# if a step fails — the box is shared and a resident 17 GB model is the whole
# point of the lock.
#
# The lock is the box's rule: one heavy step at a time, and the peak memory
# is recorded beside the numbers.
set -uo pipefail

HERE="$(dirname "$0")"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

export CRITIC_BLENDER_PYTHON="${CRITIC_BLENDER_PYTHON:-$HOME/src/infinigen-thor/.venv/bin/python}"

LOGDIR="$HERE/results"
mkdir -p "$LOGDIR"

SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "stopped the VLM (pid $SERVER_PID)"
  fi
}
trap cleanup EXIT

# -- the box's state, before ---------------------------------------------------
echo "=== the box before ==="
free -g | sed -n '2p'

# -- start the model server ----------------------------------------------------
bash "$HERE/start_vlm.sh"
SERVER_PID=$(pgrep -f "llama-server.*--port 8123" | head -1)
if [ -z "$SERVER_PID" ]; then
  echo "! the VLM server did not start"
  exit 1
fi
echo "waiting for the VLM (pid $SERVER_PID) to answer..."
READY=0
for _ in $(seq 1 120); do
  if curl -sf http://127.0.0.1:8123/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 5
done
if [ "$READY" != "1" ]; then
  echo "! the VLM did not come up in time"
  tail -30 "$LOGDIR/vlm-server.log"
  exit 1
fi
echo "the VLM is up"

# -- the peak memory sampler ---------------------------------------------------
PEAK_FILE="$LOGDIR/vlm-stage-peak.json"
(
  peak_used=0
  peak_avail=122
  while true; do
    read -r used avail <<<"$(free -g | awk 'NR==2 {print $3, $7}')"
    [ "${used:-0}" -gt "$peak_used" ] && peak_used=$used
    [ "${avail:-0}" -lt "$peak_avail" ] && peak_avail=$avail
    printf '{"peak_used_gb": %s, "min_available_gb": %s}\n' "$peak_used" "$peak_avail" > "$PEAK_FILE"
    sleep 3
  done
) &
SAMPLER_PID=$!

# -- the captions ---------------------------------------------------------------
echo
echo "=== the VLM's descriptions of the frames ==="
.venv/bin/python "$HERE/caption_frames.py" 2>&1 | tee "$LOGDIR/captions-run.log"

# -- the hybrid ----------------------------------------------------------------
echo
echo "=== the hybrid: the checks first, the model on the out-of-band class ==="
.venv/bin/python "$HERE/score_set.py" --candidate hybrid --set delegate=vlm 2>&1 \
  | tee "$LOGDIR/hybrid-run.log"

# -- done ----------------------------------------------------------------------
kill "$SAMPLER_PID" 2>/dev/null || true
echo
echo "=== the box's peak memory during this stage ==="
cat "$PEAK_FILE"
free -g | sed -n '2p'
