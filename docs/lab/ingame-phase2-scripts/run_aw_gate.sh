#!/bin/bash
# run_aw_gate.sh — task 2's prototype, the one piece worth keeping from
# build-world's three.js kit (the capture contract + the baseline/imagediff
# pixel gate) grafted onto a COPY of the agent-world viewer.
#
# The kit has no editing gizmos, no placement and no undo (checked: nothing in
# skills/build-world/engines/threejs matches gizmo/undo/TransformControls/drag
# outside node_modules). What it does have, and what our viewers lack, is the
# assertion "the same scene renders the same way twice". This runs that
# assertion over the real viewer page.
#
#   1. the viewer is COPIED (third_party/aw-viewer, gitignored), node_modules
#      symlinked from the live copy; ~/lm-wt/agent-world/viewer is untouched
#   2. one <script> tag is added to the COPY's page (public/gate-shim.js): the
#      build-world capture contract, without editing the viewer's own code
#   3. the copy logs into the live world as a second spectator ("Watcher2gw")
#      so the live viewer's watcher is not kicked by a duplicate login; the copy
#      is killed at the end of the run (a few minutes of second-spectator time)
#   4. the KIT's own tools then drive the page: capture.mjs (review set),
#      baseline.mjs twice (drift control), baseline.mjs with ?tilt=1 (the
#      deliberate-change control), imagediff.mjs for both gates
#
# Needs: the kit's npm ci once (third_party/build-world/skills/build-world/
# engines/threejs), the agent-world viewer's own node_modules (symlinked), and
# the live Minecraft world on 192.168.0.78:25565. Wall time ~3-6 min.
# Results in results/aw-viewer-gate/.
set -uo pipefail

SC=$(cd "$(dirname "$0")" && pwd)             # .../docs/lab/ingame-phase2-scripts
REPO=$(cd "$SC/../../.." && pwd)                 # the ingame-phase2 worktree
KIT="$REPO/third_party/build-world/skills/build-world/engines/threejs"
SRC="$HOME/lm-wt/agent-world/viewer"          # read-only source for the copy
CP="$REPO/third_party/aw-viewer"               # the copy (gitignored)
OUT="$SC/results/aw-viewer-gate"
export PATH="$HOME/.nvm/versions/node/v24.22.2/bin:$PATH"
PORT=8288

step() { echo; echo "=== $1 ==="; cut -d' ' -f1-3 /proc/loadavg; }

rm -rf "$OUT"   # fresh results dir: no stale PNG may leak into an imagediff gate
mkdir -p "$OUT"
: > "$OUT/exits.txt"
rsync -a --delete --exclude node_modules "$SRC/" "$CP/"
ln -sfn "$SRC/node_modules" "$CP/node_modules"
cp "$SC/aw-viewer-gate/gate-shim.js" "$CP/public/gate-shim.js"

# ONE line in the COPY only: the shim loads before the viewer's own client.
python3 - "$CP/public/index.html" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
tag = '<script src="gate-shim.js"></script>'
if tag not in s:
    s = s.replace('<body>', '<body>\n' + tag, 1)
open(p, 'w').write(s)
PY

# The copy gets its own name: a second login as "Watcher" would kick the live
# viewer's watcher out of the world.
sed -i "s/name: 'Watcher',/name: 'Watcher2gw',/" "$CP/src/server.js"

step "start the viewer copy (second spectator on the live world)"
AW_VIEW_PORT=$PORT AW_BOT_LOG="$OUT/bots.jsonl" \
  setsid nohup node "$CP/src/server.js" > "$OUT/server.log" 2>&1 < /dev/null &
trap 'pkill -f "$CP/src/server.js" 2>/dev/null || true' EXIT

for i in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$PORT/view-plan" > "$OUT/view-plan.json" 2>/dev/null && break
  sleep 1
done
cat "$OUT/view-plan.json" 2>/dev/null || echo "server did not answer on :$PORT (see server.log)"
curl -sf "http://127.0.0.1:$PORT/status" > "$OUT/status.json" 2>/dev/null || true

cd "$KIT"
step "shim diagnostics (did the shim hook, and what the page draws)"
node "$SC/aw-viewer-gate/shim-diag.mjs" --harness="$KIT/tools/lib/harness.mjs" \
   --port=$PORT --out="$OUT/shim-diag.json" --wait=25000
echo "shim-diag exit=$?" >> "$OUT/exits.txt"
step "capture (the kit's review set over the viewer page)"
node tools/capture.mjs --root="$CP" --port=$PORT --out="$OUT/shots" --w=960 --h=540 --settle=8
echo "capture exit=$?" >> "$OUT/exits.txt"

step "baseline A (viewer shots, run 1)"
node tools/baseline.mjs --root="$CP" --port=$PORT --out="$OUT/base-run1" \
   --settle=8
echo "baselineA exit=$?" >> "$OUT/exits.txt"

step "baseline B (run 2: world drift + renderer noise)"
node tools/baseline.mjs --root="$CP" --port=$PORT --out="$OUT/base-run2" \
   --settle=8
echo "baselineB exit=$?" >> "$OUT/exits.txt"

step "baseline C (?tilt=1: the deliberate-change control)"
node tools/baseline.mjs --root="$CP" --port=$PORT --out="$OUT/base-tilt" \
   --settle=8 --query=tilt=1
echo "baselineC exit=$?" >> "$OUT/exits.txt"

step "pixel gate: run1 vs run2 (live world: drift + noise, not a gate failure)"
node tools/imagediff.mjs --a="$OUT/base-run1" --b="$OUT/base-run2" --write-diff | tee "$OUT/diff-run1-run2.json"
echo "diff-run1-run2 exit=$?" >> "$OUT/exits.txt"

step "pixel gate: run1 vs tilt (must differ)"
node tools/imagediff.mjs --a="$OUT/base-run1" --b="$OUT/base-tilt" --write-diff | tee "$OUT/diff-tilt.json"
echo "diff-tilt exit=$?" >> "$OUT/exits.txt"

step "stop the copy (the second spectator leaves the world)"
pkill -f "$CP/src/server.js" 2>/dev/null || true
trap - EXIT
echo "done; results in $OUT"