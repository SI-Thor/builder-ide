#!/usr/bin/env bash
# probe which seeds survive the (upstream) floor-plan solver — the singleroom
# fast config crashes on some seeds with a degenerate shapely polygon
for s in "$@"; do
  log=$(mktemp)
  env PYTHONPATH=pylibs ~/lm-wt/v2-thor/.venv/bin/python scripts/run_solve.py \
    --seed "$s" --arm baseline --stages "" --out /tmp/probe_seed$s.json > "$log" 2>&1
  if [ -f /tmp/probe_seed$s.json ]; then
    wall=$(python3 -c "import json;print(round(json.load(open('/tmp/probe_seed$s.json'))['walls']['solve_rooms'],1))" 2>/dev/null)
    room=$(python3 -c "import json;print(json.load(open('/tmp/probe_seed$s.json'))['meta'].get('n_rooms'))" 2>/dev/null)
    echo "seed $s: OK rooms=${room}s wall=${wall}s"; rm -f /tmp/probe_seed$s.json
  else
    echo "seed $s: FAIL $(grep -m1 'Error' $log | cut -c1-80)"
  fi
  rm -f "$log"
done
