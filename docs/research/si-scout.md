# The scout: what in SuperInstance's 4,492 repos matters to today's work (2026-10-31)

Casey asked for a scout through the SuperInstance collection, "thinking about our projects today". It ran as a funnel (`~/lm-ops/scout/scout.py`):

1. **List:** 5,318 repos, 4,492 of them originals.
2. **Triage:** Groq gpt-oss-20b scored names and descriptions in batches of 60 against today's projects ($0.03).
3. **Read:** for the 668 rated relevant or better, gpt-oss-120b read each README and file tree ($0.24).
4. **Rank:** the DeepSeek library ranked the 48-repo shortlist against everything else it holds ($0.04).

## The ten to pick up

| # | Repo | What it gives us | Where it lands | Maturity |
|---|---|---|---|---|
| 1 | `agent-memory` | Rust episodic, semantic and procedural memory with decay and consolidation | Builders' memory across nights; decaying evidence for the WHY kernel; the tiles' history | Shipped |
| 2 | `voice-reflex-gate` | Hash speech-to-text plus context, match cached reflexes, learn a new reflex after 3 similar requests | **The first mile**, in front of LFM3-Audio's 51 ms path; it is the pincher idea specialised for voice | Prototype |
| 3 | `plato-nervous` | A tiered pipeline: deadband → nano-model → room LoRA → fleet → cloud | The precision cascade's shape, already built as a pipeline | Shipped |
| 4 | `ternary-predict` | Prediction-first perception with an adaptive deadband and an attention budget | Feed the cascade and the scheduler only the surprising events | Shipped |
| 5 | `constraint-schedule` | A CSP scheduler: AC-3, MRV, forward checking, simulated annealing | **The night's plan** as a constraint problem (rails, residency, the model-load cap) instead of hand-rolled admission | Prototype |
| 6 | `cocapn-glue-core` | `no_std` Rust wire protocol (Postcard/msgpack), Merkle provenance, an LRU tile cache | Moving tiles and their provenance between the Thor and the ProArt | Shipped |
| 7 | `tile-neon` | ARM64 NEON BLAKE2b, 64-dim embeddings, cosine top-K | **The tiles' retrieval front on the Thor's Neoverse cores**, the ARM path for `tiles-retrieval` | Shipped |
| 8 | `warp-vote-consensus` | CUDA warp-vote into ternary consensus with a CRDT merge | A fast agreement primitive for many decision models on the GPU (its headline number needs checking) | Prototype |
| 9 | `agent-sync` | Agents simulate their peers to choose act, wait or prepare | Timing in a multi-builder night; pairs with dsswarm's leases | Prototype |
| 10 | `superinstance-api` | A Cloudflare Worker: versioned tiles, embeddings, reflex lookups, budgets, MCP tools | A cloud-side tiles backend, if we put one on Workers next to Clef | Prototype |

## One stack, many repos

The shortlist shows the same pattern as the constraint repos: **six layers, each built several times, with the boundaries between them unstated.**

| Layer | Repos | Notes |
|---|---|---|
| Memory | `agent-memory`, `exocortex-rs`, `hierarchical-memory`, `Equipment-Context-Handoff` | `agent-memory` is the shipped one |
| Scheduling | `constraint-schedule`, `agent-sync`, `agent-polyrhythm`, `meta-agent` | The first two are complementary |
| Consensus | `warp-vote-consensus`, `fleet-coordinate`, `smartcrdt-fleet-sync`, `holonomy-consensus` | |
| Tiles | `mavis-tile-pipeline`, `tile-refiner`, `tile-cuda`, `tile-neon`, `cocapn-schemas` | A pipeline, a preprocessor, two hardware paths and a format |
| Transport | `cocapn-glue-core`, `baton-router`, `flux-a2a-prototype`, `agent-handshake-rs` | Wire format, delivery, message set, session |
| Runtime | `flux-core`, `flux-cuda`, `flux-opcodes`, `si-runtime-wasm`, `lau-agent-runtime` | A VM, a GPU port, an ISA, a browser port, a self-compiling variant |

A one-page map naming each layer's canonical repo would make the collection usable by a new agent, ours included.

## Claims to check before relying on them

- `warp-vote-consensus`: ~0.8 µs per round for 10,000 agents. `fleet-coordinate` claims 38 ms for consensus. These are three orders of magnitude apart; they are likely measuring different things.
- `tile-cuda`: 10 B cosine comparisons/s on an RTX 4050. `flux-hdc`'s C baseline is 5.5 B/s. Neither has been measured on the Thor; `ct-thor` covers flux-hdc.
- `constraint-gpu-kernels`: 341 B constraints/s. Reconcile it with the other checkers' figures.
- `ternary-quantize`: "28 GB FP32 → 1.7 GB while preserving accuracy". The accuracy is not quantified.
- `plato-nervous`: "> 90 % handled by the deadband". No dataset is named.
- `flux-core`: "deterministic execution across agents". The test suite is not described.

## Three questions for the crew

1. `warp-vote-consensus` (0.8 µs) and `fleet-coordinate` (38 ms): **are they measuring different things, or is one of them wrong?**
2. `tile-cuda`'s 10 B/s vs `flux-hdc`'s 5.5 B/s: **which is the reference for the tiles fast path, and has either run on the Thor's Neoverse cores, where `tile-neon` lives?**
3. **Is there a document naming each layer's canonical repo** (memory, scheduling, consensus, tiles, transport, runtime)? If not, which repo should a new agent start from?
