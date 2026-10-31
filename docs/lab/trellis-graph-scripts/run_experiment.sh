#!/usr/bin/env bash
# =============================================================================
# The graph-capture experiment, one arm at a time.
#
#   run_experiment.sh <arm>
#
# Each arm: start a ComfyUI with the probe loaded, run one real prop through
# it, stop the service, keep the probe's JSON.  The arms differ in what the
# probe does, so the numbers can be compared:
#
#   stage-memo    capture the per-stage sub-models, with the sparse layout
#                 memoised (the fix).  Expect the sparse stages to capture.
#   stage-nomemo  the same, without the memo.  The control: the sparse
#                 stages should refuse capture, and the record should say
#                 why.
#   unet-memo     capture the whole UNet forward, memo on.  The whole-step
#                 attempt: the dense stage should capture, the sparse ones
#                 should refuse (the parent's boolean-mask scatter).
#   fp8           the fused fp8 path, with the scales made per call.
#   fp8-pre       the fused fp8 path, with the scales precomputed per layer.
#
# The fp8 arms run the TRELLIS.2 environment's own fp8 template, which is
# what selects ComfyUI's fused fp8 ops (the UNETLoader's weight_dtype).
# =============================================================================
set -euo pipefail

ARM="${1:-}"
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
OUT="$REPO/artifacts/trg-graph"
mkdir -p "$OUT"

case "$ARM" in
stage-memo)
  MODE=graph; TARGET=stage; MEMO=1; TEMPLATE=trellis2_512.api.json ;;
stage-nomemo)
  MODE=graph; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512.api.json ;;
unet-memo)
  MODE=graph; TARGET=unet; MEMO=1; TEMPLATE=trellis2_512.api.json ;;
fp8)
  MODE=fp8; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json ;;
fp8-pre)
  MODE=fp8; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512_fp8_e4m3fn_fast.api.json
  PRECOMPUTE=1 ;;
spy)
  # No capture at all: watch the host-to-device copies the model makes.
  MODE=off; TARGET=stage; MEMO=0; TEMPLATE=trellis2_512.api.json
  SPY=1 ;;
*)
  echo "usage: $0 {stage-memo|stage-nomemo|unet-memo|fp8|fp8-pre|spy}" >&2
  exit 2
  ;;
esac

PROBE_JSON="$OUT/$ARM-probe.json"
RUN_JSON="$OUT/$ARM-run.json"

echo "== arm: $ARM  mode=$MODE target=$TARGET memo=$MEMO template=$TEMPLATE"

export TRG_MODE="$MODE"
export TRG_TARGET="$TARGET"
export TRG_MEMO_LAYOUT="$MEMO"
export TRG_PRECOMPUTE_SCALES="${PRECOMPUTE:-0}"
export TRG_SPY="${SPY:-0}"
export TRG_OUT="$PROBE_JSON"
export TRG_PORT="$PORT"

# The box's state, beside the numbers.
"$REPO/artifacts/boxstate.sh" > "$OUT/$ARM-box-before.txt" 2>&1 || true

cleanup() {
  "$HERE/serve_probe.sh" stop --port "$PORT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$HERE/serve_probe.sh" start --port "$PORT"

set +e
"$REPO/artifacts/boxstate.sh" > "$OUT/$ARM-box-running.txt" 2>&1 || true
"$PY" "$HERE/run_one_prop.py" \
  --comfy-url "http://127.0.0.1:$PORT" \
  --template "$TEMPLATE" \
  --out "$RUN_JSON" \
  --prefix "$ARM" > "$OUT/$ARM-run.log" 2>&1
RC=$?
set -e
echo "the prop run exited $RC"

cleanup
trap - EXIT

if [[ -f "$PROBE_JSON" ]]; then
  echo "-- the probe's record:"
  "$PY" - "$PROBE_JSON" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
print(f"  records: {len(data.get('records', []))}")
print(f"  refusals: {len(data.get('refusals', []))}")
for r in data.get("refusals", []):
    print(f"    - {r.get('model')}: {str(r.get('error'))[:160]}")
print(f"  layout stats: {data.get('layout_stats')}")
if "fp8_stats" in data:
    print(f"  fp8 stats: {data['fp8_stats']}")
PYEOF
else
  echo "!! the probe wrote no JSON at $PROBE_JSON"
fi
echo "-- done: $ARM (prop run rc=$RC)"
