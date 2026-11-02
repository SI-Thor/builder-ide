#!/bin/bash
# run_bw_glb.sh — task 2 of exp-ingame-phase2: put our GLBs through
# build-world's three.js kit (capture harness + pixel gate) and record timings.
#
# Run from anywhere. Needs the kit installed first:
#   (cd third_party/build-world/skills/build-world/engines/threejs && npm ci)
#
# Nothing is installed system-wide; node_modules stays the kit's own. The two
# GLBs are SYMLINKED from where they already live (the SimReady box is CC-BY-4.0
# and is never copied, not into the worktree and not into any report).
#
# Five steps, and the order matters: the kit's capture tool cannot shutter the
# heavy scene (page.screenshot: Timeout 30000ms exceeded on the 5.8 M-triangle
# agent-world room under SwiftShader/software GL — recorded in shots/report.json)
# but it CAN shutter the box, so the box work comes first and the heavy scene is
# measured afterwards with a long shutter instead of being worked around:
#
#   1. probe      — load report per GLB: loadMs, meshes, triangles, AABB,
#                   bottomOffset (the same grounding measure topview reports)
#   2. capture    — the kit's review set, all three named shots, one session
#                   (non-fatal on purpose: the room shot's shutter failure is
#                   the result, and it lands in shots/report.json)
#   3. framecost  — per-frame render ms per shot + the same screenshot with a
#                   180 s shutter (bw-glb-scene/framecost.mjs), so the failure
#                   is separated into "the frame is slow" vs "the shutter is short"
#   4. baseline   — the two box shots twice (determinism runs) and once under
#                   ?lightdim=1 (the deliberate-change control)
#   5. imagediff  — run1 vs run2 must be identical; run1 vs lightdim must differ
#
# Wall time ~5-10 min on the Thor (SwiftShader = software GL, the box is aarch64
# and has no GPU in Chromium's view). Results in results/bw-glb/.
set -uo pipefail

SC=$(cd "$(dirname "$0")" && pwd)             # .../docs/lab/ingame-phase2-scripts
REPO=$(cd "$SC/../../.." && pwd)                 # the ingame-phase2 worktree
KIT="$REPO/third_party/build-world/skills/build-world/engines/threejs"
BWL="$REPO/third_party/bw-glb"                # scratch scene dir (gitignored)
OUT="$SC/results/bw-glb"
export PATH="$HOME/.nvm/versions/node/v24.22.2/bin:$PATH"

step() { echo; echo "=== $1 ==="; cut -d' ' -f1-3 /proc/loadavg; }

rm -rf "$OUT"   # fresh results dir: no stale PNG may leak into an imagediff gate
mkdir -p "$BWL/assets" "$OUT"
: > "$OUT/exits.txt"
cp "$SC/bw-glb-scene/index.html" "$SC/bw-glb-scene/main.js" \
   "$SC/bw-glb-scene/vite.config.js" "$SC/bw-glb-scene/probe.mjs" \
   "$SC/bw-glb-scene/framecost.mjs" "$BWL/"
ln -sfn "$KIT/node_modules" "$BWL/node_modules"
ln -sfn "$HOME/lm-wt/simready-survey/data/glb/box_long_a08.glb" "$BWL/assets/box_long_a08.glb"
ln -sfn "$HOME/lm-wt/world-stream-scratch/bakeA/source_textured.glb" "$BWL/assets/books_room.glb"

cd "$BWL"
step "probe (load report: ms, meshes, triangles, bounds, bottomOffset)"
/usr/bin/time -f "TIME probe: %e s, maxrss %M KB" \
  node probe.mjs --harness="$KIT/tools/lib/harness.mjs" --port=5199 --out="$OUT/asset-report.json"
echo "probe exit=$?" >> "$OUT/exits.txt"

cd "$KIT"
step "capture (the kit's review set, all three shots, one browser session)"
# --settle=24, not the kit's 90: the review set is a look, not the gate, and the
# room shot costs ~3 s per frame on software GL (see framecost.json)
/usr/bin/time -f "TIME capture: %e s, maxrss %M KB" \
  node tools/capture.mjs --root="$BWL" --port=5199 --out="$OUT/shots" --w=960 --h=540 --settle=24
echo "capture exit=$?" >> "$OUT/exits.txt"

step "framecost (per-frame render ms + the same screenshot with a 180 s shutter)"
cd "$BWL"   # the page being costed is OURS (the two GLBs), not the kit's example
/usr/bin/time -f "TIME framecost: %e s, maxrss %M KB" \
  node "$SC/bw-glb-scene/framecost.mjs" --harness="$KIT/tools/lib/harness.mjs" \
     --port=5199 --out="$OUT/framecost.json"
echo "framecost exit=$?" >> "$OUT/exits.txt"
cd "$KIT"

step "baseline A (box shots, bit-comparable run 1)"
/usr/bin/time -f "TIME baselineA: %e s, maxrss %M KB" \
  node tools/baseline.mjs --root="$BWL" --port=5199 --out="$OUT/base-run1" \
     --shots=box-wide,box-detail --settle=90
echo "baselineA exit=$?" >> "$OUT/exits.txt"

step "baseline B (same page state again: determinism control)"
/usr/bin/time -f "TIME baselineB: %e s, maxrss %M KB" \
  node tools/baseline.mjs --root="$BWL" --port=5199 --out="$OUT/base-run2" \
     --shots=box-wide,box-detail --settle=90
echo "baselineB exit=$?" >> "$OUT/exits.txt"

step "baseline C (?lightdim=1: the deliberate-change control)"
/usr/bin/time -f "TIME baselineC: %e s, maxrss %M KB" \
  node tools/baseline.mjs --root="$BWL" --port=5199 --out="$OUT/base-lightdim" \
     --shots=box-wide,box-detail --settle=90 --query=lightdim=1
echo "baselineC exit=$?" >> "$OUT/exits.txt"

step "pixel gate: run1 vs run2 (must be identical)"
node tools/imagediff.mjs --a="$OUT/base-run1" --b="$OUT/base-run2" --write-diff | tee "$OUT/diff-run1-run2.json"
echo "diff-run1-run2 exit=$?" >> "$OUT/exits.txt"

step "pixel gate: run1 vs lightdim (must differ)"
node tools/imagediff.mjs --a="$OUT/base-run1" --b="$OUT/base-lightdim" --write-diff | tee "$OUT/diff-lightdim.json"
echo "diff-lightdim exit=$?" >> "$OUT/exits.txt"

echo "done; results in $OUT"