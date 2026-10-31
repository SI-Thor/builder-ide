# quilt-pincher and builder-ide: how the reflex engine fits

**2026-10-31.** Casey shared a chat about our crew's [quilt-pincher](https://github.com/SuperInstance/quilt-pincher) project (`new1.md`): "one line of ideas with that project … a neat concept that could go many ways". This note is the director's first read. The aider desk is extracting the chat's concrete ideas and proposing experiments; its results get appended below.

## What pincher is

A **reflex engine** (TypeScript, Apache-2.0, built from Quilt cells):

1. **Pinch:** embed the trigger plus its context.
2. **Match:** query a vector store of reflexes for the top K.
3. **Act by score band:**
   - **≥ 0.80:** execute directly;
   - **0.55–0.80:** confirm, then run;
   - **< 0.55:** an LLM *compiles* a new reflex.
4. **Veto:** a sandbox, network and permissions check before anything runs.
5. **Store:** the new reflex joins the store, content-addressed and federated.

The whole engine ships as a portable **`.nail`** bundle: the reflexes, the veto rules, the compile history and the provenance. The same sheet runs in the cloud (Workers), on a workstation and on an ESP32. The selling line: **under 50 ms, no LLM, zero marginal cost** for anything it has seen before.

## It is the front half of what we already built

