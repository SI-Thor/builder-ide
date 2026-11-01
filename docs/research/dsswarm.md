# dsswarm 1–3: committing a swarm's work safely (2026-10-31)

Casey shared three chats (`dsswarm1–3.md`, ~55k words) on further optimisations for a swarm of agents sharing the Thor, with the ProArt as the stage. The DeepSeek library extracted them ($0.02). This is the director's sorting.

## The ideas worth keeping

| Idea | Mechanism | Where it lands |
|---|---|---|
| **A shadow conductor** | Run the conductor you trust and the new decentralised loop *side by side* on the same requests; log both; measure whether the new one would have committed the same things before switching | The safe way to adopt any new chooser or scheduler. Our OPE estimators (PR #1) do this offline from logs; a shadow run does it live. Applies to tiles-retrieval, the ecology auction, and any future swarm mode |
| **A deterministic invariant kernel before any learned ranker** | A non-neural gate checks invariants (bounds, conservation, the vocabulary); the model only ranks what passed | The tiles' vocabulary door and the night's rails already do this. **Measure it:** how many d1 calls the kernel saves, and whether it falsely rejects anything (on a hand-labelled set) |
| **One register, two regions:** a committed spine and a speculative field | Committed history is written by one owner; speculation lives beside it and decays with time unless promoted | The ledger is the spine; the daytime world's pre-generated assets (B3, idea4's anticipation) are the speculative field, decaying unless the human's path promotes them |
| **Leases on exclusive actions** | A builder claims an object before acting, so two builders never edit the same thing | A real need once several builders work in one world at once; it pairs with per-agent tokens and thor-admit's lease idea |
| **An indeterminacy score with a hysteresis mode switch** | Score how unsettled a region is (rejection rate, canon sparsity, trajectory entropy); enter exploration above a high mark held for N ticks, leave below a low mark | `core/hysteresis` already provides the switch; the score is the new part, and it is unproven until it predicts something |
| **Stigmergic traces:** typed traces with decay; workers self-select by proximity, within a bounded retrieval radius | Coordination through the environment, not messages | Worth a shadow comparison against the conductor; it contradicts idea5's central conductor, and the shadow run is how to decide |
| **A selector trained on the ProArt's accept/reject history** | The owner's keep and undo become the labels | The tiles' training signal already includes the owner's keep; the cold start is the open question (Q2) |

**On MIG:** the chats propose a 12-SM / 8-SM split. That is consistent with a 20-SM Thor (2,560 CUDA cores at 128 per SM). The library marked MIG false because our box reports it **Disabled**; Disabled means supported-but-off, not absent (see `idea5.md`). It remains Casey's call, in a planned window.

**Metaphor only:** "the clearing house", "the pheromone trail", "the gravity well", "the futures market for world states", "morphological momentum", "the voice diversity thermostat".

## Experiments, under a day each

1. **Shadow conductor:** the existing conductor and a trivial trace store (SQLite with decay) on the same 100 tile requests. Pass: ≥ 80 % agreement on committed tiles, and the trace path's p99 ≤ 1.5× the conductor's.
2. **The invariant kernel before d1:** 200 tile proposals through hand-written invariants first. Pass: ≥ 30 % rejected before d1 is called, and zero false rejections on 50 hand-labelled proposals.
3. **The indeterminacy score:** log one region for a day and test whether the score predicts the next rejection. Pass: rank correlation ≥ 0.4.

## Three checkable questions for the author

1. **The MIG preview on Jetson Thor:** gated by SKU, boot flag or licence, and does a 12/8 SM split exist on the T5000?
2. **The selector's cold start:** how many labelled decisions before it beats a majority-class baseline?
3. **The indeterminacy score:** what exactly is the formula combining rejection rate, canon sparsity and trajectory entropy, and on what data was it validated?
