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
