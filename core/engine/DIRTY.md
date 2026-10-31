# DIRTY.md — the dirty-set contract: what an edit re-evaluates, what it reuses

Written **before** the first line of the stage cache (plan §3 week-2 item 9:
*"the dirty-set contract written down before the first line of it"*). It is
the contract between three pieces of the core, and every one of them treats
a sentence here as a test:

| granularity | what lives there | the home of the rule |
|---|---|---|
| **entry** | the recipe's own units — what a recipe edit marks dirty | `core/recipe/dirty.py` (§1.1) + the key-drift rule below |
| **stage** | the cache's units — what may be reused, byte for byte | `core/recipe/stagecache.py` (§1.9) + `core/engine/stagecache.py` |
| **graph node / subtree** | the engine's lower layer — what re-executes *inside* a dirty stage | `core/engine/graph.py`, over the engine's canonical graphs |

The one-sentence version: **an edit re-evaluates exactly what its bytes
would change** — the entries whose effective inputs changed, plus the
entries the spec's couplers pull in, and, inside each re-evaluated entry,
the graph nodes that changed plus everything downstream of them. Everything
else is reuse, and reuse is byte-identical or it is a bug.

The evidence this rests on is round 2
(`docs/research/engine-round2.md`): the traced graph is **byte-stable**
across runs, processes and hash seeds (§2 there), and a one-`chosen_idx`
edit is **purely additive at graph level** — +2,698 nodes, 0 removed, 2
shared ids touched — while at execution level only the desk's work runs
(+61 choice calls, +5.5 s of generation, 1,104 of 1,432 profiled functions
with identical call counts — §4 there). The graph diff is not a hope; it
was measured on an 18,725-node scene.

---

## 1. Entry granularity — what a recipe edit marks dirty

A recipe edit (an op list, §1.1) marks an entry dirty if **any** of the
following holds. Dirty entries re-evaluate; the rest are cache hits.

