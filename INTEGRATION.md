# INTEGRATION — seven seats, one green main

The record the brief asked for: what conflicted in each merge and how it
was resolved toward `docs/design/core-spec.md` (v2), every stub replaced,
every duplicated model reconciled, the m1 acceptance run's drifts
resolved, and what still deviates from the spec.

Final state: branch `integrate-core`, seven `--no-ff` merges, one
`pyproject.toml`, one venv, one pytest run over everything — **all green**
(every seat's suite kept, plus integration tests where stubs used to be).

| # | Seat | Merge commit | Package |
|---|---|---|---|
| 1 | core-api | `b417600` | `core.store`, `core.fold`, `core.svc`, `core.api` |
| 2 | core-recipe | `4b7b136` | `core.recipe` (was `core/src/builder_recipe`) |
| 3 | vocab | `0178d69` | `core.vocab` |
| 4 | why-kernel | `93b3e4c` | `core.why`, `core.justification` |
| 5 | night-runner | `494f78d` | `core.night` |
| 6 | cold-start | `814f962` | `core.coldstart` |
| 7 | usd-backbone | `d384671` | `builder_usd` (`core/usd/src`) |

Provenance note: the first three merges and the why-kernel merge
*resolution* (renames, `core/records.py`, the import fixups) were left
uncommitted by the previous agent when its provider quota ran out; that
work was verified, completed (three of its defects fixed — see §1) and
committed as merge 4. Merges 5–7 and everything after are this session's.

## 1. What conflicted, and the resolution

**why-kernel (merge 4)** — the seat shipped stub packages (`core.api`,
`core.recipe`, `core.vocab` stand-ins, contract in its `STUBS.md`) plus a
recipe-store rename (`core/src/builder_recipe` → `core.recipe`) that
collided with the stub package of the same name. Resolved toward the spec:
the real packages win, the stubs are deleted, `STUBS.md` is deleted (its
four stub-only deltas are decided below), and the rename stands with every
import fixed. Three defects in the inherited resolution were fixed before
committing: `Night.power_mode` is `int` per §1.9 (the caller passed
`None`); `Branch`/`NodeRef` are unfrozen (the recipe store's fold moves
`head` and flips `purpose` in place — §1.0's log-is-the-truth rule);
`VocabularyEntry` keeps the provenance validator and the spine's door
stamps `origin: "builtin"` rather than trusting the poster (§1.5).

**night-runner (merge 5)** — no code conflicts, but four same-named test
files were *different tests* (`test_budget`, `test_models`, `test_ledger`,
`conftest.py`): the seat's suite moved whole into `tests/night/` (the vocab
seat's convention), which also solves the `ledger`/`night` fixture-name
clash with the root conftest.

**cold-start (merge 6)** — housekeeping conflicts only (`.gitignore`,
`pyproject.toml`); the seat's tests were already namespaced
(`tests/coldstart/`).

**usd-backbone (merge 7)** — `.gitignore` only. The seat's own
`pyproject.toml` was deleted per the brief's one-pyproject rule; its wheels
ride as a `usd` extra on the root project.

## 2. Every stub replaced (each README's list, checked)

**why-kernel** (`STUBS.md`, deleted): the justification layer reads the
real records — `Task`/`Branch`/`WorkOrder`/`Asset` from `core.models`,
`RecipeVersion`/`RecipeEntry` from `core.recipe`, `VocabularyEntry` from
`core.vocab`. Its four stub-only deltas, decided toward the spec:

1. `Task.state` gains `dropped` — the owner's morning kill. §1.9's `cut` is
   budget-driven ("requeued for tomorrow"), which is a deferral, not a
   kill; the justification projection needs the difference. Audited as
   `night.task.state`.
2. `WorkOrder.serves` — the `task_` id the order answers. The spec relates
   an order to the plan only through its packet; justification needs the
   direct link, and the packet cannot carry it (it is captured before the
   order exists).
3. A version's entries are **not** on the `RecipeVersion` record: §1.0
   keeps documents as content-addressed blobs, so the justification
   projection materializes `version_entries` from the store.
4. `Task.slated_at` / `Task.review_by` — the goal horizon the attestation
   anchors to ("alive since…", questionable after review-by + grace). The
   spec has no goal-horizon field; this is the minimal extension, and it
   is the spec's own soft-expiry pattern.

**night-runner** (its README's seam table): the records and the event set
re-export from `core.records` (the try/except bridge to a sibling that no
longer exists is gone; an assert pins the runner's event groups to the
shared closed set). What stays a stand-in *on purpose* — engine-side work
no seat provides: `ScriptedExecutor`, `ScriptedCritic`, the variant
sources, the null power meter, and the presence/lane callables. Its ledger
seam keeps conforming in-memory/SQLite stand-ins for its own tests; the
spine's store is the log of record.

**cold-start** (its README's stub table): `stubs.py` no longer stubs —
hashing, clocks, the taste fold and the sealer resolve to the vocabulary's
real modules, `Rail` to `core.records`; the in-memory ledger remains as
the unit-test seam. The table's contracts are now asserted in code: the
melt threshold *is* the vocabulary gate's (`gate.py` pins
`MELT_AT == MIN_OBSERVATIONS_TO_ACT_ALONE == MIN_OBSERVATIONS_TO_SPEAK_TASTE == 2`),
and there is one canonical form (`core.canon`). Its eight stub-only deltas:
#1 (guess below two observations) follows decision 13a as the seat built
it; #2 attribution rides in taste-row tags (`asked-by:<builder>`); #3
`line.spoken` is *the* utterance type for evening moments too; #4 the skip
stays session-local (a skip writes nothing); #5 reference members are
recipe fragments until the engine lands; #6 FP/FN semantics as tested;
#7 the clamp was never load-bearing (sizing asks `fits`) — the shared
`Rail` won; #8 `q_` ids stay shared with parked questions.

**vocab** (its README's seam section): `RecipeStorePort` resolves to the
real store through the spine (below); `LedgerPort`'s in-memory
implementation stays as the Prop-maker loop's test seam; `SchedulerPort`
waits on the night runner's executor (engine-side).

**usd-backbone** (its README's seam section): `BuilderRecipeSource` reads
committed versions from the merged `core.recipe`; the availability probe
points at the merged package; the adapter test that used to skip ("the
recipe store is not on this interpreter's path") is now a real commit-and-
read-back check. `StubRecipeSource` stays — it is the CLI's JSON input
path, not a stub awaiting a seat.

**The spine's own seam** (`core/ports.py::RecipeStore`): no longer
`UnavailableRecipeStore`. `core/svc/recipes.py` implements the port over
the real store, and `SpineRecipeLedger` routes the store's appends into
the spine's ONE audit log, so `edit.proposed` / `version.committed` /
`branch.*` land in the same SQLite file as everything else and fold into
the same projections.

**Integration tests where stubs used to be** (the brief's named examples):

- `tests/test_integration_vocab_store.py` — a vocab call goes through the
  real door into the real recipe store and lands an event in the real
  ledger; the edit is validated against the vocabulary's own schema; a
  second store over the same log folds to the same world (§5.2 step 1).
- `tests/test_integration_night_report.py` — a night's report renders from
  real ledger events: an evening written by the spine's own services,
  folded by the runner's projection, with the computed status line (§3.4)
  and the identical page after a cold reopen (§5.4).
- `tests/test_integration_usd.py` — the compiled scene comes from the
  committed recipe: the compiler's hash equals the store's committed
  `root_hash`, and re-emission is byte-identical (§7.11).

## 3. Duplicated models reconciled

`core/records.py` is the single home for every record §1 names that more
than one seat wrote. Where two seats disagreed, the richer definition —
the one carrying the spec's validators — won, and the loser's extra
defaults were folded in so neither seat's construction sites break. The
seat modules (`core.models`, `core.events`, `core.recipe.models`,
`core.vocab.models`, `core.night.models`, `core.coldstart.models`)
re-export, so every import path still resolves and
`core.models.Actor is core.records.Actor` is true exactly once.

| Record | Decision |
|---|---|
| `Actor` | frozen (all seats agreed); the seven §1.8 kinds |
| `AuditEvent` | the spine's — optional `seq` until commit, the `refused` flag, the type check, the subject accessors |
| `Rail` | night-runner's arithmetic on the three agreed axes |
| `Task` | §1.9's fields + justification's `slated_at`/`review_by` + the `dropped` state (decisions 1, 4 above) + the cost model's `kind`/`ask_source`/`ask_basis` (the ask is priced from the measured model, and a client's own number is recorded as an override) |
| `Job`, `Night`, `IterationPolicy` | night-runner's (`Night.power_mode: int`, the iteration policy rides the night); the spine's `start()` passes `state="running"` explicitly, as the runner's own `start()` does |
| `Branch`, `NodeRef` | **unfrozen** — projection records the folds mutate in place; §1.0's "the log is the source of truth" is the invariant, not record immutability |
| `Recipe`, `RecipeEntry`, `EnginePin`, `Op`, `RecipeEdit`, `RecipeVersion` | the recipe seat's (frozen, with the validators: pinned config hash, ≤32 ops, ≤80-char one-line message, dotted ≤3-segment paths) |
| `Prediction` | frozen, with the §1.7 validators (claim ≤120, basis carries denominators never %, namespace follows claim_type); `prediction_seal_hash` takes the raw fields so the hash is computed *before* the frozen record is built |
| `TasteNote` (the ledger row) vs `EntryTasteNote` (the §1.5 aggregate) | the spec defines two classes of the same name; both exist, each under its unambiguous name, with aliases where a seat used the bare name |
| `VocabularyEntry` | vocab's, with the provenance-origin validator |
| Canonical JSON / hashing | one module (`core.canon`); the seats' copies were byte-identical and are now re-export shims. `builder_usd.canonical` keeps its float quantisation but delegates the serializer — no package can drift on the bytes a hash is taken over |
| The closed event set | one `EVENT_TYPES` in `core.records`; the recipe and night seats' group constants survive as documentation of *who writes what*, pinned by assert |

## 4. Payload spellings unified (the log is one, its dialects are not)

§1.8 closes the event *types*, not their payload keys — and the seats had
grown three dialects. Each is now either unified at the writer or read
bilingually with the drift named at the read site:

- **Taste rows** ride in `payload["row"]` — the vocabulary and cold-start
  folds' spelling; the spine's writer, fold, erase-redaction and the
  runner's kept-owner count were changed to match (one spelling, one log).
- **Recipe events** (`version.committed`, `branch.created`,
  `branch.head.moved`): the recipe store's spelling is canonical for the
  recipe projections; both folds (the spine's `core.fold` and the store's)
  read or skip the other's spelling explicitly, so one log feeds both.
- **Night events** (`night.started`, `night.task.state`, `budget.spend`,
  `prediction.*`): the spine addresses rows through the event *subject*
  and nests documents; the runner writes flat keys. The runner's
  projection reads both, with the drift documented in
  `core/night/projection.py`.

## 5. The m1 acceptance run's DRIFTS, resolved

From `m1-acceptance:tests/acceptance/m1/seats/recipe.py::DRIFTS`:

1. *vocab's shipped Fjellvik document writes entry kind `prop` where spec
   §1.1 and core-recipe say `prop_set`* — fixed at the source
   (`core/vocab/seed.py`); the document loads into the real store
   unchanged, and the acceptance adapter's compat translation is the thing
   that should now be deleted there.
2. *the recipe seat runs on `InMemoryLedger`, not `SQLiteLedger`
   (thread-bound connection vs the spine's HTTP worker)* — resolved by
   routing, not by un-binding: `SpineRecipeLedger` puts the recipe store's
   appends into the spine's lock-guarded SQLite store, which is the single
   writer §1.0 demands. The recipe seat's own `SQLiteLedger` remains for
   its own tests.

The run's wider finding — *"there are more ledgers than one"* — is closed
by the same mechanism plus the two remaining in-memory ledgers being
explicitly test seams (vocab's and cold-start's), never on the spine's
write path.

## 6. What still deviates from the spec

Honest list, per seat and in general:

- **The spine's `RecipeStoreSeam` is opt-in.** `Core.open` does not wire it
  by default (the service's tests construct it explicitly), so a bare
  `Core` still answers a vocab call with an uncommitted proposal until the
  caller provides the store. Making it the default needs the boot sequence
  to seed the vocabulary's schemas — boot-time wiring, not merge work.
- **`/v1/world/scene` still answers 501.** The compiler exists and reads
  committed versions, but serving the manifest per (branch, LOD) with
  `since_version` deltas is §6.2 item 4's build work; the endpoint keeps
  naming its seam rather than faking a shape.
- **The engine is not here** (by design — it is infinigen-thor's repo):
  render rungs, the merge-gate engine, the warm scene server, the
  scheduler's GPU stations and the night's executor/critic are scripted
  stand-ins behind their seams; `verdict@scripted` is on their faces.
- **The shipped §1.5 words do not compile to USD yet.** `builder_usd`'s
  entry vocabulary covers placements and materials; `props.harbor.crates`'
  count/style params need the crates generator (engine-side, §6.2). The
  compiler's own fixture compiles, deterministically, from the real store.
- **Cold-start's deltas #1–#8** (above) stand as the seat built them,
  pending the spec amendments they propose (notably §1.7's gloss of
  `guess` vs decision 13a's two-observation regime).
- **The plan slate refuses a plan that does not fit.** §3.2.1 says the
  builders cut their own lists first and that recovery is a proposal, never an
  error; the API's slate now *refuses* at the door — starting a night on a
  slate the rails cannot cover is a `Refused` with the cut named, and the
  slate is left as it was so the recovery is a trim and a try again. The
  night's own behaviour is unchanged: it still cuts and re-queues. This is
  the brief's ask, and it is the last gate before the box spends anything.
- **The slate's asks are priced, and a client's number is an override.**
  §3.2.1 stores the ask so the morning can name what was cut, but says
  nothing about where it comes from: the cost model prices it now (the task
  names a job kind; the p50 is the ask and the p95 the rail), and a number
  filed by a client is kept as an **override** — recorded on the task
  (`ask_source`, `ask_basis`) and shown on the slate beside the model's own
  price. The `Task` record gained `kind`, `ask_source` and `ask_basis` for
  this; the table in §3 records the extension.
- **`docs/lab/` notes keep their historical voice** — they describe the
  spikes as run, including "the store is not merged" statements that were
  true at the time; the package READMEs are the living documents.
- **Not merged here:** `m1-acceptance` (another seat was still writing it)
  and `melt-week`, per the brief's list.

## 7. Verifying

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev,usd]'
.venv/bin/pytest           # 831 tests: every seat's suite + the integrations
```
