#!/bin/bash
# clone.sh — depth-1 clones of the eight tools under investigation (read-only study, no builds)
cd /home/proart/lm-wt/ingame-building/src || exit 1
clone() { # name url
  if [ -d "$1/.git" ]; then echo "[skip] $1 already present"; return; fi
  echo "[clone] $1 <- $2"
  git clone --depth 1 --quiet "$2" "$1" 2>&1 | tail -3
  echo "[done] $1 exit=$?"
}
clone topview-3d-builder  https://github.com/topviewai/topview-3d-builder
clone build-world         https://github.com/thrixel/build-world
clone Vibe3DScene         https://github.com/3DSceneAgent/Vibe3DScene
clone MEP-SANDBOX-ENGINE  https://github.com/FugthChat/MEP-SANDBOX-ENGINE
clone Open-World-Builder  https://github.com/GlaireDaggers/Open-World-Builder
clone Torque3D            https://github.com/TorqueGameEngines/Torque3D
clone Prowl               https://github.com/ProwlEngine/Prowl
echo "=== ALL CLONES DONE ==="
du -sh */ 2>/dev/null
