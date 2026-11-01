#!/usr/bin/env bash
# The local decision model's stage of the bake-off.
#
#   bash docs/lab/critic-delegate-scripts/run_d1_stage.sh
#
# One model server, one job: start the local decision model, wait for it,
# score the reference set with it (alone, and as the hybrid's delegate), then
# stop the server. The server is stopped even if a step fails — the box is
# shared, and a resident model is the whole point of that.
#
# **The lock is the caller's.** This stage's server is 2 GB of a 122 GB box
# — a decision model, not a heavy step — so it does not take the shared heavy
# lock itself; a caller that wants it queued behind the other seats' heavy
# work runs it as ``flock ~/lm-wt/heavy.lock bash run_d1_stage.sh``. The
# memory rule's floor (≥ 25 GB free) is checked here either way, and the
# box's state is printed beside the numbers.
set -uo pipefail

HERE="$(dirname "$0")"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

PY="${PY:-$HOME/lm-wt/critic-select/.venv/bin/python}"
export CRITIC_BLENDER_PYTHON="${CRITIC_BLENDER_PYTHON:-$HOME/src/infinigen-thor/.venv/bin/python}"

RESULTS="$HERE/results"
mkdir -p "$RESULTS"

SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "stopped the local decision model (pid $SERVER_PID)"
  fi
}
trap cleanup EXIT

echo "=== the box before ==="
free -g | sed -n '2p'
FREE=$(free -g | awk 'NR==2 {print $7}')
if [ "${FREE:-0}" -lt 25 ]; then
  echo "! only ${FREE} GiB free — the memory rule's floor is 25 GiB"
  exit 1
fi

bash "$HERE/start_d1.sh"
SERVER_PID=$(pgrep -f "llama-server.*--port 8131" | head -1)
if [ -z "$SERVER_PID" ]; then
  echo "! the decision model's server did not start"
  exit 1
fi
READY=0
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8131/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
if [ "$READY" != "1" ]; then
  echo "! the decision model did not come up in time"
  tail -30 "$RESULTS/d1-server.log"
  exit 1
fi
echo "the decision model is up"

"$PY" "$HERE/score_set.py" --candidate d1 2>&1 | tee "$RESULTS/d1.log"
"$PY" "$HERE/score_set.py" --candidate hybrid --set delegate=d1 --name hybrid-d1 2>&1 \
  | tee "$RESULTS/hybrid-d1.log"

echo "=== the box after ==="
free -g | sed -n '2p'
