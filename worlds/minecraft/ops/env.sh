# ops/env.sh — the one place the world's addresses are written down.
#
# Sourced by every ops script and by the bots' launcher. Nothing else in
# the repo hard-codes a port or a path: one file to change when the
# world's addresses change, and one file to read when answering "how do
# I get in?".

# Where the repo is on the Thor.
AW_ROOT="${AW_ROOT:-$HOME/lm-wt/agent-world}"

# The runtime tree: not in git, all of it re-creatable.
AW_RUNTIME="${AW_RUNTIME:-$AW_ROOT/runtime}"

# The LAN address of the Thor. Every listener binds here (never 0.0.0.0)
# so the world is reachable from the house and not from the internet.
AW_HOST="${AW_HOST:-192.168.0.78}"

# --- the runtimes (local directories; nothing is installed system-wide) ---
# Two JDKs, because the Minecraft release decides which one it wants:
# the 26.x line asks for Java 25, the 1.21.x line for Java 21. Both are
# Temurin tarballs in a local directory; neither touches the system.
AW_JDK25="${AW_JDK25:-$AW_RUNTIME/jdk-25}"
AW_JDK21="${AW_JDK21:-$AW_RUNTIME/jdk-21}"
# The JDK the world is running on. Change this one line to move the
# world between the two Minecraft lines.
AW_JDK="${AW_JDK:-$AW_JDK25}"
AW_NODE="${AW_NODE:-$AW_RUNTIME/node}"

# The Paper build and the Minecraft protocol it speaks. These two travel
# together: 26.1.2 speaks 26.1, 1.21.11 speaks 1.21.11.
AW_PAPER_VERSION="${AW_PAPER_VERSION:-26.1.2-74}"
AW_MINECRAFT_VERSION="${AW_MINECRAFT_VERSION:-26.1}"
AW_PAPER_JAR="${AW_PAPER_JAR:-$AW_RUNTIME/dl/paper-$AW_PAPER_VERSION.jar}"
AW_SERVER_DIR="${AW_SERVER_DIR:-$AW_RUNTIME/paper}"
AW_GEEYSER_DIR="${AW_GEEYSER_DIR:-$AW_RUNTIME/geyser}"

# --- the world ---
AW_WORLD_DIR="${AW_WORLD_DIR:-$AW_RUNTIME/world}"
AW_LEVEL_SEED="${AW_LEVEL_SEED:-agent-world}"
AW_LOG_DIR="${AW_LOG_DIR:-$AW_RUNTIME/logs}"

# --- the ports ---
# Paper (Minecraft Java): TCP.
AW_PAPER_PORT="${AW_PAPER_PORT:-25565}"
# Geyser (Minecraft Bedrock): UDP. Different protocol, different socket.
AW_BEDROCK_PORT="${AW_BEDROCK_PORT:-19132}"
# The browser view: prismarine-viewer (3D) and the Syzygy ASCII view beside it.
AW_VIEW_PORT="${AW_VIEW_PORT:-8080}"
# The reflex service: the bots' decision seam. Loopback only — it is an
# internal door, not a service anyone on the LAN needs.
AW_REFLEX_PORT="${AW_REFLEX_PORT:-8110}"
# d1-2B, served once on the Thor and shared by every bot.
AW_D1_PORT="${AW_D1_PORT:-8094}"

# --- the memory cap ---
# Paper's heap. The rule on this box is >= 25 GB free; the world is
# capped well below that so it can never be the reason a seat dies.
AW_PAPER_XMX="${AW_PAPER_XMX:-6G}"
AW_PAPER_XMS="${AW_PAPER_XMS:-2G}"

# --- the lease ---
# Heavy work on the Thor takes this lock, one at a time. The world is
# long-lived, so it takes the lock the way a seat would: it waits for it,
# it holds it while it runs, and it gives it up the moment it stops.
AW_HEAVY_LOCK="${AW_HEAVY_LOCK:-$HOME/lm-wt/heavy.lock}"

# --- the tmux session ---
AW_TMUX_SESSION="${AW_TMUX_SESSION:-agent-world}"

# --- the whitelist ---
# The world's door. In offline mode the whitelist is the only gate, so
# every name that may join is listed here.
AW_WHITELIST="${AW_WHITELIST:-$AW_ROOT/ops/world/whitelist.txt}"

# --- the log of record for the box ---
AW_LAST_MILE_OPS="${AW_LAST_MILE_OPS:-$HOME/last-mile-ops.md}"

# The java binary, if the runtime is installed.
aw_java() {
    if [ -x "$AW_JDK/bin/java" ]; then
        echo "$AW_JDK/bin/java"
    else
        command -v java
    fi
}
# The node binary, if the runtime is installed.
aw_node() {
    if [ -x "$AW_NODE/bin/node" ]; then
        echo "$AW_NODE/bin/node"
    else
        command -v node
    fi
}

export AW_ROOT AW_RUNTIME AW_HOST AW_JDK AW_JDK21 AW_JDK25 AW_NODE AW_PAPER_JAR \
    AW_PAPER_VERSION AW_MINECRAFT_VERSION AW_SERVER_DIR \
    AW_GEEYSER_DIR AW_WORLD_DIR AW_LEVEL_SEED AW_LOG_DIR AW_PAPER_PORT \
    AW_BEDROCK_PORT AW_VIEW_PORT AW_REFLEX_PORT AW_D1_PORT AW_PAPER_XMX \
    AW_PAPER_XMS AW_HEAVY_LOCK AW_TMUX_SESSION AW_WHITELIST AW_LAST_MILE_OPS
