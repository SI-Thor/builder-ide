#!/usr/bin/env bash
# ops/community-watch.sh — the unattended community, measured.
#
# The brief's per-hour numbers, sampled every 60 s while the world runs
# itself: projects finished, blocks placed in project scope, issues
# filed/fixed, pauses in force, grief (player builds known), TPS,
# memory. One CSV row per sample; one rollup block per hour into the
# .summary beside it. The playtest note quotes the summary, not the
# CSV, and the CSV is the reproducible record under it.
#
#   ops/community-watch.sh start [tag]   run detached (setsid nohup)
#   ops/community-watch.sh stop
#   ops/community-watch.sh status
#
# The undo: stop. The CSV and summary stay where they are.
set -euo pipefail

. "$(dirname "$0")/env.sh"

TAG="${2:-$(date -u +%Y%m%d)}"
OUT="$AW_LOG_DIR/community-$TAG"
CSV="$OUT.csv"
SUMMARY="$OUT.summary"
PAPER_LOG="$AW_LOG_DIR/paper.log"
BOARD="$AW_RUNTIME/board.json"
PAUSE="$AW_RUNTIME/drift-pause.json"

# The server's console is the tmux pane whose terminal the java process
# was born on (panes get reshuffled across restarts; the steady run of
# 2026-11-02 typed "tps" into a bystander bash for half an hour).
find_console() {
    local java_pid tty pane pty
    java_pid="$(pgrep -f 'paper-.*\.jar' | head -1)"
    [ -n "$java_pid" ] || return 1
    tty="$(ps -o tty= -p "$java_pid" | tr -d ' ')"
    [ -n "$tty" ] || return 1
    while read -r pane pty; do
        if [ "$pty" = "/dev/$tty" ]; then
            echo "$pane"
            return 0
        fi
    done < <(tmux list-panes -a -F "#{session_name}:#{window_index} #{pane_tty}" 2>/dev/null)
    return 1
}

# One sample: the box, the board, the pauses, the reflex.
sample() {
    local CONSOLE MARK TPS STATS MEM LOAD BOARD_JSON PAUSES YIELDS
    CONSOLE="$(find_console || true)"
    TPS=""
    if [ -n "$CONSOLE" ]; then
        MARK=$(wc -c < "$PAPER_LOG" 2>/dev/null || echo 0)
        tmux send-keys -t "$CONSOLE" -l "tps" </dev/null 2>/dev/null || true
        tmux send-keys -t "$CONSOLE" Enter </dev/null 2>/dev/null || true
        sleep 3
        # The console prints the TPS with ANSI colour codes around the
        # numbers, so the colour is stripped before the number is read.
        # Without that, the column was empty for every sample of the
        # first hour (the number is there: "TPS from last 1m, 5m, 15m:
        # <esc>[38;5;10m20.0<esc>[0m").
        TPS=$(tail -c "+$((MARK + 1))" "$PAPER_LOG" 2>/dev/null \
            | sed -e 's/\x1b\[[0-9;]*m//g' \
            | grep -aoE 'TPS from last 1m, 5m, 15m: [0-9]+(\.[0-9]+)?' | tail -1 \
            | sed 's/.*: //' || true)
    fi
    STATS=$(curl -sS --max-time 3 "http://127.0.0.1:$AW_REFLEX_PORT/stats" 2>/dev/null || echo '{}')
    MEM=$(awk '/^MemAvailable:/ {printf "%.1f", $2/1048576}' /proc/meminfo)
    LOAD=$(cut -d' ' -f1 /proc/loadavg)
    BOARD_JSON=$(cat "$BOARD" 2>/dev/null || echo '{}')
    PAUSES=$("$AW_RUNTIME/venv/bin/python" - "$PAUSE" <<'PY' 2>/dev/null || echo ""
import json, sys, time
try:
    doc = json.load(open(sys.argv[1]))
    now = time.time()
    print(sum(1 for v in doc.values()
              if isinstance(v, dict) and (v.get("until") is None or v["until"] >= now)))
except Exception:
    print(0)
PY
)
    YIELDS=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("yielded_ticks",""))' "$STATS" 2>/dev/null || echo '')
    python3 - "$BOARD_JSON" "${TPS:-}" "$MEM" "$LOAD" "${PAUSES:-0}" "$YIELDS" "$AW_LOG_DIR/player-builds.jsonl" >> "$CSV" <<'PY'
