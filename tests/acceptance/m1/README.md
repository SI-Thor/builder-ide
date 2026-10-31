# M1 acceptance — the session script, as an executable test

M1 is *"one evening, one night, one morning, one builder, one room"*
(`docs/plan.md` §2). This directory turns that session into a headless
driver that plays it step by step — the evening (planning with one
builder), a simulated night, and the morning (the report, the branch
choice, one in-game computer call) — **asserting each step's outcome and
its latency budget from the experience spine** (`budgets.py`; spec v2 §4.1
and the plan's §6 measures table), and marking each step **stub / real**
in its output.

**Rewired to the integrated core** (branch `m1-real`): the seats are the
merged `core.*` packages — `siblings.load()` imports them from this tree,
the recipe store rides the spine's **one ledger** through the real
`RecipeStoreSeam`, ask-mode writes its rows straight into that log through
`core.ports.SpineLedgerPort`, and the mirrors are gone. **The render rungs
and the merge gate's engine half now run on the core's engine seam**
(`core/engine`, behind the **fake engine** — `seats/engine.py` holds the
one configuration line), so pointing the session at a real engine is
configuration, not rewiring. What the rewiring exposed in the core is
fixed there, with tests; what is still a stub is listed below with the
exact missing piece.

## Run it

One venv for the repo (the seats need no separate one anymore):

```sh
.venv/bin/python -m pytest tests/acceptance/m1 -q   # as a test
.venv/bin/python tests/acceptance/m1/driver.py      # headless; prints the step table
```

The table (also written to `run/<timestamp>/steps.txt`):

```
STEP                               CLK             MS  BUDGET BACKEND                                      RESULT
-----------------------------------------------------------------------------------------------------------------
evening/cold-open                  Talk           0.2      2s real:cold-start+real:core-api(ledger)        PASS
evening/slate                      Workshop       9.5     30s real:core-api                                PASS
night/sealed-bet-crates            —              17.7       — real:core-api+real:core-recipe(seam)+fake:... PASS
night/kill-9                       Watch          81.6       — real:core-api                                PASS
morning/computer-call              Workshop      14.1     20s real:core-api+real:core-recipe(registry)     PASS
...
M1 session played end to end: 30 steps, 30/30 passed.
```

## The session, and where each step is served from

The **spine** is the core's FastAPI service (`core.api` + `core.svc`),
driven over HTTP through Starlette's in-process `TestClient` — a real §4.2
client. Everything else is the merged core's own code, on the same one
ledger:

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
| `night/sealed-bet-crates` | the crates bet on the spine: typed call commits through the recipe seam, seal → render → `verdict@scripted` critic → hit; **gate (c)**: `prediction.sealed` strictly before `job.enqueued` | — | core-api + core-recipe(seam) + fake engine(render) + stub critic |
| `night/sealed-bet-racks` | the racks bet: critic misses (`wrong_scale`), scored not hidden, task reverted | — | core-api + core-recipe(seam) + fake engine(render) + stub critic |
| `night/wo-attempt` | stub engineer delivers, the merge gate passes (licence scan, budget audit, engine rungs — the rebuild check really byte-compares through the seam), `landed` with preview + evidence before the owner is notified | — | core-api + stub engineer + fake engine(gate rungs) |
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

One tree, one ledger. Every seat below is the merged package; the step
table's `real:*` labels point at it.

| seat | package | what it serves here |
|---|---|---|
| the spine | `core.api`, `core.svc`, `core.store` | the whole §4.2 surface over HTTP: call, work orders, questions, slate/tasks, night + pre-flight, budget, report, branches/apply (which scores the night's taste bets and moves the world), vocab, seal, tally, taste, assets, SSE — and the SQLite ledger the kill -9 test actually closes and reopens |
| recipe store | `core.recipe` behind `core.svc.recipes.RecipeStoreSeam` | Fjellvik as a typed recipe **in the one log**; vocabulary-validated edits; the node registry (§1.4.0) that the two-referent test resolves through; the branch flip as a pointer move — the spine's `/v1/branches/{id}/apply` reports `recipe_sync: ok` because the seam really moved the store |
| vocabulary | `core.vocab` | the three words (data + schemas), the call door's refusals, sealed predictions with the confidence gate, and the Prop-maker's scripted loop as the night's reference implementation |
| cold start | `core.coldstart` | the opener (computed from counts in the one log) and ask-mode (≤ 6, sequential, skip writes nothing) — its rows land directly in the spine's ledger through `core.ports.SpineLedgerPort` |
| the engine | `core.engine` behind the **fake engine** | the render rungs and the gate's engine half through the seam: the door's `render_job` renders the **committed version** via `Engine.render_preview`, and the spine's `gate_engine` port is `EngineGateEngine` — whose deterministic-rebuild rung really byte-compares two generated stages. The fake is deterministic in the whole request and its bytes say `fake-engine` inside themselves; `seats/engine.py::SPEC` is the one line a real engine changes |
| night runner | `core.night` | the reference night for the kill -9 parity check: rails, graduated throttle, detach-or-deadline, heartbeats, the computed status line |
| why kernel | `core.why`, `core.justification` | merged, not yet load-bearing in this session — M1's "why?" is the provenance one-tap, which the spine serves; goal-chains belong to a later morning |
| USD backbone | `builder_usd` | present on the tree (its tests run in the suite) but not in this session — M1's render rungs run on the fake engine by design (plan §2 M1 risks). It plugs in where the fake engine stands, through `/v1/world/scene`'s 501 seam |

**Still a stub — each with the exact missing piece** (labelled `stub:` in
the step table):

* `stub:critic` — the verdict. Missing: a chosen, calibrated critic model
  (week 3 item 18); until then every verdict wears `verdict@scripted`
  (RV patch 15). The *render* under it is the seam's (`fake:engine`);
  only the verdict is scripted.
* `stub:engineer(aider-local)` — the work order's deliverable. Missing: the
  engineer adapter behind the attempt loop (the bake-off's pick, wired to
  the local lane).

**No longer a stub** — the render rungs and the gate's engine rungs. They
run on the core's engine seam (`core/engine`) behind the **fake engine**,
labelled `fake:engine(render)` / `fake:engine(gate-rungs)` in the step
table — the honest label for "the real seam, a fake engine". Missing piece,
named: a real engine adapter (`infinigen-1x` or `infinigen-2-procfunc`)
pointed at the infinigen-thor checkout — **configuration** in
`seats/engine.py::SPEC` (`core.engine.registry.open_engine`), not code.

**One bridge remains** (`bridge:runner-half`, `night/cut-at-the-bar`): the
80% bar's cut is performed as the runner's action by the driver — real
spine writes, but the night runner's own queue loop (`core.night`'s
iterator) is not the thing driving this session's queue. Missing: the
runner resident in the core process, working the spine's queue.

**Also honest**: `night/reference-loop` runs the vocabulary seat's
Prop-maker on its own in-memory world — real vocab code on the seat's own
test seams (its `SchedulerPort` is engine-side; INTEGRATION.md keeps it
that way), never on the spine's write path. And `night/kill-9`'s parity
check runs night-runner's reference night on its in-memory ledger for the
same reason — the spine's ledger is the log of record.

## Layout

```
budgets.py       the spine's latency budgets, with citations
siblings.py      loads the integrated core's packages (core.*) — one tree
spec_client.py   SpecClient (§4.2 over HTTP) + CoreDoor (the resident core's own hands;
                 the door's render_job renders through the engine seam)
session.py       the step recorder: outcome, budget, backend, per-step table
seats/           the thin adapters that remain: cold-start's ledger routing,
                 the recipe seat over the seam, the vocab loop's world, the
                 engine seat (one configuration line), the lane telemetry
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
* **The engine is the fake one, and the bytes say so.** The seam
  (`core/engine`) is the real code — the door renders the committed
  version through `Engine.render_preview`, the gate byte-compares real
  stage generations — but the engine behind it is the deterministic fake.
  Its artifacts name `fake-engine` inside themselves, so nothing on this
  run can be mistaken for a render that came off the box.
* **There is one ledger.** The spine's SQLite store is the only store; the
  recipe seat's commits, ask-mode's rows and the melt's seals all land in
  it. The two DRIFTS this run used to carry are resolved at the source
  (the shipped Fjellvik document loads unchanged; `SpineRecipeLedger` is
  the single writer's path). What the rewiring exposed in the core is
  fixed there with tests — see the commits on `m1-real` and
  `tests/test_integration_melt_ledger.py`: the seam's branch context (a
  night's call committed onto main), the session-id collision, the
  vocabulary's seal dialect invisible to the spine's fold, the gate blind
  to the spine's scored events, apply neither scoring taste bets nor
  moving the world.
* The calibration batch is filed as the queue's third item and cut at the
  bar — the M1 beat. Its internals (seeded-defect members, the FP/FN
  table) are week-2 item 12, tested in the `cold-start` seat's suite.
* `run/` is scratch, gitignored. `.siblings/` is gone — nothing is
  materialized from branches anymore.