| pincher | builder-ide today | The fit |
|---|---|---|
| A reflex: an action compiled once by an LLM, then reused for free | **A tile:** a script a cloud LLM writes once, in the typed vocabulary (`core/tiles`) | Same idea. "LLM as compiler" is B2's "the cloud writes the options". |
| Match by **embedding similarity** to the trigger | The chooser picks by **context bucket**, a contextual bandit (`core/tiles/chooser.py`) | Pincher's retrieval is the missing **front**. With a large library, retrieve the top K by meaning first, then let the bandit (which *learns from outcomes*, something pincher's similarity score does not) choose among them. |
| **Three score bands** (execute / confirm / compile) | Hysteresis gate (`core/hysteresis`), the ambiguity gate (PR #2), Jev's escape hatch, the cascade's escalation | The bands are a threshold policy. Ours can hold them steady (split thresholds plus dwell) and *learn* where they belong per task (`lab-cascade` E3). |
| **Veto** (sandbox, network, permissions) | The vocabulary door: characters never run code; tiles are validated against the closed vocabulary | Our door is stricter; pincher's veto is the right shape for reflexes that touch the *host* (files, processes) rather than the world. |
| **`.nail`**: a portable, content-addressed bundle | The tile library is content-addressed; the chooser has weights | **A `.nail`-compatible export of a tile library plus its chooser** would let the same reflexes run on the ProArt's first mile, in a Worker, and offline. |
| **Three tiers** (cloud, workstation, ESP32) | ProArt (first mile), Thor (decision models, assets), cloud (Workers AI: Clef, Jev) | The same tiering, with the Thor as a fourth, heavy tier. |
| Reflex **tensors**: weight, gravity, distance (hot reflexes near, cold far) | Tile scores and retirement; the stage cache's hot/warm/cold | Hot reflexes cached at the first mile, cold ones on the Thor or in the cloud. |

## Where it lands first: the first mile

The ProArt's voice model (`first-mile` spike) needs to answer **in a breath**. Pincher is the layer that makes most answers free:

1. A spoken command is pinched and matched in under 50 ms.
2. **A known command runs at once:** "pause the night", "show me last night", "make these sturdier" when the context is clear.
3. **A near match is confirmed in one line,** which is the computer's existing "ask, don't guess" rule.
4. **A miss goes to the cloud** to compile a new reflex, or becomes a work order. The answer becomes a reflex for next time.

The first mile gets faster the more you use it, which is "builders that grow with you" at the interface level.

## Proposed next steps (for Casey)

1. **Pattern into `core/tiles`** (small, our own code): an embedding-retrieval front over the library, score bands held by the hysteresis gate, and a `.nail`-style export. No new dependency.
2. **Pincher itself in the first-mile prototype:** run `quilt-pincher` (our crew's code, Apache-2.0) as the reflex layer behind the ProArt voice model. **This needs Casey's OK**, because it is a GitHub project outside the approved list. It is our crew's, so the answer is probably yes.
3. **An experiment that settles it:** on the same task sets (`lab-cascade`, the tiles toy, spoken builder commands), compare:
   - bandit only;
   - pincher-style similarity only;
   - retrieval then bandit.

   Measure win rate, latency, and how fast each improves with use.

## The aider desk's extraction of the chat (Hy4, 2026-10-31, $0.07)

**Mechanisms worth keeping** (mapped onto tiles and the first mile):
1. **Embedding match with score bands.** Embed state plus context and take the top K by meaning. Tiles: match the game state to tile embeddings. Voice: match the utterance plus context to cached intents.
2. **Signed, portable `.nail` bundles.** Each tile (script, embedding, capability manifest, signature) is published from the Thor to the ProArt or an ESP32; voice intents are synced from the cloud to the laptop.
3. **A veto/ExecutionGuard with a sandbox:** a schema check plus a capability manifest (WASM/Landlock) before anything touches the world or the host.
4. **Modular traits** (EmbeddingProvider, ExecutionGuard, ReflexRunner), so each tier swaps a local or cloud embedder, the guard and the runner.
5. **A fast-loop cache with a slow-loop auditor.** Low-confidence matches and escalations are logged, and a nightly auditor updates the categories and schema. This is our night, applied to reflexes.
6. **User-scoped vs global caches, with a promotion rule:** personal tiles stay scoped, and only validated ones are promoted. This fits A1/A5 authorship.
7. **An interruption token:** barge-in or a world change cancels the in-flight cloud compile and rolls back the fork.
8. **Fork, prune, commit:** run a candidate tile in a structurally shared fork with fuel metering, and commit only the safe winner. This is our predict, render, keep-or-undo loop.
9. **Program synthesis with gas metering and hot swap:** frequently used tiles are compiled and swapped in without downtime.

**Metaphor only, no testable mechanism:** the viscous, wave, crystal-lattice, superfluid, soliton and "living tissue" passages.

**Three experiments, each under a day.** Each one measures fast-path coverage, reward or accuracy against the bandit, the escalation rate and p95 latency.
- **E1, offline replay over the tiles logs.** Embedding fast path at ≥ 0.80, falling back to the bandit's logged choice. It beats the bandit if it covers ≥ 30 % of contexts, its reward is within ε of the bandit's, and p95 is under 50 ms. The new OPE estimators (PR #1) make this an honest offline test.
- **E2, a live A/B in the world.** Pincher bands plus a WASM-sandboxed compile of new tiles, against the bandit. It also counts sandbox vetoes, which must show zero unsafe executions.
- **E3, a voice first-responder A/B** on 100–200 scripted intents. It beats the bandit if the fast path takes ≥ 50 % of intents at equal accuracy and under 50 ms.

## Part 2 of the chat (`new2.md`): the DeepSeek library's extraction ($0.02)

Part 2 turns from the reflex idea to **Rust systems plumbing**. The new mechanisms, and where each fits:

| Mechanism in new2 | Our reading |
|---|---|
| Telemetry from `/proc` (loadavg, meminfo, the fd count) into a typed `SystemState` | Already being built: **thor-admit** (the Rust admission daemon) reads `MemAvailable` and the load |
| Guest WASM calling **virtualized** host primitives (`get_cpu_load`, `trigger_state_reset`) against a fake state | Good for tiles that touch the host: the veto runs them against a virtual machine state first |
| Cranelift JIT of a validated trace, hot-swapped via `memfd_create` + `mmap` and a pointer flip | Clever, but premature; our tiles are vocabulary scripts, not native code. A seed for much later |
| A reactive cell DAG (Quilt): `StableGraph`, `link_dependency`, BFS cascade; a per-cell logic slot (static / WASM / JIT) | **The same shape as our stage cache's dirty-set** (`core/engine/DIRTY.md`); a cell is a stage. Nothing new to adopt; a good cross-check |
| A double-buffered atomic mailbox (64-byte header, write the inactive slot, `sfence`, release store) | Correct **within one machine's shared memory**. The chat aims it at ProArt → Thor, which share **no** memory (they are on Wi-Fi), so there it is false. Within the Thor (render buffer → critic) it is sound and matches our zero-copy finding |
| A lock-free ring event loop (mpsc 1024 + a task per event) | Standard; fine for the first mile's event intake |

**Metaphor only:** resonant catastrophe, crystalline necrosis, epigenetic methylation, the phylogenetic "evolutionary sieve", skeletal remodelling, "myelination" for JIT hardening.

**Experiments, under a day each:**
- **A mailbox race test** (10⁶ toggles; zero torn reads; p99 handoff under 1 ms).
- **A cascade test:** a compiled trampoline against BFS with an `RwLock`, ≥ 5× at p50. The cycle check must reject a 1→2→1 edge, which the chat's code does not do.

**Three checkable questions for the chat's author** (all are code defects in its own listings):
1. `link_dependency` has no cycle check, despite its comment ("Internal loop checking must happen here…"). Does a 1→2→1 link deadlock the BFS, or double-fire cell 2?
2. The trampoline calls `call_indirect` with a no-argument, no-return signature. What is the calling-convention contract when a target takes arguments?
3. The mailbox's second buffer sits at `base + 64 + stride` (4160 for stride 4096), which is not 64-byte aligned. Was only the header meant to be cache-line isolated?
