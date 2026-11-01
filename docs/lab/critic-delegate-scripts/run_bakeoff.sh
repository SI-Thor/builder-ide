#!/usr/bin/env bash
# The delegate bake-off: the scripted baseline, the two delegates, and the
# hybrid with each.
#
#   bash docs/lab/critic-delegate-scripts/run_bakeoff.sh
#
# The stages are:
#
#   1. the scripted checks (the baseline row, no model, no network);
#   2. d1-2B: the local decision model with its projector, under the box's
#      shared lock, asked the fixed question per class;
#   3. clef-flash: the cloud decision model, through the throwaway Worker
#      that holds the AI binding (nothing is deployed);
#   4. the hybrid with each delegate — the checks first, the delegate only on
#      the class the checks are out of band on;
#   5. the tables side by side.
#
# The box's state is captured beside the numbers, and every resident model is
# stopped when its stage ends.
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

# -- 1. the baseline ----------------------------------------------------------
echo
echo "=== the scripted checks: the baseline row ==="
"$PY" "$HERE/score_set.py" --candidate scripted 2>&1 | tee "$RESULTS/scripted.log"

# -- 2. the local decision model ----------------------------------------------
echo
echo "=== d1-2B: the local decision model with its projector ==="
echo "(the whole stage runs under the box's shared lock)"
flock "$HOME/lm-wt/heavy.lock" bash "$HERE/run_d1_stage.sh"

# -- 3. the cloud decision model ----------------------------------------------
echo
echo "=== clef-flash: the cloud decision model, with the image ==="
if curl -sf -o /dev/null http://127.0.0.1:8797/ 2>/dev/null; then
  echo "the Workers AI proxy is reachable on 127.0.0.1:8797"
elif curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8797/ | grep -qE '^[45]'; then
  echo "the Workers AI proxy answered (a request without a body is refused, which is what it should do)"
else
  echo "! the Workers AI proxy is not reachable on 127.0.0.1:8797"
  echo "  start it on the ProArt (wrangler dev --remote) and forward the port"
fi

"$PY" "$HERE/score_set.py" --candidate clef 2>&1 | tee "$RESULTS/clef.log"
"$PY" "$HERE/score_set.py" --candidate hybrid --set delegate=clef --name hybrid-clef 2>&1 \
  | tee "$RESULTS/hybrid-clef.log"

# -- 4. the tables -------------------------------------------------------------
echo
echo "=== the tables, side by side ==="
"$PY" "$HERE/report.py"

echo
echo "=== the box after ==="
free -g | sed -n '2p'
