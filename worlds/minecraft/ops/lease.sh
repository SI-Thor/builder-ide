#!/usr/bin/env bash
# ops/lease.sh — the world's lease on the Thor.
#
# The rule from the 13:22 OOM: heavy work on this box takes
# `flock ~/lm-wt/heavy.lock`, one at a time, and keeps >= 25 GB free.
# thor-admit will replace this with a real admission controller; until it
# lands, the lock is the lease.
#
# Two shapes:
#
#   aw_lease_run <cmd...>   block until the lease is free, hold it for the
#                           command, release it when the command ends.
#   aw_lease_try <cmd...>   take the lease only if it is free right now;
#                           return 1 (and run nothing) if it is not.
#
# The world uses both: the *server* takes the lease for the heavy part of
# its life (world generation, the first chunk load), and the *agents* take
# it for the short part (each decision tick). So a seat that needs the GPU
# waits at most one tick, and the world keeps going the rest of the time.
set -euo pipefail

. "$(dirname "$0")/env.sh"

# The lock file has to exist before flock will take it.
aw_lock_file() {
    mkdir -p "$(dirname "$AW_HEAVY_LOCK")"
    [ -e "$AW_HEAVY_LOCK" ] || : > "$AW_HEAVY_LOCK"
    echo "$AW_HEAVY_LOCK"
}

# aw_lease_run <cmd...>
aw_lease_run() {
    local lock
    lock="$(aw_lock_file)"
    exec flock "$lock" "$@"
}

# aw_lease_try <cmd...>
aw_lease_try() {
    local lock
    lock="$(aw_lock_file)"
    exec flock -n "$lock" "$@"
}

# aw_lease_free — exit 0 when the lease is free right now, 1 when it is taken.
# Used by the agent loop: a tick that cannot take the lease is a tick that
# waits for the next one, which is how the world yields to live work.
aw_lease_free() {
    local lock
    lock="$(aw_lock_file)"
    flock -n "$lock" -c true
}

export -f aw_lease_free aw_lock_file 2>/dev/null || true
