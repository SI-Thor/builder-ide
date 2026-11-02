#!/usr/bin/env bash
# Empty the sandbox bot's hands before a measured run.
#
# The measured run has to start from nothing in the inventory: a tech
# tree that is already climbed at step one measures nothing. The bot's
# saved player file is edited while the server is stopped, because
# Paper keeps its own copy of a player and wins.
set -euo pipefail

REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
NODE="${VOYAGER_NODE:-$HOME/lm-wt/agent-world/runtime/node/bin/node}"

cd "$REPO"
"$NODE" docs/lab/voyager-port-scripts/reset_hands.js
