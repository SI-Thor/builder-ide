#!/usr/bin/env bash
# =============================================================================
# The fp8 experiment, one arm at a time.
#
#   run_experiment.sh <arm> [seed ...]
#
# Each arm: start a ComfyUI with the probe loaded, run the prop(s) through
# it, stop the service, keep the probe's JSON.  The arms differ in the dtype
# the TRELLIS.2 loader is asked for and in whether the fp8 fix is installed,
# so the numbers can be compared:
#
#   bf16          the control: the model in bfloat16, as the night runs it.
#   fp8-declined  the fp8 template *without* the fix: the weights arrive
#                 bf16, the fused path declines, and the model falls back to
#                 the manual-cast path.  This is what the box does today.
#   fp8-fixed     the fp8 template *with* the fix: the weights are fp8 and
#                 the fused path runs.
#
# The three are the same prop, the same seed, the same workflow and the same
# box, so the numbers are comparable.  The arms are run one after another
# and each gets its own ComfyUI process, so nothing is shared but the box.
#
# The old arms (stage-memo, stage-nomemo, unet-memo, fp8, fp8-pre, spy) are
# the CUDA-graph experiment's, and they keep working: they now also turn the
# fp8 fix *off* (FP8_REAL_FIX=0), so they reproduce what they measured.
# =============================================================================
set -euo pipefail

ARM="${1:-}"
shift || true
SEEDS=("$@")
[[ ${#SEEDS[@]} -eq 0 ]] && SEEDS=(101)

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PORT="${TRG_PORT:-8189}"
# The driver needs the seat's own environment (pydantic, aiohttp). Prefer an
# explicit $PYTHON, then the venv the first mini-night used, then python3.
if [[ -z "${PYTHON:-}" ]]; then
  for candidate in "$HOME/lm-wt/propmaker-batch/.venv/bin/python" \
                   "$REPO/.venv/bin/python" "$(command -v python3 || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then PY="$candidate"; break; fi
  done
fi
PY="${PY:-python3}"
OUT="$REPO/artifacts/fp8-real"
mkdir -p "$OUT"

case "$ARM" in
bf16)
  MODE=steps; TEMPLATE=trellis2_512.api.json; FIX=0; DTYPE=default ;;
fp8-declined)
  MODE=steps; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json; FIX=0; DTYPE=fp8_e4m3fn_fast ;;
fp8-fixed)
  MODE=steps; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json; FIX=1; DTYPE=fp8_e4m3fn_fast ;;
stage-memo)
  MODE=graph; TARGET=stage; MEMO=1; TEMPLATE=trellis2_512.api.json; FIX=0; DTYPE=default ;;
stage-nomemo)
  MODE=graph; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512.api.json; FIX=0; DTYPE=default ;;
unet-memo)
  MODE=graph; TARGET=unet; MEMO=1; TEMPLATE=trellis2_512.api.json; FIX=0; DTYPE=default ;;
fp8)
  MODE=fp8; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json; FIX=0; DTYPE=fp8_e4m3fn_fast ;;
fp8-pre)
  MODE=fp8; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json
  PRECOMPUTE=1; FIX=0; DTYPE=fp8_e4m3fn_fast ;;
spy)
  # No capture at all: watch the host-to-device copies the model makes.
  MODE=off; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512.api.json
  SPY=1; FIX=0; DTYPE=default ;;
*)
  echo "usage: $0 {bf16|fp8-declined|fp8-fixed|stage-memo|stage-nomemo|unet-memo|fp8|fp8-pre|spy} [seed ...]" >&2
  exit 2
  ;;
esac

SUFFIX="${TRG_SUFFIX:-}"
PROBE_JSON="$OUT/$ARM$SUFFIX-probe.json"

echo "== arm: $ARM  mode=$MODE template=$TEMPLATE fix=$FIX dtype=$DTYPE seeds=${SEEDS[*]}"

export TRG_MODE="$MODE"
export TRG_TARGET="${TARGET:-stage}"
export TRG_MEMO_LAYOUT="${MEMO:-0}"
export TRG_PRECOMPUTE_SCALES="${PRECOMPUTE:-0}"
export TRG_SPY="${SPY:-0}"
export TRG_OUT="$PROBE_JSON"
export TRG_PORT="$PORT"
export FP8_REAL_FIX="$FIX"
export FP8_REAL_STATS="$OUT/$ARM$SUFFIX-fp8-real.json"

# The box's state, beside the numbers.
"$HERE/boxstate.sh" > "$OUT/$ARM$SUFFIX-box-before.txt" 2>&1 || true

cleanup() {
  "$HERE/serve_probe.sh" stop --port "$PORT" >/dev/null 2>&1 || true
  [[ -n "${GPU_SAMPLER:-}" ]] && kill "$GPU_SAMPLER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$HERE/serve_probe.sh" start --port "$PORT"

set +e
"$HERE/boxstate.sh" > "$OUT/$ARM$SUFFIX-box-running.txt" 2>&1 || true

# The GPU's own memory, sampled while the prop runs: the peak is a moment,
# not a number the box keeps.
(
  while true; do
    nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader
    sleep 1
  done
) > "$OUT/$ARM$SUFFIX-gpu-samples.txt" 2>&1 &
GPU_SAMPLER=$!

RC=0
for SEED in "${SEEDS[@]}"; do
  "$PY" "$HERE/run_one_prop.py" \
    --comfy-url "http://127.0.0.1:$PORT" \
    --template "$TEMPLATE" \
    --weight-dtype "$DTYPE" \
    --out "$OUT/$ARM$SUFFIX-run-s$SEED.json" \
    --seed "$SEED" \
    --prefix "fp8real/$ARM$SUFFIX/s$SEED" > "$OUT/$ARM$SUFFIX-run-s$SEED.log" 2>&1
  rc=$?
  echo "  seed $SEED exited $rc"
  [[ $rc -ne 0 ]] && RC=$rc
done
set -e

cleanup
trap - EXIT

if [[ -f "$PROBE_JSON" ]]; then
  echo "-- the probe's record:"
  "$PY" - "$PROBE_JSON" <<'PYEOF'
import json, statistics, sys
data = json.load(open(sys.argv[1]))
records = data.get("records", [])
print(f"  records: {len(records)}")
print(f"  refusals: {len(data.get('refusals', []))}")
for r in data.get("refusals", []):
    print(f"    - {r.get('model')}: {str(r.get('error'))[:160]}")
if records and "gpu_ms" in records[0]:
    gpu = sorted(r["gpu_ms"] for r in records)
    host = sorted(r["host_ms"] for r in records)
    print(f"  per-step gpu ms: median {statistics.median(gpu):.1f}  min {gpu[0]:.1f}  max {gpu[-1]:.1f}  n={len(gpu)}")
    print(f"  per-step host ms: median {statistics.median(host):.1f}")
    mem = records[-1].get("memory", {})
    print(f"  memory: {mem}")
print(f"  layout stats: {data.get('layout_stats')}")
if "fp8_stats" in data:
    print(f"  fp8 stats: {data['fp8_stats']}")
PYEOF
else
  echo "!! the probe wrote no JSON at $PROBE_JSON"
fi
if [[ -f "$OUT/$ARM$SUFFIX-fp8-real.json" ]]; then
  echo "-- the fp8 fix's counters:"
  cat "$OUT/$ARM$SUFFIX-fp8-real.json"
fi
echo "-- done: $ARM (rc=$RC)"
exit "$RC"
