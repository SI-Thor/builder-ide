# builder-ide

A headless agentic game and simulation IDE whose builders are avatars: they work in-world overnight on procedurally generated projects (infinigen-thor) and grow with you.

- Vision and phases: [docs/vision.md](docs/vision.md)
- For agents and Claude sessions: [CLAUDE.md](CLAUDE.md)

## The core service (half A)

The service that owns the audit ledger, the projections and the event
stream. Its design is [docs/design/core-spec.md](docs/design/core-spec.md)
(core-spec v2) — the ledger, the API, and the work orders.

```
core/
  store.py       the store of record: one SQLite file, WAL + synchronous=FULL,
                 one transaction per state change
  fold.py        audit log -> projections; every table is rebuildable by
                 folding the log
  events.py      the closed event-type set (§1.8)
  svc/           one service per lifecycle (work orders, vocab, predictions,
                 taste, nights, budget, questions, tasks, lines, call, report)
  auth.py        token classes carry an actor (§4.1)
  api.py         the FastAPI door: §4.2's endpoints and §4.3's stream
```

Run it:

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
BUILDER_HOME=~/builder-ide .venv/bin/uvicorn core.api:app --port 8080
```

`BUILDER_HOME` holds `core.db`, `artifacts/`, `recipes/`, `sandboxes/`,
`reports/` and `tokens.json`. The dev token registry (`dev-token-casey`,
`dev-token-magnus`, `dev-token-panel`, `dev-token-propmaker`,
`dev-token-companion`) is LAN-only development credentialing; real
per-actor issuance is a later milestone.

Tests:

```sh
.venv/bin/pytest
```

### The seams — what the other half must provide

Half A is complete on its own: the ledger, the projections, the API, the
stream, and the work-order lifecycle. The other half (the recipe store, the
compiler, the engineer adapter) plugs in through four ports in
`core/ports.py`:

| Port | What the other half must provide |
|---|---|
| `RecipeStore` | `commit_edit` (a validated edit becomes a version) and `fast_forward` (a branch's head moves). Until then a vocabulary call returns an uncommitted proposal. |
| `MergeGateEngine` | the engine-dependent rungs of the merge gate (§2.3): deterministic rebuild, render ladder, analytic checks, the critic. Without it the gate fails closed rather than landing unverified work. |
| `Telemetry` | the lane load for the pre-flight. Blind telemetry is `None`, and the pre-flight says so in words rather than guessing. |
| `Power` | the `nvpmodel` mode. Record-only by default: flipping the real box's power mode is an operator decision, not a library default. |

Two endpoints are the other half's doors and answer `501` with the seam
named rather than faking an answer: `/v1/world/scene` (the compiled
glTF/USD manifest — the compiler's) and `/acp/proxy/{attempt}` (the
engineer session — the adapter's).

