# builder-ide

A headless agentic game and simulation IDE whose builders are avatars: they work in-world overnight on procedurally generated projects (infinigen-thor) and grow with you.

- Vision and phases: [docs/vision.md](docs/vision.md)
- For agents and Claude sessions: [CLAUDE.md](CLAUDE.md)

## The core service — integrated

The seven seat branches are merged (see [INTEGRATION.md](INTEGRATION.md)
for the record: every stub replaced, every duplicated model reconciled,
every named drift resolved). One tree, one venv, one test run — **831
tests green**. The design is [docs/design/core-spec.md](docs/design/core-spec.md)
(core-spec v2).

| Seat | Branch | Status |
|---|---|---|
| ledger, API, SSE, work orders | `core-api` | merged (b417600) |
| recipe store: versions, branches, typed edits, the recipe hash | `core-recipe` | merged (4b7b136), now `core.recipe` |
| the closed vocabulary, the door, sealed predictions, the Prop-maker | `vocab` | merged (0178d69) |
| the WHY kernel + justification | `why-kernel` | merged (93b3e4c) |
| night, iterator loop, morning report | `night-runner` | merged (494f78d), `core.night` |
| ask-mode, the melt, calibration | `cold-start` | merged (814f962), `core.coldstart` |
| recipe → USD, STEP → GLB | `usd-backbone` | merged (d384671), `builder_usd` |

```
core/
  store.py       the store of record: one SQLite file, WAL + synchronous=FULL,
                 one transaction per state change
  fold.py        audit log -> projections; every table is rebuildable by
                 folding the log
  records.py     the spec's shared records — one definition each (§1)
  events.py      the closed event-type set (§1.8)
  svc/           one service per lifecycle (work orders, vocab, predictions,
                 taste, nights, budget, questions, tasks, lines, call, report)
                 and recipes.py — the recipe store behind the spine's port,
                 its events landing in the ONE ledger
  auth.py        token classes carry an actor (§4.1)
  api.py         the FastAPI door: §4.2's endpoints and §4.3's stream
  recipe/        the recipe store (§1.1–§1.2, §1.4.0)
  vocab/         the closed vocabulary, the call door, the gate (§1.5, §1.7)
  night/         the overnight loop and the computed morning (§1.9, §3.2–§3.4)
  coldstart/     ask-mode, the melt, the calibration batch (§3.5)
  why/           the vendored WHY kernel, justification over the records
  usd/           the compiled-scene backbone: recipe → layered USD, STEP → GLB
```

Run it:

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev,usd]'
BUILDER_HOME=~/builder-ide .venv/bin/uvicorn core.api:app --port 8080
```

`BUILDER_HOME` holds `core.db`, `artifacts/`, `recipes/`, `sandboxes/`,
`reports/` and `tokens.json`. The dev token registry (`dev-token-casey`,
`dev-token-magnus`, `dev-token-panel`, `dev-token-propmaker`,
`dev-token-companion`) is LAN-only development credentialing; real
per-actor issuance is a later milestone.

Tests:

```sh
.venv/bin/pytest          # everything, every seat's suite included
```

### The seams that remain — engine and hardware, not seats

The seat-level seams are closed: a vocabulary call commits through the real
recipe store into the one ledger (`core/svc/recipes.py`), and the runner's
morning report folds the spine's own events. What remains open is the
engine-and-hardware half of §6.2, behind the ports in `core/ports.py`:

| Port | What is still owed |
|---|---|
| `MergeGateEngine` | the engine-dependent rungs of the merge gate (§2.3): deterministic rebuild on infinigen-thor, the render ladder, the calibrated critic. Without it the gate fails closed rather than landing unverified work. |
| `Telemetry` | the lane load for the pre-flight. Blind telemetry is `None`, and the pre-flight says so in words rather than guessing. |
| `Power` | the `nvpmodel` mode. Record-only by default: flipping the real box's power mode is an operator decision, not a library default. |

Two endpoints remain doors that answer `501` with the seam named rather
than faking an answer: `/v1/world/scene` (the compiled manifest per
branch/LOD — the compiler exists as `builder_usd` and its adapter reads
committed versions, but serving the endpoint is §6.2 item 4's build work)
and `/acp/proxy/{attempt}` (the engineer session — the adapter's).

