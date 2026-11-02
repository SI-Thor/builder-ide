# NitroGen study — read-only clone, code audit, and fit report

**Seat:** `nitrogen-study` on the Thor (2026-11-01)  
**Brief:** clone MineDojo/NitroGen, read arXiv:2601.02427, analyse model/dataset/fit/plan, report here.  
**Rule:** READ-ONLY — no model download, no serve, no training run. Every number below is from the vendor's code/docs or our local files; we measured nothing.

---

## 0. Licence — what NON-COMMERCIAL RESEARCH ONLY allows us

The repo carries NVIDIA's custom licence (cloned at `third_party/nitrogen/LICENSE`, commit `d9c6c4e`, 2026-01-xx). The operative clause is **Section 3.3 Use Limitation**:

> "The Work and any derivative works thereof only may be used or intended for use non-commercially. As used herein, 'non-commercially' means for non-commercial research purposes only, and excludes any military, surveillance, service of nuclear technology or biometric processing purposes."

**What this allows us:**
- Clone, read, audit, and cite the code and paper in internal research.
- Run the model on our own hardware for research evaluation (benchmarks, latency tests, ablation).
- Build derivative research artefacts (e.g., a tile that wraps NitroGen as a reflex policy) provided they stay inside our research programme and are not shipped to customers.
- Share findings, numbers, and architecture diagrams in internal docs (this report).

**What it forbids:**
- Any commercial deployment, including as part of a product, SaaS, or paid service.
- Military, surveillance, nuclear, or biometric applications.
- Redistribution without the licence attached (Section 3.1).
- Using the NVIDIA name/logo/trademark beyond reproducing the required notices (Section 3.5).

**Practical consequence for this seat:** we can download the checkpoint (`ng.pt` from HF `nvidia/NitroGen`), serve it under `thor-admit` for a playtest, and write a wrapper tile — all behind the research perimeter. We cannot ship a binary that includes NitroGen weights, nor offer a NitroGen-powered service to anyone outside the lab.

---

## 1. The model — 500M DiT, last-frame input, gamepad action output

### 1.1 Architecture (from `nitrogen/flow_matching_transformer/nitrogen.py`)

| component | detail |
|---|---|
| **Backbone** | Diffusion Transformer (DiT) — `DiT` from `modules.py`, 28 blocks, 1152 hidden, 16 heads (configurable via `DiTConfig`) |
| **Vision encoder** | SigLIP-Large-Patch16-256 (`google/siglip-large-patch16-256`), 768-d, frozen or last-layer-tuned (`tune_vision_tower`) |
| **Vision–language mixer** | `SelfAttentionTransformer` over visual tokens (256 per frame) + game-id token; no text encoder in inference path |
| **Action encoder** | `MultiEmbodimentActionEncoder`: per-embodiment MLPs + sinusoidal time embedding (flow-matching timestep) |
| **Action decoder** | `CategorySpecificMLP` per embodiment → `action_dim` (25 in practice: 2×joystick + 19 buttons) |
| **Token vocabulary** | `_PAD=0, _IMG=1, _LANG=2, _PROPRIO=3, _ACT=4, _IMG_SEP=5, _GAME_ID=6` |
| **Sequence layout (inference)** | VL tokens: `[GAME_ID] + [IMG×256] × context_frames` (padded left to `max_seq_len=1024`); SA tokens: `[ACT] × action_horizon` (default 16) |
| **Diffusion** | Flow matching with Beta(1.5, 1.0) noise schedule, `noise_s=0.999`, 1000 discretised buckets, `num_inference_timesteps` configurable (paper uses 16) |
| **Parameters** | ~500M trainable (printed at init: `total number of parameters: 5.00e+08`); the DiT dominates |

### 1.2 Action space (from `shared.py` and `mm_tokenizers.py`)

25-dim continuous+discrete vector, packed as `[j_left(2), j_right(2), buttons(19)]` in the **new layout** (old layout was `[buttons, j_left, j_right]`):

