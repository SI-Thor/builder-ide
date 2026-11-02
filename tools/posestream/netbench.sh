#!/usr/bin/env bash
# Round 2: the pose stream on a real (simulated) network.
#
#   ./netbench.sh              # the whole matrix: the baseline, the network, and each
#                              # carried-over idea measured on its own
#   TICKS=600 ./netbench.sh    # a shorter run (the same shape, fewer seconds)
#   SEED=12345 ./netbench.sh   # a different world (the same code path)
#
# One run is 60 s of world time at 60 Hz with the same 64 subscribers as round 1. The
# crate uses the Rust standard library only: no network access, no system installs.
#
# Every run writes runs/<name>.json and runs/<name>.txt (the full log). The summary at the
# end is the table in the README.
set -euo pipefail
cd "$(dirname "$0")"

SEED="${SEED:-209937112109620}"   # 0xBEEF_CAFE_1234, the seed round 1 used
TICKS="${TICKS:-3600}"            # 60 s at 60 Hz
MODE="${MODE:-predictive}"
TEAM="${TEAM:-mcode}"
DELAY_MIN="${DELAY_MIN:-2}"       # ms
DELAY_MAX="${DELAY_MAX:-12}"      # ms
JITTER="${JITTER:-1.5}"           # ms, +/- around the delay
HYSTERESIS="${HYSTERESIS:-8}"     # m, the exit hysteresis the other entry used

mkdir -p runs

echo "== build (offline, std only) =="
cargo build --release --offline

echo
echo "== tests =="
cargo test --release --offline 2>&1 | tail -3

BIN=./target/release/posestream
SUMMARY=runs/SUMMARY.txt
: > "$SUMMARY"

# run <name> <extra args...>
run() {
    local name="$1"; shift
    echo
    echo "== $name: $* =="
    $BIN --seed "$SEED" --ticks "$TICKS" --mode "$MODE" --team "$TEAM" \
         --out "runs/$name.json" --log "runs/$name.txt" "$@" | sed 's/^/   /'
}

summarise() {
    local name="$1"
    python3 - "$name" <<'PY' >> "$SUMMARY"
import json, sys
name = sys.argv[1]
r = json.load(open("runs/%s.json" % name))
print("%-10s %9s %9s %8s %8s %8s %7s %7s %7s %8s" % (
    name,
    r["bytes_per_s_per_subscriber_mean"],
    r["bytes_per_s_per_subscriber_sent_mean"],
    r["emitter_work_ms_per_tick_p95"],
    r["delivery_latency_ms_p95"],
    r["reconstruction_errors"],
    r["resyncs"],
    r["keyframes"],
    r["mirror_mismatches"],
    r["max_reconstruction_error_mm"],
))
PY
}

{
printf "%-10s %9s %9s %8s %8s %8s %7s %7s %7s %8s\n" \
  run bytes/s sent "work p95" "lat p95" errors resyncs keys mirrors "err mm"
} >> "$SUMMARY"

# ---------------------------------------------------------------- the matrix

# 1. the loopback: round 1's conditions, and the check that the bytes have not changed.
run base --net off
summarise base

# 2. the network, with the delay alone and with the two loss rates the brief asks for.
run net0 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0
summarise net0
run net005 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.005
summarise net005
run net02 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.02
summarise net02

# 3. (a) the back-dating, off: the receiver anchors at the arrival instead of at the
#    packet's tick. Measured on its own, on both loss rates.
run naive005 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.005 --backdate off
summarise naive005
run naive02 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.02 --backdate off
summarise naive02

# 4. (b) the exit hysteresis, on the network with no loss (the cleanest A/B) and at 0.5%.
#    The margin is swept: the trade is between the leaves it saves and the objects it
#    holds outside the region.
for H in 0 2 4 8 16; do
    run "hys${H}_0" --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0 --hysteresis "$H"
    summarise "hys${H}_0"
done
run hys8 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.005 --hysteresis "$HYSTERESIS"
summarise hys8

# 5. (c) the 2-byte evicts, on the network with no loss (the cleanest A/B).
run ev2_0 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0 --evict2 on
summarise ev2_0

# 6. the configuration the README keeps: the back-dating, and whatever the hysteresis
#    sweep says.
run keep --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.005
summarise keep
run keep02 --net on --delay-min "$DELAY_MIN" --delay-max "$DELAY_MAX" --jitter "$JITTER" --loss 0.02
summarise keep02

echo
echo "== the summary =="
cat "$SUMMARY"
