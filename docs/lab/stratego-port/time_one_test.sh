#!/bin/bash
# Time one upstream test alone, to separate "the port is slow" from
# "the box is busy". Usage: bash time_one_test.sh test_cemetery
set -uo pipefail
TEST="${1:-test_cemetery}"
CHECKOUT="$HOME/lm-wt/stratego/third_party/stratego"
cd "$CHECKOUT/build"
export PATH="$CHECKOUT/.venv/bin:$PATH"
export PYTHONPATH="$CHECKOUT"
START=$(date +%s.%N)
python "../tests/${TEST}.py" -v 2>&1 | tail -20
END=$(date +%s.%N)
echo "ELAPSED_S=$(echo "$END - $START" | bc)"