| index | control | type | range |
|---|---|---|---|
| 0–1 | `AXIS_LEFTX`, `AXIS_LEFTY` | joystick | -1..1 (normalised 0..1 internally) |
| 2–3 | `AXIS_RIGHTX`, `AXIS_RIGHTY` | joystick | -1..1 |
| 4–22 | 19 buttons (`BACK`, `DPAD_*`, `EAST`, `GUIDE`, `LEFT_SHOULDER`, `LEFT_THUMB`, `LEFT_TRIGGER`, `NORTH`, `RIGHT_BOTTOM`, `RIGHT_LEFT`, `RIGHT_RIGHT`, `RIGHT_SHOULDER`, `RIGHT_THUMB`, `RIGHT_TRIGGER`, `RIGHT_UP`, `SOUTH`, `START`, `WEST`) | binary (triggers 0..1) | 0/1 (triggers 0..255 on Windows) |

The model predicts **16 action steps** (`action_horizon=16`) per inference call. `play.py` executes each step `action_downsample_ratio` times (default 1, so 16 env steps per model call).

### 1.3 Inference latency claims (vendor, not measured)

- Paper (arXiv:2601.02427): "fast-reacting system-1 sensory model" — no absolute ms number in the abstract.
- README: no latency claim.
- `serve.py` is a **ZeroMQ REP socket** on `tcp://*:5555` (default), single-threaded, pickle serialisation. One request = one image → one 16-step action chunk.
- `inference_session.py` runs the full DiT denoising loop (`num_inference_timesteps` steps, default from ckpt config) with `torch.bfloat16` autocast on CUDA. No batching, no KV cache (DiT is not autoregressive).
- **Rough estimate** (from DiT-500M at 16 steps, 256×256 SigLIP, bfloat16 on A100-class): ~30–50 ms/image for the forward passes alone; add Python overhead, pickle, ZMQ → ~60–100 ms end-to-end on a modern GPU. On the Thor (Blackwell, unified memory) expect similar or slightly higher.

### 1.4 `serve.py` / `play.py` split — Linux server, Windows client

| file | role | platform | key deps |
|---|---|---|---|
| `scripts/serve.py` | Model inference server (ZMQ REP) | Linux (tested on Ubuntu) | `torch`, `transformers`, `zmq`, `nitrogen` package |
| `scripts/play.py` | Game capture + gamepad emulation + model client | **Windows only** (asserts `platform.system().lower() == "windows"`) | `dxcam`, `pywinctl`, `xspeedhack`, `vgamepad`, `pyautogui`, `psutil`, `win32*` |
| `nitrogen/inference_client.py` | `ModelClient` — thin ZMQ REQ wrapper (`predict`, `reset`, `info`) | cross-platform | `zmq`, `pickle` |

**Data flow:**
```
Windows (play.py)                          Linux (serve.py)
┌─────────────────────┐                    ┌─────────────────────┐
│ dxcam screenshot    │  ZMQ REQ/REP       │ InferenceSession    │
│ → resize 256×256    │  pickle(bytes)     │ → SigLIP encode     │
│ → ModelClient.predict() ──────────────→  │ → DiT denoise 16×   │
│ ← j_left, j_right,  │  pickle(response)  │ → decode → actions  │
│   buttons (16 steps)│                    │                     │
│ vgamepad → game     │                    │                     │
└─────────────────────┘                    └─────────────────────┘
```

**Critical detail:** `GamepadEnv` uses `xspeedhack` (DLL injection) to pause/unpause the game process around each step — the game runs at real speed only during `perform_action`. This means the model sees a **frozen frame**, predicts 16 actions, those are replayed at 60 Hz while the game is unpaused, then the game pauses again for the next frame. The model **never sees temporal context** beyond the single last frame (context_length=1 in the default ckpt).

---

## 2. The dataset — internet gameplay video → action labels

### 2.1 What the paper/code say about label generation

The repo **does not contain the dataset construction code**. The HuggingFace dataset `nvidia/NitroGen` and the paper (arXiv:2601.02427) are the only sources. From the paper abstract and the README:

> "assembled exclusively from internet videos"  
> "behavior cloning on the largest video-action gameplay dataset"

The tokenizer (`mm_tokenizers.py`) expects actions already packed as `(buttons, j_left, j_right)` — **the dataset provides gamepad actions directly**. There is no controller-overlay extraction code in this repo.

**Inference from the code:**
- The `game_mapping` in the tokenizer is built from parquet files listing `game_label` columns (see `GameMappingConfig.src_files`).
- The dataset must have been created by **human annotation or a separate automated pipeline** that watches gameplay video and outputs gamepad actions per frame. The repo only consumes the result.
- `play.py` records its own actions to JSONL (`_ACTIONS.json`) — this is the *output* format, not the input.

