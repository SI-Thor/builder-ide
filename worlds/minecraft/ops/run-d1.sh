#!/usr/bin/env bash
# ops/run-d1.sh — the world's decision model, loaded under the admission.
#
# The model is **one server, shared by every builder**: a decision tick
# asks it a pack of questions (one per builder) and gets one answer per
# question back, so four builders cost one model call, not four.
#
# The admission (the director's rule, 2026-10-31 21:25, and
# ~/lm-wt/MEMORY-RULE.md):
#
# * a decision tick is **light** — the builders never take the heavy
#   lock, not even per tick;
# * the **model load** is heavy, so it goes through `thor-admit serve`:
#   the model loads under a lease, the lease is released once it is
#   serving, and — the point of `serve` — a second caller anywhere on
#   the box gets this server's port instead of loading a second copy.
#   serve stays in the foreground supervising the model, which is what
#   this window wants;
# * when the daemon is not running, the old heavy lock still loads the
#   model: lock held only while loading, released the moment the model
#   answers.
#
# The undo: ops/d1.sh stop.
set -euo pipefail

. "$(dirname "$0")/env.sh"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

MODEL="${AW_D1_MODEL:-/home/caseydigennaro/models/d1-2B/d1-2B-Q8_0.gguf}"
MMPROJ="${AW_D1_MMPROJ:-/home/caseydigennaro/models/d1-2B/mmproj-d1-2B-Q8_0.gguf}"
LLAMA="${AW_LLAMA:-/home/caseydigennaro/llama.cpp-upstream/build-up/bin/llama-server}"
THOR_ADMIT="${AW_THOR_ADMIT:-$HOME/lm-tools/thor-admit}"

[ -x "$LLAMA" ] || { printf 'no llama-server at %s\n' "$LLAMA" >&2; exit 1; }
[ -f "$MODEL" ] || { printf 'no model at %s\n' "$MODEL" >&2; exit 1; }

# --- the model ----------------------------------------------------------------
# The same command line as the d1-2b user unit, including its eight
# parallel slots: a pack of questions is several requests at once, and
# continuous batching is what makes one call for four builders cheap.
CMD=("$LLAMA" -m "$MODEL" --mmproj "$MMPROJ" \
    --host 0.0.0.0 --port "$AW_D1_PORT" -ngl 99 --flash-attn on \
    --ctx-size 32768 -ub 4096 --parallel 8 --cont-batching \
    --slot-prompt-similarity 0 --alias d1-2B)

# --- the admission daemon first, the heavy lock only without it ----------------
if [ -x "$THOR_ADMIT" ] && "$THOR_ADMIT" status >/dev/null 2>&1; then
    say "the admission daemon is up: serving d1-2B once for the whole box"
    exec "$THOR_ADMIT" serve d1-2B --port "$AW_D1_PORT" \
        --peak "${AW_D1_PEAK:-8G}" -- "${CMD[@]}"
fi

mkdir -p "$(dirname "$AW_HEAVY_LOCK")"
[ -e "$AW_HEAVY_LOCK" ] || : > "$AW_HEAVY_LOCK"
exec 9>"$AW_HEAVY_LOCK"

say "no admission daemon; queued for the lease on $AW_HEAVY_LOCK"
if ! flock -w 3600 9; then
    say "the lease was never freed; the decision model is not loading"
    exit 1
fi
say "lease taken; loading the model"

"${CMD[@]}" &
SERVER_PID=$!

# --- release the lease as soon as the model is up -----------------------------
(
    waited=0
    while [ "$waited" -lt 600 ]; do
        if curl -sf --max-time 2 "http://127.0.0.1:$AW_D1_PORT/health" >/dev/null 2>&1; then
            say "the model is up; releasing the lease"
            flock -u 9
            break
        fi
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
) &

wait "$SERVER_PID"
say "the decision model has stopped"
