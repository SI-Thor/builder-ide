#!/bin/bash
# runner.sh — ct-thor: run remaining experiments sequentially under the heavy lock.
cd /home/caseydigennaro/lm-wt/ct-thor

flock ~/lm-wt/heavy.lock bash -c '
cd /home/caseydigennaro/lm-wt/ct-thor
set -x
FREE=$(free -g | awk "/^Mem:/{print \$7}")
if [ "$FREE" -lt 25 ]; then echo "SKIP: only ${FREE} GB free"; exit 1; fi
echo "=== lock acquired, ${FREE} GB free, $(date) ==="
./exp2 2>&1
./exp3 2>&1
./exp4 2>&1
crdt-bench/target/release/crdt-bench 2>&1
python3 exp5b_judge_bench.py 2>&1
echo "=== chain done $(date) ==="
'
