#!/usr/bin/env bash
# ops/check-views.sh — do the world's windows really work?
#
# The 3D view once showed "null is not supported" and a blank canvas, and
# a 200 with live frames did not catch it. So this drives a real browser:
# it opens each page, reads what the console says, and looks at the
# pixels that were actually drawn.
#
#   ops/check-views.sh             check all three pages
#   ops/check-views.sh /ascii      check one page
#
# The three pages:
#
#   /         the 3D view (prismarine-viewer): the world, in 3D
#   /ascii    the text view: the same world, projected into text
#   /voices   the voices: each agent's voice, in the page
#
# The undo: nothing. It only looks.
set -uo pipefail

. "$(dirname "$0")/env.sh"

BASE="http://127.0.0.1:$AW_VIEW_PORT"
# The browser lives with the other tools on the Thor.
NODE_BIN="${AW_NODE_BIN:-$HOME/.nvm/versions/node/v24.22.2/bin}"
export PATH="$NODE_BIN:$PATH"
CHECKER="$(dirname "$0")/check-views.mjs"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }

check_one() {
    local path_name="$1" label="$2"
    if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$path_name" ]; then
        return 0
    fi
    node "$CHECKER" "$BASE$path_name" "$label"
}

if ! curl -sS --max-time 5 "$BASE/status" >/dev/null 2>&1; then
    warn "the view is not answering on $BASE — start it with ops/viewer.sh start"
    exit 1
fi

say "the translation"
node "$(dirname "$0")/check-translation.js" | tail -n 3 || {
    warn "the drawing is not honest — see the check above"
    exit 1
}

say "the pages, in a real browser"
failed=0
check_one "/" "the 3D view" || failed=1
check_one "/ascii" "the text view" || failed=1
check_one "/voices" "the voices" || failed=1

if [ "$failed" -ne 0 ]; then
    warn "a page is not working"
    exit 1
fi
say "all three pages work"
