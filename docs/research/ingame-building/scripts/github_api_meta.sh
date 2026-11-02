#!/bin/bash
# api_meta.sh — read-only GitHub API metadata for the repos under investigation.
# Writes one JSON blob per repo into .research/api/. No writes to GitHub, no builds.
set -u
OUT=/home/proart/lm-wt/ingame-building/.research/api
repos=(
  "topviewai/topview-3d-builder"
  "thrixel/build-world"
  "3DSceneAgent/Vibe3DScene"
  "FugthChat/MEP-SANDBOX-ENGINE"
  "GlaireDaggers/Open-World-Builder"
  "TorqueGameEngines/Torque3D"
  "ProwlEngine/Prowl"
)
for r in "${repos[@]}"; do
  slug=$(echo "$r" | tr '/' '_')
  echo "=== $r ==="
  gh api "repos/$r" > "$OUT/${slug}_repo.json" 2>/dev/null \
    && echo "  repo: ok" || echo "  repo: FAIL"
  gh api "repos/$r/languages" > "$OUT/${slug}_lang.json" 2>/dev/null || echo "  lang: FAIL"
  gh api "repos/$r/contributors?per_page=1&anon=1" -i 2>/dev/null | grep -i '^link:' > "$OUT/${slug}_contributors.link"
  gh api "repos/$r/commits?per_page=1" -i 2>/dev/null | grep -i '^link:' > "$OUT/${slug}_commits.link"
  gh api "repos/$r/releases?per_page=5" > "$OUT/${slug}_releases.json" 2>/dev/null || echo "  rel: FAIL"
  gh api "repos/$r/tags?per_page=10" > "$OUT/${slug}_tags.json" 2>/dev/null || echo "  tags: FAIL"
  # open issues and open PRs counted separately (repo.open_issues_count mixes both)
  gi=$(gh api "search/issues?q=repo:$r+type:issue+state:open" --jq '.total_count' 2>/dev/null)
  gp=$(gh api "search/issues?q=repo:$r+type:pr+state:open" --jq '.total_count' 2>/dev/null)
  gc=$(gh api "search/issues?q=repo:$r+type:issue+state:closed" --jq '.total_count' 2>/dev/null)
  echo "  open_issues=$gi open_prs=$gp closed_issues=$gc"
  echo "{\"open_issues\":$gi,\"open_prs\":$gp,\"closed_issues\":$gc}" > "$OUT/${slug}_issues.json"
done
echo "=== API PASS DONE ==="
