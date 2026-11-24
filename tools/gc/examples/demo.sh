#!/usr/bin/env bash
# A worked example of the general contractor at work, end to end.
#
#   ./examples/demo.sh
#
# It writes into a scratch directory, so it never touches the repo's ledger.
# Every check that runs here is real: the goal line is a command the demo
# actually satisfies (a file the "carpet" lands in), and the close re-runs it
# instead of taking the seat's word.
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
# bytes every time. GC_NOW=1793640000 is 2026-11-02T17:20:00Z, the moment
# the award lands; the checkpoints below use --at to move the clock forward.
export GC_NOW=1793640000

say() { printf '\n=== %s\n' "$1"; }

say "the general contractor writes the job, with clauses in the contract"
$GC job new \
  --title "lay 40 square metres of carpet in the lobby" \
  --class build-feature \
  --scope "Lay 40 square metres of carpet in the lobby, seams cut, edges trimmed, underlay down." \
  --accept-cmd "test -f lobby/carpet-laid" \
  --estimate-min 120 \
  --deadline-min 480 \
  --penalty-per-day-min 45 \
  --clause "seam_count <= 40 penalty 30" \
  --clause "waste_pct <= 10 window 480 penalty 15"

say "the seats bid, each from its own track record"
$GC bid --job J001 --sub zcode
$GC bid --job J001 --sub mcode
$GC bid --job J001 --sub zcode --submit                  # zcode bids from its record
$GC bid --job J001 --sub mcode --crew-min 160 --submit   # mcode bids by hand

say "the general contractor awards the job"
$GC award --job J001 --auto

say "the subcontractor reports its burn; the forecast warns early"
# 60 crew-min in 45 job-min: the forecast projects past the stop line before
# the deadline even though only 40% of the bid is spent.
$GC checkpoint --job J001 --crew-used-min 60 --at 2026-11-02T18:05:00Z --note "underlay down"

say "the burn passes 80% with the goal line not passing: stop and report"
# The acceptance command runs here too — the carpet is not down yet, so the
# check fails, and the stop rule bites.
$GC checkpoint --job J001 --crew-used-min 121 --at 2026-11-02T18:20:00Z --note "seams cut, not trimmed"

say "the general contractor re-scopes the job"
$GC change-order --job J001 --reason "the lobby had to be cleared first" --add-crew-min 60 --add-job-min 240 \
  --at 2026-11-02T18:30:00Z

say "the carpet goes down (the thing the goal line can check)"
mkdir -p lobby
touch lobby/carpet-laid

say "the subcontractor finishes: the check passes, the clauses are measured"
$GC checkpoint --job J001 --crew-used-min 165 --at 2026-11-02T19:50:00Z \
  --metric seam_count=38 --metric waste_pct=8

say "the close re-runs the goal line itself and takes the clause penalties"
$GC close --job J001 --crew-min 165 --at 2026-11-02T19:55:00Z \
  --metric seam_count=38 --metric waste_pct=8 --goal-line "test -f lobby/carpet-laid exits 0"

say "a lying close is refused: the flag cannot say what the command decides"
$GC job new --title "the rush job" --class build-feature --scope "s" \
  --accept-cmd "test -f lobby/carpet-laid" --estimate-min 60 --deadline-min 480 >/dev/null
$GC bid --job J002 --sub zflash --crew-min 60 --submit >/dev/null
$GC award --job J002 --auto >/dev/null
rm lobby/carpet-laid   # the lobby is bare again, whatever the seat claims
$GC close --job J002 --crew-min 30 --accepted || true

say "the contract, as the seat would have read it"
$GC brief --job J001

say "the book"
$GC report

say "the ledger is intact"
$GC verify