1. **Touched** — an op addressed inside the entry (`touched_entries`;
   `core/recipe/dirty.py`'s first term).
2. **Key drift** — the entry's **effective stage key** changed between the
   base and head documents. The effective key is over the entry's
   *effective inputs*:
   - the entry's own content (`path`, `kind`, `generator`, `params`,
     `constraints`, `assets` — the canonical entry document),
   - its **effective seed**: `entry.seed` when set, else
     `recipe.seeds[<first path segment>]` (the fallback every engine
     adapter on this seam uses to resolve a seed — `venv2.trace`'s rule),
   - the **engine pin** (whole: repo, commit, config hash, blender,
     python), and
   - its **dep-keys** — the stage keys of the entries it is coupled to
     (term 3 below). A coupled entry whose coupling changed is a different
     stage even though its own content did not move.
   Key drift is the safety net under the op-shape rules: **content
   decides, not the shape of the ops that got there.** An edit that
   changes `recipe.seeds.terrain` dirties the terrain entry even though no
   op was addressed inside it, because the effective seed — and therefore
   the bytes — changed. An engine-pin edit (the explicit swap, X R9)
   dirties **every** entry: the pin is in every key.
3. **Coupled** — the spec's three cross-entry couplers (`core/recipe/
   dirty.py`, §1.1): entries whose constraints reference nodes inside
   touched entries; entries consuming assets produced by touched entries;
   downstream compile stages whose declared dep-keys include a touched
   entry's stage key. A coupled entry re-evaluates *and* its own stage key
   carries the coupling (as a dep-key), so two different couplings never
   alias one cache slot.

An entry with no generator (`asset_ref` and its kind) has no stage and is
never dirty in its own right.

## 2. Stage granularity — what may be reused

* **A hit skips the stage entirely.** The engine is not called for it; the
  cached bytes are the stage's bytes. This is the whole point: the 534 s
  coarse stage nobody touched must not run again because a sibling entry
  gained a crate (plan item 9).
* **A hit is byte-identical to re-evaluation** (§1.9's invariant). The
  cache stores the stage's artifact hash and verifies it on every read; a
  mismatch is an **integrity error** (rebuild, never serve, never silently
  regenerate). Byte-identity is not an assertion about engines in general:
  it holds because the key is a function of the recipe version alone (RV
  patch 13 — no wall-clock, no hostname, no ambient config reaches the key
  or the bytes) *and* because the engines on this seam keep it: the fake
  by construction, v2 because the traced graph is normalized to
  byte-stability (`venv2.normalize_graph`, round 2 §2). **Render outputs
  are not stage-cache promises** — Cycles' GPU accumulation moves pixels by
  ±1 LSB (round 1 §5.4) — stages are byte-stable, previews are not.
* **Two key spaces, one home for the arithmetic** (`core/recipe/
  stagecache.py`):
  - the **content key** (`entry_stage_key`): an entry's stage, keyed on
    its effective inputs — *stable across recipe versions*, which is what
    makes "an entry nobody touched keeps its cache slot" true;
  - the **request key** (`stage_cache_key` over the recipe version hash —
    what `expected_stage_key` verifies an engine reported, contract rule
    4): the identity of one *request*, which any edit changes.
    The cache is addressed by content keys; the engine-reported request
    key is recorded beside the bytes as provenance. A per-entry stage
    request names its stage `entry:<path>` so two entries' requests are
    never the same key for different bytes.
* **Reuse verdicts** are the spec's `Job.stage_cache` closed set:
  `hit` (cached; engine skipped), `miss` (generated in full), `partial`
  (stage-level miss, subtree-level reuse — the graph-edit path of §3).
  Hit rate is a first-class nightly measure (P §6-2; reported from the
  cache's own counters, per session).

## 3. Node and subtree granularity — what re-executes inside a dirty stage

The Infinigen 2.0 adapter emits the **canonical graph** per generation
(`RANDOM_CONTROL` trace, normalized byte-stable). The core stores it by
hash beside the recipe — graphs are megabytes and two versions share most
of one — and diffs two of them (`core/engine/graph.py`):

* **node diff** — by node id: `added`, `removed`, `changed`. A changed
  node that grew by referencing an added node is a **join point** (round
  2's `_operator.add` where the desk's objects join the room's lists); a
  changed node with no reference to an added node is a **re-bound id**
  (round 2's positional tail artifact — the one shared id that is a
  bookkeeping artifact, not a semantic change).
* **the dirty subtrees** — `added ∪ removed ∪ changed`, plus **every
  transitive consumer** of those (the `$ref` edges' downstream). That
  closure is what re-executes: nothing outside it can produce different
  bytes, because a dataflow node's value is a function of its inputs.
* **what the closure means, per mechanism**:
  - a **graph-edit engine** (`reexecute` capability, contract rule 5):
    re-execute the closure only — splice the edited nodes into the base
    graph and evaluate the dirty subtrees. The seam's `reexecute` carries
    the ops and the base stage; the engine owns the splicing.
  - a **re-tracing engine** (the venv boundary today): the closure is the
    *marginal* work — round 2 measured it at scene scale (+5.5 s of
    generation for the desk against 21.6 s shared; 1,104 of 1,432
    functions with identical call counts). The stage still re-traces as a
    unit; the closure is the honest statement of what that re-trace
    *adds*, and the measurement the night's budget line needs.
  - **splice-safety**: a diff with removals or re-bound ids is not
    splice-safe — the mechanism falls back to full re-evaluation of the
    stage rather than guessing what a re-bound id means. (The round-2
    desk diff has one re-bound tail id: honest verdict — re-trace the
    stage, execute the desk subtree.)
* **why sibling reuse is sound — RNG scoping** (round 2 §1.4): v2 draws
  every grammar decision from `spawn`ed child generators (independent
  bit-streams), so a draw not consumed at trace time can shift only its
  own child's later draws. An edit inside one subtree cannot cascade into
  a sibling choice; that is the property the closure relies on.
* **what the graph cannot promise** (round 2 §1.4, stated again so nobody
  leans on it too hard): the traced graph is a *structural* recipe —
  grammar and composition exactly, placement approximately (trace-time
  optimistic assumptions). Render-time culling can still drop objects the
  graph contains, and adding an object changes light transport everywhere
  (the mean-3.4/255 GI ripple). The closure bounds **execution**, not
  physics.

## 4. What may never be reused

1. **A stage whose key inputs changed** — that is what the key *is*; the
   engine swap test (the standing gate) checks the extreme case: one pin
   edit changes every key, so the cache invalidates honestly instead of
   serving work built under different settings than the pin promises.
2. **A base stage another engine flavour produced** (contract rule 5):
   `reexecute` interprets only its own lower layer. A v1 blob or a fake
   digest is not a v2 graph, and the refusal names the flavour.
3. **Bytes that fail their hash** — integrity error, rebuild. A cache
   that served unverifiable bytes would be a second, worse problem.
4. **Nothing else.** Eviction (below) removes entries; it can never
   change correctness, because a recompute of the same key is the same
   bytes.

## 5. Eviction — by size, LRU, never by invalidation

Entries are content-addressed, so they never *invalidate* — they only get
**evicted**: after each write the cache enforces a byte budget,
evicting least-recently-used entries first (the just-written entry
excepted). Access order is bookkeeping in the entry's metadata; it is not
part of the key and cannot affect hits. Eviction statistics are reported
with the hit rate.

## 6. Where the scene server helps (and where it cannot)

Hits skip the engine outright — no process, warm or cold, is asked
anything. **Misses and partials** are where residency helps: through the
same seam, a resident engine (`core/engine/resident/`, plan item 15)
holds the scene, so the re-execution lands in a process that already paid
the launch tax, and a kill is a replay rather than a loss. What residency
does not change is this contract: the resident is a derived cache, never
a writer (§1.9's hard rule), and its stage keys are these same keys.

## 7. The contract's mechanical checks

Each sentence above that can be checked is checked, in
`tests/engine/test_graph.py`, `tests/engine/test_stagecache.py` and
`tests/engine/test_regen.py`:

- a hit is byte-identical to re-evaluation (fake and graph-runtime
  doubles), and the engine is *never called* for a hit;
- a sibling edit does not dirty an untouched entry (key drift covers the
  `recipe.seeds` fallback);
- a pin edit dirties every entry and changes every key;
- the node/subtree diff reproduces round 2's shape on an additive edit:
  join point grown, closure ⊇ added ∪ consumers, splice-safety verdict
  honest about removals and re-bound ids;
- a base stage from another flavour is refused by `reexecute`;
- eviction by size keeps the budget and never evicts the just-written
  entry; a corrupted entry is an integrity error, not a stale serve;
- the whole flow runs through the engine seam — including the resident
  engine, where the scene is warm.
