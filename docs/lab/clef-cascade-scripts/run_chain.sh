#!/usr/bin/env bash
# C1e (paced flash alone) -> C1d (flash + clef-27B together) -> C4 (improver).
# Run in order: the rate experiments must not overlap, and C4 must not run
# while a rate cell is measuring the ceiling.
set -u
cd /home/proart/lm-wt/clef-cascade/scripts
L=/home/proart/lm-wt/clef-cascade/logs

echo "=== C1e: flash alone, paced at 30 rps, 120 s window ==="
python3 c1c_rate_ceiling.py --out c1e-paced-allowance.json \
  --seconds 120 --quiet 150 --pace 30 --cells flash:q1:32 2>&1 | tee "$L/c1e.log"

echo "=== C1d: flash + clef-27B together, paced at 40 rps each ==="
python3 c1d_mixed.py --seconds 60 --quiet 150 --pace 40 --concurrency 16 \
  2>&1 | tee "$L/c1d.log"

echo "=== C4: cloud improver, 8 rounds ==="
python3 c4_improver.py --rounds 8 2>&1 | tee "$L/c4.log"

echo "=== chain done ==="
