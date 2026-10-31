#!/usr/bin/env bash
# =============================================================================
# The box's state, beside the numbers.
#
# A number without the box's state beside it is a number nobody can read
# later.  This is the same recipe the mini-nights used
# (~/lm-wt/mini-night2/artifacts/boxstate.sh), kept here so the experiment
# does not depend on a gitignored artifacts directory.
# =============================================================================
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
uptime
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv,noheader
free -m
echo "--- compute apps ---"
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
echo "--- top cpu ---"
ps -eo pid,pcpu,etimes,comm --sort=-pcpu | head -12
