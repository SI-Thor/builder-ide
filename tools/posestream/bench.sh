#!/usr/bin/env bash
# Reproduce RESULT.json for the pose stream (Mission B).
#
#   ./bench.sh                  # the scored run: 60 s at 60 Hz, 64 subscribers
#   MODE=direct ./bench.sh      # the plain delta mode, for comparison
#   SEED=12345 ./bench.sh       # a different world (same code path)
#   TICKS=600 ./bench.sh        # a shorter run
#
# No network, no system installs: the crate uses the Rust standard library only.
set -euo pipefail
cd "$(dirname "$0")"

SEED="${SEED:-209937112109620}"   # 0xBEEF_CAFE_1234
TICKS="${TICKS:-3600}"            # 60 s at 60 Hz
MODE="${MODE:-predictive}"        # predictive | direct
TEAM="${TEAM:-mcode}"

echo "== build (offline, std only) =="
cargo build --release --offline

echo
echo "== tests: wire round trip, world determinism, quantisation bound, end to end =="
cargo test --release --offline 2>&1 | tail -3

echo
echo "== scored run: seed $SEED, $TICKS ticks, $MODE mode =="
./target/release/posestream \
    --seed "$SEED" --ticks "$TICKS" --mode "$MODE" --team "$TEAM" \
    --out RESULT.json --log bench_log.txt

echo
echo "== determinism: the same seed must deliver exactly the same bytes =="
mkdir -p runs
./target/release/posestream \
    --seed "$SEED" --ticks "$TICKS" --mode "$MODE" --team "$TEAM" \
    --out runs/RESULT_repeat.json --log runs/bench_log_repeat.txt >/dev/null
a=$(grep -o 'stream digest.*' bench_log.txt | tail -1)
b=$(grep -o 'stream digest.*' runs/bench_log_repeat.txt | tail -1)
if [ "$a" = "$b" ]; then
    echo "OK  $a"
else
    echo "MISMATCH: $a  vs  $b"
    exit 1
fi

echo
echo "== RESULT.json =="
cat RESULT.json
