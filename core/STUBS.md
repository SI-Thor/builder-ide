# STUBS — what this branch stubbed, and the contract the real seats must keep

The `why-kernel` branch attaches justification (the vendored WHY kernel,
`core/why`) to the spec's records **behind the spec's interfaces**. Three
sibling seat branches — `core-api`, `core-recipe`, `vocab` — own the real
records; until they land, `core.justification` reads these stubs. Each stub
models only the fields justification reads, under the spec v2 field names
(`docs/design/core-spec.md`).

| Stub file | For seat branch | Stubbed names | Stub-only deltas |
|---|---|---|---|
| `core/api/__init__.py` | `core-api` | `Actor`, `WorkOrder`, `Task`, `Asset`, `WoState`, `TaskState` | two — below |
| `core/recipe/__init__.py` | `core-recipe` | `RecipeEntry`, `RecipeVersion`, `Branch` | one — below |
| `core/vocab/__init__.py` | `vocab` | `VocabularyEntry` | none |

## The contract

`core.justification.graph.build_graph(records)` needs exactly this, from
whatever the real seats provide:

1. **Goals**: each plan goal with a stable id, its intention text, a state,
   the branches it owns, and (optional) a soft-expiry date.
2. **Branches**: id, purpose, protected flag, and — for WO branches — the
   creating actor's `via` naming the `wo_` id.
3. **Recipe versions**: for each branch, its head version's entries, each
   entry's `path` and `assets` (the `ast_` ids it consumes).
4. **Work orders**: id, title, state, the goal it serves, and its
   `vocabulary_gap`.
5. **Vocabulary**: each word, its status, and `provenance["origin"]`.
6. **Assets**: id and kind.

Anything richer (budgets, attempts, predictions, taste) is deliberately not
read: justification is a *projection over lifecycle facts*, in line with the
spec's §5 rule that the audit log is the source of truth and everything else
folds from it.

## Stub-only deltas (each needs a spec decision on merge)

1. **`Task.state` gains `"dropped"`** — the owner's morning *kill this goal*
   decision. Spec §1.9's `cut` is budget-driven ("dropped at the bar,
   requeued for tomorrow"), which is not an owner kill; nothing in the spec's
   closed Task states records the owner abandoning a goal. Proposal: either
   add `dropped` to Task.state (audited as `night.task.state`), or state that
   kills are attestation-level facts in the justification projection.
2. **`WorkOrder.serves`** — the `task_` id of the goal the order is for. The
   spec relates a WO to the plan only through its context packet
   (`origin.packet`); justification needs the direct link to answer "who/what
   does this order serve". Proposal: `WorkOrder.task: str | None` in the
   spec, or a rule that it is compiled from the packet at file time.
3. **`RecipeVersion.entries`** — the materialized version document
   (spec §1.0 keeps documents as content-addressed blobs under
   `$BUILDER_HOME/recipes/`). The real core-recipe projection must expose the
   same version → entries mapping.
4. **`Task.review_by`** — a soft-expiry date for a goal (the slate
   re-affirms goals each night; an untouched goal should eventually go
   *questionable*, not silently live — the kernel's `review-by` + 30-day
   grace). The spec has no goal-horizon field; without one, goals are
   attested alive with no review date and only explicit kills can question
   them.
