#!/usr/bin/env bash
# =============================================================================
# The ten props, generated on the Thor.
#
#   text (the planner's image prompt) --SDXL--> picture --TRELLIS.2--> mesh
#
# The TRELLIS.2 environment is *read*, never written: its scripts build
# the workflows and run them, and this script only drives it and collects
# what comes out. The mesh for a prop lands in
# ``artifacts/physag-lite/meshes/<prop>.glb`` with the picture beside it.
#
# **This script runs its own ComfyUI.** The TRELLIS.2 environment is a shared
# service on this box: another seat's night job was holding the server on
# :8188 when this was written, and posting our prompts into its queue would
# have polluted that seat's timings and ours. So we start a second instance on
# our own port, with our own input/output directories and our own pidfile —
# the shared tree's ``logs/comfy_server.pid`` is never touched, and the
# instance we start is the only one we stop.
#
# The memory rule (~/lm-wt/MEMORY-RULE.md): the whole batch runs under one
# admission lease, and the lease covers the server as well as the runs — the
# ComfyUI process holds the model weights, so without one the box can be
# filled by another seat's work while the weights are resident.
#
#   thor-admit run --tier live --peak 40G --label physag-lite.generate -- \
#       docs/lab/physag-lite/generate_meshes.sh
#
# The peak is the measured one: the spike recorded a 40-47 GB dip in
# MemAvailable for the 512 path with the weights resident (SPIKE.md §4).
#
# The GPU-busy seconds are sampled here, once a second, and integrated: the
# wall clock alone would charge the GPU for the time it spent waiting for the
# CPU (the mesh tail is CPU-bound). The other processes on the GPU are
# counted at the same time, so a number taken on a busy box says so.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TRELLIS="${TRELLIS_DIR:-$HOME/lm-wt/trellis}"
OUT="${PHYSAG_OUT:-$REPO/artifacts/physag-lite}"
SPECS="$HERE/specs"
PY="$TRELLIS/.venv-e2/bin/python"

# Our own ComfyUI: port, pidfile, log, input and output directories. The
# shared tree's own files are read and never written.
PORT="${PHYSAG_TRELLIS_PORT:-8189}"
PIDFILE="$OUT/generation/comfy.pid"
COMFY_LOG="$OUT/generation/comfy_server.log"
COMFY_IN="$OUT/comfy_in"
COMFY_OUT="$OUT/comfy_out"

MODE="${PHYSAG_MODE:-512}"
PROPS="${PHYSAG_PROPS:-crate chest lantern door drawer_unit barrel cart gate ladder table}"

mkdir -p "$OUT/meshes" "$OUT/pictures" "$OUT/generation" "$COMFY_IN" "$COMFY_OUT"

is_up() {
    curl -s --max-time 3 "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1
}

stop_comfy() {
    if [[ -f "$PIDFILE" ]]; then
        pid="$(cat "$PIDFILE")"
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 30); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$PIDFILE"
        echo "== stopped our ComfyUI (pid $pid)"
    fi
}

start_comfy() {
    if is_up; then
        echo "== a ComfyUI is already answering on :${PORT}; using it"
        return
    fi
    echo "== starting our ComfyUI on :${PORT} (pidfile $PIDFILE)"
    nohup "$TRELLIS/.venv-e2/bin/python" "$TRELLIS/ComfyUI/main.py" \
        --listen 127.0.0.1 --port "$PORT" --disable-auto-launch \
        --extra-model-paths-config "$TRELLIS/extra_model_paths.yaml" \
        --use-pytorch-cross-attention \
        --output-directory "$COMFY_OUT" \
        --input-directory "$COMFY_IN" \
        --cache-none > "$COMFY_LOG" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 120); do
        sleep 2
        if is_up; then
            echo "== up on http://127.0.0.1:${PORT}"
            return
        fi
    done
    echo "FAIL: our ComfyUI did not come up; see $COMFY_LOG" >&2
    exit 1
}

echo "== the box before"
free -g | head -2
uptime
nvidia-smi --query-gpu=name,utilization.gpu,memory.total,compute_cap --format=csv,noheader 2>/dev/null || true

start_comfy
cleanup() {
    echo
    stop_comfy
}
trap cleanup EXIT

# The GPU-busy seconds: the utilisation sampled once a second while the
# batch runs, integrated. The wall clock alone would charge the GPU for the
# time it spent waiting for the CPU.
UTIL_LOG="$OUT/generation/gpu_util.log"
: > "$UTIL_LOG"
(
    while true; do
        nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null \
            | head -1 >> "$UTIL_LOG" || true
        sleep 1
    done
) &
UTIL_PID=$!
trap 'kill $UTIL_PID 2>/dev/null || true; cleanup' EXIT

for prop in $PROPS; do
    spec="$SPECS/$prop.json"
    if [[ ! -f "$spec" ]]; then
        echo "!! no plan for $prop; skipping" >&2
        continue
    fi
    prompt="$($PY - "$spec" <<'EOF'
import json, sys
print(json.load(open(sys.argv[1]))["image_prompt"])
EOF
)"
    echo
    echo "== $prop"
    echo "   prompt: $prompt"

    started=$(date +%s)
    "$PY" "$TRELLIS/scripts/build_text2image.py" \
        --prompt "$prompt" \
        --prefix "trellis2/physag_${prop}_image" \
        --out "$TRELLIS/workflows/physag_${prop}_image.api.json" >/dev/null
    "$PY" "$TRELLIS/scripts/run_workflow.py" \
        --workflow "$TRELLIS/workflows/physag_${prop}_image.api.json" \
        --label "physag_${prop}_image" \
        --server "http://127.0.0.1:${PORT}" \
        --port "$PORT" \
        --comfy-out "$COMFY_OUT" \
        --out-dir "$OUT/generation" 2>&1 | tail -3

    # ComfyUI's LoadImage reads the input directory; the image stage wrote
    # to the output directory.
    img="$(ls -t "$COMFY_OUT/trellis2/physag_${prop}_image_"*.png 2>/dev/null | head -1)"
    if [[ -z "$img" ]]; then
        echo "!! $prop: no image came out; skipping the mesh" >&2
        continue
    fi
    cp "$img" "$OUT/pictures/${prop}.png"
    cp "$img" "$COMFY_IN/physag_${prop}.png"

    "$PY" "$TRELLIS/scripts/build_workflow.py" \
        --mode "$MODE" \
        --image "physag_${prop}.png" \
        --prefix "trellis2/physag_${prop}" \
        --out "$TRELLIS/workflows/physag_${prop}.api.json" >/dev/null
    "$PY" "$TRELLIS/scripts/run_workflow.py" \
        --workflow "$TRELLIS/workflows/physag_${prop}.api.json" \
        --label "physag_${prop}" \
        --server "http://127.0.0.1:${PORT}" \
        --port "$PORT" \
        --comfy-out "$COMFY_OUT" \
        --out-dir "$OUT/generation" 2>&1 | tail -3

    glb="$(ls -t "$COMFY_OUT/trellis2/physag_${prop}_"*.glb 2>/dev/null | head -1)"
    if [[ -z "$glb" ]]; then
        echo "!! $prop: no mesh came out" >&2
        continue
    fi
    cp "$glb" "$OUT/meshes/${prop}.glb"
    ended=$(date +%s)
    echo "   $prop: mesh $(stat -c%s "$OUT/meshes/${prop}.glb") bytes in $((ended - started))s"
done

echo
echo "== the box after"
free -g | head -2
uptime
echo "== done; the meshes are in $OUT/meshes"
ls -la "$OUT/meshes"
