#!/usr/bin/env bash
# A worked example of the general contractor at work, end to end.
#
#   ./examples/demo.sh
#
# It writes into a scratch directory, so it never touches the repo's ledger.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
GC="$ROOT/target/release/gc"
if [ ! -x "$GC" ]; then
  echo "build it first:  cd $ROOT && cargo build --release"
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

# A fixed clock, so the run is reproducible: the same commands write the same
# bytes every time.
export GC_NOW=1793640000

say() { printf '\n=== %s\n' "$1"; }

say "the general contractor writes the job"
$GC job new \
  --title "lay 40 square metres of carpet in the lobby" \
  --class build-feature \
  --scope "Lay 40 square metres of carpet in the lobby, seams cut, edges trimmed, underlay down." \
  --accept-cmd "cargo test --test carpet" \
  --estimate-min 120 \
  --deadline-min 480 \
  --penalty-per-day-min 45

say "the seats bid, each from its own track record"
$GC bid --job J001 --sub zcode
$GC bid --job J001 --sub mcode
$GC bid --job J001 --sub zcode --crew-min 150 --submit   # a seat bids by hand

say "the general contractor awards the job"
$GC award --job J001 --auto

say "the subcontractor reports its burn"
$GC checkpoint --job J001 --crew-used-min 60 --note "underlay down"

say "the burn passes 80% without the goal line: stop and report"
$GC checkpoint --job J001 --crew-used-min 110 --note "seams cut, not trimmed"

say "the general contractor re-scopes the job"
$GC change-order --job J001 --reason "the lobby had to be cleared first" --add-crew-min 60 --add-job-min 240

say "the subcontractor finishes and closes"
$GC checkpoint --job J001 --crew-used-min 150
$GC close --job J001 --crew-min 150 --accepted --goal-line "cargo test --test carpet exits 0"

say "the contract, as the seat would have read it"
$GC brief --job J001

say "the book"
$GC report

say "the ledger is intact"
$GC verify
