#!/usr/bin/env bash
# after the gate sweep: the node-impl profile run, then the analysis
cd ~/lm-wt/lab5
while pgrep -f "python3 scripts/sweep.py" >/dev/null; do sleep 60; done
echo "$(date +%H:%M:%S) gate sweep done; profile run" >> runs/sweep_progress.txt
mkdir -p results_profile
env PYTHONPATH=pylibs ~/lm-wt/v2-thor/.venv/bin/python scripts/run_solve.py \
  --seed 0 --arm baseline --stages large --steps-override 15,0,0 \
  --profile --out results_profile/baseg_seed0.json > runs/profile_baseg_seed0.log 2>&1
echo "$(date +%H:%M:%S) profile done; analysis" >> runs/sweep_progress.txt
python3 scripts/analyze.py > results/analysis.txt 2>&1
bash scripts/box_state.sh > runs/box_analysis.txt
echo "$(date +%H:%M:%S) CHAIN DONE" >> runs/sweep_progress.txt
