#!/usr/bin/env bash
# Rebuild a sweep scene's geometry so the critic's mesh half has a real mesh.
#
# The overnight sweep deletes its .blend files when a scene finishes (that is
# the sweep's disk policy, and the sweep is read-only to this seat). A member
# whose defect lives in the *geometry* — wrong scale, a hollow shell, geometry
# cut by the frame — needs that scene's mesh, so this script re-runs the
# sweep's own coarse + fine stages, with the sweep's own argv, into a scratch
# tree. The sweep itself is never written to.
#
# Same seed + same gin + same code = the same scene, so the rebuilt mesh
# belongs to the render the sweep already produced. That is *checked* rather
# than assumed: the coarse assets are the scene's terrain and the sweep kept
# its copy, so the two are compared byte-for-byte afterwards and the result is
# reported.
#
# Usage:
#   core/critic/rebuild_mesh.sh <scene>:<seed> [<scene>:<seed> ...]
#
# Environment:
#   CRITIC_MESH_ROOT   where the rebuilt scenes go (default ~/lm-critic/scenes)
#   CRITIC_SWEEP_ROOT  the sweep to compare against (default the Thor's)
set -uo pipefail

REPO="${CRITIC_INFINIGEN_REPO:-/home/caseydigennaro/src/infinigen-thor}"
OUT="${CRITIC_MESH_ROOT:-/home/caseydigennaro/lm-critic/scenes}"
SWEEP="${CRITIC_SWEEP_ROOT:-$REPO/outputs/sweep}"
PY="$REPO/.venv/bin/python"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <scene>:<seed> [<scene>:<seed> ...]" >&2
  exit 2
fi

cd "$REPO" || exit 1
mkdir -p "$OUT"

log() { printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$*"; }

for spec in "$@"; do
  scene="${spec%%:*}"
  seed="${spec##*:}"
  base="$OUT/${scene}-s${seed}"
  if [ -f "$base/fine/scene.blend" ]; then
    log "$scene-s$seed already built"
    continue
  fi
  mkdir -p "$base"

  t0=$(date +%s)
  if ! "$PY" -m infinigen_examples.generate_nature --seed "$seed" -g "$scene.gin" simple.gin \
        --task coarse --output_folder "$base/coarse" >"$base/coarse.log" 2>&1; then
    log "$scene-s$seed coarse FAILED (see $base/coarse.log)"
    continue
  fi
  t1=$(date +%s)

  if ! "$PY" -m infinigen_examples.generate_nature --seed "$seed" -g "$scene.gin" simple.gin \
        --task populate fine_terrain --input_folder "$base/coarse" --output_folder "$base/fine" \
        >"$base/fine.log" 2>&1; then
    log "$scene-s$seed fine FAILED (see $base/fine.log)"
    continue
  fi
  t2=$(date +%s)

  # Same scene as the sweep's? The coarse assets are the scene's terrain, and
  # the sweep kept its copy -- compare them byte-for-byte.
  same="no-sweep-copy"
  if [ -d "$SWEEP/${scene}-s${seed}/coarse/assets" ]; then
    if diff -r -q "$SWEEP/${scene}-s${seed}/coarse/assets" "$base/coarse/assets" >/dev/null 2>&1; then
      same="identical"
    else
      same="DIFFERENT"
    fi
  fi

  log "$scene-s$seed ok coarse=$((t1-t0))s fine=$((t2-t1))s assets=$same"
done

log "rebuild-mesh done"