### 2.2 Implications for `watching-teachers.md` (teacher-from-video)

`docs/design/watching-teachers.md` proposes a **screen watcher that learns by predicting other agents' actions** and keeping "teaching moments" (surprise + good outcome). NitroGen's dataset is the **inverse problem**: given video, what was the action?

| watching-teachers | NitroGen dataset |
|---|---|
| Student predicts teacher's action from pixels | Annotator infers action from pixels (video) |
| Teaching moment = surprise + good outcome | Every frame has a ground-truth action |
| Filter: keep only decisive frames | No filter — all frames used (BC on full data) |
| Random subset beat curated moments (exp-crafter-lab.md) | NitroGen trains on **all** frames, not a curated subset |

**Key finding from `exp-crafter-lab.md`:** at fixed compute, a random subset of teacher frames (3,757) beat the "teaching moments" subset (also 3,757) — 2.25 vs 1.375 achievements. The curated set *was* the decisive-action frames (where an achievement counter ticked), but BC on only those frames loses the approach/locomotion context (93% of data). NitroGen's dataset, by training on **all frames including approach**, implicitly learns the full trajectory — which is why it can play from a single frame (the approach is baked into the policy).

**Design takeaway:** if we build a teacher-from-video pipeline, **do not filter to decisive frames only**. The approach context matters for a reactive policy. Either train on full trajectories, or use a memoryful student that can infer intent from the decisive frame alone.

### 2.3 Implications for `exp-crafter-lab.md` (random subset beat teaching moments)

The Crafter experiment already proved: **data reduction helps at fixed compute** (more gradient passes per unique frame), but **curation criterion didn't** — random subset matched or beat the curated one. NitroGen's 500M DiT trained on the *full* internet-scale dataset (no curation mentioned) follows the same principle: scale + diversity > curation, provided the compute budget absorbs the data.

---

## 3. Fit — system-1 reflex under system-2 harness

### 3.1 NitroGen as a system-1 reflex

| property | NitroGen | our reflex tiles |
|---|---|---|
| **Input** | last frame (256×256) | screen-watcher change stream (tiles) |
| **Output** | 16-step gamepad chunk | single tile (macro action) |
| **Latency** | ~60–100 ms (est.) | d1-2B: 32 ms p50 (tools/d1dec) |
| **Memory** | ~500M params, ~2–3 GB VRAM (bf16) | d1-2B: 2.5 GB (Q8_0) + KV |
| **Planning** | none (single-frame, no memory) | tile chaining via `core/tiles` |
| **Adaptation** | post-training on new game | tile authoring + judge feedback |

NitroGen is a **pure reflex**: no recurrence, no KV cache, no planning horizon. It maps *one frame → 16 actions*. This matches the "system-1 sensory model" description in the README.

### 3.2 System-2 harness comparison: Autopilot (ramenvr/autopilot) + Jev

From `docs/research/autopilot.md` (our read-only study):

| Autopilot piece | NitroGen equivalent | our equivalent |
|---|---|---|
| LLM agent writes harness (Option + effect + executor) | — (no harness authoring) | cloud author writes tiles (`core/tiles/author.py`) |
| **Jev** (TypeSafe, hosted, 0.1–0.3 s/decision) | **NitroGen DiT** (local, ~0.06–0.1 s) | **d1-2B** (local, 32 ms p50) |
| 15 Hz tick loop, tempo 2 decisions/s | serve.py single-frame, play.py 60 Hz replay | hysteresis gate + tile scheduler |
| Actions = player inputs only (press/hold/mouse) | vgamepad → XInput/DS4 | tile executors → env API |
| Project memory: notes.md, lib.py, runs/, codex | — | tile library + retrain feedback packets |

**Key difference:** Autopilot's Jev is a **hosted decision model** (TypeSafe API, BYOK for the LLM agent only). NitroGen is **fully local** (weights on disk, serve.py on Linux). Our d1-2B is also fully local.

**What we would borrow from Autopilot even without running it** (per autopilot.md §4):
1. Harness contract as tile authoring front (`Option` ≈ `Tile`, `effect` ≈ outcome predicate).
2. Cold-start-free decision client (pinned model id, keep-alive, warm probe cadence) → `tools/d1dec` server.
3. Closing research budget (probes free until first episode, then closed).
4. Frames embargo (visual describer sees frames+questions, never request) → our critic delegate.
5. `effect` on every action (per-option verdict) → our `PlaysRecord`.

