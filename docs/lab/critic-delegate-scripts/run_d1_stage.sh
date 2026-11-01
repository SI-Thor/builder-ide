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
# **The admission daemon is the caller's.** The stage itself takes a lease
# with `thor-admit run` (the memory rule), and the model server takes one of
# its own with `thor-admit serve` (a model is loaded once per box). The
# stage does not take the old shared flock: that is the stopgap for when the
# daemon's binary is missing, not the default.
#
# The endpoint is **read back** from the daemon rather than assumed: if
# another seat already has d1-2B answering, the daemon hands back its port
# and starts nothing, and the stage talks to that one.
set -uo pipefail

HERE="$(dirname "$0")"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

PY="${PY:-$ROOT/.venv/bin/python}"
ADMIT="${ADMIT:-$HOME/lm-tools/thor-admit}"
export CRITIC_BLENDER_PYTHON="${CRITIC_BLENDER_PYTHON:-$HOME/src/infinigen-thor/.venv/bin/python}"

RESULTS="$HERE/results"
mkdir -p "$RESULTS"

REQUESTED_PORT="${PORT:-8131}"
SERVE_PID=""
OWNED=0
cleanup() {
  # Only a server **we** started is ours to stop. If another seat already had
  # d1-2B answering, the daemon handed back its port and started nothing, so
  # there is nothing of ours to kill.
  if [ "$OWNED" != "1" ] || [ -z "$SERVE_PID" ]; then
    return
  fi
  # The serve command holds the lease, and the daemon terminates the
  # server's process group when the lease ends; the kill below makes that
  # prompt rather than waiting for the daemon's watchdog.
  kill "$SERVE_PID" 2>/dev/null || true
  wait "$SERVE_PID" 2>/dev/null || true
  pkill -f "llama-server.*--port $REQUESTED_PORT" 2>/dev/null || true
  echo "stopped the local decision model (serve pid $SERVE_PID)"
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
PORT=$(cat "$RESULTS/d1.port" 2>/dev/null || echo "")
if [ -z "$PORT" ]; then
  echo "! the decision model's port was not resolved"
  exit 1
fi
# If the daemon had to start the server for us, the serve command is still in
# front of it and the server is ours; if another seat already had the model,
# the serve command has already exited and the server is not ours to stop.
SERVE_PID=$(cat "$RESULTS/d1.pid" 2>/dev/null || echo "")
if [ -n "$SERVE_PID" ] && kill -0 "$SERVE_PID" 2>/dev/null; then
  OWNED=1
else
  echo "another seat already had d1-2B answering — using it, not stopping it"
fi

READY=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
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
echo "the decision model is up on port $PORT"

ENDPOINT="http://127.0.0.1:$PORT"
"$PY" "$HERE/score_set.py" --candidate d1 --set "endpoint=$ENDPOINT" 2>&1 \
  | tee "$RESULTS/d1.log"
"$PY" "$HERE/score_set.py" --candidate hybrid --set delegate=d1 --name hybrid-d1 \
  --set "endpoint=$ENDPOINT" 2>&1 \
  | tee "$RESULTS/hybrid-d1.log"

# the continuation test, with the same delegate: the verdict's edit is applied
# to the frames where the flag fired, and the flag has to be gone afterwards
"$PY" "$HERE/continuation_test.py" --delegate d1 --endpoint "$ENDPOINT" 2>&1 \
  | tee "$RESULTS/continuation-d1.log"

echo "=== the box after ==="
free -g | sed -n '2p'
