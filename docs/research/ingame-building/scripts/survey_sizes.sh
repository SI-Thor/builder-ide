#!/bin/bash
# survey_sizes.sh — reproducible size/count table for every repo cloned under src/
cd /home/proart/lm-wt/ingame-building/src || exit 1
printf "%-24s %10s %12s %s\n" REPO WORKTREE_KB TRACKED_FILES LAST_COMMIT
tot_kb=0; tot_files=0
for d in */; do
  d=${d%/}
  [ -d "$d/.git" ] || continue
  kb=$(du -sk --exclude=.git "$d" | cut -f1)
  files=$(git -C "$d" ls-files | wc -l)
  last=$(git -C "$d" log -1 --date=short --format='%ad')
  printf "%-24s %10s %12s %s\n" "$d" "$kb" "$files" "$last"
  tot_kb=$((tot_kb+kb)); tot_files=$((tot_files+files))
done
printf "%-24s %10s %12s\n" TOTAL "$tot_kb" "$tot_files"
