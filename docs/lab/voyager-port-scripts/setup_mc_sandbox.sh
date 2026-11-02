#!/usr/bin/env bash
# Set up the **private** Minecraft sandbox for the Voyager port.
#
# The brief: "Minecraft via mineflayer against a PRIVATE Paper server
# instance you start yourself from ~/lm-wt/agent-world/runtime (copy the
# server dir to ./mc-sandbox, new world, port 25600, offline mode, bind
# 127.0.0.1) — NEVER the live agent-world server on 25565 and never its
# world".
#
# So this script:
#
#   * copies the Paper server **directory** out of the live runtime — the
#     jar, the libraries and the Mojang cache, so nothing is downloaded
#     again — and nothing else: no world, no logs, no plugins;
#   * gives it a **new world** with a fixed seed, so a run is
#     reproducible;
#   * binds it to **127.0.0.1:25600** and turns **offline mode** on;
#   * writes the properties that make the measurement a measurement:
#     peaceful, no monsters, no daylight cycle, no spawn protection.
#
# The live server on 25565 is never touched, and its world is never
# copied: the copy is made from the server *directory*, and the world
# directory is excluded by name.
#
# Usage:
#   bash docs/lab/voyager-port-scripts/setup_mc_sandbox.sh
#
# What it needs: the live runtime at ~/lm-wt/agent-world/runtime, and
# ~160 MB of disk for the copied server. It takes about a minute.
set -euo pipefail

RUNTIME="${AW_RUNTIME:-$HOME/lm-wt/agent-world/runtime}"
REPO="${VOYAGER_REPO:-$HOME/lm-wt/voyager-port}"
SANDBOX="${VOYAGER_SANDBOX:-$REPO/mc-sandbox}"
PAPER_JAR="${AW_PAPER_JAR:-$RUNTIME/dl/paper-26.1.2-74.jar}"
PORT="${VOYAGER_MC_PORT:-25600}"
SEED="${VOYAGER_MC_SEED:-voyager-port}"

say() { printf '\033[1m==>\033[1m %s\n' "$*"; }
die() { printf '\033[31mxx\033[1m %s\n' "$*" >&2; exit 1; }

[ -d "$RUNTIME/paper" ] || die "no Paper server directory at $RUNTIME/paper"
[ -f "$PAPER_JAR" ] || die "no Paper jar at $PAPER_JAR"

if [ -e "$SANDBOX" ]; then
  say "the sandbox is already there at $SANDBOX (remove it to rebuild)"
else
  say "copying the server directory to $SANDBOX (no world, no logs, no plugins)"
  mkdir -p "$SANDBOX"
  # The server's own files: the config, the libraries, the Mojang cache
  # and the version data. NOT the world, and NOT the plugins (they are
  # the live world's Bedrock bridge).
  for entry in bukkit.yml commands.yml eula.yml eula.txt help.yml ops.json \
      permissions.yml spigot.yml usercache.json version_history.json \
      whitelist.json whitelist.txt banned-ips.json banned-players.json \
      config cache libraries versions; do
    if [ -e "$RUNTIME/paper/$entry" ]; then
      cp -a "$RUNTIME/paper/$entry" "$SANDBOX/"
    fi
  done
  mkdir -p "$SANDBOX/logs"
fi

say "writing the sandbox's own server.properties"
cat > "$SANDBOX/server.properties" <<PROPS
# The private sandbox for the Voyager port (docs/lab/exp-voyager-port.md).
#
# The differences from the live agent-world server, and why:
#   server-port=25600      the live world is on 25565; this one is not it
#   server-ip=127.0.0.1    loopback only; the sandbox is not on the LAN
#   online-mode=false      the bot joins offline, and there is no Mojang call
#   level-name=world       a NEW world, generated on first start
#   level-seed=SEEDHERE    a fixed seed, so a run can be repeated
#   difficulty=peaceful    no mobs: the measurement is the tech tree, not combat
#   spawn-monsters=false   the same, stated twice on purpose
#   doDaylightCycle=false  the bot cannot sleep, so the day/night cycle is noise
#   spawn-protection=0     the bot may mine where it spawns
#   pvp=false              no combat, no damage from other players
server-port=PORTHERE
server-ip=127.0.0.1
online-mode=false
level-name=world
level-seed=SEEDHERE
level-type=minecraft\:normal
generator-settings={}
difficulty=peaceful
spawn-monsters=false
spawn-protection=0
gamemode=survival
pvp=false
allow-flight=false
force-gamemode=false
max-players=4
view-distance=8
simulation-distance=6
enable-command-block=false
enable-status=true
enforce-secure-profile=false
white-list=false
motd=voyager-port sandbox
server-name=voyager-port
pause-when-empty-seconds=-1
sync-chunk-writes=false
use-native-transport=true
network-compression-threshold=256
enable-jmx-monitoring=false
enable-rcon=false
rate-limit=0
hide-online-players=false
PROPS

# The two placeholders the heredoc left for the shell to fill.
sed -i "s/PORTHERE/$PORT/; s/SEEDHERE/$SEED/" "$SANDBOX/server.properties"

say "turning off the server's keep-alive timeout in the sandbox's own spigot.yml"
# The bot's node process searches the world in one go, and a process
# that is busy cannot answer the server's keep-alive packets: the server
# then kicks it (spigot.yml settings.timeout-time, 60 s) and the bridge
# dies in the middle of a program. The sandbox is ours, so the timeout
# is off here. The live world on 25565 keeps its own setting.
if [ -f "$SANDBOX/spigot.yml" ]; then
  sed -i 's/^  timeout-time: .*/  timeout-time: 0/' "$SANDBOX/spigot.yml"
  grep -q '^  timeout-time: 0$' "$SANDBOX/spigot.yml" || die "could not set timeout-time in $SANDBOX/spigot.yml"
else
  say "no spigot.yml in the sandbox (nothing to change)"
fi

say "agreeing to the EULA in the sandbox's own copy"
printf 'eula=true\n' > "$SANDBOX/eula.txt"

say "the sandbox is at $SANDBOX"
say "start it with: bash docs/lab/voyager-port-scripts/start_mc_sandbox.sh"
