# `core/vocab` — the vocabulary seat of builder-ide's core

Week 1 item 5 of `docs/plan.md`: *three vocabulary words + the Prop-maker
scripted loop + sealed predictions with the confidence gate*.

Everything here implements `docs/design/core-spec.md` (v2). Each module's
docstring cites the section it implements; the citations are the contract.

```
core/vocab/
  models.py       the spec's records: VocabularyEntry, Prediction, RecipeEdit, AuditEvent…
  hashing.py      canonical JSON and content hashes (spec §1.0)
  schema.py       the §1.5 param-schema subset, and the validation of a call's params
  words.py        the three words of the M1 slice
  taste.py        the taste ledger's read side: rows → per-entry aggregates
  seed.py         the seeded world: Fjellvik, Casey's taste rows, the Prop-maker's earlier bets
  registry.py     the words, the entry paths, the capability view
  call.py         the door: a character's typed call, validated or refused
  predictions.py  sealing a bet: the hash, the immutability, the three-writer rule
  gate.py         the confidence gate: when a builder may speak, and when it may act alone
  projections.py  derived views over the audit log
  propmaker.py    the Prop-maker's scripted loop (D §23:04)
  ports.py        the seams to core-api and core-recipe
  stubs.py        in-memory implementations of those seams
  clock.py        RFC 3339 UTC, injectable
```

## The three words

Spec §6.1 names them, and this is the vocabulary of one room — Fjellvik's
harbour — that a builder would actually use on one evening. The Prop-maker
owns all three (T: "props, materials, scale, wear").

| word | kind | params |
|---|---|---|
| `props.harbor.crates` | prop | `count 1–48`, `style enum[plain, weathered, stained]`, `from_library 0–count`, `seed` |
| `props.harbor.racks` | prop | `count 1–24`, `length_m 0.5–6` |
| `material.wood.weathering` | material | `wear 0–5`, `tone enum[pale, gray, dark]` |

Each is **typed and bounded** (its `params` is a schema from the §1.5
subset), and each carries **taste notes** and **provenance**. The taste notes
are the aggregate of the owner's own decisions about that entry — Casey's
thirteen seeded rows, folded by reason code with the denominator kept
(`4/4 kept`, `0/2 kept`) — not adjectives written by hand. A note without a
denominator would be a fabrication, and the whole project is against that.

## The loop

`propmaker.py` is D §23:04's fish-crate bet, scripted — no LLM yet, which the
slice allows (§6.1). The rules the LLM will have to obey are all in place:

1. **Edit** — a typed vocabulary call. Out of schema is refused at the door.
2. **Predict and seal** — the bets are hashed into the ledger *before* the
   render job exists (§5.1). The seal hash covers `render_spec` too, so a
   verdict is re-scorable against the same inputs (X R7).
3. **Preview** — the render is enqueued *after* the seal; the ledger refuses a
   `job.enqueued` that references an unsealed bet.
4. **Critic** — a scripted critic, deterministic in the seed, whose card says
   `verdict@scripted` on its face (RV patch 15).
5. **Act** — keep or revert as a **critic verdict plus an audited branch op**,
   never a taste write (§1.7; X C5). The taste bet stays open until the owner
   acts.

The **confidence gate** decides the last step. A builder with fewer than two
prior observations on the axis may **bet** (sealing is always allowed) but may
not **decide**: the branch does not move and the question is parked. That is
the cold start (G §1 20:44) and the melt after it, and both are exercised.

In Fjellvik the loop seals two bets — `material_read` on `2/3 hit` and
`taste_keep` on `4/4 kept` ("Casey keeps 8 of 12 crates") — the hollow crates
fall back to the library, and the owner's morning scores the taste bet
`partial`. On night one it seals a `guess`, refuses the taste claim, and parks
the question.

## The seams, and exactly what was stubbed

`ports.py` holds the protocols; `stubs.py` holds in-memory implementations.
The protocol docstrings carry the invariants each real implementation owes.

