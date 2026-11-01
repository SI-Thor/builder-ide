#!/usr/bin/env bash
# Watch the **live** guard for an hour, with the real seats.
#
# The guard is the daemon's rule for work that is outside any lease: when the
# box falls below the emergency floor, or when the box loses memory faster
# than the leases can explain it, it stops the biggest unleased process.
# Round 12 proved the rule works against a test daemon and a scripted
# memory curve. This is the other half of the claim: with the real seats'
# real work on the box, does it stay quiet, and does it stay correct?
#
# The watcher does not touch the box. It reads /proc/meminfo, asks the
# daemon for its status, and reads the daemon's own log for the guard's
# events. Nothing is started, nothing is stopped.
#
# Usage: watch-guard.sh <output-file> [samples] [interval-seconds]
#
# What it needs: the daemon running, and `thor-admit` on PATH (or in
# ~/lm-tools). What it does: reads /proc and the daemon's log. It allocates
# nothing and takes nothing. How long it takes: as long as you ask it to —
# a minute per sample, 62 samples for the hour of round 13.
set -uo pipefail

OUT="${1:?output file}"
SAMPLES="${2:-60}"
INTERVAL="${3:-60}"
STATE="$HOME/.local/state/thor-admit"
LOG="$STATE/daemon.log"
ADMIT="$HOME/lm-tools/thor-admit"

mkdir -p "$(dirname "$OUT")"
: > "$OUT"

# The byte offset we have already read, so each sample reports only the
# events that are new since the last one.
mark=0
[ -f "$LOG" ] && mark=$(stat -c %s "$LOG" 2>/dev/null || echo 0)

{
  echo "# thor-admit round 13 — the live guard, watched"
  echo "# started $(date -Is)  host $(hostname)"
  echo "# daemon pid(s): $(pgrep -f 'thor-admit daemon' | tr '\n' ' ')"
  echo "# daemon started at: $(grep -m1 '"event":"daemon.started"' "$LOG" | tail -1 | cut -c1-120)"
  echo "# samples: $SAMPLES every ${INTERVAL}s"
  echo "# protected.txt:"
  sed 's/^/#   /' "$STATE/protected.txt" 2>/dev/null
  echo "#"
} >> "$OUT"

for i in $(seq 1 "$SAMPLES"); do
  ts=$(date -Is)
  read -r avail total swapfree <<<"$(awk '/^MemAvailable/{a=$2}/^MemTotal/{t=$2}/^SwapFree/{s=$2}END{print a, t, s}' /proc/meminfo)"
  load=$(cut -d' ' -f1-3 /proc/loadavg)

  size=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
  news=""
  if [ "$size" -gt "$mark" ]; then
    news=$(tail -c "+$((mark + 1))" "$LOG" | grep -E '"event":"(guard\.|lease\.preempt)' | sed 's/.*"event":"\([^"]*\)".*/\1/' | sort | uniq -c | tr '\n' ';')
    mark=$size
  fi

  status="$($ADMIT status 2>&1)"
  leases=$(printf '%s\n' "$status" | sed -n 's/^leases: \([0-9]*\).*/\1/p' | head -1)
  queue=$(printf '%s\n' "$status" | sed -n 's/^queue: \([0-9]*\).*/\1/p' | head -1)
  guardline=$(printf '%s\n' "$status" | grep -i 'guard' | tr '\n' ';')

  printf '%s avail_kb=%s total_kb=%s swapfree_kb=%s load=%s leases=%s queue=%s new_events=[%s] guard=[%s]\n' \
    "$ts" "$avail" "$total" "$swapfree" "$load" "${leases:-?}" "${queue:-?}" "$news" "$guardline" >> "$OUT"

  # Every fifth sample, the box's biggest processes: the guard's candidate
  # set. Seeing them is how a false positive (or a near miss) is noticed.
  if [ $((i % 5)) -eq 0 ]; then
    {
      echo "--- top processes at $ts ---"
      python3 - "$status" <<'PY'
import os, sys
status = sys.argv[1]
leased = set()
for line in status.splitlines():
    line = line.strip()
    if line.startswith("#") and "pid" in line:
        for tok in line.split():
            if tok.isdigit():
                leased.add(int(tok))
                break
rows = []
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    try:
        with open(f"/proc/{pid}/statm") as fh:
            rss_pages = int(fh.read().split()[1])
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        continue
    rss = rss_pages * 4096
    if rss < 512 * 1024 * 1024:
        continue
    rows.append((rss, pid, pid in leased, cmd[:110]))
rows.sort(reverse=True)
for rss, pid, is_leased, cmd in rows[:10]:
    tag = "leased" if is_leased else "UNLEASED"
    print(f"  {rss/2**30:6.2f}G pid={pid:<7} {tag:9} {cmd}")
PY
    } >> "$OUT" 2>&1
  fi

  sleep "$INTERVAL"
done

{
  echo "# finished $(date -Is)"
  echo "# protected.txt at the end:"
  sed 's/^/#   /' "$STATE/protected.txt" 2>/dev/null
  echo "# guard events in the whole log:"
  grep -E '"event":"guard\.' "$LOG" | sed 's/^/#   /'
} >> "$OUT"

echo "guard watch finished: $OUT"
