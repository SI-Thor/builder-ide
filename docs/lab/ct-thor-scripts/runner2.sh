#!/bin/bash
# runner2.sh — ct-thor round 2: diagnostics + fixed exp3/exp5b, under the heavy lock.
flock /home/caseydigennaro/lm-wt/heavy.lock bash -c '
cd /home/caseydigennaro/lm-wt/ct-thor
set -x
FREE=$(free -g | awk "/^Mem:/{print \$7}")
if [ "$FREE" -lt 25 ]; then echo "SKIP: only ${FREE} GB free"; exit 1; fi
echo "=== lock acquired, ${FREE} GB free, $(date) ==="
./exp_diag 2>&1
./exp3 2>&1
python3 exp5b_judge_bench.py 2>&1
echo "=== round2 done $(date) ==="
'
