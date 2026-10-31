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

# -- the box's state, sampled beside the stage --------------------------------
echo
echo "=== the box's state, beside the numbers ==="
.venv/bin/python "$HERE/stage_box.py" --out "$LOGDIR/vlm-stage-box.json" &
BOX_PID=$!
trap 'kill $BOX_PID 2>/dev/null || true; cleanup' EXIT

# -- the hybrid ----------------------------------------------------------------
# First, because the hybrid is what the pick rests on: it is eight model
# calls (the two escalated members and the six clean controls), while the
# captions are twenty-one long ones. If the stage has to be cut short, the
# hybrid's table is the one that must exist.
echo
echo "=== the hybrid: the checks first, the model on the out-of-band class ==="
.venv/bin/python "$HERE/score_set.py" --candidate hybrid --set delegate=vlm 2>&1 \
  | tee "$LOGDIR/hybrid-run.log"

# -- the captions ---------------------------------------------------------------
echo
echo "=== the VLM's descriptions of the frames ==="
.venv/bin/python "$HERE/caption_frames.py" 2>&1 | tee "$LOGDIR/captions-run.log"

# -- done ----------------------------------------------------------------------
kill "$BOX_PID" 2>/dev/null || true
wait "$BOX_PID" 2>/dev/null || true
echo
echo "=== the box during this stage ==="
cat "$LOGDIR/vlm-stage-box.json" 2>/dev/null || echo "(the box capture did not finish)"
free -g | sed -n '2p'
