#!/bin/bash
# Part 2 of the liquid-study brief: the checks the box can settle.
#
# Coordination: the whole run takes ~/lm-wt/heavy.lock, so it queues behind
# lab-fp4's sweep and any other seat's heavy step instead of fighting them
# for the GPU. Nothing here stops anybody else's job or service -- the only
# processes this script starts are llama-servers on ports 8290-8294, and it
# stops each one before the next starts.
#
# Only the d1 decision models are served. No other LLM is hosted on the Thor.
set -u
cd /home/caseydigennaro/lm-wt/liquid-study || exit 1
mkdir -p logs results

echo "[runner] started $(date -Is); queueing for the heavy lock"
exec flock -w 7200 /home/caseydigennaro/lm-wt/heavy.lock bash -c '
set -x
cd /home/caseydigennaro/lm-wt/liquid-study
echo "[runner] got the lock at $(date -Is)"

# Idempotent: a step is skipped if its result file already exists and is
# non-empty, so a second runner that wins the lock later does not redo work.
run_step () {
  local out="$1"; shift
  if [ -s "results/$out" ]; then
    echo "[runner] SKIP $out (results/$out already present)"
    return 0
  fi
  "$@"; echo "[runner] $out exit=$?"
}

run_step exp_a_latency.json              python3 scripts/exp_a_latency.py
run_step exp_b_state.json                python3 scripts/exp_b_state.py
run_step exp_c_hysteresis_d1-3B.json     python3 scripts/exp_c_hysteresis.py d1-3B 8293 6 40 0.35
run_step exp_c_hysteresis_d1-2B.json     python3 scripts/exp_c_hysteresis.py d1-2B 8294 6 40 0.35

echo "[runner] done $(date -Is)"
'