**`LedgerPort` — core-api's (branch `core-api`):** the append-only audit log.
Stubbed: `append` (gapless `seq`, idempotent replay, the **sealed-before-render
guard**), `head_seq`, `events(since_seq, types)`, `find`. Not stubbed: the
SQLite store and WAL, the projections table, SSE `/v1/events`, the HTTP API,
the taste export/erase/ratify endpoints, the tally API.

**`RecipeStorePort` — core-recipe's (branch `core-recipe`):** the recipe store.
Stubbed: versions, branches, `apply_edit` (with the vocabulary's validator
injected, so the store asks the vocabulary whether a touched entry's params
are still inside its schema, §1.1), the **recipe hash** (`sha256` over the
canonical JSON), and `move_head` (fast-forward only). Not stubbed: the
dirty-set contract and partial regeneration, the node registry, constraint
checking beyond the vocabulary schema, the recipe → USD/glTF compile.

**`SchedulerPort` — a third seam the brief does not name.** The preview step
needs a job door (§1.9), and the job's enqueue is the event that must come
after the seal. It belongs to core-api's night runner; stubbed here as
`enqueue_render` + `job`.

## Deviations from the spec

1. **`docs/understanding.md` does not exist in this branch.** The brief points
   at it for "the vocabulary, sealed predictions and the Prop-maker". It is
   not in the tree (the plan calls it `synth-u/UNDERSTANDING.md`, "not present
   when this was written"). The spec, the plan and the research documents the
   spec cites — `docs/research/ux-day.md` §23:04 for the loop, and
   `docs/research/ux-trust.md` for the taste ledger and the utterance rules —
   were used instead.
2. **`x-cross-field`, one extension to the §1.5 subset.** The spec's own slice
   word needs it: `props.harbor.crates` has `from_library 0–count`, a bound a
   static `maximum` cannot express. The subset's other rules are enforced as
   written.
3. **A third seam** (`SchedulerPort`) beyond the two the brief names — see
   above.
4. **No HTTP layer here.** `core-api` owns the API (spec §4.2). This seat
   provides the service layer the endpoints call: `VocabularyService.call` is
   what `POST /v1/vocab/call` does, `PredictionService.seal` is what
   `POST /v1/predictions/seal` does. `GET /v1/predictions/tally` is not
   implemented; `fold_predictions` and `ObservationCounts` are the read path it
   would sit on.
5. **The stub recipe store keeps the recipe as plain canonical JSON**, not as
   typed models — `core-recipe` owns `Recipe`, `RecipeEntry` and `EnginePin`,
   and duplicating them here would only create a second definition to
   reconcile at merge time. The stub also does **not** write the store's own
   audit events (`edit.proposed`, `version.committed`); those belong to the
   real store's write path, so a night in this seat logs `vocab.call`,
   `prediction.*`, `job.enqueued`, `critic.verdict`, `question.parked` and
   `branch.head.moved`, but not `version.committed`.
6. **`Prediction` is frozen in full.** The spec says `sealed_at` is immutable
   and that the bet cannot be edited after; freezing the whole record is the
   stricter reading and the simpler one. The verdict is written to the log,
   never to the record.
7. **The taste gate is scoped to the word as well as to the reason code.** The
   spec says "per reason code"; a claim about the crates is also measured on
   the crates, so its denominator is about the thing it claims about. Without
   the scoping, a crates claim would be answered by the owner's keeps of every
   busy thing in the project.
8. **`Actor.kind` carries §1.8's seven kinds** (`owner`, `character`,
   `engineer`, `critic`, `core`, `scheduler`, `client`); §1.1's four are the
   subset allowed to author a recipe edit, and `RecipeEdit` enforces that.
9. **The scripted critic's numbers are its own rule.** It reproduces D §23:04's
   *shape* — 10 kept, 2 reverted to the library — but its geometry count is
   10/12 where D §23:04 says 9/12, and the two hollow crates are the ones D
   names (7 and 11). The rule is deterministic in the seed, so a night is
   replayable.

## Running it

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[test]"
./.venv/bin/python -m pytest
```

111 tests, no network, no GPU: the slice's whole point is that the loop, the
ledger and the words can be exercised before the engine lands.
