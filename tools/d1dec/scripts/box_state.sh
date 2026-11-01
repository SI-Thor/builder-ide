#!/usr/bin/env bash
# Record the state of the box: the memory, the GPU, the load, and the
# other seats' processes. The measurements on a shared box are only
# meaningful with the box's state next to them.
set -u
OUT="${1:-}"

{
  echo "=== box state $(date -Is) ==="
  echo "loadavg: $(cat /proc/loadavg)"
  echo "--- memory ---"
  free -g
  echo "--- nvidia-smi ---"
  nvidia-smi --query-compute-apps=pid,used_memory --format=csv 2>/dev/null || nvidia-smi | tail -12
  echo "--- other llama / seat processes ---"
  ps -eo pid,rss,vsz,args --sort=-rss | grep -E "llama-server|llama-|serve-|python.*serve|blender|infinigen" | grep -v grep | head -12
  echo "--- thor-admit leases ---"
  "$HOME/lm-tools/thor-admit" status 2>&1 | head -20
} > "${OUT:-/dev/stdout}"

[ -n "$OUT" ] && echo "wrote $OUT"