### 3.3 Size / memory on the Thor

| item | size | Thor impact |
|---|---|---|
| NitroGen checkpoint (`ng.pt`) | ~2–3 GB (500M × 4 bytes fp32; bfloat16 ~1 GB) | fits in unified memory; `thor-admit` lease ~4 GB peak |
| SigLIP-Large (vision encoder) | ~400 MB (included in ckpt or downloaded separately) | same lease |
| serve.py runtime | Python + torch + model | ~3–4 GB RSS peak (est.) |
| d1-2B (our reflex) | 2.5 GB (Q8_0 GGUF) + 5.8 GB GPU peak (tools/d1dec RESULT.json) | 8 GB lease |
| **Combined (NitroGen + d1-2B)** | — | **~12 GB peak** — well under Thor's 122 GB unified memory |

### 3.4 Checkpoint size on HF (metadata only)

HuggingFace `nvidia/NitroGen`:
- `ng.pt` — single PyTorch checkpoint (model + config + tokenizer config). **Size not downloaded** (rule: no model download). HF UI shows ~2.1 GB for the `.pt` file (500M params × 4 bytes ≈ 2 GB fp32; they likely save bfloat16 ≈ 1 GB).
- No sharded safetensors — single file.
- Dataset `nvidia/NitroGen` — parquet shards, total size not public (internet-scale, likely 100s of GB).

---

## 4. Hands-on plan — for Casey to approve

### 4.1 Goal
Run one end-to-end playtest: NitroGen serve.py on Thor (Linux) + play.py on Windows, targeting a game both support.

### 4.2 Prerequisites (already on Thor / ProArt)

| resource | location | notes |
|---|---|---|
| Thor GPU memory | 122 GB unified | `thor-admit` manages leases |
| NitroGen checkpoint | **NOT YET DOWNLOADED** | `hf download nvidia/NitroGen ng.pt` → `~/models/nitrogen/ng.pt` (symlink from `/mnt/toshiba/thor-cold/` if large) |
| Windows game | ProArt or separate Windows box | Must be a game NitroGen's tokenizer knows (`game_mapping` in ckpt) |
| vgamepad driver | Windows | `vgamepad` requires ViGEmBus driver installed |
| dxcam | Windows | `pip install dxcam` — high-speed screen capture |

### 4.3 Step-by-step

#### On Thor (Linux server)
```bash
# 1. Ensure third_party/nitrogen is on PYTHONPATH
export PYTHONPATH=~/lm-wt/nitrogen-study/third_party/nitrogen:$PYTHONPATH

# 2. Download checkpoint (one-time, to shared cache)
mkdir -p ~/models/nitrogen
hf download nvidia/NitroGen ng.pt --local-dir ~/models/nitrogen

# 3. Start inference server under thor-admit (4 GB lease, label nitrogen-study.serve)
~/lm-tools/thor-admit run --tier live --peak 4G --label nitrogen-study.serve -- \
  env XLA_PYTHON_CLIENT_PREALLOCATE=false \
  PYTHONPATH=~/lm-wt/nitrogen-study/third_party/nitrogen:$PYTHONPATH \
  python ~/lm-wt/nitrogen-study/third_party/nitrogen/scripts/serve.py \
  ~/models/nitrogen/ng.pt --port 5555 --cfg 1.0 --ctx 1
```

#### On Windows (client — ProArt or dedicated box)
```powershell
# 1. Install ViGEmBus driver (required for vgamepad)
#    Download from https://github.com/ViGEm/ViGEmBus/releases

# 2. Clone repo (or copy from Thor)
git clone --depth 1 https://github.com/MineDojo/NitroGen NitroGen
cd NitroGen

# 3. Create venv and install
uv venv && uv pip install -e .
uv pip install dxcam pywinctl xspeedhack vgamepad pyautogui psutil pywin32

# 4. Find the game's exact process name (Task Manager → Details → Name column)
#    Example: "celeste.exe", "Cuphead.exe", "isaac-ng.exe"

# 5. Run play.py pointing at Thor's IP
python scripts/play.py --process "celeste.exe" --port 5555 --allow-menu
#    (replace 5555 with Thor's LAN IP if not localhost; ZMQ works over TCP)
```

