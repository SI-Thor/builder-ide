# Phase 1b: ingamebuilding2.md (list2.md) — read-only, same rules as BRIEF.md

Casey: "it went off track but came back with good repos to research." The goal it serves:
humans AND agents vibecode in-world under supervision; a human comes and goes, checks in,
and can REWIND if things went off track while they were away.

## A. Repos/tools to investigate (clone --depth 1 / read docs; run nothing)
1. NVIDIA ACE for Games: the "Game Agent SDK" (claimed Apache 2.0, C/C++ agent+chat+RAG) and
   NVIGI (In-Game Inferencing SDK). Verify the repos exist, the licence per component, and
   aarch64/Jetson support. Note: our rule is no resident LLMs on the Thor; judge it for its
   METHODS (agent loop, plugin seam, scheduling of inference next to a game loop).
2. Godot headless dedicated server on ARM64 Linux: does it build/run on aarch64; how a
   server-authoritative world + scripted agents would look; compare with our Bevy world and
   the agent-world (Minecraft/mineflayer) stack.
3. NVTX + Nsight Systems + OpenTelemetry: tracing a world tick across ProArt<->Thor; what we
   could add to thor-admit / agent-world / night runs cheaply.
4. gorakhargosh/watchdog + headless Blender bake daemon (decimate, LOD, AO/normal bake) on a
   watched share; compare with our critic/cad pipeline (build123d, critic-shells).
5. input-leap (virtual KVM) for one keyboard/mouse across ProArt and Thor desktop.
6. gRPC vs our current transports (NATS on the Thor, websockets in agent-world) for the
   engine<->Thor hook.
7. ComfyUI and vLLM: list only what we already have or ruled out (check docs/research first).
Also confirm the claimed Thor 10 GbE port and what a direct ProArt<->Thor cable needs
(this is the Ethernet ask already pending with Casey).

## B. Ideas in list2.md to map onto our designs (one paragraph each: exists / partial / new)
- #9 Time-travel delta ledger + headless timeline forks  -> canon ledger, keyframes, forkable canon (REWIND)
- #8 Pre-flight sandbox for injected scripts, hot-swap if it passes -> supervision of agent-written code
- #7 Client prediction + server "hindsight" correction -> reflex/canon split
- #1 "Never wait" placeholder fallback; Thor bakes neighbouring tiles ahead
- #6 Shared substrate, many viewers (tablet/glasses) -> presence, come-and-go
- #10/#16 Repo-as-a-room / terminal MUD -> agent-world rooms, TextWorld
- #11 Interface that adapts to failure patterns -> screen watcher (when to speak)
- #14 Push-to-talk voice to world macros -> NOTE the privacy rule: no human audio stored
- #17 Orin as a perception sub-node -> NOTE the Orin is shared; no memory-hungry services
Skip as off-track: AYN Thor handheld (different device), monitor PbP setup, posture/glasses
health advice, bathymetry (Casey's own data: note only that it could seed terrain later).

## Deliverables
- Append a "Phase 1b" section to docs/ingame-building.md (same per-tool fields as phase 1).
- A short "rewind and supervision" table: each idea -> our existing piece -> the gap.
- Update the phase-2 ranking if anything here beats a phase-1 pick. Phase 2 still needs Casey's OK.
- Follow ~/lm-wt/DOC-RULES.md. Never "breakthrough"/"groundbreaking" in docs.
