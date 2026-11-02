#!/bin/bash
# Run the upstream test suite against the ported extension on the Thor.
# The suite is the port's correctness gate: 45 ctest cases over the rules
# engine (moves, combat, termination, the belief masks, the search, the
# arrangement generator).
set -uo pipefail

CHECKOUT="$HOME/lm-wt/stratego/third_party/stratego"
cd "$CHECKOUT/build"

export PATH="$CHECKOUT/.venv/bin:$PATH"
export PYTHONPATH="$CHECKOUT"

ctest --output-on-failure -j 4
echo "CTEST_EXIT=$?"
