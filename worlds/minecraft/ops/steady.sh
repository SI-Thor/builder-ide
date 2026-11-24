#!/usr/bin/env bash
# ops/steady.sh — the world, steady, with a person in it.
#
# The brief's bar: TPS >= 19.5 for 30 minutes with TestHuman active,
# d1's latency unchanged, MemAvailable >= 30 GB. This script holds the
# person (bots/probe-steady.js: a client that wanders, digs and asks,
# the load of a curious player) and samples the box every 30 seconds:
#
#   tps_1m        the server's own one-minute tick average ("tps" on
#                 the console, parsed from paper.log)
#   d1_ms         the decision model's mean latency this run
#                 (reflex /stats, model.mean_latency_ms)
#   pack_ms       the whole pack's mean latency (all bots, one call)
#   mem_avail_gb  /proc/meminfo MemAvailable
#   load1         the box's one-minute load
#
#   ops/steady.sh 30              # the half hour
#   ops/steady.sh 5               # a smoke run
#
# The undo: the script ends by itself; Ctrl-C stops the person too.
# The CSV and the JSONL it writes are the reproducible record; the
# playtest note quotes them.
set -euo pipefail

. "$(dirname "$0")/env.sh"

MINUTES="${1:-30}"
OUT="$AW_LOG_DIR/steady-$(date +%Y%m%d-%H%M%S)"
CSV="$OUT.csv"
JSONL="$OUT.jsonl"
PAPER_LOG="$AW_LOG_DIR/paper.log"

# The server's console is the tmux pane whose terminal the java process
# was born on -- panes get reshuffled across restarts (the 2026-11-02
# run typed "tps" into a bystander bash for half an hour), so the pane
# is found, not assumed.
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
CONSOLE="$(find_console)"
if [ -z "$CONSOLE" ]; then
    echo "could not find the server console pane (is the world up?)" >&2
    exit 1
fi
echo "the console pane is $CONSOLE"

[ -x "$AW_NODE/bin/node" ] || { echo "no node at $AW_NODE" >&2; exit 1; }
# The guard matches the probe's own process line (a node process), not
# any wrapper that happens to carry the words.
if pgrep -f "node .*probe-steady" >/dev/null 2>&1; then
    echo "a steady probe is already running:" >&2
    pgrep -af "node .*probe-steady" >&2
    exit 1
fi
echo "the steady run: ${MINUTES} minutes, a sample every 30 s, into $CSV"

# The person, held by this script's process group so it cannot linger.
"$AW_NODE/bin/node" "$AW_ROOT/bots/probe-steady.js" --minutes "$MINUTES" \
    >> "$OUT.probe.log" 2>&1 &
PROBE_PID=$!
trap 'kill "$PROBE_PID" 2>/dev/null || true' EXIT INT TERM

# d1's mean latency is a running mean over the whole run of the reflex,
# so the honest "before" is the mean of everything up to now.
BASE_D1_MS=$(curl -sS --max-time 3 "http://127.0.0.1:$AW_REFLEX_PORT/stats" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("model",{}).get("mean_latency_ms","?"))' 2>/dev/null || echo '?')
echo "baseline d1 mean latency (whole run so far): ${BASE_D1_MS} ms"

echo "at,tps_1m,d1_ms,pack_ms,mem_avail_gb,load1,probe_alive" > "$CSV"

SAMPLES=$(( MINUTES * 2 ))
for (( i = 0; i < SAMPLES; i++ )); do
    # The server's own number: ask the console, read only what the
    # answer wrote to the log (never an earlier run's line).
    MARK=$(wc -c < "$PAPER_LOG" 2>/dev/null || echo 0)
    tmux send-keys -t "$CONSOLE" -l "tps" </dev/null 2>/dev/null || true
    tmux send-keys -t "$CONSOLE" Enter </dev/null 2>/dev/null || true
    sleep 3
    # Under pipefail a slow console answer (grep finds nothing) would
    # end the whole run, so this pipeline is allowed to come up empty.
    TPS=$(tail -c "+$((MARK + 1))" "$PAPER_LOG" 2>/dev/null \
        | grep -oE 'TPS from last 1m, 5m, 15m: [0-9]+(\.[0-9]+)?' | tail -1 \
        | sed 's/.*: //' || true)
    STATS=$(curl -sS --max-time 3 "http://127.0.0.1:$AW_REFLEX_PORT/stats" 2>/dev/null || echo '{}')
    MEM=$(awk '/^MemAvailable:/ {printf "%.1f", $2/1048576}' /proc/meminfo)
    LOAD=$(cut -d' ' -f1 /proc/loadavg)
    ALIVE=no; kill -0 "$PROBE_PID" 2>/dev/null && ALIVE=yes

    AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    D1=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("model",{}).get("mean_latency_ms",""))' "$STATS" 2>/dev/null || echo '')
    PACK=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("mean_pack_latency_ms",""))' "$STATS" 2>/dev/null || echo '')
    echo "$AT,${TPS:-},$D1,$PACK,$MEM,$LOAD,$ALIVE" >> "$CSV"
    printf '{"at":"%s","stats":%s}\n' "$AT" "${STATS:-{\}}" >> "$JSONL"
    sleep 27
done

# The summary, from the CSV itself, so the note quotes what is measured.
python3 - "$CSV" "$BASE_D1_MS" "$OUT.summary" <<'PY'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1])))
tps = [float(r["tps_1m"]) for r in rows if r["tps_1m"]]
mem = [float(r["mem_avail_gb"]) for r in rows if r["mem_avail_gb"]]
d1 = [float(r["d1_ms"]) for r in rows if r["d1_ms"]]
pack = [float(r["pack_ms"]) for r in rows if r["pack_ms"]]
out = open(sys.argv[3], "a")
def say(line):
    print(line)
    out.write(line + "\n")
say(f"samples: {len(rows)}")
if tps:
    ok = sum(1 for t in tps if t >= 19.5)
    say(f"tps_1m: min {min(tps)}, median {statistics.median(tps)}, max {max(tps)}  ({ok}/{len(tps)} samples >= 19.5)")
else:
    say("tps_1m: no samples parsed (does the console answer 'tps'?)")
if mem:
    say(f"mem_avail_gb: min {min(mem)}, median {statistics.median(mem)}")
if d1:
    say(f"d1_ms (running mean): last {d1[-1]}, before the run {sys.argv[2]}")
if pack:
    say(f"pack_ms (running mean): last {pack[-1]}")
PY
echo "the steady run is written up in $OUT.summary"
