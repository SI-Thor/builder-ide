#!/bin/bash
# Wait for the Thor to come back and re-capture the parts that need error
# classification. Harmless if it never returns: the raw/ files already hold a
# complete capture from 15:48 except for the error classes.
cd "$(dirname "$0")/.."
for i in $(seq 1 60); do
  if timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=8 thor-lan 'true' 2>/dev/null; then
    echo "$(date '+%H:%M:%S') Thor reachable, capturing"
    python3 scripts/capture.py 2>&1 | grep -E 'seats-thor|git-commits-thor|!!'
    exit 0
  fi
  sleep 30
done
echo "$(date '+%H:%M:%S') Thor did not come back within 30 min"
exit 1
