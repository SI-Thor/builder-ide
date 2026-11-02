#!/bin/bash
# github_api_meta_phase1b.sh — read-only GitHub REST metadata for the phase-1b repositories.
# Writes one JSON blob per repo into .research/api1b/. No writes to GitHub, no builds.
set -u
OUT=/home/proart/lm-wt/ingame-building/.research/api1b
mkdir -p "$OUT"
repos=(
  "NVIDIA/game-agent-sdk"
  "NVIDIA/ACE"
  "NVIDIA-RTX/NVIGI"
  "NVIDIA-RTX/NVIGI-Core"
  "NVIDIA-RTX/nvigi_godot_extension"
  "godotengine/godot"
  "NVIDIA/NVTX"
  "open-telemetry/opentelemetry-cpp"
  "open-telemetry/opentelemetry-python"
  "gorakhargosh/watchdog"
  "input-leap/input-leap"
  "grpc/grpc"
  "vllm-project/vllm"
  "comfyanonymous/ComfyUI"
  "NVIDIA/nsight-python"
)
for r in "${repos[@]}"; do
  slug=$(echo "$r" | tr '/' '_')
  echo "=== $r ==="
  gh api "repos/$r" > "$OUT/${slug}_repo.json" 2>/dev/null && echo "  repo: ok" || echo "  repo: FAIL"
  gh api "repos/$r/languages" > "$OUT/${slug}_lang.json" 2>/dev/null || echo "  lang: FAIL"
  gh api "repos/$r/contributors?per_page=1&anon=1" -i 2>/dev/null | grep -i '^link:' > "$OUT/${slug}_contributors.link"
  gh api "repos/$r/commits?per_page=1" -i 2>/dev/null | grep -i '^link:' > "$OUT/${slug}_commits.link"
  gh api "repos/$r/releases?per_page=5" > "$OUT/${slug}_releases.json" 2>/dev/null || echo "  rel: FAIL"
  echo "  open_issues=$(gh api "search/issues?q=repo:$r+type:issue+state:open" --jq '.total_count' 2>/dev/null)"
done
echo "=== PHASE 1b API PASS DONE ==="
