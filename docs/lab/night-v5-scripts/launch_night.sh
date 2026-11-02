#!/usr/bin/env bash
# Launch the night, and the finisher beside it, both detached.
#
#   bash docs/lab/night-v5-scripts/launch_night.sh [out-dir]
#
# The night itself is the one command (run_night.py). This script only
# detaches it, so the ssh that starts it can close without holding the
# connection open for the night's hours; and it starts the finisher, which
# waits for the night to end and then measures it and writes the letter.
#
# The redirections are inside this script on purpose. A launcher that puts
# them on an ssh command line gets the order wrong under shell precedence —
# the redirect is set up before the cd takes effect and the log lands
# nowhere (the finisher's first launch on 2026-11-01 died that way).
#
# What it needs: the Thor, the models under ~/models, and no other copy of
# the night running (check with pgrep -af 'night-v5-scripts/run_nigh[t].py').
set -uo pipefail

cd "$HOME/lm-wt/night-v5"
OUT="${1:-artifacts/night-v5}"
PY="$HOME/lm-wt/propmaker-batch/.venv/bin/python"

if pgrep -f "night-v5-scripts/run_nigh[t].py" >/dev/null; then
    echo "a night is already running; not starting a second one" >&2
    exit 1
fi

mkdir -p "$OUT"

# On this box the GPU's memory is the system's memory, so a framework that
# preallocates takes it from the box.
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export PYTHONPATH=.

setsid -f nohup "$PY" docs/lab/night-v5-scripts/run_night.py --out "$OUT" \
    > "$OUT/run.log" 2>&1 < /dev/null
sleep 3
NIGHT="$OUT" setsid -f nohup bash docs/lab/night-v5-scripts/finish_night.sh \
    > "$OUT/finish.log" 2>&1 < /dev/null

echo "the night is launched: $OUT/run.log"
echo "the finisher is beside it: $OUT/finish.log"