import datetime, json, os, sys
board = json.loads(sys.argv[1] or "{}")
counts = board.get("counts", {})
player_builds = 0
if os.path.exists(sys.argv[7]):
    with open(sys.argv[7]) as handle:
        player_builds = sum(1 for line in handle if line.strip())
row = [
    datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    sys.argv[2], sys.argv[3], sys.argv[4],
    counts.get("active", 0), counts.get("done", 0), counts.get("blocks_placed", 0),
    counts.get("open_issues", 0), counts.get("fixed_issues", 0),
    sys.argv[5], sys.argv[6], player_builds,
]
print(",".join(str(v) for v in row))
PY
}

# One rollup: the whole CSV so far, appended to the summary.
rollup() {
    python3 - "$CSV" "$SUMMARY" <<'PY'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1])))
out = open(sys.argv[2], "a")
def say(line):
    print(line); out.write(line + "\n")
if not rows:
    say("no samples yet"); raise SystemExit
def col(name):
    return [float(r[name]) for r in rows if r.get(name) not in ("", None)]
tps = col("tps_1m"); mem = col("mem_avail_gb")
say(f"--- rollup at {rows[-1]['at']} over {len(rows)} samples ---")
say(f"projects: done {rows[-1]['projects_done']} (active {rows[-1]['projects_active']}), "
    f"blocks placed in scope {rows[-1]['blocks_placed']}, "
    f"issues open {rows[-1]['issues_open']} / fixed {rows[-1]['issues_fixed']}")
say(f"pauses seen (max in force): {max(col('pauses') or [0])}, yields {rows[-1]['yields']}")
say(f"grief: player builds known {rows[-1]['player_builds']} (the rule held; standing checks live in the probe)")
if tps:
    ok = sum(1 for t in tps if t >= 19.5)
    say(f"tps_1m: min {min(tps)}, median {statistics.median(tps)}, max {max(tps)} ({ok}/{len(tps)} >= 19.5)")
else:
    say("tps_1m: no samples parsed")
if mem:
    say(f"mem_avail_gb: min {min(mem)}, median {statistics.median(mem)}")
say(f"load1: last {rows[-1]['load1']}")
PY
}

cmd_start() {
    if pgrep -f "community-watch-heartbeat" >/dev/null 2>&1; then
        echo "the community watch is already running:"
        pgrep -af "community-watch-heartbeat" || true
        return 0
    fi
    echo "at,tps_1m,mem_avail_gb,load1,projects_active,projects_done,blocks_placed,issues_open,issues_fixed,pauses,yields,player_builds" > "$CSV"
    echo "the community watch: samples every 60 s into $CSV, rollups into $SUMMARY"
    setsid nohup bash -c "exec -a community-watch-heartbeat $(dirname "$0")/community-watch.sh _beat $TAG" \
        >> "$OUT.watch.log" 2>&1 < /dev/null &
    echo "detached."
}

_beat() {
    local n=0
    trap 'rollup; exit 0' INT TERM
    while true; do
        if ! pgrep -f 'paper-.*\.jar' >/dev/null 2>&1; then
            echo "$(date -u +%FT%TZ) the server is down; the watch holds (no samples)" >> "$OUT.watch.log"
        else
            sample || echo "$(date -u +%FT%TZ) sample failed" >> "$OUT.watch.log"
        fi
        n=$((n + 1))
        if [ $((n % 60)) -eq 0 ]; then
            rollup || true
        fi
        sleep 60
    done
}

cmd_stop() {
    pkill -f "community-watch-heartbeat" 2>/dev/null || true
    rollup || true
    echo "the watch is stopped; the record is $CSV"
}

cmd_status() {
    if pgrep -f "community-watch-heartbeat" >/dev/null 2>&1; then
        echo "watch: running ($(wc -l < "$CSV") lines in the CSV)"
    else
        echo "watch: down"
    fi
}

case "${1:-}" in
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    _beat) _beat ;;
    *) sed -n '2,17p' "$0"; exit 1 ;;
esac
