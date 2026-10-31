#!/usr/bin/env bash
# =============================================================================
# Start ComfyUI with the probe loaded, for the graph-capture experiment.
#
#   serve_probe.sh start [--fast-fp8] [--port 8189]
#   serve_probe.sh stop
#   serve_probe.sh status
#
# The point of the base directory: ComfyUI looks for custom nodes under
# <base>/custom_nodes, and that base lives in *this worktree*.  The probe is
# therefore a monkeypatch kept here, never in the TRELLIS.2 checkout — the
# environment is read, never modified.
#
# Everything else is the TRELLIS.2 spike's own service recipe
# (~/lm-wt/trellis/scripts/serve.sh), with two differences:
#
#   --base-directory   the worktree's comfy-base, so the probe loads;
#   --port             8189 by default, so this service does not fight the
#                      plain one on 8188.
#
# The flags that matter on this box (rev-tech):
#   --use-pytorch-cross-attention   the SDPA path — the only attention
#                                   backends with sm_110 kernels that exist
#                                   without a source build;
#   --cache-none                    ComfyUI's node cache OFF, so a second
#                                   run of the same workflow does not reuse
#                                   the previous run's sampler output;
#   --fast fp8_matrix_mult          the fused fp8 path, for the scale
#                                   experiment (trellis-spike §7.3).
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TRELLIS="${TRELLIS_ROOT:-$HOME/lm-wt/trellis}"
BASE="$HERE/comfy-base"
PORT="${TRG_PORT:-8189}"
PIDFILE="$HERE/comfy-base/logs/comfy_probe.pid"
LOGFILE="$HERE/comfy-base/logs/comfy_probe.log"

CMD="${1:-start}"
shift || true
FAST_FP8=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast-fp8) FAST_FP8=1 ;;
    --port) PORT="$2"; shift ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$BASE/logs" "$TRELLIS/out" "$TRELLIS/input"

is_up() {
  curl -s --max-time 3 "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1
}

case "$CMD" in
start)
  if is_up; then
    echo "already up on :${PORT}"
    exit 0
  fi
  ARGS=(
    "$TRELLIS/ComfyUI/main.py"
    --base-directory "$BASE"
    --listen 127.0.0.1 --port "$PORT" --disable-auto-launch
    --extra-model-paths-config "$TRELLIS/extra_model_paths.yaml"
    --models-directory "$TRELLIS/models"
    --use-pytorch-cross-attention
    --output-directory "$TRELLIS/out"
    --input-directory "$TRELLIS/input"
    --cache-none
  )
  [[ "$FAST_FP8" -eq 1 ]] && ARGS+=(--fast fp8_matrix_mult)
  nohup "$TRELLIS/.venv-e2/bin/python" "${ARGS[@]}" > "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  echo "started pid=$(cat "$PIDFILE")  port=$PORT  log=$LOGFILE"
  for _ in $(seq 1 120); do
    sleep 2
    if is_up; then
      echo "up on http://127.0.0.1:${PORT}"
      exit 0
    fi
  done
  echo "FAIL: server did not come up; see $LOGFILE" >&2
  exit 1
  ;;
stop)
  if [[ -f "$PIDFILE" ]]; then
    PID="$(cat "$PIDFILE")"
    kill "$PID" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$PID" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "stopped pid=$PID"
  else
    echo "no pidfile"
  fi
  ;;
status)
  if is_up; then
    echo "up on :${PORT}"
  else
    echo "down on :${PORT}"
  fi
  ;;
*)
  echo "usage: $0 {start|stop|status} [--fast-fp8] [--port N]" >&2
  exit 2
  ;;
esac
