#!/usr/bin/env bash
# Measure what one llama-server holds of the Thor's GPU, under the flags the
# night uses and under smaller ones.
#
# The night's two decision servers (d1-3B and d1-2B) were resident for the
# whole heavy phase, and the thor-admit guard measured 18,486,394,880 bytes
# of GPU for each one. That is the number this script checks, and the
# number the smaller flags should change.
#
# Each server runs under its own thor-admit lease, so the guard leaves it
# alone and the measurement is of a leased server.
#
#   bash ~/lm-wt/night-v5/docs/lab/night-v5-scripts/measure_llama_gpu.sh
set -uo pipefail

MODEL="$HOME/models/d1-3B/d1-3B-Q8_0.gguf"
SERVER="$HOME/llama.cpp-upstream/build-up/bin/llama-server"
PORT=8299

echo "=== the model ==="
ls -la "$MODEL"
echo "=== the box before ==="
free -g | head -2
nvidia-smi --query-compute-apps=pid,used_memory --format=csv

healthy () {
    python3 - "$PORT" <<'PY' 2>/dev/null
import sys, urllib.request
try:
    urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1)
except Exception:
    sys.exit(1)
PY
}

measure () {
    label="$1"; shift
    log="/tmp/llama-gpu-$label.log"
    echo
    echo "=== $label ==="
    echo "flags: $*"
    "$HOME/lm-tools/thor-admit" run --tier practice --peak 20G \
        --label "night-v5.llama.$label" -- \
        "$SERVER" -m "$MODEL" --host 127.0.0.1 --port "$PORT" --alias probe \
        "$@" > "$log" 2>&1 < /dev/null &
    runner=$!
    ready=0
    for _ in $(seq 1 180); do
        if healthy; then ready=1; break; fi
        sleep 1
    done
    if [ "$ready" = 1 ]; then
        sleep 5
        echo "-- health: answering"
        echo "-- nvidia-smi per-process (pid, MiB) --"
        nvidia-smi --query-compute-apps=pid,used_memory --format=csv
        pid=$(pgrep -f "llama-server.*--port $PORT" | head -1)
        if [ -n "$pid" ]; then
            echo "-- the server's own rss --"
            grep -E "VmRSS|VmHWM" "/proc/$pid/status"
        fi
        echo "-- the box --"
        free -g | head -2
    else
        echo "NOT READY; the log says:"
        tail -5 "$log"
    fi
    kill "$runner" 2>/dev/null
    sleep 3
    pkill -f "llama-server.*--port $PORT" 2>/dev/null
    sleep 3
}

measure ctx8192_ub4096 -ngl 99 --flash-attn on --ctx-size 8192 -ub 4096
measure ctx4096_ub1024 -ngl 99 --flash-attn on --ctx-size 4096 -ub 1024
measure ctx4096_ub512  -ngl 99 --flash-attn on --ctx-size 4096 -ub 512

echo
echo "=== the box after ==="
free -g | head -2
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
echo "=== done ==="
