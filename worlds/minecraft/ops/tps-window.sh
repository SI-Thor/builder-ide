#!/usr/bin/env bash
# ops/tps-window.sh — the server's own tick numbers for a window of
# paper.log, reconstructed from the console's timestamped answers.
#
# The steady run asks the console "tps" every 30 s; its output lands in
# paper.log wrapped in ANSI colour, which the live parse could not
# read. The answers are all there, timestamped, so the numbers are
# recovered afterwards rather than guessed — and this script is the
# reproducible step beside them.
#
#   ops/tps-window.sh <from-utc> <to-utc>   # e.g. 2026-11-02T05:22:00 2026-11-02T05:53:00
set -euo pipefail

. "$(dirname "$0")/env.sh"

FROM="${1:?usage: ops/tps-window.sh <from> <to> (UTC, ISO minutes)}"
TO="${2:?usage: ops/tps-window.sh <from> <to> (UTC, ISO minutes)}"

python3 - "$AW_LOG_DIR/paper.log" "$FROM" "$TO" <<'PY'
import re, statistics, subprocess, sys
from datetime import datetime, timedelta

path, lo, hi = sys.argv[1], sys.argv[2], sys.argv[3]
# Paper's console lines carry no date, only local HH:MM:SS — so the
# requested UTC window is turned into local wall-clock times with the
# box's own offset, and lines are matched by time of day.
offset = int(subprocess.run(["date", "+%z"], capture_output=True, text=True).stdout.strip()[:3])
def to_local_text(utc_text):
    t = datetime.strptime(utc_text, "%Y-%m-%dT%H:%M:%S") + timedelta(hours=offset)
    return t.strftime("%H:%M:%S")
lo_local, hi_local = to_local_text(lo), to_local_text(hi)

ansi = re.compile(r"\x1b\[[0-9;]*m")
stamp = re.compile(r"^\[(\d{2}:\d{2}:\d{2})")
tps = re.compile(r"TPS from last 1m, 5m, 15m: ([0-9.]+)")

def in_window(clock):
    if lo_local <= hi_local:
        return lo_local <= clock <= hi_local
    return clock >= lo_local or clock <= hi_local  # the window wraps midnight

rows = []
for line in open(path, encoding="utf-8", errors="replace"):
    m = stamp.match(line)
    if not m or not in_window(m.group(1)):
        continue
    clean = ansi.sub("", line)
    t = tps.search(clean)
    if t:
        rows.append((m.group(1), float(t.group(1))))

if not rows:
    print("no tps answers found in that window")
    sys.exit(1)
values = [v for _, v in rows]
ok = sum(1 for v in values if v >= 19.5)
print(f"samples: {len(rows)}  (local {rows[0][0]} .. {rows[-1][0]}, box offset {offset:+d})")
print(f"min {min(values)}  median {statistics.median(values)}  max {max(values)}")
print(f"{ok}/{len(values)} samples >= 19.5")
below = [f"{at} {v}" for at, v in rows if v < 19.5]
for line in below[:10]:
    print("below:", line)
PY
