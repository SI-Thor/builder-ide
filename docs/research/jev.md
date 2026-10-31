# Jev in builder-ide: cheap typed judgments at runtime and in play

**2026-10-31.** Casey installed the Jev MCP server (`@jkudish/jev-mcp`, MIT; TypeSafe's Jev model behind it) and asked us to use it in our work, at runtime and in play.

**What it is.** Twelve judgment tools that return typed verdicts with probability distributions and a confidence score: `verify`, `screen`, `noul`, `find`, `rerank`, `classify`, `decide`, `compare`, `extract`, `audit`, `review`, `gate`. Calls take about 150–500 ms and cost a fraction of a cent each. It is a cloud model, so it fits B2 (no LLMs on the Thor). It can run over stdio per agent, or as one shared stateless HTTP server (`--http`, bearer token, loopback by default).

**Where it fits.** The core already has places where a judgment is a typed choice among bounded options, which is exactly Jev's shape. It is too slow for anything per tick, and right at human speed: per decision, per request, per night.

## In the product

| Place in builder-ide | Jev tool | What it does |
|---|---|---|
| **The ship's computer: "this / these / here"** (vision §"Calling the computer in-game") | `jev_find` over the candidate objects (selection, camera ray hits, recent history) | Resolves the reference. Its `exists_verdict` says when nothing matches. |
| **"Ask, never guess"** (the same section) | `jev_decide` with its explicit **escape hatch** | An `escaped` answer *is* the computer asking which one you meant. This is the rule we wrote, built in. |
| **Compiling a terse request into a work order** | `jev_extract` + `jev_audit` | Fields (object ids, counts, the load factor, the deadline) pulled verbatim and audited against the conversation before the one-line confirmation. |
| **Tiles: labelling play outcomes** (B2, the system that gets better) | `jev_classify` in batches | Each play record (game log, critic notes, owner keep/undo) gets a win / lose / partial label. These are the training labels for the local decision models, with the probability kept as a soft label. |
| **Tiles: keeping the library clean** | `jev_compare` | Catches near-duplicate tiles written by different cloud authors, and tiles whose description contradicts what they do. |
| **Tiles: the shortlist** | `jev_rerank` | Pre-ranks a large library down to the few candidates the local decision model chooses among at play time. |
| **Sealed predictions** (seal, test, verdict) | `jev_verify` | Checks the builder's sealed claim against the render's critic report and the ledger, and records the verdict with its distribution. |
| **The morning report's honesty** (A4) | `jev_verify` / `jev_compare` | Every claim in the report checked against the ledger rows it cites, so a report cannot say what the night did not do. |
| **Magnus's free input** (A2: he can do it all) | `jev_screen` | Only to keep injected text out of an agent's context, never to limit what he may ask. |

**Rules.**
- **The tools advise; the core enforces.** A Jev verdict is a record with its author (`jev@<model>`), never a silent gate.
- **Low confidence on a consequential call goes to Casey,** with the numbers attached.
- **Send only the evidence the decision needs:** no secrets, and nothing from the taste ledger beyond what A5 allows.

## In our own work (the director and the seats)

- **`jev_gate` before every merge:** the final diff plus the seat's "tests pass" claim, checked against the Thor's verify output.
- **`jev_verify`:** seat summaries against their own `exp-*.md` before numbers reach the top README.
- **`jev_screen`:** fetched pages and other agents' idea dumps.
- **`jev_classify`:** triaging idea dumps against `docs/lab/IDEAS.md` (Part B, killed by fact).

## Next

1. A small adapter in the core (`core/judge/`): Jev behind one interface with a fake for tests. Every judgment is recorded in the ledger with its distribution and cost.
2. Wire the first two: reference resolution plus the escape hatch (the computer), and outcome labelling (tiles).
3. `thor-world`'s MCP server can **proxy** Jev for agents in the world, so a builder's judgment calls are recorded like everything else.
