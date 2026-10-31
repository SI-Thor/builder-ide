# M1 acceptance — the session script, as an executable test

M1 is *"one evening, one night, one morning, one builder, one room"*
(`docs/plan.md` §2). This directory turns that session into a headless
driver that plays it step by step — the evening (planning with one
builder), a simulated night, and the morning (the report, the branch
choice, one in-game computer call) — **asserting each step's outcome and
its latency budget from the experience spine** (`budgets.py`; spec v2 §4.1
and the plan's §6 measures table), and marking each step **stub / real**
in its output.

Nothing here merges anything. The core's parts that are not on `main` yet
live on sibling branches; `siblings.py` materializes them with
`git show <branch>:<path>` into a gitignored scratch dir and imports them
behind thin adapters, so that **after the seats merge onto `main`, only the
adapters change** — the session script stays as it is.

## Run it

```sh
cd tests/acceptance/m1
python3 -m venv .venv                        # once
.venv/bin/pip install "pydantic>=2.7,<3" "fastapi>=0.115" "httpx>=0.27" "pytest>=8"
.venv/bin/python -m pytest . -q               # as a test
.venv/bin/python driver.py                   # headless; prints the step table
```

The table (also written to `run/<timestamp>/steps.txt`):

```
STEP                               CLK             MS  BUDGET BACKEND                                      RESULT
-----------------------------------------------------------------------------------------------------------------
evening/cold-open                  Talk           0.2      2s real:cold-start+bridge:spine-ledger          PASS
evening/slate                      Workshop       9.5     30s real:core-api                                PASS
night/sealed-bet-crates            —             17.7       — real:core-api+real:core-recipe(seam)+stub:... PASS
night/kill-9                       Watch         81.6       — real:core-api                                PASS
morning/computer-call              Workshop      14.1     20s real:core-api+real:core-recipe(registry)     PASS
...
M1 session played end to end: 30 steps, 30/30 passed.
```

## The session, and where each step is served from

The **spine** is `core-api`'s FastAPI service (branch `core-api`,
materialized), driven over HTTP through Starlette's in-process `TestClient`
— a real §4.2 client. Everything else plugs into it or runs beside it:

