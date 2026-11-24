#!/usr/bin/env bash
# ops/run-paper.sh — what actually runs inside the world's tmux window.
#
# The lease, and what it is actually for (the director, 2026-10-31 21:25).
#
# The rule from the 13:22 OOM is not "nothing heavy may run at the same
# time" — it is **"keep 25 GB free"**, and the heavy lock is the
# stopgap for that. The world is a resident service: a 6 GB heap, under
# the ~8 GB heavy threshold, at `nice 10`. So:
#
# * **the world never takes the heavy lock.** It is not a heavy step;
# * **it checks the memory instead**, and does not start while the box
#   has less than 25 GB free. That is the rule, applied directly;
# * the part of the world that *is* light — the builders' decision ticks
#   — never takes the lock either, for the same reason. What pre-empts
#   the world is the memory floor: when the box is full, the builders
#   stand aside and say so in the log (see
#   reflex/agent_world_reflex/service.py).
#
# The heavy lock is for genuinely heavy, short steps — and the world has
# one of those: loading the decision model, which takes the lease only
# while it loads (ops/run-d1.sh).
#
# The server runs in the **foreground** of this script on purpose: that is
# what gives it the tmux pane's stdin, so `tmux send-keys "stop"` reaches
# the server console and the world saves and shuts down cleanly.
set -euo pipefail

. "$(dirname "$0")/env.sh"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31mxx\033[0m %s\n' "$*" >&2; exit 1; }

# The rule: keep this much free on the box.
FREE_FLOOR_GB="${AW_FREE_FLOOR_GB:-25}"

free_gb() {
    awk '/MemAvailable/ {printf "%d", $2 / 1048576}' /proc/meminfo
}

# --- the memory check ---------------------------------------------------------
available="$(free_gb)"
waited=0
while [ "$available" -lt "$FREE_FLOOR_GB" ]; do
    if [ "$waited" -eq 0 ]; then
        say "only ${available} GB free; the box's rule is to keep ${FREE_FLOOR_GB} GB free — waiting"
    fi
    sleep 30
    waited=$((waited + 30))
    available="$(free_gb)"
    if [ "$waited" -ge 1800 ]; then
        die "the box stayed under ${FREE_FLOOR_GB} GB free for 30 minutes; the world is not starting"
    fi
done
say "${available} GB free on the box (the floor is ${FREE_FLOOR_GB} GB)"

mkdir -p "$AW_LOG_DIR" "$AW_SERVER_DIR"
cd "$AW_SERVER_DIR"

# --- the server, in the foreground so the console reaches it ------------------
nice -n 10 "$AW_JDK/bin/java" \
    -Xms"$AW_PAPER_XMS" -Xmx"$AW_PAPER_XMX" \
    -XX:+UseG1GC -XX:MaxGCPauseMillis=100 \
    -Dcom.mojang.eula.agree=true \
    -jar "$AW_PAPER_JAR" --nogui
say "the world has stopped"
