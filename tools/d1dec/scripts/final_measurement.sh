#!/usr/bin/env bash
# The whole measurement, end to end, on the box as it is.
#
#   scripts/final_measurement.sh
#
# It starts the batched server with the engine's default settings (the
# ones the code ships with), checks the tokenizer against llama.cpp,
# checks the answers against llama.cpp, and then measures the two
# servers **interleaved** — baseline, ours, baseline, ours, three times
# each — so that the shared box's drift hits both of them the same way.
#
# The llama.cpp baseline is expected to be running already on :8137; if
# it is not, the script says so and stops.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ADMIT="${ADMIT:-$HOME/lm-tools/thor-admit}"
PY="$REPO/.venv/bin/python"
BASE="${BASE:-http://127.0.0.1:8137}"
OURS="${OURS:-http://127.0.0.1:8138}"
ROUNDS="${ROUNDS:-3}"

cd "$REPO" || exit 1
mkdir -p logs results

if ! curl -sf "$BASE/health" >/dev/null 2>&1; then
  echo "the llama.cpp baseline is not answering on $BASE — start it first"
  exit 1
fi

# -- the box's state, before -------------------------------------------
bash scripts/box_state.sh > results/box_state_before.txt 2>&1

# -- our server, with the engine's shipped settings -------------------
if ! curl -sf "$OURS/health" >/dev/null 2>&1; then
  echo "starting the batched server ..."
  setsid nohup "$ADMIT" run --tier live --priority 1 --peak 6G \
    --label d1-2B-batched -- \
    "$PY" "$REPO/scripts/run_server.py" \
      --gguf /home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf \
      --host 127.0.0.1 --port 8138 \
      --max-batch-seqs 192 --max-batch-tokens 49152 --linger-ms 4.0 \
    > logs/ours_server.log 2>&1 < /dev/null &
  disown
fi

for i in $(seq 1 1800); do
  curl -sf "$OURS/health" >/dev/null 2>&1 && { echo "the batched server is up (${i}s)"; break; }
  sleep 1
done
if ! curl -sf "$OURS/health" >/dev/null 2>&1; then
  echo "the batched server did not come up"; tail -30 logs/ours_server.log; exit 1
fi

# -- the measurement ----------------------------------------------------
"$PY" "$REPO/scripts/measure.py" \
  --baseline "$BASE" --ours "$OURS" \
  --workload workload/packs.jsonl --rounds "$ROUNDS" --out-dir results
rc=$?

# -- the box's state, after --------------------------------------------
bash scripts/box_state.sh > results/box_state_after.txt 2>&1

# -- the pre-registered score ------------------------------------------
# every round that has ever been measured is pooled, and the median of
# them is the headline: the box's load moves the absolute numbers by a
# factor of two within a run, so one round is a sample, not a result.
TAG="run$(date +%H%M)"
"$PY" "$REPO/scripts/pool_rounds.py" --archive "$TAG"
"$PY" "$REPO/scripts/make_result.py"

exit $rc
