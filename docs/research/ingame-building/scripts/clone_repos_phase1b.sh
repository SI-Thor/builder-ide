#!/bin/bash
# clone_repos_phase1b.sh — depth-1 clones for BRIEF-2 phase 1b (read docs only, run nothing)
cd /home/proart/lm-wt/ingame-building/src || exit 1
clone() {
  if [ -d "$1/.git" ]; then echo "[skip] $1"; return; fi
  echo "[clone] $1 <- $2"
  git clone --depth 1 --quiet "$2" "$1" 2>&1 | tail -2
  echo "[done] $1 exit=$?"
}
clone game-agent-sdk        https://github.com/NVIDIA/game-agent-sdk
clone nvidia-ace            https://github.com/NVIDIA/ACE
clone nvigi                 https://github.com/NVIDIA-RTX/NVIGI
clone nvigi-core            https://github.com/NVIDIA-RTX/NVIGI-Core
clone nvigi-godot-extension https://github.com/NVIDIA-RTX/nvigi_godot_extension
clone godot                 https://github.com/godotengine/godot
clone nvtx                  https://github.com/NVIDIA/NVTX
clone opentelemetry-cpp    https://github.com/open-telemetry/opentelemetry-cpp
clone opentelemetry-python  https://github.com/open-telemetry/opentelemetry-python
clone watchdog              https://github.com/gorakhargosh/watchdog
clone input-leap            https://github.com/input-leap/input-leap
clone grpc                  https://github.com/grpc/grpc
clone vllm                  https://github.com/vllm-project/vllm
clone comfyui               https://github.com/comfyanonymous/ComfyUI
clone nsight-systems        https://github.com/NVIDIA/nsight-systems
echo "=== PHASE 1b CLONES DONE ==="
du -sh */ 2>/dev/null | sort -h
