# OmniAgent (HarryHsing, ICML 2026), triage 2026-11-01

Casey: "has some perception ideas we can learn from too". Director's read of the README (arXiv:2606.19341); no code run.

**What it is.** Apache-2.0. A 7B omni-modal model (Qwen2.5-Omni-7B base; SFT and RL checkpoints on HF) that
answers questions about long videos by *choosing what to look at*: an Observation-Thought-Action loop whose actions
are `get_frames`, `get_audio`, `get_clip` or `answer`. Claimed: beats Qwen2.5-VL-72B on LVBench with 73% fewer
frames. The method went into Qwen3.8-Omni-Flash. The environment is a gym-like `reset`/`step` loop that returns only
raw media (`agent_system/`).

**The four ideas, and where they land for us**

| idea | what it means | ours |
|---|---|---|
| Active perception | look on demand, not watch everything up front | the screen watcher's "when to look" (docs/design/screen-watcher.md); rolling-perception's viewport gating; the playtester looks where the critic is unsure |
| Memory consolidation | each percept becomes a line of text memory, then the raw media is **purged** | exactly our privacy rule (no screen pixels stored): an agent may look, but only its text notes persist. Also the returning human as a "late reader": the letter is consolidated memory |
| Test-time scaling with adaptive stop | a higher turn cap helps, and turns used saturate by themselves | the closing probe budget borrowed from Autopilot; the watcher spends looks only when the rate gate says something is moving |
| TAURA credit to pivotal turns | turn-level entropy steers RL credit to discovery turns | the "teaching moments" idea; but exp-crafter-lab found a random subset beat curated moments, so any use needs that control |

**The use that fits the community goal best:** catching up after absence. A returning human (or the return screen
on their behalf) asks a question ("what did the builders do to the village?"), and an active-perception agent
pulls only the clips and ledger slices that answer it, instead of a replay of everything. The world's spectator
camera plus the ledger is the "video"; `get_clip(t0,t1)` maps onto ledger ranges and snapshots.

**Running it:** a 7B omni model is an LLM-class model, so not resident on the Thor; leased under thor-admit for an
experiment, or through a hosted Qwen3.8-Omni if DeepInfra carries it. Hands-on needs Casey's OK.
**Verdict:** take the ideas now (active looking, consolidate-then-purge, adaptive stop) into the return screen and
the watcher; queue a hands-on catch-up experiment after the community loop is running.