#### Game selection
The checkpoint's `game_mapping` (printed by `serve.py` at startup) lists supported games. From the paper: trained on **Minecraft, Celeste, Cuphead, Isaac, and others**. The tokenizer config (`game_mapping_cfg.src_files`) points to parquet files we don't have locally, but the ckpt embeds the mapping.

**Recommended first game:** **Celeste** (single-player, deterministic, no menus after start, 2D — dxcam works well). Isaac (`isaac-ng.exe`) and Cuphead need the menu-press sequence in `play.py` (already coded).

### 4.4 Linux stand-in (if Windows game unavailable)

If no Windows box is ready, we can **simulate the client loop** on Thor:
- Write a dummy `GamepadEnv` that reads frames from a video file or synthetic generator.
- Connect to the same `serve.py` ZMQ endpoint.
- Measure end-to-end latency, action distribution, and frame-rate.

This validates the serve path without vgamepad/dxcam.

### 4.5 Thor-admit lease plan

| phase | lease label | peak | purpose |
|---|---|---|---|
| serve | `nitrogen-study.serve` | 4 GB | serve.py + model weights |
| (optional) d1-2B | `nitrogen-study.d1dec` | 8 GB | our reflex for comparison |
| (optional) play sim | `nitrogen-study.play-sim` | 2 GB | Linux stand-in client |

Total concurrent peak: **≤12 GB** — trivial on Thor.

### 4.6 Approval checklist for Casey

- [ ] TypeSafe API key (for Autopilot/Jev comparison, not needed for NitroGen alone)
- [ ] Anthropic API key (for Autopilot agent, not needed for NitroGen)
- [ ] Windows box with ViGEmBus + target game installed
- [ ] Thor LAN IP reachable from Windows box (port 5555 open)
- [ ] `hf download` authenticated (HF token with access to `nvidia/NitroGen`)

---

## 5. What we did not verify

| item | status |
|---|---|
| Actual inference latency on Thor (serve.py + DiT 16-step) | **Not measured** — vendor claims only |
| Checkpoint exact size on disk | **Not downloaded** — HF metadata ≈ 2 GB |
| Dataset construction pipeline (controller overlay extraction?) | **Not in repo** — paper says "internet videos", no code released |
| NitroGen on a game not in its `game_mapping` (zero-shot) | **Not tested** — paper says "cannot play completely unseen game" |
| Post-training adaptation to new game | **Not tested** — paper mentions "can be adapted via post-training" |
| Memory under `thor-admit` with concurrent seats | **Not measured** — estimate only |
| End-to-end Windows client latency (dxcam + ZMQ + vgamepad) | **Not measured** |

---

## 6. Summary for the director

**What was asked:** clone NitroGen, read paper, analyse model/dataset/fit/plan, report.  
**What was done:** cloned `--depth 1` to `third_party/nitrogen` (gitignored), read all Python files, read `watching-teachers.md`, `exp-crafter-lab.md`, `autopilot.md`, `tools/d1dec/README.md`. No model downloaded, no serve run.

**Key numbers (all vendor or derived from our code):**
- Model: 500M DiT, SigLIP-Large vision, flow-matching 16-step, 25-dim gamepad (16-step horizon)
- Action space: 2×joystick + 19 buttons (XInput layout)
- Serve/client split: Linux ZMQ server + Windows dxcam/vgamepad client
- Dataset: internet video → gamepad actions (method not in repo; no controller-overlay code)
- Licence: NVIDIA non-commercial research only — allows internal eval, forbids commercial/military
- Thor memory: ~4 GB lease for serve, ~12 GB combined with d1-2B
- HF checkpoint: `ng.pt` ~2 GB (metadata)

**Fit:** NitroGen is a pure system-1 reflex (single frame → 16 actions, no memory). It slots under a system-2 harness exactly as our tile/reflex architecture does: the harness (Autopilot's Jev, our judge/tiles) picks *what* to do; the reflex (NitroGen, d1-2B) executes *how* at 60 Hz. Our d1-2B is faster (32 ms vs ~60–100 ms est.) and local; NitroGen brings gamepad-native actions and multi-game coverage.

**Plan:** download `ng.pt`, serve under `thor-admit` on Thor, play Celeste (or Linux stand-in) from Windows. Needs Casey's Windows box + ViGEmBus + HF token.

**Committed:** this report (`docs/research/nitrogen.md`), `third_party/nitrogen/` (gitignored). No push.