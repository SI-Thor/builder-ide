#!/usr/bin/env bash
# Wait for the night to end, then measure it and write its letter.
#
# The night is long (run D: 152.6 minutes), and the numbers the brief asks
# for — wall time, GPU-minutes against the rail, the lease waits, the
# decisions by rung, the props kept and rejected, and the diff against run
# D — come out of the night's own ledger. This script waits for the run to
# finish and then produces them, so the finishing is a matter of running a
# command rather than of being there at the right minute.
#
#   nohup setsid bash docs/lab/night-v6-scripts/finish_night.sh \
#       > artifacts/night-v6/finish.log 2>&1 &
#
# It writes:
#   artifacts/night-v6/measurements.txt   the measurements and the diff
#   artifacts/night-v6/measurements.json  the same, as JSON
#   artifacts/night-v6/letter.md           the letter (write_letter.py)
set -uo pipefail

cd "$HOME/lm-wt/night-v6"
NIGHT="${NIGHT:-artifacts/night-v6}"
PY="$HOME/lm-wt/propmaker-batch/.venv/bin/python"

echo "waiting for the night to end (started $(date -Is))"
while pgrep -f "night-v6-scripts/run_nigh[t].py" >/dev/null; do
    sleep 20
done
echo "the night ended at $(date -Is)"

PYTHONPATH=. "$PY" docs/lab/night-v6-scripts/measure.py \
    --night "$NIGHT" \
    --against "$HOME/lm-wt/night-v5/artifacts/night-v5" \
    --json "$NIGHT/measurements.json" > "$NIGHT/measurements.txt" 2>&1
echo "--- the measurements are written ---"

PYTHONPATH=. "$PY" docs/lab/night-v6-scripts/write_letter.py \
    --out "$NIGHT" > "$NIGHT/letter-words.txt" 2>&1
cat "$NIGHT/letter-words.txt"
echo "--- the night is finished ---"