| step (act/name) | what it asserts | budget | served by |
|---|---|---|---|
| `boot/fresh-home` | a fresh `$BUILDER_HOME` holds only the boot's own events | — | core-api |
| `boot/recipe-seat` | Fjellvik created as a recipe; the node registry derived and published into the spine | — | core-recipe + vocab's shipped document |
| `boot/vocabulary` | the three slice words active; capability rows carry zero denominators | — | vocab (data) + core-api |
| `evening/cold-open` | the zero-denominator opener ("0 of 0"), no adjective about the owner, exactly one offer of four seeds with seeds on their faces | Talk ≤ 2 s | cold-start (computed from the spine's ledger) |
| `evening/pick-a-starter` | the picked starter is the world's terrain seed | Talk ≤ 1.5 s | core-recipe |
| `evening/ask-mode` | ≤ 6 two-chip questions, strictly sequential (a second collapses into the slate), a skip writes nothing, every answer an owner-written taste row mirrored into the spine | Talk ≤ 1.5 s per answer | cold-start + core-api taste ledger |
| `evening/slate` | two bets slated with `[e]` asks, the WO line exists from night one, one bar with counters, `$0.00 (local)`, capability rows | Workshop ≤ 30 s | core-api |
| `evening/work-order-call` | one referent group → draft (question XOR draft); the confirm line carries **both** price lines (a one-line estimate is a build failure — slice gate (f)) | Workshop ≤ 20 s | core-api |
| `evening/propmaker-limit` | `lids: true` refused at the door and audited; the order carries the vocabulary gap | — | core-api + vocab's schema |
| `evening/work-order-confirm` | go → queued; a doubled Go is one Go (idempotency) | Talk ≤ 2 s | core-api |
| `evening/handoff` | night running; the pre-flight names lane, queue and detach rule, and proposes nothing when the lane is free | Watch ≤ 10 s | core-api |
| `night/reference-loop` | the Prop-maker's loop on the cold world: guess-sealed world bet, taste claim refused by the gate, hollow crates 7/11 to the library, question parked not decided, seal seq < enqueue seq | — | vocab (its own ledger) |
| `night/sealed-bet-crates` | the crates bet on the spine: typed call commits through the recipe seam, seal → render → `verdict@scripted` critic → hit; **gate (c)**: `prediction.sealed` strictly before `job.enqueued` | — | core-api + core-recipe(seam) + stub render/critic |
| `night/sealed-bet-racks` | the racks bet: critic misses (`wrong_scale`), scored not hidden, task reverted | — | core-api + core-recipe(seam) + stubs |
| `night/wo-attempt` | stub engineer delivers, the merge gate passes (licence scan, budget audit, engine rungs), `landed` with preview + evidence before the owner is notified | — | core-api + stub engineer/gate |
| `night/heartbeats-and-rails` | ticks, spend against the bar, the 80% graduation computed, the per-model load cap at its cap | — | core-api |
| `night/cut-at-the-bar` | the calibration batch (queue item three) is cut at the 80% bar and requeued — named, never dropped | — | core-api + the runner half |
| `night/peek` | cold join is a ledger replay ≤ 5 s, a card legible ≤ 5 s, rewind free, never fast-forward past the head | Watch ≤ 5 s | core-api (SSE) |
| `night/kill-9` | **gate (a)**: a real close and reopen; the feed renders from the ledger alone, complete to the last seal; parity with night-runner's resume | Watch | core-api (+ night-runner parity) |
| `night/stop` | the kill switch answers ≤ 2 s; the status line is computed and one of the four | Talk ≤ 2 s | core-api |
| `morning/report` | **gate (d)** (a fresh client after the kill): status line leads, failure line always present, the cut named, numbers with the load count, all sections, **no single prediction score**, text mode the same read | Watch ≤ 3 s | core-api |
| `morning/branch-flip` | the two standing exits present from night one; the flip ≤ 2 s | Watch ≤ 2 s | core-api + core-recipe(seam) |
| `morning/branch-apply` | apply is a head move ≤ 10 s and the recipe store follows (`recipe_sync: ok`) | Workshop ≤ 10 s | core-api + core-recipe(seam) |
| `morning/landed-wo-keep` | the card shows landed with preview + evidence; keep promotes crates v2 (lids, rope handles) in one transaction | Talk ≤ 2 s | core-api |
| `morning/tally` | 2 sealed · 1 hit · 1 miss with denominators per builder × claim type | — | core-api |
| `morning/why` | the why-card ≤ 1 s: provenance (seed, model), complete licence row with dependency terms, the seal and verdict one tap away | Talk ≤ 1 s | core-api |
| `morning/computer-call` | **gate (b)**: "make these sturdier" over crates + stalls → a question naming both, never a plan | Workshop ≤ 20 s | core-api + core-recipe registry |
| `morning/question-answer` | the parked question answered in one tap, idempotently | Talk ≤ 2 s | core-api |
| `morning/decisions` | the morning asked ≤ 10 decisions (it asked 3); the three-number line | — | core-api |

The plan's M1 slice gates map to steps, not a separate suite: **(a)**
`night/kill-9`, **(b)** `morning/computer-call`, **(c)**
`night/sealed-bet-crates` (plus the reference loop), **(d)** every morning
read goes through the client recreated after the kill, the cold-open test
`evening/cold-open`, the question budget `evening/ask-mode`.

## The seats, and what is real

| seat | branch | status per its own README | what it serves here |
|---|---|---|---|
| the spine | `core-api` | in progress | the whole §4.2 surface over HTTP: call, work orders, questions, slate/tasks, night + pre-flight, budget, report, branches/apply, vocab, seal, tally, taste, assets, SSE — and the SQLite ledger the kill -9 test actually closes and reopens |
| recipe store | `core-recipe` | done or near | Fjellvik as a typed recipe; vocabulary-validated edits; the node registry (§1.4.0) that the two-referent test resolves through; the branch flip as a pointer move — reached from the spine through the `RecipeStore` seam (`recipe_sync: ok`) |
| vocabulary | `vocab` | done or near | the three words (data + schemas), the call door's refusals, sealed predictions with the confidence gate, and the Prop-maker's scripted loop as the night's reference implementation |
| cold start | `cold-start` | done or near | the opener (computed from counts) and ask-mode policy (≤ 6, sequential, skip writes nothing) |
| night runner | `night-runner` | done or near | the reference night: rails, graduated throttle, detach-or-deadline, heartbeats, the computed status line — parity-checked against the spine's status after the kill |
| why kernel | `why-kernel` | done or near | materialized (its `core.why` + `core.justification`) but not yet load-bearing in this session — M1's "why?" is the provenance one-tap, which the spine serves; goal-chains belong to a later morning |
| USD backbone | `usd-backbone` | done or near | **not materialized** — it needs the `usd-core`/`build123d` wheels, and M1's render rungs run on the stub generator by design (plan §2 M1 risks). It plugs in where `stub_render` stands, through `/v1/world/scene`'s 501 seam |

**Stubs the plan expects** (all labelled `stub:` in the step table): the
render rungs (deterministic bytes — same seed, same bytes; the engine
spike replaces them), the scripted critic (`verdict@scripted` on its face,
per RV patch 15), the stub engineer behind the merge gate, and the stub
gate engine (core-api's own seam).

**Bridges** (labelled `bridge:`) — real code on both sides, joined here:
ask-mode rows mirrored into the spine's taste ledger; the recipe seat
committing the spine's typed calls and following its branch applies; the
runner-half actions at the bar (the 80% cut). These are the seams that
disappear when the seats share one store.

## Layout

```
budgets.py       the spine's latency budgets, with citations
siblings.py      git show <branch>:<path> → scratch import (no merges, ever)
spec_client.py   SpecClient (§4.2 over HTTP) + CoreDoor (the resident core's own hands)
session.py       the step recorder: outcome, budget, backend, per-step table
seats/           one thin adapter per sibling branch + the stubs
driver.py        the session script itself (acts 0–3); `main()` runs it headless
test_m1_session.py   the pytest wrapper (plays the script, asserts the gates)
conftest.py      a fresh $BUILDER_HOME per run
```

## Honest notes (what this run is and is not)

* **The latencies are in-process microseconds.** The budgets pass trivially
  today; they are kept because they are the regression gate for the day
  real services, models and renders stand behind the same interfaces —
  a step that is honest but late, or fast but fabricated, is equally a
  failure (plan §6).
* **There are more ledgers than one.** The spine's SQLite ledger is the
  only one the panels read; the recipe seat and the vocab reference loop
  run on their own (the seats are not merged yet). The bridges above are
  the visible seams. After integration, one store.
* **Cross-seat drifts found by this session** (also in
  `seats/recipe.py::DRIFTS`): vocab's shipped Fjellvik document writes
  entry kind `prop` where spec §1.1 and core-recipe say `prop_set`;
  core-recipe's `SQLiteLedger` connection is thread-bound, so the seat
  runs on its conforming `InMemoryLedger` (an artifact of the in-process
  TestClient). Both are merge-time decisions, not quiet fixes.
* The calibration batch is filed as the queue's third item and cut at the
  bar — the M1 beat. Its internals (seeded-defect members, the FP/FN
  table) are week-2 item 12, tested on the `cold-start` branch.
* `run/` and `.siblings/` are scratch, gitignored; `.siblings/` rebuilds
  when a branch head moves (the run's first note pins every seat's commit).
