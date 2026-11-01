#!/usr/bin/env bash
# Start the decision server with a given set of engine settings, measure
# it, and print what it cost.
#
#   scripts/try_config.sh <rope> <conv> <chunk> <label>
#
# The server is left running, so the next configuration can be started
# after this one's process has been stopped.
set -u

ROPE="${1:-native}"
CONV="${2:-native}"
CHUNK="${3:-64}"
LABEL="${4:-try}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ADMIT="${ADMIT:-$HOME/lm-tools/thor-admit}"
PY="$REPO/.venv/bin/python"

cd "$REPO" || exit 1
mkdir -p logs results

echo "=== $LABEL: rope=$ROPE conv=$CONV chunk=$CHUNK ==="

D1DEC_ROPE="$ROPE" D1DEC_CONV="$CONV" D1DEC_FORWARD_CHUNK="$CHUNK" D1DEC_GQA=1 \
  setsid nohup "$ADMIT" run --tier live --priority 1 --peak 6G \
    --label "missionA-mcode.$LABEL" -- \
    "$PY" "$REPO/scripts/run_server.py" \
      --gguf /home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf \
      --host 127.0.0.1 --port 8138 \
      --max-batch-seqs 192 --max-batch-tokens 49152 --linger-ms 4.0 \
    > "logs/ours_server.log" 2>&1 < /dev/null &
disown

for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8138/health >/dev/null 2>&1; then
    echo "up after ${i}s"; break
  fi
  sleep 1
done
if ! curl -sf http://127.0.0.1:8138/health >/dev/null 2>&1; then
  echo "the server did not come up"; tail -20 logs/ours_server.log; exit 1
fi

"$PY" "$REPO/scripts/bench.py" --server http://127.0.0.1:8138 --mode n64 \
  --ticks 4 --warmup 1 --label "$LABEL" 2>&1 | grep -E "decisions_per_s|tick_ms_mean|tick_ms_p95|errors|error_kinds" -A2 | head -20

echo "--- the server's own memory and batch numbers ---"
curl -s http://127.0.0.1:8138/stats | "$PY" -c "
import json,sys
s=json.load(sys.stdin)
h=s.pop('batch_hist',[])
print('gpu_peak_alloc_gb   ', round(s.get('gpu_peak_alloc_gb',0),3))
print('gpu_peak_reserved_gb', round(s.get('gpu_peak_reserved_gb',0),3))
print('batches', s.get('batches'), 'sequences', s.get('sequences'))
print('batch ms:', [round(x['ms']) for x in h[-8:]])
"
echo "--- the host's peak resident set of the server ---"
"$PY" "$REPO/scripts/peak_mem.py" --ours http://127.0.0.1:8138 --baseline http://127.0.0.1:8137 2>&1 | head -20
